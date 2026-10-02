---
name: viz-dashboards
description: Use for dashboards and data apps — Streamlit, Dash, Panel or BI tools, layout, caching, freshness.
---
# Dashboards and data apps
Hub: `data-visualization` (chart choice, color, uncertainty). Charts as Claude Artifacts or chat-surface dashboards: the built-in `dataviz` skill. Front-end code: `frontend-frameworks`. Serving and exposing an app on the home server: `self-hosting-ops`.

## Design
- Dashboards: each view answers one question; defaults that show the main message without interaction; consistent colors and scales across views; data freshness and n visible; pre-aggregate for speed; prefer a static report when interaction answers nothing new.
- Lay out by priority: the headline numbers (with comparison to target or previous period) top-left, trends next, detail and tables last; one screen without scrolling for the main message.
- Every number carries its unit, period, filter state and definition (tooltip or footnote); totals reconcile with the source.
- Filters change all views consistently; show active filters; defaults reproduce the main message.
- Performance: pre-aggregate in the database or a materialized table; cache queries with a TTL that matches data freshness; never load raw event tables into the browser.
- Access: authenticate anything with non-public data; dashboards are read paths — no writes back to production data without an explicit design.

## Tool choice
| Need | Tool |
|---|---|
| Python script → interactive app quickly | Streamlit (`st.cache_data` for query caching) |
| Callback-driven apps with plotly figures | Dash |
| HoloViz/Bokeh ecosystem, notebooks to apps | Panel |
| SQL + Markdown reports as static sites | Evidence (unverified as of 2026-10-02) |
| Operational metrics and time series | Grafana (`self-hosting-ops` for hosting) |
| A one-off report with no interaction needed | static HTML/PDF from `viz-matplotlib` or `data-visualization` `references/interactive.md` |

## Verify
- [ ] Each view states the question it answers; the main message is visible without interaction.
- [ ] Three displayed numbers recomputed from the source with the same filters.
- [ ] Data freshness and n shown; load time measured with production-sized data.
- [ ] Keyboard access and a table alternative for each chart (`web-accessibility`).

## Sources
- Verified 2026-10-02 https://pypi.org/pypi/streamlit/json — Streamlit 1.64.0; https://pypi.org/pypi/dash/json — Dash 4.4.1; https://pypi.org/pypi/panel/json — Panel 1.9.4.
- Unverified as of 2026-10-02: Evidence, `st.cache_data` naming (check the docs of the installed version).
