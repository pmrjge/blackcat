---
name: web-research
description: Use before web work beyond one WebSearch — tool ladder, crawling, budgets, source quality, citations.
---
# Web research

## Tool ladder (cheapest adequate tool first)
1. **WebSearch** — discovery and quick facts.
2. **WebFetch** — one known URL; ask it a precise question (it returns an extract, not the page).
3. **context-mode** (researcher, doc-specialist) — `ctx_fetch_and_index` (one `url`, or a batch in `requests` with `concurrency`) stores pages in a local search index and returns only a short preview; `ctx_search` (every question in one `queries` array) returns just the matching passages, verbatim. For long pages, docs sections and anything you will query more than once; `ctx_index` does the same for a local file. The page itself never enters your context.
4. **mcp__jina** (needs `JINA_API_KEY`; without it only `guess_datetime_url` works — fall back to WebFetch) — `read_url` gives a page or PDF as clean markdown (pass `question` to get only the relevant passages); `search_arxiv` / `search_ssrn` for papers; `extract_pdf` for figures/tables/equations; `capture_screenshot_url` when layout matters; `sort_by_relevance` to rerank many snippets; `guess_datetime_url` to date a page.
5. **mcp__exa** — `web_search_exa` (semantic search with content), `web_search_advanced_exa` (domain/date filters, subpage crawling), `web_fetch_exa` (several URLs in one call). Works without a key (rate-limited); `EXA_API_KEY` raises the limits.
6. **mcp__spider** (researcher only) — `spider_crawl` for a whole site or section (set limit and depth), `spider_scrape` for JS-heavy single pages, `spider_links` to map a site first. Check cost with `spider_get_credits` before big crawls.

Per-call caps (results, characters, pages, depth) and Spider's politeness rules (robots.txt obeyed, 1 s crawl delay, concurrency 2) are applied by a hook (`hooks/web_caps.py`, values in stack.env); a changed call says so in its context. The hook refuses Spider's bypass tools and options (`spider_unblocker`, `spider_browser_open`, proxies, fingerprint, user_agent, cookies) unless the user enabled them.

## Blocked pages
Public pages only; the aim is a polite fetch, not defeating the protection. No CAPTCHA solving, stealth or fingerprint tricks, user-agent spoofing, proxy rotation, someone's cookies or login, or ignoring robots.txt.
- **Recognise**: HTTP 403, 429 or 503; a challenge or interstitial title ("Just a moment…", "Attention Required", "Access denied", "Verify you are human", "Checking your browser"); a CAPTCHA; a body that is empty, a few hundred characters of boilerplate, or only an "enable JavaScript" notice. A page disallowed by robots.txt counts as blocked for crawlers.
- **Escalate in this order**, one URL at a time, stopping at the first rung that returns the content:
  1. Retry the same tool at most twice with exponential backoff and jitter (about 5 s then 20 s, ±30%), never sooner than a `Retry-After` header says; do other sub-questions in between rather than idling. `Retry-After` over 2 minutes → skip to rung 2.
  2. Rendered fetch: `spider_scrape` with `request: "chrome"` (researcher), or jina `read_url` for agents without Spider.
  3. Another reader or a cached copy: jina `read_url`, exa `web_fetch_exa` (Exa's index), then the publisher's official mirror, feed, API or the Wayback Machine (`https://web.archive.org/web/<url>`) — cite the copy's URL and date.
  4. A real browser: NEXT: browser-operator (headless Playwright, or the user's Chrome) with the URL and what to read; it stops at CAPTCHAs and logins.
  5. Stop: report the URL as blocked (status code or challenge seen, rungs tried) in CONFIDENCE & GAPS, or STATUS: partial.
- Every retry and rung is a tool call that counts against the session's MCP and search caps; at a cap, go straight to rung 5. Keep any one site under ~1 request per second across all your calls; never fan out parallel calls to a site that is pushing back.

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

Division of labour: this skill is the tool and sourcing procedure for any web lookup. `anthropic-skills:deep-research` plans and coordinates a multi-source narrative report (it spawns research subagents, which then follow this procedure). `literature-review` covers papers, preprints and checking every citation.
