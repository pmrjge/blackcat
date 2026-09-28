---
name: adobe-creative-cloud
description: Load before automating or working in Adobe apps beyond Illustrator — Photoshop and InDesign scripting (UXP, ExtendScript, batchPlay), actions, data merge, preflight, Acrobat.
---
# Adobe Creative Cloud

## Scope and routing
- Photoshop, InDesign, Lightroom Classic, Acrobat Pro, Bridge, CC Libraries, Adobe Fonts. Illustrator lives in `svg-vector-craft` (the stack has an Illustrator MCP server); After Effects and Premiere Pro in `motion-graphics` (MCP servers exist for both); Substance 3D in `sculpting-texturing`; print output in `print-production`; color in `color-management`.
- Order of tools: a script (repeatable, exact) → an action or droplet → computer use for GUI-only steps (load `computer-use-apps` first; one agent on the screen). Work on copies of the user's files; close documents without saving unless told otherwise.
- **Generative features (Firefly, Generative Fill/Expand, Text to Image) are an image-generation service**: the stack's rules route all image generation and editing through image-studio, so don't use them — use `edit_image`/`generate_image` and composite the result in Photoshop.
- Photoshop and InDesign have no MCP server in this stack. A community Photoshop/Premiere/InDesign bridge (adb-mcp: a UXP plugin plus a local proxy) exists; adding it is mcp-broker's call after vetting, not a default.

## Running scripts on macOS
- ExtendScript (`.jsx`) via AppleScript:
  `osascript -e 'tell application id "com.adobe.Photoshop" to do javascript (POSIX file "/abs/path/script.jsx")'`
  InDesign: `osascript -e 'tell application id "com.adobe.InDesign" to do script (POSIX file "/abs/path/script.jsx") language javascript'`.
  Pass arguments by writing a JSON file the script reads, or `with arguments {…}`; return values by writing a result file.
- UXP scripts: Photoshop `.psjs` and InDesign `.idjs` run from File → Scripts → Browse (and the Scripts panel); UXP plugins are developed and loaded with the UXP Developer Tool. Check the current Adobe docs for command-line invocation on your version.
- Suppress dialogs so scripts never block: ExtendScript `app.displayDialogs = DialogModes.NO` (Photoshop), `app.scriptPreferences.userInteractionLevel = UserInteractionLevels.NEVER_INTERACT` (InDesign) — restore the previous value in `finally`.

## Photoshop
- UXP (modern JavaScript, `require("photoshop")`): DOM (`app.activeDocument`, `layers`, `resizeImage`, `saveAs.png`), every document-modifying call inside `core.executeAsModal(async () => {…}, {commandName: "…"})`, and `action.batchPlay([descriptors], {})` for features the DOM lacks (record the descriptor with Alchemist or the Actions panel's "Copy as JavaScript"). ExtendScript (ES3, `.jsx`) is frozen but supported and has the most community scripts; use it when an existing script fits.
- Non-destructive practice: smart objects (keep originals, scale freely), adjustment layers with masks, layer comps for variants, 16-bit for heavy grading, artboards for multi-size deliverables; Linked Smart Objects for shared assets.
- Batch: Actions → File → Automate → Batch or a Droplet; Image Processor for format/size conversions; Variables + data sets for data-driven templates. For pure resizing/format conversion, command-line tools are faster and reproducible (`raster-imaging`).
- Export: Export As / Quick Export (sRGB conversion, metadata options) for screen; Save a Copy as TIFF/PSD for print with the right profile; Save for Web (Legacy) only for GIF palettes. Resampling: Bicubic Sharper/Automatic for reduction, Preserve Details 2.0 for enlargement (or a proper upscaler).
- Color: Edit → Color Settings (working spaces), Assign vs Convert to Profile, soft-proofing (View → Proof Setup) — details in `color-management`.

## InDesign
- Structure first: paragraph and character styles (with GREP styles), object styles, table/cell styles, master/parent pages, baseline grid, text variables, cross-references; no local overrides in deliverables (check the style override indicators).
- Automation: ExtendScript remains the most complete API (`app.documents`, `stories`, `findGrep`/`changeGrep` with `app.findGrepPreferences`), UXP scripting is available in recent versions; Data Merge for catalogs and badges (CSV/TSV, `@image` fields).
- Output: Preflight profiles (fonts, missing links, resolution, overset text, color spaces), Package (fonts, links, IDML), PDF presets (PDF/X-4 for modern print, PDF/X-1a when the printer requires it — see `print-production`), interactive PDF/EPUB only when asked. IDML for exchange with older versions.

## Lightroom Classic and Lightroom
- Non-destructive catalog: develop settings live in the catalog (and XMP sidecars when "Automatically write changes into XMP" is on). Presets (XMP) and Export presets encode repeatable looks and deliveries (size, sharpening, color space, watermark, metadata).
- Automation: the Lua SDK for plugins; otherwise presets + batch export. No official CLI — for scripted raw development use darktable-cli or RawTherapee CLI, or Photoshop's Camera Raw via scripts.

## Acrobat Pro and Bridge
- Acrobat: Preflight (fixups, PDF/X conversion), Print Production → Output Preview (separations, total ink), Action Wizard for batch tasks, Acrobat JavaScript for forms. For scripted PDF work outside Acrobat, the `pdf` skill and qpdf/Ghostscript are usually better.
- Bridge: batch rename, metadata templates (IPTC), keywording, collections; it also launches Photoshop batch tools.

## Libraries, fonts, interchange
- CC Libraries share colors, character styles and graphics across apps — export palettes as ASE for other tools.
- Adobe Fonts: activation-based license; fonts can't be packaged or sent as files (InDesign packaging excludes them) and web use needs a web project — flag this in handoffs (`typography`).
- Interchange: PSD → After Effects/Premiere (layers as compositions), AI/PDF → InDesign placed graphics, IDML, PDF/X for print, TIFF/PNG/JPEG exports with embedded profiles.

## Checklist
Work on copies · script over clicks · dialogs suppressed and restored · no Firefly/Generative features · styles instead of overrides · preflight clean · exports verified by opening or rendering them and Reading the result · app versions reported.
