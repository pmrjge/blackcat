# Figure design rules (reference)
Read when writing titles, labels and annotations, building small multiples, deciding table vs chart, writing alt text, or reviewing a figure for misleading patterns. Parent: `data-visualization` SKILL.md.

## 4. Text and annotation
- Title states the finding ("Median latency fell 38% after caching"); subtitle or caption says what, where, when, units, n and source.
- Axis labels with units; readable tick formats (thousands separators, consistent decimals, SI prefixes; percent vs percentage points spelled out).
- Direct labels at line ends or on bars instead of legends where possible; otherwise order the legend like the data.
- Annotate what the reader must notice: the key point, reference lines (target, baseline, zero), events.
- Remove non-data ink that does not help reading (3D, heavy frames, gradients, redundant gridlines); keep light gridlines when values will be looked up.
- Final-size legibility: ≥ 7–8 pt in print, larger on slides; draw at the final size instead of scaling afterwards.

## 5. Small multiples
Same axes and scales, one panel per group, meaningful panel order, panel titles as direct labels; highlight each panel's series against the others in gray to fix spaghetti plots. seaborn figure-level functions (`relplot`, `displot`, `catplot` with `col=`, `row=`, `col_wrap=`), or `plt.subplots(nrows, ncols, sharex=True, sharey=True)`.

## 7. Table or chart
Table when readers need exact values, the numbers are few, units are mixed, or there is no pattern to see; chart when shape, trend or comparison is the point. Tables: right-aligned numbers with equal decimals per column, units in headers, meaningful row order, sparse highlighting of the cells that carry the message.

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
