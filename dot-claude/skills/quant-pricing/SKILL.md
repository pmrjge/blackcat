---
name: quant-pricing
description: Use to price derivatives and bonds — closed forms, trees, Monte Carlo, PDEs, curves, QuantLib.
---
# Derivatives and fixed-income pricing

Baseline: `quant-finance`. Numerical schemes and error analysis: `numerical-methods`, `num-ode-sde`, `sci-pde-fem`; derivations: `proof-craft`.

## Tools
- QuantLib 1.43 (C++) and the `QuantLib` Python package 1.43 — Verified 2026-10-02 https://github.com/lballabio/QuantLib/releases/latest https://pypi.org/project/QuantLib/
- QuantLib's global evaluation date (`ql.Settings.instance().evaluationDate`) changes every subsequent price: set it explicitly at the top of every script and test.

## Method choice
| product | method |
|---|---|
| European vanilla | closed form (Black–Scholes–Merton, Black-76 for futures, Bachelier for normal/negative rates) |
| American/Bermudan | binomial/trinomial trees (≥ 500 steps with Richardson extrapolation), finite differences, Longstaff–Schwartz Monte Carlo |
| path-dependent (Asian, barrier, lookback) | Monte Carlo with variance reduction; PDE for low-dimensional barriers; closed forms where they exist (geometric Asian, continuous barriers with a discrete-monitoring correction) |
| stochastic volatility | Heston semi-closed form (Fourier/COS) for calibration, MC (QE scheme) for exotics |
| rates | curve bootstrapping, Hull–White/G2++ for callables, SABR for swaption smiles, LMM for path dependence |

## Rules
- Conventions written down: day count (ACT/360, 30/360, ACT/ACT ISDA), calendar, business-day adjustment, settlement lag, compounding and frequency. Most "pricing bugs" are conventions.
- Curves: bootstrap from instruments actually quoted (deposits/futures/OIS swaps), with the post-LIBOR setup (OIS discounting, RFR compounding in arrears for SOFR/€STR/SONIA); check that the curve reprices its inputs to < 0.01 bp.
- Volatility surfaces: arbitrage-free checks (calendar and butterfly), interpolation in total variance; calibrated parameters with fit errors reported.
- Monte Carlo: seeds fixed, standard error reported with every price, antithetic/control variates (e.g. the geometric Asian as control for the arithmetic one), quasi-random (Sobol + Brownian bridge) for smooth payoffs; time-step bias checked by halving Δt.
- Greeks: analytic where available; bump-and-revalue with central differences and common random numbers; pathwise/likelihood-ratio or AAD for MC; gamma near barriers and digitals is unstable — smooth or use wider bumps and say so.
- PDE: Crank–Nicolson with Rannacher start-up steps for non-smooth payoffs, grid aligned with strikes/barriers, boundary conditions justified; convergence checked by grid refinement.

## Validation
- Put–call parity, bounds (intrinsic ≤ American ≤ appropriate upper bound), monotonicity in strike and maturity, convergence of tree/PDE/MC to the closed form on vanilla cases.
- Cross-check against a second implementation (QuantLib vs own code, or two QuantLib engines) on a set of reference trades; tolerance stated.
- Market reasonableness: implied vol of the model price close to the market's for vanillas used in calibration.

## Pitfalls
Wrong day count or calendar; evaluation date left at today; dividends ignored or treated as continuous yield inconsistently; discrete vs continuous barrier monitoring; MC prices without standard errors; Greeks from noisy MC with independent seeds; negative rates in lognormal models.

## Verify
Closed-form/vanilla limits reproduced to stated tolerance · parity and no-arbitrage checks pass · MC prices with standard errors and Δt/paths convergence · curve reprices inputs · conventions table included in the report.
