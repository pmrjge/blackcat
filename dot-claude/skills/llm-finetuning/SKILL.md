---
name: llm-finetuning
description: Use to plan or run an LLM fine-tune — LoRA/QLoRA, DPO, chat templates, mlx-lm, PEFT/TRL.
---
# LLM fine-tuning protocol

## 0. Should you fine-tune?
Try prompting, few-shot examples and retrieval first. Fine-tune for: a stable format/style, a narrow skill with many examples, latency/cost (smaller model), or behavior that prompting cannot reach. Write the success metric (see llm-evals) before collecting data.

## 1. Data
- Format with the model's own chat template (from `tokenizer_config.json`/`chat_template`), including system prompts and special tokens exactly as at inference. Mask the loss on prompt tokens unless you intend to train on them.
- Deduplicate; hold out a validation set and a test set (no near-duplicates across them); inspect 20 random formatted examples as decoded text.
- Record dataset source, license, size, token counts and filtering rules.

## 2. Method
- LoRA/QLoRA by default: target attention and MLP projections; rank 8–64; alpha ≈ rank to 2× rank; dropout 0–0.1. QLoRA when memory forces it (base in 4-bit, adapters in higher precision).
- Full fine-tuning only with enough data and memory, and a reason.
- Preference tuning (DPO/ORPO/KTO) needs paired chosen/rejected data of good quality; start from an SFT checkpoint.
- Apple Silicon: mlx-lm's LoRA/fine-tune entry points (check `--help`; config file or flags for rank, layers, learning rate, batch size, iterations, grad checkpointing). CUDA: PEFT + TRL (SFTTrainer/DPOTrainer) or the project's framework, on the CUDA host (driver, CUDA and PyTorch setup: `linux-workstation`).

## 3. Hyperparameters (starting points, then measure)
LR 1e-4–2e-4 for LoRA (1e-5–2e-5 full FT), warmup 3–10%, cosine or linear decay, 1–3 epochs, effective batch 16–64 sequences, max length set from the data's token-length distribution.

## 4. During training
Log train and validation loss; stop when validation loss turns up. Sample generations from fixed prompts every N steps. Watch for catastrophic forgetting on a small general-capability probe.

## 5. After training
- Evaluate base vs fine-tuned on the held-out test set and the general probe with identical settings (llm-evals).
- Merge or fuse adapters only after evaluation; re-run a quick eval on the merged/quantized artifact.
- Save: adapter weights, the exact training config, data manifest, tokenizer/template, eval results, tool versions.

## Verify
- Base vs fine-tuned on the held-out test set and the general probe, identical settings.
- Validation loss and fixed-prompt samples logged; no catastrophic forgetting on the probe.
- Merged or quantized artifact re-evaluated; config, data manifest, template and versions saved.

## Report
Data (size, source, split), method and hyperparameters, curves, before/after table with CIs, sample generations, artifacts and paths, known failure modes.

Related skills: `dataset-curation` (building and cleaning the training set), `llm-evals` (before/after numbers), `local-llm-serving` (serving the result), `hf-hub` (downloads and publishing), `distributed-training` (multi-GPU or multi-node runs).
