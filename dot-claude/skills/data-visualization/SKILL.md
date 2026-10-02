---
name: data-visualization
description: Load before making a data figure in code — chart choice, perception, palettes, labels, uncertainty; Artifact or HTML charts load dataviz.
---
# Data visualization

## Scope
Figures made in code and saved as files (PNG/SVG/PDF/HTML) for papers, reports, notebooks and slides. Charts built as Artifacts, React/HTML pages or chat-surface dashboards → the built-in `dataviz` skill. The analysis behind the numbers → `data-analysis`; experiment result tables → `ml-experiment`; color spaces, print profiles and contrast math → `color-management`; charts inside slide decks → `presentation-design`; figures in LaTeX papers → `latex-typesetting`. Environment: the science venv `__CLAUDE_DIR__/venvs/sci/bin/python` has matplotlib, seaborn, pandas, polars; add plotly or Altair per project (`uv run --with plotly --with kaleido …`, `uv run --with altair --with vl-convert-python …`). APIs below were checked against matplotlib 3.11, seaborn 0.13, plotly with Kaleido ≥ 1 and Altair 5.

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

## 6. Uncertainty
- Name the interval every time: 95% CI of the mean, ±1 SD, 50/90% prediction interval, bootstrap percentile CI — plus n.
- Estimates: point + interval (dot-and-whisker). Curves and forecasts: bands (`fill_between`), nested 50/80/95% for gradation. Predictive distributions: quantile dot plots or a sample of draws. Small n: show the raw points.
- seaborn (≥ 0.12): `errorbar=("ci", 95)`, `("pi", 50)`, `"se"`, `"sd"`, with `n_boot` and `seed` for bootstrap reproducibility.
- Overlapping intervals are not a test; when a comparison matters, plot the difference with its interval (`data-analysis`).

## Modules
| Module | Load when |
|---|---|
| `viz-matplotlib` | static publication figures with matplotlib or seaborn: styles, fonts, export |
| `viz-interactive` | interactive/HTML charts with plotly or Altair: hover, static export, large data |
| `viz-dashboards` | dashboards and data apps: Streamlit, Dash, Panel, BI tools; layout and freshness |

## References
- `references/design-rules.md` — read when writing titles, labels and annotations, building small multiples, choosing table vs chart, writing alt text, or checking for misleading patterns.

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
