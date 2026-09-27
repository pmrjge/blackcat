---
name: diffusion-flow-models
description: Load before building, training, sampling or evaluating a diffusion, score-based or flow-matching model. Covers VP/VE SDEs, score matching, the probability-flow ODE, DDPM/DDIM, flow matching, rectified flow, OT-CFM, interpolants, parameterizations and loss weighting, schedules, guidance, samplers, latent diffusion, training, evaluation caveats, MLX/PyTorch notes and debugging.
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
| predict | target | recover x̂₀ | loss in x₀ units |
|---|---|---|---|
| ε | ε | (x_t − σ_t ε̂)/α_t | ‖ε−ε̂‖² = SNR·‖x₀−x̂₀‖² |
| x₀ | x₀ | direct | ‖x₀−x̂₀‖² |
| v (VP, α²+σ²=1; Salimans & Ho 2202.00512) | α_t ε − σ_t x₀ | α_t x_t − σ_t v̂ (and ε̂ = σ_t x_t + α_t v̂) | (1+SNR)·‖x₀−x̂₀‖² |
| EDM denoiser D = c_skip x + c_out F_θ(c_in x; c_noise) | x₀ | direct | λ(σ)c_out² = 1 on F_θ |

- ε-prediction cannot represent zero terminal SNR (α_T = 0 makes x̂₀ undefined). Use v or x₀ there.
- Only the product "sampling density of t × weight" affects the expected loss, but the gradient
  variance differs between choices. Monotone weightings equal the ELBO under noise augmentation
  (Kingma & Gao 2303.00848; Kingma et al., VDM 2107.00630).
- Min-SNR-γ (Hang et al. 2303.09556): x₀-space weight min(SNR, γ), with γ = 5 by default. That is
  min(SNR, γ)/SNR for ε-prediction and min(SNR, γ)/(SNR+1) for v-prediction.
- EDM (Karras et al. 2206.00364):
  - σ_data = 0.5; c_skip = σ_d²/(σ²+σ_d²); c_out = σσ_d/√(σ²+σ_d²); c_in = 1/√(σ²+σ_d²);
    c_noise = ¼ln σ.
  - Train with ln σ ~ N(−1.2, 1.2²) and λ(σ) = (σ²+σ_d²)/(σσ_d)².
  - Sample with σ_i = (σ_max^{1/ρ} + i/(N−1)·(σ_min^{1/ρ} − σ_max^{1/ρ}))^ρ, ρ = 7, σ ∈ [0.002, 80], and
    Heun steps.
- Rectified-flow timestep sampling (SD3, Esser et al. 2403.03206): logit-normal t = sigmoid(u), u ~ N(0,1)
  ranked best among the variants tested. At higher resolution shift toward noise with
  t ↦ αt/(1+(α−1)t), α = √(m/n) for pixel counts m vs n (t = 1 is noise).

## 3. Flow matching, rectified flow, interpolants
This section uses Lipman's convention: noise z at t = 0, data x₁ at t = 1.
- Conditional flow matching (Lipman et al. 2210.02747): pick a conditional path x_t | x₁ with a known
  velocity u_t(x|x₁) and minimize E‖v_θ(x_t, t) − u_t(x_t|x₁)‖². The minimizer is the marginal
  velocity; sample by integrating the ODE from noise to data.
- Rectified flow (Liu et al. 2209.03003): x_t = (1−t)z + t x₁ with target x₁ − z. "Reflow" retrains on
  the model's own (noise, sample) pairs to straighten paths for few-step sampling.
- OT-CFM (Tong et al. 2302.00482): pair noise and data within a minibatch by exact or entropic OT
  before building paths. This gives straighter paths and lower-variance targets.
- Stochastic interpolants (Albergo & Vanden-Eijnden 2209.15571; Albergo, Boffi & Vanden-Eijnden
  2303.08797): for x₀ ~ ρ₀ and x₁ ~ ρ₁ (any two distributions), x_t = α(t)x₀ + β(t)x₁ + γ(t)z with
  γ(0) = γ(1) = 0. This unifies flows and diffusions.
- One ODE, many parameterizations. For Gaussian paths x_t = α_t x_data + σ_t ε:
  v(x,t) = (α̇/α)x + (σ̇ − σα̇/α)ε̂, with ε̂ = E[ε|x_t = x] = −σ∇log p_t.
  - Rectified flow (α = t, σ = 1−t) gives v = (x − ε̂)/t.
  - Convert between parameterizations instead of retraining.
  - Reference code and conventions: Lipman et al., "Flow Matching Guide and Code" 2412.06264.

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
- DDPM ancestral: stochastic, needs hundreds of steps.
- DDIM (Song, Meng & Ermon 2010.02502):
  x_{t−1} = √ᾱ_{t−1} x̂₀ + √(1−ᾱ_{t−1}−σ_t²) ε̂ + σ_t z,
  σ_t = η√((1−ᾱ_{t−1})/(1−ᾱ_t))·√(1−ᾱ_t/ᾱ_{t−1}).
  η = 0 is deterministic (a PF-ODE discretization); η = 1 is close to DDPM.
- ODE solvers:
  - Euler; Heun (2nd order, as in EDM);
  - DPM-Solver and DPM-Solver++ (Lu et al. 2206.00927, 2211.01095): exponential integrators in λ. The
    multistep "2M" is the usual default, and the data-prediction "++" variant is the one to use with
    guidance, which the paper reports gives high-quality guided samples in 15–20 steps;
  - UniPC (Zhao et al. 2302.04867).
  - Measure quality against NFE for your model; do not copy step counts from elsewhere.
- Stochastic samplers (EDM churn, SDE solvers) correct accumulated error but need more steps and
  tuning.
- Few-step sampling: progressive distillation (2202.00512), consistency models (Song et al.
  2303.01469), reflow.
- diffusers (0.40) schedulers:
  - `DDPMScheduler`, `DDIMScheduler`, `EulerDiscreteScheduler`, `HeunDiscreteScheduler`,
    `UniPCMultistepScheduler`, `FlowMatchEulerDiscreteScheduler`, `FlowMatchHeunDiscreteScheduler`,
    `EDMEulerScheduler`, `EDMDPMSolverMultistepScheduler`, `LCMScheduler`.
  - `DPMSolverMultistepScheduler` takes `algorithm_type="dpmsolver++"|"sde-dpmsolver++"`,
    `use_karras_sigmas`, `timestep_spacing="linspace"|"leading"|"trailing"`, `rescale_betas_zero_snr`
    and `prediction_type="epsilon"|"sample"|"v_prediction"|"flow_prediction"`.
  - Swap schedulers with `NewScheduler.from_config(pipe.scheduler.config)`. `prediction_type` must match
    how the model was trained.

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
- FID (Heusel et al. 1706.08500): Fréchet distance of Inception-v3 2048-d pool features, usually
  generated vs reference at 50k samples.
  - Biased at small N: compare only at equal N, the same reference set and the same implementation.
  - Sensitive to resizing and compression (clean-fid, Parmar et al. 2104.11222).
  - Can be gamed by matching ImageNet classes (Kynkäänniemi et al. 2203.06026).
- KID (Bińkowski et al. 1801.01401): unbiased, so usable at small N; report mean ± std over subsets.
- Precision/recall (Kynkäänniemi et al. 1904.06991): fidelity and coverage separately (k-NN manifolds).
- Alternative features: FD-DINOv2 (Stein et al. 2306.04675); CMMD with CLIP embeddings (Jayasumana et
  al. 2401.09603).
- Text-to-image: CLIPScore (Hessel et al. 2104.08718) measures alignment under one CLIP model. It
  saturates and rewards rendered keywords; it is not an image-quality metric. Back claims with human
  preference studies.
- torchmetrics (needs `torch-fidelity` for FID/KID):
  - `torchmetrics.image.fid.FrechetInceptionDistance(feature=2048, normalize=False)` expects uint8
    images in [0, 255]; `normalize=True` takes floats in [0, 1].
  - Also `torchmetrics.image.kid.KernelInceptionDistance` and
    `torchmetrics.multimodal.clip_score.CLIPScore`.
- Toy 2-D sanity suite, run before any large job:
  - Data: 8 Gaussians, two moons, checkerboard.
  - Model: MLP with a sinusoidal time embedding.
  - Checks:
    - every mode covered with the right mass;
    - no bridges between modes;
    - quality vs NFE curve;
    - PF-ODE round trip x → z → x;
    - the learned score vs the closed-form score of a Gaussian mixture;
    - MMD or sliced Wasserstein to the ground truth.

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
| run-to-run differences | nondeterministic kernels; per-sample seeds not fixed | `numerical-methods` §10 |

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
