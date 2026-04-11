# WeChat Connector Notes: Agent-Reach + mcporter + Exa MCP

Read this only when you want to enable the optional `wechat_mp` source.

## Background

WeChat public account articles are useful as discovery signals for fast-moving AI research, but they are not a normal open paper API. A local connector bridge is usually needed to fetch article text reliably.

## Recommended Stack

- Agent-Reach: content access helper for channels such as WeChat.
- mcporter: local MCP bridge runner.
- Exa MCP: web fetch/crawl backend used by mcporter.

PaperPulse does not vendor or install these tools automatically. Users should configure them in their own environment.

## Setup Pattern

Use an isolated local test directory or virtual environment. Do not install experimental connector dependencies into a shared project environment unless you intentionally want that.

Recommended flow:

1. Create an isolated test directory.
2. Create and activate a Python virtual environment.
3. Install Agent-Reach from its upstream package or repository.
4. Install `mcporter` in a local npm prefix or another isolated Node environment.
5. Add the Exa MCP endpoint to mcporter.
6. Run the Agent-Reach doctor or equivalent health check.
7. Confirm WeChat support is available.
8. Fetch one explicit WeChat article URL and confirm the article title/body are returned.
9. Enable `wechat_mp` in `config.yaml`.

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
