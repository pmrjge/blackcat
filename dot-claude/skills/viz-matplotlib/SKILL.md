---
name: viz-matplotlib
description: Use for publication figures in matplotlib or seaborn — styles, fonts, figure sizes, facets, export.
---
# matplotlib and seaborn for publication
Hub: `data-visualization` (chart choice, perception, color, uncertainty, checklist; design rules in `data-visualization` `references/design-rules.md`). APIs were checked earlier against matplotlib 3.11, seaborn 0.13, plotly with Kaleido ≥ 1 and Altair 5 without recorded URLs: unverified as of 2026-10-02.

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

## Verify
- [ ] Figure regenerated from the script at final size; `pdffonts fig.pdf` lists only embedded, non-Type-3 fonts.
- [ ] Shared style module or `.mplstyle` used by every figure of the project.
- [ ] Dense layers rasterized or PNG ≥ 300 dpi; vector axes and text kept.
