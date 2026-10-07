# Diffusion and flow-matching models: implementation

Read when implementing a model or training loop (moved from `diffusion-flow-models` SKILL.md).

## 10. Implementation notes
- Converters: write ε ↔ x₀ ↔ v ↔ score ↔ velocity as tested pure functions (round-trip to 1e-6 in fp32
  on random tensors). Write samplers as pure functions of (model, schedule, x_T, seed).
- PyTorch (CUDA, MPS):
  - `torch.nn.functional.scaled_dot_product_attention`; `torch.compile` for the denoiser;
    channels-last for convnets; bf16 on Ampere or newer.
  - On the 12 GB RTX 5070 Ti laptop GPU, latent models at 512–1024 px need bf16, gradient
    checkpointing, and small batches with accumulation. Measure with
    `torch.cuda.max_memory_allocated()`.
  - MPS has no float64.
- MLX (Apple Silicon):
  - Structure: `nn.value_and_grad(model, loss_fn)`, `mx.compile` the step, then
    `mx.eval(model.parameters(), optimizer.state)` every step (lazy graphs otherwise grow).
  - `mx.random.key`/`split` for reproducible noise. float64 is CPU-only.
  - Unified memory allows large batches.
  - Inference references: `ml-explore/mlx-examples` `stable_diffusion` (SDXL-Turbo, SD 2.1) and mflux
    (MLX ports of recent image models).
