# presentation-design — export handoff (reference)
Read when handing a deck to other tools or people, or exporting it (PDF, PPTX, Keynote, video). Parent: `presentation-design` SKILL.md.

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
