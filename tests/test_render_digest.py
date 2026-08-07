"""Tests for the PaperPulse HTML report renderer."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from types import ModuleType


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "render_digest.py"


def _load_renderer() -> ModuleType:
    """Load the renderer script without requiring a package install."""
    spec = importlib.util.spec_from_file_location("render_digest", SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load {SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RENDERER = _load_renderer()


class RenderDigestTests(unittest.TestCase):
    """Verify document rendering and local digest integration."""

    def test_render_repository_protocol(self) -> None:
        source = PROJECT_ROOT / "docs" / "agent-protocol.md"
        result = RENDERER.render_report(source.read_text(encoding="utf-8"), source, 1)

        self.assertTrue(result.startswith("<!doctype html>"))
        self.assertIn("PaperPulse Agent Protocol", result)
        self.assertIn('id="theme-toggle"', result)
        self.assertIn('class="pulse-wave"', result)
        self.assertNotIn("@keyframes pulse", result)

    def test_render_verified_paper_resources(self) -> None:
        markdown = """# Paper Digest: 2026-08-07

## [Example Paper](https://arxiv.org/abs/2608.00001)

**Score**: 9.5/10 | **Category**: 视频理解 | **Read Depth**: 全文精读
**Authors**: Researcher et al. | **Date**: 2026-08-07 | **Source**: arXiv
**Evidence Level**: 预印本
**Links**: [PDF](https://arxiv.org/pdf/2608.00001) | [代码](https://github.com/example/paper) | [项目主页](https://example.org/paper) | [主图](https://arxiv.org/html/2608.00001v1/x1.png)

### 一句话总结

用一个真实资源字段验证图文卡片。
"""

        result = RENDERER.render_report(markdown, Path("2026-08-07.md"), 1)

        self.assertIn('<details class="paper-card has-visual"', result)
        self.assertIn('class="paper-visual"', result)
        self.assertIn('loading="lazy"', result)
        self.assertIn('href="https://example.org/paper"', result)
        self.assertIn('href="https://github.com/example/paper"', result)
        self.assertIn('class="paper-resource-bar"', result)
        self.assertNotIn('<p><strong>Links</strong>', result)

    def test_source_health_separates_disabled_and_partial_states(self) -> None:
        section = RENDERER.Section(
            title="数据源状态",
            body=(
                "| 数据源 | 状态 | 说明 |",
                "|---|---|---|",
                "| arXiv | 成功 | 10 篇 |",
                "| Blog | 部分成功 | 一个 feed 失效 |",
                "| Semantic Scholar | 已停用 | 避免限流 |",
                "| WeChat | 未运行 | 未配置 |",
            ),
            anchor="sources",
        )

        health = RENDERER._source_health(section)

        self.assertEqual(health.successful, 1)
        self.assertEqual(health.partial, 1)
        self.assertEqual(health.failed, 0)
        self.assertEqual(health.disabled, 1)
        self.assertEqual(health.skipped, 1)
        self.assertEqual(health.unknown, 0)

    def test_render_latest_private_digest_when_available(self) -> None:
        digests = sorted((PROJECT_ROOT / "digests").glob("????-??-??.md"))
        if not digests:
            self.skipTest("No private local digest is available")
        source = digests[-1]

        result = RENDERER.render_report(source.read_text(encoding="utf-8"), source, 1)

        self.assertIn('<details class="paper-card"', result)
        self.assertIn('class="paper-tldr"', result)
        self.assertIn("prefers-color-scheme: dark", result)
        self.assertIn("--glass-surface:", result)
        self.assertIn("backdrop-filter: saturate(165%) blur(30px)", result)
        self.assertIn('<section class="decision-stack"', result)
        self.assertIn('<div class="sidebar-brief"', result)
        self.assertIn('<details class="report-appendix"', result)
        self.assertLess(
            result.index('<div class="paper-tools"'),
            result.index('<details class="report-appendix"'),
        )
        self.assertNotIn("<h2>Top 10</h2>", result)

    def test_reject_unsafe_link_schemes(self) -> None:
        self.assertIsNone(RENDERER._safe_url("javascript:alert(1)"))
        self.assertIsNone(RENDERER._safe_image_url("mailto:paper@example.org"))
        self.assertEqual(RENDERER._safe_url("https://arxiv.org/"), "https://arxiv.org/")


if __name__ == "__main__":
    unittest.main()
