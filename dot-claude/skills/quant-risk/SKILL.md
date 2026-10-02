---
name: quant-risk
description: Load before risk or portfolio analytics — volatility, VaR/ES, factor models, optimization, stress.
---
# Risk and portfolio analytics

Baseline and data rules: `quant-finance`. Time-series models: `time-series-forecasting`; Bayesian approaches: `bayesian-modeling`.

## Tools
- arch 8.0.0 (GARCH family, bootstrap) — Verified 2026-10-02 https://github.com/bashtage/arch/releases/latest
- cvxpy 1.9.3 (convex optimization) — Verified 2026-10-02 https://github.com/cvxpy/cvxpy/releases/latest
- Riskfolio-Lib 7.3.0 and PyPortfolioOpt 1.6.0 (portfolio optimization) — Verified 2026-10-02 https://pypi.org/project/riskfolio-lib/ https://pypi.org/project/pyportfolioopt/
- statsmodels for regressions (factor models with HAC/Newey–West standard errors).

## Volatility and dependence
- Estimators: rolling/EWMA (RiskMetrics λ ≈ 0.94 daily) for monitoring, GARCH(1,1)/GJR-GARCH with Student-t innovations for forecasting; check standardized residuals (Ljung–Box on squares).
- Covariance for many assets: shrinkage (Ledoit–Wolf), factor-based, or denoised (random matrix theory) — never the raw sample covariance when N is close to T.
- Correlations rise in stress: report them in calm and stressed subperiods; copulas for tail dependence when it matters.

## VaR and Expected Shortfall
- Define horizon, confidence (99 % VaR, 97.5 % ES as in FRTB), and P&L sign convention (losses positive).
- Methods: historical simulation (filtered by volatility for responsiveness), parametric (normal is too thin-tailed for daily returns — use Student-t or Cornish–Fisher), Monte Carlo with full revaluation for options.
- Scaling by √h assumes iid returns: say so or simulate the horizon.
- Backtest VaR: exception counts with Kupiec (unconditional coverage) and Christoffersen (independence) tests; ES backtests (Acerbi–Székely) when ES is the reported measure.

## Factor models and attribution
- Fama–French/Carhart or the user's factor set (Kenneth French data library for the standard factors, with its download date); time-series regressions with HAC errors; rolling betas to show instability.
- Attribution: Brinson for allocation/selection; factor-based return and risk decomposition (marginal and component contributions to risk sum to total).

## Portfolio optimization
- Mean–variance is extremely sensitive to expected-return inputs: prefer minimum variance, risk parity/equal risk contribution, hierarchical risk parity, or Black–Litterman views; shrink expected returns.
- Constraints explicit: budget, long-only or gross/net leverage, position and sector limits, turnover and transaction costs in the objective.
- Solve with cvxpy (check `problem.status == "optimal"`), report the solver; robustness via resampled/bootstrapped inputs.
- Evaluate out of sample with rebalancing costs; in-sample optimal weights are not evidence.

## Stress testing and scenarios
Historical scenarios (2008, 2020 March, 2022 rates) re-priced on today's portfolio; hypothetical shocks (rates +200 bp, equity −30 %, vol ×2) with full revaluation of nonlinear positions; reverse stress test (what breaks the portfolio).

## Pitfalls
Annualizing with the wrong frequency; mixing simple and log returns in aggregation; sample covariance on short histories; normal VaR on fat-tailed returns; ignoring liquidity horizons; optimization weights that flip with tiny input changes; backtesting risk models on the period they were fitted on.

## Verify
Risk numbers recomputed by a second method (e.g. historical vs parametric) with differences explained · VaR backtest exception counts and test p-values · optimizer status and constraints checked on the output weights · stress scenarios documented with shock definitions.
