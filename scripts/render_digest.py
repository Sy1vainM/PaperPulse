#!/usr/bin/env python3
"""Render a PaperPulse Markdown digest as an interactive HTML report."""

from __future__ import annotations

import argparse
import html
import json
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import quote, urlparse


LOGGER = logging.getLogger("paperpulse.renderer")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
FIGURE_PATTERN = re.compile(r"!\[([^]\n]*)]\((\S+)\)")
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
    "今日判断与行动",
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
    """Accept HTTP(S) or document-relative image paths."""
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if (parsed.scheme or parsed.netloc or not parsed.path or value.startswith("/")
            or "\\" in value or any(ord(c) < 32 for c in value)):
        return None
    return value


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
    if FIGURE_PATTERN.fullmatch(line.strip()):
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

        figure = FIGURE_PATTERN.fullmatch(line.strip())
        if figure:
            caption = html.escape(figure[1] or "论文配图")
            image_url = _safe_image_url(figure[2])
            if image_url:
                url = html.escape(image_url, quote=True)
                output.append(
                    f'<figure class="evidence-figure"><img src="{url}" alt="{caption}" loading="lazy">'
                    f'<figcaption>{caption} · <a href="{url}" target="_blank" rel="noopener noreferrer">'
                    '查看原图</a></figcaption></figure>'
                )
            else:
                output.append(f"<p>{caption}</p>")
            index += 1
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
            for item in re.split(r"[,，、]|\s+/\s+", _strip_markdown(category_match.group(1)))
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
    summary = _section_text(section.body, ("一句话总结", "TL;DR", "核心结论", "核心突破与做法"))
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


def _extract_count(markdown: str, patterns: Sequence[str], fallback: Optional[int]) -> Optional[int]:
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
    score_value = format(meta.score, ".2f").rstrip("0").rstrip(".") if meta.score is not None else "—"
    category_badges = "".join(f'<span class="tag">{html.escape(item)}</span>' for item in meta.categories)
    depth_class = "deep" if "全文" in meta.read_depth or "精读" in meta.read_depth else "standard"
    opened = " open" if index <= open_top else ""
    body = _render_blocks(_prepare_paper_body(section.body))
    if meta.image_url and not any(
        (m := FIGURE_PATTERN.fullmatch(line.strip())) and m[2] == meta.image_url for line in section.body
    ):
        caption = section.paper_title + " · 论文主图"
        body = _render_blocks([f"![{caption}]({meta.image_url})"]) + body

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
<details class="paper-card" id="{html.escape(section.anchor, quote=True)}"
         data-score="{score_value}" data-depth="{html.escape(depth_class, quote=True)}"
         data-search="{html.escape((section.paper_title + ' ' + ' '.join(meta.categories)).lower(), quote=True)}"{opened}>
  <summary>
    <span class="paper-rank">{index:02d}</span>
    <span class="paper-summary-copy">
      <span class="paper-badges"><span class="depth-badge {depth_class}">{html.escape(meta.read_depth)}</span>{category_badges}</span>
      <span class="paper-title">{html.escape(section.paper_title)}</span>
      <span class="paper-tldr">{html.escape(meta.summary)}</span>
    </span>
    <span class="paper-score"><strong>{score_value}</strong><small>/10</small></span>
    <span class="expand-icon" aria-hidden="true">⌄</span>
  </summary>
  <div class="paper-body">
    {resource_bar}
    {body}
  </div>
</details>"""


def _report_css() -> str:
    return """
:root {
  color-scheme:light;
  --bg:#f3f7fa;
  --ink:#152e42;
  --muted:#485f70;
  --paper:#fff;
  --rule:#cbd9e2;
  --blue:#185680;
  --pale:#e8f1f7;
  --accent:#a35b20
}
:root[data-theme=dark] {
  color-scheme:dark;
  --bg:#101d27;
  --ink:#edf5fa;
  --muted:#acc2d0;
  --paper:#192b38;
  --rule:#3b5362;
  --blue:#98d2f5;
  --pale:#233c4e;
  --accent:#edb176
}
* {
  box-sizing:border-box
}
body {
  margin:0;
  background:var(--bg);
  color:var(--ink);
  font:16px/1.55 "Inter",-apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif
}
main,.topbar,footer {
  width:min(1320px,94%);
  margin:auto
}
h1,h2,h3,p {
  margin-block:0 .6em
}
h1 {
  font-size:clamp(28px,3vw,42px);
  letter-spacing:-.045em;
  line-height:1.1
}
h2 {
  font-size:22px;
  letter-spacing:-.03em
}
.topbar,.mast,.filters,.paper-tools,.paper-actions,.byline,.top-actions,.paper-badges {
  display:flex;
  align-items:center;
  gap:10px;
  flex-wrap:wrap
}
.topbar {
  justify-content:space-between;
  padding:15px 0;
  border-bottom:1px solid var(--rule)
}
.brand {
  font-size:21px;
  font-weight:750;
  letter-spacing:-.05em;
  text-decoration:none
}
.brand b {
  color:var(--blue)
}
a {
  color:var(--blue);
  text-underline-offset:3px
}
button,input {
  font:inherit;
  color:inherit
}
button,.chip,input {
  border:1px solid var(--rule);
  background:var(--paper);
  border-radius:7px;
  padding:5px 10px;
  font-size:13px
}
button,summary {
  cursor:pointer
}
button:hover,a:hover {
  color:var(--blue)
}
button[aria-pressed=true] {
  background:var(--blue);
  color:var(--paper);
  border-color:var(--blue)
}
:focus-visible {
  outline:3px solid var(--blue);
  outline-offset:3px
}
.mast {
  padding:18px 0;
  justify-content:space-between
}
.mast h1 {
  font-size:26px
}
.mast p {
  margin:0;
  color:var(--muted)
}
.chip {
  display:inline-block;
  color:var(--muted);
  text-decoration:none
}
.decision-stack,.paper-card,.report-appendix,.industry,.archive-card,.scan {
  background:var(--paper);
  border:1px solid var(--rule);
  border-radius:12px
}
.decision-stack {
  padding:15px 20px;
  border-left:4px solid var(--blue)
}
.decisions {
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(min(330px,100%),1fr));
  gap:20px
}
.decisions summary {
  font-weight:550
}
.decision-label,.tag,.depth-badge,.report-meta,.paper-byline,.paper-rank,figcaption,.count {
  font-size:13px;
  color:var(--muted)
}
.decision-label {
  color:var(--blue);
  font-weight:650
}
.decisions p {
  margin:2px 0
}
.decision-stack h2 {
  font-size:19px
}
.scan {
  margin:16px 0;
  overflow:hidden
}
.scan-head,.paper-tools {
  display:flex;
  align-items:center;
  justify-content:space-between;
  gap:10px;
  padding:12px 16px
}
.scan-head h2,.paper-tools h2 {
  margin:0
}
.filters {
  padding:0 16px 10px;
  gap:5px
}
.filters button {
  font-size:12px;
  padding:3px 8px
}
.table-wrap {
  overflow:auto
}
table {
  width:100%;
  border-collapse:collapse;
  text-align:left;
  font-size:14px
}
th,td {
  padding:7px 10px;
  border-top:1px solid var(--rule);
  vertical-align:middle
}
thead {
  background:var(--pale);
  color:var(--muted)
}
.scan table {
  table-layout:fixed
}
.scan th:nth-child(1) {
  width:14%
}
.scan th:nth-child(2) {
  width:28%
}
.scan th:nth-child(4) {
  width:7%
}
.scan th:nth-child(5) {
  width:5%
}
.scan td {
  font-size:13px;
  padding:6px 10px
}
.scan td span,.scan td a {
  display:block;
  white-space:nowrap;
  overflow:hidden;
  text-overflow:ellipsis
}
.scan td a {
  font-weight:650
}
.scan td:last-child {
  font-variant-numeric:tabular-nums;
  font-weight:700;
  color:var(--blue)
}
.paper-tools {
  padding-inline:0
}
.paper-card,.report-appendix,.industry {
  margin-bottom:10px;
  scroll-margin-top:12px
}
.paper-card>summary {
  display:flex;
  align-items:center;
  gap:18px;
  padding:15px 20px
}
.paper-summary-copy {
  flex:1;
  min-width:0
}
.paper-title,.paper-tldr {
  display:block
}
.paper-title {
  font-size:19px;
  font-weight:680
}
.paper-tldr {
  color:var(--muted);
  margin-top:4px
}
.depth-badge.deep {
  color:var(--accent)
}
.paper-score small {
  font-size:11px;
  color:var(--muted)
}
.paper-body,.appendix-body,.industry {
  padding:20px clamp(15px,4vw,60px);
  overflow-wrap:anywhere
}
.paper-body {
  border-top:1px solid var(--rule)
}
.paper-body h3 {
  margin-top:1.5em
}
.paper-body p {
  max-width:95ch
}
.paper-resource-bar {
  display:grid;
  gap:8px
}
.paper-byline span {
  margin-right:12px
}
.paper-link {
  font-size:14px
}
figure {
  margin:20px 0;
  background:var(--bg);
  padding:12px;
  border-radius:8px
}
figure img {
  display:block;
  max-width:100%;
  max-height:75vh;
  margin:auto;
  object-fit:contain
}
figcaption {
  margin:8px 0 0
}
pre {
  white-space:pre-wrap;
  overflow-wrap:anywhere;
  background:var(--pale);
  padding:12px
}
blockquote {
  border-left:3px solid var(--rule);
  margin-left:0;
  padding-left:15px
}
.report-appendix>summary {
  padding:14px 20px
}
.report-appendix small {
  margin-left:12px;
  color:var(--muted)
}
footer {
  padding:25px 0;
  color:var(--muted)
}
[hidden] {
  display:none!important
}
.archive {
  max-width:1060px
}
.archive header {
  margin:34px 0 18px
}
.archive input {
  width:min(100%,510px);
  padding:10px 12px
}
.archive-card {
  display:grid;
  gap:3px;
  padding:12px 18px;
  margin:6px 0;
  color:inherit;
  text-decoration:none
}
.archive-card:hover {
  border-color:var(--blue)
}
.archive-card time {
  font-size:13px;
  color:var(--blue);
  font-variant-numeric:tabular-nums
}
.month-group {
  margin:24px 0
}
.month-group h2 {
  font-size:18px
}
.empty-state {
  padding:16px
}
@media(max-width:760px) {
  .scan table {
    width:850px
  }
  .mast {
    align-items:flex-start
  }
  .decisions {
    grid-template-columns:1fr
  }
  .paper-score {
    display:none
  }
  .paper-card>summary {
    padding:12px;
    gap:8px
  }
}
@media print {
  .top-actions,.filters,.paper-tools input {
    display:none
  }
}
"""



THEME_SCRIPT = """
const root = document.documentElement;
const theme = document.querySelector('#theme-toggle');
try { if(localStorage.getItem('paperpulse-theme')==='dark') root.dataset.theme='dark'; } catch {}
function syncTheme(){
  document.querySelector('meta[name="color-scheme"]').content=root.dataset.theme;
  theme.textContent=root.dataset.theme==='dark'?'浅色':'深色';theme.setAttribute('aria-label','切换为'+theme.textContent+'主题')}
theme.addEventListener('click',()=>{root.dataset.theme=root.dataset.theme==='dark'?'light':'dark';
  try{localStorage.setItem('paperpulse-theme',root.dataset.theme)}catch{} syncTheme()});
syncTheme();
"""

DAILY_SCRIPT = """
const rows=[...document.querySelectorAll('[data-paper]')];
const buttons=[...document.querySelectorAll('[data-category]')];
const query=document.querySelector('#paper-search');
let category='';
function filter(){
  let count=0;
  for(const row of rows){
    const card=document.getElementById(row.dataset.paper);
    const categoryMatches = !category || JSON.parse(row.dataset.categories).includes(category);
    const searchable = (row.textContent + ' ' + card.dataset.search).toLowerCase();
    const match = categoryMatches && searchable.includes(query.value.trim().toLowerCase());
    row.hidden=card.hidden=!match;
    if(match)count++;
  }
  document.querySelector('#count').textContent=count+' / '+rows.length+' 篇';
  document.querySelector('#empty-state').hidden=count>0;
}
buttons.forEach(button=>button.addEventListener('click',()=>{
  category=button.dataset.category;
  buttons.forEach(b=>b.setAttribute('aria-pressed',String(b===button)));filter()
}));
query.addEventListener('input',filter);
document.querySelectorAll('.scan a').forEach(link=>link.addEventListener('click',event=>{
  event.preventDefault();const card=document.getElementById(link.closest('tr').dataset.paper);
  card.open=true;card.querySelector('summary').focus({preventScroll:true});
  card.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
}));
for(const open of [true,false]) document.getElementById(open?'expand-all':'collapse-all').onclick=()=>{
  for(const card of document.querySelectorAll('.paper-card:not([hidden])'))card.open=open;
};
let printState = [];
window.addEventListener('beforeprint', () => {
  printState = [...document.querySelectorAll('details')].map(node => [node, node.open]);
  for (const [node] of printState) node.open = true;
});
window.addEventListener('afterprint', () => {
  for (const [node, open] of printState) node.open = open;
});
document.querySelectorAll('[data-appendix]').forEach(a=>a.onclick=()=>{document.querySelector('#report-appendix').open=true});
"""


def page(title, body, script):
    return f"""<!doctype html>
<html lang="zh-CN" data-theme="light"><head><meta charset="utf-8">
<meta name="color-scheme" content="light"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(title)} · PaperPulse</title>
<style>{_report_css()}</style></head><body>
<header class="topbar"><a class="brand" href="index.html" aria-label="返回日报列表">Paper<b>Pulse</b></a>
<div class="top-actions"><a href="index.html">历史日报</a><button id="theme-toggle">深色</button></div></header>
{body}<script>{THEME_SCRIPT}{script}</script></body></html>"""


def render_report(markdown: str, source_path: Path, open_top: int) -> str:
    title, prelude, sections = _parse_document(markdown)
    date_match = DATE_PATTERN.search(source_path.stem) or DATE_PATTERN.search(title)
    day = date_match[0] if date_match else title
    papers = [s for s in sections if s.is_paper]
    decisions = [s for s in sections if _section_name(s) in PRIMARY_SECTION_NAMES]
    if not decisions:
        decisions = [s for s in sections if _section_name(s) in {"效果", "结论", "summary", "key findings"}][:1]
    industry = [s for s in sections if s.title.startswith("行业与开源速递")]
    appendix = [s for s in sections if not s.is_paper and s not in decisions+industry and _section_name(s) not in REDUNDANT_SECTION_NAMES]
    source = next((s for s in appendix if _section_name(s) in {"数据源状态", "sources", "source status"}), None)
    health_html = ""
    if source:
        health = _source_health(source)
        states = ((health.successful,"正常"),(health.partial,"部分"),(health.failed,"失败"),
                  (health.disabled,"停用"),(health.skipped,"未运行"),(health.unknown,"未知"))
        health_html = f'<a class="chip" data-appendix href="#{source.anchor}">信源 · ' + " / ".join(f"{n} {label}" for n,label in states if n) + '</a>'
    candidate = _extract_count(markdown,(r"Collected\s*[:：]\s*(\d+)",r"原始收集\s*(\d+)\s*条",r"(\d+)\s*篇新候选"),None)
    rows, categories = [], []
    deep = 0
    for s in papers:
        m = _paper_meta(s)
        deep += int("全文" in m.read_depth or "精读" in m.read_depth)
        for cat in m.categories:
            if cat not in categories:
                categories.append(cat)
        names = html.escape(" · ".join(m.categories) or "未标注")
        name = html.escape(s.paper_title)
        summary = html.escape(m.summary)
        score = format(m.score, ".2f").rstrip("0").rstrip(".") if m.score is not None else "—"
        rows.append(f'<tr data-paper="{s.anchor}" data-categories="{html.escape(json.dumps(m.categories, ensure_ascii=False),quote=True)}">'
                    f'<td><span title="{names}">{names}</span></td><td><a href="#{s.anchor}" title="{name}">{name}</a></td>'
                    f'<td><span title="{summary}">{summary}</span></td><td>{html.escape(m.read_depth)}</td><td>{score}</td></tr>')
    filters = '<button data-category="" aria-pressed="true">全部</button>' + "".join(
        f'<button data-category="{html.escape(c)}" aria-pressed="false">{html.escape(c)}</button>' for c in categories)
    decision_body = "".join(f'<details><summary><span class="decision-label">{html.escape(s.title)}</span><br>'
                            f'{html.escape(_first_readable_line(s.body))}</summary>{_render_blocks(s.body)}</details>' for s in decisions)
    decision_html = f'<section class="decision-stack"><h2>今日判断与行动</h2><div class="decisions">{decision_body}</div></section>' if decisions else ""
    briefs = "".join(f'<section class="industry"><h2>{html.escape(s.title)}</h2>{_render_blocks(s.body)}</section>' for s in industry)
    appendix_body = _render_blocks(prelude) + "".join(f'<section id="{s.anchor}"><h2>{html.escape(s.title)}</h2>{_render_blocks(s.body)}</section>' for s in appendix)
    appendix_html = f'<details class="report-appendix" id="report-appendix"><summary>报告背景与数据源</summary><div class="appendix-body">{appendix_body}</div></details>' if appendix_body else ""
    cards = "".join(_render_paper_card(s,i,open_top) for i,s in enumerate(papers,1))
    headers = "".join(f'<th scope="col">{h}</th>' for h in ("研究方向","论文","一句话结论","阅读深度","评分"))
    return page(title,f"""<main><header class="mast"><h1>{html.escape(day)} 研究晨读</h1>
<p>候选 <b>{candidate if candidate is not None else '未记录'}</b>　入选 <b>{len(papers)}</b>　精读 <b>{deep}</b>　{health_html}</p></header>
{decision_html}<section class="scan" aria-labelledby="scan-title"><div class="scan-head"><h2 id="scan-title">今日论文速览</h2>
<span class="count" id="count" aria-live="polite">{len(papers)} / {len(papers)} 篇</span></div>
<div class="filters" role="group" aria-label="按研究方向筛选">{filters}
<input id="paper-search" type="search" aria-label="搜索论文" placeholder="搜索论文"></div>
<div class="table-wrap"><table aria-label="今日论文速览"><thead><tr>{headers}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p class="empty-state" id="empty-state" hidden>没有匹配的论文。</p></section>{briefs}
<div class="paper-tools"><h2>逐篇阅读</h2><div><button id="expand-all">全部展开</button> <button id="collapse-all">全部收起</button></div></div>
{cards}{appendix_html}</main>""", DAILY_SCRIPT)


def archive_meta(path):
    source = path.with_suffix(".md")
    if not source.exists():
        return "", [], [], ""
    _, _, sections = _parse_document(source.read_text(encoding="utf-8"))
    papers = [s for s in sections if s.is_paper]
    top = sorted(papers, key=lambda s: _paper_meta(s).score or 0, reverse=True)[:3]
    directions = list(dict.fromkeys(c for s in top for c in _paper_meta(s).categories))
    theme = next((_first_readable_line(s.body) for name in
                  ("今日判断与行动", "今日决策", "今日结论", "结论", "效果", "背景")
                  for s in sections if _section_name(s) == name), "")
    keywords = " ".join(f"{s.paper_title} {' '.join(_paper_meta(s).categories)}" for s in papers)
    return theme or " · ".join(directions), [s.paper_title for s in top], directions, keywords


def render_archive_index(report_paths: Sequence[Path]) -> str:
    entries = {}
    for path in sorted(report_paths):
        if not DATE_PATTERN.fullmatch(path.stem) or path.suffix not in (".html",".md"):
            continue
        try:
            datetime.strptime(path.stem,"%Y-%m-%d")
        except ValueError:
            continue
        if path.stem not in entries or path.suffix == ".html":
            entries[path.stem] = path
    groups = {}
    for day,path in sorted(entries.items(),reverse=True):
        theme, top, directions, keywords = archive_meta(path)
        terms = " ".join([day, theme, keywords, *top, *directions]).lower()
        meta = " · ".join(top)
        label = theme or day
        tags = " · ".join(directions)
        groups.setdefault(day[:7],[]).append(
            f'<a class="archive-card" data-search="{html.escape(terms)}" href="{quote(path.name)}"><time>{day}</time>'
            f'<strong>{html.escape(label)}</strong><span class="report-meta">{html.escape(tags)}</span>'
            f'<span class="report-meta">{html.escape(meta)}</span></a>')
    body = "".join(f'<section class="month-group"><h2>{month}</h2>{"".join(items)}</section>' for month,items in groups.items())
    return page("历史日报",f"""<main class="archive"><header><h1>历史日报</h1><p><strong>{len(entries)}</strong> 份报告</p>
<input id="archive-search" type="search" aria-label="搜索历史日报" placeholder="搜索标题、关键词、方向或日期"></header>
{body}<p id="archive-empty" {'hidden' if entries else ''}>没有匹配的日报。</p></main>""", """
const groups=document.querySelectorAll('.month-group');
document.querySelector('#archive-search').oninput=event=>{
 const terms=event.target.value.toLowerCase().trim().split(/\\s+/);
 let visible=0;
 for(const group of groups){
   const cards=[...group.querySelectorAll('.archive-card')];
   for(const card of cards){card.hidden=!terms.every(x=>card.dataset.search.includes(x));if(!card.hidden)visible++}
   group.hidden=cards.every(c=>c.hidden);
 }
 document.querySelector('#archive-empty').hidden=visible>0;
};""")



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
    archive_index: Optional[Path] = None
    try:
        markdown = source.read_text(encoding="utf-8")
        report = render_report(markdown, source, args.open_top)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(report, encoding="utf-8")
        if DATE_PATTERN.fullmatch(source.stem) and output.name != "index.html":
            archive_index = output.parent / "index.html"
            report_paths = [*output.parent.glob("????-??-??.html"), *output.parent.glob("????-??-??.md")]
            archive_index.write_text(render_archive_index(report_paths), encoding="utf-8")
    except (OSError, UnicodeError, ValueError) as error:
        LOGGER.exception("Unable to render digest: %s", error)
        return 1
    LOGGER.info("Rendered %s", output)
    if archive_index is not None:
        LOGGER.info("Updated report archive %s", archive_index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
