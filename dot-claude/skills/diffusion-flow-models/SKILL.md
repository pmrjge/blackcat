---
name: diffusion-flow-models
description: Load before building, training, sampling or evaluating a diffusion or flow-matching model — SDEs, DDPM/DDIM, rectified flow, guidance.
---
# Diffusion and flow-matching models

## Scope
- Covers: theory, training, sampling, evaluation and debugging of diffusion, score-based and
  flow-matching models (pixels, latents, toy data, other modalities).
- Elsewhere: experiment protocol in `ml-experiment`; broken runs in `training-debug`; floating-point
  limits in `numerical-methods`; downloading weights and checking licenses in `hf-hub`; speed and memory
  claims in `accelerator-perf`.
- Notation: data x₀, noise ε ~ N(0, I), x_t = α_t x₀ + σ_t ε, SNR = α²/σ², λ = log SNR.
- Direction warning: flow-matching papers often put noise at t = 0 and data at t = 1 (Lipman; rectified
  flow), while SD3 puts data at t = 0 and noise at t = 1. State the convention in code and in reports.
- Every arXiv ID below was checked against arxiv.org (Sept 2026). Library names were checked against
  diffusers 0.40, torchmetrics 1.9 and MLX 0.32.

## 1. Forward processes and the reverse picture
- VP SDE: dx = −½β(t)x dt + √β(t) dW, so α_t = exp(−½∫₀ᵗβ) and σ_t² = 1 − α_t². DDPM's
  ᾱ_t = ∏(1−β_s) is its discretization, with α_t = √ᾱ_t.
- VE SDE: dx = √(dσ²/dt) dW, so x_t = x₀ + σ_t ε. This is NCSN and EDM's σ-parameterization.
- References: Sohl-Dickstein et al. 1503.03585; Song & Ermon 1907.05600; Ho et al. (DDPM) 2006.11239;
  Song et al. (SDE framework) 2011.13456.
- For dx = f(t)x dt + g(t) dW:
  - reverse SDE (Anderson): dx = [f x − g²∇log p_t] dt + g dW̄, with time running backward;
  - probability-flow ODE: dx/dt = v = f x − ½g²∇log p_t. It has the same marginals, is deterministic
    and invertible, and gives exact likelihoods: log p₀(x₀) = log p_T(x_T) + ∫₀ᵀ tr ∂v/∂x dt. The trace
    is usually estimated with Hutchinson's estimator.
- Denoising score matching (Vincent 2011): ∇log p(x_t|x₀) = −ε/σ_t, so E‖s_θ + ε/σ_t‖² has the
  explicit-score minimizer, and s_θ = −ε_θ/σ_t.
- Tweedie: E[x₀|x_t] = (x_t + σ_t²∇log p_t(x_t))/α_t. A denoiser, a score model and an ε-model
  carry the same information.

## 2. Parameterizations and loss weighting
Read `references/parameterizations-flows.md` when choosing a parameterization, loss weighting or flow-matching formulation.

## 3. Flow matching, rectified flow, interpolants
Read `references/parameterizations-flows.md` when choosing a parameterization, loss weighting or flow-matching formulation.

## 4. Noise schedules
- DDPM: linear β from 1e-4 to 0.02 with T = 1000.
- Cosine (Nichol & Dhariwal 2102.09672): ᾱ(t) = f(t)/f(0), f(t) = cos²(((t/T)+s)/(1+s)·π/2),
  s = 0.008, β clipped at 0.999.
- Reason in λ = log SNR. What matters is which λ the model sees in training and how sampling
  discretizes λ.
- Zero terminal SNR (Lin et al. 2305.08891): common schedules leave ᾱ_T > 0, so training never sees pure
  noise but sampling starts from it, giving a brightness bias. Fix it with a schedule rescaled to
  ᾱ_T = 0, v-prediction, "trailing" timestep spacing and CFG rescale.
- High resolution needs more noise: shift the schedule (Hoogeboom et al., "simple diffusion"
  2301.11093; SD3's shift above).
- Latents: scale to about unit variance using the VAE's config `scaling_factor` (0.18215 for SD 1.x),
  plus `shift_factor` if the config has one.

## 5. Samplers
Read `references/samplers.md` when choosing or implementing a sampler.

## 6. Guidance and conditioning
- Classifier guidance (Dhariwal & Nichol 2105.05233) adds s·∇log p_φ(y|x_t) and needs a
  noise-aware classifier.
- Classifier-free guidance (Ho & Salimans 2207.12598):
  - Train with the condition dropped to ∅ with probability ≈ 0.1–0.2.
  - Sample with ε̃ = ε(x,∅) + w(ε(x,c) − ε(x,∅)), where w = 1 means no guidance. The paper writes
    (1+w)ε_c − wε_∅, so state which convention you use.
  - Costs two evaluations per step (batch them).
- High w gives oversaturation, low diversity and artifacts. Remedies:
  - CFG rescale (Lin et al. 2305.08891);
  - guidance only in a middle noise interval (Kynkäänniemi et al. 2404.07724);
  - APG (Sadat et al. 2410.02416);
  - autoguidance with a weaker model (Karras et al. 2406.02507).
- Conditioning mechanisms:
  - class embedding added to the time embedding;
  - adaptive LayerNorm (AdaLN-Zero in DiT, Peebles & Xie 2212.09748);
  - cross-attention to text tokens (latent diffusion, Rombach et al. 2112.10752);
  - channel concatenation for inpainting and super-resolution.

## 7. Latent diffusion
- Train or reuse an autoencoder (KL-regularized, usually 8× downsampling), run diffusion on its scaled
  latents, and decode with the same VAE.
- Never mix VAEs and backbones from different model families: the latent statistics differ.
- Evaluate the autoencoder alone (reconstruction PSNR/LPIPS). It caps achievable quality and is a
  frequent hidden cause of bad FID.

## 8. Training practice
- EMA weights for sampling (decay 0.999–0.9999 depending on run length); EDM2 (2312.02696) adds
  post-hoc EMA reconstruction.
  - PyTorch, with `get_ema_multi_avg_fn` from `torch.optim.swa_utils`:
    `AveragedModel(model, multi_avg_fn=get_ema_multi_avg_fn(0.9999), use_buffers=True)`.
  - diffusers: `diffusers.training_utils.EMAModel`.
  - Sample and evaluate with the EMA weights.
- Mixed precision: bf16 autocast, but keep these in fp32:
  - timestep and noise-level embeddings (sinusoids of large arguments);
  - schedule tables (compute in fp64, then cast);
  - loss reduction and normalization statistics.

  fp16 needs loss scaling and can still overflow in attention.
- Optimization: warmup; clip gradients and log the pre-clip norm. The loss is noisy and only weakly
  tied to sample quality, so log loss per noise-level bucket.
- Logging:
  - Fixed seeds and fixed classes or prompts; sample grids every N steps with EMA weights and a fixed
    sampler and step count.
  - Trend FID/KID on a fixed 5–10k subset. It is not comparable to 50k FID.
- Data: scale to [−1, 1]; flip only if semantics allow; deduplicate (duplicates cause memorization).
  Train only on data and weights whose licenses permit it (model cards via `hf-hub`). Released
  generators need content-safety filtering and should not reproduce identifiable people or trademarks.

## 9. Evaluation
Read `references/evaluation.md` when evaluating a diffusion or flow model.

## 10. Implementation notes
Read `references/implementation.md` when implementing a model or training loop.

## 11. Debugging
| symptom | likely cause | check or fix |
|---|---|---|
| NaN/inf loss | fp16 overflow; dividing by α or σ near 0 (ε→x₀ at t≈T, v near σ≈0); log of σ = 0; LR too high | clamp the t range; conversions in fp32; bf16; `training-debug` |
| pure noise or blur | parameterization mismatch (ε vs v vs x₀); schedule reversed; timestep off by one (0…T−1 vs 1…T); missing latent scaling | toy-mixture test; compare against a 1000-step DDPM sampler |
| washed out, cannot make very dark or bright images | nonzero terminal SNR; "leading" spacing | zero terminal SNR + v-prediction + trailing spacing |
| oversaturated, harsh contrast | CFG scale too high | lower w, CFG rescale, interval guidance, APG |
| low diversity, mode collapse | high guidance; stale EMA; duplicated data; distillation artifacts | recall metric; many seeds on one prompt; dedupe |
| good loss, bad samples | weighting mismatched to where the sampler spends steps; raw weights instead of EMA; too few NFE | per-λ loss; more steps; EMA weights |
| grid or checkerboard artifacts | decoder or upsampler; wrong latent scale | reconstruct through the VAE alone |
| run-to-run differences | nondeterministic kernels; per-sample seeds not fixed | `numerical-methods` `references/reproducibility.md` |

## Verify
- Converters and schedules unit-tested; toy-mixture score and modes correct; quality vs NFE saturates.
- Metrics state their implementation, N, reference set and resolution. Comparisons use the same seeds,
  sampler, steps and guidance (see `ml-experiment` for the ablation protocol).

## Report
- Model: parameterization, schedule, conditioning, size.
- Training: data and license, steps, batch, LR, EMA, precision.
- Sampler: type, steps or NFE, guidance scale and its convention.
- Metrics: name, implementation, N, reference set, resolution, mean ± std.
- Sample grids with their seeds; compute used; deviations from the reference papers.
