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

    def test_extract_keeps_results_separate(self):
        data = {"results": [
            {"publishedDate":"2026-11-24T08:10Z","text":"https://github.com/example/release"},
            {"text":"引用 2022-01-01。发布于：2026年11月25日 项目主页 https://example.org/project"},
            {"text":"提到 2021-01-01 https://mp.weixin.qq.com/s/x"},
        ]}
        articles = CONNECTOR.extract_results(data)
        self.assertEqual([v["published"] for v in articles], ["2026-11-24","2026-11-25",None])
        self.assertEqual(articles[1]["links"][0]["kind"], "project_candidate")
        self.assertFalse(articles[2]["links"])
        self.assertTrue(CONNECTOR.build_parser().parse_args(["search","topic"]).objective)

    def test_exa_text_envelope_separates_publication_from_quoted_dates(self):
        data = {"content":[{"text":"Title: A\nURL: https://mp.weixin.qq.com/s/a\nPublished: N/A\n"
                                 "published 2020-01-01 https://github.com/org/one\n"
                                 "Title: B\nURL: https://mp.weixin.qq.com/s/b\nPublished: 2026-11-25\n"
                                 "https://huggingface.co/org/two"}]}
        first, second = CONNECTOR.extract_results(data)
        self.assertIsNone(first["published"])
        self.assertEqual(second["published"], "2026-11-25")
        self.assertEqual(second["source"], "https://mp.weixin.qq.com/s/b")
        self.assertEqual(len(first["links"]), 1)

    @patch.object(CONNECTOR, "_mcporter_call", return_value=0)
    @patch.object(CONNECTOR, "_validate_runtime")
    def test_search_adds_wechat_domain(
        self,
        _validate_runtime: Mock,
        mcporter_call: Mock,
    ) -> None:
        args = argparse.Namespace(query="示例公众号 多模态", num_results=3, objective="find releases", timeout_ms=60000)

        result = CONNECTOR.search_wechat(args)

        self.assertEqual(result, 0)
        mcporter_call.assert_called_once_with(
            "exa.web_search_exa",
            {"query": "site:mp.weixin.qq.com 示例公众号 多模态", "numResults": 3, "objective": "find releases"},
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
