---
name: houdini-fx
description: Use for Houdini — VEX, HDAs, Pyro/FLIP/Vellum/RBD, caching, Solaris/Karma, hython, PDG.
---
# Houdini FX

## Scope and baseline
- Covers Houdini for procedural modeling, effects simulation and USD rendering. Blender-side work in `blender-3d`; compositing and delivery in `motion-graphics` and `media-ffmpeg`.
- Versions: Houdini 21 shipped Aug 2025 (sparse GPU Pyro solver, Copernicus texture baking, Solaris Shot Builder, Karma Gaussian splats); Houdini 22 is reported as released in Jul 2026 (unverified — check `hython --version` or Help → About and the SideFX "What's new" page). APIs and node versions (`::2.0` namespaced nodes) change between majors.
- Licenses decide what runs: Apprentice (free, watermarked, `.hipnc`, restricted command-line and third-party renderer use), Indie (`.hiplc`, revenue cap), Core/FX. Check what the user's license allows before planning hython or husk batch jobs; files don't move up from Apprentice/Indie to commercial.
- No Houdini MCP server is enabled in this stack: script it with `hython` via Bash, and use computer use only for GUI inspection (load `computer-use-apps` first). A maintained community server exists (github.com/kleer001/houdini-mcp, MIT, v0.3.1 Sep 2026) but installs a plugin and `pythonrc.py` hook into the Houdini preferences: optional, only with the user's consent.

## Mental model
- Contexts: OBJ (objects), **SOP** (geometry), **DOP** (dynamics), **LOP** (Solaris, USD stage), **COP** (Copernicus image ops), **TOP** (PDG task graphs), CHOP (channels), VOP (visual VEX), ROP/outputs.
- Geometry = points, vertices, primitives, detail, each carrying **attributes**: `@P`, `@N`, `@Cd`, `@v` (velocity, needed for motion blur and sims), `@pscale`, `@orient`/`@up` (instancing), `@id` (stable identity), `@name` (pieces), `@density`/`@temperature`/`@flame` (volumes). Most bugs are an attribute on the wrong class or missing.
- Everything is procedural: keep the network live, drive variations with parameters and wedges, lock or cache only at stable boundaries.

## VEX (Attribute Wrangle, run over points unless set otherwise)
```c
// jitter points along their normal, with a per-point seed
float amp = chf("amp");                       // spare parameter (click the button to create it)
@P += @N * amp * (rand(@id + chi("seed")) - 0.5);
i@pieceid = int(rint(fit01(rand(@ptnum), 0, 9)));
```
- Lookups: `point(0, "P", pt)`, `nearpoint`, `pcfind`/`pcopen` (neighbors), `xyzdist` + `primuv` (closest surface point and its attributes), `volumesample`. Creation/removal: `addpoint`, `addprim`, `setpointattrib`, `removepoint` (applied after the wrangle finishes).
- Noise: `noise`, `onoise`, `curlnoise` (divergence-free, for advection), `anoise`; `fit`, `chramp` for artist controls.
- Performance: VEX over Python for per-element work; avoid wrangles that loop over all points per point (O(n²)) — use point clouds.

## Procedural modeling and assets
- For-Each loops (per piece/connected piece/number) with compile blocks for speed; Solver SOP for iterative growth; Labs tools (SideFX Labs) for game-art utilities.
- Houdini Digital Assets (HDAs): promote only needed parameters, version the asset type name (`studio::tool::1.0`), keep embedded help; Houdini Engine exposes HDAs in Unreal, Unity and other hosts.

## Simulations
| Solver | For | Key controls |
|---|---|---|
| Pyro (sparse; GPU option in 21) | smoke, fire, explosions | voxel size, source attributes (density, temperature, flame, v), dissipation, disturbance/turbulence, shredding, sparse padding |
| FLIP | liquids | particle separation (resolution), narrow band, collision VDBs, viscosity, whitewater as a post-sim |
| Vellum | cloth, hair, soft bodies, grains | constraint types and stiffness, substeps and constraint iterations, pin groups, `thickness` |
| RBD (Bullet) | fracture, destruction | RBD Material Fracture, glue/cone-twist constraints, collision padding, `@active`, sleeping |
| MPM | snow, sand, mud, elastoplastic | material presets, particle separation; heavy — test at low resolution |
| POPs | particles | forces, collisions, birth attributes, `@age`/`@life` |
- **Real-world scale** (1 unit = 1 m) or the defaults misbehave; set gravity and densities accordingly.
- Iterate at low resolution (voxel size / particle separation ×2–4), then raise; resolution scales cost roughly with the cube of 1/voxel size.
- Substeps for fast motion and stiff constraints; collisions from clean closed VDBs (VDB from Polygons) with adequate thickness.
- Velocity fields and `@v` are required for motion blur and retiming.

## Caching discipline
- File Cache SOP with versioning (`$HIP/geo/$HIPNAME/<name>/v001/<name>.$F4.bgeo.sc`), one cache per stable stage (source → sim → post), caching to local SSD, never re-simulating what is cached.
- Formats: `.bgeo.sc` (Houdini), VDB for volumes, Alembic for geometry exchange, USD for layout/lookdev/render.
- Wedging and farm-style batch: TOPs (PDG) with `wedge` attributes (`@wedgeindex`), local scheduler with a sane slot count, or HQueue/Deadline on a farm.

## Solaris, USD, Karma
- LOPs build a USD stage: SOP Import/SOP Create, Material Library (MaterialX), Camera, Lights, Karma Render Settings, USD Render ROP. Keep payloads and layers structured (asset, layout, lookdev, lighting).
- Karma CPU vs XPU (GPU + CPU): XPU for speed where features suffice; check feature parity for the shader/volume you use.
- Command-line render: `husk --renderer BRAY_HdKarma --frame-range 1 120 -o $HIP/render/shot.$F4.exr stage.usd` (options vary by version — `husk --help`).

## hython and batch automation
```python
# hython build.py scene.hip  — cook a cache and save
import sys, hou
hou.hipFile.load(sys.argv[1], suppress_save_prompt=True)
cache = hou.node("/obj/fx/filecache_sim")
cache.parm("execute").pressButton()          # or a ROP: hou.node("/out/geo1").render(frame_range=(1, 120))
hou.hipFile.save()
```
- `hou.node(path).createNode("…")`, `.setInput`, `.parm("x").set(v)`, `.layoutChildren()`, `.cook(force=True)`; errors via `node.errors()`. Use environment variables (`$HIP`, `$JOB`) instead of absolute paths.
- `hbatch` for interactive command-line scripting; `hython -c` for one-liners. Run long cooks in the background (Monitor) and log to a file.

## Exports and hand-off
Alembic/USD for DCC exchange, FBX (with care for scale and axes) or glTF (ROP GLTF) for engines, VDB for volumes, EXR multichannel with AOVs for compositing; vertex animation textures (Labs) for real-time engines. Record units, frame range and fps with every export.

## Pitfalls
Wrong attribute class; missing `@v`/`@id`; time-dependent nodes cooking every frame unnecessarily; non-deterministic seeds; caches written into the .hip directory tree without versioning; UI-only settings not captured in scripts; Apprentice files contaminating a commercial pipeline.

## Checklist
License confirmed for batch/CLI · scene at real scale · low-res iteration before final · caches versioned and reused · velocity for motion blur · render or flipbook frames Read · exports opened back in the target app · Houdini version reported.
