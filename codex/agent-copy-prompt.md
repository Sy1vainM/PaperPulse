# Codex Copy Prompt

Copy this prompt into Codex:

```text
Run the PaperPulse daily paper digest in the current repository.

First read docs/agent-protocol.md, then read config.yaml, last_run.json, seen_papers.json, and sources-reference.md.

Follow the shared protocol exactly:
- If config.yaml is missing, stop and ask me to copy config.example.yaml to config.yaml.
- If the digest already ran successfully today, stop and report Already ran today.
- Collect from sources enabled in config.yaml.
- Continue when a single source fails, but report failed sources at the end.
- Deduplicate candidates and skip entries already in seen_papers.json.
- Score papers against filter.my_work_context.
- Write Chinese structured summaries to digests/YYYY-MM-DD.md.
- If Notion is enabled and available, archive selected papers to the configured database.
- If Obsidian is enabled and configured, copy the generated digest into the configured vault path.
- Update seen_papers.json and last_run.json only after at least one key phase succeeds.

Final report: date range, successful/failed source counts, collected count, selected count, local digest path, Notion status, Obsidian status, and top selected papers with one-line reasons.
```
