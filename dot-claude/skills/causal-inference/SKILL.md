---
name: causal-inference
description: Use to estimate causal effects from observational data — DiD, event studies, IV, RD, synthetic control.
---
# Causal inference

## Scope
Designs and estimators for causal claims without (or around) randomization. Randomized A/B tests, power and general testing → `data-analysis`; ML-model comparisons → `ml-experiment`; Bayesian versions → `bayesian-modeling`; uplift/treatment-effect models built with GBMs → `tabular-ml` for the learners. Without a design from this skill, write "associated with".

## 0. Before any estimate
1. **Estimand**: ATE, ATT, LATE (compliers), CATE, or a dose-response; population and time window. Different designs identify different estimands — say which one you report.
2. **DAG**: draw the assumed graph (dagitty or by hand). Adjust for confounders; never for mediators (blocks the effect), colliders or post-treatment variables ("bad controls"); pre-treatment only.
3. **Identification argument** in one paragraph (what assumption makes the comparison causal) and what would break it.
4. **Unit of assignment** = clustering level for inference.

## Tooling (PyPI, 2026-09-29)
pyfixest 0.60 (feols/fepois with fixed effects, `i()` event-study syntax, `did2s`, `lpdid`, saturated/Sun-Abraham `event_study`, wild cluster bootstrap via wildboottest, CCV), `differences` 0.3 and `csdid` 0.4 (Callaway–Sant'Anna), linearmodels 7.0 (IV2SLS/LIML/GMM, panel), `rdrobust` 2.1 (RD with robust bias-corrected CIs; also `rddensity` for manipulation tests), DoWhy 0.14 (DAG-based identification + refuters), EconML 0.17 (DML, causal forests, meta-learners), pysyncon 1.7 (synthetic control, augmented SC, placebo inference). R's `did`, `fixest`, `synthdid`, `HonestDiD` remain the references; cross-check a key estimate in R when stakes are high.

## Difference-in-differences
- One treatment date, two groups: TWFE `pf.feols("y ~ treat | unit + year", df, vcov={"CRV1": "unit"})` is fine; show the event study `pf.feols("y ~ i(rel_year, ref=-1) | unit + year", …)` with pre-period coefficients near zero.
- **Staggered adoption or heterogeneous effects: never report plain TWFE** (already-treated units act as controls; weights can be negative, estimates wrong-signed). Use a heterogeneity-robust estimator and report cohort/event-time aggregates:
  ```python
  import pyfixest as pf
  fit = pf.event_study(data=df, yname="y", idname="unit", tname="year", gname="g", estimator="saturated")  # Sun–Abraham
  fit.aggregate(weighting="shares"); fit.iplot_aggregate(weighting="shares")
  fit.test_treatment_heterogeneity()
  pf.did2s(df, yname="y", first_stage="~ 0 | unit + year", second_stage="~ i(rel_year, ref=-1.0)",
           treatment="treat", cluster="state")                                              # Gardner two-stage
  pf.lpdid(data=df, yname="y", gname="g", tname="year", idname="unit", vcov={"CRV1": "state"},
           pre_window=-5, post_window=5, att=False)                                         # local projections
  ```
  `g` = first treatment period (0 or NaN for never-treated, per the estimator's convention — check). Callaway–Sant'Anna via `differences`/`csdid` or R `did`.
- Parallel trends is untestable; pre-trends are evidence, not proof. Pre-trend tests have low power — add HonestDiD-style sensitivity (how large a violation would overturn the result).
- Simultaneous bands for event studies: `fit.iplot(joint="both")`, `fit.confint(joint=True)`.
- Check: no anticipation (treatment announced early?), composition stable (panel balanced or attrition analysed), spillovers to controls, never-treated vs not-yet-treated control choice stated. `pf.panelview(...)` to plot treatment timing.

## Instrumental variables
- Relevance: first-stage F reported; weak instruments (F well below ~10, or effective F by Montiel Olea–Pflueger) → weak-IV-robust inference (Anderson–Rubin CIs), LIML over 2SLS.
- Exclusion: argue it substantively; it cannot be tested with one instrument. Monotonicity needed for LATE; describe the complier population.
- linearmodels: `IV2SLS.from_formula("y ~ 1 + x_exog + [d ~ z]", df).fit(cov_type="clustered", clusters=df.cl)`.

## Regression discontinuity
- `rdrobust(y, x, c=cutoff)` for local-linear estimates with MSE-optimal bandwidth and robust bias-corrected CIs; report conventional and robust; bandwidth sensitivity (half/double).
- Manipulation: density test at the cutoff (`rddensity`); covariate balance and placebo cutoffs; donut RD if heaping at the threshold. Fuzzy RD = IV at the cutoff.
- Plot binned means with the fit (`rdplot`); never fit high-order global polynomials.

## Matching and weighting (selection on observables)
- Only with a credible "all confounders observed" argument. Estimate propensity scores, check **overlap** (trim or change the estimand to ATT/overlap weights), check **balance**: standardized mean differences < 0.1 after weighting, variance ratios near 1.
- Prefer doubly robust estimators (AIPW, DML in EconML) over pure matching or pure regression; cross-fit nuisance models.
- Report the effective sample size after weighting.

## Synthetic control and synthetic DiD
One or few treated units, many controls, long pre-period. Donor pool without spillovers or similar shocks; pre-period fit (RMSPE) shown; inference by in-space placebos (ratio of post/pre RMSPE) and in-time placebos; augmented SC when pre-fit is imperfect; synthetic DiD (R `synthdid`) when both unit and time weights help.

## Inference
Cluster at the treatment-assignment level; with few clusters (< ~40, or few treated clusters) use wild cluster bootstrap (pyfixest `wildboottest`) or randomization inference. Don't cluster below the assignment level.

## Sensitivity and robustness (report them)
Placebo outcomes (should show no effect) and placebo timings; alternative control groups and specifications; E-values or Cinelli–Hazlett omitted-variable bounds for selection-on-observables designs; DoWhy refuters (placebo treatment, random common cause, data subset); a specification curve when many defensible choices exist.

## Report template
Estimand and population → design and identifying assumption → data and sample construction → main estimate with CI and clustering level → event-study/first-stage/balance/RD plots → robustness table → what would invalidate the result → plain-language conclusion scoped to the estimand.

Sources (checked 2026-09-29): https://pyfixest.org/tutorials/difference-in-differences.html · https://github.com/py-econometrics/pyfixest · https://doi.org/10.1016/j.jeconom.2020.12.001 (Callaway & Sant'Anna 2021) · https://doi.org/10.1016/j.jeconom.2020.09.006 (Sun & Abraham 2021) · https://www.pywhy.org/dowhy/ · https://pypi.org/project/rdrobust/ · https://pypi.org/project/pysyncon/ · https://pypi.org/project/linearmodels/ · https://pypi.org/project/econml/
