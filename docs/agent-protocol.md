# PaperPulse Agent Protocol

This document defines the shared workflow for all supported agents. Codex and Claude Code entry files should delegate to this protocol instead of maintaining separate logic.

## Goal

Run a daily paper digest workflow:

1. Determine the date range to cover.
2. Collect new research items from enabled sources.
3. Deduplicate against previous runs.
4. Rank papers by their contribution to a tracked research field.
5. Deep-read the configured number of highest-ranked papers.
6. Write a rich Chinese Markdown source document.
7. Render an interactive HTML report when enabled.
8. Optionally archive selected papers to Notion or Obsidian.
9. Update state only after at least one key phase succeeds.

## Required Files

Read these files before collecting:

- `config.yaml`
- `last_run.json`
- `sources-reference.md`

If `config.yaml` is missing, tell the user to copy `config.example.yaml` to `config.yaml` and customize it.

If a runtime state file is missing, initialize it from the versioned template:

- `last_run.example.json` -> `last_run.json`
- `seen_papers.example.json` -> `seen_papers.json`

The runtime state files and generated Markdown/HTML digests are private local data and must remain ignored by Git.

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

Keep historical state out of model context. Send the private candidate JSON array to the local helper:

```sh
python3 scripts/dedup_seen.py filter --input candidates.json > unseen.json
```

The output contains `candidates` and counts for input, repeated items in the batch, historical matches and unseen items. The helper also accepts stdin. It matches arXiv versions, DOI, normalized URL or Unicode-normalized title, including chains across sources. Keep the returned identity aliases with candidates while ranking; pass only actually processed entries to `record` after success. Empty historical state may be initialized from the template; never load the historical ledger into a prompt.

## Scoring Rules

Use `filter.categories` to identify the research field and the problem the paper addresses. Score its contribution to that field using primary evidence. Keep `filter.my_work_context` for commentary after selection.

For each enabled source that supports topic queries, search the configured fields by their own vocabulary. For a sports reconstruction field, include single-view and multi-view work, fast motion in different sports, human–equipment interaction, and biomechanics. Distinguish what was observed (camera views and frame rate), what was reconstructed (pose, equipment trajectory), and what was inferred (forces or joint moments). A useful benchmark or failure analysis can merit selection across sports. In the report, briefly identify fields searched with no qualifying evidence when known; avoid treating a failed search as zero research.

Use these dimensions and weights:

| Dimension | Weight | Evaluates |
|---|---:|---|
| Field contribution | 35% | How much does the work advance an important problem in a tracked field? Consider methods, datasets, measurements and well-supported negative results. |
| Innovation | 25% | New architecture, method, benchmark, or paradigm. |
| Impact | 20% | Strong results, open code, strong baselines, or community attention. |
| Method Quality | 10% | Technical soundness visible from abstract or paper page. |
| Practicality | 10% | Whether researchers in the field can reproduce, compare or build on the work. |

Scale final score to `1-10`.

Use multiple discovery sources and editorial recommendations to locate evidence. The same paper keeps its score, rank and deep-reading priority when the user changes projects or experiment versions. Break ties by strength of primary evidence.

Selection:

1. Keep score `>= filter.threshold`.
2. Keep at most `filter.max_papers_per_day`.
3. Fix the selection and ranking before considering project fit. In each Chinese summary, first explain the field contribution, comparison and evidence limits. Then use the work context to describe a possible application, its prerequisites, or “暂无直接关联”.
4. If no paper passes the threshold, write a minimal digest noting that no papers passed and still update state if collection succeeded.

## Reading Depth Rules

Use a tiered reading policy so the report gains evidence without making every daily run unnecessarily expensive.

1. Rank candidates using official abstracts and primary metadata first.
2. Read the original full text for the top `report.deep_read_top_n` selected papers. Prefer official arXiv HTML or PDF and inspect at minimum:
   - problem definition and claimed novelty;
   - method or system architecture;
   - experiment setup, datasets, baselines, and exact headline metrics;
   - ablations or failure analysis when available;
   - limitations, compute requirements, and release status.
3. For the remaining selected papers, verify the official abstract, paper page, and primary project/code page when available.
   - Record the official PDF separately from the abstract page.
   - Record author-owned project and code URLs when they can be verified.
   - Prefer one representative teaser or method figure from the official paper HTML or author-owned project page. Validate that the URL resolves to an image before recording it.
   - Place the verified figure next to the Chinese explanation it supports using standalone Markdown image syntax. Write a caption that points to something visible and explains what the reader can learn. For example, identify where the method selects frames and what happens to the frames it keeps. Introduce technical terms in everyday language on first use.
   - If a figure is unavailable, show a short text flow for a verified method or a compact results table with baseline, metric, units and test conditions. Mark your own diagrams as explanatory. Compare numbers only under matching evaluation conditions.
   - Never use search-result thumbnails, screenshots from secondary articles, or an unrelated generated image as a paper figure.
4. Label every paper honestly:
   - `全文精读`: method, experiments, and limitations checked in the original paper;
   - `摘要核验`: official abstract and primary metadata checked, without a full-paper claim.
5. Assign an evidence level: `同行评审`, `预印本`, or `二手发现信号`. A secondary article may aid discovery but must not be graded as paper evidence.
6. Never infer a full-text result from a blog, search snippet, or secondary article.
7. Every exact metric or technical claim in the evidence section must point to the original paper, table, section, or official project source in the same card.
8. Target roughly 600-1000 Chinese characters for each full-text review and 250-500 for each abstract-verified paper. Prefer concrete evidence over padding.
9. If the full text is inaccessible, downgrade the label to `摘要核验` and state the access limitation.

## Digest Content and Format

Write `digests/YYYY-MM-DD.md`.

The Markdown file is the canonical content source; the HTML file is the primary reading surface. Organize the report in two levels:

1. Decision layer:
   - `背景`: what changed in today's research landscape;
   - `问题`: the production or research bottlenecks these papers address;
   - `方案`: the shared technical direction across papers;
   - `效果`: evidence summary plus Go/Watch/No-Go decisions;
   - `今日决策`: the three most important conclusions;
   - `行动建议`: where warranted, describe a project application, its prerequisites and a test. A digest can have no project actions;
   - `数据源状态`: one normalized row for every configured source, including disabled and skipped sources.
   - `证据与生成说明`: reading-depth policy, unavailable evidence, and an AI-assisted research disclosure.
When an evidence gap warrants deeper investigation, add a short “值得继续追的问题” next to the relevant paper. Give the primary link, the comparison or citation worth checking, and what finding would change the interpretation. This is an input for MorrowOS; publish the digest without waiting for its follow-up.

2. Evidence layer: one expandable card per selected paper in the HTML report.

Header:

```markdown
# Paper Digest: YYYY-MM-DD

> Date range: YYYY-MM-DD to YYYY-MM-DD
> Collected: N unique candidates from X successful sources | Selected: M papers (threshold: T)
> Generated: YYYY-MM-DD HH:mm TZ
```

Data source status table:

```markdown
## 数据源状态

| 数据源 | 状态 | 当日结果 |
|---|---|---|
| arXiv | 成功 | 120 篇去重条目 |
| Optional Source | 已停用 | 当前配置未启用 |
```

Use exactly one of these states: `成功`, `部分成功`, `失败`, `已停用`, or `未运行`.

- Include every entry from `sources` in `config.yaml`, even when it is disabled or skipped.
- Count only `失败` as a failure. `已停用` and `未运行` are neutral states and must never inflate the failure count.
- Use `部分成功` when at least one sub-feed or query succeeds and another fails.
- Put HTTP codes, redirect details, missing dependencies, and retry guidance in `当日结果`, not in the state value.
- Keep the table as a run-time snapshot. If a source is repaired later, either regenerate the snapshot or explicitly state the recheck time and preserve the original failure in the note.

Summary table:

```markdown
## Summary Table

| # | Score | Title | Categories | Source |
|---|-------|-------|------------|--------|
```

Per-paper format:

```markdown
## [Paper Title](url)

**Score**: X/10 | **Category**: cat1, cat2 | **Read Depth**: 全文精读 / 摘要核验
**Authors**: first_author et al. | **Date**: YYYY-MM-DD | **Source**: source1, source2
**Evidence Level**: 同行评审 / 预印本 / 二手发现信号
**Links**: [PDF](url) | [代码](url) | [项目主页](url) | [主图](official-image-url)

### 核心突破与做法
第一句用中文写清核心突破。随后解释方法，配作者原图及图注，写明读者应该观察什么；图或许可不可核验时保留来源链接。

### 关键证据与适用边界
列出数据、对照、指标及一手出处；说明失效条件、缺失的实验或未核实部分。

### 与我工作的关联与下一步
给出适用前提及一个可验证的动作；没有直接关联时如实说明。

### 交给 MorrowOS 追查的问题与一手链接
写清要复查哪个实验或对照、什么证据会改变判断，并附原文、项目或代码。
```

After the decisions, add a separate `## 行业与开源速递（微信信源）`. Aim for 3–5 distinct, verified non-paper releases or industry developments. Include date, what materially changed, the WeChat discovery link, and the original release or changelog link. Verify both publication and original release dates. When evidence is thin publish fewer or explicitly record the gap. Never put these items into paper counts or rankings.

For `摘要核验` papers, keep unavailable sections concise and explicitly say which evidence was not verified. Do not invent missing experiments, compute, code status, or limitations.

Resource links are optional and evidence-driven. Omit `代码`, `项目主页`, or `主图` when no author-owned or official source can be verified; missing artwork must never block an otherwise valid daily report.

End the decision layer with a short disclosure that AI-assisted tools performed collection, ranking, and summarization, and that the reading-depth and evidence labels describe the actual verification completed in this run.

All digest prose should be in Chinese unless the user asks otherwise.

## HTML Rendering Rules

When `report.html.enabled` is true, render the completed Markdown after its content has been validated:

```bash
python3 scripts/render_digest.py digests/YYYY-MM-DD.md --open-top N
```

Use `report.html.open_top_n` for `N`. The output is `digests/YYYY-MM-DD.html`.

Every successful dated render also rebuilds `digests/index.html`, a stable local archive that lists all rendered reports newest-first. Users should bookmark this file, select a date there, and use the PaperPulse brand or `日报列表` action in a report to return. The archive contains only relative report filenames and remains private under the existing `digests/*` ignore rule.

The renderer provides:

- an executive header and daily metrics;
- responsive desktop/mobile layout;
- a compact decision brief and a direction-filterable table linking to expanded paper cards;
- searchable, expandable paper cards;
- visible score, category, reading-depth, and one-line conclusion;
- an optional official paper figure, compact authorship metadata, and separate paper/PDF/project/code/figure actions;
- light/dark theme, reading progress, and print styles;
- offline Mermaid source blocks and document-relative or HTTPS paper figures.

If HTML rendering fails, keep the Markdown source, report the HTML failure, and do not claim that the HTML artifact exists.

## Privacy and Public Release Rules

The repository is public code; runtime research data is private by default.

1. Never copy values from `config.yaml`, runtime state, generated digests, logs, local MCP configuration, or environment files into tracked source, tests, prompts, or documentation.
2. Keep real work context, source channels, archive IDs, local paths, collected-paper history, and generated reports only in Git-ignored files.
3. Use `config.example.yaml`, `last_run.example.json`, and `seen_papers.example.json` as sanitized public templates.
4. Tests must use synthetic placeholder values and must not embed a real home-directory path, database ID, article history, credential, or private endpoint.
5. Before any public push, run `python3 scripts/check_public_release.py`; a non-zero exit blocks the release.
6. Error messages and logs may name a field or file but must not print credential values.

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
2. Render `digests/YYYY-MM-DD.html` when enabled.
3. Run `python3 scripts/dedup_seen.py record --input processed.json` with selected papers and evaluated rejections, including score, selected flag, reading depth and date_seen where available.
4. Update `last_run.json`.

Every attempted run, including partial and failed runs, writes a private structured summary to `logs/YYYY-MM-DD.json`: date, coverage, status, per-source state, dedup counts, selected count, actual deep-read count, verified WeChat releases, render/archive status, and concise failure reasons. Never include credentials or raw articles. Record only observed counts; use null for unavailable measurements. For repeat attempts on the same date retain the preceding attempt in the log. An already-completed-day skip preserves the existing success record.

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
- Local Markdown path.
- Local HTML path and render status.
- Notion archive status.
- Obsidian archive status.
- Top selected papers with one-line reasons.

## Safety Rules

- Do not invent papers, authors, metrics, or URLs.
- Do not commit private `config.yaml`.
- Do not expose API keys, tokens, cookies, private paths, private Notion database IDs, or private Obsidian vault paths.
- Prefer source attribution and uncertainty over confident guessing.

## Daily Feishu card

After writing the dated Markdown and HTML, run `python3 scripts/send_feishu_card.py --digest digests/YYYY-MM-DD.md --send` when local feishu.enabled is true. Use the digest produced by this run. Preview with `--dry-run --output-json preview.json`. Record delivery success or warning in the daily structured log. Keep the digest and archival state on delivery failure. Retries for the same digest use the same daily idempotency key. Keep recipient IDs and installation paths in the ignored local config.
