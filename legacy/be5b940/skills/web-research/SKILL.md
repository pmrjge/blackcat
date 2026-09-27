---
name: web-research
description: Web search, scraping and crawling procedure — tool ladder, budgets, source quality and citation format. Use before any web work beyond a single WebSearch.
---
# Web research

## Tool ladder (cheapest adequate tool first)
1. **WebSearch** — discovery and quick facts.
2. **WebFetch** — one known URL; ask it a precise question (it returns an extract, not the page).
3. **mcp__jina** — `read_url` gives a page or PDF as clean markdown (pass `question` to get only the relevant passages); `search_arxiv` / `search_ssrn` for papers; `extract_pdf` for figures/tables/equations; `capture_screenshot_url` when layout matters; `sort_by_relevance` to rerank many snippets; `guess_datetime_url` to date a page.
4. **mcp__exa** — `web_search_exa` (semantic search with content), `web_search_advanced_exa` (domain/date filters, subpage crawling), `web_fetch_exa` (several URLs in one call), `agent_run` (multi-step research — only when cheaper than doing it yourself).
5. **mcp__spider** (researcher only) — `spider_crawl` for a whole site or section (always set limit and depth), `spider_scrape` for JS-heavy single pages, `spider_links` to map a site first, `spider_unblocker` only when blocked. Check cost with `spider_get_credits` before big crawls.

## Budget and hygiene
- Write down what "answered" means before searching; stop the moment it is met.
- Run independent queries in parallel in one message; keep the overall rate under ~10 requests/second.
- Prefer passages to full pages. Never paste raw pages into your context or output.
- Log each source you rely on (URL, publisher, date) as you go.

## Source quality
Primary (official docs, specs, filings, papers, changelogs, datasets) > reputable secondary (major outlets, recognized experts) > everything else. Check dates: for "current" facts prefer sources under 6 months old and state the as-of date. Contested claims need two independent sources; report disagreements rather than averaging them.

## Citation format
Inline `[n]` markers, then:
```
Sources:
[n] Title — Publisher, YYYY-MM-DD — URL
```
Quote at most one sentence per source; paraphrase the rest.
