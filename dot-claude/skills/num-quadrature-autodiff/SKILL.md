---
name: num-quadrature-autodiff
description: Use when integrating numerically or computing derivatives — adaptive quad, tanh-sinh, QMC, autodiff modes, finite-difference steps.
---
# Quadrature and derivatives
Hub: `numerical-methods` (conditioning §3, verification §9; reproducibility in `numerical-methods` `references/reproducibility.md`). Environments: `__CLAUDE_DIR__/venvs/sci/bin/python`, `__CLAUDE_DIR__/venvs/ml/bin/python`. Version-specific API notes were checked in Sept 2026 without recorded URLs (unverified as of 2026-10-02); latest releases are Verified in the hub.


## Quadrature
- 1-D: `scipy.integrate.quad(f, a, b, epsabs=1.49e-8, epsrel=1.49e-8, limit=50)` returns (value,
  abserr).
  - Put kinks and singularities in `points=`; use `weight='alg'|'alg-loga'|'cauchy'|'sin'|'cos'` for
    special integrands; infinite limits are allowed.
  - `quad_vec` for vector-valued integrands.
- Newer SciPy (≥ 1.15): `tanhsinh` (vectorized, handles endpoint singularities) and `cubature`
  (adaptive, multidimensional). `romberg` and `quadrature` were removed in 1.15.
- Sampled data: `scipy.integrate.trapezoid`/`simpson` (`np.trapz` is gone; use `np.trapezoid`).
  Gauss nodes: `numpy.polynomial.legendre.leggauss`, `scipy.special.roots_legendre`.
- Special cases: periodic analytic integrands converge exponentially under the trapezoid rule. High
  dimensions: (quasi-)Monte Carlo, e.g. scrambled `scipy.stats.qmc.Sobol` with n a power of two, and
  error bars from independent scramblings.
- Arbitrary precision: `mpmath.quad` (tanh-sinh by default, or `method='gauss-legendre'`);
  `mpmath.quadosc` for oscillatory tails.
- Never trust `abserr` alone: re-check with another method or a refined subdivision, and confirm
  integrability first.

## Derivatives: autodiff vs finite differences
- Prefer autodiff:
  - PyTorch: `torch.func.grad/jacrev/jacfwd/hessian/vmap`, `torch.autograd.grad`.
  - MLX: `mx.grad`, `mx.value_and_grad`, `mx.vjp`, `mx.jvp`, `mx.vmap`.
  - Use reverse mode for scalar outputs with many inputs, forward mode for few inputs.
- Finite differences in fp64:
  - forward: h = √ε·max(1,|x|), error ~1e-8;
  - central: h = ε^{1/3}·max(1,|x|), error ~1e-11;
  - make h representable (`h = (x + h) - x`).
  - Demo: central differences reach relative error 1.4e-10 at h = 1e-6 but 2e-7 at h = 1e-10
    (roundoff).
- Complex step: f′(x) ≈ Im f(x+ih)/h with h = 1e-20 has no cancellation (the demo error was 0 to
  machine precision). It needs a real-analytic f written with complex-safe ops: no `abs`, `max`, value
  branches or `conj`.
- `scipy.differentiate.derivative`/`jacobian`/`hessian` (SciPy ≥ 1.15) are adaptive, with error
  estimates.
- Gradient checks: `torch.autograd.gradcheck` in float64 (float32 fails spuriously); `check_grad`;
  complex step; `mpmath.diff`.
- AD pitfalls:
  - Non-differentiable points: relu at 0, `abs`, `max`, `sqrt` at 0.
  - `where` with NaN or inf in the unselected branch still poisons the gradient: sanitize the input,
    not only the output.
  - In-place ops, and custom kernels without a backward.

## Verify
- [ ] Integrals re-checked with a second method or refined subdivision; integrability confirmed; `abserr` not trusted alone.
- [ ] Gradients checked in float64 (`gradcheck`, `check_grad`, complex step or `mpmath.diff`).
- [ ] Finite-difference step chosen by the rules above and made representable.
- [ ] QMC error bars from independent scramblings with n a power of two.
