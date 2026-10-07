# Diffusion and flow-matching models: parameterizations flows

Read when choosing a parameterization, loss weighting or flow-matching formulation (moved from `diffusion-flow-models` SKILL.md).

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
