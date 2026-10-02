# Image prompting: costs, limits, errors

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
