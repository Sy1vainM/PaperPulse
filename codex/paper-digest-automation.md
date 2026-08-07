# PaperPulse Codex Automation

This is the Codex entry point for PaperPulse.

## Instructions

1. Work from the repository root.
2. Read `docs/agent-protocol.md`.
3. Read `config.yaml`, `last_run.json`, `seen_papers.json`, and `sources-reference.md`.
4. If `wechat_mp` is enabled, also read `docs/wechat-integration.md`.
5. Follow the shared protocol exactly.
6. Apply the configured tiered reading policy before writing the final report.
7. If `report.html.enabled` is true, render the completed Markdown with `scripts/render_digest.py`.
8. Do not modify `.claude/commands/` unless the user asks to change Claude Code behavior.
9. Do not commit or expose private `config.yaml` values, including Notion database IDs or Obsidian vault paths.

## Output

End with a concise run report:

- Covered date range.
- Successful source count.
- Failed source count.
- Collected count.
- Selected count.
- Local Markdown path.
- Local HTML path and render status.
- Notion status.
- Obsidian status.
- Top selected papers with one-line reasons.

If `config.yaml` is missing, stop and tell the user to copy `config.example.yaml` to `config.yaml` and customize it.
