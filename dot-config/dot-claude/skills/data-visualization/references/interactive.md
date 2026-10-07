# data-visualization — interactive charts: plotly and Altair (reference)
Read when a chart must be interactive or HTML (plotly, Altair). Parent: `data-visualization` SKILL.md (chart choice, perception, color, uncertainty, checklist); design rules in `references/design-rules.md`. APIs verified on Python 3.13 with matplotlib 3.11.2, seaborn 0.13.2, plotly 7.1.0 (Kaleido 1.4.0), Altair 6.3.0 (vl-convert-python 1.9.0.post1, vegafusion 2.0.3), as of 2026-10-04; plotly `write_image` and WebGL rasterization stay unverified (Chrome could not start in the verification sandbox).

- plotly: `px.line/px.scatter/...` with `hover_data` and hover templates carrying units; `fig.write_html("f.html", include_plotlyjs="cdn")` (small, needs network) or `include_plotlyjs=True` (self-contained). Static export `fig.write_image("f.pdf")` needs Kaleido ≥ 1.0 and a Chrome install (`plotly_get_chrome` or `plotly.io.get_chrome()`); WebGL traces export partly rasterized in vector formats.
- Altair: typed encodings (`alt.Chart(df).mark_line().encode(x="date:T", y="value:Q", color="series:N")`), `.interactive()` and selections for linked views; `chart.save("c.html")`; PNG/SVG/PDF need `vl-convert-python` (`chart.save("c.png", ppi=200)` or `scale_factor=2`); more than 5000 rows raises `MaxRowsError` → `alt.data_transformers.enable("vegafusion")` (needs `--with vegafusion --with pyarrow` for pandas input), pass data by URL, or pre-aggregate.

## Verify
- [ ] HTML opens offline when it must (`include_plotlyjs=True`) or the CDN dependency is stated.
- [ ] Static exports (PDF/PNG/SVG) render with the same content as the HTML; Kaleido/vl-convert versions recorded.
- [ ] Hover text carries units; a keyboard user and a screen reader get a table alternative (hub checklist).
