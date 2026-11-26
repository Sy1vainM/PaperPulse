#!/usr/bin/env python3
"""Stable PaperPulse entry point for WeChat discovery through Exa MCP."""

from __future__ import annotations

import argparse
import json
import logging
import re
from datetime import date
from html import unescape
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


DEFAULT_OBJECTIVE = ("优先近 1–3 天发布的微信原文，排除旧文转载。关注多模态、视频、空间、运动重建、"
                     "世界模型、具身智能、推理降本和开源发布。提取发布日期、版本变化与作者一手链接。")


def search_wechat(args: argparse.Namespace) -> int:
    """Search WeChat public-account pages through Exa."""
    _validate_runtime()
    query = args.query.strip()
    if not query:
        raise ValueError("Search query must not be empty")
    if not args.objective.strip():
        raise ValueError("Search objective must not be empty")
    if "mp.weixin.qq.com" not in query:
        query = f"site:mp.weixin.qq.com {query}"
    payload: dict[str, object] = {
        "query": query,
        "objective": args.objective.strip(),
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


def extract_article(text, published=None):
    """Return date and artifact leads; ownership requires checking the linked source."""
    text = unescape(text)
    labeled = re.search(r"(?:发布(?:时间|日期|于)?|published(?:\s+on|\s+date)?|publish_time)[：:\s\"=]*(\d{4}[-年/]\d{1,2}[-月/]\d{1,2})", text, re.I)
    raw_date = str(published or (labeled[1] if labeled else ""))
    match = re.match(r"(\d{4})[-年/](\d{1,2})[-月/](\d{1,2})", raw_date)
    stamp = None
    if match:
        try:
            stamp = date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    links = {}
    previous = ""
    for line in (part for part in text.splitlines() if part.strip()):
        for raw in re.findall(r"https://[A-Za-z0-9._~:/?#@!$&'*+,%=;\-]+", line):
            url = raw.rstrip(".,;")
            host = urlparse(url).hostname or ""
            if host in ("arxiv.org", "doi.org", "openreview.net"):
                kind = "paper"
            elif host in ("github.com", "huggingface.co"):
                kind = "release"
            elif host.endswith(".github.io") or re.search(r"项目(?:主页|地址|页)|project (?:page|site)|官方(?:主页|发布)", previous + " " + line, re.I):
                if host in ("mp.weixin.qq.com", "weixin.qq.com"):
                    continue
                kind = "project_candidate"
            else:
                continue
            links[url] = kind
        previous = line if "https://" not in line else ""
    return {"published": stamp, "links": [{"kind": kind, "url": url} for url, kind in links.items()]}


def extract_results(value):
    if isinstance(value, list):
        return [article for item in value for article in extract_results(item)]
    if isinstance(value, dict):
        for key in ("results", "content", "data"):
            if isinstance(value.get(key), (dict, list)):
                return extract_results(value[key])
        body = "\n".join(str(value[k]) for k in ("title", "text", "markdown", "content", "highlights") if k in value)
        published = value.get("publishedDate") or value.get("published_at")
        if value.get("url") or published:
            return [dict(extract_article(body, published), source=value.get("url"))]
        return extract_results(body)
    if isinstance(value, str):
        articles = []
        for block in re.split(r"(?m)(?=^Title: )", value):
            if not block.strip():
                continue
            source = re.search(r"(?m)^URL:\s*(https://\S+)", block)
            published = re.search(r"(?m)^Published:[ \t]*(.*)$", block)
            article = extract_article(block, published[1] if published else None)
            article["source"] = source[1] if source else None
            articles.append(article)
        return articles
    raise ValueError("expected text or search/fetch results")


def extract_command(args):
    text = args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        value = text
    print(json.dumps(extract_results(value), ensure_ascii=False, indent=2))
    return 0



def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_parser = subparsers.add_parser("check", help="Validate the local runtime and Exa MCP")
    check_parser.set_defaults(handler=check_connector)

    search_parser = subparsers.add_parser("search", help="Search WeChat public-account pages")
    search_parser.add_argument("query")
    search_parser.add_argument("--objective", default=DEFAULT_OBJECTIVE)
    search_parser.add_argument("--num-results", type=int, choices=range(1, 21), default=5)
    search_parser.add_argument("--timeout-ms", type=int, choices=range(1000, 120001), default=60000)
    search_parser.set_defaults(handler=search_wechat)

    fetch_parser = subparsers.add_parser("fetch", help="Fetch one explicit WeChat article")
    fetch_parser.add_argument("url")
    fetch_parser.add_argument("--max-characters", type=int, choices=range(1000, 50001), default=12000)
    fetch_parser.add_argument("--timeout-ms", type=int, choices=range(1000, 120001), default=60000)
    fetch_parser.set_defaults(handler=fetch_wechat)
    extract = subparsers.add_parser("extract", help="Extract dates and primary-source leads from stdin or file")
    extract.add_argument("--input", type=Path)
    extract.set_defaults(handler=extract_command)
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
