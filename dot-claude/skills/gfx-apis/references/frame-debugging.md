# Frame debugging checklist

## Capture
- RenderDoc: launch through `renderdoccmd capture -w ./game` or the in-app API (`RENDERDOC_API` StartFrameCapture/EndFrameCapture) around the frame; `.rdc` files saved next to the build. Python scripting (`renderdoc` module, in RenderDoc's own Python) for automated checks of draw counts or pixel values.
- Xcode: Capture GPU Workload (or `MTLCaptureManager` programmatically to a `.gputrace` file); Metal System Trace in Instruments for timing.
- PIX on Windows for D3D12 (GPU captures and timing captures).
- Browser WebGPU: Chrome `chrome://gpu`, WebGPU Inspector extension; Safari Web Inspector graphics tab.

## Wrong image — walk the pipeline backwards
1. Pixel history on a wrong pixel: which draw wrote it, was it depth-/stencil-/blend-rejected?
2. Draw state: viewport/scissor, cull mode and winding, depth test/write/compare (reverse-Z expects GREATER), blend state, render target formats (sRGB?).
3. Vertex input: mesh viewer pre-/post-transform; NaNs or collapsed vertices → matrix order (row vs column major), wrong stride/offset, wrong index type.
4. Resources bound: texture views (mip/array ranges, swizzle), samplers (filtering, address mode), uniform/constant buffer contents (alignment: std140/std430, 256-byte constant buffer alignment on D3D12, 16-byte vec3 padding).
5. Shader debugging: step the pixel or vertex shader (RenderDoc, PIX, Xcode shader debugger); compare against a CPU reference for one pixel.

## Black or missing output
Pipeline not bound or failed creation (check logs); render pass load op `CLEAR`/`DONT_CARE` wiping earlier work; missing barrier so the read sees old data; present from the wrong image; exposure/tonemapping producing zero; alpha zero with blending.

## Flicker or vendor-specific breakage
Synchronization: run with synchronization validation; check frames-in-flight resource reuse; uninitialized memory (render targets used before being written).

## Performance capture
GPU timestamps per pass (queries) in the build itself; vendor tools (Nsight Graphics, Radeon GPU Profiler, Xcode Metal counters) for occupancy, bandwidth and stalls; compare against the frame budget per pass.
