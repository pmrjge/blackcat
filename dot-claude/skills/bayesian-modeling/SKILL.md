---
name: bayesian-modeling
description: Use for Bayesian models — PyMC, NumPyro, Stan; prior checks, R-hat/ESS, divergences, LOO.
---
# Bayesian modeling

## Scope
Probabilistic models fitted by MCMC or variational methods. Frequentist tests and GLMs → `data-analysis`; causal designs → `causal-inference` (Bayesian estimation fits inside them); numerical stability → `numerical-methods`; forecasting protocol → `time-series-forecasting`. Versions (PyPI, 2026-09-29): PyMC 6.3.2 (6.0 May 2026), PyTensor 3.3.2, nutpie 0.16.11, ArviZ 1.3.0 (arviz-base/stats/plots 1.3.x), NumPyro 0.22.0, CmdStanPy 1.3.0.

## Breaking changes models recall wrongly
- **PyMC 6 / PyTensor 3**: default compile backend is **Numba** (was C); `pm.sample(..., backend="numba"|"c"|"jax")`. **nutpie is the default NUTS sampler when installed** (`uv add "pymc[nutpie]"`); `nuts_sampler="nutpie"|"pymc"|"numpyro"|"blackjax"`; `nuts={"adaptation": "low_rank"}` for correlated posteriors. `pymc.dims` (`import pymc.dims as pmd`) adds named-dimension distributions. JAX backend for GPU sampling.
- **ArviZ 1.0**: `InferenceData` is gone → `xarray.DataTree` (`dt["posterior"].dataset`); package split into arviz-base, arviz-stats, arviz-plots (bundled by `arviz`). Defaults: credible interval **0.89 ETI** (was 0.94 HDI) — state the interval you report. **WAIC removed**; PSIS-LOO is the comparison tool. `az.hdi(x, prob=0.95)` (was `hdi_prob`). Plots return `PlotCollection`; renames: `plot_trace` → `plot_trace_dist`/`plot_trace_rank`, `plot_ppc` → `plot_ppc_dist`, `plot_posterior`/`plot_density` → `plot_dist`, `plot_bpv` → `plot_ppc_pit`. Old netCDF/Zarr files still load (`az.from_netcdf`); write with `dt.to_netcdf()`.
- Tutorials older than mid-2026 use the pre-1.0 APIs: check against the installed versions.

## Workflow (Gelman et al., Bayesian workflow)
1. Generative story in words and a DAG; parameters with units.
2. Priors on interpretable scales (standardize predictors); weakly informative, not flat.
3. **Prior predictive check**: `pm.sample_prior_predictive()` — simulated outcomes in a plausible range?
4. Fit on simulated data with known parameters first (parameter recovery), then on real data.
5. Diagnostics (below) → fix the model, not the sampler settings, when they fail.
6. **Posterior predictive check**: `pm.sample_posterior_predictive(idata, extend_inferencedata=True)`; compare distributions and targeted statistics (PIT/LOO-PIT via `plot_ppc_pit`).
7. Compare/expand models with LOO; sensitivity to priors (power-scaling or refits with wider priors).

```python
import pymc as pm, arviz as az
with pm.Model(coords={"group": groups}) as m:
    mu = pm.Normal("mu", 0, 1)
    tau = pm.HalfNormal("tau", 1)
    z = pm.Normal("z", 0, 1, dims="group")
    theta = pm.Deterministic("theta", mu + tau * z, dims="group")          # non-centered
    sigma = pm.HalfNormal("sigma", 1)
    pm.Normal("y", theta[g_idx], sigma, observed=y)
    idata = pm.sample(draws=1000, tune=1000, chains=4, random_seed=1, idata_kwargs={"log_likelihood": True})
az.summary(idata, var_names=["mu", "tau", "sigma"])
```

## Diagnostics — thresholds and fixes
| Check | Target | If it fails |
|---|---|---|
| R-hat (rank-normalized) | ≤ 1.01 | longer chains won't fix multimodality or non-identifiability; reparameterize, add prior information |
| Bulk and tail ESS | ≥ 400 total (≥ 100 per chain) for the quantities you report | more draws, better parameterization |
| Divergences | 0 after tuning | non-centered parameterization, tighter priors on scales, `target_accept` 0.9–0.99 only as a last step |
| Tree depth saturation | rare | rescale predictors, dense/low-rank mass matrix |
| E-BFMI | > 0.3 | heavy tails or funnels: reparameterize |
| MCSE | small vs the precision you report | more draws |

Always 4+ chains from dispersed inits; look at trace/rank plots, not just summaries. Never report results from a run with unresolved divergences.

## Reparameterization cookbook
Non-centered hierarchies (above) when groups have little data; centered when data per group is large. Standardize continuous predictors and use a QR decomposition for correlated ones. Sum-to-zero effects: `pm.ZeroSumNormal`. Positive scales: HalfNormal/Exponential priors; avoid Inverse-Gamma(ε, ε). Correlated effects: LKJ Cholesky (`pm.LKJCholeskyCov`). Ordinal outcomes: ordered cutpoints with `transform=pm.distributions.transforms.ordered`.

## Model comparison
- PSIS-LOO via `az.loo(idata)` and `az.compare({...})` (needs `log_likelihood` stored); Pareto k > 0.7 flags unreliable estimates → moment matching, K-fold CV, or a more robust model. Report elpd differences with their SE; |Δelpd| < ~4 is not a meaningful difference.
- Stacking weights for prediction; don't pick a model on LOO alone when the scientific question needs a specific structure.

## Library choice
- **PyMC 6**: model building in Python, nutpie/Numba sampling, `pymc-extras` (Pathfinder `fit_pathfinder`, DADVI, state-space models, marginalization of discrete parameters).
- **NumPyro** (JAX): fastest for large models and GPU/vectorized chains; `numpyro.infer.MCMC(NUTS(model), num_chains=4, chain_method="vectorized")`; convert with `az.from_numpyro`.
- **Stan via CmdStanPy**: reference implementation, excellent diagnostics; `CmdStanModel(stan_file="m.stan").sample(data=d, chains=4, parallel_chains=4, seed=1)`, `fit.summary()`, `fit.diagnose()`; `az.from_cmdstanpy(fit)`.
- Variational inference (ADVI, Pathfinder) for initialization or very large data; validate against MCMC on a subset before trusting its uncertainty.

## Verify
- Prior predictive outcomes plausible; parameters recovered on simulated data.
- 4+ chains: R-hat ≤ 1.01, bulk and tail ESS ≥ 400, 0 divergences, E-BFMI > 0.3; trace/rank plots inspected.
- Posterior predictive check done; when comparing, LOO Pareto k ≤ 0.7 or handled.
- The interval type is stated (e.g. 89% ETI); versions and seeds recorded.

## Reporting
Model specification (math + priors with justification) · prior and posterior predictive plots · diagnostics table (R-hat, ESS, divergences) · posterior summaries with the interval type and probability stated (e.g. "89% ETI") · decision-relevant quantities computed from draws (P(effect > 0), expected loss) · prior sensitivity · LOO comparison if models were compared · versions and seeds.

Sources (checked 2026-09-29): https://www.pymc.io/blog/pymc_v6_ecosystem_updates.html · https://python.arviz.org/en/latest/user_guide/migration_guide.html · https://mc-stan.org/cmdstanpy/users-guide/hello_world.html · https://pypi.org/project/pymc/ · https://pypi.org/project/numpyro/ · https://pypi.org/project/nutpie/ · Vehtari et al. 2021, rank-normalized R-hat, https://doi.org/10.1214/20-BA1221
