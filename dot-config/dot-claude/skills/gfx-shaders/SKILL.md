---
name: gfx-shaders
description: Use for shaders — HLSL, GLSL, MSL, WGSL, Slang; cross-compiling, PBR, debugging.
---
# Shaders

Baseline: `game-graphics`; API plumbing: `gfx-apis`; engine shader graphs: `game-engines`.

## Toolchain
- Slang v2026.19 (compiles to SPIR-V, HLSL/DXIL, MSL, WGSL, CUDA; modules and generics) — Verified 2026-10-02 https://github.com/shader-slang/slang/releases/latest
- DXC v1.9.2609 (HLSL → DXIL and SPIR-V) — Verified 2026-10-02 https://github.com/microsoft/DirectXShaderCompiler/releases/latest
- glslang / `glslangValidator`, SPIRV-Tools (`spirv-val`, `spirv-opt`), SPIRV-Cross (SPIR-V → MSL/HLSL/GLSL), naga (wgpu's WGSL/SPIR-V/MSL translator), `xcrun metal` for MSL — versions with the SDK in use.
- One source language per project; cross-compile from it (Slang or HLSL→SPIR-V→SPIRV-Cross) instead of maintaining parallel hand-written copies.
- Compile shaders at build time and fail the build on errors and warnings; runtime compilation only for hot reload in dev.

## Writing rules
- Precision: full `float` for positions and lighting accumulation; `half`/`min16float` (MSL/HLSL) for colors and normals on mobile where measured to help.
- Spaces explicit in names (`posWS`, `normalVS`, `uvTS`); matrices documented as row- or column-major and multiplication order consistent with the host code.
- Uniform/constant buffer layout matches the host struct exactly (std140/std430/scalar layout, HLSL packing rules, 16-byte alignment of vec3/float3); static-assert sizes on the host side.
- Branching: uniform branches are cheap; divergent branches and dynamic indexing into local arrays cost — measure before restructuring.
- Texture sampling: correct sampler (linear/point, clamp/repeat), explicit LOD or gradients inside divergent control flow; `textureSize`/`GetDimensions` instead of passing sizes when available.
- Color: textures holding color are sRGB formats (hardware decode), data textures (normals, roughness, masks) are linear; lighting in linear space; tonemap and encode once at the end.
- No NaN sources: `normalize(0)`, `pow(negative, x)`, division by zero, `sqrt` of negatives → clamp or `max(eps, …)`.

## PBR baseline (metal/roughness)
GGX/Trowbridge-Reitz NDF, Smith height-correlated visibility, Schlick Fresnel with F0 = 0.04 for dielectrics and base color for metals; energy conservation; roughness remap (`alpha = roughness²`); image-based lighting with prefiltered environment + split-sum BRDF LUT; normal maps in tangent space with a consistent handedness (MikkTSpace, matching the baker).
Read `references/pbr-checks.md` when a material looks wrong or must match another renderer.

## Compute shaders
Workgroup size a multiple of the subgroup/wave width (32 or 64; query it); shared memory for tiles with barriers; avoid bank conflicts; atomics sparingly. Heavy ML-style compute belongs to `gpu-kernel-dev`.

## Debugging and performance
- Debug output: visualize intermediates (normals, UVs, roughness) through a debug mode switch; shader printf (Vulkan `debugPrintfEXT`, Slang `printf`) in dev builds.
- Step through with RenderDoc/PIX/Xcode shader debuggers (`gfx-apis` reference).
- Cost: compiler stats (DXC `-Fc` disassembly, Radeon GPU Analyzer, Xcode shader profiler, Mali/Adreno offline compilers) for register pressure and instruction counts; occupancy drops when registers spike.
- Variants: keep permutations bounded (feature flags as specialization constants/function constants instead of `#ifdef` explosions); precompile the variants actually used.

## Pitfalls
Matrix order mismatch; sRGB double-encode or missing decode; tangent-space handedness mismatch with the baker; derivative functions in non-uniform control flow; precision artifacts in large worlds (camera-relative rendering); shader variants compiled at first use causing hitches.

## Verify
All shaders compile in the build with warnings as errors · `spirv-val` clean for SPIR-V outputs · reference scene screenshots compared (diff threshold stated) on every backend shipped · GPU timing for the changed pass recorded.
