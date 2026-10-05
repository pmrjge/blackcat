---
name: procedural-3d-workflows
description: Use for procedural 3D — Geometry Nodes systems, node-group interfaces, scattering, parametric assets, Unreal PCG, testing generators.
---
# Procedural 3D workflows

Hub: `blender-3d` (bpy, headless runs, export). Houdini (SOPs, VEX, HDAs, PDG): `houdini-fx`. Engine runtime and shaders: `game-graphics`. Generators of meshes for print: `3d-printing`.

## Versions (checked 2026-10-05)
- Blender 5.2 LTS (2026-07-14). Geometry Nodes milestones: For Each Element zone and node-group gizmos (4.3); Bundles, Closures and volume grids (5.0); Lists, Set/Get Geometry Bundle, a Mesh Bevel node, Geometry Nodes on empties and experimental hair and cloth physics (5.2). Simulation and Repeat zones, Bake node, Menu Switch and node tools predate 4.3.
- 5.2 Python API break: modifier inputs are RNA properties now (below); scripts written for `mod["Socket_2"]` fail.
- Unreal Engine PCG (Procedural Content Generation framework) is production-ready since UE 5.7 (Nov 2025).

## 1. Design a generator like an API
- Inputs: the fewest parameters that cover the design space, each with a unit, a default that already gives a good result, and min/max limits (`default_value`, `min_value`, `max_value` on the interface socket). Group them with panels; hide internals.
- Menu Switch inputs (named options) instead of magic integers; booleans for features that toggle.
- Every random choice takes an exposed **seed**; randomness keyed by a stable ID attribute (not by index) so adding one element does not reshuffle the rest.
- Outputs: named attributes for downstream use (masks, IDs, UV maps) with documented domains (point, edge, face, corner, instance).
- One generator = one node group with a description; sub-groups for reusable parts; node groups shared through an asset library (mark as asset, catalog, version suffix in the name).

## 2. Building blocks (Geometry Nodes)
- Fields evaluate lazily on the geometry they reach: keep a field's context in mind (a field built on points evaluated on faces interpolates).
- Instances first, Realize Instances last (or never): instancing 100 K trees is cheap, realizing them is not. Scatter with Distribute Points on Faces (Poisson disk for minimum spacing), align with Align Rotation to Vector, then Instance on Points.
- Zones: Repeat (iterations), Simulation (state across frames, bake to disk), For Each Element (per-element sub-graphs). Closures and Bundles (5.0+) pass functions and grouped data between groups; Lists (5.2) hold per-element arrays.
- Curves for paths, profiles and hair; Curve to Mesh with a profile for pipes and trims; Resample and Fillet for clean shapes.
- Volumes (5.0 grids) for SDF-style modeling: mesh → volume, boolean on grids, volume → mesh at the needed voxel size.
- Gizmos (4.3+) on node-group inputs give direct manipulation in the viewport; prefer them to sliders for positions, directions and radii.
- Debug with the Viewer node, the Spreadsheet and node timings in the editor overlay.

## 3. Scripting node groups (5.2)
```python
import bpy
ng = bpy.data.node_groups.new("Fence", "GeometryNodeTree")
ng.is_modifier = True
count = ng.interface.new_socket("Posts", in_out="INPUT", socket_type="NodeSocketInt")
count.default_value, count.min_value, count.max_value = 10, 2, 200
ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
# … add nodes with ng.nodes.new("GeometryNodeMeshLine") and link them with ng.links.new(a, b)
mod = obj.modifiers.new("Fence", "NODES"); mod.node_group = ng
inputs = mod.properties.inputs                         # 5.2+: RNA, keyed by socket identifier
getattr(inputs, count.identifier).value = 24
# attribute input: getattr(inputs, ident).type = "ATTRIBUTE"; .attribute_name = "density"
# output attribute name: getattr(mod.properties.outputs, ident).attribute_name = "mask"
```
- Before 5.2: `mod[count.identifier] = 24`, `mod[ident + "_use_attribute"] = True`, `mod[ident + "_attribute_name"] = "density"`. Support both only if the user's Blender is older; check `bpy.app.version`.
- Socket identifiers (`Socket_2`) are stable; names are not unique. Look them up from `ng.interface.items_tree`.
- Generated node layouts: set `node.location` on a grid so a human can read the graph; frame related nodes.
- Bake evaluated results for hand-off: Bake node or `bpy.ops.object.modifier_apply` on a copy, or export with modifiers applied (`export_apply=True` for glTF).

## 4. Unreal PCG
- A PCG Graph on a PCG Component (in a level or on a Blueprint actor) samples surfaces, splines or volumes into points with attributes, filters and transforms them, then spawns static meshes or actors. Keep graphs data-driven: point attributes from data assets or tables, not hard-coded meshes.
- Determinism: seeds on the component and per node; regenerate on parameter change only; partitioned/hierarchical generation for large worlds (exact options per version unverified: read the 5.7 docs).
- Runtime generation (generate at load or around the player) costs frame time: budget it and measure with Unreal Insights.
- Blender ↔ Unreal: author meshes and instance sets procedurally in Blender, export them, and let PCG distribute them in the engine; keep units (cm in Unreal) and pivots consistent.

## 5. Testing generators
- Parameter sweep script (headless `blender -b`): grid or random samples over the inputs (fixed seeds), record vertex and face counts, bounds, manifoldness, instance counts and evaluation time per sample; fail on NaN bounds, empty geometry, non-manifold output where it must be closed, or time over budget.
- Golden renders: a few fixed parameter sets rendered (Workbench or EEVEE, fixed camera) and compared with stored images by a perceptual diff; update goldens only on intended changes.
- Version node groups (`Fence_v003`) and keep the sweep script with them; a changed default is a breaking change for users of the asset.

## Verify
Every exposed input has a unit, default and limits · seeds exposed and ID-keyed · sweep passes (no empty, NaN or over-budget sample) · golden renders Read and matched · 5.2 RNA input API used (or version-guarded) · Blender and engine versions reported.

Sources (checked 2026-10-05): https://developer.blender.org/docs/release_notes/5.2/geometry_nodes/ · https://developer.blender.org/docs/release_notes/5.2/python_api/ · https://developer.blender.org/docs/release_notes/5.0/ · https://developer.blender.org/docs/release_notes/4.3/ · dev.epicgames.com (Unreal Engine 5.7 release notes, PCG framework)
