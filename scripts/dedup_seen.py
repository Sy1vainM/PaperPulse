#!/usr/bin/env python3
"""Filter discovery candidates against the private ledger or record completed work."""
import argparse
import contextlib
import fcntl
import json
import os
import re
import sys
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ARXIV = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7})(?:v\d+)?", re.I)
DOI = re.compile(r"10\.\d{4,9}/\S+", re.I)


def identifier(value):
    value = value.strip()
    parts = urlsplit(value)
    if parts.scheme in ("http", "https") and parts.hostname:
        if parts.hostname.lower() in ("arxiv.org", "www.arxiv.org", "export.arxiv.org"):
            path = re.sub(r"^/(?:abs|pdf|html)/", "", parts.path).removesuffix(".pdf").rstrip("/")
            if ARXIV.fullmatch(path):
                return re.sub(r"v\d+$", "", path.lower())
        if parts.hostname in ("doi.org", "dx.doi.org"):
            return identifier(parts.path.lstrip("/"))
        query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                 if not k.lower().startswith("utm_")]
        return urlunsplit(("https", parts.netloc.lower(), parts.path.rstrip("/"), urlencode(query), ""))
    value = re.sub(r"^(?:arxiv|doi):\s*", "", value, flags=re.I).lower()
    if ARXIV.fullmatch(value):
        return re.sub(r"v\d+$", "", value)
    if DOI.fullmatch(value):
        return value
    return None


def keys(row, legacy=""):
    found = []
    for value in (legacy, *(row.get(k) for k in ("arxiv_id", "arxiv", "doi", "url", "id", "canonical_key"))):
        if isinstance(value, str) and value:
            key = identifier(value)
            if key:
                found.append(key)
    title = row.get("title", "")
    if not isinstance(title, str):
        raise ValueError("title must be text")
    normalized = re.sub(r"[\W_]+", " ", unicodedata.normalize("NFKC", title).casefold()).strip()
    if normalized:
        found.append("title:" + normalized)
    aliases = row.get("dedup_aliases", [])
    if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
        raise ValueError("dedup_aliases must be a list of strings")
    found.extend(aliases)
    return list(dict.fromkeys(found))


def process(ledger, rows, record=False):
    """Group the whole batch before filtering, including transitive identifier matches."""
    seen = {key: old for old, row in ledger.items() for key in keys(row, old)}
    parent = {}

    def root(key):
        while key != parent.setdefault(key, key):
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    batch = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each candidate must be an object")
        aliases = keys(row)
        if not aliases:
            raise ValueError("candidate needs an arXiv ID, DOI, URL or title")
        for alias in aliases:
            parent[root(alias)] = root(aliases[0])
        batch.append((row, aliases))
    groups = {}
    for row, aliases in batch:
        groups.setdefault(root(aliases[0]), []).append((row, aliases))
    fresh = []
    historical = 0
    for group in groups.values():
        aliases = list(dict.fromkeys(k for _, values in group for k in values))
        old = next((seen[k] for k in aliases if k in seen), None)
        if old is not None:
            historical += 1
        row = dict(group[0][0])
        sources = []
        for item, _ in group:
            for field, value in item.items():
                if value and not row.get(field):
                    row[field] = value
            for source in (item.get("source"), *item.get("sources", [])):
                if source and source not in sources:
                    sources.append(source)
        if len(sources) > 1:
            row["sources"] = sources
        if old is None:
            fresh.append(row)
        if record:
            key = old or aliases[0]
            entry = ledger.setdefault(key, row.copy())
            extra = sorted(set(aliases) - set(keys(entry, key)))
            if extra:
                entry["dedup_aliases"] = sorted(set(entry.get("dedup_aliases", []) + extra))
        elif old is None and len(group) > 1:
            row["dedup_aliases"] = aliases
    return {"candidates": fresh, "stats": {"input": len(rows), "batch_duplicates": len(rows)-len(groups),
            "already_seen": historical, "unseen": len(fresh)}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("record", "filter"))
    parser.add_argument("--input", type=Path, help="Candidate array or filter output; default stdin")
    parser.add_argument("--seen", type=Path, default=Path(__file__).resolve().parents[1]/"seen_papers.json")
    args = parser.parse_args(argv)
    try:
        rows = json.loads(args.input.read_text() if args.input else sys.stdin.read())
        if isinstance(rows, dict):
            rows = rows.get("candidates")
        if not isinstance(rows, list):
            raise ValueError("expected an array of candidates")
        writing = args.action == "record"
        with contextlib.ExitStack() as stack:
            if writing:
                lock = stack.enter_context(args.seen.with_suffix(".json.lock").open("a"))
                fcntl.flock(lock, fcntl.LOCK_EX)
            ledger = json.loads(args.seen.read_text(encoding="utf-8"))
            if not isinstance(ledger, dict) or not all(isinstance(v, dict) for v in ledger.values()):
                raise ValueError("expected a seen ledger mapping keys to records")
            result = process(ledger, rows, writing)
            if writing:
                with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.seen.parent, delete=False) as out:
                    temp = Path(out.name)
                    stack.callback(temp.unlink, missing_ok=True)
                    json.dump(ledger, out, ensure_ascii=False, indent=2)
                    out.write("\n")
                    out.flush()
                    os.fsync(out.fileno())
                os.replace(temp, args.seen)
                result = {"stats": result["stats"], "ledger_size": len(ledger)}
        print(json.dumps(result, ensure_ascii=False))
    except (OSError, ValueError, TypeError) as error:
        parser.exit(2, f"{error}\n")


if __name__ == "__main__":
    main()
