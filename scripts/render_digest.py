#!/usr/bin/env python3
"""Render a PaperPulse Markdown digest as an interactive HTML report."""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import urlparse


LOGGER = logging.getLogger("paperpulse.renderer")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
PAPER_LINK_PATTERN = re.compile(r"^\[([^]]+)]\(([^)]+)\)$")
INLINE_PATTERN = re.compile(r"(`[^`]+`|\*\*[^*]+\*\*|\[[^]]+]\([^)]+\))")
TABLE_DIVIDER_PATTERN = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}")
SCORE_PATTERN = re.compile(r"(?:\*\*)?(?:Score|评分)(?:\*\*)?\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)", re.I)
CATEGORY_PATTERN = re.compile(r"(?:\*\*)?(?:Category|分类)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
DEPTH_PATTERN = re.compile(r"(?:\*\*)?(?:Read Depth|阅读深度)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
AUTHORS_PATTERN = re.compile(r"(?:\*\*)?(?:Authors|作者)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
PUBLISHED_PATTERN = re.compile(r"(?:\*\*)?(?:Date|日期)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
SOURCE_PATTERN = re.compile(r"(?:\*\*)?(?:Source|来源)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
EVIDENCE_PATTERN = re.compile(r"(?:\*\*)?(?:Evidence Level|证据等级)(?:\*\*)?\s*[:：]\s*([^\n|]+)", re.I)
RESOURCE_LINE_PATTERN = re.compile(
    r"^\s*(?:\*\*)?(Links|链接|Resources|资源|Main Figure|主图|封面图)(?:\*\*)?\s*[:：]\s*(.+)$",
    re.I,
)
MARKDOWN_LINK_PATTERN = re.compile(r"\[([^]]+)]\(([^)]+)\)")
PRESENTATION_META_PATTERN = re.compile(
    r"^\s*(?:\*\*)?(?:Score|评分|Authors|作者|Date|日期|Source|来源|Evidence Level|证据等级|Links|链接|"
    r"Resources|资源|Main Figure|主图|封面图)(?:\*\*)?\s*[:：]",
    re.I,
)
PRIMARY_SECTION_NAMES = {
    "今日结论",
    "今日决策",
    "行动建议",
    "关键结论",
    "executive summary",
    "recommendations",
}
REDUNDANT_SECTION_NAMES = {
    "top 10",
    "top papers",
    "summary table",
    "论文总览",
    "论文列表",
}
SIDEBAR_SECTION_NAMES = ("背景", "问题", "效果")


@dataclass(frozen=True)
class Section:
    """Represent one second-level digest section."""

    title: str
    body: tuple[str, ...]
    anchor: str
    paper_title: Optional[str] = None
    paper_url: Optional[str] = None

    @property
    def is_paper(self) -> bool:
        """Return whether the section is a paper card."""
        return self.paper_title is not None and self.paper_url is not None


@dataclass(frozen=True)
class PaperMeta:
    """Store presentation metadata extracted from one paper section."""

    score: Optional[float]
    categories: tuple[str, ...]
    read_depth: str
    summary: str
    authors: str
    published_date: str
    sources: tuple[str, ...]
    evidence_level: str
    pdf_url: Optional[str]
    code_url: Optional[str]
    project_url: Optional[str]
    image_url: Optional[str]


@dataclass(frozen=True)
class SourceHealth:
    """Store normalized source execution states from one digest snapshot."""

    successful: int
    partial: int
    failed: int
    disabled: int
    skipped: int
    unknown: int

    @property
    def attempted(self) -> int:
        """Return sources that actually attempted collection."""
        return self.successful + self.partial + self.failed


def _safe_url(value: str) -> Optional[str]:
    """Allow only URLs suitable for links in a local report."""
    parsed = urlparse(value.strip())
    if parsed.scheme in {"http", "https", "mailto"}:
        return value.strip()
    return None


def _safe_image_url(value: str) -> Optional[str]:
    """Allow only remote HTTP(S) image resources."""
    safe_url = _safe_url(value)
    if safe_url is None or urlparse(safe_url).scheme not in {"http", "https"}:
        return None
    return safe_url


def _strip_markdown(value: str) -> str:
    """Remove common inline Markdown markers for compact labels."""
    value = re.sub(r"\[([^]]+)]\([^)]+\)", r"\1", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"\1", value)
    value = re.sub(r"`([^`]+)`", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, limit: int = 180) -> str:
    """Shorten text without cutting far past the display budget."""
    normalized = _strip_markdown(value)
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def _slugify(value: str, used: dict[str, int]) -> str:
    """Create deterministic, unique anchors for Chinese and Latin titles."""
    base = re.sub(r"[^\w\u3400-\u9fff]+", "-", _strip_markdown(value).lower()).strip("-")
    if not base:
        base = "section"
    count = used.get(base, 0)
    used[base] = count + 1
    return base if count == 0 else f"{base}-{count + 1}"


def _render_inline(value: str) -> str:
    """Render the limited inline Markdown used by PaperPulse safely."""
    rendered: list[str] = []
    cursor = 0
    for match in INLINE_PATTERN.finditer(value):
        rendered.append(html.escape(value[cursor : match.start()]))
        token = match.group(0)
        if token.startswith("`"):
            rendered.append(f"<code>{html.escape(token[1:-1])}</code>")
        elif token.startswith("**"):
            rendered.append(f"<strong>{html.escape(token[2:-2])}</strong>")
        else:
            link_match = re.fullmatch(r"\[([^]]+)]\(([^)]+)\)", token)
            if link_match is None:
                rendered.append(html.escape(token))
            else:
                label, raw_url = link_match.groups()
                safe_url = _safe_url(raw_url)
                if safe_url is None:
                    rendered.append(html.escape(label))
                else:
                    rendered.append(
                        f'<a href="{html.escape(safe_url, quote=True)}" '
                        f'target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'
                    )
        cursor = match.end()
    rendered.append(html.escape(value[cursor:]))
    return "".join(rendered)


def _split_table_row(line: str) -> list[str]:
    """Split a simple Markdown table row into cells."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _render_table(lines: Sequence[str]) -> str:
    """Render a Markdown table as responsive semantic HTML."""
    headers = _split_table_row(lines[0])
    rows = [_split_table_row(line) for line in lines[2:]]
    header_html = "".join(f"<th>{_render_inline(cell)}</th>" for cell in headers)
    body_html = "".join(
        "<tr>" + "".join(f"<td>{_render_inline(cell)}</td>" for cell in row) + "</tr>"
        for row in rows
    )
    return (
        '<div class="table-wrap"><table><thead><tr>'
        f"{header_html}</tr></thead><tbody>{body_html}</tbody></table></div>"
    )


def _is_special_start(lines: Sequence[str], index: int) -> bool:
    """Return whether a line starts a non-paragraph Markdown block."""
    line = lines[index]
    if not line.strip():
        return True
    if line.startswith("```") or HEADING_PATTERN.match(line):
        return True
    if line.startswith(">") or re.match(r"^\s*[-*+]\s+", line):
        return True
    if re.match(r"^\s*\d+[.)]\s+", line):
        return True
    return index + 1 < len(lines) and "|" in line and TABLE_DIVIDER_PATTERN.match(lines[index + 1]) is not None


def _render_blocks(lines: Sequence[str]) -> str:
    """Render the block-level Markdown subset used by daily digests."""
    output: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        if line.startswith("```"):
            language = line[3:].strip().lower()
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1 if index < len(lines) else 0
            code = html.escape("\n".join(code_lines))
            if language == "mermaid":
                output.append(f'<div class="diagram"><pre class="mermaid">{code}</pre></div>')
            else:
                language_class = f" language-{html.escape(language, quote=True)}" if language else ""
                output.append(f'<pre class="code-block"><code class="{language_class.strip()}">{code}</code></pre>')
            continue

        heading_match = HEADING_PATTERN.match(line)
        if heading_match is not None:
            level = min(max(len(heading_match.group(1)), 3), 6)
            output.append(f"<h{level}>{_render_inline(heading_match.group(2))}</h{level}>")
            index += 1
            continue

        if index + 1 < len(lines) and "|" in line and TABLE_DIVIDER_PATTERN.match(lines[index + 1]):
            table_lines = [line, lines[index + 1]]
            index += 2
            while index < len(lines) and lines[index].strip().startswith("|"):
                table_lines.append(lines[index])
                index += 1
            output.append(_render_table(table_lines))
            continue

        if line.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].startswith(">"):
                quote_lines.append(lines[index].lstrip("> "))
                index += 1
            output.append(f"<blockquote>{'<br>'.join(_render_inline(item) for item in quote_lines)}</blockquote>")
            continue

        unordered_match = re.match(r"^\s*[-*+]\s+(.+)", line)
        ordered_match = re.match(r"^\s*\d+[.)]\s+(.+)", line)
        if unordered_match is not None or ordered_match is not None:
            ordered = ordered_match is not None
            pattern = r"^\s*\d+[.)]\s+(.+)" if ordered else r"^\s*[-*+]\s+(.+)"
            items: list[str] = []
            while index < len(lines):
                item_match = re.match(pattern, lines[index])
                if item_match is None:
                    break
                item = item_match.group(1)
                checkbox_match = re.match(r"\[([ xX])]\s*(.+)", item)
                if checkbox_match is not None:
                    checked = checkbox_match.group(1).lower() == "x"
                    marker = '<span class="check checked">✓</span>' if checked else '<span class="check"> </span>'
                    items.append(f"<li>{marker}{_render_inline(checkbox_match.group(2))}</li>")
                else:
                    items.append(f"<li>{_render_inline(item)}</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            output.append(f"<{tag}>{''.join(items)}</{tag}>")
            continue

        paragraph_lines = [line.strip()]
        index += 1
        while index < len(lines) and not _is_special_start(lines, index):
            paragraph_lines.append(lines[index].strip())
            index += 1
        output.append(f"<p>{_render_inline(' '.join(paragraph_lines))}</p>")
    return "\n".join(output)


def _parse_document(markdown: str) -> tuple[str, tuple[str, ...], tuple[Section, ...]]:
    """Split a digest into its title, prelude, and second-level sections."""
    lines = markdown.splitlines()
    title = "PaperPulse Daily Research Report"
    if lines and lines[0].startswith("# "):
        title = _strip_markdown(lines[0][2:])
        lines = lines[1:]

    used_anchors: dict[str, int] = {}
    prelude: list[str] = []
    sections: list[Section] = []
    current_title: Optional[str] = None
    current_body: list[str] = []

    def flush_section() -> None:
        nonlocal current_title, current_body
        if current_title is None:
            return
        paper_match = PAPER_LINK_PATTERN.fullmatch(current_title.strip())
        paper_title: Optional[str] = None
        paper_url: Optional[str] = None
        if paper_match is not None and _safe_url(paper_match.group(2)) is not None:
            paper_title = paper_match.group(1).strip()
            paper_url = paper_match.group(2).strip()
        sections.append(
            Section(
                title=current_title,
                body=tuple(current_body),
                anchor=_slugify(paper_title or current_title, used_anchors),
                paper_title=paper_title,
                paper_url=paper_url,
            )
        )
        current_title = None
        current_body = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("### "):
            flush_section()
            current_title = line[3:].strip()
        elif current_title is None:
            prelude.append(line)
        else:
            current_body.append(line)
    flush_section()
    return title, tuple(prelude), tuple(sections)


def _section_text(lines: Sequence[str], names: Iterable[str]) -> str:
    """Extract the first paragraph below a named third-level heading."""
    normalized_names = {_strip_markdown(name).lower() for name in names}
    collecting = False
    content: list[str] = []
    for line in lines:
        heading = re.match(r"^###\s+(.+)$", line)
        if heading is not None:
            if collecting:
                break
            collecting = _strip_markdown(heading.group(1)).lower() in normalized_names
            continue
        if collecting:
            if not line.strip() and content:
                break
            if line.strip():
                content.append(line.strip())
    return " ".join(content)


def _resource_key(label: str) -> Optional[str]:
    """Map a human resource label to one supported card action."""
    normalized = _strip_markdown(label).strip().lower().replace(" ", "")
    if normalized in {"pdf", "论文pdf", "全文pdf"}:
        return "pdf"
    if any(token in normalized for token in ("主图", "封面", "figure", "image", "teaser")):
        return "image"
    if any(token in normalized for token in ("项目", "project", "homepage", "主页")):
        return "project"
    if any(token in normalized for token in ("代码", "code", "github", "repo")):
        return "code"
    return None


def _paper_resources(section: Section) -> dict[str, str]:
    """Extract explicitly verified PDF, code, project, and figure links."""
    resources: dict[str, str] = {}
    for raw_line in section.body:
        match = RESOURCE_LINE_PATTERN.match(raw_line)
        if match is None:
            continue
        line_label, content = match.groups()
        context_key = _resource_key(line_label)
        links = list(MARKDOWN_LINK_PATTERN.finditer(content))
        for index, link_match in enumerate(links):
            label, raw_url = link_match.groups()
            key = _resource_key(label) or (context_key if index == 0 else None)
            safe_url = _safe_image_url(raw_url) if key == "image" else _safe_url(raw_url)
            if key is not None and safe_url is not None and key not in resources:
                resources[key] = safe_url
        if not links and context_key is not None:
            safe_url = _safe_image_url(content) if context_key == "image" else _safe_url(content)
            if safe_url is not None and context_key not in resources:
                resources[context_key] = safe_url

    if "pdf" not in resources and section.paper_url is not None:
        parsed = urlparse(section.paper_url)
        if parsed.netloc.lower() == "arxiv.org" and parsed.path.startswith("/abs/"):
            arxiv_id = parsed.path.removeprefix("/abs/").strip("/")
            if arxiv_id:
                resources["pdf"] = f"https://arxiv.org/pdf/{arxiv_id}"
    return resources


def _paper_meta(section: Section) -> PaperMeta:
    """Extract presentation and resource metadata for a paper card."""
    body_text = "\n".join(section.body)
    score_match = SCORE_PATTERN.search(body_text)
    score = float(score_match.group(1)) if score_match is not None else None
    category_match = CATEGORY_PATTERN.search(body_text)
    categories: tuple[str, ...] = ()
    if category_match is not None:
        categories = tuple(
            item.strip()
            for item in re.split(r"[,，/]", _strip_markdown(category_match.group(1)))
            if item.strip()
        )
    depth_match = DEPTH_PATTERN.search(body_text)
    read_depth = _strip_markdown(depth_match.group(1)) if depth_match is not None else "历史摘要"
    authors_match = AUTHORS_PATTERN.search(body_text)
    authors = _strip_markdown(authors_match.group(1)) if authors_match is not None else ""
    published_match = PUBLISHED_PATTERN.search(body_text)
    published_date = _strip_markdown(published_match.group(1)) if published_match is not None else ""
    source_match = SOURCE_PATTERN.search(body_text)
    sources: tuple[str, ...] = ()
    if source_match is not None:
        sources = tuple(
            item.strip()
            for item in re.split(r"[,，/]", _strip_markdown(source_match.group(1)))
            if item.strip()
        )
    evidence_match = EVIDENCE_PATTERN.search(body_text)
    evidence_level = _strip_markdown(evidence_match.group(1)) if evidence_match is not None else ""
    summary = _section_text(section.body, ("一句话总结", "TL;DR", "核心结论"))
    if not summary:
        summary = next((line for line in section.body if line.strip() and not line.startswith("**")), "点击展开详情")
    resources = _paper_resources(section)
    return PaperMeta(
        score=score,
        categories=categories,
        read_depth=read_depth,
        summary=_truncate(summary),
        authors=authors,
        published_date=published_date,
        sources=sources,
        evidence_level=evidence_level,
        pdf_url=resources.get("pdf"),
        code_url=resources.get("code"),
        project_url=resources.get("project"),
        image_url=resources.get("image"),
    )


def _section_name(section: Section) -> str:
    """Normalize a section title for layout classification."""
    return _strip_markdown(section.title).strip().lower()


def _first_readable_line(lines: Sequence[str]) -> str:
    """Extract a concise plain-text preview from a Markdown section."""
    in_code = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not line or line.startswith("#"):
            continue
        if line.startswith("|") or TABLE_DIVIDER_PATTERN.match(line):
            continue
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+|>\s*)", "", line)
        if line:
            return _truncate(line, 118)
    return "暂无摘要"


def _source_status(value: str) -> str:
    """Normalize one source state without confusing disabled with failed."""
    normalized = _strip_markdown(value).strip().lower()
    if any(token in normalized for token in ("停用", "disabled")):
        return "disabled"
    if any(token in normalized for token in ("未运行", "未记录", "跳过", "not run", "skipped")):
        return "skipped"
    if any(token in normalized for token in ("部分", "partial")):
        return "partial"
    if any(token in normalized for token in ("失败", "failed", "error")):
        return "failed"
    if any(token in normalized for token in ("成功", "正常", "success", "healthy")):
        return "successful"
    return "unknown"


def _source_health(section: Optional[Section]) -> SourceHealth:
    """Count normalized source states from a digest status table."""
    counts = {
        "successful": 0,
        "partial": 0,
        "failed": 0,
        "disabled": 0,
        "skipped": 0,
        "unknown": 0,
    }
    if section is None:
        return SourceHealth(**counts)
    for line in section.body:
        if not line.strip().startswith("|") or TABLE_DIVIDER_PATTERN.match(line):
            continue
        cells = _split_table_row(line)
        if len(cells) < 2:
            continue
        state = _source_status(cells[1])
        if state == "unknown" and _strip_markdown(cells[0]).strip().lower() in {"数据源", "source"}:
            continue
        counts[state] += 1
    return SourceHealth(**counts)


def _render_sidebar_brief(sections: Sequence[Section]) -> str:
    """Render short context previews without moving long prose into the sidebar."""
    by_name = {_section_name(section): section for section in sections}
    previews: list[str] = []
    for name in SIDEBAR_SECTION_NAMES:
        section = by_name.get(name.lower())
        if section is None:
            continue
        previews.append(
            f'<a class="brief-item" href="#report-appendix" '
            f'data-target="{html.escape(section.anchor, quote=True)}">'
            f'<span>{html.escape(name)}</span><p>{html.escape(_first_readable_line(section.body))}</p></a>'
        )

    source_section = next(
        (
            section
            for section in sections
            if _section_name(section) in {"数据源状态", "source status", "sources"}
        ),
        None,
    )
    health = _source_health(source_section)
    source_html = ""
    if source_section is not None:
        secondary_states = "".join(
            item
            for count, item in (
                (health.disabled, f'<span class="status-pill disabled"><strong>{health.disabled}</strong> 停用</span>'),
                (health.skipped, f'<span class="status-pill skipped"><strong>{health.skipped}</strong> 未运行</span>'),
                (health.unknown, f'<span class="status-pill skipped"><strong>{health.unknown}</strong> 未知</span>'),
            )
            if count > 0
        )
        source_html = (
            f'<a class="source-health" href="#report-appendix" '
            f'data-target="{html.escape(source_section.anchor, quote=True)}">'
            f'<span class="health-head"><span class="health-label">数据源</span><small>{health.attempted} 个已执行</small></span>'
            '<span class="health-pills">'
            f'<span class="status-pill success"><strong>{health.successful}</strong> 正常</span>'
            f'<span class="status-pill partial"><strong>{health.partial}</strong> 部分</span>'
            f'<span class="status-pill failed"><strong>{health.failed}</strong> 失败</span>'
            f'{secondary_states}</span></a>'
        )
    return "".join(previews) + source_html


def _prepare_paper_body(lines: Sequence[str]) -> tuple[str, ...]:
    """Remove metadata and a TL;DR already promoted into the card chrome."""
    output: list[str] = []
    skipping = False
    for line in lines:
        heading = re.match(r"^###\s+(.+)$", line)
        if heading is not None:
            normalized = _strip_markdown(heading.group(1)).lower()
            if normalized in {"一句话总结", "tl;dr", "核心结论"}:
                skipping = True
                continue
            if skipping:
                skipping = False
        if not skipping and PRESENTATION_META_PATTERN.match(line) is None:
            output.append(line)
    return tuple(output)


def _extract_count(markdown: str, patterns: Sequence[str], fallback: int) -> int:
    """Extract a report count from Chinese or English digest prose."""
    for pattern in patterns:
        match = re.search(pattern, markdown, re.I)
        if match is not None:
            return int(match.group(1))
    return fallback


def _render_paper_card(section: Section, index: int, open_top: int) -> str:
    """Render one paper as a compact expandable evidence card."""
    if section.paper_title is None or section.paper_url is None:
        raise ValueError("Paper card requires a title and URL")
    meta = _paper_meta(section)
    score_value = f"{meta.score:.1f}" if meta.score is not None else "—"
    category_badges = "".join(f'<span class="tag">{html.escape(item)}</span>' for item in meta.categories)
    depth_class = "deep" if "全文" in meta.read_depth or "精读" in meta.read_depth else "standard"
    opened = " open" if index <= open_top else ""
    body = _render_blocks(_prepare_paper_body(section.body))
    card_class = "paper-card has-visual" if meta.image_url is not None else "paper-card"
    visual_html = ""
    if meta.image_url is not None:
        visual_html = (
            '<span class="paper-visual">'
            f'<img src="{html.escape(meta.image_url, quote=True)}" '
            f'alt="{html.escape(section.paper_title + " 的论文主图", quote=True)}" '
            'loading="lazy" decoding="async" referrerpolicy="no-referrer">'
            '<span class="visual-label">论文主图</span></span>'
        )

    byline_items: list[str] = []
    if meta.authors:
        byline_items.append(f'<span>{html.escape(_truncate(meta.authors, 76))}</span>')
    if meta.published_date:
        byline_items.append(f'<span>{html.escape(meta.published_date)}</span>')
    if meta.sources:
        byline_items.append(f'<span>{html.escape(" · ".join(meta.sources))}</span>')
    if meta.evidence_level:
        byline_items.append(f'<span>{html.escape(meta.evidence_level)}</span>')
    byline_html = "".join(byline_items)

    resources = [
        ("论文", section.paper_url, "primary"),
        ("PDF", meta.pdf_url, "secondary"),
        ("项目主页", meta.project_url, "secondary"),
        ("代码", meta.code_url, "secondary"),
        ("主图", meta.image_url, "secondary"),
    ]
    seen_urls: set[str] = set()
    resource_links: list[str] = []
    for label, url, variant in resources:
        if url is None or url in seen_urls:
            continue
        seen_urls.add(url)
        resource_links.append(
            f'<a class="paper-link {variant}" href="{html.escape(url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">{html.escape(label)} ↗</a>'
        )
    resource_bar = (
        '<div class="paper-resource-bar">'
        f'<div class="paper-byline">{byline_html}</div>'
        f'<div class="paper-actions">{"".join(resource_links)}</div></div>'
    )
    return f"""
<details class="{card_class}" id="{html.escape(section.anchor, quote=True)}"
         data-score="{score_value}" data-depth="{html.escape(depth_class, quote=True)}"
         data-search="{html.escape((section.paper_title + ' ' + ' '.join(meta.categories)).lower(), quote=True)}"{opened}>
  <summary>
    <span class="paper-rank">{index:02d}</span>
    <span class="paper-summary-copy">
      <span class="paper-badges"><span class="depth-badge {depth_class}">{html.escape(meta.read_depth)}</span>{category_badges}</span>
      <span class="paper-title">{html.escape(section.paper_title)}</span>
      <span class="paper-tldr">{html.escape(meta.summary)}</span>
    </span>
    {visual_html}
    <span class="paper-score"><strong>{score_value}</strong><small>/10</small></span>
    <span class="expand-icon" aria-hidden="true">⌄</span>
  </summary>
  <div class="paper-body">
    {resource_bar}
    {body}
  </div>
</details>"""


def _report_css() -> str:
    """Return the self-contained responsive visual system."""
    return r"""
:root {
  color-scheme: light;
  --bg: #f5f5f7;
  --surface: rgba(255, 255, 255, 0.74);
  --surface-solid: #ffffff;
  --surface-muted: rgba(118, 118, 128, 0.08);
  --glass-surface: rgba(255, 255, 255, 0.50);
  --glass-surface-strong: rgba(255, 255, 255, 0.68);
  --glass-lowlight: rgba(255, 255, 255, 0.28);
  --glass-border: rgba(255, 255, 255, 0.72);
  --glass-highlight: rgba(255, 255, 255, 0.92);
  --glass-shadow: 0 1px 1px rgba(255, 255, 255, 0.78) inset, 0 18px 50px rgba(31, 38, 53, 0.13);
  --ambient-blue: rgba(0, 113, 227, 0.22);
  --ambient-purple: rgba(175, 82, 222, 0.14);
  --ambient-cyan: rgba(100, 210, 255, 0.18);
  --ambient-sheen: rgba(255, 255, 255, 0.34);
  --ink: #1d1d1f;
  --muted: #6e6e73;
  --tertiary: #86868b;
  --line: rgba(0, 0, 0, 0.08);
  --line-strong: rgba(0, 0, 0, 0.13);
  --brand: #0071e3;
  --brand-hover: #0077ed;
  --brand-soft: rgba(0, 113, 227, 0.10);
  --brand-line: rgba(0, 113, 227, 0.22);
  --brand-glow: rgba(0, 113, 227, 0.16);
  --deep: #5856d6;
  --deep-soft: rgba(88, 86, 214, 0.11);
  --success: #248a3d;
  --success-soft: rgba(36, 138, 61, 0.11);
  --warning: #a45100;
  --warning-soft: rgba(164, 81, 0, 0.11);
  --danger: #d70015;
  --danger-soft: rgba(215, 0, 21, 0.10);
  --shadow-soft: 0 1px 2px rgba(0, 0, 0, 0.03), 0 12px 38px rgba(0, 0, 0, 0.055);
  --shadow-open: 0 2px 4px rgba(0, 0, 0, 0.03), 0 22px 60px rgba(0, 0, 0, 0.09);
  --radius-xl: 32px;
  --radius-lg: 24px;
  --radius-md: 18px;
}

[data-theme="dark"] {
  color-scheme: dark;
  --bg: #000000;
  --surface: rgba(28, 28, 30, 0.78);
  --surface-solid: #1c1c1e;
  --surface-muted: rgba(118, 118, 128, 0.18);
  --glass-surface: rgba(28, 28, 30, 0.48);
  --glass-surface-strong: rgba(44, 44, 46, 0.60);
  --glass-lowlight: rgba(255, 255, 255, 0.08);
  --glass-border: rgba(255, 255, 255, 0.20);
  --glass-highlight: rgba(255, 255, 255, 0.28);
  --glass-shadow: 0 1px 1px rgba(255, 255, 255, 0.12) inset, 0 22px 58px rgba(0, 0, 0, 0.42);
  --ambient-blue: rgba(41, 151, 255, 0.28);
  --ambient-purple: rgba(191, 90, 242, 0.20);
  --ambient-cyan: rgba(100, 210, 255, 0.16);
  --ambient-sheen: rgba(255, 255, 255, 0.045);
  --ink: #f5f5f7;
  --muted: #a1a1a6;
  --tertiary: #8e8e93;
  --line: rgba(255, 255, 255, 0.11);
  --line-strong: rgba(255, 255, 255, 0.18);
  --brand: #2997ff;
  --brand-hover: #40a9ff;
  --brand-soft: rgba(41, 151, 255, 0.16);
  --brand-line: rgba(41, 151, 255, 0.30);
  --brand-glow: rgba(41, 151, 255, 0.18);
  --deep: #bf5af2;
  --deep-soft: rgba(191, 90, 242, 0.17);
  --success: #30d158;
  --success-soft: rgba(48, 209, 88, 0.16);
  --warning: #ff9f0a;
  --warning-soft: rgba(255, 159, 10, 0.16);
  --danger: #ff453a;
  --danger-soft: rgba(255, 69, 58, 0.16);
  --shadow-soft: 0 1px 2px rgba(0, 0, 0, 0.20), 0 16px 42px rgba(0, 0, 0, 0.26);
  --shadow-open: 0 2px 5px rgba(0, 0, 0, 0.25), 0 26px 70px rgba(0, 0, 0, 0.42);
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --bg: #000000;
    --surface: rgba(28, 28, 30, 0.78);
    --surface-solid: #1c1c1e;
    --surface-muted: rgba(118, 118, 128, 0.18);
    --glass-surface: rgba(28, 28, 30, 0.48);
    --glass-surface-strong: rgba(44, 44, 46, 0.60);
    --glass-lowlight: rgba(255, 255, 255, 0.08);
    --glass-border: rgba(255, 255, 255, 0.20);
    --glass-highlight: rgba(255, 255, 255, 0.28);
    --glass-shadow: 0 1px 1px rgba(255, 255, 255, 0.12) inset, 0 22px 58px rgba(0, 0, 0, 0.42);
    --ambient-blue: rgba(41, 151, 255, 0.28);
    --ambient-purple: rgba(191, 90, 242, 0.20);
    --ambient-cyan: rgba(100, 210, 255, 0.16);
    --ambient-sheen: rgba(255, 255, 255, 0.045);
    --ink: #f5f5f7;
    --muted: #a1a1a6;
    --tertiary: #8e8e93;
    --line: rgba(255, 255, 255, 0.11);
    --line-strong: rgba(255, 255, 255, 0.18);
    --brand: #2997ff;
    --brand-hover: #40a9ff;
    --brand-soft: rgba(41, 151, 255, 0.16);
    --brand-line: rgba(41, 151, 255, 0.30);
    --brand-glow: rgba(41, 151, 255, 0.18);
    --deep: #bf5af2;
    --deep-soft: rgba(191, 90, 242, 0.17);
    --success: #30d158;
    --success-soft: rgba(48, 209, 88, 0.16);
    --warning: #ff9f0a;
    --warning-soft: rgba(255, 159, 10, 0.16);
    --danger: #ff453a;
    --danger-soft: rgba(255, 69, 58, 0.16);
    --shadow-soft: 0 1px 2px rgba(0, 0, 0, 0.20), 0 16px 42px rgba(0, 0, 0, 0.26);
    --shadow-open: 0 2px 5px rgba(0, 0, 0, 0.25), 0 26px 70px rgba(0, 0, 0, 0.42);
  }
}

* { box-sizing: border-box; }
html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  background-color: var(--bg);
  background-image:
    radial-gradient(circle at 8% 18%, var(--ambient-cyan), transparent 27rem),
    radial-gradient(circle at 82% -8%, var(--ambient-blue), transparent 34rem),
    radial-gradient(circle at 96% 46%, var(--ambient-purple), transparent 29rem),
    linear-gradient(180deg, var(--ambient-sheen), transparent 38rem);
  background-attachment: fixed;
  background-repeat: no-repeat;
  color: var(--ink);
  font: 16px/1.68 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", "PingFang SC", "Microsoft YaHei", sans-serif;
  min-height: 100vh;
  text-rendering: optimizeLegibility;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

a { color: var(--brand); text-decoration-thickness: 1px; text-underline-offset: 3px; }
a:hover { color: var(--brand-hover); }
button, input, summary { -webkit-tap-highlight-color: transparent; }
button:focus-visible, input:focus-visible, summary:focus-visible, a:focus-visible {
  outline: 3px solid var(--brand-soft);
  outline-offset: 2px;
}
.reading-progress {
  position: fixed;
  z-index: 200;
  inset: 0 auto auto 0;
  width: 0;
  height: 3px;
  border-radius: 0 99px 99px 0;
  background: var(--brand);
}

.shell { width: min(1240px, calc(100% - 40px)); margin: 0 auto; padding: 16px 0 80px; }
.topbar {
  position: sticky;
  z-index: 90;
  top: 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 54px;
  margin-bottom: 24px;
  padding: 8px 10px 8px 14px;
  border: 1px solid var(--glass-border);
  border-radius: 18px;
  background: linear-gradient(135deg, var(--glass-surface-strong), var(--glass-surface));
  box-shadow: var(--glass-shadow);
  -webkit-backdrop-filter: saturate(165%) blur(30px);
  backdrop-filter: saturate(165%) blur(30px);
  isolation: isolate;
  overflow: hidden;
}
.topbar::before, .sidebar::before, .hero::before {
  position: absolute;
  z-index: 0;
  inset: 0;
  border-radius: inherit;
  background:
    radial-gradient(circle at 14% 0%, var(--glass-highlight), transparent 31%),
    linear-gradient(115deg, rgba(255, 255, 255, 0.18), transparent 36%, transparent 72%, var(--brand-soft));
  box-shadow: inset 0 1px 0 var(--glass-highlight), inset 0 -1px 0 rgba(255, 255, 255, 0.10);
  content: "";
  pointer-events: none;
}
.topbar > *, .sidebar > *, .hero > * { position: relative; z-index: 1; }
.brand { display: flex; align-items: center; gap: 10px; font-weight: 650; letter-spacing: -0.018em; }
.brand-mark {
  position: relative;
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  background:
    radial-gradient(circle at 32% 22%, rgba(255, 255, 255, 0.42), transparent 31%),
    linear-gradient(145deg, #0a84ff, #0066cc);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.34), 0 4px 12px rgba(0, 113, 227, 0.30);
}
.brand-mark svg { width: 26px; height: 26px; overflow: visible; }
.pulse-ring {
  fill: none;
  stroke: rgba(255, 255, 255, 0.24);
  stroke-width: 1;
}
.pulse-wave {
  fill: none;
  stroke: #ffffff;
  stroke-width: 2.05;
  stroke-linecap: round;
  stroke-linejoin: round;
  filter: drop-shadow(0 1px 2px rgba(0, 58, 122, 0.32));
}
.top-actions { display: flex; gap: 8px; }
.icon-button, .control-button {
  min-height: 36px;
  border: 1px solid transparent;
  border-radius: 999px;
  background: var(--surface-muted);
  color: var(--ink);
  padding: 8px 13px;
  cursor: pointer;
  font: 600 13px/1 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
  transition: background-color .18s ease, color .18s ease, transform .18s ease;
}
.icon-button:hover, .control-button:hover { background: var(--brand-soft); color: var(--brand); }
.icon-button:active, .control-button:active { transform: scale(0.97); }

.hero {
  position: relative;
  overflow: hidden;
  padding: clamp(34px, 4.8vw, 58px);
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-xl);
  background: linear-gradient(145deg, var(--glass-surface-strong), var(--glass-surface));
  box-shadow: var(--glass-shadow), inset 0 1px 0 var(--glass-highlight);
  -webkit-backdrop-filter: saturate(155%) blur(28px);
  backdrop-filter: saturate(155%) blur(28px);
  isolation: isolate;
}
.hero::after {
  position: absolute;
  width: 430px;
  height: 430px;
  right: -160px;
  top: -250px;
  border-radius: 50%;
  content: "";
  background: radial-gradient(circle, var(--brand-glow), rgba(0, 113, 227, 0));
  z-index: 0;
  pointer-events: none;
}
.eyebrow { color: var(--brand); font-size: 12px; font-weight: 700; letter-spacing: 0.13em; text-transform: uppercase; }
.hero h1 {
  position: relative;
  z-index: 1;
  max-width: 820px;
  margin: 14px 0 12px;
  font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", "PingFang SC", sans-serif;
  font-size: clamp(36px, 4.8vw, 54px);
  font-weight: 700;
  line-height: 1.07;
  letter-spacing: -0.052em;
}
.hero-subtitle { max-width: 690px; margin: 0; color: var(--muted); font-size: clamp(15px, 1.6vw, 18px); line-height: 1.55; }
.hero-date {
  display: inline-flex;
  margin-top: 20px;
  padding: 7px 11px;
  border-radius: 999px;
  border: 1px solid var(--glass-border);
  background: var(--glass-lowlight);
  box-shadow: inset 0 1px 0 var(--glass-highlight);
  color: var(--muted);
  font-size: 12px;
  font-weight: 650;
}

.metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  margin-top: 18px;
  padding: 6px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-solid);
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.025);
}
.metric { position: relative; padding: 18px 22px; }
.metric:not(:last-child)::after { position: absolute; inset: 20% 0 20% auto; width: 1px; content: ""; background: var(--line); }
.metric span { display: block; color: var(--muted); font-size: 11px; font-weight: 650; letter-spacing: 0.04em; }
.metric strong { display: block; margin-top: 4px; font-size: 32px; font-weight: 650; line-height: 1.12; letter-spacing: -0.042em; }

.layout { display: grid; grid-template-columns: 230px minmax(0, 1fr); gap: 24px; margin-top: 28px; align-items: start; }
.sidebar {
  position: sticky;
  top: 82px;
  max-height: calc(100vh - 100px);
  overflow: auto;
  padding: 16px;
  border: 1px solid var(--glass-border);
  border-radius: var(--radius-md);
  background: linear-gradient(145deg, var(--glass-surface-strong), var(--glass-surface));
  box-shadow: var(--glass-shadow);
  -webkit-backdrop-filter: saturate(165%) blur(26px);
  backdrop-filter: saturate(165%) blur(26px);
  isolation: isolate;
}
.sidebar-title { margin: 2px 0 10px; padding: 0 8px; color: var(--tertiary); font-size: 10px; font-weight: 700; letter-spacing: 0.10em; text-transform: uppercase; }
.sidebar-paper-title { margin-top: 20px; }
.sidebar-brief { display: grid; gap: 6px; }
.brief-item, .source-health {
  display: block;
  padding: 9px 10px;
  border-radius: 11px;
  color: var(--ink);
  text-decoration: none;
  transition: background-color 100ms ease-out, transform 100ms ease-out;
}
.brief-item:hover, .source-health:hover { background: var(--surface-muted); color: var(--ink); }
.brief-item:active, .source-health:active { transform: scale(0.985); }
.brief-item span, .health-label { color: var(--brand); font-size: 10px; font-weight: 700; letter-spacing: 0.04em; }
.brief-item p {
  display: -webkit-box;
  overflow: hidden;
  margin: 3px 0 0;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.45;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.source-health { display: grid; gap: 8px; margin-top: 3px; }
.health-head { display: flex; align-items: baseline; justify-content: space-between; gap: 8px; }
.health-head small { color: var(--tertiary); font-size: 9px; }
.health-pills { display: flex; flex-wrap: wrap; gap: 5px; }
.status-pill { display: inline-flex; align-items: baseline; gap: 3px; padding: 4px 7px; border-radius: 999px; font-size: 9px; font-weight: 650; }
.status-pill strong { font-size: 11px; }
.status-pill.success { background: var(--success-soft); color: var(--success); }
.status-pill.partial { background: var(--warning-soft); color: var(--warning); }
.status-pill.failed { background: var(--danger-soft); color: var(--danger); }
.status-pill.disabled, .status-pill.skipped { background: var(--surface-muted); color: var(--muted); }
.toc { display: grid; gap: 3px; }
.toc a { display: block; padding: 7px 8px; border-radius: 9px; color: var(--muted); text-decoration: none; font-size: 12px; line-height: 1.38; }
.toc a:hover { background: var(--brand-soft); color: var(--brand); }
.toc .paper-toc { padding-left: 14px; }

.content { min-width: 0; }
.report-intro, .content-section {
  margin-bottom: 14px;
  padding: clamp(26px, 4vw, 46px);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-solid);
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.02);
}
.content-section h2, .report-intro h2 { margin: 0 0 18px; font-size: clamp(25px, 3vw, 34px); font-weight: 650; letter-spacing: -0.038em; }
.content-section p, .report-intro p, .paper-body p { max-width: 76ch; }
.decision-stack {
  overflow: hidden;
  margin-bottom: 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-solid);
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.02);
}
.decision-item { padding: clamp(22px, 3vw, 34px); }
.decision-item + .decision-item { border-top: 1px solid var(--line); }
.decision-label { margin-bottom: 12px; color: var(--brand); font-size: 11px; font-weight: 700; letter-spacing: 0.08em; }
.decision-item > :last-child { margin-bottom: 0; }
h3 { margin: 30px 0 10px; font-size: 18px; font-weight: 650; letter-spacing: -0.02em; }
p { margin: 8px 0 17px; }
blockquote { margin: 18px 0; padding: 16px 18px; border-left: 3px solid var(--brand); border-radius: 0 14px 14px 0; background: var(--surface-muted); color: var(--ink); }
ul, ol { padding-left: 1.3rem; }
li { margin: 6px 0; }
code { padding: 2px 6px; border-radius: 6px; background: var(--brand-soft); font: 0.88em ui-monospace, SFMono-Regular, Menlo, monospace; }
.code-block { overflow: auto; padding: 20px; border-radius: 16px; background: #1d1d1f; color: #f5f5f7; }
.diagram { overflow: auto; padding: 22px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface-solid); }

.table-wrap { overflow-x: auto; margin: 18px 0 26px; border: 1px solid var(--line); border-radius: 16px; background: var(--surface-solid); }
table { width: 100%; border-collapse: collapse; font-size: 14px; }
th { background: var(--surface-muted); color: var(--muted); text-align: left; font-size: 11px; font-weight: 650; letter-spacing: 0.02em; }
th, td { padding: 13px 15px; border-bottom: 1px solid var(--line); vertical-align: top; }
tr:last-child td { border-bottom: 0; }

.paper-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 24px 0 14px; }
.paper-tools h2 { margin: 0 auto 0 0; font-size: clamp(28px, 3vw, 38px); font-weight: 650; letter-spacing: -0.045em; }
.paper-search {
  width: min(260px, 100%);
  min-height: 38px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface-solid);
  color: var(--ink);
  padding: 9px 15px;
  font: 13px/1.2 -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
  outline: none;
}
.paper-search:focus { border-color: var(--brand-line); box-shadow: 0 0 0 4px var(--brand-soft); }

.paper-list { display: grid; gap: 10px; }
.paper-card {
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-solid);
  box-shadow: 0 1px 1px rgba(0, 0, 0, 0.025), 0 7px 22px rgba(0, 0, 0, 0.025);
  overflow: hidden;
  transition: border-color .2s ease, transform .2s ease, box-shadow .24s ease;
}
.paper-card:hover { border-color: var(--line-strong); transform: translateY(-1px); box-shadow: 0 2px 4px rgba(0, 0, 0, 0.035), 0 12px 30px rgba(0, 0, 0, 0.055); }
.paper-card[open] { border-color: var(--brand-line); box-shadow: var(--shadow-open); }
.paper-card[hidden] { display: none; }
.paper-card summary {
  display: grid;
  grid-template-areas: "rank copy score icon";
  grid-template-columns: 44px minmax(0, 1fr) auto 22px;
  gap: 16px;
  align-items: center;
  padding: 22px 24px;
  cursor: pointer;
  list-style: none;
  transition: background-color 180ms ease-out;
}
.paper-card.has-visual summary {
  grid-template-areas: "rank copy visual score icon";
  grid-template-columns: 44px minmax(0, 1fr) minmax(158px, 190px) auto 22px;
}
.paper-card summary:hover { background: linear-gradient(90deg, transparent, var(--surface-muted)); }
.paper-card summary::-webkit-details-marker { display: none; }
.paper-rank {
  grid-area: rank;
  display: grid;
  place-items: center;
  width: 40px;
  height: 40px;
  border: 1px solid var(--brand-line);
  border-radius: 50%;
  background: linear-gradient(145deg, var(--brand-soft), transparent);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.42);
  color: var(--brand);
  font-weight: 700;
  font-size: 12px;
}
.paper-summary-copy { grid-area: copy; min-width: 0; }
.paper-badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 7px; }
.depth-badge, .tag { display: inline-flex; align-items: center; border-radius: 999px; padding: 3px 8px; font-size: 10px; font-weight: 650; }
.depth-badge.deep { background: var(--deep-soft); color: var(--deep); }
.depth-badge.standard { background: var(--surface-muted); color: var(--muted); }
.tag { border: 1px solid var(--line); color: var(--tertiary); }
.paper-title { display: block; font-size: clamp(17px, 2vw, 21px); font-weight: 650; line-height: 1.28; letter-spacing: -0.025em; }
.paper-tldr { display: block; max-width: 72ch; margin-top: 7px; color: var(--muted); font-size: 13px; line-height: 1.5; }
.paper-visual {
  position: relative;
  grid-area: visual;
  display: block;
  width: 100%;
  height: 112px;
  padding: 5px;
  border: 1px solid var(--line);
  border-radius: 16px;
  background: #ffffff;
  box-shadow: 0 7px 20px rgba(0, 0, 0, 0.08), inset 0 1px 0 rgba(255, 255, 255, 0.75);
  overflow: hidden;
}
.paper-visual img { width: 100%; height: 100%; border-radius: 11px; object-fit: contain; transition: transform 240ms ease-out; }
.paper-card:hover .paper-visual img { transform: scale(1.018); }
.visual-label {
  position: absolute;
  inset: auto 9px 9px auto;
  padding: 3px 7px;
  border: 1px solid rgba(255, 255, 255, 0.54);
  border-radius: 999px;
  background: rgba(29, 29, 31, 0.62);
  -webkit-backdrop-filter: blur(10px);
  backdrop-filter: blur(10px);
  color: #ffffff;
  font-size: 9px;
  font-weight: 650;
  letter-spacing: 0.02em;
}
.paper-score {
  grid-area: score;
  display: flex;
  align-items: baseline;
  justify-content: center;
  min-width: 62px;
  padding: 8px 10px;
  border: 1px solid var(--brand-line);
  border-radius: 15px;
  background: var(--brand-soft);
  color: var(--brand);
}
.paper-score strong { font-size: 24px; font-weight: 650; letter-spacing: -0.052em; }
.paper-score small { color: var(--muted); font-size: 11px; }
.expand-icon { grid-area: icon; color: var(--tertiary); font-size: 18px; transition: transform .2s ease; }
.paper-card[open] .expand-icon { transform: rotate(180deg); }
.paper-body { padding: 0 clamp(24px, 4vw, 52px) 42px 80px; border-top: 1px solid var(--line); background: linear-gradient(180deg, var(--surface-muted), transparent 80px); }
.paper-body > h3 { margin-top: 28px; color: var(--ink); }
.paper-resource-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px 18px; padding: 18px 0 8px; }
.paper-byline { display: flex; flex: 1 1 280px; flex-wrap: wrap; gap: 5px 14px; color: var(--muted); font-size: 11px; }
.paper-byline span { position: relative; }
.paper-byline span + span::before { position: absolute; left: -9px; color: var(--tertiary); content: "·"; }
.paper-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 7px; margin-left: auto; }
.paper-link { display: inline-flex; align-items: center; padding: 8px 13px; border: 1px solid transparent; border-radius: 999px; text-decoration: none; font-size: 12px; font-weight: 650; transition: background-color 160ms ease-out, border-color 160ms ease-out, transform 160ms ease-out; }
.paper-link.primary { background: var(--brand); color: #ffffff; }
.paper-link.primary:hover { background: var(--brand-hover); color: #ffffff; }
.paper-link.secondary { border-color: var(--line); background: var(--surface-solid); color: var(--brand); }
.paper-link.secondary:hover { border-color: var(--brand-line); background: var(--brand-soft); color: var(--brand); }
.paper-link:active { transform: scale(0.975); }
.check { display: inline-grid; place-items: center; width: 17px; height: 17px; margin-right: 7px; border: 1px solid var(--line); border-radius: 5px; }
.check.checked { background: var(--brand); color: #ffffff; }
.empty-state { padding: 40px; color: var(--muted); text-align: center; }

.report-appendix {
  margin-top: 24px;
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  background: var(--surface-solid);
  overflow: clip;
}
.report-appendix > summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 20px 24px;
  cursor: pointer;
  list-style: none;
}
.report-appendix > summary::-webkit-details-marker { display: none; }
.report-appendix > summary span:first-child { display: grid; gap: 2px; }
.report-appendix > summary strong { font-size: 15px; font-weight: 650; }
.report-appendix > summary small { color: var(--muted); font-size: 11px; }
.appendix-icon { color: var(--tertiary); transition: transform 180ms ease-out; }
.report-appendix[open] .appendix-icon { transform: rotate(180deg); }
.appendix-body { border-top: 1px solid var(--line); }
.appendix-intro, .appendix-section { padding: clamp(22px, 3vw, 36px); }
.appendix-intro + .appendix-section, .appendix-section + .appendix-section { border-top: 1px solid var(--line); }
.appendix-section h2 { margin: 0 0 16px; font-size: clamp(20px, 2.4vw, 28px); font-weight: 650; letter-spacing: -0.03em; }
.appendix-section > :last-child, .appendix-intro > :last-child { margin-bottom: 0; }

.footer { display: flex; justify-content: space-between; gap: 20px; margin-top: 30px; padding: 18px 4px; color: var(--muted); font-size: 12px; }

@media (max-width: 900px) {
  .shell { width: min(100% - 24px, 760px); padding-top: 16px; }
  .metrics { grid-template-columns: repeat(2, 1fr); }
  .metric:nth-child(2)::after { display: none; }
  .metric:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
  .layout { grid-template-columns: 1fr; }
  .sidebar { display: none; }
  .paper-tools h2 { flex-basis: 100%; }
  .paper-search { flex: 1 1 100%; }
}

@media (max-width: 720px) {
  .paper-card summary, .paper-card.has-visual summary {
    grid-template-areas: "rank copy score" ". visual visual";
    grid-template-columns: 44px minmax(0, 1fr) auto;
  }
  .paper-card:not(.has-visual) summary { grid-template-areas: "rank copy score"; }
  .paper-visual { height: 160px; margin-top: 2px; }
  .expand-icon { display: none; }
}

@media (max-width: 600px) {
  .shell { width: min(100% - 20px, 560px); padding-top: 10px; }
  .topbar { top: 8px; min-height: 50px; margin-bottom: 14px; border-radius: 16px; }
  .top-actions .control-button { display: none; }
  .hero { padding: 32px 24px; border-radius: 26px; }
  .hero h1 { font-size: 36px; }
  .hero-subtitle { font-size: 16px; }
  .metrics { padding: 4px; border-radius: 20px; }
  .metric { padding: 15px 16px; }
  .metric strong { font-size: 25px; }
  .report-intro, .content-section, .decision-item, .appendix-intro, .appendix-section { padding: 24px 20px; }
  .decision-stack, .report-appendix { border-radius: 20px; }
  .paper-card { border-radius: 20px; }
  .paper-card summary, .paper-card.has-visual summary { grid-template-columns: 38px minmax(0, 1fr) auto; gap: 11px; padding: 18px 16px; }
  .paper-rank { width: 36px; height: 36px; }
  .paper-visual { height: 148px; }
  .paper-score strong { font-size: 22px; }
  .paper-tldr { -webkit-line-clamp: 2; display: -webkit-box; -webkit-box-orient: vertical; overflow: hidden; }
  .paper-body { padding: 0 17px 28px; }
  .paper-resource-bar { align-items: flex-start; padding-top: 15px; }
  .paper-byline { flex-basis: 100%; }
  .paper-actions { justify-content: flex-start; margin-left: 0; }
  .footer { display: block; }
}

@media print {
  .topbar, .sidebar, .paper-tools input, .paper-tools button, .reading-progress { display: none !important; }
  body { background: #fff; color: #111; }
  .shell { width: 100%; padding: 0; }
  .hero, .metrics, .metric, .report-intro, .content-section, .decision-stack, .report-appendix, .paper-card { box-shadow: none; background: #fff; break-inside: avoid; }
  .layout { display: block; }
  .paper-card { margin-bottom: 12px; }
  .paper-card .paper-body { display: block; }
}

@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; }
}

@media (prefers-reduced-transparency: reduce) {
  body { background-image: none; }
  .topbar, .sidebar, .hero { background: var(--surface-solid); -webkit-backdrop-filter: none; backdrop-filter: none; }
  .topbar::before, .sidebar::before, .hero::before { display: none; }
}

@media (prefers-contrast: more) {
  .topbar, .sidebar, .hero, .metrics, .decision-stack, .paper-card, .report-appendix { border-color: var(--line-strong); }
  .muted, .paper-tldr, .brief-item p { color: var(--ink); }
}
"""


def _report_script(has_mermaid: bool) -> str:
    """Return progressive-enhancement JavaScript for report interactions."""
    mermaid_loader = """
const mermaidScript = document.createElement('script');
mermaidScript.src = 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.min.js';
mermaidScript.onload = () => window.mermaid.initialize({ startOnLoad: true, theme: resolvedTheme() === 'dark' ? 'dark' : 'neutral' });
document.head.appendChild(mermaidScript);
""" if has_mermaid else ""
    return f"""
const root = document.documentElement;
const themeToggle = document.getElementById('theme-toggle');
const themeColor = document.querySelector('meta[name="theme-color"]');
const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
let storedTheme = null;
try {{ storedTheme = localStorage.getItem('paperpulse-theme'); }} catch (error) {{ storedTheme = null; }}
if (storedTheme) root.dataset.theme = storedTheme;

const resolvedTheme = () => root.dataset.theme || (systemTheme.matches ? 'dark' : 'light');
const syncThemeButton = () => {{
  const dark = resolvedTheme() === 'dark';
  themeToggle.textContent = dark ? '浅色' : '深色';
  themeToggle.setAttribute('aria-label', dark ? '切换到浅色外观' : '切换到深色外观');
  themeColor.setAttribute('content', dark ? '#000000' : '#f5f5f7');
}};
syncThemeButton();

themeToggle.addEventListener('click', () => {{
  const next = resolvedTheme() === 'dark' ? 'light' : 'dark';
  root.dataset.theme = next;
  try {{ localStorage.setItem('paperpulse-theme', next); }} catch (error) {{ /* Local files may deny storage. */ }}
  syncThemeButton();
}});
if (systemTheme.addEventListener) {{
  systemTheme.addEventListener('change', () => {{ if (!root.dataset.theme) syncThemeButton(); }});
}}

const cards = [...document.querySelectorAll('.paper-card')];
const appendix = document.getElementById('report-appendix');
document.querySelectorAll('.paper-visual img').forEach(image => {{
  const disableVisual = () => {{
    const card = image.closest('.paper-card');
    const visual = image.closest('.paper-visual');
    if (card) card.classList.remove('has-visual');
    if (visual) visual.remove();
  }};
  if (image.complete && image.naturalWidth === 0) disableVisual();
  else image.addEventListener('error', disableVisual, {{ once: true }});
}});
document.getElementById('expand-all').addEventListener('click', () => cards.filter(card => !card.hidden).forEach(card => card.open = true));
document.getElementById('collapse-all').addEventListener('click', () => cards.forEach(card => card.open = false));

document.querySelectorAll('[data-target]').forEach(link => {{
  link.addEventListener('click', event => {{
    if (!appendix) return;
    event.preventDefault();
    appendix.open = true;
    const target = document.getElementById(link.dataset.target);
    requestAnimationFrame(() => (target || appendix).scrollIntoView({{
      behavior: reducedMotion.matches ? 'auto' : 'smooth',
      block: 'start'
    }}));
  }});
}});

const search = document.getElementById('paper-search');
const empty = document.getElementById('empty-state');
search.addEventListener('input', () => {{
  const query = search.value.trim().toLowerCase();
  let visible = 0;
  cards.forEach(card => {{
    card.hidden = query.length > 0 && !card.dataset.search.includes(query);
    if (!card.hidden) visible += 1;
  }});
  empty.hidden = visible !== 0;
}});

const progress = document.getElementById('reading-progress');
const updateProgress = () => {{
  const height = document.documentElement.scrollHeight - window.innerHeight;
  progress.style.width = `${{height > 0 ? (window.scrollY / height) * 100 : 0}}%`;
}};
document.addEventListener('scroll', updateProgress, {{ passive: true }});
updateProgress();

let printOpenStates = [];
let printAppendixOpen = false;
window.addEventListener('beforeprint', () => {{
  printOpenStates = cards.map(card => card.open);
  cards.forEach(card => card.open = true);
  if (appendix) {{ printAppendixOpen = appendix.open; appendix.open = true; }}
}});
window.addEventListener('afterprint', () => {{
  cards.forEach((card, index) => card.open = printOpenStates[index]);
  if (appendix) appendix.open = printAppendixOpen;
}});
{mermaid_loader}
"""


def render_report(markdown: str, source_path: Path, open_top: int) -> str:
    """Create a complete interactive HTML document from one digest."""
    title, prelude, sections = _parse_document(markdown)
    paper_sections = [section for section in sections if section.is_paper]
    regular_sections = [section for section in sections if not section.is_paper]
    date_match = DATE_PATTERN.search(source_path.stem) or DATE_PATTERN.search(title)
    report_date = date_match.group(0) if date_match is not None else source_path.stem
    paper_count = len(paper_sections)
    selected_count = _extract_count(
        markdown,
        (r"入选\s*([0-9]+)\s*篇", r"Selected\s*[:：]\s*([0-9]+)", r"精选\s*([0-9]+)\s*篇"),
        paper_count,
    )
    candidate_count = _extract_count(
        markdown,
        (r"原始收集\s*([0-9]+)\s*条", r"Collected\s*[:：]\s*([0-9]+)", r"([0-9]+)\s*篇新候选"),
        selected_count,
    )
    scores = [meta.score for meta in (_paper_meta(section) for section in paper_sections) if meta.score is not None]
    top_score = max(scores) if scores else None
    deep_count = sum(
        1
        for section in paper_sections
        if "全文" in _paper_meta(section).read_depth or "精读" in _paper_meta(section).read_depth
    )
    reading_minutes = max(1, round(len(markdown) / 900))

    intro_html = _render_blocks(prelude)
    primary_sections = [
        section for section in regular_sections if _section_name(section) in PRIMARY_SECTION_NAMES
    ]
    if not primary_sections:
        fallback = next(
            (
                section
                for section in regular_sections
                if _section_name(section) in {"效果", "结论", "summary", "key findings"}
            ),
            None,
        )
        if fallback is not None:
            primary_sections = [fallback]
    primary_ids = {id(section) for section in primary_sections}
    supporting_sections = [
        section
        for section in regular_sections
        if id(section) not in primary_ids and _section_name(section) not in REDUNDANT_SECTION_NAMES
    ]

    decision_html = "\n".join(
        f'<article class="decision-item" id="{html.escape(section.anchor, quote=True)}">'
        f'<div class="decision-label">{_render_inline(section.title)}</div>'
        f"{_render_blocks(section.body)}</article>"
        for section in primary_sections
    )
    appendix_sections_html = "\n".join(
        f'<section class="appendix-section" id="{html.escape(section.anchor, quote=True)}">'
        f"<h2>{_render_inline(section.title)}</h2>{_render_blocks(section.body)}</section>"
        for section in supporting_sections
    )
    appendix_intro_html = (
        f'<div class="appendix-intro">{intro_html}</div>' if intro_html.strip() else ""
    )
    appendix_html = (
        '<details class="report-appendix" id="report-appendix">'
        '<summary><span><strong>报告背景与数据源</strong>'
        '<small>查看完整背景、筛选流程、效果与数据源状态</small></span>'
        '<span class="appendix-icon" aria-hidden="true">⌄</span></summary>'
        '<div class="appendix-body">'
        f"{appendix_intro_html}"
        f"{appendix_sections_html}</div></details>"
        if intro_html.strip() or appendix_sections_html.strip()
        else ""
    )
    paper_html = "\n".join(
        _render_paper_card(section, index, open_top) for index, section in enumerate(paper_sections, start=1)
    )
    sidebar_brief_html = _render_sidebar_brief(supporting_sections)
    toc_papers = "".join(
        f'<a class="paper-toc" href="#{html.escape(section.anchor, quote=True)}">'
        f"{index:02d} · {html.escape(_truncate(section.paper_title or section.title, 42))}</a>"
        for index, section in enumerate(paper_sections, start=1)
    )
    top_score_display = f"{top_score:.1f}" if top_score is not None else "—"
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %Z")
    has_mermaid = 'class="mermaid"' in appendix_html or 'class="mermaid"' in paper_html

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#f5f5f7">
  <meta name="description" content="PaperPulse daily research intelligence report for {html.escape(report_date, quote=True)}">
  <title>{html.escape(title)} · PaperPulse</title>
  <style>{_report_css()}</style>
</head>
<body>
  <div class="reading-progress" id="reading-progress"></div>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 32 32" focusable="false">
            <circle class="pulse-ring" cx="16" cy="16" r="13"></circle>
            <path class="pulse-wave" d="M3 16h5l2.4-4.2 3.4 9 4.2-14 3.2 9.2H29"></path>
          </svg>
        </span>
        <span>PaperPulse</span>
      </div>
      <div class="top-actions">
        <button class="control-button" id="collapse-all" type="button">全部收起</button>
        <button class="control-button" id="expand-all" type="button">全部展开</button>
        <button class="icon-button" id="theme-toggle" type="button" aria-label="切换深浅主题">外观</button>
      </div>
    </header>

    <section class="hero">
      <div class="eyebrow">Daily Research Intelligence</div>
      <h1>{html.escape(title)}</h1>
      <p class="hero-subtitle">先看决策信号，再按需展开论文证据。精读内容、实验结果和落地建议集中在卡片内部。</p>
      <span class="hero-date">{html.escape(report_date)}</span>
    </section>

    <section class="metrics" aria-label="日报关键指标">
      <div class="metric"><span>候选论文</span><strong>{candidate_count}</strong></div>
      <div class="metric"><span>最终入选</span><strong>{selected_count}</strong></div>
      <div class="metric"><span>全文精读</span><strong>{deep_count}</strong></div>
      <div class="metric"><span>最高评分</span><strong>{top_score_display}</strong></div>
    </section>

    <div class="layout">
      <aside class="sidebar">
        <div class="sidebar-title">今日速览</div>
        <div class="sidebar-brief">{sidebar_brief_html}</div>
        <div class="sidebar-title sidebar-paper-title">论文导航</div>
        <nav class="toc">{toc_papers}</nav>
      </aside>

      <main class="content">
        {f'<section class="decision-stack" id="daily-brief">{decision_html}</section>' if decision_html.strip() else ''}

        <div class="paper-tools" id="papers">
          <h2>论文精读卡片</h2>
          <input class="paper-search" id="paper-search" type="search" placeholder="搜索标题或分类" aria-label="搜索论文">
          <button class="control-button" id="expand-all-inline" type="button" onclick="document.getElementById('expand-all').click()">展开</button>
        </div>
        <div class="paper-list">{paper_html}</div>
        <div class="empty-state" id="empty-state" hidden>没有匹配的论文卡片。</div>
        {appendix_html}
      </main>
    </div>

    <footer class="footer">
      <span>PaperPulse · Evidence before confidence</span>
      <span>约 {reading_minutes} 分钟阅读 · 生成于 {html.escape(generated_at)}</span>
    </footer>
  </div>
  <script>{_report_script(has_mermaid)}</script>
</body>
</html>
"""


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Markdown digest path")
    parser.add_argument("--output", type=Path, help="HTML output path; defaults beside the source")
    parser.add_argument(
        "--open-top",
        type=int,
        choices=range(0, 11),
        default=1,
        help="Number of leading paper cards expanded initially",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Validate paths, render the digest, and write UTF-8 HTML."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = build_parser().parse_args(argv)
    source = args.source.expanduser().resolve()
    if not source.is_file() or source.suffix.lower() != ".md":
        LOGGER.error("Source must be an existing Markdown file: %s", source)
        return 2
    output = (args.output or source.with_suffix(".html")).expanduser().resolve()
    if output.suffix.lower() != ".html":
        LOGGER.error("Output must use the .html extension: %s", output)
        return 2
    if source == output:
        LOGGER.error("Source and output paths must differ")
        return 2
    try:
        markdown = source.read_text(encoding="utf-8")
        report = render_report(markdown, source, args.open_top)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        LOGGER.exception("Unable to render digest: %s", error)
        return 1
    LOGGER.info("Rendered %s", output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
