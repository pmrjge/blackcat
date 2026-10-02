---
name: game-graphics
description: Load before game or real-time graphics work — engines, GPU APIs, shaders, netcode, frame budgets, profiling; the module map.
---
# Games and real-time graphics (hub)

## Scope
Gameplay code, engine work and real-time rendering. 3D assets (modeling, texturing, Blender/Houdini) in `blender-3d`, `sculpting-texturing`, `houdini-fx`; GPU compute kernels in `gpu-kernel-dev`; CPU profiling method in `cpu-performance`.

## Modules
| module | load when |
|---|---|
| `game-engines` | Godot, Unity, Unreal, Bevy: project structure, scripting, scenes, builds, editor automation |
| `gfx-apis` | Vulkan, Metal, Direct3D 12, WebGPU/wgpu: resources, sync, pipelines, debugging layers, frame capture |
| `gfx-shaders` | HLSL, GLSL, MSL, WGSL, Slang; PBR, shader compilation and cross-compilation, shader debugging |
| `game-netcode` | multiplayer: authority, prediction, rollback, interpolation, transports, lag testing |

## Baseline rules
- **Frame budget** is the requirement: 16.6 ms at 60 Hz, 8.3 ms at 120 Hz, 11.1 ms at 90 Hz for VR; state the target platform and budget before optimizing, split CPU (game, render thread) and GPU time.
- **Measure first**: engine profiler or Tracy for CPU, RenderDoc/PIX/Xcode GPU capture/Nsight Graphics for GPU; report frame-time percentiles (p50/p99, 1 % lows), never average FPS alone. Profile release/development builds, not the editor.
- Fixed timestep for simulation (`accumulator` pattern) and variable-rate rendering with interpolation; never scale physics by a raw frame delta.
- Determinism where it matters (replays, lockstep, rollback): fixed-point or controlled float settings, seeded RNG per system, ordered iteration.
- Data-oriented hot paths: contiguous arrays/ECS for many entities; no per-frame allocations in update loops (GC spikes in C#/GDScript, allocator churn in C++/Rust).
- Asset pipeline is code: import settings versioned, textures compressed per platform (BC/ASTC/ETC2), meshes with LODs, audio streamed vs. loaded deliberately.
- Input, UI scaling, controller support and accessibility options (remapping, subtitles, colorblind modes) are features, not polish.

## Using the machine
- One GPU-heavy job at a time on the local GPU (builds with shader compilation, light baking, benchmarks); say when one is running.
- Editor GUIs driven by screen only as a last resort: load `computer-use-apps` first; prefer headless CLI builds and engine scripting (Godot `--headless`, Unity `-batchmode`, Unreal `UnrealEditor-Cmd`/RunUAT).
- Store submissions, console dev-kit deployment and publishing builds to storefronts (Steam, itch.io, consoles) need the user's consent; SDKs under NDA (consoles) are never copied into public places.

## Verify
Builds for the target platform from the CLI · automated tests (engine test runner) green · frame-time capture before/after for performance work with platform and settings · visual changes checked with screenshots or frame captures that you Read · engine and SDK versions reported.
