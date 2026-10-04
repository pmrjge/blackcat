---
name: diagrams-as-code
description: Use for diagrams as text — Mermaid, Graphviz, D2, PlantUML, TikZ/tikz-cd; rendering, embedding.
---
# Diagrams as code

## Scope
- Structural diagrams kept as text: flowcharts, sequence/state/class/ER, architecture, dependency graphs,
  commutative and string diagrams. Data plots are out of scope (`data-visualization`); hand-drawn inline-SVG diagrams inside Artifacts → the built-in `artifact-diagramming` skill. What a categorical
  diagram asserts is `category-theory`; LaTeX documents and builds are `latex-typesetting`; SVG cleanup is
  `svg-vector-craft`; site/Pandoc pipelines are `markdown-publishing`.
- Checked Sep 2026: Mermaid and mermaid-cli 12.0, Graphviz 16.1, D2 0.9.0, PlantUML 1.2026.8, TeX Live
  (tikz-cd, quiver.sty 1.7), dvisvgm 3, poppler 26. Every snippet below was rendered.
- Latest releases Verified 2026-10-02: mermaid 12.1.0 and @mermaid-js/mermaid-cli 12.0.0 (https://registry.npmjs.org/<pkg>/latest);
  Graphviz 16.1.0 (gitlab.com/graphviz/graphviz tags), D2 0.9.0 (github.com/terrastruct/d2 tags), PlantUML 1.2026.8
  (github.com/plantuml/plantuml tags). quiver.sty, dvisvgm and poppler versions: unverified since Sep 2026.

## References (read the one the task touches)
| Reference | Read when the task needs |
|---|---|
| `references/mermaid.md` | Mermaid 12 syntax, mmdc rendering, SVG caveats, Excalidraw |
| `references/graphviz-d2-plantuml.md` | Graphviz DOT, D2, PlantUML: syntax, layouts, rendering |
| `references/tikz.md` | tikz-cd, quiver, string diagrams in TikZ, PDF/DVI → SVG/PNG conversion |

## 1. Choose the tool
| Need | Tool | Strengths / limits |
|---|---|---|
| Flowchart, sequence, class, state, ER, gantt, mindmap, timeline inside Markdown on GitHub/GitLab | Mermaid | renders natively on the forge; little layout control (no pinning), clutter beyond ~30–50 nodes, `maxTextSize` 50 000 chars and `maxEdges` 500 by default, renderer version skew |
| Large or dense graphs, dependency/call graphs, generated from code | Graphviz DOT (`dot`; `neato`/`fdp`/`sfdp` force-directed, `circo`, `twopi`) | best hierarchical layout, ranks and clusters, scriptable; verbose styling |
| Architecture diagrams, containers, icons, good defaults | D2 | layouts dagre (default), ELK, TALA (open source and bundled since 0.9); SVG/PNG/PDF/PPTX/GIF; LaTeX and Markdown labels |
| UML-heavy documentation, C4, Java shops | PlantUML | widest UML coverage; Smetana layout needs no Graphviz; GitLab.com renders it |
| Commutative diagrams, diagrams in papers | tikz-cd; draw in quiver (q.uiver.app) and export | typographically matches the paper; needs TeX |
| String diagrams (monoidal categories, ZX, circuits) | TikZ by hand, or TikZiT (GUI; `.tikz` + `.tikzstyles`) | exact positions; semantics in `category-theory` |
| Whiteboard or hand-drawn look | Excalidraw (`.excalidraw` JSON); from code: D2 `--sketch`, Mermaid `look: handDrawn` | Excalidraw diffs only as JSON |
| One HTTP API for many languages | Kroki (Mermaid, PlantUML, D2, Graphviz, TikZ, Excalidraw, BPMN, Vega, WaveDrom…) | public kroki.io receives the source: self-host (Docker) for private material |

## 8. Embedding
| Target | How |
|---|---|
| GitHub Markdown | ```` ```mermaid ```` fences (also geojson, topojson, stl); other tools: commit source and SVG side by side |
| GitLab | ```` ```mermaid ````; ```` ```plantuml ```` on GitLab.com (self-managed: admin enables); Kroki fences if the instance enables Kroki |
| Astro or other unified sites | build time: `rehype-mermaid` (strategies `inline-svg` default, `img-svg`, `img-png`, `pre-mermaid`; `dark: true` for a color-scheme `<picture>`; needs Playwright + Chromium); exclude `mermaid` from Shiki. Astro config wiring: `markdown-publishing` |
| MkDocs Material | `pymdownx.superfences` custom fence: `name: mermaid`, `class: mermaid`, `format: !!python/name:pymdownx.superfences.fence_code_format` |
| Docusaurus | `@docusaurus/theme-mermaid` with `markdown: {mermaid: true}` |
| LaTeX, Word, slides | pre-rendered PDF/SVG (vector) or PNG at ≥ 2× display size |

Prefer build-time rendering (no client JS, no layout drift when a renderer updates). Keep `name.mmd` next to
`name.svg` and regenerate from a Makefile or CI step.

## 9. Readable diagrams
- One question per diagram; beyond ~15–20 nodes split it or cluster (heuristic).
- One primary direction: LR for pipelines and time, TB for hierarchies. Reorder declarations to remove crossings.
- One shape per kind of thing; add a legend when more than three kinds or more than one line style appear.
- Arrows mean one thing per diagram (data flow, dependency or control); variants (dashed = async/optional) go in the legend.
- Nodes are short nouns, edges verbs; sentence case; no undefined abbreviations.
- Font: match the host document (tikz-cd inherits the math font; set `fontname`, `--font-regular` or
  Mermaid `themeVariables.fontFamily`) and install it where rendering happens.
- Color encodes at most one variable. Contrast: text ≥ 4.5:1 (large text 3:1), lines and shapes ≥ 3:1
  against the background (WCAG SC 1.4.11); never color alone (SC 1.4.1). Check grayscale, a color-vision
  simulation and dark mode (dark text on a transparent background disappears).
- Alt text states what the diagram shows and its point. Mermaid `accTitle`/`accDescr` become SVG
  `<title>`/`<desc>`; inline SVG gets `role="img"` and `aria-labelledby`; complex diagrams also get a text equivalent.

## Pitfalls (all tools)
| Symptom | Cause | Fix |
|---|---|---|
| Text overflows boxes in SVG | viewer substitutes the font | install the font; text as paths |
Tool-specific pitfalls are in each reference.

## Verify
- Renders cleanly in the target renderer and version: mmdc exit 0, no `dot` warnings, `d2 validate`, LaTeX log
  without errors or overfull boxes.
- Viewed at the final size: labels legible (≥ surrounding body text; ≥ 12 px on screen), nothing clipped.
- Arrow semantics consistent, legend present when needed, removable crossings removed, names match the prose.
- Accessibility: contrast checked, meaning not color-only, alt text or `accTitle`/`accDescr`, dark mode checked.
- Source committed beside the output with the regeneration command.

## Deliverables / Report
Sources (`.mmd`, `.dot`, `.d2`, `.puml`, `.tex`, `.excalidraw`), outputs (SVG for web, PDF for print, PNG at
2× for slides and chat), render commands with tool versions, alt text per diagram, renderer caveats.
