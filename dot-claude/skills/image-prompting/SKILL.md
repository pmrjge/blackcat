---
name: image-prompting
description: Load before generating or editing any image through image-studio — SVG logos, icons, illustrations, photos, raster images, edits and composites; prompts, references, QA, costs.
---
# Image generation and editing (mcp__image-studio)

One server, one job per tool. Files are saved to disk; you get paths, sizes and the cost.
`preview=true` adds a small render for your eyes only.

| Tool | Default model (provider) | Use it for | Output | Cost with the default |
|---|---|---|---|---|
| `generate_svg` | Recraft V4.1 Pro Vector (OpenRouter) | logos, icons, illustrations, stickers, patterns, posters, any graphic design; one optional reference image | SVG only | $0.30 an image |
| `generate_image` | GPT Image 2.5 Sunburst (Opper) | photographs and photoreal scenes, product and lifestyle shots, ads and posters with legible text, transparent cutouts; 1-4 a call, up to 8 references | PNG, JPEG or WebP | per 1024x1024 image: low ≈ $0.006, medium ≈ $0.013, high ≈ $0.053 (default), xhigh ≈ $0.094, max ≈ $0.21; a 4K image ≈ 1.9× |
| `edit_image` | Riverflow V2.5 Pro (OpenRouter) | retouching, background swaps, object edits, relighting, style transfer, composites, a design on a mockup; 1-10 input images | PNG, JPEG or WebP | $0.13 at 1K, $0.15 at 2K, $0.17 at 4K |
| `collect_image` | — | an Opper job still rendering when `generate_image` stopped waiting (its `pending` list) | as generated | already billed |

Graphic design is always SVG; never make a logo, icon or illustration as a raster. There is no other
image API or service in this stack (rules). Agents without the tools ask designer or image-director.

## 0. Models
- The user picks the model behind each tool in stack.env: IMAGE_STUDIO_SVG_MODEL (an OpenRouter model
  with SVG output), IMAGE_STUDIO_IMAGE_MODEL (an Opper image model), IMAGE_STUDIO_EDIT_MODEL (an
  OpenRouter model that takes input images). Empty = the default above. /stack-doctor shows the models
  in use and checks each in its provider's catalog.
- Each tool's description names the model in use and, for the defaults, its options and prices. The
  sizes, qualities and prices in this skill are the defaults'; with another model, the tool checks
  every option against that model's catalog entry and refuses one it lacks before anything is paid,
  saying which option or which setting.
- Never edit stack.env. When the model in use can't do what's needed (no SVG, no input images, too few
  references), say so and name the setting the user can change.

## 1. Spec
- Purpose and placement: app icon, favicon, website hero, social post, print, merch, packaging.
- Aspect ratio and, for rasters, resolution: web and social 1K-2K; print = mm ÷ 25.4 × 300 px for
  close viewing (so an A4 page wants 4K); a vector has no resolution, only proportions.
- Style, palette as hex (brand colors first), must-have elements, exact text to render, count and
  budget (count × price above).

## 2. References
- Read every reference image first: subject, composition (framing, angle, lens feel, negative space),
  light (direction, softness, color temperature), palette (5 hex), materials, level of detail, mood.
  Decide what to KEEP and what to CHANGE.
- `generate_svg` takes one `reference_image` (image-to-image: Recraft redraws it as vector art, guided
  by the prompt); put anything else you keep from references into words (form language, palette hexes, line weight, level of detail).
  `generate_image` takes up to 8 `reference_images` as style or subject references; `edit_image` takes
  1-10 `images` to change or combine. Local files (PNG/JPEG/WebP) go out scaled under 1920 px and
  together under the request limit; https URLs go as they are.
- References must be the user's, licensed or client-supplied.

## 3. Vector prompts (generate_svg)
Short concrete sentences, most important first: subject and action → form language (geometric,
organic, rounded, angular; line weight; filled or outline) → style (flat vector, line icon, glyph,
isometric, emblem, mascot, die-cut sticker, pattern tile, poster layout) → composition (centered,
negative space, margins, plain background) → palette in words and hex → text in double quotes with
its typographic look → constraints ("no gradients", "at most 4 colors", "no text"). Leave out camera,
lens and lighting words: photographic cues push toward noisy, many-path results.
- Logo mark: "Geometric fox head logo mark built from six flat triangles, centered on a plain white
  background, two colors #E8590C and #1B1B1B, no text, bold enough to read at 16 px."
- Icon in a set: the same style block every time ("line icon, 2 px uniform stroke, rounded caps and
  joins, 24-unit grid, #111827 on white, no fill") plus the subject.
- `colors=["#1A73E8", ...]` and `background_color` hand Recraft the palette (its `controls` option);
  a model without a palette option, or a refusal of it, puts the palette into the prompt instead (see
  `notes`). Fix a wrong fill in the SVG instead of regenerating.
- aspect_ratio with Recraft: 1:1, 4:3, 3:4, 16:9, 9:16 or auto; n 1-6 a call.

## 4. Photo and raster prompts (generate_image)
Natural sentences, 40-150 words, most important first: subject and action → setting → composition and
camera (shot size, angle, lens such as 35 mm or 85 mm, depth of field) → light (key direction,
softness, time of day, color temperature) → medium and look (film stock, grain, motion blur, color
grade) → palette → materials and details → constraints. No keyword soup: GPT Image follows long,
specific instructions and keeps several constraints at once.
- Quality is the main cost and time dial: low or medium for drafts and variations, high (default) for
  most work, xhigh or max for finals (max is slowest; a job still rendering comes back with
  `collect_image`).
- Size: aspect_ratio + resolution — 1K = short side 1024 (1024x1024, 1536x1024, 1824x1024 for 16:9),
  2K = 1440 (2560x1440), 4K = 2160 (3840x2160) — or an exact `size` "WxH" (multiples of 16, sides up
  to 3840, ratio up to 3:1).
- Text: the exact string verbatim in double quotes with its casing, font look and placement ("'LISBOA
  2027' in white condensed capitals across the top third").
- A transparent cutout (a product, a character): `background="transparent"`, `output_format` png or
  webp, and "isolated on a plain background" in the prompt.
- Subject consistency: pass the product or character as a reference and say its role ("image 1 is the
  bottle: keep its shape, label and colors exactly").

## 5. Edits (edit_image)
- Say the change and what must stay: "Replace the sky with a warm dusk; keep the building, the people
  and the framing unchanged." One or two changes per call; chain calls for more.
- Multi-image jobs: name each input by its role in the order given ("image 1 is the room, image 2 the
  sofa: place the sofa against the back wall, matching the room's light and perspective").
- `aspect_ratio` stays "auto" to keep the original framing; pick a ratio only to recompose (Riverflow:
  1:1, 4:3, 3:4, 3:2, 2:3, 16:9, 9:16, 21:9). `resolution` 1K, 2K or 4K; `background` transparent for
  a cutout (png or webp).
- Retouching: blemishes, stray objects, reflections, garbled signage; always "keep the face and
  identity unchanged" for people.
- Mockups: generate the scene with a blank panel, then `edit_image` with the SVG design (rasterized
  with `rsvg-convert -w 1600`) to place it, or set it in layout software for exact results.

## 6. Iterate cheaply
Drafts: `generate_image` at quality low (n up to 4 for variations); SVG with n=1-2 → look with
`preview=true` → change one variable → final at the size and quality the use needs. Keep a manifest
(file, tool, model, prompt, settings, references, cost, chosen or rejected and why).

## 7. Series and consistency
- A style block pasted verbatim into every prompt: medium, light, lens, palette hexes, texture and
  grain, composition rules, things that never appear (for vectors: stroke, radius, level of detail).
- Make the key image first, then pass it as a `reference_images` entry (or an `edit_image` input) for
  the rest; there is no seed to reuse.
- Review as a set: `montage *.png -tile 4x -geometry 512x512+8+8 sheet.jpg` (SVGs: rasterize first
  with `rsvg-convert -w 512`), then Read the sheet for drift in light, camera height, palette, grain.

## 8. Text and logotypes
- Logos and logotypes: SVG directions only; clean or rebuild the chosen one by construction
  (`svg-vector-craft`), set the wordmark in a licensed font converted to outlines, and screen it for
  conflicts (`brand-identity`).
- Text in raster images (posters, ads, packaging shots): `generate_image` at high or above, or
  `edit_image` to fix a word; 1-5 words per element, at most three elements, then check character by
  character at 100 % (accents such as Ç, Ã, É fail most often; a second reading:
  `tesseract image.png stdout -l por`). Body copy and legal lines are set as real type afterwards.

## 9. SVG QA and clean-up
- Root viewBox, sensible width/height; `paths` from the result (hundreds for an icon means
  over-detailed); stray specks, hidden shapes, needless clip paths and masks.
- An embedded raster (`<image>` with a data: URI) defeats the point: regenerate or redraw.
- `npx svgo --multipass in.svg -o out.svg`, then confirm the viewBox survived; `role="img"` and a
  `<title>` for web use. Rasterize at 16, 32 and 48 px to check small sizes.

## 10. Raster post-processing
- Prefer native resolution (`generate_image` or `edit_image` at 4K) over upscaling. Upscaling invents
  detail: up to 2× is usually safe for photos; inspect faces, hands, text and fabric at 100 %; never
  upscale text or logos.
- Background removal: `background="transparent"` first (either raster tool); otherwise rembg with
  `-m birefnet-general` (MIT; its default model is non-commercial). Check edges over black, white and
  mid-gray.
- Compositing: match perspective and horizon, lens and depth of field, light direction and softness,
  color temperature, black level, grain and sharpness; add contact shadows. `edit_image` can harmonize
  ("match the product's light and color to the scene; keep its shape, label and colors unchanged").
- Color: outputs are 8-bit sRGB. Web: keep sRGB. Print: convert once at the end with the printer's
  profile (`color-management`).
- Raster exports of an SVG, only when asked: `rsvg-convert -w 1024 logo.svg -o logo.png`; PDF with
  `-f pdf`; favicon `magick -background none logo.svg -define icon:auto-resize=16,32,48 favicon.ico`.

## 11. Costs, limits, errors
- Prices above: OpenRouter's listings for Recraft and Riverflow, OpenAI's token rates for GPT Image
  2.5 ($30 per million image-output tokens, charged through Opper), September 2026. Another model's
  price comes from its catalog entry when listed. Each result reports `cost_usd` when the provider
  sends it, plus an estimate.
- `generate_svg`: as many a call as the model allows (Recraft 1-6). `generate_image`: 1-4 (one Opper
  job each). `edit_image`: one image a call. Input images in one OpenRouter request: about 4.4 MB in
  all.
- Errors say why: an `IMAGE_STUDIO_…_MODEL=…` message = the model in use can't take that call (tell
  the user which setting); 402 = add credits (Opper or OpenRouter, whichever the tool names); 403 or a
  content-policy 400 = refused by moderation; OpenRouter 404 = the model isn't available to the
  account: its provider settings must allow the model's provider (recraft and sourceful for the
  defaults); 429 = wait; a missing key names the tools that need it (OPENROUTER_API_KEY:
  generate_svg and edit_image; OPPER_API_KEY: generate_image).
- Files go to `out_dir` (an absolute path inside the project for project work) or
  `$IMAGE_STUDIO_OUT_DIR` (default ~/Pictures/image-studio).

## 12. Legal and ethical guardrails
- Real brands: no real logos, trademarks, packaging or trade dress; mockups use client-supplied assets
  or invented brands that resemble no real mark.
- Artists: no living artist's name as a style prompt; describe the look by medium, technique, era,
  palette and composition.
- People: no identifiable real person without documented consent for that use; no fake endorsements,
  no sexual content, no realistic fakes of real events. Editing someone else's photo needs their right
  to it. In the EU, realistic generated or edited images of people, places or events must be disclosed
  as artificial (AI Act Art. 50, applicable since 2 August 2026).
- Outputs: purely AI-generated material is not copyrightable in the US (Copyright Office, January
  2025): client work needs real human authorship (selection, redrawing, compositing, editing) and a note
  of which parts were generated. Check the terms of the model makers (Recraft, OpenAI, Sourceful for
  the defaults) and of Opper and OpenRouter.

## 13. Deliver
Paths, tool and model, final prompt(s), settings (aspect, resolution or size, quality, palette),
references used, cost from the results, known flaws, clean-up and post-processing done, legal
notes. Never paste image data into the conversation.
