---
name: gfx-apis
description: Load before Vulkan, Metal, D3D12 or WebGPU/wgpu code — resources, sync, validation, frame capture.
---
# Graphics APIs

Baseline rules: `game-graphics`. Shaders: `gfx-shaders`. Compute kernels for ML/HPC: `gpu-kernel-dev`.

## Versions
- Vulkan SDK 1.4.363.0 (API 1.4) per LunarG's announcement (seen in search results only: unverified) — https://vulkan.lunarg.com/sdk/home
- wgpu 30.0.1 (breaking API changes most majors) — Verified 2026-10-02 https://github.com/gfx-rs/wgpu/releases/latest
- WebGPU on by default: Chrome 113+ (Windows, macOS, ChromeOS), Safari 26, Firefox 141+ on Windows; other Firefox platforms and Linux Chrome vary — Verified 2026-10-02 https://web.dev/blog/webgpu-supported-major-browsers (Firefox macOS details unverified)
- Metal 4 requires the OS 26 releases on Apple silicon (partly unverified) — https://developer.apple.com/wwdc26/guides/metal/
- RenderDoc 1.46 — Verified 2026-10-02 https://github.com/baldurk/renderdoc/releases/latest

## Choosing
| target | API |
|---|---|
| portable native + web, Rust | wgpu (Vulkan/Metal/D3D12/GL backends, WebGPU in browsers) |
| portable native C/C++ with max control | Vulkan (on Apple through a Vulkan-on-Metal layer such as MoltenVK, only when needed) |
| Apple-only, best tooling there | Metal |
| Windows/Xbox | Direct3D 12 |
| browser | WebGPU (WebGL2 fallback only when the audience needs it) |

## Core model (explicit APIs)
- Resources: buffers and textures with explicit usage flags and memory types (device-local for GPU data, host-visible for uploads/readback); suballocate (VMA on Vulkan, D3D12MA) — never one allocation per object.
- Pipelines are expensive to create: build them at load time or asynchronously, cache them (`VkPipelineCache`, Metal binary archives, PSO libraries), and prefer dynamic state to pipeline explosions.
- Descriptors/bind groups: group by update frequency (per frame, per material, per draw); bindless/descriptor indexing for large material sets where supported.
- Command recording per thread, submission ordered; frames in flight (2–3) with per-frame resources to avoid CPU/GPU stalls.

## Synchronization (most bugs live here)
- Vulkan: synchronization2 barriers with exact stage and access masks; image layout transitions; semaphores between queues/swapchain, fences for CPU waits; timeline semaphores for general scheduling. Dynamic rendering instead of render pass objects in new code where the target supports it.
- D3D12: resource barriers or enhanced barriers; fences per queue.
- Metal: hazard tracking automatic for tracked resources; untracked heaps need fences/events; Metal 4 moves more control to the app (residency sets, explicit barriers) — read the Metal 4 docs before porting.
- WebGPU/wgpu: synchronization is implicit; costs come from buffer mapping and queue writes — use staging belts and `queue.write_buffer` wisely.
- Never wait idle per frame (`vkDeviceWaitIdle`, `waitUntilCompleted`) outside teardown.

## Debugging
- Validation always on in debug: Vulkan validation layers (incl. synchronization validation and GPU-assisted validation when chasing out-of-bounds), D3D12 debug layer + GPU-based validation, Metal API and shader validation (`MTL_DEBUG_LAYER=1`, `MTL_SHADER_VALIDATION=1`), wgpu with `InstanceFlags::VALIDATION | DEBUG`.
- Name every object (`vkSetDebugUtilsObjectNameEXT`, `label` in wgpu/Metal) and add debug groups per pass.
- Frame capture: RenderDoc (Vulkan, D3D, GL), PIX (D3D12), Xcode GPU capture / Metal debugger, Nsight Graphics; read `references/frame-debugging.md` when a frame renders wrong or a capture is needed.
- GPU crashes: Vulkan device-lost → Aftermath/DRED/`VK_EXT_device_fault`; check the last submitted work and out-of-bounds indices.

## Pitfalls
Missing barrier/layout transition (works on one vendor, breaks on another); sRGB vs linear format confusion; depth range and Y-flip differences between APIs; swapchain resize not recreating dependent resources; uploading per draw instead of batching; validation layers off in the only test run.

## Verify
Zero validation errors in a full run · captures of the changed passes Read · frame time measured on target hardware · tested on at least two backends/vendors when portability is claimed · API/SDK and driver versions reported.
