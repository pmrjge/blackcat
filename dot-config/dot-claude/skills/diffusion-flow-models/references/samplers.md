# Diffusion and flow-matching models: samplers

Read when choosing or implementing a sampler (moved from `diffusion-flow-models` SKILL.md).

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
