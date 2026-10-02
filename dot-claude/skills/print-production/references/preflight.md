# print-production — preflight (reference)
Read when preflighting a print PDF in detail. Parent: `print-production` SKILL.md.

## 7. Preflight
GUI:
- Illustrator: Window › Document Info (fonts, linked/embedded images, spot colors), Links panel (link info shows image resolution; confirm effective ppi with `pdfimages -list` on the exported PDF), Separations Preview, Overprint Preview, Flattener Preview, File › Package.
- Illustrator MCP server, when mounted: read document info, image resolution and color space, overprint and separation info, run its preflight against the target PDF/X, then export the PDF. Illustrator's scripting API cannot read the document bleed setting, so always verify the boxes in the exported PDF.
- Acrobat Pro: Print Production › Preflight with the matching PDF/X profile (the real standards validator); Output Preview for separations, Total Area Coverage highlight at the profile's TAC, and overprint simulation; Object Inspector for per-object color and ppi.

Command line (poppler, Ghostscript, qpdf; all verified):
```sh
pdfinfo -box file.pdf                    # pages, Media/Crop/Bleed/Trim/Art boxes in pt (1 pt = 0.3528 mm)
pdfinfo -custom file.pdf                 # Info keys GTS_PDFXVersion / GTS_PDFXConformance (X-1a)
pdfinfo -meta file.pdf | grep -ai pdfx   # XMP pdfxid:GTS_PDFXVersion (X-4); -a because some producers write NUL bytes
pdffonts file.pdf                        # emb must be yes on every row
pdfimages -list file.pdf                 # color space, bpc, x-ppi/y-ppi = effective resolution
qpdf --check file.pdf                    # structure; exit 0 ok, 2 errors, 3 warnings
qpdf --json --json-key=qpdf file.pdf | grep -o '"/OutputConditionIdentifier": "[^"]*"'   # output intent
gs -q -dSAFER -o - -sDEVICE=ink_cov file.pdf     # average ink % per plate per page (inkcov = share of pixels touched)
gs -q -dSAFER -o sep-%d.tif -sDEVICE=tiffsep -r150 file.pdf       # one TIFF per plate, spots included: sep-1(Foil).tif
gs -q -dSAFER -o soft-%d.png -sDEVICE=png16m -r150 -dOverprint=/simulate file.pdf   # overprint-accurate RGB view
```
Maximum TAC per pixel (the number printers reject files for):
```sh
gs -q -dSAFER -o tac-%03d.tif -sDEVICE=tiff32nc -r100 file.pdf
__CLAUDE_DIR__/venvs/sci/bin/python - <<'EOF'
import glob, numpy as np
from PIL import Image
for f in sorted(glob.glob("tac-*.tif")):
    t = np.asarray(Image.open(f), dtype=np.float32).sum(axis=2) / 2.55   # C+M+Y+K in %
    print(f, f"max {t.max():.0f}%", f"area over 300%: {(t > 300).mean():.3%}")
EOF
```
DeviceCMYK passes through unchanged. RGB/ICC objects are converted with Ghostscript's default profiles unless you add `-sOutputICCProfile=printer.icc` (and `-dUsePDFX3Profile` to honor the file's output intent), so treat those numbers as approximate. Render a PNG of each page (`-sDEVICE=png16m -r100`) and Read it.
