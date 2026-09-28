---
name: blender-3d
description: Load before modeling, scripting, rendering or exporting in Blender — headless bpy, bmesh, geometry nodes, materials, Cycles/EEVEE, glTF/FBX/USD/STL export, the Blender MCP server.
---
# Blender

## Scope and baseline
- Covers Blender as modeler, scripting host, renderer and exporter. Sculpting, retopology, UVs and texturing in `sculpting-texturing`; print preparation in `3d-printing`; Houdini in `houdini-fx`; texture files in `raster-imaging`.
- Versions (endoflife.date, Sep 2026): **5.2 LTS** (Jul 2026) is current, 5.1 and 5.0 before it, 4.5 the previous LTS. Python API details change between majors — `blender --version`, and read https://docs.blender.org/api/current/ (or the versioned API docs) for anything you haven't used on this version.
- macOS binary: `/Applications/Blender.app/Contents/MacOS/Blender` (alias it as `blender`).

## Headless first (reproducible)
```bash
blender -b scene.blend --python build.py -- --out /abs/out.glb   # args after -- reach sys.argv
blender -b --factory-startup --python-expr "import bpy; print(bpy.app.version_string)"
blender -b scene.blend -E CYCLES -o //renders/frame_#### -F PNG -f 1        # one frame
blender -b scene.blend -s 1 -e 120 -a                                      # animation
```
- In scripts: `argv = sys.argv[sys.argv.index("--") + 1:]`; exit non-zero on failure (`sys.exit(1)`) — Blender otherwise returns 0 after a Python error unless you pass `--python-exit-code 1`.
- `bpy` is also a PyPI wheel for pure-Python pipelines; it must match the Python version that Blender release bundles (`blender -b --python-expr "import sys; print(sys.version)"`).

## The bpy model
- `bpy.data` (all datablocks: objects, meshes, materials, images), `bpy.context` (current scene, selection, active object — depends on UI state), `bpy.ops` (operators: need the right context, slow, fragile in background). Prefer the data API; when an operator is unavoidable, use `with bpy.context.temp_override(active_object=obj, selected_objects=[obj]): bpy.ops.…`.
- Create without operators: `mesh = bpy.data.meshes.new("M"); mesh.from_pydata(verts, [], faces); obj = bpy.data.objects.new("O", mesh); bpy.context.scene.collection.objects.link(obj)`.
- Edit topology with `bmesh` (`bm = bmesh.new(); bm.from_mesh(me); … bm.to_mesh(me); bm.free()`); `mathutils` for vectors, matrices, quaternions, BVH trees and KD-trees.
- Speed: `foreach_get`/`foreach_set` with numpy buffers instead of Python loops over vertices; evaluated geometry (modifiers applied) via `obj.evaluated_get(bpy.context.evaluated_depsgraph_get())`.
- Units: set `scene.unit_settings` (metric, scale 1.0 = meters); apply rotation and scale (`bpy.ops.object.transform_apply`) before export or physics.

## Procedural modeling
- Modifier stack order matters (Mirror → Subdivision → Bevel differs from Bevel → Subdivision); keep modifiers live until export.
- Geometry Nodes for scatter, instancing, parametric assets; expose inputs on the node group (modifier inputs) so scripts can drive them: `mod["Socket_2"] = 0.5` (socket identifiers, not names — inspect `mod.node_group.interface.items_tree`).
- Drivers and custom properties for parametric rigs; Python only for what nodes can't do.

## Materials and color
- Principled BSDF inputs were renamed in 4.0 (for example "Subsurface Weight", "Specular IOR Level", "Emission Color"); look inputs up by name at runtime and fail loudly if missing.
- Image textures: base color in sRGB, everything else (roughness, metallic, normal, height, ORM) **Non-Color**. Normal maps through a Normal Map node (tangent space, OpenGL convention).
- View transform: AgX is the default since 4.0 (Filmic is legacy; "Standard" for flat graphics and product shots where colors must match hex values); set explicitly in scripts (`scene.view_settings.view_transform`). Output PNG/EXR color depth per use; EXR is scene-linear.

## Rendering
- Cycles on Apple Silicon: Preferences → System → Cycles Render Devices → Metal; in scripts `prefs = bpy.context.preferences.addons["cycles"].preferences; prefs.compute_device_type = "METAL"; prefs.get_devices(); scene.cycles.device = "GPU"`. NVIDIA: `OPTIX` or `CUDA`.
- Quality/time: adaptive sampling with a noise threshold, denoising (OpenImageDenoise), light paths clamped for fireflies, persistent data for animations. EEVEE for fast previews and stylized work; Workbench for clay/QA renders.
- QA renders: low samples and resolution first, Read the PNG, then the final. Render passes/AOVs and Cryptomatte for compositing.

## Import / export
- glTF/GLB (`bpy.ops.export_scene.gltf(filepath=…, export_format="GLB", export_apply=True)`) for web and real-time; FBX for DCC/game engines (axis and scale settings: apply transforms, check unit scale); USD for pipelines (Houdini Solaris); OBJ via `bpy.ops.wm.obj_export`; STL/PLY via `bpy.ops.wm.stl_export`/`wm.ply_export` on current versions (older builds used `export_mesh.*`) — check the operator exists with `hasattr`.
- Pack or relativize textures (`bpy.ops.file.pack_all()` or `//relative/paths`) before handing over a .blend; linked vs appended data matters for library files.

## MCP for Blender (agent-scoped server)
- `mcp__blender` talks to a running Blender through the MCP for Blender add-on (socket on localhost:9876 by default): scene and object info, viewport screenshots, `execute_blender_code`, Poly Haven assets; Sketchfab search and Hyper3D/Hunyuan3D generation need their own keys and toggles in the add-on panel.
- Setup once: `uvx mcp-for-blender@2.1.1 install-addon` (or install the add-on file from the repo), enable it, click "Connect" in the N-panel. Telemetry is disabled in the stack's config (`DISABLE_TELEMETRY=true`).
- `execute_blender_code` runs arbitrary Python in the user's session: save the file first, keep changes inside the project, and prefer headless scripts for anything that must be reproducible. Generated 3D assets (Hyper3D etc.) are paid third-party services — only on the user's request.

## Pitfalls
- Operators in background mode failing with "context is incorrect" → use data API or `temp_override`.
- Scale not applied → wrong physics, bevels, exports. Flipped normals → black faces, bad prints (Mesh → Normals → Recalculate Outside).
- Name collisions: Blender renames to `Name.001`; look up by the object you created, not by name.
- Undo and memory: long scripts in the UI session accumulate undo steps; run heavy batch jobs headless.
- Absolute texture paths break on other machines; missing textures render pink.

## Checklist
Script runs headless and exits non-zero on failure · units and scale applied · color spaces right · QA render Read · export opened back (or validated with the glTF validator) · versions of Blender and add-ons reported.
