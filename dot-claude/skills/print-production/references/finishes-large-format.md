# print-production — finishes large format (reference)
Read when specifying finishes (foil, spot UV, die cuts, white ink) or large-format and vehicle-wrap jobs. Parent: `print-production` SKILL.md.

## 9. Finishes (each is its own separation)

| Finish | Supply as | Constraints (typical; confirm) |
|---|---|---|
| Hot foil | vector mask, spot `Foil` 100% overprint, or a separate 100K page | lines ≥ 0.5–1 pt, type ≥ ~5 pt, no halftones; the block is made at the supplied size |
| Cold/digital foil | mask plate; CMYK can print over cold foil for metallic colors | tint rules per press |
| Spot UV / spot varnish | vector mask, spot `SpotUV` 100% overprint | lines ≥ ~0.5 pt; registration tolerance, so avoid hairline fits to printed edges; ask whether to choke |
| Emboss / deboss | vector mask at 1:1 (`Emboss`, `Deboss`); registered or blind | no fine detail; away from folds and trim; heavier uncoated stock works best; the reverse shows on the back |
| Flood varnish, aqueous, lamination | no file (flood) | lamination shifts color slightly; soft-touch scuffs on dark solids |
| Die/kiss cut, crease, perf | technical layer (§2) | closed paths; minimum inside radius per die maker |

Masks align exactly with the art. Add a composite preview page (art with the finish tinted) for approval.

## 12. Large format and vehicle wraps
- Build at 1:1 when it fits Illustrator's normal canvas (227 × 227 in, 5.77 m); otherwise at a stated scale and let the RIP enlarge. Add 2–3% noise to large smooth gradients against banding. Ask for hems, grommets, pole pockets and seams.

Vehicle wraps:
1. Measure the vehicle (overall length, beltline height, wheelbase, door, handle and fuel-door positions) and shoot each side straight on. Templates (1:10 is the North American norm; 1:20 for large vehicles) are drawings: verify key dimensions against the vehicle, trim level and model year.
2. Design at 1:10 (the RIP scales 1000%). Rasters at 10 × the final ppi: 100–150 ppi at 1:1 = 1000–1500 ppi in the 1:10 file; Document Raster Effects likewise; if you scale artwork up, turn on Scale Strokes & Effects. Put the scale in the file name and on a note layer.
3. Keep logos, phone numbers, URLs, faces and text off door gaps, handles, hinges, fuel doors, deep recesses and channels, rivets, body lines, compound curves and mirrors; make them readable with doors closed.
4. Bleed 3–5 in (75–125 mm) past every panel edge; some shops want 6 in on cars and vans, 2 in on box trucks. The installer decides.
5. Panelize to the printable width of the roll (54–60 in media, minus margins); overlap seams ≥ 0.5 in (12.7 mm), 0.5–1 in typical. Vertical seams shingle rear-to-front (each forward panel laps over the one behind it, so exposed edges face rearward, away from the airflow); horizontal seams bottom-up (upper panel over lower, edges face down). Never seam through text or logos. Number panels and mark orientation.
6. Film: cast (about 2 mil / 50 µm, conformable, dimensionally stable, 5–12 years) for compound curves, rivets and recesses; calendered (thicker, stiffer, shrinks) for flat or simple curves, polymeric for mid-term, monomeric for short-term. Laminate with the film maker's matched cast overlaminate (Avery MPI 1105 Easy Apply RS, for example, is approved only with DOL 1000Z, DOL 1400Z series or DOL 6460). Solid colors can use color-change films instead of print. Windows: perforated window film; keep the windshield and front side windows clear (legal limits vary; check local law).
7. Print: 3M IJ180mC and Avery MPI 1105 both specify maximum total ink 270%, so keep rich black ≤ 270% (C60 M40 Y40 K100 = 240% fits). Solvent and eco-solvent prints outgas before lamination (Avery: 24–48 h flat, 72 h for conforming or fleet work); latex needs no extra curing.
8. Installer notes (not design decisions): clean and decontaminate the surface; apply within the film's temperature range (3M IJ180mC: 16–32 °C on compound curves, 18–22 °C optimal); post-heat stretched areas and recesses to the film maker's value (3M lists 95–110 °C for IJ180); relief cuts in recesses; remove hardware where possible.
Deliver: each side (driver, passenger, rear, front, roof, hood) at scale with the panel map, a client mockup on the template, and the print files.
