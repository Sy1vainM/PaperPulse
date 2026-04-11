---
description: "Use when: user says /paper-digest, wants a daily research update, asks for new papers, or wants to catch up on recent AI papers. Collects, filters, scores, and summarizes papers from configured sources, then archives to local Markdown and optionally Notion or Obsidian."
user-invocable: true
---

# PaperPulse Daily Paper Digest

Collect papers from multiple sources, score them by relevance to the configured work context, generate structured Chinese summaries, and archive to local Markdown plus optional Notion or Obsidian.

**Project root**: current repository root. Do not use an absolute user-specific path.

Read `docs/agent-protocol.md` first, then execute phases 0-5 below. User arguments, such as a date range or source name, override defaults when they do not conflict with safety rules.

---

## Phase 0: Load Config and Determine Date Range

1. Read these files from the project root:
   - `config.yaml`
   - `last_run.json`
   - `seen_papers.json`
   - `sources-reference.md`
2. If `config.yaml` is missing, stop and tell the user to copy `config.example.yaml` to `config.yaml` and customize it.
3. Determine today's date in the user's local timezone.
4. Date range logic:
   - `last_run_date` is `null` -> collect today only.
   - `last_run_date` equals today and `last_run_status` is `success` -> report `Already ran today` and stop.
   - Otherwise -> collect from `last_run_date + 1 day` through today, inclusive.
5. Report: `Collecting papers from YYYY-MM-DD to YYYY-MM-DD`.

If a public daily source lags local time but exposes items not present in `seen_papers.json`, you may include them and must note the source-date mismatch in the digest.

---

## Phase 1: Collect from Enabled Sources

Read `sources-reference.md` for source-specific fetch URLs, metadata requirements, and fallback instructions.

Collect from sources where `enabled: true` in `config.yaml`.

Supported source types:

| Source | Key notes |
|---|---|
| `arxiv` | One query per category, filter by date range. |
| `huggingface_daily` | Extract arXiv IDs from paper URLs for dedup. |
| `blog_list` | Fetch configured RSS/Atom URLs and filter by date range. |
| `web_search` | Broad catch-all using configured query templates. |
| `openalex` | Free metadata source; reconstruct abstracts from inverted index when available. |
| `semantic_scholar` | Useful when enabled, but handle rate limits gracefully. |
| `papers_with_code` | Use as secondary signal when it duplicates HuggingFace Daily. |
| `website` | User-configured website discovery signal; extract original paper, GitHub, model, or benchmark links. |
| `wechat_mp` | Optional discovery signal only when the local environment has an approved fetch path; read `docs/wechat-integration.md` when enabled. |

Collection strategy:

1. Collect in parallel when your runtime supports it.
2. A single source failure must not stop the pipeline.
3. Record failed source names and reasons.
4. Wait for all background collection tasks before scoring. Do not score partial results while slow sources are still running.
5. If every source fails, skip to final report and do not update `last_run.json`.

---

## Phase 1b: Post-Collection Dedup

After all enabled sources complete:

1. Remove entries already present in `seen_papers.json`.
2. Cross-source deduplicate and merge metadata by:
   - arXiv ID exact match.
   - DOI exact match.
   - URL exact match.
   - Normalized title similarity.
3. Normalize titles by lowercasing, removing punctuation, and collapsing whitespace.
4. When merging, keep the richest metadata and record all discovered sources in a `sources` list.
5. Report: `Collected N unique items from X/Y sources (Z failed: names)`.

Multi-source discovery is a positive scoring signal.

---

## Phase 2: Filter and Score

Score papers against `filter.my_work_context` in `config.yaml`.

Use batch scoring when there are many candidates. Score each candidate on five dimensions:

| Dimension | Weight | Evaluates |
|---|---:|---|
| Relevance | 35% | Match to the configured work context and categories. |
| Innovation | 25% | New architecture, method, benchmark, or paradigm. |
| Impact | 20% | Strong results, open code, strong baselines, or community attention. |
| Method Quality | 10% | Technical soundness visible from abstract or paper page. |
| Practicality | 10% | Reproducibility, deployment feasibility, reasonable compute, or actionable ideas. |

Final score:

1. Compute weighted score and scale to `1-10`.
2. Add source bonuses only when justified:
   - Curated website/editorial signal: `+0.5`.
   - Multi-source discovery: `+0.3` per additional independent source, max `+0.6`.
3. Assign matched categories from `filter.categories`.
4. Add one Chinese sentence explaining the score.

Selection:

1. Keep score `>= filter.threshold`.
2. Cap at `filter.max_papers_per_day`.
3. Keep top-scoring papers.
4. If no paper passes the threshold, write a minimal digest noting that no papers passed and still update state if collection succeeded.

Do not invent details. If authors, metrics, or full text are unavailable, explicitly mark them as unconfirmed.

---

## Phase 3: Deep Read and Summarize

For each selected paper:

### 3a. Fetch Full Text or Rich Metadata

- arXiv: prefer `https://arxiv.org/html/{arxiv_id}` when available; fall back to `https://arxiv.org/abs/{arxiv_id}`.
- HuggingFace paper pages: use them for title, links, abstract, and community signal; resolve to arXiv when possible.
- Blog or media: fetch the original paper, project, model, benchmark, or GitHub link; do not summarize commentary as if it were a paper.
- Fallback chain: primary source -> project page -> abstract-only summary. Note abstract-only summaries when needed.

### 3b. Structured Chinese Summary

Use this structure exactly:

```markdown
## [Paper Title](url)

**Score**: X/10 | **Category**: cat1, cat2
**Authors**: first_author et al. | **Date**: YYYY-MM-DD | **Source**: source1, source2

### 一句话总结
<One Chinese sentence: core contribution and why it matters.>

### 核心贡献
- <Contribution 1>
- <Contribution 2>
- <Contribution 3 when useful>

### 方法要点
- <Technical approach>
- <Architecture or algorithm details>
- <Design tradeoffs when visible>

### 关键结果
- <Quantitative or qualitative result. If unavailable, say it was not confirmed from accessible sources.>

### 与我工作的关联
<2-3 Chinese sentences tied to the configured work context. Be specific and actionable.>
```

---

## Phase 4: Archive

### 4a. Local Markdown

Write to `digests/YYYY-MM-DD.md`. Create `digests/` if needed.

Use this header:

```markdown
# Paper Digest: YYYY-MM-DD

> Date range: YYYY-MM-DD to YYYY-MM-DD
> Collected: N unique candidates from X successful sources | Selected: M papers (threshold: T)
> Generated: YYYY-MM-DD HH:mm TZ
```

Then include:

```markdown
## Summary Table

| # | Score | Title | Categories | Source |
|---|-------|-------|------------|--------|
```

Append all structured summaries, separated by `---`.

### 4b. Optional Notion

If `archive.notion.enabled` is true and `archive.notion.database_id` is set:

1. Confirm the agent has Notion access.
2. Fetch the configured database or data source first to confirm schema.
3. For each selected paper, create a page with conservative property mapping:
   - `Title`: paper title.
   - `Score`: number.
   - `Category`: configured categories when supported.
   - `Date`: digest date.
   - `Source`: closest configured select value; map unsupported sources to `Other` if needed.
   - `userDefined:URL` or `URL`: paper URL, depending on schema.
   - `Summary`: one-sentence summary.
4. Notion failure for any paper -> record the error, continue, and keep local Markdown as the primary archive.

### 4c. Optional Obsidian

If `archive.obsidian.enabled` is true:

1. Read `archive.obsidian.vault_path`, `archive.obsidian.digest_directory`, and `archive.obsidian.filename_template`.
2. If `vault_path` is empty, skip Obsidian and report it as not configured.
3. Copy the generated local digest into `{vault_path}/{digest_directory}/{filename_template}`.
4. Replace `{date}` in `filename_template` with the digest date.
5. Create the target directory if needed.
6. Obsidian copy failure -> record the error, continue, and keep local Markdown as the primary archive.

### 4d. Update State

Only update state if at least one key phase succeeded.

Update `seen_papers.json`:

```json
{
  "arxiv_id_or_url": {
    "title": "Paper title",
    "score": 7.5,
    "selected": true,
    "date_seen": "YYYY-MM-DD",
    "source": "source1, source2"
  }
}
```

Update `last_run.json`:

```json
{
  "last_run_date": "YYYY-MM-DD",
  "last_run_status": "success",
  "papers_collected": 0,
  "papers_selected": 0
}
```

If all sources fail, do not advance `last_run_date`.

---

## Phase 5: Report

Use this final report shape:

```text
PaperPulse complete.

Date range: YYYY-MM-DD to YYYY-MM-DD
Sources: X/Y succeeded
Collected: N unique candidates
Selected: M papers
Archived: Local Markdown yes/no | Notion yes/no | Obsidian yes/no
Local file: digests/YYYY-MM-DD.md

Top papers:
1. [score/10] Paper title — one-line reason
2. [score/10] Paper title — one-line reason
```

---

## Error Handling

- Source fails: skip it and report in summary.
- Fetch fails for one paper: fall back to abstract-only summary and mark uncertainty.
- Notion fails: local Markdown still succeeds.
- All sources fail: do not update `last_run.json`.
- No papers pass filter: write minimal digest and update state if collection succeeded.
- Missing `config.yaml`: stop and ask user to copy `config.example.yaml`.

## Arguments

$ARGUMENTS
