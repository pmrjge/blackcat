---
name: sculpting-texturing
description: Load before digital sculpting, retopology, UV unwrapping, baking or 3D texture painting — ZBrush, Blender sculpt, texel density, normal maps, Substance 3D Painter, PBR.
---
# Digital sculpting and 3D painting

## Scope
- From blockout to textured, export-ready asset. Blender mechanics in `blender-3d`; printing sculptures in `3d-printing`; texture file handling in `raster-imaging`; color targets in `color-management`.
- Apps: ZBrush (Maxon; desktop and iPad), Blender sculpt and texture paint, Substance 3D Painter (Adobe), with Instant Meshes, RizomUV or Blender for retopology and UVs. ZBrush and Painter have no MCP server: drive them through computer use (load `computer-use-apps` first) and keep every hand-off file-based (OBJ/FBX in, maps out).

## Sculpting workflow
1. Blockout: primitives, ZSpheres or DynaMesh/voxel remesh at low resolution; get proportions and silhouette right from several angles before any detail.
2. Primary → secondary → tertiary forms. Work at the lowest subdivision that can hold the form; step up only for detail.
3. Resolution strategy:
   - ZBrush: DynaMesh while forms change → ZRemesher for clean topology → subdivision levels (project details back) → layers for reversible detail passes; polypaint for color.
   - Blender: Dyntopo or voxel remesh (Ctrl+R) while exploring → Multires modifier on a retopologized base for detail and baking; face sets and masks to isolate regions.
4. Brushes that carry most work: Clay Buildup/Clay Strips (volume), Move/Grab (proportions), Dam Standard/Crease (sharp creases), hPolish/Flatten/Scrape (planes), Trim Dynamic, Inflate, Pinch; symmetry on until asymmetry is intended; reference images on a second monitor or as image planes.
5. Hard surface in sculpt: ZModeler, Live Booleans, or model hard parts polygonally in Blender and combine.

## Topology and retopology
- Deforming meshes need quads, even density and edge loops following deformation (eyes, mouth, shoulders, elbows, knees); poles away from joints; triangles only where they don't deform.
- Tools: ZRemesher (guides and density painting), Blender Quad Remesher (paid add-on), Instant Meshes (free), manual retopo in Blender with snapping to faces + Shrinkwrap; static props can use decimation (ZBrush Decimation Master) instead.
- Budgets: state a triangle budget per use (game hero vs background, real-time vs offline, print).

## UVs
- Seams in low-visibility places and along hard edges; straighten shells where textures have direction; consistent **texel density** across the asset (e.g. 10.24 px/cm for a 1K-per-meter target) unless an area deserves more.
- Pack with 8–16 px padding at the target resolution (mip bleeding), avoid overlaps except intentional mirrored shells (offset one by 1 UV unit when baking). UDIMs for film-resolution assets.
- Tools: Blender (Unwrap, Smart UV Project for hard surface quick jobs, UV Packmaster add-on), RizomUV, ZBrush UV Master.

## Baking (high → low)
- Maps: tangent-space normal, ambient occlusion, curvature, thickness, world-space normal, position, material ID (from polypaint/vertex colors).
- Cage or ray distance just large enough to enclose the high poly; name matching (`_low`/`_high`) or exploded bakes to avoid cross-projection.
- Normal-map Y convention: **OpenGL (Y+)** — Blender, Unity, glTF, Maya; **DirectX (Y−)** — Unreal, Substance Painter's default, 3ds Max. Mismatch looks like inverted lighting on bevels; fix by flipping the green channel, and set the project convention once.
- Tangent basis: bake and render with the same (MikkTSpace); triangulate before bake if the target engine triangulates differently.

## Substance 3D Painter
- New project: template for the target (glTF PBR Metal Roughness, Unreal, Unity HDRP/URP), normal map format, document resolution, "use UV tile workflow" for UDIMs; bake mesh maps inside Painter or import your own.
- Layer stack: fill layers with masks > paint layers; smart materials and smart masks driven by curvature/AO/position; generators and anchor points for reusable wear; keep base materials physically plausible before adding story (dirt, wear).
- Export presets define channel packing: ORM (R = occlusion, G = roughness, B = metallic) for glTF/Unreal, separate maps for Blender; 8-bit PNG/TGA for color and packed maps, 16-bit for height. Check output color spaces when importing elsewhere.
- Automation: Painter has a Python API (`substance_painter` module) for plugins and batch export — check the version's API docs before scripting.

## PBR rules of thumb (metal/roughness)
- Base color holds no lighting or AO. Non-metals: sRGB values roughly 30–240 (charcoal ~50, fresh snow ~240); metals: bright, tinted base color with metallic = 1 (raw metal ~180–255).
- Metallic is almost binary (0 or 1); partial values only for transitions (dust on metal). Roughness carries most of the realism — vary it.
- Height/displacement for silhouette-changing detail, normal maps for surface detail only.
- Validate under a neutral HDRI and several lighting setups; compare with a real reference photo.

## 3D painting (hand-painted and stylized)
- Blender Texture Paint (projection painting from camera, stencils, clone), vertex paint for low-poly styles, Grease Pencil for drawn 3D strokes; ZBrush polypaint baked to texture; Painter with hand-painted brushes and unlit preview.
- Stylized look: paint lighting cues into albedo intentionally (and say so), limited palettes (`color-management` for OKLCH ramps), clear value hierarchy, texel density consistent so brushwork scale matches.

## Export and QA
- Formats: FBX/OBJ (mesh), glTF/GLB (mesh + PBR), USD for pipelines; textures named `<asset>_<map>.<ext>` with resolution in the name if several.
- QA: renders in a neutral lighting setup and the target renderer/engine; check seams, texel density (checker texture), normal-map direction, mip bleeding at a distance, texture memory; Read the renders.

## Checklist
Proportions checked from multiple views before detail · topology fit for deformation (or budgeted decimation) · consistent texel density · bake cage clean, normal convention matched to target · PBR values plausible · packed maps in the right color spaces · QA renders reviewed.
