"""Tests for the PaperPulse HTML report renderer."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
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

    def test_body_figure_with_adjacent_text_and_untrusted_url(self) -> None:
        result = RENDERER._render_blocks([
            "方法说明", "![图一 <输入>](https://example.org/a.png)", "实验结果",
            "![受限图](data:text/html,untrusted)",
        ])
        self.assertIn('<p>方法说明</p>', result)
        self.assertIn('<img src="https://example.org/a.png" alt="图一 &lt;输入&gt;"', result)
        self.assertIn('<figcaption>图一 &lt;输入&gt;', result)
        self.assertIn('<p>实验结果</p>', result)
        self.assertNotIn("data:text/html", result)

    def test_render_repository_protocol(self) -> None:
        source = PROJECT_ROOT / "docs" / "agent-protocol.md"
        result = RENDERER.render_report(source.read_text(encoding="utf-8"), source, 1)

        self.assertTrue(result.startswith("<!doctype html>"))
        self.assertIn("PaperPulse Agent Protocol", result)
        self.assertIn('id="theme-toggle"', result)
        self.assertIn('class="brand"', result)
        self.assertIn('href="index.html" aria-label="返回日报列表"', result)
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

        self.assertIn('<details class="paper-card"', result)
        self.assertNotIn('<img', result.split('<summary>')[-1].split('</summary>')[0])
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
        self.assertIn('data-theme="light"', result)
        self.assertIn('id="scan-title"', result)
        self.assertNotIn('<aside', result)
        self.assertIn('<section class="decision-stack"', result)
        self.assertIn('<details class="report-appendix"', result)
        self.assertLess(
            result.index('<div class="paper-tools"'),
            result.index('<details class="report-appendix"'),
        )
        self.assertNotIn("<h2>Top 10</h2>", result)

    def test_new_template_industry_and_relative_figures(self):
        md = """# Report
## [Paper](https://example.org/p)
**Score**: 8.7 | **Category**: 高效 Video/VLM 系统 | **Read Depth**: 摘要核验
### 核心突破与做法
用更少帧保留关键证据。
![方法图](assets/fig.png)
### 关键证据与适用边界
原文条件。
### 与我工作的关联与下一步
暂无直接关联。
### 交给 MorrowOS 追查的问题与一手链接
核验对照。
## 行业与开源速递（微信信源）
- 发布 [源码](https://github.com/example/tool)
```mermaid
A-->B
```
"""
        report = RENDERER.render_report(md, Path("2030-01-01.md"), 0)
        self.assertIn('data-category="高效 Video/VLM 系统"', report)
        self.assertIn('src="assets/fig.png"', report)
        self.assertIn('<section class="industry">', report)
        self.assertNotIn('cdn.jsdelivr', report)
        self.assertEqual(report.count('<tr data-paper='),1)
        self.assertIsNone(RENDERER._safe_image_url('//other.example/a.png'))
        with tempfile.TemporaryDirectory() as d:
            source = Path(d)/"2030-01-01.md"
            source.write_text(md)
            archive = RENDERER.render_archive_index([source])
            self.assertIn('href="2030-01-01.md"',archive)
            self.assertIn('高效 video/vlm 系统',archive)

    def test_reject_unsafe_link_schemes(self) -> None:
        self.assertIsNone(RENDERER._safe_url("javascript:alert(1)"))
        self.assertIsNone(RENDERER._safe_image_url("mailto:paper@example.org"))
        self.assertEqual(RENDERER._safe_url("https://arxiv.org/"), "https://arxiv.org/")

    def test_render_updates_date_sorted_archive(self) -> None:
        markdown = """# Paper Digest: 2030-01-02

## 今日决策

没有需要展开的测试论文。
"""
        with tempfile.TemporaryDirectory() as directory:
            digest_dir = Path(directory)
            source = digest_dir / "2030-01-02.md"
            source.write_text(markdown, encoding="utf-8")
            (digest_dir / "2030-01-01.html").write_text("older", encoding="utf-8")

            result = RENDERER.main([str(source), "--open-top", "0"])

            self.assertEqual(result, 0)
            archive = (digest_dir / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="2030-01-02.html"', archive)
            self.assertIn('href="2030-01-01.html"', archive)
            self.assertLess(archive.index("2030-01-02.html"), archive.index("2030-01-01.html"))
            self.assertIn("2</strong> 份报告", archive)
            self.assertNotIn("window.location.replace", archive)

    def test_archive_skips_invalid_date_filename(self) -> None:
        archive = RENDERER.render_archive_index(
            (Path("2030-01-03.html"), Path("2030-99-99.html"), Path("notes.html"))
        )

        self.assertIn("2030-01-03.html", archive)
        self.assertNotIn("2030-99-99.html", archive)


if __name__ == "__main__":
    unittest.main()
