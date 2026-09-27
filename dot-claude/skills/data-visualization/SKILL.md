---
name: data-visualization
description: Load before making a chart, figure or dashboard meant to communicate data — choosing the chart by question, perception rules, colorblind-safe palettes, annotation and direct labels, small multiples, showing uncertainty, tables vs charts, matplotlib/seaborn publication defaults with vector export and embedded fonts, plotly/Altair interactivity, accessibility, misleading patterns and a pre-publication checklist.
---
# Data visualization

## Scope
Static and interactive figures whose job is to communicate a finding. The analysis behind the numbers → `data-analysis`; experiment result tables → `ml-experiment`; color spaces, print profiles and contrast math → `color-management`; charts inside slide decks → `presentation-design`; figures in LaTeX papers → `latex-typesetting`. Environment: the science venv `__CLAUDE_DIR__/venvs/sci/bin/python` has matplotlib, seaborn, pandas, polars; add plotly or Altair per project (`uv run --with plotly --with kaleido …`, `uv run --with altair --with vl-convert-python …`). APIs below were checked against matplotlib 3.11, seaborn 0.13, plotly with Kaleido ≥ 1 and Altair 5.

## 1. Start from the question
1. Write the one-sentence message and the audience (paper, slide, report, dashboard) before choosing anything.
2. Pick the form by the question:

| Question | Default | Alternatives | Avoid |
|---|---|---|---|
| Compare values across categories | sorted horizontal bars, dot plot | lollipop; grouped bars for ≤3 groups | pies with >3 slices, 3D bars |
| One distribution | histogram (state bin width), ECDF | density (state bandwidth), box + points | bar of the mean |
| Distributions across groups | box/violin with jittered points, ECDF overlay, ridgeline | small multiples of histograms | mean ± SE bars |
| Relationship of two numeric variables | scatter with alpha | hexbin/2D density for large n; smoother with band | dual axes |
| Change over time | line, time on x | slope chart (2 time points); small multiples (many series); area only for totals | >5–7 unhighlighted lines |
| Part-to-whole | 100% stacked bar, waffle | pie/donut for 2–3 parts | many-layer stacked areas |
| Ranking over time | bump chart | sorted dots per period | |
| Estimates with uncertainty | point + interval, bands, quantile dot plots | fan charts for forecasts | bare points |
| Spatial rates | choropleth of normalized rates | proportional symbols for counts | raw counts on a choropleth |
| Many variables | small multiples, ordered/clustered heatmap | parallel coordinates | 3D scatter |

3. Sketch, build, then read the result back against the message; if the message is not visible in five seconds, change the form, not the colors.

## 2. Perception
- Accuracy ranking (Cleveland & McGill): position on a common scale > position on unaligned scales > length > angle/slope > area > volume, color saturation. Put the key comparison on a common position axis.
- Bars encode length: zero baseline always. Dots and lines may start elsewhere when the axis says so.
- Aspect ratio: aim for the important slopes near 45° (Cleveland's banking); most time series want wide panels.
- Order categories by value or by their natural order, not alphabetically by default.
- One accent color for the focus, gray for context; direct attention, don't decorate.
- Log scales for multiplicative quantities or several orders of magnitude, labeled as such; handle zeros explicitly.
- Dual y-axes invite false correlations through arbitrary scaling: use two aligned panels or index both series to 100.
- Shared scales across panels unless within-panel shape is the point — then say "free y".

## 3. Color
- Categorical (≤ 7–8 classes): Okabe–Ito `#E69F00 #56B4E9 #009E73 #F0E442 #0072B2 #D55E00 #CC79A7 #000000`; matplotlib styles `petroff10` / `petroff8` / `petroff6` (accessible cycles from Petroff 2021), `tableau-colorblind10`, `seaborn-v0_8-colorblind`; seaborn palette `"colorblind"`.
- Sequential: perceptually uniform maps (viridis, cividis, magma) or one hue light → dark.
- Diverging (deviation from a meaningful center): ColorBrewer RdBu, PuOr, BrBG with the center pinned (`matplotlib.colors.TwoSlopeNorm(vcenter=0)` or `CenteredNorm()`).
- Never jet/rainbow for continuous data (non-uniform lightness creates false boundaries); never red vs green as the only distinction.
- Same category → same color in every figure of a piece of work; one neutral gray for "other"/missing.
- Redundant encoding (shape, line style, direct labels) so the figure survives grayscale and color-vision deficiency.
- Check: simulate CVD (`colorspacious`, not in the science venv — `uv run --with colorspacious`: `cspace_convert(rgb, {"name": "sRGB1+CVD", "cvd_type": "deuteranomaly", "severity": 100}, "sRGB1")`, likewise protanomaly and tritanomaly), print or render in grayscale; where the huetension color MCP server is available, use its WCAG/APCA contrast and color-blindness checks.

## 4. Text and annotation
- Title states the finding ("Median latency fell 38% after caching"); subtitle or caption says what, where, when, units, n and source.
- Axis labels with units; readable tick formats (thousands separators, consistent decimals, SI prefixes; percent vs percentage points spelled out).
- Direct labels at line ends or on bars instead of legends where possible; otherwise order the legend like the data.
- Annotate what the reader must notice: the key point, reference lines (target, baseline, zero), events.
- Remove non-data ink that does not help reading (3D, heavy frames, gradients, redundant gridlines); keep light gridlines when values will be looked up.
- Final-size legibility: ≥ 7–8 pt in print, larger on slides; draw at the final size instead of scaling afterwards.

## 5. Small multiples
Same axes and scales, one panel per group, meaningful panel order, panel titles as direct labels; highlight each panel's series against the others in gray to fix spaghetti plots. seaborn figure-level functions (`relplot`, `displot`, `catplot` with `col=`, `row=`, `col_wrap=`), or `plt.subplots(nrows, ncols, sharex=True, sharey=True)`.

## 6. Uncertainty
- Name the interval every time: 95% CI of the mean, ±1 SD, 50/90% prediction interval, bootstrap percentile CI — plus n.
- Estimates: point + interval (dot-and-whisker). Curves and forecasts: bands (`fill_between`), nested 50/80/95% for gradation. Predictive distributions: quantile dot plots or a sample of draws. Small n: show the raw points.
- seaborn (≥ 0.12): `errorbar=("ci", 95)`, `("pi", 50)`, `"se"`, `"sd"`, with `n_boot` and `seed` for bootstrap reproducibility.
- Overlapping intervals are not a test; when a comparison matters, plot the difference with its interval (`data-analysis`).

## 7. Table or chart
Table when readers need exact values, the numbers are few, units are mixed, or there is no pattern to see; chart when shape, trend or comparison is the point. Tables: right-aligned numbers with equal decimals per column, units in headers, meaningful row order, sparse highlighting of the cells that carry the message.

## 8. matplotlib and seaborn for publication
```python
import matplotlib as mpl, matplotlib.pyplot as plt
plt.style.use("petroff10")                      # color cycle only; apply before the rc overrides
mpl.rcParams.update({
    "figure.constrained_layout.use": True,
    "pdf.fonttype": 42, "ps.fonttype": 42,      # embed TrueType (default 3 = Type 3 fonts)
    "svg.fonttype": "none",                     # keep text as text in SVG (default "path")
    "savefig.dpi": 300, "savefig.bbox": "tight",
    "font.size": 9, "axes.titlesize": 10, "axes.labelsize": 9, "legend.fontsize": 8,
    "axes.spines.top": False, "axes.spines.right": False,
})
fig, ax = plt.subplots(figsize=(3.5, 2.4))      # draw at final size; column widths are venue-specific
...
fig.savefig("fig.pdf"); fig.savefig("fig.svg"); fig.savefig("fig.png", dpi=300)
```
- Vector (PDF/SVG) for line art; for dense scatters or images keep the axes vector and rasterize the heavy artist (`rasterized=True`), or export PNG ≥ 300 dpi.
- Fonts: match the document's font where installed (`font.family`), mathtext via `mathtext.fontset` (`"cm"`, `"stix"`, …) or full LaTeX (`text.usetex`) when equations must match a LaTeX paper.
- Verify embedding: `pdffonts fig.pdf` should list only embedded (`emb yes`) TrueType/CID TrueType fonts, no Type 3.
- seaborn: `sns.set_theme(context="paper", style="ticks", palette="colorblind")`; figure-level functions for facets; `seaborn.objects` (`so.Plot(df, x=..., y=...).add(so.Dot(), so.Jitter())`) for layered grammar.
- Put styling in one module or `.mplstyle` file shared by every figure of the project; generate figures from scripts, never by hand edits.

## 9. Interactive: plotly and Altair
- plotly: `px.line/px.scatter/...` with `hover_data` and hover templates carrying units; `fig.write_html("f.html", include_plotlyjs="cdn")` (small, needs network) or `include_plotlyjs=True` (self-contained). Static export `fig.write_image("f.pdf")` needs Kaleido ≥ 1.0 and a Chrome install (`plotly_get_chrome` or `plotly.io.get_chrome()`); WebGL traces export partly rasterized in vector formats.
- Altair: typed encodings (`alt.Chart(df).mark_line().encode(x="date:T", y="value:Q", color="series:N")`), `.interactive()` and selections for linked views; `chart.save("c.html")`; PNG/SVG/PDF need `vl-convert-python` (`chart.save("c.png", ppi=200)` or `scale_factor=2`); more than 5000 rows raises `MaxRowsError` → `alt.data_transformers.enable("vegafusion")`, pass data by URL, or pre-aggregate.
- Dashboards: each view answers one question; defaults that show the main message without interaction; consistent colors and scales across views; data freshness and n visible; pre-aggregate for speed; prefer a static report when interaction answers nothing new.

## 10. Accessibility
- Alt text: chart type, what is plotted, the takeaway and the notable values, in 1–3 sentences; for complex figures add a longer description or the data table. Don't repeat the caption verbatim.
- Contrast (WCAG 2.x): text ≥ 4.5:1 (≥ 3:1 for large text); graphical elements needed to understand the chart ≥ 3:1 against adjacent colors.
- No color-only encodings; no thin light-gray text; interactive charts need keyboard access and a table alternative, since SVG/canvas charts are opaque to screen readers.

## 11. Misleading patterns

| Pattern | Effect | Fix |
|---|---|---|
| Truncated bar axis | exaggerates differences | zero baseline or a dot plot |
| Dual y-axes | arbitrary scaling fakes correlation | aligned panels, indexed series |
| 3D and perspective pies | distort angle and area | flat 2D |
| Symbol radius ∝ value | area grows with the square | scale area, or use bars |
| Cherry-picked time window | hides context | full range, or justify the window |
| Cumulative totals for flows | everything rises | plot rate or level |
| Uneven bins or silent time gaps | distorted density or trend | equal bins or density scale; mark gaps |
| Rainbow colormap | false boundaries | viridis/cividis |
| Mean bars without spread | hides variability | points + intervals |
| Raw counts on maps | population map in disguise | per-capita rates |
| Overplotting | hides density | alpha, hexbin, jitter, sampling |
| Smooth curve without data | hides noise and n | points or band behind the fit |

## 12. Pre-publication checklist
- [ ] Title or caption states the message; the chart shows it at a glance
- [ ] Form fits the question; the key comparison sits on a common position scale
- [ ] Axes labeled with units; bars start at zero; panel scales consistent (or declared free)
- [ ] Colorblind-safe, consistent color encoding; readable in grayscale; contrast checked
- [ ] Uncertainty shown and defined (interval type, n)
- [ ] Direct labels or annotations where they help; legend order matches the data
- [ ] Plotted values recomputed from the data and matching the text
- [ ] Source, date and n in the caption; script and data snapshot reproduce the figure
- [ ] Exported at final size; PDF/SVG with embedded fonts or PNG ≥ 300 dpi
- [ ] Alt text written

## Verify
Regenerate from the script and diff the outputs; check three plotted values against the data; view at final size, in grayscale and under CVD simulation; `pdffonts` shows only embedded non-Type-3 fonts; a cold reader can state the takeaway after five seconds.

## Deliverables
The script or notebook, exported files (PDF/SVG and PNG), caption (message, interval definition, n, source, date), alt text, and the data snapshot or query behind the figure.
