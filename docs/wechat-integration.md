# Optional WeChat Integration

PaperPulse can use WeChat public account articles as a discovery signal for new papers, models, benchmarks, and GitHub projects. This integration is optional and disabled by default.

## Why It Is Optional

WeChat public account pages are not a normal open paper API. Access often requires a third-party fetch bridge, and the exact setup depends on the user's local environment. PaperPulse therefore documents the connector contract but does not vendor tools, credentials, or MCP configuration.

## Recommended Stack

One working approach is:

- Agent-Reach: content access helper.
- mcporter: local MCP bridge runner.
- Exa MCP: web fetch/crawl backend for article extraction.

Do not commit API keys, MCP credentials, cookies, local paths, or generated connector state to this repository.

Keep connector dependencies in the stable, Git-ignored `.runtime/` directory. Do not install them in a Codex worktree because worktrees are disposable and do not share project-local dependencies.

For installation notes and validation checks, read `docs/wechat-agent-reach-notes.md` only when enabling this connector.

## Config

Enable only after your local agent environment can fetch WeChat articles:

```yaml
sources:
  - name: wechat_mp
    type: connector
    enabled: true
    channels:
      - "Example Account"
    article_urls: []
    connector_command: "python3 scripts/wechat_connector.py"
    description: "Optional WeChat public account connector."
```

For the most reliable run, provide explicit article URLs:

```yaml
sources:
  - name: wechat_mp
    type: connector
    enabled: true
    channels: []
    article_urls:
      - "https://mp.weixin.qq.com/s/..."
    connector_command: "python3 scripts/wechat_connector.py"
```

## Stable Connector Commands

Use the tracked helper instead of calling a worktree-local binary:

```bash
python3 scripts/wechat_connector.py check
python3 scripts/wechat_connector.py search 'site:mp.weixin.qq.com "Example Account" multimodal paper'
python3 scripts/wechat_connector.py fetch 'https://mp.weixin.qq.com/s/...'
```

The helper resolves `.runtime/connectors/mcporter` and `config/mcporter.json` relative to the PaperPulse repository root.

## Agent Behavior

When `wechat_mp` is enabled, the agent should:

1. Read `docs/wechat-agent-reach-notes.md`.
2. Run `python3 scripts/wechat_connector.py check`.
3. Fetch explicit `article_urls` first.
4. If channel discovery is supported, fetch recent articles from configured `channels`.
5. Extract original technical artifacts:
   - arXiv or paper links.
   - GitHub repositories.
   - Project pages.
   - Model or benchmark names.
   - Institutions and key results when visible.
6. Send papers with primary sources to the paper candidate pool. Keep non-paper releases in the separate roundup.
7. Use `scripts/dedup_seen.py filter` on paper candidates. Deduplicate release news by original release and version.
8. Treat WeChat as a discovery signal, not as the primary paper record.

## Failure Handling

If the connector is missing or unavailable:

- Mark `wechat_mp` as failed.
- Continue with other sources.
- Do not fail the whole digest unless every source fails.

If an article has no original technical artifact:

- Skip it.
- Do not summarize commentary as if it were a paper.

## Validation

A minimal validation is:

1. Fetch one explicit WeChat article URL.
2. Confirm the title and article text are returned.
3. Confirm original paper, GitHub, model, or benchmark links can be extracted when present.
4. Run PaperPulse with `wechat_mp.enabled: true`.
5. Confirm WeChat items merge into the main candidate pool and do not duplicate arXiv or HuggingFace entries.

## 最近发布与开源速递

Search accepts `--objective`; the default requests the last 1–3 days and excludes old reposts. Extract each article separately, from stdin or `--input`:

```sh
python3 scripts/wechat_connector.py fetch 'https://mp.weixin.qq.com/s/...' | python3 scripts/wechat_connector.py extract
```

Extraction yields a publication date (null if unknown) and potential primary URLs. Check the original date, author ownership, release tag and concrete change before publication. Use the four-section paper template for verified research; list 3–5 verified non-paper releases under **行业与开源速递（微信信源）** with both discovery and original links. Fewer verified items is acceptable. Record the actual count and connector state in the private daily JSON log.
