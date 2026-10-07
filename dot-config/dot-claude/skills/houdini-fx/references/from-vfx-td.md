# Houdini FX TD procedure (moved from the vfx-td prompt)

## Tools, most precise first
- `hython` scripts (`hou`) and `hbatch` via Bash build and cook networks, write caches and export; keep each script next to its .hip so the scene can be rebuilt.
- Renders: `husk` on a USD stage (Karma CPU/XPU); ROP renders through `hython` for other outputs.
- Long cooks, sims and renders run in the background with a log file; watch them with Monitor and stop a runaway job with TaskStop.
- The GUI (viewport checks, steps no script reaches) only through computer use.

## Process
1. Spec: shot and frame range, fps, units and scale, sim type and look, cache formats (bgeo.sc, VDB, USD, Alembic), render outputs and AOVs, color pipeline, deliverable paths.
2. Build procedurally: named nodes, promoted parameters, HDAs for reuse; low-resolution proxy sims before full resolution.
3. Cache every sim stage to disk in versioned folders (`$HIP/cache/<name>/v###`); never overwrite a version.
4. Self-check before reporting: probe the frame range (every frame file present, sizes plausible, no empty or NaN geometry on the first, middle and last frames via `hython`), then a contact sheet of renders or flipbook frames (ffmpeg tile) that you Read.
5. Deliver: .hip and HDA paths, scripts, cache and render paths with frame ranges, the contact sheet, sim settings and timings, what remains.
