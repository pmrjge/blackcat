---
name: 3d-printing
description: Load before designing, repairing, slicing or checking anything to be 3D printed (FDM or resin) — design rules (walls, overhangs, tolerances, holes, inserts, orientation), mesh repair and watertightness, STL vs 3MF vs STEP, parametric CAD (OpenSCAD, build123d), sculpture prep (hollowing, splitting, keys), slicer CLIs and settings, materials, calibration, safety.
---
# 3D printing

## Scope
- FDM/FFF and resin (MSLA/SLA), with notes for SLS/MJF services. Modeling and sculpting in `blender-3d` and `sculpting-texturing`; robot parts in `robotics-engineering`.
- Versions to check (Sep 2026): PrusaSlicer 2.9.x, Bambu Studio 2.x, OrcaSlicer (community fork), Cura/CuraEngine; OpenSCAD and build123d move fast — check release notes.
- Never start a print, send G-code to a printer, or change printer firmware without the user's explicit instruction. Deliver files; the user presses print.

## Design rules (FDM, 0.4 mm nozzle; adjust for others)
| Rule | Typical value |
|---|---|
| Wall thickness | multiples of line width: ≥ 0.8–1.2 mm (2–3 perimeters); structural parts 4+ perimeters |
| Overhangs | ≤ 45° without supports; chamfer instead of fillet on downward edges |
| Bridges | short spans (≤ 10–20 mm) print clean; longer need supports |
| Clearances | press fit ~0.1–0.15 mm, snug 0.2 mm, sliding 0.3–0.5 mm per side — **print a tolerance coupon on the target printer** |
| Holes | print undersized; vertical holes +0.1–0.2 mm, horizontal holes as teardrops or drilled after |
| Heat-set inserts | hole per the insert maker's spec (M3 inserts commonly ~4.0–4.2 mm), wall ≥ 1.5× insert diameter around them |
| Text/embossing | ≥ 0.4–0.6 mm stroke, ≥ 0.4 mm depth/height |
| Min feature | ≈ 2 × line width |
- Orientation decides strength: layer bonds are weakest in Z, so align principal loads along layers; also consider surface finish, support scars and first-layer contact area.
- Elephant's foot: small chamfer (0.3–0.5 mm) on bottom edges or slicer compensation.
- Threads: print coarse threads ≥ M8, otherwise heat-set inserts, captive nuts or tapping.

## Resin specifics
- Minimum walls ~0.8–1.5 mm for durable parts (thin detail down to ~0.3 mm for miniatures, unsupported it breaks); hollow large parts (2–3 mm shell) with **at least two drain holes** (≥ 2–3 mm), low on the part, to avoid suction/cupping and trapped resin.
- Orient 30–45° to reduce cross-section per layer; supports on non-visible faces; account for post-cure shrinkage on fits.
- Safety: uncured resin is a skin sensitizer and irritant — nitrile gloves, eye protection, ventilation, IPA (or dedicated cleaner) for washing, full UV cure before handling; never pour resin or contaminated IPA down drains (cure it first).

## Mesh preparation
- Required: watertight (manifold, closed), consistent outward normals, no self-intersections, no zero-thickness faces, correct scale (STL has no units — convention is millimeters).
- Check and repair:
  ```python
  import trimesh
  m = trimesh.load("part.stl")
  print(m.is_watertight, m.is_winding_consistent, m.is_volume, m.bounds, m.volume)
  trimesh.repair.fix_normals(m); trimesh.repair.fill_holes(m)
  ```
  manifold3d for robust booleans, PyMeshLab for remeshing and cleaning, Blender's 3D-Print Toolbox (checks for non-manifold, thin walls, overhangs, intersections), admesh for STL stats.
- Sculptures: decimate to a sensible triangle count (0.5–2 M is plenty for most printers), voxel-remesh to make them watertight, hollow (resin) or plan infill (FDM), split large models along hidden seams with registration keys/pins (0.2–0.3 mm clearance), add a flat base.
- Formats: **3MF** preferred (units, multiple objects, colors/materials, and the slicer project with settings), STL for simple interchange, **STEP** for CAD parts (current slicers import it and tessellate at print resolution), OBJ for colored meshes.

## Parametric CAD
- OpenSCAD: `openscad -o part.stl -D 'width=40' -D 'holes=4' part.scad`; recent builds offer the Manifold backend (far faster booleans) — check `openscad --help`. Keep dimensions as named parameters; `$fn` high enough for round holes (or `$fa`/`$fs`).
- build123d or CadQuery (Python on OpenCascade): real B-rep with fillets/chamfers, export STEP and STL; ideal for functional parts generated from code and tests (assert bounding boxes, volumes, clearances).
- FreeCAD, Fusion or Onshape when the user works there; always export STEP alongside STL/3MF for later edits.

## Slicing
- PrusaSlicer CLI: `prusa-slicer --export-gcode --load printer_profile.ini --load filament.ini --load print.ini -o out.gcode part.3mf` (also `--export-3mf`, `--info` for dimensions/volume). Bambu Studio and OrcaSlicer ship CLIs too, less documented — prefer exporting a 3MF project the user opens.
- Key settings: layer height (≤ 75 % of nozzle; 0.2 mm default, 0.1–0.12 for detail), perimeters (strength comes mostly from walls, not infill), infill 15–25 % gyroid/cubic for general parts, top/bottom layers ≥ 0.8–1 mm total, seam placement (rear/aligned), supports (tree/organic for organic shapes, snug for mechanical), brim for tall/thin or warping materials, Arachne perimeter generator for variable-width thin walls.
- Check the G-code before handing over: estimated time and material, layer preview (first layer, bridges, overhang areas), max temperatures matching the material.

## Materials (FDM)
| Material | Notes |
|---|---|
| PLA | easy, stiff, low heat resistance (~55–60 °C softening) |
| PETG | tougher, some flexibility, stringing; good for functional parts |
| ABS/ASA | heat resistant, UV-stable (ASA); needs enclosure and ventilation (fumes) |
| TPU | flexible; slow, direct drive |
| PA/PA-CF, PC | engineering parts; must be dried; hardened nozzle for CF |
- Dry hygroscopic filaments (PETG, TPU, nylon, PC) before printing; wet filament = stringing, bubbles, weak parts.

## Calibration order
Mechanical checks → temperature tower → flow/extrusion multiplier → pressure/linear advance → retraction → first layer (Z offset) → input shaping (Klipper) → dimensional accuracy and tolerance coupon. Record results per printer and material.

## Deliverable
Source (CAD/.blend/.scad) + STEP (CAD parts) + 3MF with orientation and settings (+ STL if requested), a short print sheet: printer/nozzle, material, layer height, walls/infill, supports, orientation, estimated time and material, post-processing.

## Checklist
Watertight and correctly scaled · design rules met for the process · tolerance coupon for fits · orientation justified by loads · sliced preview checked · resin parts hollowed with drain holes · no print started without the user.
