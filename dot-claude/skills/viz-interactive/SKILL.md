---
name: viz-interactive
description: Use when a chart must be interactive or HTML — plotly or Altair, hover and selection, static export, large datasets.
---
# Interactive charts: plotly and Altair
Hub: `data-visualization` (chart choice, perception, color, uncertainty, checklist; design rules in `data-visualization` `references/design-rules.md`). APIs were checked earlier against matplotlib 3.11, seaborn 0.13, plotly with Kaleido ≥ 1 and Altair 5 without recorded URLs: unverified as of 2026-10-02.

- plotly: `px.line/px.scatter/...` with `hover_data` and hover templates carrying units; `fig.write_html("f.html", include_plotlyjs="cdn")` (small, needs network) or `include_plotlyjs=True` (self-contained). Static export `fig.write_image("f.pdf")` needs Kaleido ≥ 1.0 and a Chrome install (`plotly_get_chrome` or `plotly.io.get_chrome()`); WebGL traces export partly rasterized in vector formats.
- Altair: typed encodings (`alt.Chart(df).mark_line().encode(x="date:T", y="value:Q", color="series:N")`), `.interactive()` and selections for linked views; `chart.save("c.html")`; PNG/SVG/PDF need `vl-convert-python` (`chart.save("c.png", ppi=200)` or `scale_factor=2`); more than 5000 rows raises `MaxRowsError` → `alt.data_transformers.enable("vegafusion")`, pass data by URL, or pre-aggregate.

## Verify
- [ ] HTML opens offline when it must (`include_plotlyjs=True`) or the CDN dependency is stated.
- [ ] Static exports (PDF/PNG/SVG) render with the same content as the HTML; Kaleido/vl-convert versions recorded.
- [ ] Hover text carries units; a keyboard user and a screen reader get a table alternative (hub checklist).
