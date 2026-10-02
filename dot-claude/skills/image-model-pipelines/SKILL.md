---
name: image-model-pipelines
description: Load to run, fine-tune or evaluate open-weight image models — diffusers, mflux, ComfyUI API, LoRA/DreamBooth, memory, FID/CLIP caveats.
---
# Image-generation model pipelines

## Scope and the stack's rule
- Engineering on image generators: running open-weight models locally, fine-tuning them (LoRA, DreamBooth, full), building pipelines and services, evaluating them. Theory and training objectives in `diffusion-flow-models`; datasets in `dataset-curation`; training failures in `training-debug`; comparisons in `ml-experiment`.
- **Making images for the user's deliverables goes through image-studio only** (`image-prompting`). Local models are for model-development work the user asked for (training a style LoRA, benchmarking, building a product's pipeline) — not a way around that rule.
- Versions (Sep 2026): diffusers 0.40.0 (Aug 2026). Model families and leaders change monthly: search the Hub (mcp__huggingface `search hf://models …`, sort by trending/downloads) and read the model card for license, resolution, recommended steps/guidance and VRAM.

## Licenses and gating (check every time)
- Each checkpoint has its own license: e.g. FLUX.1 [dev] ships under a non-commercial license while FLUX.1 [schnell] is Apache-2.0; Stable Diffusion 3.5 uses a community license with a revenue threshold; SDXL uses CreativeML OpenRAIL++-M. Many repos are gated (accept terms on the Hub, `hf auth login`). LoRAs inherit their base model's terms.
- Training data: rights to the images, consent for identifiable people, no trademark or artist-style imitation the user can't justify — `dataset-curation`.

## Running models
- diffusers (PyTorch):
  ```python
  import torch
  from diffusers import DiffusionPipeline
  pipe = DiffusionPipeline.from_pretrained(repo_id, torch_dtype=torch.bfloat16).to("mps")  # "cuda" on NVIDIA
  g = torch.Generator("cpu").manual_seed(0)       # CPU generator: reproducible across devices
  img = pipe(prompt, num_inference_steps=28, guidance_scale=3.5, generator=g).images[0]
  ```
  Swap schedulers via `pipe.scheduler = X.from_config(pipe.scheduler.config)`; LoRA via `pipe.load_lora_weights(path, adapter_name=…)` + `set_adapters` with weights; `enable_model_cpu_offload()`, `vae.enable_tiling()` for memory; `torch.compile(pipe.transformer)` on CUDA for throughput.
- Apple Silicon: MPS works for most pipelines (bf16/fp16 support varies by op — fall back to float32 components if you see NaNs or black images); **mflux** is an MLX-native implementation of FLUX-family and other supported models with quantization (`-q 4`/`-q 8`) and LoRA loading — check its README for the supported model list and CLI flags of the installed version.
- ComfyUI: node workflows; export "API format" JSON and queue it with `POST /prompt` on the local server (`127.0.0.1:8188`), poll `/history/<prompt_id>`. Custom nodes run arbitrary code: review before installing, pin commits, never install from unknown repos on the user's main machine without approval.
- Memory levers: bf16 weights, 8-/4-bit quantization of the transformer and text encoder (bitsandbytes NF4 or torchao on CUDA, GGUF checkpoints via diffusers, MLX quantization in mflux), sequential CPU offload, VAE slicing/tiling, smaller resolution for drafts. Large T5-class text encoders dominate memory — quantize or offload them first.

## Sampling knobs
- Steps: model-specific (distilled "turbo/schnell" models 1–8 steps; base models 20–50). Guidance: classic CFG 3–8 for SD-family; guidance-distilled models (FLUX dev) take a single guidance value (~3–4) and no negative prompt; CFG-free distilled models ignore it. Read the card.
- Samplers/schedulers: flow-matching Euler for rectified-flow models; DPM-Solver++ (2M, Karras sigmas) or Euler/Euler-a for SD-family. Change one knob at a time with fixed seeds.
- Resolution: stay on the model's trained buckets/aspect ratios (e.g. ~1 MP for SDXL/FLUX-class); upscale with a second pass (img2img/tiled) rather than generating far off-distribution.

## Fine-tuning
- Methods: LoRA (rank 8–64; the default), DreamBooth (subject identity, often combined with LoRA), full fine-tune (large data and compute), textual inversion (legacy). Trainers: diffusers example scripts (`examples/dreambooth/train_dreambooth_lora_*.py`, `examples/text_to_image`), and community trainers such as kohya sd-scripts/musubi-tuner, ostris ai-toolkit, SimpleTuner, OneTrainer — follow what the user uses; check each for model support.
- Data: subject LoRA ~15–50 varied images (angles, lighting, backgrounds), style LoRA ~50–300; dedupe; crop to buckets without cutting the subject; captions by a VLM (Florence-2, Qwen-VL-class, JoyCaption) edited by hand, with a rare trigger token and captions describing what should *not* be learned as the concept.
- Starting hyperparameters (LoRA): AdamW lr ~1e-4 (Prodigy with lr 1.0 as an alternative), batch 1–4 with gradient accumulation, 1–3k steps, bf16, gradient checkpointing, cache latents and text embeddings. Save checkpoints every few hundred steps and sample a fixed prompt × seed grid at each.
- Overfitting signs: identical poses/backgrounds, trigger bleeding into unrelated prompts, loss of prompt adherence. Fix with fewer steps, lower rank/lr, more varied data, or prior-preservation images.
- Compute: small LoRAs are feasible on a large-memory Mac (MPS or MLX tooling); big runs and full fine-tunes on the NVIDIA host (cuda-engineer territory for throughput).

## Evaluation
- Fixed prompt set (covering the use case plus a generic set) × ≥ 4 seeds, same sampler settings across compared models; blind side-by-side human review for the final decision.
- Metrics and their limits: FID/KID (clean-fid; ≥ 10k samples, same preprocessing and reference set — tiny sample FIDs are noise), CLIPScore (weak on composition), GenEval / T2I-CompBench / DPG-Bench for prompt adherence, preference models (ImageReward, PickScore, HPS v2) that carry their training biases, VLM-as-judge with the controls in `llm-evals`. Report uncertainty (bootstrap over prompts).
- For LoRAs: identity similarity (face embeddings for consented subjects), style consistency, and prompt adherence with and without the trigger.

## Serving and safety
- Batch by resolution and steps; cache text embeddings; compile on CUDA (torch.compile, TensorRT where supported); queue with timeouts; stream progress.
- Safety: NSFW/safety checkers as the product requires, provenance (C2PA manifests, invisible watermarks) when publishing, likeness and trademark policies, logging of prompts per the user's privacy rules.

## Checklist
License and gating checked · deliverable images still go through image-studio · seeds and settings recorded · memory plan fits the device · training data rights and captions reviewed · fixed-seed sample grids per checkpoint · evaluation with enough samples and stated limits · versions of diffusers/mflux/trainers reported.
