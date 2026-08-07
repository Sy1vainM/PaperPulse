"""Tests for the public-release privacy gate."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "check_public_release.py"


def _load_checker() -> ModuleType:
    """Load the privacy checker without installing a package."""
    spec = importlib.util.spec_from_file_location("check_public_release", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CHECKER = _load_checker()


class PublicReleaseTests(unittest.TestCase):
    """Verify that private runtime files and values block a public release."""

    def test_reject_private_runtime_paths(self) -> None:
        self.assertIsNotNone(CHECKER._is_forbidden_tracked("config.yaml"))
        self.assertIsNotNone(CHECKER._is_forbidden_tracked("digests/2026-08-07.md"))
        self.assertIsNone(CHECKER._is_forbidden_tracked("config.example.yaml"))
        self.assertIsNone(CHECKER._is_forbidden_tracked("digests/.gitkeep"))

    def test_detect_personal_home_path_without_storing_one(self) -> None:
        private_path = "/" + "Users" + "/alice/Documents/private"

        findings = CHECKER._scan_text("example.md", private_path)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].reason, "personal home-directory path")

    def test_allow_empty_and_placeholder_fields(self) -> None:
        text = 'database_id: ""\nvault_path: "<your-vault>"\napi_key: "${PAPER_API_KEY}"\n'

        self.assertEqual(CHECKER._scan_text("config.example.yaml", text), [])

    def test_detect_populated_private_field_and_token(self) -> None:
        private_field = "database_id" + ": " + "1234567890abcdef"
        token = "sk-" + ("A" * 20)

        findings = CHECKER._scan_text("config.example.yaml", private_field + "\n" + token)

        self.assertEqual(len(findings), 2)


if __name__ == "__main__":
    unittest.main()
