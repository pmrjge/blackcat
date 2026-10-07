---
name: llm-quantization
description: Use for LLM quantization — MLX mixed precision, GPTQ/AWQ, sensitivity, memory, perplexity.
---
# LLM quantization protocol

## Principles
- MLX-native first on Apple Silicon: `mlx_lm.convert -q` (`--q-bits`, `--q-group-size`, `--q-mode affine|mxfp4|nvfp4|mxfp8`, `--quant-predicate mixed_*`; the Python `convert(quant_predicate=callable)` takes a per-layer precision map), `mlx_lm.dynamic_quant` (target bits-per-weight from a sensitivity estimate), `mlx_lm.gptq`, `mlx_lm.awq`, `mlx_lm.dwq`. Verify current flags with `--help` and libdocs: the tooling changes between releases.
- Quality is decided by measurement against the unquantized (or FP8/BF16 source) baseline under an identical protocol — never by bits-per-weight alone.
- Streaming and sharding: convert shard by shard when the source does not fit comfortably; write to the output path the user names; report disk space needed before starting.

## 1. Budget
Memory at inference = weights (params × bits/8 × (1 + group-size overhead: scales/biases per group)) + KV cache + activations + runtime overhead. For MoE, all experts must be resident unless the runtime pages them. State the target (e.g. "fits in N GB with 32K context at batch 1") before choosing bits.

## 2. Baseline and protocol (fixed for every candidate)
- Same tokenizer, same dataset split (e.g. wikitext-2-raw-v1 test, or a held-out domain set the user cares about), same context length and stride, same BOS/EOS handling, same number of tokens.
- Record: perplexity (and its delta vs baseline in %), a small task suite when relevant (see llm-evals), generation sanity samples with fixed prompts and greedy decoding, tokens/s and peak memory.

## 3. Sensitivity analysis
- Start uniform (e.g. 4-bit, group size 64) to get a reference point, then find sensitive tensors: per-layer or per-module sweeps (quantize one block at higher/lower bits, measure Δppl), or cheaper proxies (activation outlier statistics, Hessian/Fisher diagonals from a calibration set).
- Usually sensitive: embeddings and lm_head, the first and last few layers, attention output/value projections, MLP down projections, MoE router/gate weights and shared experts. Usually tolerant: most routed-expert MLP weights in the middle layers.
- Encode the result as a per-layer precision map (bits, group size) and keep it in the run folder.

## 4. Techniques (choose by evidence, one at a time)
- Smaller group size or higher bits on sensitive tensors (cheapest, most reliable).
- Rotations (Hadamard / QuaRot / SpinQuant-style) to spread activation outliers before quantizing; verify the rotated model's output matches the original in full precision before quantizing.
- Error-compensating methods (GPTQ-style with a calibration set; AWQ-style activation-aware scaling) and vector/trellis codebook methods (QTIP-style) for very low bits; distillation-based refinement when a teacher fits.
- Calibration data: representative of the target use (chat, code, domain), a few hundred to a few thousand sequences; record its source.

## 5. Failure signatures
- NaN/inf or exploding perplexity → a few tensors under-quantized (bisect by layer range; raise bits / shrink groups there), or a rotation applied inconsistently. Bisection procedure with per-layer statistics: §6.
- Good perplexity, broken generation → chat template/tokenizer mismatch, lost special tokens, wrong RoPE/context settings in the converted config.
- MoE: collapsed routing after quantization → keep router/gate in higher precision.

## 6. Very large MoE models (0.5–1T parameters) on a 512 GB Mac
Read `references/large-moe.md` before quantizing one — memory and disk plan, FP8 block-scaled sources, streaming conversion, expert-level precision maps, rotations, NaN-cascade bisection, codebook and trellis methods.

## Verify
- Every candidate measured under the fixed protocol of §2 (same split, context, stride, token count) against the baseline.
- Perplexity delta, task scores, fixed-prompt greedy samples, tokens/s and peak memory recorded.
- No NaN/inf; generation sane with the right chat template and special tokens.

## 7. Report
```
| recipe | avg bits/weight | size on disk | peak mem | ppl | Δppl % | task scores | tok/s | notes |
|---|---|---|---|---|---|---|---|---|
```
Plus the per-layer precision map, calibration data, exact commands and tool versions, and the environment block (chip, memory, OS, mlx/mlx-lm versions). For large MoE conversions also the source format and dequantization path (FP8 block-scaled, compressed-tensors, bf16), disk used, conversion peak memory and any rotation applied.
