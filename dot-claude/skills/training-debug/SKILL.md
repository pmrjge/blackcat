---
name: training-debug
description: Load the moment a training run misbehaves — loss NaN/inf, divergence, no learning, plateaus, overfitting, mixed-precision and quantization overflows, input-pipeline bugs.
---
# Training and numerics debugging

Work from cheapest to most expensive check; change one thing at a time and keep the failing config reproducible.

## 0. Reproduce small
Smallest model/data/steps that still shows the failure, fixed seed, deterministic data order. Save the exact command and config.

## 1. Data first (most bugs live here)
- Look at real batches after the full pipeline: decode tokens back to text, render images with labels, print tensor stats (min/max/mean/std, NaN count, dtype, shape).
- Labels aligned with inputs (shifted-by-one for causal LM, padding and ignore_index masked, class ids in range).
- Normalization applied once, with train statistics. Augmentations not destroying the signal.
- Input pipeline throughput: time the loader alone; a starved accelerator looks like "slow training".

## 2. Sanity ladder
1. Loss at initialization matches theory (e.g. ln(V) for a V-way softmax, ≈ variance of targets for MSE).
2. Overfit one batch to near-zero loss. If it can't, the bug is in model/loss/optimizer wiring, not in data scale.
3. Gradients: every trainable parameter gets a finite, non-zero gradient; check `requires_grad`, frozen layers, detached tensors.
4. Short run with the real schedule: loss decreases, gradient norm stable.

## 3. NaN / inf
- Locate the first non-finite tensor: anomaly detection (`torch.autograd.set_detect_anomaly(True)` for short runs), forward hooks that assert `isfinite`, or bisecting layers.
- Usual causes: LR too high or no warmup; fp16 overflow (use bf16, loss scaling, or keep softmax/norm/loss in fp32); log/exp/sqrt/division without epsilon or clamping; attention logits overflow at long context; bad data rows (inf, huge values); optimizer epsilon too small in low precision.
- Quantized models: a NaN/inf cascade usually starts in a few under-quantized projections (often MLP gate/up projections or attention outputs in specific early layers, or MoE router/gates). Bisect by layer ranges, raise those tensors to higher bits or smaller group size, and re-measure perplexity.

## 4. Divergence and instability
Lower LR / longer warmup, gradient clipping (log the pre-clip norm), check weight decay on norms/biases/embeddings, check β2 and epsilon of Adam-family optimizers at low precision, check loss spikes against specific batches (log batch ids).

## 5. No learning / plateau
LR too low or schedule decays too early; wrong loss for the target; labels mostly ignore_index; dead activations; initialization; too-strong regularization; frozen backbone by mistake. Compare against the reference config's curves.

## 6. Overfitting / generalization gap
More/cleaner data, augmentation, regularization, early stopping on validation, smaller model; confirm no leakage makes validation look better than test.

## 7. Performance
Profile before optimizing (see accelerator-perf): data loading vs compute vs synchronization. Common wins: larger batch with gradient accumulation, fused kernels/compile, pinned memory and more loader workers, avoiding host–device syncs (`.item()`, prints) in the hot loop, MLX `mx.eval` placement.

## Report
Symptom → root cause (with the evidence that proves it) → fix → before/after curves or numbers → what guards against recurrence (assertion, test, config check).

Related skills: `numerical-methods` (precision, overflow, conditioning), `ml-experiment` (runs and comparisons), `gpu-kernel-dev` (a custom kernel is the suspect).
