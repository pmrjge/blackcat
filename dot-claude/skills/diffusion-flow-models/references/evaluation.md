# Diffusion and flow-matching models: evaluation

Read when evaluating a diffusion or flow model (moved from `diffusion-flow-models` SKILL.md).

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
