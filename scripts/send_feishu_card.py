"""Render a daily digest as a Feishu card; delivery requires an explicit --send."""
from __future__ import annotations

import argparse
from datetime import date
import html
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

if __package__:
    from . import render_digest as digest
else:
    import render_digest as digest

ROOT = Path(__file__).resolve().parents[1]
GAP = "0px 0px 12px 0px"
LINK = re.compile(r"\[([^]\n]+)]\((https?://[^()\s]+)\)")
DIRECTIONS = {"运动重建与人体动力学": "运动重建", "视频生成与可交互世界模型": "视频生成", "结构化视频感知": "结构化感知", "生产级 VLM 系统": "生产 VLM", "高效 Video/VLM 系统": "高效 VLM"}


def clean(value, limit, sentence=False):
    value = LINK.sub(r"\1", value)
    value = re.sub(r"^\s*(?:[-*+]\s+|\d+[.、)]\s*)", "", value)
    value = re.sub(r"<[^>]+>|[*\x60~]", "", value)
    value = " ".join(value.split()).strip()
    if sentence:
        value = re.split(r"(?<=[。！？])|(?<=\.)\s+(?=[A-Z])", value, maxsplit=1)[0]
    return value if len(value) <= limit else value[:limit-1].rstrip() + "…"


def safe_text(value):
    if re.search(r"/Users/|(?:ou_|oc_)[a-f0-9]{16,}|cli_[a-f0-9]{12,}", value, re.I):
        raise ValueError("Private identifier or personal path in card")
    value = html.escape(value, quote=False)
    return re.sub(r"([\\\[\]*_\x60~])", r"\\\1", value)


def linked(title, url):
    label = safe_text(clean(title, 160))
    if url and urlsplit(url).scheme in ("https", "http") and urlsplit(url).hostname and not re.search(r"[\s<>\\]", url):
        return f"[{label}]({url.replace('(', '%28').replace(')', '%29')})"
    return label


def prose(lines):
    """Extract report sentences, omitting scoring metadata, captions, and tables."""
    for line in lines:
        line = line.strip()
        if (not line or line.startswith(("#", "|", "!", "作者图", "图注", "五维分", "五维评分"))
                or digest.PRESENTATION_META_PATTERN.match(line)
                or re.match(r"^\*{0,2}(?:分类|方向|Category|Read Depth|阅读深度)\b", line, re.I)):
            continue
        line = re.sub(r"^\[(?:原文|摘要及图)[^]]*\]\([^)]+\)\s*[:：]\s*", "", line)
        text = clean(line, len(line) + 1)
        yield from (x.strip() for x in re.split(r"(?<=[。！？])|(?<=\.)\s+(?=[A-Z])", text) if x.strip())


def result_excerpt(lines):
    """Keep comparison headers attached to their data, including units and conditions."""
    header = []
    for line in lines:
        if not line.strip().startswith("|"):
            header = []
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not header:
            header = cells
        elif len(cells) == len(header) and any(re.search(r"\d", c) for c in cells[1:]):
            detail = [label + " " + value for label, value in zip(header[1:], cells[1:])]
            if header[-1] in {"解读", "正确解读", "判断", "边界"}:
                detail[-1] = cells[-1]
            statement = cells[0] + "：" + "，".join(detail) + "。"
            if len(statement) <= 85:
                return statement
    sentences = list(prose(lines))
    for sentence in sentences:
        if re.search(r"提高|降低|提升|下降|更差|高于|低于|仅限|不能|尚未|不适用", sentence):
            return sentence
    return next(iter(sentences), "")


def micro_summary(lines):
    fields = {"": []}
    heading = ""
    for line in lines:
        if line.startswith("### "):
            heading = line[4:].strip().strip("*")
        else:
            fields.setdefault(heading, []).append(line)

    def field(*names):
        return next((fields[name] for name in names if fields.get(name)), [])

    intro = list(prose(field("一句话总结", "核心结论", "TL;DR")))
    method = list(prose(field("方法", "方法拆解", "技术路线", "核心突破与做法")))
    evidence = field("实验结果", "关键证据与适用边界", "实验与证据", "核心发现", "局限与风险", "局限", "工程启示")
    if not (intro or method or evidence):
        return clean("".join(list(prose(lines))[:3]), 160), "", ""
    core = (intro or method or list(prose(fields[""])) or [""])[0]
    method_line = next((x for x in method if x != core), "")
    core = clean(core, 80)
    method_line = clean(method_line, 95)
    result = clean(result_excerpt(evidence), 85)
    # Prefer a complete result over clipping its last qualifier to meet the target.
    budget = 200 - len(core) - len(result)
    if len(method_line) > budget:
        prefix = re.split(r"[，；]", method_line[:budget])
        method_line = "，".join(prefix[:-1]) + "。" if len(prefix) > 1 else clean(method_line, budget)
    return core, method_line, result


def digest_data(markdown):
    _, _, sections = digest._parse_document(markdown)
    papers, news, decisions = [], [], []
    editorial = []
    grouped = False
    deep = 0
    four_section = False
    marked_deep = 0

    def add(title, url, lines, section_depth=False):
        section = digest.Section(title, tuple(lines), "", title, url)
        meta = digest._paper_meta(section)
        summary, method, evidence = micro_summary(lines)
        papers.append(dict(title=title, url=url, categories=meta.categories,
                           summary=summary, method=method, evidence=evidence))
        return int(section_depth)

    for section in sections:
        title = section.title.strip()
        if section.is_paper:
            four_section |= any(line.strip() == "### 核心突破与做法" for line in section.body)
            depth = digest._paper_meta(section).read_depth
            marked_deep += int("全文精读" in depth or "全文深读" in depth)
            add(section.paper_title, section.paper_url, section.body)
        elif re.match(r"^(核心精读|精选速览)", title):
            grouped = True
            current = None
            lines = []
            for line in (*section.body, "### "):
                heading = re.match(r"^###\s+(.*)", line)
                # Grouped digests also allow compact linked list entries.
                if not heading and re.match(r"^\s*(?:[-*]|\d+[.)、])\s+\[", line):
                    heading = re.match(r"^\s*(?:[-*]|\d+[.)、])\s+(.*)", line)
                if heading:
                    if current:
                        deep += add(*current, lines, title.startswith("核心精读"))
                    text = re.sub(r"^\d+[.、)]\s*", "", heading[1]).strip()
                    link = LINK.search(text)
                    current = (link[1], link[2]) if link else (text, None)
                    lines = [text[link.end():].lstrip(" ：:—-")] if link else []
                else:
                    lines.append(re.sub(r"^####\s", "### ", line))
        elif re.match(r"今日\s*(?:3|三)\s*条判断", title):
            decisions.extend(clean(s, 60, True) for s in section.body if s.strip())
        elif title == "今日决策":
            editorial = [clean(s, 60, True) for s in section.body if re.match(r"^\s*(?:\d+[.)、]|[-*])\s+", s)]
        elif title.startswith("行业与开源速递"):
            for line in section.body:
                links = list(LINK.finditer(line))
                primary = next((l for l in links if urlsplit(l[2]).hostname not in {"mp.weixin.qq.com", "weixin.qq.com"}), None)
                if primary:
                    news.append((clean(line.strip(" |"), 90), primary[2]))
    match = re.search(r"(?:Collected|候选总数|候选数)\s*[:：]\s*([\d,]+)", markdown, re.I)
    return papers, (decisions or editorial)[:3], news, deep if grouped else marked_deep if four_section else None, int(match[1].replace(",", "")) if match else None


def md(content, **style):
    return dict(tag="markdown", content=content, **style)


def plain(content):
    return dict(tag="plain_text", content=content)


def box(heading, children, tinted=False):
    return dict(tag="interactive_container", width="fill", has_border=True,
                border_color="blue-100" if tinted else "grey-200", corner_radius="8px",
                background_style="blue-50" if tinted else "bg-white", padding="12px 12px 12px 12px",
                vertical_spacing="4px" if tinted else "8px", margin=GAP,
                elements=[md(f"**<font color='blue'>{heading}</font>**"), *children])


def build_card(markdown, day):
    papers, decisions, news, deep, candidates = digest_data(markdown)
    directions = {c for p in papers for c in p["categories"]}
    metrics = [(len(papers), "入选论文"), (deep, "核心精读") if deep is not None else (len(directions), "覆盖方向"),
               (candidates, "候选总数") if candidates is not None else (len(news), "微信速递")]
    columns = [dict(tag="column", width="weighted", weight=1, background_style="grey-50",
                    padding="12px", vertical_spacing="2px", elements=[
                        md(f"## <font color='{color}'>{n}</font>", text_align="center"),
                        md(f"<font color='grey'>{label}</font>", text_align="center", text_size="notation")])
               for (n, label), color in zip(metrics, ("blue", "wathet", "indigo"))]
    blocks = [dict(tag="column_set", flex_mode="none", horizontal_spacing="12px", columns=columns, margin=GAP)]
    if decisions:
        blocks.append(box("今日核心判断", [md(f"{i}. {safe_text(s)}") for i,s in enumerate(decisions, 1)], True))
    preview_count = 3 if decisions else 5
    remaining = papers[preview_count:]
    top = []
    for p in papers[:preview_count]:
        cat = next(iter(p["categories"]), "论文")
        tag = safe_text(DIRECTIONS.get(cat, clean(cat, 12)))
        description = [f"<text_tag color='blue'>{tag}</text_tag> **{linked(p['title'],p['url'])}**"]
        if p["summary"]:
            description.append("**核心**：" + safe_text(p["summary"]))
        for label, key in (("做法", "method"), ("结果/边界", "evidence")):
            if p[key]:
                description.append(f"<font color='grey'>**{label}**：{safe_text(p[key])}</font>")
        top.append(md("\n".join(description)))
    if top:
        blocks.append(box("重点推荐", top))
    rest = [md(linked(p["title"],p["url"])) for p in remaining]
    if news:
        rest += [md("**行业与开源速递**"), *(md(linked(t,u)) for t,u in news)]
    if rest:
        blocks.append(dict(tag="collapsible_panel", expanded=False, border=dict(color="grey-200",corner_radius="8px"),
                           padding="8px 12px 12px 12px", vertical_spacing="6px", margin=GAP,
                           header=dict(title=plain(f"展开查看其余 {len(remaining)} 篇论文" + ("与行业速递" if news else "")),background_color="grey-50",width="fill"),elements=rest))
    blocks.append(md(f"<font color='grey'>完整图文版见本机 digests/{day}.html · Obsidian 与 Notion 归档同步</font>",text_size="notation",margin="0px"))
    tags = [(f"精选 {len(papers)} 篇","blue")] + ([(f"微信 {len(news)} 条","wathet")] if news else [])
    return dict(schema="2.0",config=dict(update_multi=True,width_mode="default",enable_forward=True,summary=dict(content=f"[PaperPulse 晨报] {day} · {len(papers)} 篇精选")),
                header=dict(title=plain("PaperPulse 论文晨报"),subtitle=plain(f"{day} · 11 方向研究雷达"),template="blue",
                            icon=dict(tag="standard_icon",token="myai_colorful"),text_tag_list=[dict(tag="text_tag",text=plain(label),color=c) for label,c in tags]),
                body=dict(direction="vertical",padding="12px 12px 20px 12px",vertical_spacing="0px",elements=blocks))


def load_settings(path):
    # macOS system Python lacks PyYAML; its system Ruby supplies a safe YAML reader.
    try:
        import yaml
    except ImportError:
        result = subprocess.run(["ruby","-ryaml","-rjson","-e",
                                 'puts JSON.generate(YAML.safe_load(File.read(ARGV[0])).fetch("feishu", {}))',str(path)],
                                capture_output=True, text=True, check=True)
        return json.loads(result.stdout)
    return yaml.safe_load(path.read_text()).get("feishu", {})


def cli_path(config):
    if config.get("lark_cli_bin"):
        return os.path.expanduser(config["lark_cli_bin"])
    found = shutil.which("lark-cli")
    if found:
        return found
    bins = Path.home().glob(".nvm/versions/node/v*/bin/lark-cli")
    return str(max((p for p in bins if os.access(p, os.X_OK)),
                   key=lambda p:tuple(map(int,re.findall(r"\d+",p.parents[1].name)))))


def deliver(card, config, identity, flag, target, key):
    if config.get("enabled") is not True or identity not in ("bot","user") or flag not in ("--user-id","--chat-id") or not target:
        raise ValueError("Check feishu.enabled, identity and recipient")
    result = subprocess.run([cli_path(config),"im","+messages-send","--as",identity,flag,target,"--msg-type","interactive",
                             "--content",json.dumps(card, ensure_ascii=False),"--idempotency-key",key],capture_output=True,text=True)
    if result.returncode != 0 or json.loads(result.stdout).get("ok") is not True:
        raise ValueError("Feishu delivery not confirmed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--latest",action="store_true"); src.add_argument("--digest",type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run",action="store_true"); mode.add_argument("--send",action="store_true")
    to = parser.add_mutually_exclusive_group()
    to.add_argument("--user-id"); to.add_argument("--chat-id")
    parser.add_argument("--as",dest="identity",choices=("user","bot"))
    parser.add_argument("--idempotency-key"); parser.add_argument("--output-json",type=Path)
    parser.add_argument("--config",type=Path,default=ROOT/"config.yaml")
    args = parser.parse_args(argv)
    path = args.digest
    if args.latest:
        dated = sorted(p for p in (ROOT/"digests").glob("*.md") if re.fullmatch(r"\d{4}-\d{2}-\d{2}",p.stem))
        if not dated: parser.error("No dated digest found")
        path = dated[-1]
    markdown = path.read_text()
    day_match = digest.DATE_PATTERN.search(path.stem) or digest.DATE_PATTERN.search(markdown.splitlines()[0] if markdown else "")
    if not day_match: parser.error("Digest filename or heading must specify the ISO date")
    day = date.fromisoformat(day_match[0]).isoformat()
    card = build_card(markdown,day)
    encoded = json.dumps(card,ensure_ascii=False,indent=2)
    if re.search(r"/Users/|(?:ou_|oc_)[a-f0-9]{16,}|cli_[a-f0-9]{12,}", encoded, re.I):
        raise ValueError("Private identifier or personal path in card")
    if args.output_json: args.output_json.write_text(encoded+"\n")
    if args.send:
        cfg = load_settings(args.config)
        flag = "--user-id" if args.user_id else "--chat-id" if args.chat_id else {"user_id":"--user-id","chat_id":"--chat-id"}.get(cfg.get("receive_id_type"))
        deliver(card,cfg,args.identity or cfg.get("identity") or "bot",flag,args.user_id or args.chat_id or cfg.get("receive_id"),args.idempotency_key or "paperpulse-"+day)
        print('{"ok":true}')
    else:
        print(encoded)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        sys.exit(str(error))
