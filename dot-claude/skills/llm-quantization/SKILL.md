---
name: llm-quantization
description: Use for LLM quantization recipes — MLX mixed precision, GPTQ/AWQ, sensitivity, memory, perplexity.
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
Facts below were checked against mlx 0.32 and mlx-lm at its September 2026 main branch; re-check the named files in the installed version.

**Memory and disk plan**
- Count routed-expert parameters separately: MoE layers × experts × 3 × hidden × expert_ffn. DeepSeek-V3 (61 layers, first 3 dense, 256 experts, 7168 × 2048) → 58 × 256 × 3 × 7168 × 2048 ≈ 654B of ~671B: ~97% of the weights are routed experts, so their bit width sets the size, and attention, shared experts, dense layers, embeddings and lm_head can stay at 6–8 bits for a few percent more. Kimi-K2-class (60 MoE layers × 384 experts, same dims) ≈ 1.01T routed.
- Bytes = Σ params × bpw / 8 with affine bpw = bits + 32/group (4-bit g64 = 4.5, 3-bit g64 = 3.5, 2-bit g64 = 2.5; `mxfp4` 4.25):

| routed params | 4.5 bpw | 3.5 bpw | 2.5 bpw |
|---|---|---|---|
| 654B (DeepSeek-V3 class) | 368 GB | 286 GB | 204 GB |
| 1.01T (Kimi-K2 class) | 571 GB | 444 GB | 317 GB |

- The GPU working set is bounded by the wired limit (`mx.device_info()["max_recommended_working_set_size"]`; raise with `sudo sysctl iogpu.wired_limit_mb=N`, below physical RAM, reset at reboot) and must also hold KV cache, activations and macOS. A 1T-class model needs ~3-bit routed experts (or a 3/4-bit split) on 512 GB; uniform 4-bit does not fit. MLA KV cache is (kv_lora_rank + rope_dim) × layers × 2 bytes per token (~70 KB for DeepSeek-V3) when the runtime caches the latent — measure at two context lengths to confirm.
- Disk: the FP8 source is ~1 byte/param (DeepSeek-V3 688.6 GB, Kimi K2 1029 GB of safetensors) plus the output plus headroom. `mlx_lm.convert` writes no bf16 intermediate; a manual dequantization pass writes 2 bytes/param unless done shard by shard with cleanup. State the total before starting.

**FP8 block-scaled sources**
- DeepSeek-style FP8 (`quantization_config`: `quant_method: fp8`, `fmt: e4m3`, `weight_block_size: [128, 128]`, companion `*.weight_scale_inv` tensors) is dequantized to bf16 inside the model's `sanitize()` at load, for architectures that implement it — at the checked commit `deepseek_v3` (also used for `kimi_k2`), `deepseek_v32`, `minimax`, `minimax_m3_vl`, `mistral4`, `ministral3`, `mimo_v2_flash` (`grep -l weight_scale_inv mlx_lm/models/*.py`). `mlx_lm.convert --hf-path <src> --mlx-path <dst> -q …` then re-quantizes lazily.
- MLX reads `F8_E4M3` (and `F8_E8M0`) safetensors as uint8; `mx.from_fp8(w, dtype=mx.bfloat16)` decodes e4m3; `F8_E5M2` tensors cannot be loaded.
- compressed-tensors FP8 (`format: float-quantized`) is rejected ("dequantize to bf16 before converting"); packed INT4/NVFP4/MXFP4 compressed-tensors checkpoints load as MLX quantized weights — keep a QAT INT4 release as is rather than dequantize-and-requantize (double rounding).
- Manual path for other architectures: per source shard, `d = mx.load(shard)`; for each `X.weight` with `X.weight_scale_inv`, apply the 128×128 block dequantization (copy `dequant()` from `mlx_lm/models/deepseek_v3.py`: pad to block multiples, multiply by the broadcast scales, crop), drop the scale tensors, `mx.save_safetensors(out, d)`; rewrite `model.safetensors.index.json` and remove `quantization_config` from `config.json`. Check a few tensors against the publisher's reference dequantization first.
- The baseline for Δppl is the FP8 model as published, not an imagined bf16 original.

**Streaming conversion**
- `mlx_lm.convert` loads lazily and `save_model` materializes one ≤ 5 GB output shard at a time, freeing it after writing (`donate_model`), so peak memory tracks the per-shard graph (its source tensors plus `sanitize` work such as FP8 dequantization and expert stacking), not the model size. Measure on the first run: call `convert()` from Python after `mx.reset_peak_memory()` and print `mx.get_peak_memory()`. The output directory must not exist.
- Methods that need activations (GPTQ-style, calibration sweeps) on models that do not fit twice: go layer by layer — load one layer's weights lazily, compute, write, free its parameters (`layer.update(tree_map(lambda _: mx.array([]), layer.parameters()))`, as `save_model` does) — and keep the index current.

**Expert-level precision maps**
- mlx-lm stacks all routed experts of a layer into one module per projection (`mlp.switch_mlp.{gate,up,down}_proj`, `SwitchGLU`): precision varies per layer and per projection, not per expert (that needs a custom module). Shared experts (`mlp.shared_experts.*`) and attention are separate modules.
- `quant_predicate(path, module) -> bool | dict` (`{"bits", "group_size", "mode"}`; modules whose input dim is not divisible by the group size are skipped). A custom predicate replaces the model's own `quant_predicate`, which in many MoE files keeps the router at 8 bits (e.g. `minimax`, `bailing_moe`, `step3p5`) — re-implement those rules. DeepSeek-V3's `MoEGate` has no `to_quantized` and stays unquantized. The type hint on `convert()` still shows an older three-argument form while `quantize_model` calls it with two — read `quantize_model` in the installed `mlx_lm/utils.py` before relying on either.
```python
from mlx_lm import convert
def predicate(path, module):
    if (path.endswith("mlp.gate") or "shared_experts" in path or "self_attn" in path
            or "embed_tokens" in path or path.endswith("lm_head")):
        return {"bits": 8, "group_size": 64, "mode": "affine"}
    if "switch_mlp.down_proj" in path:
        return {"bits": 4, "group_size": 64, "mode": "affine"}
    if "switch_mlp" in path:
        return {"bits": 3, "group_size": 64, "mode": "affine"}
    return {"bits": 6, "group_size": 64, "mode": "affine"}   # dense layers and anything else
convert("<src>", mlx_path="<dst>", quantize=True, q_group_size=64, q_bits=4, quant_predicate=predicate)
```
  Start there (routed `down_proj` a step above `gate/up`, extra bits in the first and last MoE layers), then move bits by measured sensitivity (`mlx_lm.dynamic_quant` or a per-layer Δppl sweep).

**Rotations: offline vs online**
- Foldable offline (the checkpoint stays a stock architecture): the residual-stream rotation (QuaRot/SpinQuant R1) — fold RMSNorm scales into the following linear layers, then rotate embeddings, every residual-reading input (attention or MLA down-projections, router gate, expert and shared-expert gate/up) by Qᵀ and every residual-writing output (o_proj, all down_proj) and lm_head by Q; routing is invariant in exact arithmetic. Per-head V/O rotation (R2) folds offline where V and O are plain per-head projections (check MLA's structure first). LayerNorm with mean-centering, post-norms or sandwich norms break simple folding.
- Online at runtime: a Hadamard before `down_proj` (after the SwiGLU nonlinearity; R4) and Q/K Hadamards after RoPE (R3, only for KV-cache quantization).
- MLX: `mx.hadamard_transform(x, scale=None)` exists for sizes m·2ᵏ with m ∈ {1, 12, 20, 28} and 2ᵏ ≤ 8192 (fp32) / 16384 (fp16/bf16) — 7168 = 28·256 works, 18432 does not (in a CPU test the unsupported size crashed the process instead of raising; check the factorization, or use block-diagonal Hadamards). No stock mlx-lm model applies online rotations, so R3/R4 checkpoints need a custom model class and will not run in stock mlx-lm, LM Studio or oMLX. Prefer offline-foldable rotations for shareable checkpoints; verify invariance in full precision before quantizing (§4).

**NaN-cascade bisection**
1. Check the source first: dequantized tensors are finite with plausible max |w| and per-tensor scale comparable to neighbouring layers (a misapplied or misaligned `weight_scale_inv` shows up as magnitudes orders off).
2. Capture per-layer statistics — MLX has no hooks, so wrap the decoder layers:
```python
import mlx.core as mx
stats = []
class Probe:
    def __init__(self, inner, i): self.inner, self.i = inner, i
    def __getattr__(self, name): return getattr(self.inner, name)
    def __call__(self, x, *args, **kwargs):
        y = self.inner(x, *args, **kwargs)
        h = (y[0] if isinstance(y, tuple) else y).astype(mx.float32)
        stats.append((self.i, mx.isnan(h).sum().item(), mx.isinf(h).sum().item(),
                      mx.abs(h).max().item(), mx.sqrt(mx.mean(h * h)).item()))
        return y
layers = model.model.layers            # attribute path per model file
for i in range(len(layers)):
    layers[i] = Probe(layers[i], i)
model(mx.array([tokenizer.encode(prompt)]))
```
3. The first layer with NaN/inf, or whose max |h| jumps by orders of magnitude relative to its neighbours, is the suspect; wrap its `self_attn`, `mlp.switch_mlp` and `mlp.shared_experts` the same way to find the module.
4. Local error: run the suspect layer's captured input through the quantized layer and a source-precision copy of that layer alone (loaded from the source shards) and compare relative error — this separates the layer's own error from upstream drift and works when the full reference model does not fit.
5. Fix at the smallest scope (more bits or smaller groups for that module and layer range, router in high precision, `--dtype bfloat16` instead of float16 when activations exceed ±65504), then rerun the probe and the perplexity protocol.

**Codebook and trellis methods (QTIP-, AQLM-, QuIP#-style)**
- They beat affine mainly at ≤ 3 bpw, and only with a fused kernel that reads the compressed weights and dequantizes in registers inside the matmul. Batch-1 decode is bandwidth-bound (tok/s ≈ 819 GB/s ÷ active bytes per token on the M3 Ultra); dequantizing to bf16 before the matmul reads more bytes than the affine baseline and forfeits the gain.
- Stock MLX has quantized-matmul kernels only for affine, mxfp4, nvfp4 and mxfp8; a codebook format needs a custom kernel (`mx.fast.metal_kernel`; see `gpu-kernel-dev`) and a custom model/loader, and other MLX tools cannot run the result.
- Worth it when affine mixed precision cannot reach acceptable quality at the size that fits (e.g. 1T-class at ≤ 3 bpw) and you can maintain the kernel. Decide on equal bpw budgets: perplexity/task scores vs affine mixed precision, plus decode and prefill tok/s against the bandwidth ceiling.

## 7. Report
```
| recipe | avg bits/weight | size on disk | peak mem | ppl | Δppl % | task scores | tok/s | notes |
|---|---|---|---|---|---|---|---|---|
```
Plus the per-layer precision map, calibration data, exact commands and tool versions, and the environment block (chip, memory, OS, mlx/mlx-lm versions). For large MoE conversions also the source format and dequantization path (FP8 block-scaled, compressed-tensors, bf16), disk used, conversion peak memory and any rotation applied.
