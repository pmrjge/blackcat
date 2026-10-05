---
name: 3d-interface-engineering
description: Use to build 3D app interfaces — three.js/WebGPU viewports, cameras, picking, gizmos, outlines, in-scene and XR UI, editor tooling.
---
# 3D interface engineering

Hub: `game-graphics` (frame budgets, profiling, GPU APIs). Interaction design it implements: `3d-ux-design`. Web app around the canvas: `frontend-frameworks`, `typescript-engineering`. Shaders: `gfx-shaders`. Native Rust GUIs: `rust-native-gui`. Engine editors: `game-engines`.

## Versions (checked 2026-10-05)
- three.js r186 (2026-09-24). `WebGPURenderer` is imported from `three/webgpu` (since r171) and falls back to WebGL 2 where WebGPU is missing; node materials are written in TSL (`three/tsl`). WebXR works on `WebGPURenderer` since r185. Pin the exact release in `package.json`; three.js has no semver, and APIs move between releases (read the migration guide on every bump).
- Other stacks: Babylon.js (built-in GUI, gizmos, inspector), React Three Fiber with drei (React bindings), Godot (Control nodes, SubViewport, EditorPlugin gizmos), Unity (UI Toolkit, editor Handles), Unreal (UMG/Slate, Widget Components, Editor Utility Widgets), visionOS (SwiftUI + RealityKit `RealityView` with attachments). Library versions beyond three.js: unverified here, check before use.

## 1. Viewport architecture
- Separate the **document** (scene data, serializable: glTF, USD or your own schema) from the **view** (renderer, cameras, helpers, gizmos). Commands mutate the document; the view re-derives. This gives undo, collaboration and headless tests.
- Commands: each user action is a command object with `do`/`undo` and a label; a drag coalesces into one command on release; group multi-step operations in a transaction.
- Render on demand in editors (render after input, data change or animation tick; idle otherwise) to save battery; continuous loop only while something animates.
- Scene graph for the user's objects; a separate overlay scene for gizmos, grids and selection outlines, rendered after the main pass with its own depth handling.
- Units and axes defined once (meters, Y-up in three.js and glTF; convert at import from Z-up sources).

## 2. Cameras and navigation
- Perspective with the near/far ratio as small as the scene allows (z-fighting grows with it); logarithmic depth buffer only when the range demands it (it costs early-z). Orthographic for CAD-style views.
- Controls: `OrbitControls` (turntable), `TrackballControls`/`ArcballControls`, `MapControls`, or the camera-controls library for smooth transitions. Implement the presets from `3d-ux-design` (Blender, Maya-style, trackpad) as input maps, not separate control classes.
- Orbit pivot at the selection or the picked surface point; zoom toward the cursor (`zoomToCursor` on OrbitControls); frame-selected computes the bounding sphere and fits it to the frustum for both FOV axes.
- Never animate the camera without user input except framing; respect `prefers-reduced-motion`.

## 3. Picking and selection
- CPU raycasting (`Raycaster`) against a BVH (three-mesh-bvh accelerates raycasts on large meshes by orders of magnitude); `InstancedMesh` and `BatchedMesh` hits return the instance or batch id.
- Lines and points need screen-space tolerances (`raycaster.params.Line.threshold`, `.Points.threshold`) scaled by distance.
- GPU picking for very large or shader-deformed scenes: render object IDs into an offscreen target, read back one pixel (async readback on WebGPU), map to the object.
- Box and lasso selection: project bounding boxes or vertices to screen space and test against the region; frustum-test for "select through", depth-test against an ID buffer for visible-only.
- Selection outline as a post pass (mask + edge detection) or an inverted-hull mesh for few objects; never change the object's own material to show selection.

## 4. Gizmos (manipulators)
- Constant screen size: scale the gizmo by `distance × tan(fov/2) × k` each frame (orthographic: by zoom). Render in the overlay pass, depth test off or against a separate buffer, with hit areas larger than the visible handles.
- Axis drag: intersect the mouse ray with the plane that contains the axis and faces the camera most, then project onto the axis; plane drag: ray–plane intersection; rotation: angle between successive hit vectors on the rotation plane, accumulated (never `atan2` of absolute positions, which wraps).
- Snapping and numeric input apply to the computed delta, not to mouse pixels; show the delta in scene units during the drag.
- `TransformControls` in three.js covers translate, rotate and scale with local/world space; extend or replace it when the UX spec needs plane handles, pivots or snapping it lacks.
- Engines: Unity editor `Handles`, Godot `EditorNode3DGizmoPlugin`, Unreal editor modes and the Interactive Tools Framework for editor-side gizmos.

## 5. UI in and around the scene
- 2D panels outside the canvas (DOM or the engine's UI system) for properties, outliner and tools: accessible, searchable, testable. Keep the canvas for spatial content.
- Labels attached to 3D points: `CSS2DRenderer` (DOM labels following projected points) for few labels; SDF text in the scene (troika-three-text) for many or when depth occlusion matters.
- In-scene UI (XR, diegetic panels): flat panels facing the user, sized by angle (see `3d-ux-design`), text as SDF or MSDF, hit-tested with the same raycaster; pmndrs/uikit or engine UI on world-space canvases (Unity world-space UI, Unreal Widget Component, Godot SubViewport on a quad).
- Accessibility: the canvas is one element; mirror the scene tree as an ARIA tree or list in the DOM (names, types, selected state), keep keyboard focus in the DOM, and route keyboard commands to the same command layer as mouse input.

## 6. Performance
- Measure: `renderer.info` (draw calls, triangles, programs), browser performance panel, GPU timing where available; frame-time p50/p99 on named hardware (rules in `game-graphics`).
- Draw calls: instancing (`InstancedMesh`), batching (`BatchedMesh`), merged static geometry; LOD; frustum culling stays on.
- Assets: glTF with meshopt or Draco geometry compression and KTX2 (Basis Universal) textures (`gltfpack`, `KTX2Loader`); load in workers or with progressive placeholders; dispose geometries, materials and textures you remove (three.js does not garbage-collect GPU memory).
- Interaction budget: during orbit and drag drop expensive passes (shadows refresh, SSAO, high DPR) and restore them when idle.
- Device pixel ratio capped (e.g. `Math.min(devicePixelRatio, 2)`); resize via `ResizeObserver`.

## 7. XR
- three.js: `renderer.xr.enabled = true`, `XRButton`/`VRButton` from the addons, `renderer.setAnimationLoop` (not `requestAnimationFrame`); controllers and hands via `renderer.xr.getController(i)` / `getHand(i)`; hit-test and anchors for AR sessions.
- Frame budget 11.1 ms at 90 Hz; foveation and lower resolution scale before cutting content; avoid per-frame allocation (GC pauses are dropped frames).
- visionOS native: SwiftUI windows, volumes and immersive spaces with RealityKit; hover effects come from the system (no gaze data reaches the app).

## 8. Testing
- Unit-test the math (ray–plane, ray–axis projection, frustum fit, snapping) with plain tests; property tests for round-trips (world ↔ screen).
- Command layer tests headless (no renderer): do/undo sequences restore the document exactly.
- Visual tests: Playwright screenshots of the canvas at fixed size and DPR, with deterministic scenes (no time-based animation, seeded randomness), compared with tolerance; WebGL fallback in CI if the runner lacks WebGPU.
- Interaction tests: scripted pointer sequences (orbit, select, drag gizmo) asserting document state, not pixels.

## Verify
Document/view split and command-based undo in place · navigation presets and frame-selected work · picking correct on instances, lines and points · gizmo drags correct at any camera angle and with snapping · DOM mirror of the scene tree for accessibility · frame-time p50/p99 measured on named hardware · tests (math, commands, screenshots) green · library versions pinned and reported.

Sources (checked 2026-10-05): https://github.com/mrdoob/three.js/releases · https://threejs.org/docs/ · https://github.com/mrdoob/three.js/wiki/Migration-Guide · https://immersive-web.github.io/webxr/ · https://developer.apple.com/documentation/realitykit
