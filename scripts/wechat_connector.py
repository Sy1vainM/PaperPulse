#!/usr/bin/env python3
"""Stable PaperPulse entry point for WeChat discovery through Exa MCP."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence
from urllib.parse import urlparse


LOGGER = logging.getLogger("paperpulse.wechat")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = PROJECT_ROOT / ".runtime" / "connectors"
MCPORTER = RUNTIME_ROOT / "mcporter" / "node_modules" / ".bin" / "mcporter"
AGENT_REACH = RUNTIME_ROOT / "agent-reach-venv" / "bin" / "agent-reach"
MCP_CONFIG = PROJECT_ROOT / "config" / "mcporter.json"


def _validate_runtime() -> None:
    """Raise a clear error when the private connector runtime is incomplete."""
    missing = [path for path in (MCPORTER, AGENT_REACH, MCP_CONFIG) if not path.exists()]
    if missing:
        formatted = ", ".join(str(path.relative_to(PROJECT_ROOT)) for path in missing)
        raise FileNotFoundError(f"Missing connector runtime files: {formatted}")


def _run(command: Sequence[str]) -> int:
    """Run a connector command with predictable cwd and error propagation."""
    LOGGER.info("Running connector command: %s", command[0])
    completed = subprocess.run(command, cwd=PROJECT_ROOT, check=False)
    return completed.returncode


def _mcporter_call(tool: str, payload: dict[str, object], timeout_ms: int) -> int:
    """Invoke one Exa MCP tool using a JSON payload."""
    command = [
        str(MCPORTER),
        "--config",
        str(MCP_CONFIG),
        "call",
        tool,
        "--args",
        json.dumps(payload, ensure_ascii=False),
        "--output",
        "json",
        "--timeout",
        str(timeout_ms),
    ]
    return _run(command)


def check_connector(_: argparse.Namespace) -> int:
    """Validate local binaries, configuration, and remote Exa tool discovery."""
    _validate_runtime()
    commands = (
        [str(AGENT_REACH), "--version"],
        [str(MCPORTER), "--version"],
        [str(MCPORTER), "--config", str(MCP_CONFIG), "config", "doctor"],
        [str(MCPORTER), "--config", str(MCP_CONFIG), "list", "exa", "--schema"],
    )
    for command in commands:
        return_code = _run(command)
        if return_code != 0:
            return return_code
    return 0


def search_wechat(args: argparse.Namespace) -> int:
    """Search WeChat public-account pages through Exa."""
    _validate_runtime()
    query = args.query.strip()
    if not query:
        raise ValueError("Search query must not be empty")
    if "mp.weixin.qq.com" not in query:
        query = f"site:mp.weixin.qq.com {query}"
    payload: dict[str, object] = {
        "query": query,
        "numResults": args.num_results,
    }
    return _mcporter_call("exa.web_search_exa", payload, args.timeout_ms)


def fetch_wechat(args: argparse.Namespace) -> int:
    """Fetch one explicit WeChat public-account article through Exa."""
    _validate_runtime()
    parsed = urlparse(args.url)
    if parsed.scheme != "https" or parsed.netloc != "mp.weixin.qq.com":
        raise ValueError("URL must be an https://mp.weixin.qq.com article")
    payload: dict[str, object] = {
        "urls": [args.url],
        "maxCharacters": args.max_characters,
    }
    return _mcporter_call("exa.web_fetch_exa", payload, args.timeout_ms)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Validate the local runtime and Exa MCP")
    check_parser.set_defaults(handler=check_connector)

    search_parser = subparsers.add_parser("search", help="Search WeChat public-account pages")
    search_parser.add_argument("query")
    search_parser.add_argument("--num-results", type=int, choices=range(1, 21), default=5)
    search_parser.add_argument("--timeout-ms", type=int, choices=range(1000, 120001), default=60000)
    search_parser.set_defaults(handler=search_wechat)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one explicit WeChat article")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--max-characters", type=int, choices=range(1000, 50001), default=12000)
    fetch_parser.add_argument("--timeout-ms", type=int, choices=range(1000, 120001), default=60000)
    fetch_parser.set_defaults(handler=fetch_wechat)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the selected connector operation."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (FileNotFoundError, ValueError) as error:
        LOGGER.error("%s", error)
        return 2
    except OSError as error:
        LOGGER.exception("Connector execution failed: %s", error)
        return 1


if __name__ == "__main__":
    sys.exit(main())
