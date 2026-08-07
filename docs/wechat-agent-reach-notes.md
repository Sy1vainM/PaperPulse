# WeChat Connector Notes: Agent-Reach + mcporter + Exa MCP

Read this only when you want to enable the optional `wechat_mp` source.

## Background

WeChat public account articles are useful as discovery signals for fast-moving AI research, but they are not a normal open paper API. A local connector bridge is usually needed to fetch article text reliably.

## Recommended Stack

- Agent-Reach: content access helper for channels such as WeChat.
- mcporter: local MCP bridge runner.
- Exa MCP: web fetch/crawl backend used by mcporter.

PaperPulse does not vendor these tools. Install them into the Git-ignored `.runtime/connectors/` directory so every local PaperPulse run uses one stable runtime.

## Setup Pattern

Use the repository-local `.runtime/connectors/` directory. It is private, stable across runs, and excluded from Git.

Recommended flow:

1. Create `.runtime/connectors/agent-reach-venv` with Python 3.10 or newer.
2. Install Agent-Reach into that virtual environment.
3. Install `mcporter` into `.runtime/connectors/mcporter`.
4. Store the project MCP configuration at `config/mcporter.json`.
5. Add the Exa MCP endpoint to that configuration.
6. Run `python3 scripts/wechat_connector.py check`.
7. Fetch one explicit WeChat article URL and confirm the article title/body are returned.
8. Enable `wechat_mp` in `config.yaml`.

Never install connector dependencies in `.codex/worktrees/...`; a later automation run may use a different worktree and lose the binaries and MCP configuration.

## Example Config

Explicit article URLs are the most reliable:

```yaml
sources:
  - name: wechat_mp
    type: connector
    enabled: true
    channels: []
    article_urls:
      - "https://mp.weixin.qq.com/s/..."
```

Channel discovery is more environment-dependent:

```yaml
sources:
  - name: wechat_mp
    type: connector
    enabled: true
    channels:
      - "Example Account"
    article_urls: []
```

## Validation Checklist

- The connector command can list available tools.
- Exa MCP is registered and reachable.
- The health check reports WeChat article access as available.
- A known explicit WeChat article URL returns title and article body.
- The fetched article can be reduced to original technical artifacts:
  - arXiv links.
  - GitHub repositories.
  - Project pages.
  - Model names.
  - Benchmark names.

## Common Failures

- Missing media downloader dependency: install the dependency in the isolated environment and rerun the health check.
- MCP bridge unavailable: confirm `mcporter` can list the Exa tools.
- Exa MCP not configured: add the endpoint again and rerun the tool list command.
- Network/DNS failure: treat `wechat_mp` as failed and continue with other PaperPulse sources.
- Article has no original technical artifact: skip it instead of summarizing commentary as a paper.

## Security Rules

- Do not commit MCP config files that contain credentials.
- Do not commit API keys, cookies, or generated connector state.
- Do not commit private WeChat article URLs unless you intentionally want them public.
- Keep connector-specific caches outside the public repository or add them to `.gitignore`.

## Agent Behavior

When `wechat_mp` is enabled, the agent should:

1. Read this note after `docs/wechat-integration.md`.
2. Verify connector availability before attempting collection.
3. Prefer explicit `article_urls`.
4. Extract original technical artifacts rather than summarizing the media article itself.
5. Merge extracted artifacts into the main candidate pool.
6. Deduplicate against arXiv, HuggingFace, OpenAlex, and other sources.
7. Continue the PaperPulse run if WeChat collection fails.
