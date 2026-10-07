---
name: udim-texture-painting
description: Use for UDIM texturing — tile layout, texel density, painting across tiles in Substance 3D Painter, Mari or Blender, UDIM export.
---
# UDIM texture painting

Hub: `sculpting-texturing` (UVs, baking, PBR values). Color spaces and ACES: `color-management`. Map files (conversion, packing, resizing): `raster-imaging`. Sculpted displacement feeding the tiles: `organic-sculpting`.

## Versions (checked 2026-10-05)
- Substance 3D Painter 12.1.5 (2026-09-15); 12.1 added OpenPBR, automatic re-bake and skew painting. Export token for the tile: `$udim` (wrap it as `(.$udim)` so non-UDIM exports drop the dot); `$uvTileName` since 11.0. Multi-layer PSD export does not support UV tiles. Exact project-creation option names: unverified, read them on screen.
- Mari 7.5v2 (2026-02-04) is the stable release; Mari 8.0 is in open beta (Sep 2026): use 7.5 for production unless the user chose the beta.
- Blender 5.2 LTS: image textures take UDIM tiles (`<UDIM>` token in the file path); 5.2's `bpy.data.file_path_foreach` with `EXPAND_TOKENS` visits every tile's path (for path fix-ups and packaging scripts). 5.0 made the working color space selectable: Linear Rec.709 (default), Linear Rec.2020 or ACEScg.

## 1. Tile numbering and layout
- Tile number = 1001 + u + 10·v for the tile whose lower-left corner is (u, v), u in 0–9: tile 1001 is [0,1]×[0,1], 1002 is u ∈ [1,2], 1011 is v ∈ [1,2]. Never more than 10 tiles in a row.
- Lay tiles out by body region and resolution need: e.g. head 1001, torso 1002, arms 1003–1004, legs 1005–1006, hands 1007, plus separate tiles or texture sets for eyes, teeth and hair cards. Write the map in a table (`tile · region · resolution`) and keep it with the asset.
- Texel density: equal across tiles unless an area deserves more (face often 2× the body); check with a checker texture across tile boundaries. All tiles of one set usually share one resolution (4K film, 2K real-time) — mixed resolutions are allowed by most tools but complicate engines.
- Shells must stay strictly inside their tile with padding (≥ 8–16 px at the tile's resolution); a shell crossing a tile edge paints and bakes wrong.
- One UV map for all UDIM textures of a material: glTF and several engines require it.

## 2. Painting
- Substance 3D Painter: enable the UV tile workflow at project creation (one texture set spanning tiles, painting across tile borders), bake mesh maps per tile from the high poly, then fill layers with masks, smart masks and generators driven by the baked curvature, AO and position maps. Keep the stack non-destructive (fills, masks and anchors over paint layers).
- Mari: channels per map (base color, roughness, specular, displacement modulation), layers and masks per channel, paint buffer projection with high bit depth; project photo references with the projector tools; shaders preview the look.
- Blender: an Image Texture node pointing at a tiled image (`Image → New → Tiled`, or a file path with `<UDIM>`), Texture Paint mode paints across tiles; bake per tile with Cycles to the same tiled image.
- Paint in the working color space (scene-linear, ACEScg in film pipelines; sRGB textures for base color in real-time); data maps (roughness, metallic, normal, displacement, masks) are Non-Color/Raw everywhere.

## 3. Export and naming
- Name files `<asset>_<channel>.<UDIM>.<ext>`: `hero_baseColor.1001.exr`, `hero_roughness.1001.png`. Mari's token is `$UDIM`, Painter's `$udim`, Blender, Arnold, RenderMan and USD use `<UDIM>` in the path.
- Bit depth: base color 8-bit sRGB (real-time) or 16-bit half EXR in ACEScg (film); roughness and masks 8-bit; normals 16-bit; displacement 32-bit float EXR, mid-level 0, Non-Color.
- Check that every tile in the layout exists for every channel: a missing tile renders black, pink or as the default value depending on the renderer.

## 4. Targets
- USD: the texture path in `UsdUVTexture`'s `inputs:file` carries the `<UDIM>` token. Omniverse's USDZ export does not support UDIM: bake to a single atlas for USDZ (Apple Quick Look, AR).
- Unreal Engine: files named `Name.1001.png` import as one UDIM texture; UDIMs need Virtual Texture streaming enabled for the project and the texture.
- glTF: no UDIM support. The Blender glTF exporter splits a UDIM image into one image per tile, and all UDIM textures of a material must share one UV map; for web or real-time delivery, prefer re-baking onto a single 0–1 atlas.
- Unity: no native UDIM sampling (unverified for 6.x: check the version's docs); re-bake to atlases or split materials per tile.
- Film renderers (Arnold, RenderMan, Karma, Cycles) read UDIM paths natively; Houdini and Solaris details in `houdini-fx`.

## 5. Scripted checks
```python
import re, pathlib, collections
tiles = collections.defaultdict(set)
for p in pathlib.Path("textures").glob("*.*.*"):
    m = re.match(r"(.+)_(\w+)\.(\d{4})\.\w+$", p.name)
    if m: tiles[m[2]].add(int(m[3]))
union = set().union(*tiles.values())
for ch, t in sorted(tiles.items()):
    print(ch, "missing", sorted(union - t))
```
Run it with `uv run`; compare against the tile table from §1.

## Verify
Tile table matches UV layout (no shell crosses a tile) · texel density checked across tiles · every channel has every tile · color space per map correct in the target renderer · seams checked across tile borders in renders that you Read · the delivery target's UDIM support confirmed (atlas re-bake where it has none) · app versions reported.

Sources (checked 2026-10-05): experienceleague.adobe.com (Substance 3D Painter release notes) · foundry.com (Mari releases) · https://www.sidefx.com/docs/houdini/solaris/udim.html · docs.omniverse.nvidia.com (USD and USDZ export) · dev.epicgames.com (UDIM import, virtual texturing) · https://github.com/KhronosGroup/glTF-Blender-IO (docs/blender_docs/scene_gltf2.rst) · https://developer.blender.org/docs/release_notes/5.2/python_api/ · https://developer.blender.org/docs/release_notes/5.0/color_management/
