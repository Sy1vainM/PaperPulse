# Data Source Fetch Reference

This file documents how agents should collect papers from each supported source. Use it as operational guidance, not as a replacement for `config.yaml`.

## General Rules

- Only collect from sources with `enabled: true`.
- Continue when a single source fails.
- Prefer primary paper links such as arXiv, OpenReview, ACL Anthology, CVF, project pages, or GitHub.
- Treat media articles as discovery signals, not primary paper records.
- Do not invent authors, metrics, or results. If a detail is unavailable, say it was not confirmed from accessible sources.

## arXiv

Config source name: `arxiv`

Fetch one query per configured category:

```text
https://export.arxiv.org/api/query?search_query=cat:{category}&start=0&max_results=100&sortBy=submittedDate&sortOrder=descending
```

Extract:

- title
- authors
- abstract
- arxiv_id
- published date
- URL
- categories

Use arXiv ID as the primary dedup key.

## HuggingFace Daily Papers

Config source name: `huggingface_daily`

Fetch:

```text
https://huggingface.co/papers
```

If available, also try:

```text
https://huggingface.co/papers/date/YYYY-MM-DD
```

Extract:

- title
- HuggingFace paper URL
- arXiv ID from URL or page content
- upvote count when visible
- authors and abstract when visible

Use HuggingFace primarily as a curation signal. Resolve to arXiv URLs when possible.

## Semantic Scholar

Config source name: `semantic_scholar`

Use only when enabled and rate limits allow it.

Extract:

- title
- authors
- abstract
- publication date or year
- paper URL
- DOI or arXiv ID when available
- citation or venue signal when useful

Treat 429 responses as source failure and continue.

## Papers With Code

Config source name: `papers_with_code`

Fetch:

```text
https://paperswithcode.com/latest
```

Extract:

- title
- task
- paper URL
- code URL
- date when visible

If it duplicates HuggingFace Daily, count it only as a multi-source signal.

## Blogs / RSS

Config source name: `blog_list`

Fetch each configured RSS or Atom URL.

Extract:

- title
- URL
- published date
- summary

Keep only entries with clear research value for the configured work context.

## Web Search

Config source name: `web_search`

Use configured query templates and replace `{date_range}` with the actual range.

Example query templates:

```text
latest multimodal LLM papers {date_range}
video understanding AI research {date_range}
efficient inference edge deployment {date_range}
agent memory visual perception paper {date_range}
```

Extract paper titles, source URLs, arXiv IDs, GitHub links, project pages, and dates. Skip product-only announcements, funding news, and commentary without original technical artifacts.

## OpenAlex

Config source name: `openalex`

Fetch works by representative keywords from configured categories:

```text
https://api.openalex.org/works?filter=from_publication_date:{start_date},to_publication_date:{end_date},type:article&search={keywords}&sort=publication_date:desc&per_page=25&select=id,title,authorships,abstract_inverted_index,doi,publication_date,primary_location,open_access
```

Extract:

- title
- authors
- reconstructed abstract when available
- DOI
- publication date
- source URL

If `abstract_inverted_index` is absent, keep the entry only if title and URL are relevant enough.

## Website

Config source name: `website`

Use as secondary discovery for user-configured websites.

Config example:

```yaml
sources:
  - name: website
    type: web
    enabled: true
    sites:
      - name: "Example Site"
        url: "https://example.com/"
```

Process:

1. Fetch recent article lists.
2. Keep articles about concrete papers, models, benchmarks, datasets, or technical frameworks.
3. Skip funding, hiring, gossip, and product-only news.
4. Open relevant articles and extract original paper, GitHub, model, benchmark, or project links.
5. Merge extracted technical artifacts into the main candidate pool.
6. Treat the website page as a discovery signal, not as the primary paper record.

## WeChat Public Accounts

Optional source name: `wechat_mp`

Use only if the local environment has an approved WeChat fetch path. Do not assume credentials or MCP tools are available.

Recommended connector stack:

- Agent-Reach: content access helper.
- mcporter: local MCP bridge runner.
- Exa MCP: web fetch/crawl backend for article extraction.

The public repository must not vendor these dependencies or store their credentials. See `docs/wechat-integration.md` for setup guidance.

Recommended behavior:

- Use explicit article URLs when available.
- Extract original paper links, GitHub links, project names, model names, institutions, and key results.
- Treat WeChat articles as discovery signals, not primary paper records.
- If `article_urls` is configured, fetch those first because explicit URLs are more reliable than channel discovery.
- If only channel names are configured, discover recent posts and keep only articles with concrete technical artifacts.
- Skip articles that are pure commentary, funding news, hiring, gossip, or product-only announcements.

## Scoring Notes

Raise scores for topics that match the user's configured work context, especially:

- Multimodal AI.
- Video understanding.
- Efficient inference.
- Agent memory.
- Evaluation and safety.
- Edge deployment.
- Practical engineering workflows.

Lower scores for:

- Pure product announcements.
- News without original technical artifacts.
- Papers outside the configured scope.
- Results with no accessible source details.
