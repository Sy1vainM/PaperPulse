#!/usr/bin/env python3
"""Reject tracked files that could expose private PaperPulse runtime data."""

from __future__ import annotations

import argparse
import logging
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence


LOGGER = logging.getLogger("paperpulse.privacy")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_EXACT = {
    "config.yaml",
    "last_run.json",
    "seen_papers.json",
    "config/mcporter.json",
}
PRIVATE_FIELD_PATTERN = re.compile(
    r"^\s*(database_id|vault_path|api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*(.*?)\s*$",
    re.I | re.M,
)
HOME_PATH_PATTERN = re.compile(r"/(Users|home)/([^/\s]+)/")
TOKEN_PATTERN = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{16,}|xox[baprs]-[A-Za-z0-9_-]{16,})",
    re.I,
)
SAFE_HOME_NAMES = {"user", "username", "example", "your_name", "your-name"}


@dataclass(frozen=True)
class Finding:
    """Describe one release-blocking privacy issue without exposing its value."""

    path: str
    reason: str
    line: Optional[int] = None


def _is_forbidden_tracked(path: str) -> Optional[str]:
    """Return a reason when a tracked path belongs only to private runtime state."""
    normalized = path.strip("/")
    if normalized in FORBIDDEN_EXACT:
        return "private runtime file is tracked"
    if normalized.startswith(".runtime/"):
        return "local connector runtime is tracked"
    if normalized.startswith("digests/") and normalized != "digests/.gitkeep":
        return "generated digest is tracked"
    if normalized.startswith("logs/") and normalized != "logs/.gitkeep":
        return "runtime log is tracked"
    name = Path(normalized).name
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return "environment file is tracked"
    if Path(normalized).suffix.lower() in {".pem", ".p12", ".pfx"}:
        return "credential file is tracked"
    return None


def _is_placeholder(value: str) -> bool:
    """Return whether a configuration value is intentionally non-secret."""
    normalized = value.split("#", 1)[0].strip().strip('"\'').lower()
    return (
        not normalized
        or normalized in {"...", "none", "null", "changeme", "placeholder"}
        or normalized.startswith(("${", "<", "your_", "your-", "example"))
    )


def _line_number(text: str, offset: int) -> int:
    """Return a one-based line number for a text offset."""
    return text.count("\n", 0, offset) + 1


def _scan_text(path: str, text: str) -> list[Finding]:
    """Find private paths and populated credential-like fields in tracked text."""
    findings: list[Finding] = []
    for match in HOME_PATH_PATTERN.finditer(text):
        if match.group(2).lower() not in SAFE_HOME_NAMES:
            findings.append(Finding(path, "personal home-directory path", _line_number(text, match.start())))
    for match in PRIVATE_FIELD_PATTERN.finditer(text):
        if not _is_placeholder(match.group(2)):
            findings.append(
                Finding(path, f"populated private field: {match.group(1).lower()}", _line_number(text, match.start()))
            )
    for match in TOKEN_PATTERN.finditer(text):
        findings.append(Finding(path, "token-like credential", _line_number(text, match.start())))
    return findings


def _tracked_files(root: Path) -> tuple[str, ...]:
    """Return Git-tracked paths using the index as the public release boundary."""
    completed = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return tuple(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)


def _read_index_file(root: Path, relative_path: str) -> bytes:
    """Read the exact staged blob that a commit would publish."""
    completed = subprocess.run(
        ["git", "show", f":{relative_path}"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return completed.stdout


def _history_blobs(root: Path) -> tuple[tuple[str, str], ...]:
    """Return unique reachable Git blobs and their first recorded path."""
    completed = subprocess.run(
        ["git", "rev-list", "--objects", "--all"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    blobs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for line in completed.stdout.splitlines():
        object_id, _, path = line.partition(" ")
        if not path or object_id in seen:
            continue
        object_type = subprocess.run(
            ["git", "cat-file", "-t", object_id],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if object_type == "blob":
            seen.add(object_id)
            blobs.append((object_id, path))
    return tuple(blobs)


def audit_repository(root: Path) -> list[Finding]:
    """Audit staged paths and blobs without logging sensitive values."""
    findings: list[Finding] = []
    for relative_path in _tracked_files(root):
        forbidden_reason = _is_forbidden_tracked(relative_path)
        if forbidden_reason is not None:
            findings.append(Finding(relative_path, forbidden_reason))
            continue
        try:
            payload = _read_index_file(root, relative_path)
        except (OSError, subprocess.CalledProcessError) as error:
            findings.append(Finding(relative_path, f"unable to read staged file: {error.__class__.__name__}"))
            continue
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(_scan_text(relative_path, text))
    return findings


def audit_history(
    root: Path,
    blobs: Optional[Sequence[tuple[str, str]]] = None,
) -> list[Finding]:
    """Scan reachable historical blobs so deleted secrets still block release."""
    findings: list[Finding] = []
    history_blobs = tuple(blobs) if blobs is not None else _history_blobs(root)
    for object_id, path in history_blobs:
        completed = subprocess.run(
            ["git", "cat-file", "-p", object_id],
            cwd=root,
            check=True,
            capture_output=True,
        )
        payload = completed.stdout
        if b"\0" in payload:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        history_path = f"history:{path}@{object_id[:8]}"
        findings.extend(_scan_text(history_path, text))
    return findings


def build_parser() -> argparse.ArgumentParser:
    """Build the release-audit command line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT, help="Repository root to audit")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the privacy audit and return non-zero when release must stop."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    root = args.root.expanduser().resolve()
    try:
        history_blobs = _history_blobs(root)
        findings = audit_repository(root) + audit_history(root, history_blobs)
    except (OSError, subprocess.CalledProcessError) as error:
        LOGGER.error("Unable to audit repository: %s", error.__class__.__name__)
        return 2
    if findings:
        for finding in findings:
            location = f"{finding.path}:{finding.line}" if finding.line is not None else finding.path
            LOGGER.error("%s: %s", location, finding.reason)
        LOGGER.error("Public release blocked with %d privacy finding(s)", len(findings))
        return 1
    LOGGER.info(
        "Public release privacy audit passed for %d staged files and %d historical blobs",
        len(_tracked_files(root)),
        len(history_blobs),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
