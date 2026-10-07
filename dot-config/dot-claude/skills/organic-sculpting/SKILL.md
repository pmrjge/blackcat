---
name: organic-sculpting
description: Use for organic sculpts — characters, creatures, anatomy, faces, cloth folds; ZBrush and Blender detail passes and displacement.
---
# Organic sculpting

Hub: `sculpting-texturing` (retopology, UVs, baking, PBR). Painting the result on UDIMs: `udim-texture-painting`. Rigging the result: `character-rigging`. Printing it: `3d-printing`.

## Versions (checked 2026-10-05)
- ZBrush 2026.2.1 (2026-06-17); 2026.0 added Python scripting, 2026.1 added Retopology brushes. Option names inside ZBrush menus vary by release: read them on screen, never from memory.
- Blender 5.2 LTS (2026-07-14). 5.0: Multires "Conform Base"; brush size is now a **diameter** (double old radius values in scripts and presets; property names on 5.x: check the API docs); radial symmetry is stored per mesh. 5.2: Scene Project brush, Add Primitive tools inside Sculpt Mode, the voxel remesher keeps (interpolates) attributes such as color and face sets.
- 5.2 Python: automasking settings moved to `mesh_automasking_settings` on `Paint` and `Brush` (`brush.mesh_automasking_settings.use_automasking_topology`; numeric ones lose the prefix: `automasking_cavity_factor` → `mesh_automasking_settings.cavity_factor`).

## 1. Brief and reference
- Purpose decides everything: hero film asset (UDIM displacement, 8–20 M polys in sculpt), game character (bakes onto a 20–100 K triangle low poly; state the real budget), print (closed volume, wall thickness), stylized or realistic.
- Reference board before the first stroke: front and side orthographic references aligned to the grid, anatomy references (skeleton and muscle charts for the pose), material and surface references (skin pores, scales, fabric weave). Likeness of a real person, or a third party's character, only with the user's stated rights.
- Fix proportions in head units (an adult is ~7.5 heads tall; heroic 8–8.5; children fewer) or the target character sheet; measure, don't eyeball.

## 2. Blockout (silhouette first)
- ZBrush: ZSpheres or primitives → DynaMesh at low resolution (resolution 64–128 for the whole figure); Blender: primitives or a quick metaball/skin-modifier armature → Voxel Remesh (Ctrl+R) with a coarse voxel size.
- Check silhouette and gesture from at least front, side, three-quarter and top, in a flat matcap and in silhouette (black material); a pose that reads in silhouette reads everywhere.
- Primary forms only: rib cage, pelvis and skull as boxes and eggs, limbs as tapered cylinders with the right overlaps (where one form tucks behind another).

## 3. Anatomy that sells a sculpt
- Bony landmarks show through at every body type: clavicles, acromion, sternum notch, iliac crest, kneecap, ankle malleoli, elbow, seventh cervical vertebra, zygomatic arch, brow ridge, jaw angle. Place them first; soft tissue drapes between them.
- Muscle groups as masses with directions, not separate bumps: deltoid wraps the shoulder, pectoral twists into the arm, forearm flexors and extensors spiral, calf masses sit high on the inside. Fat and skin soften transitions on most bodies.
- Head: planes of the head first (Asaro-style plane head as a mental model), eye line at half the head height, eyes one eye-width apart, lips and nose on the facial midline; eyes are spheres set back in sockets, lids wrap them with thickness.
- Hands and feet: block as boxes with the knuckle arc and the foot's arch before fingers or toes.
- Creatures: borrow real anatomy (a quadruped's skeleton, a reptile's scale pattern), keep functional logic (where muscles anchor, how joints bend) so the design reads as alive.

## 4. Refinement passes
- Work up subdivision levels only when the current level holds the form: secondary forms (muscle separation, wrinkles, fat folds) at mid levels, tertiary detail (pores, fine wrinkles, scales) at the top levels or in displacement.
- ZBrush: DynaMesh while forms change → ZRemesher (with guides) → Project All onto subdivision levels → Layers for reversible passes (each detail type on its own layer, slider-mixable) → polypaint for color IDs. Morph Targets as an undo brush against a stored state.
- Blender: Voxel Remesh or Dyntopo while exploring → retopologized base + Multires; face sets to isolate regions; masks and auto-masking (topology, face sets, cavity) to protect areas; Layer brush and shape keys for reversible passes.
- Brushes: Clay Strips/Clay Buildup (volume), Move/Grab and Snake Hook (forms, horns, tendrils), Dam Standard/Crease (creases, lids), hPolish/Flatten/Scrape (planes), Inflate and Pinch, Standard with alphas for pores and scales; alphas from scanned skin libraries need their licence.
- Symmetry on until the last pass; break it deliberately (asymmetric expression, weight shift, wear) at the end.
- Cloth: start from gravity and tension points (shoulders, hips, bent knees); fold types (pipe, zig-zag, spiral, half-lock, diaper, drop, inert) at those points; Blender's Cloth brush and cloth filter, ZBrush's Cloth brushes or Marvelous Designer for simulated drape, then sculpt the read.

## 5. Hand-off: low poly, maps and displacement
- Retopologize a deforming character with loops around eyes, mouth and joints (rules in the hub); keep the sculpt's base level close to the low poly so details project cleanly.
- Bake normals, AO, cavity, curvature and thickness from the top level onto the low poly (hub's baking section), or export displacement:
  - ZBrush: Multi Map Exporter, 32-bit float EXR, mid-value 0, per UDIM tile (`udim-texture-painting`).
  - Blender: Multires bake (displacement or normals) or a Cycles bake from the high mesh; vector displacement for overhangs (horns, ears).
- Displacement maps are scalar or vector float data, Non-Color, mid-level and scale written next to the file (`<asset>_disp.<UDIM>.exr`, `midlevel=0`, `scale=1`): a wrong mid-level inflates or shrinks the whole mesh.
- Test the displacement on the low poly in the target renderer (Cycles with adaptive subdivision, or the film renderer) against a turntable of the sculpt.

## 6. Scripting
- Blender sculpt automation runs through `bpy` in Sculpt Mode with `temp_override`; remesh and multires operators need a mesh in context (`bpy.ops.object.voxel_remesh()`, `bpy.ops.object.multires_subdivide(modifier="Multires")`).
- ZBrush 2026 Python API: check the installed version's docs before scripting; ZScript remains for older plugins (details unverified here).

## Verify
Silhouette and proportions checked from four views against the references · landmarks placed · details layered and reversible · turntable renders (matcap and neutral light) Read · baked or displaced low poly compared with the sculpt · file versions saved (`v###`), app versions reported.

Sources (checked 2026-10-05): https://developer.blender.org/docs/release_notes/5.0/sculpt/ · https://developer.blender.org/docs/release_notes/5.2/sculpt/ · https://developer.blender.org/docs/release_notes/5.2/python_api/ · https://www.maxon.net/en/zbrush (release notes)
