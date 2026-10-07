---
name: data-analysis
description: Use for dataset analysis — profiling, exploratory plots, tests, effect sizes, A/B tests, power.
---
# Data analysis protocol

## 1. Profile first
Rows, columns, types, grain (what one row is), keys and their uniqueness, missingness per column (and whether it depends on other variables), duplicates, ranges and impossible values, time coverage and gaps, category cardinalities. Write the profile to the job folder. Work on a copy; never modify source data.

## 2. Explore visually
Distributions (histograms/ECDFs, log scale for heavy tails), relationships (scatter with alpha, binned means), time series (raw + rolling), breakdowns by the segments that matter. Read every chart back before drawing a conclusion from it.

## 3. Choose the test by design and data
| Question | Default | Notes |
|---|---|---|
| Mean difference, 2 groups | Welch's t-test | Heavy tails/outliers → Mann-Whitney or bootstrap of the difference |
| Paired measurements | paired t / Wilcoxon signed-rank | |
| Proportions, 2 groups | two-proportion z / Fisher exact (small n) | |
| > 2 groups | ANOVA / Kruskal-Wallis, then corrected pairwise | |
| Association, categorical | χ² (expected ≥ 5) / Fisher | report Cramér's V |
| Relationship with controls | OLS/GLM with robust (HC3) or clustered SEs | check residuals, leverage, collinearity |
| Counts | Poisson/negative binomial GLM | overdispersion check |
| Time to event | Kaplan-Meier, Cox | proportional hazards check |
Report effect sizes (difference, ratio, Cohen's d, odds ratio) with 95% CIs; p-values only alongside them.

## 4. Multiple comparisons and forking paths
Count every test you ran. Control FWER (Holm) or FDR (Benjamini-Hochberg). Separate confirmatory (pre-stated) from exploratory findings and label them.

## 5. Experiments (A/B)
Before: primary metric, minimum detectable effect, power analysis → sample size, randomization unit, duration covering weekly cycles, guardrail metrics. After: sample-ratio-mismatch check, pre-period balance, the pre-stated test; no peeking-driven stopping unless a sequential method was planned. CUPED or regression adjustment for variance reduction when pre-period data exists.

## 6. Causal claims
Only with a design: randomization (§5), or a quasi-experimental design (DiD, IV, RD, matching/weighting, synthetic control) done per `causal-inference`. Otherwise write "associated with".

## 7. Forecasting
Forecasts follow `time-series-forecasting` (rolling-origin backtests, seasonal-naive baselines, interval coverage).

## 8. Reproducibility
Notebook or script that runs top-to-bottom from the raw snapshot (`jupyter nbconvert --to notebook --execute` or nbclient), fixed seeds, pinned environment, data snapshot identified by path and hash. Every number in the report is recomputed a second way (another query, bootstrap, independent script).

## Verify
- Profile written; source data untouched; every chart read back.
- Effect sizes with 95% CIs; every test counted and corrected (Holm or BH); confirmatory vs exploratory labelled.
- A/B: sample-ratio mismatch and balance checked. Causal wording only with a design (§6).
- Notebook runs top to bottom from the snapshot; every reported number recomputed a second way.

## 9. Report
Answer first (with interval) → data and method → checks performed (assumptions, robustness, sensitivity) → limitations → figures and tables (files) → next steps. Charts: labeled axes with units, zero baseline for bar charts, colorblind-safe palettes, no dual axes unless unavoidable.

Related skills: `data-visualization` (the figures), `numerical-methods` (numerical pitfalls), `technical-writing` (the write-up).
