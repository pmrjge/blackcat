---
name: image-prompting
description: Opper image generation/editing procedure — reference-image analysis, prompt anatomy per model family, model choice, edits, consistent series and storyboards, file handling.
---
# Image direction with Opper (mcp__opper-image)

Tools: `image_models` (live catalog), `generate_image`, `edit_image`, `upload_image` (→ file_id for reuse), `image_job` (poll async jobs). Outputs are saved to disk; you get paths. Inspect them with Read.

## 1. Spec
Purpose, audience, format (px or aspect; print → size × 300 dpi), style, must-have elements, exact text to render, number of deliverables, deadline for quality vs cost.

## 2. Reference analysis (Read each image)
Subject · composition (framing, angle, lens feel, negative space) · lighting (key direction, softness, color temperature) · palette (5 hex) · materials/textures · medium/style · era · mood · typography. Then decide per reference: KEEP vs CHANGE.

## 3. Model choice (confirm with `image_models`; the catalog changes)
| Need | Try first |
|---|---|
| Photoreal, general quality | `bytedance:ap/seedream-5-pro`, `gemini/imagen-4.0-ultra-generate-001`, `deepinfra/black-forest-labs/FLUX-2-max` |
| Text, typography, layouts, infographics | `openai/gpt-image-2`, `fal/ideogram-v3`, `fal/recraft-v3` |
| Edits, multi-reference, character consistency | `gemini/gemini-3-pro-image-preview` (Nano Banana Pro), `bytedance:ap/seedream-5-pro`, `fal/flux-kontext-pro`, `openai/gpt-image-2` |
| Vector-style logos/icons | `deepinfra/Bria/Bria-3.2-vector`, `fal/recraft-v3` → hand to designer for true vectors |
| Fast, cheap drafts | `deepinfra/black-forest-labs/FLUX-2-klein-9b`, `pruna/p-image`, `gemini/imagen-4.0-fast-generate-001` |
| EU data residency | `bytedance:eu/seedream-5` |
Default when unsure: `$OPPER_IMAGE_MODEL`. Pixel-size models take `size` ("2048x2048"); aspect-ratio models take `aspect_ratio` ("16:9"). Use only values the catalog lists.

## 4. Prompt anatomy
Natural sentences, most important first: subject + action → setting → composition/camera (shot, lens, angle) → lighting → style/medium → palette → materials/details → text in quotes with its typographic style → constraints. 40–120 words; no keyword soup.
- Gemini / GPT-image: conversational, precise spatial language; edits as instructions ("Replace the sky with dusk; keep the building and people unchanged").
- Seedream / FLUX / Imagen: descriptive scene prose; name lens (e.g. 85 mm), light quality, textures.
- Provider-specific knobs (seed, negative_prompt, guidance, steps) go in `parameters` only if the model supports them.

## 5. Iterate cheaply
Draft 1–2 images (fast model or low quality) → Read → adjust one variable at a time → final at target size/quality. Slow models: `run_async=true`, then `image_job`.

## 6. Edits
`edit_image(image=path|url|file_id, prompt, mask=?, reference_images=[…])`. Mask: white = area to change. Always state what must stay unchanged. Upload a source used repeatedly once with `upload_image` and pass the file_id.

## 7. Series and storyboards
Write a style bible (character sheet: face, hair, build, wardrobe, palette; world rules; camera language) and reuse it verbatim in every prompt. Generate the key frame first; pass it as a reference image for the rest. Shot list: number · beat · shot type · action · emotion · continuity notes.

## 8. Deliver
Paths, model, final prompt(s), cost from the tool output, and any known flaws. Never paste image data.
