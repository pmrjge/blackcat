---
name: presentation-design
description: Load before designing or rebuilding a slide deck (pitch, talk, reading deck) — narrative, one message per slide, grids, type sizes, charts, notes; .pptx file mechanics in pptx.
---
# Presentation design

## Scope
Planning, designing and shipping decks: investor and sales pitches, talks, reports, reading decks.
Elsewhere: chart choice and palettes → `data-visualization`; brand systems → `brand-identity`; contrast and
color → `color-management`; type → `typography`; reading or writing .pptx files programmatically → the
`pptx` skill (python-pptx is also in the science venv); imagery → `image-prompting`.

## 1. Decide the deck type first
| | Presented (projected, live, video call) | Reading (sent, read alone) |
|---|---|---|
| Job | Support a speaker | Replace the speaker |
| Text per slide | Headline plus a few words | Headline plus structured text (roughly ≤ 120 words) |
| Type | Large (§4) | Smaller (§4) |
| Narrative lives in | Speaker notes and voice | The slides |
| Charts | One point each, built up | Annotated, with sources |
Never send the presented deck as is: make a reading version, an appendix, or a notes-page PDF.

## 2. Narrative
1. Write the one-sentence message and the decision you want from this audience.
2. Write every headline as a full-sentence assertion before designing ("Churn fell to 2 % after the new
   onboarding", not "Churn"). Reading the headlines alone must tell the story (headline test).
3. One message per slide: split slides rather than shrink type.
4. Structures:
   - Investor deck: title with one-line positioning → problem → solution/product → why now → market
     (bottom-up TAM/SAM/SOM, assumptions shown) → traction (the strongest real metric over time, with units
     and source; cohorts or retention if available; no vanity metrics) → business model → competition and
     alternatives → go-to-market → team → financials and use of funds → the ask (amount, instrument,
     milestones it buys, runway). Sequoia's outline: company purpose, problem, solution, why now, market
     potential, competition/alternatives, business model, team, financials, vision. YC's seed deck: title,
     problem, solution, traction, unique insight, business model, market, team, ask — legible, simple,
     obvious. Kawasaki's 10/20/30: ten slides, twenty minutes, no font under 30 pt (on a 7.5-inch-high
     slide that is ≥ 60 px at 1080p).
   - Talk: situation → complication → resolution (Minto's SCQA), or Duarte's alternation between "what
     is" and "what could be" ending in a call to action; signpost sections; close on the takeaway slide,
     not "Questions?".
   - Report: answer first (pyramid): executive summary slide, supporting sections, appendix with method
     and data.
5. Assertion-evidence slides: a sentence headline of at most two lines plus visual evidence (chart, image,
   diagram) instead of bullets; studies by Alley and colleagues found better comprehension and recall than
   with topic-and-bullet slides.

## 3. Grid and hierarchy
- 16:9 canvas; outer margins about 5–6 % of the width; a 12-column grid with gutters; titles and body in
  fixed positions on every slide so the eye never hunts.
- Order of attention: headline → evidence → annotation → source. One focal point per slide, at most three
  text levels, generous space, everything on the grid.
- Builds only to reveal a sequence; no decorative transitions.

## 4. Type sizes and the unit trap
"24 pt" differs between tools because their canvases differ:
| Tool | 16:9 canvas | 1 pt in a 1920×1080 export |
|---|---|---|
| PowerPoint | 13.333 × 7.5 in (960 × 540 pt) | 2 px |
| Google Slides | 10 × 5.625 in (720 × 405 pt) | 2.67 px |
| Keynote (Wide) | 1920 × 1080 pt | 1 px |
| Canva | 1920 × 1080 px, sizes in px | 1 px |
| python-pptx default | 10 × 7.5 in, i.e. 4:3 | set `prs.slide_width = Emu(12192000)`, `prs.slide_height = Emu(6858000)` (`from pptx.util import Emu`) |
Specify sizes in px at 1920×1080 and convert: PowerPoint pt = px ÷ 2; Google Slides pt = px × 0.375;
Keynote and Canva = px.

| Role (px at 1920×1080) | Presented | Reading |
|---|---|---|
| Headline | 64–88 | 44–60 |
| Body | 44–56, never below 36 | 28–36 |
| Chart labels | ≥ 32 | ≥ 22 |
| Sources, footnotes | ≥ 24 | ≥ 18 |
Microsoft's accessibility guidance asks for ≥ 18 pt in PowerPoint (36 px). Check the smallest text on the
smallest screen expected (a laptop in a video call, a phone for sent decks).

## 5. Data on slides
- One chart, one message; the headline states the takeaway; the key series in the accent color, the rest
  gray; direct labels instead of legends; faint or no gridlines; bars from zero; rounded numbers; units and
  source on the slide. A single KPI earns a big-number slide.
- Tables: tabular figures, numbers right-aligned, at most 6–7 rows when presented; detail to the appendix.
- Native charts (editable in PowerPoint/Keynote) for decks others will edit; vector images (SVG/PDF) for
  fidelity; always keep the data file (CSV/XLSX). Chart types and palettes: `data-visualization`.

## 6. Images and icons
- Full-bleed or deliberate crops; full-bleed images ≥ 1920 px wide (3840 px for 4K output); check the app's
  image-compression setting before exporting.
- Text on images: a scrim or overlay, contrast measured at the worst spot.
- One icon family (stroke, fill, corners); vectors where the tool supports them, otherwise PNG at 2×.
- Licenses for every photo, icon and font; customer and partner logos only with permission; generated
  imagery per `image-prompting`.

## 7. Brand application
- Build a real template: layouts for title, section, one column, two columns, chart, full-bleed image,
  quote, big number, team, closing, all with placeholders rather than loose text boxes.
- PowerPoint theme: map the palette to the 12 theme slots (dk1, lt1, dk2, lt2, accent1–6, hlink,
  folHlink) and set heading/body theme fonts, so charts and new shapes inherit brand colors and type.
- Logo placed once in the master at a fixed position and above its minimum size (brand guidelines).

## 8. Accessibility
- Contrast 4.5:1 for text and 3:1 for large text and chart marks (WCAG 2.2; math in `color-management`);
  never color alone in charts: labels, patterns or annotations too.
- A unique title on every slide (it may sit off the visible area); reading order checked (PowerPoint:
  Review > Check Accessibility and the Reading Order pane); alt text on informative images, decorative ones
  marked decorative; captions on video; nothing flashing.
- Sizes per §4, robust faces, little text; share slides in advance; describe visuals aloud (W3C WAI).
- Accessible PDF: keep PowerPoint's document-structure tags on when saving to PDF; Keynote's PDF export has
  accessibility tags for large tables among its advanced options.

## 9. Speaker notes
- Per slide: the point in one breath, the transition, the numbers to say, sources, timing cues; about
  60–120 words; prompts, not a script to read.
- Rehearse with a timer; mark optional slides to skip when time runs short.
- Notes can travel: PowerPoint notes pages to PDF; Keynote's PDF export can include presenter notes. Check
  that notes contain nothing the recipient should not read.

## 10. Handing a deck to other tools or people
- Fonts: Google Slides cannot upload custom fonts (its Google Fonts library and add-ons only). PowerPoint
  for Windows embeds fonts whose embedding permissions allow it (File > Options > Save > "Embed fonts in
  the file", with "Embed all characters" when others will edit). Keynote files rely on installed fonts. For
  decks others will edit, pick fonts available in their tool or name licensed fallbacks with similar
  metrics (`typography` covers licensing and `fsType`).
- Rebuild in the target tool's own masters; never hand flat slide images to someone who must edit.
- Handoff guide (PDF or page): canvas and units; grid in px and %; per-role type table with sizes converted
  for each tool (§4); color tokens (HEX/RGB) and theme-slot mapping; spacing tokens; layout list with
  screenshots; a reference PNG per slide; assets folder (named, sized, 2× rasters, SVG icons); chart data;
  animation notes; fonts with sources and licenses; a short do/don't list.
- Conversions lose things (Keynote ↔ PowerPoint fonts and some effects; PPTX → Google Slides substitutes
  missing fonts and flattens some effects): inspect every slide afterwards.

## 11. Export
- PDF to send: fonts embedded, links working, builds flattened (Keynote can print each build stage; usually
  off), notes and hidden slides excluded unless intended, sensible image compression (email: well under
  20 MB), document properties and comments cleaned (PowerPoint for Windows: File > Info > Check for Issues
  > Inspect Document).
- Exact-size PNG sequence from any tool: export or convert to PDF, then rasterize:
```bash
soffice --headless --convert-to pdf deck.pptx                    # LibreOffice; substitutes fonts it lacks
pdftoppm -png -scale-to-x 3840 -scale-to-y 2160 deck.pdf slide  # or 1920/1080; slide-1.png… (zero-padded from 10 pages)
pdffonts deck.pdf                                                 # every font "emb yes"?
```
- Video: PowerPoint File > Export > Create a Video (Ultra HD 4K 3840×2160, Full HD 1080p, HD 720p, 480p;
  MP4 or WMV); Keynote File > Export To > Movie (resolution menu, or custom); or from the PNGs (match the
  file-name padding):
```bash
ffmpeg -framerate 1/5 -i slide-%02d.png \
  -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709" \
  -c:v libx264 -r 30 deck.mp4   # 5 s per slide; BT.709 matrix, limited range and tags
```
  (Tag with `setparams`, not output options: FFmpeg ≥ 7.1 drops output-side `-color_primaries`/`-color_trc`
  when re-encoding. Check with `ffprobe -show_entries stream=color_space,color_primaries,color_transfer`;
  `media-ffmpeg` has more.)
- Google Slides: File > Download (PDF, PPTX and others); use the PDF route above for image sequences.

## 12. Pre-send checklist
- Story: the headline test passes; one message per slide; the ask or call to action is explicit; numbers,
  dates and names agree across slides and appendix; spelling checked in every language used.
- Design: grid alignment; titles in fixed positions; sizes above the §4 floors; contrast passes; images
  sharp at output size; no placeholder text; no stray animations.
- Files: fonts embedded (`pdffonts`), links work, size fits the channel, comments/hidden slides/notes/
  metadata checked, name carries date and version (`Company_Deck_2026-09_v3.pdf`).
- Opened on a second device (and a phone for sent decks); presented decks rehearsed on the real display or a
  1920×1080 window.

## Verify
- Render every slide to PNG (§11) and Read them in order: hierarchy, alignment, overflow, substituted
  fonts, contrast, legibility of the smallest text.
- `pdffonts` shows every font embedded; `pdfinfo` page size matches the canvas (a 16:9 PowerPoint PDF is
  960 × 540 pt).
- Rebuilt or edited decks: compare old and new renders side by side
  (`montage old/slide-03.png new/slide-03.png -tile 2x -geometry +8+8 cmp-03.png`).

## Deliverables / Report
- Source deck (.pptx, .key or Slides link) with masters; PDF; PNG sequence or video when asked; notes PDF
  for presented decks.
- Handoff guide when someone else edits or rebuilds; chart data; asset folder with licenses.
- A short note: deck type, the one-sentence message, slide count, fonts and their availability in the
  target tool, known limitations.
