---
name: quant-finance
description: Load before quantitative finance work — backtests, risk, portfolio construction, derivatives pricing, market data; safety rules and the module map.
---
# Quantitative finance (hub)

## Scope
Research code for trading strategies, risk and portfolio analytics, and pricing models. Statistics and time series: `data-analysis`, `time-series-forecasting`, `causal-inference`; numerics: `numerical-methods`; dataframes: `dataframes-duckdb`.

## Modules
| module | load when |
|---|---|
| `quant-backtesting` | strategy research, event-driven or vectorized backtests, costs, walk-forward, overfitting checks |
| `quant-risk` | returns, volatility, VaR/ES, factor models, portfolio optimization, stress tests |
| `quant-pricing` | options and fixed income: Black–Scholes, trees, Monte Carlo, PDEs, curves, QuantLib, Greeks |

## Safety and scope rules
- **No real orders.** Placing, modifying or cancelling orders, moving money or changing brokerage settings is never done by an agent; live connections are read-only or paper trading, and even paper accounts are used only when the user asked. Report what a strategy would do; the user executes.
- Results are research, not investment advice: state assumptions, sample period and limitations with every number.
- Market data has licenses: respect vendor terms (no redistribution of paid data into repos or public places); API keys come from the user's store (`stack.env`), never from files in the repo or URLs in logs.
- Data sources: free/public (FRED, SEC EDGAR, exchange-published data, yfinance-style scrapers with their reliability caveats), vendor APIs with the user's key. In this stack, an SEC EDGAR MCP server exists in the magg catalog (mounted on request; needs a `SEC_EDGAR_USER_AGENT` with the user's name and email); the Alpha Vantage MCP server is documented only — call its REST API with the user's key instead.

## Baseline rules
- Point-in-time data: every value used at time t must have been known at t (release dates for fundamentals and macro data, index membership as of t, delisted securities included). Lookahead and survivorship bias are the default failure; check for both explicitly.
- Returns: simple vs log returns chosen deliberately (log for time aggregation, simple for cross-sectional portfolio aggregation); prices adjusted for splits and dividends consistently; total return when dividends matter.
- Calendars and time zones: exchange calendars (`exchange_calendars`/`pandas_market_calendars`), timestamps in UTC with the exchange zone recorded, close-to-close vs open-to-close alignment explicit.
- Annualization stated (252 trading days, √252 for volatility), risk-free rate source stated.
- Money in decimal types or integer minor units in accounting/settlement code; floats are fine for statistical research.
- Reproducibility: data snapshot (hash, date range, vendor, download date), code commit, parameters and random seeds saved with every result.

## Verify
Bias checklist (lookahead, survivorship, data snooping) answered in the report · results recomputed with a second implementation or simple sanity case (buy-and-hold, known option price) · transaction costs and sample period stated · no order or account action taken.
