---
name: model-export
description: Load before exporting a trained model for deployment — torch.export, ONNX (dynamo), ONNX Runtime, Core ML, ExecuTorch, TensorRT, parity checks, packaging.
---
# Model export and packaging

## Scope
Turning a trained PyTorch/sklearn/GBM model into a deployable artifact and proving it matches. LLM weight formats (GGUF, mlx-lm conversion, AWQ/GPTQ) → `local-llm-serving` and `llm-quantization`; HF Hub uploads → `hf-hub`; benchmarking the result → `accelerator-perf`; image-generation pipelines → `image-model-pipelines`. Versions (PyPI, 2026-09-29): torch 2.14.0, onnx 1.23.0, onnxscript 0.7.2, onnxruntime 1.30.0, executorch 1.5.1, coremltools 9.0.

## 1. Pick the target first
| Target | Artifact | When |
|---|---|---|
| ONNX Runtime (CPU/CUDA/CoreML/DirectML EPs) | `.onnx` (+ external data) | portable server/desktop inference, non-Python runtimes |
| TensorRT | engine built from ONNX (or Torch-TensorRT) | lowest latency on NVIDIA; engine tied to GPU arch + TRT version |
| Core ML | `.mlpackage` | Apple apps, ANE/GPU on iPhone/Mac |
| ExecuTorch | `.pte` | on-device PyTorch (iOS, Android, embedded, desktop) with delegates |
| torch.export / AOTInductor | `.pt2` | PyTorch-native C++/Python serving without Python model code |
| safetensors + code | weights file | HF-style serving where the model code ships too |
| sklearn/GBM | native (`.ubj`/`.json` XGBoost, LightGBM `.txt`, CatBoost `.cbm`) or ONNX (skl2onnx, onnxmltools) | tabular serving |

List the target's supported ops, dtypes and dynamic-shape limits before exporting.

## 2. torch.export (the common front end)
```python
model.eval()
batch = torch.export.Dim("batch", min=1, max=64)
ep = torch.export.export(model, (x,), dynamic_shapes={"x": {0: batch}})   # non-strict by default
torch.export.save(ep, "model.pt2")
```
- Graph breaks are errors here: data-dependent Python control flow → `torch.cond`, tensor-to-Python conversions (`.item()`, `.tolist()`) → keep as tensors or mark with `torch._check`; unsupported custom ops need registration (`torch.library`).
- Mark only truly dynamic dims; specialization errors mean the model constrains the dim (read the suggested fix in the error).
- `ep.run_decompositions()` for backends that need core ATen ops.

## 3. ONNX
```python
onnx_program = torch.onnx.export(model, (x,), dynamo=True,                 # default since 2.9
                                 dynamic_shapes={"x": {0: "batch"}},
                                 opset_version=None,                       # recommended opset; pin if the runtime needs it
                                 report=True, verify=True)                 # markdown report; ORT check
onnx_program.save("model.onnx")                                            # external data for > 2 GB
```
- `dynamic_axes` is deprecated (legacy TorchScript exporter, `dynamo=False`). The `fallback` option was removed in 2.11; the exporter tries non-strict then strict `torch.export`.
- Pin `opset_version` to what the deployment runtime supports; `onnx.checker.check_model` and `onnxruntime.InferenceSession(..., providers=["CPUExecutionProvider"])` to load-test.
- Watch for shapes baked in by buffers or `.size()` arithmetic, fp16 overflow in LayerNorm/softmax when converting precision, and ops falling back to CPU in the chosen execution provider (enable ORT verbose logging).

## 4. Core ML (coremltools 9.0)
- Two front ends: `torch.jit.trace` (recommended, stable, faster) or `torch.export` ExportedProgram (beta since coremltools 8; ~70% op coverage). `ct.convert(traced, inputs=[ct.TensorType(shape=x.shape)], minimum_deployment_target=ct.target.macOS26)`; new targets `iOS26`/`macOS26`.
- coremltools 9.0 lists PyTorch 2.7 as tested — convert in an environment pinned to a torch version it supports (warnings about untested versions are real risks), not necessarily your training env.
- `compute_units=ct.ComputeUnit.ALL|CPU_AND_NE|CPU_AND_GPU`; the ANE needs static or enumerated shapes (`ct.EnumeratedShapes`), fp16, supported ops — check in Xcode's Core ML performance report which layers run on the NE.
- Compression via `coremltools.optimize` (palettization, linear quantization, pruning), then re-check accuracy.

## 5. ExecuTorch (1.0 GA Oct 2025; current 1.5.1)
```python
from executorch.exir import to_edge_transform_and_lower
from executorch.backends.xnnpack.partition.xnnpack_partitioner import XnnpackPartitioner
et = to_edge_transform_and_lower(torch.export.export(model, (x,)), partitioner=[XnnpackPartitioner()]).to_executorch()
open("model.pte", "wb").write(et.buffer)
from executorch.runtime import Runtime
out = Runtime.get().load_program("model.pte").load_method("forward").execute([x])
```
- Production backends at 1.0: XNNPACK (CPU), Core ML, Qualcomm AI Engine, Arm Ethos-U, Vulkan; MPS is beta/alpha. **MLX delegate** (`MLXPartitioner`, Apple Silicon GPUs, bf16/fp16 and 2/4/8-bit TorchAO quantization) is **experimental** (announced May 2026).
- Quantize with TorchAO `quantize_` before lowering; HF transformer models via `optimum-executorch`.

## 6. TensorRT (NVIDIA)
Build engines on the deployment GPU (engines are not portable across GPU architectures or TRT major versions): `trtexec --onnx=model.onnx --saveEngine=model.plan --fp16` (or bf16/fp8/int8 with calibration), optimization profiles for dynamic shapes; Torch-TensorRT for staying in PyTorch. Verify parity after every precision change.

## 7. MLX (non-LLM models)
Port the module to `mlx.nn` and convert weights from safetensors; conv weights move from PyTorch NCHW/OIHW to MLX channels-last (`w.transpose(0, 2, 3, 1)` for Conv2d); check `mx.eval` placement and dtype. LLMs: `mlx_lm.convert` (`local-llm-serving`).

## 8. Parity protocol (mandatory)
1. Fixed inputs: a seeded random batch plus ≥ 100 real samples covering edge cases (min/max shapes, empty/padding cases).
2. Compare every output tensor: max abs error, max rel error, and a task metric (top-1 agreement, IoU, WER) between reference (eager fp32, `model.eval()`, `torch.no_grad()`) and exported model.
3. Tolerances by dtype: fp32 ≈ 1e-5 rel; fp16/bf16 ≈ 1e-2–1e-3; int8 judged on the task metric (e.g. ≤ 0.5 pt drop), never on raw tensors alone.
4. Test the dynamic dims you declared (batch 1 and max, varied sequence lengths).
5. Record versions (torch, exporter, runtime, opset/deployment target, hardware) with the result.

## 9. Packaging for deployment
- Artifact + `model_card.md`/metadata: training data version and date range, feature list and preprocessing (tokenizer/normalization identical to training — export it too), metric with CI on the held-out set, seed, git commit, export command, parity report.
- Version artifacts immutably (registry or `name-vX.Y.Z` with checksums); keep the eager checkpoint for re-export.
- sklearn pipelines: export the whole `Pipeline` (preprocessing included) — skl2onnx for ONNX, or `skops` rather than pickle when loading untrusted files. GBMs: native formats are the most faithful; ONNX converters can differ on categorical handling — run parity.
- Serving smoke test: load in a clean environment/container, run the parity inputs, measure p50/p95 latency and memory at the target batch size.

Sources (checked 2026-09-29): https://docs.pytorch.org/docs/2.14/onnx_export.html · https://docs.pytorch.org/docs/stable/export.html · https://pytorch.org/blog/introducing-executorch-1-0 · https://docs.pytorch.org/executorch/stable/getting-started.html · https://pytorch.org/blog/running-pytorch-models-on-apple-silicon-gpus-with-the-executorch-mlx-delegate · https://github.com/apple/coremltools/releases/tag/9.0 · https://apple.github.io/coremltools/docs-guides/source/convert-pytorch-workflow.html · PyPI (versions above)
