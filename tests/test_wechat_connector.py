"""Unit tests for the stable WeChat connector entry point."""

from __future__ import annotations

import argparse
import importlib.util
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock, patch


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "wechat_connector.py"


def _load_connector() -> ModuleType:
    """Load the connector script without requiring it to be a package."""
    spec = importlib.util.spec_from_file_location("wechat_connector", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONNECTOR = _load_connector()


class WeChatConnectorTests(unittest.TestCase):
    """Verify query normalization and strict fetch boundaries."""

    @patch.object(CONNECTOR, "_mcporter_call", return_value=0)
    @patch.object(CONNECTOR, "_validate_runtime")
    def test_search_adds_wechat_domain(
        self,
        _validate_runtime: Mock,
        mcporter_call: Mock,
    ) -> None:
        args = argparse.Namespace(query="新智元 多模态", num_results=3, timeout_ms=60000)

        result = CONNECTOR.search_wechat(args)

        self.assertEqual(result, 0)
        mcporter_call.assert_called_once_with(
            "exa.web_search_exa",
            {"query": "site:mp.weixin.qq.com 新智元 多模态", "numResults": 3},
            60000,
        )

    @patch.object(CONNECTOR, "_mcporter_call", return_value=0)
    @patch.object(CONNECTOR, "_validate_runtime")
    def test_fetch_uses_full_article_tool(
        self,
        _validate_runtime: Mock,
        mcporter_call: Mock,
    ) -> None:
        url = "https://mp.weixin.qq.com/s/example"
        args = argparse.Namespace(url=url, max_characters=12000, timeout_ms=60000)

        result = CONNECTOR.fetch_wechat(args)

        self.assertEqual(result, 0)
        mcporter_call.assert_called_once_with(
            "exa.web_fetch_exa",
            {"urls": [url], "maxCharacters": 12000},
            60000,
        )

    @patch.object(CONNECTOR, "_validate_runtime")
    def test_fetch_rejects_non_wechat_url(self, _validate_runtime: Mock) -> None:
        args = argparse.Namespace(
            url="https://example.com/article",
            max_characters=12000,
            timeout_ms=60000,
        )

        with self.assertRaisesRegex(ValueError, "mp.weixin.qq.com"):
            CONNECTOR.fetch_wechat(args)


if __name__ == "__main__":
    unittest.main()
