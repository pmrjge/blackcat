# Color management: displays profiles

Read when calibrating displays, soft-proofing, or embedding and checking profiles (moved from `color-management` SKILL.md).

## 10. Displays, calibration, soft-proofing
- Calibrate every display with a colorimeter (vendor software, or ArgyllCMS/DisplayCAL). Screen work:
  D65 white, sRGB/2.2 tone response. Print matching: match the D50 viewing booth and paper, not a number;
  ISO 12646 (proofing displays) specifies D50 and 160 cd/m²; dim rooms often need less.
- Apple displays with reference modes (Pro Display XDR, Studio Display/Studio Display XDR, MacBook Pro
  XDR): System Settings > Displays > Preset, e.g. "Design and Print (P3-D50)", "Photography (P3-D65)",
  "Internet and Web (sRGB)".
- Pen displays: gamut ranges from about sRGB to wide-gamut depending on model (check the spec sheet);
  Wacom does not supply ICC profiles and points to profiling with Wacom Color Manager. Set the display's
  OSD color mode first (if it has one), then profile it with a colorimeter; macOS assigns one profile per
  display, so profile each screen and judge color on the more capable one. A narrow-gamut screen cannot
  show out-of-gamut colors: trust numbers and proofs there.
- Soft-proof (Illustrator and Photoshop): View > Proof Setup > Customize → Device to Simulate (printer
  profile), Preserve CMYK Numbers (on for CMYK files), Rendering Intent, Black Point Compensation, Simulate
  Paper Color, Simulate Black Ink; toggle with View > Proof Colors. Illustrator: View > Overprint Preview
  and Window > Separations Preview for spots/overprints. PDFs: Acrobat Pro Output Preview.
- A soft proof is not a contract proof: color-critical print jobs get a certified proof (ISO 12647-7 with a
  control strip) or a press check.

## 11. Embedding and checking profiles
- Web: convert to sRGB and keep the profile (or the PNG sRGB chunk); browsers treat untagged images as sRGB.
  P3 images: embed Display P3 and keep an sRGB fallback. Metadata-stripping optimizers can drop the
  profile: check after optimizing.
- Print: PDF/X with the output intent set to the agreed profile (`export_pdf` accepts `output_intent_profile`;
  details in `print-production`). Video: sRGB stills become BT.709.
- Check: `identify -verbose f | grep -i icc` (ImageMagick), `sips -g profile f`,
  `exiftool -ICC_Profile:ProfileDescription f`; PDF output intent:
```python
from pypdf import PdfReader
oi = PdfReader("out.pdf").trailer["/Root"].get("/OutputIntents")
print([o.get_object().get("/OutputConditionIdentifier") for o in oi] if oi else "no output intent")
```
