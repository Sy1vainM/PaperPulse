# Public Release Checklist

Use this checklist before pushing PaperPulse to a public GitHub repository.

## Must Pass

- `config.yaml` is not committed.
- `config.example.yaml` has no private database IDs, Obsidian vault paths, local paths, API keys, tokens, or company-specific context.
- `last_run.json` is reset to `never_run`.
- `seen_papers.json` is an empty object.
- `digests/` contains only `.gitkeep` unless you intentionally want to publish example digests.
- `logs/` contains only `.gitkeep`.
- No files contain private filesystem paths or Obsidian vault paths.
- No files contain API keys, tokens, cookies, Notion database IDs, or Obsidian vault paths.

## Recommended First Commit

```bash
git init
git add .
git commit -m "feat: add PaperPulse agent workflow"
```

Then create a GitHub repository and add the remote:

```bash
git remote add origin git@github.com:YOUR_NAME/paperpulse.git
git branch -M main
git push -u origin main
```

## Agent Entrypoints

- Codex: `codex/agent-copy-prompt.md`
- Claude Code: `.claude/commands/paper-digest.md`
- Shared behavior: `docs/agent-protocol.md`
