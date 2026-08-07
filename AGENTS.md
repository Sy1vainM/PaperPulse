# AGENTS.md

This repository contains PaperPulse, an agent-ready daily paper digest workflow.

## For Codex

When asked to run the digest:

1. Read `docs/agent-protocol.md`.
2. Read `config.yaml`, `last_run.json`, `seen_papers.json`, and `sources-reference.md`.
3. If `config.yaml` is missing, tell the user to copy `config.example.yaml` to `config.yaml` and customize it.
4. If either state file is missing, initialize it from the matching `*.example.json` template.
5. Follow the shared protocol exactly.

## Boundaries

- Do not commit private `config.yaml`.
- Do not expose API keys, tokens, cookies, private filesystem paths, private Notion database IDs, or private Obsidian vault paths.
- Do not invent paper details.
- Write digest prose in Chinese unless the user asks otherwise.

## Entrypoints

- Codex prompt: `codex/agent-copy-prompt.md`
- Claude Code command: `.claude/commands/paper-digest.md`
- Shared workflow: `docs/agent-protocol.md`
