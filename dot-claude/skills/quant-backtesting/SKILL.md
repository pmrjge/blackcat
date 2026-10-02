---
name: quant-backtesting
description: Load to backtest a trading strategy — signal timing, costs, walk-forward and holdout, overfitting checks, metrics with uncertainty.
---
# Backtesting

Safety (no real orders), data and bias baseline: `quant-finance`.

## Tools
- vectorbt 1.1.1 (vectorized research, parameter sweeps) — Verified 2026-10-02 https://github.com/polakowo/vectorbt/releases/latest
- NautilusTrader 1.231.0 (event-driven, research-to-live parity) — Verified 2026-10-02 https://github.com/nautechsystems/nautilus_trader/releases/latest
- zipline-reloaded 3.1.1 (daily equities, pipeline API) — Verified 2026-10-02 https://github.com/stefan-jansen/zipline-reloaded/releases/latest
- A plain pandas/polars implementation is often the clearest for a daily strategy; use it as the second implementation to check a framework's numbers.
- Install in a uv project (`uv add vectorbt`), run with `uv run`.

## Design the test before running it
1. Hypothesis in one sentence with the economic reason it should work.
2. Universe definition as of each date (point-in-time constituents, delisted names included), sample period with an untouched **holdout** (most recent 20–30 %) that is run once at the end.
3. Signal timing: signal computed from data available at bar close t, trades at t+1 open (or with an explicit execution delay); never trade on the bar that produced the signal at that bar's close unless modeled as a MOC order placed before the close.
4. Benchmark (buy-and-hold, the index, equal-weight universe) and the metrics to judge on.

## Costs and execution realism
- Commissions, bid–ask spread (half-spread per side at minimum), slippage/market impact (e.g. proportional to volatility × √(order size / ADV)), borrow fees for shorts, financing for leverage, taxes if relevant.
- Capacity: position sizes vs average daily volume; flag strategies whose edge disappears at the intended size.
- Corporate actions, trading halts, limit-up/down, and data gaps handled; fills only within the bar's range.
- Run the strategy at 2× and 3× the assumed costs: an edge that only survives at low cost is not an edge.

## Validation
- Walk-forward: optimize on a rolling or expanding window, test on the next window, stitch the out-of-sample segments; report only stitched out-of-sample performance as the result.
- Purged and embargoed cross-validation for overlapping labels (López de Prado) when using ML.
- Multiple testing: count every variant tried; report the deflated Sharpe ratio or probability of backtest overfitting (CSCV) when many were tried.
- Parameter stability: performance surface over neighbouring parameters should be smooth; isolated peaks are overfitting.
- Regime and subperiod analysis (crises, rate regimes); results per year.
- Sanity tests: random signals should earn ≈ benchmark minus costs; shifting signals one bar forward (into the future) should make results much better — if it doesn't change anything, the timing is wrong somewhere.

## Metrics (report with the sample period)
CAGR, annualized volatility, Sharpe (with risk-free rate) and its standard error (Lo 2002) or bootstrap CI, Sortino, max drawdown and duration, Calmar, turnover, hit rate, average win/loss, exposure, beta to benchmark, alpha t-stat. Equity curve and drawdown plot (log scale) for the full and out-of-sample periods.

## Pitfalls
Lookahead through resampling (`resample().last()` labelled at the period start), centered rolling windows, forward-filled fundamentals before release dates; survivorship (today's index members); adjusted-price signals with unadjusted fills; ignoring costs and shorting constraints; optimizing on the full sample; reporting the best of many variants as if it were the only one.

## Verify
Second implementation matches trades and P&L on a sample period · random-signal and shifted-signal sanity tests behave as expected · cost sensitivity table · out-of-sample (walk-forward + holdout) metrics with uncertainty · number of variants tried stated.
