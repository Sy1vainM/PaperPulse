# PaperPulse Agent Protocol

This document defines the shared workflow for all supported agents. Codex and Claude Code entry files should delegate to this protocol instead of maintaining separate logic.

## Goal

Run a daily paper digest workflow:

1. Determine the date range to cover.
2. Collect new research items from enabled sources.
3. Deduplicate against previous runs.
4. Score candidates against the configured work context.
5. Write a Chinese Markdown digest.
6. Optionally archive selected papers to Notion or Obsidian.
7. Update state only after at least one key phase succeeds.

## Required Files

Read these files before collecting:

- `config.yaml`
- `last_run.json`
- `seen_papers.json`
- `sources-reference.md`

If `config.yaml` is missing, tell the user to copy `config.example.yaml` to `config.yaml` and customize it.

If a runtime state file is missing, initialize it from the versioned template:

- `last_run.example.json` -> `last_run.json`
- `seen_papers.example.json` -> `seen_papers.json`

The runtime state files and generated digests are private local data and must remain ignored by Git.

## Date Range Rules

1. Determine today's date in the user's local timezone.
2. If `last_run_date` is `null`, collect today only.
3. If `last_run_date` equals today and `last_run_status` is `success`, stop and report `Already ran today`.
4. Otherwise collect from `last_run_date + 1 day` through today, inclusive.
5. If a public daily source lags local time but exposes items not present in `seen_papers.json`, the agent may include them and must note the source-date mismatch in the digest.

## Collection Rules

Use only sources with `enabled: true` in `config.yaml`.

Supported source names:

- `arxiv`
- `huggingface_daily`
- `semantic_scholar`
- `papers_with_code`
- `blog_list`
- `web_search`
- `openalex`
- `website`
- `wechat_mp`

Use `sources-reference.md` for source-specific details.

For `wechat_mp`, read `docs/wechat-integration.md`. If the local connector is not already installed, read `docs/wechat-agent-reach-notes.md` only then. Treat WeChat as optional and disabled unless the local connector is configured.

Partial failure is acceptable:

- Continue when a single source fails.
- Record failed source names and reasons.
- Do not advance `last_run.json` if every major phase fails.
- When collecting in parallel, wait for all enabled sources or background collection tasks before scoring. Do not score partial results while slow sources are still running.

## Dedup Rules

Deduplicate in this order:

1. arXiv ID exact match.
2. DOI exact match.
3. URL exact match.
4. Normalized title similarity.

Then remove items already present in `seen_papers.json`.

Normalize titles by lowercasing, removing punctuation, and collapsing whitespace.

## Scoring Rules

Score each candidate against `filter.my_work_context` from `config.yaml`.

Use these dimensions and weights:

| Dimension | Weight | Evaluates |
|---|---:|---|
| Relevance | 35% | Match to the configured work context and categories. |
| Innovation | 25% | New architecture, method, benchmark, or paradigm. |
| Impact | 20% | Strong results, open code, strong baselines, or community attention. |
| Method Quality | 10% | Technical soundness visible from abstract or paper page. |
| Practicality | 10% | Reproducibility, deployment feasibility, reasonable compute, or actionable ideas. |

Scale final score to `1-10`.

Apply bonuses only when justified:

- Multi-source discovery.
- Strong editorial or benchmark signal.
- Direct fit with configured categories.
- Practical implementation value.

Default bonus guidance:

- Curated website/editorial signal: `+0.5`.
- Multi-source discovery: `+0.3` per additional independent source, max `+0.6`.

Selection:

1. Keep score `>= filter.threshold`.
2. Keep at most `filter.max_papers_per_day`.
3. Generate Chinese structured summaries for selected papers.
4. If no paper passes the threshold, write a minimal digest noting that no papers passed and still update state if collection succeeded.

## Digest Format

Write `digests/YYYY-MM-DD.md`.

Header:

```markdown
# Paper Digest: YYYY-MM-DD

> Date range: YYYY-MM-DD to YYYY-MM-DD
> Collected: N unique candidates from X successful sources | Selected: M papers (threshold: T)
> Generated: YYYY-MM-DD HH:mm TZ
```

Summary table:

```markdown
## Summary Table

| # | Score | Title | Categories | Source |
|---|-------|-------|------------|--------|
```

Per-paper format:

```markdown
## [Paper Title](url)

**Score**: X/10 | **Category**: cat1, cat2
**Authors**: first_author et al. | **Date**: YYYY-MM-DD | **Source**: source1, source2

### 一句话总结

### 核心贡献

### 方法要点

### 关键结果

### 与我工作的关联
```

All digest prose should be in Chinese unless the user asks otherwise.

## Archive Rules

Local Markdown is the primary archive. Optional archive backends are controlled by `archive` in `config.yaml`.

### Notion

If `archive.notion.enabled` is true:

1. Confirm the agent has Notion access.
2. Fetch the target database or data source first to confirm schema.
3. Map fields conservatively:
   - Title -> paper title.
   - Date -> digest date.
   - Score -> numeric score.
   - Source -> closest configured select option.
   - Category -> configured categories when supported.
   - Summary -> one-line summary.
   - URL -> paper URL.
4. If Notion fails, keep the local digest and report Notion status as failed.

### Obsidian

If `archive.obsidian.enabled` is true:

1. Read `archive.obsidian.vault_path`, `archive.obsidian.digest_directory`, and `archive.obsidian.filename_template`.
2. If `vault_path` is empty, skip Obsidian and report it as not configured.
3. Copy the generated local digest into:

   ```text
   {vault_path}/{digest_directory}/{filename_template}
   ```

4. Replace `{date}` in `filename_template` with the digest date, for example `YYYY-MM-DD`.
5. Create the target directory if needed.
6. If Obsidian copy fails, keep the local digest and report Obsidian status as failed.

## State Update Rules

When at least one key phase succeeds:

1. Write or update `digests/YYYY-MM-DD.md`.
2. Update `seen_papers.json` with selected papers and useful rejected candidates when available.
3. Update `last_run.json`.

When all major phases fail:

- Do not advance `last_run_date`.
- Do not create a misleading empty successful digest.
- Report the failure and the likely cause.

## Final Report

Report:

- Covered date range.
- Successful source count.
- Failed source count.
- Collected count.
- Selected count.
- Local digest path.
- Notion archive status.
- Obsidian archive status.
- Top selected papers with one-line reasons.

## Safety Rules

- Do not invent papers, authors, metrics, or URLs.
- Do not commit private `config.yaml`.
- Do not expose API keys, tokens, cookies, private paths, private Notion database IDs, or private Obsidian vault paths.
- Prefer source attribution and uncertainty over confident guessing.
