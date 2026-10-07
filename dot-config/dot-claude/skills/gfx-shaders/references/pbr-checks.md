# PBR material checks

## Reference values
- Dielectric F0 ≈ 0.04 (water 0.02, glass 0.04–0.05, gems up to ~0.17); metals take F0 from base color, with no diffuse.
- Base color albedo in sRGB: charcoal ~50, fresh snow ~240; nothing dark below ~30 or bright above ~240 for non-emissive dielectrics. Metals' base color is bright (≥ ~180 sRGB).
- Roughness 0 only for idealized mirrors; most real surfaces 0.2–0.9.

## White furnace test
Render a sphere with base color white under a uniform white environment: a correct energy-conserving BRDF makes it nearly invisible (no dark rims except where multiple-scattering compensation is missing at high roughness). Rims brighter than the environment = energy gain bug.

## Matching another renderer (glTF viewers, Blender, Substance)
- Same color management (linear workflow, same tonemapper — compare with tonemapping off or a neutral/ACES/AgX choice matched), same exposure, same environment map and its intensity.
- glTF 2.0 metallic-roughness: roughness in G, metallic in B of the same texture; occlusion in R (often packed ORM).
- Normal map convention: OpenGL (Y+) vs DirectX (Y−) green channel; flip when the source differs.
- Compare with the Khronos glTF Sample Viewer on the glTF sample assets as the reference.

## Common visual bugs
Too-shiny everything (roughness read as smoothness or from the wrong channel); dark metals (diffuse not zeroed or IBL specular missing); fireflies (unclamped specular at grazing angles, too few prefilter samples); banding (8-bit intermediate targets — use RGBA16F); seams on mirrored UVs (tangent handedness).
