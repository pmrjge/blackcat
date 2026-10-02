---
name: time-series-forecasting
description: Load before forecasting or backtesting a time series — rolling-origin splits, seasonal-naive baselines, ETS/ARIMA.
---
# Time-series forecasting

## Scope
Point and probabilistic forecasts and their validation. General experiment protocol → `ml-experiment`; GBM tuning → `tabular-ml`; Bayesian structural models → `bayesian-modeling`; causal effects of interventions on a series → `causal-inference`; plotting fans and bands → `data-visualization`.

## 1. Frame the problem
- Horizon `h`, frequency, forecast origin cadence (daily re-forecast?), and the decision the forecast feeds (a quantile such as P90 for stock, a mean for budgets).
- Level: one series, many series (global model), or a hierarchy that must add up.
- Exogenous variables: known in advance (calendar, prices you set, planned promotions) vs only observed (weather, competitor prices) — the latter must themselves be forecast or lagged by ≥ h.
- Data latency: if yesterday's value arrives in two days, the model can't use lag 1.

## 2. Validation (never shuffle)
- Rolling-origin / expanding-window CV with the production horizon and cadence; several windows covering seasonal cycles; a gap equal to data latency.
- Nixtla format: long dataframe `unique_id`, `ds`, `y`.
  ```python
  from statsforecast import StatsForecast
  from statsforecast.models import AutoETS, AutoARIMA, SeasonalNaive, MSTL
  sf = StatsForecast(models=[SeasonalNaive(season_length=7), AutoETS(season_length=7), AutoARIMA(season_length=7)],
                     freq="D", n_jobs=-1)
  cv = sf.cross_validation(df=df, h=28, step_size=7, n_windows=8)   # columns: unique_id, ds, cutoff, y, <model>
  from utilsforecast.evaluation import evaluate
  from utilsforecast.losses import mase, rmse
  ```
  Check the `evaluate`/`mase` signature in your installed utilsforecast (MASE needs the training series and seasonality).
- Features for ML models are built only from data available at each cutoff; recompute them inside each window (or use mlforecast, which does this).
- Hold out the final period untouched until model selection is done.

## 3. Baselines (always report skill against them)
Naive (last value), seasonal naive, drift, ETS. Report **MASE** (scale-free, < 1 = beats the in-sample seasonal naive) or relative error vs seasonal naive per horizon. A complex model that doesn't beat seasonal naive on the backtest doesn't ship.

## 4. Model families
| Situation | Start with |
|---|---|
| Few series, clear seasonality | statsforecast `AutoETS`, `AutoARIMA`, `MSTL` (multiple seasonalities), `AutoTheta` |
| Many related series, covariates | global GBM (mlforecast with LightGBM/XGBoost; lags, rolling stats, calendar, target transforms such as differences) |
| Intermittent demand | Croston/ADIDA/IMAPA/TSB (statsforecast), evaluate with appropriate metrics (not MAPE) |
| Zero-shot baseline or little history | Chronos-2 (Apache-2.0) |
| Long, complex series with lots of data | neuralforecast (NHITS, PatchTST, TFT) after the above |

- Multi-step: recursive (one model, feeds predictions back; errors compound) vs direct (one model per horizon step); mlforecast supports both.
- Diagnostics for classical models: residual ACF/Ljung–Box, residual vs fitted, parameter stability across windows (statsmodels).

## 5. Foundation models (checked 2026-09-29)
- **Chronos-2** (`amazon/chronos-2`, Apache-2.0, ~120M params, encoder-only; paper Oct 2025): univariate, multivariate, past-only and known-future covariates (real or categorical), context up to 8192, horizon up to 1024, quantile outputs. `chronos-forecasting` 2.3.2:
  ```python
  from chronos import Chronos2Pipeline
  pipe = Chronos2Pipeline.from_pretrained("amazon/chronos-2", device_map="cuda")  # or "cpu"
  pred = pipe.predict_df(context_df, future_df=future_cov_df, prediction_length=28,
                         quantile_levels=[0.1, 0.5, 0.9], id_column="id", timestamp_column="ds", target="y")
  ```
- **TimesFM 3.0** (`google/timesfm-3.0-pytorch`, Aug 2026; `timesfm` 3.0.2; `uv add "timesfm[torch]"` or `"timesfm[mlx]"`): multivariate and covariates; **weights under a non-commercial, non-production licence** — for commercial work use TimesFM ≤ 2.5 (Apache-2.0) or Chronos-2. Code is Apache-2.0.
- Treat zero-shot forecasts as a strong baseline in the same backtest, not as ground truth. Leakage risk: public benchmark series may be in the pretraining corpus — evaluate on your own recent data. Cost: GPU/MPS inference per origin × windows.

## 6. Uncertainty
- Produce intervals or quantiles, not just points: model-based (ETS/ARIMA `level=[80, 95]`), quantile losses for GBMs, conformal prediction intervals from CV residuals (statsforecast/mlforecast support conformal intervals).
- Check **coverage** on the backtest (a nominal 90% interval should cover ~90%, per horizon) and interval width; report both.

## 7. Metrics
| Metric | Use | Pitfall |
|---|---|---|
| MAE / RMSE | same-scale series; RMSE punishes large misses | not comparable across series |
| MASE / RMSSE | across series, vs seasonal naive | define the seasonal period |
| MAPE | avoid | undefined at 0, explodes near 0, asymmetric |
| sMAPE | only if required | still unstable near 0 |
| WAPE (sum abs err / sum actual) | business reporting of totals | dominated by large series |
| Pinball / CRPS / scaled quantile loss | quantile and probabilistic forecasts | report per quantile |

Report per horizon step and per segment, not just one average.

## 8. Hierarchies and deployment
- Forecast all levels and reconcile (hierarchicalforecast: BottomUp, MinTrace) so totals add up; compare reconciled vs base accuracy.
- Monitor after deployment: error vs baseline over time, coverage drift, data latency changes; retrain cadence set by the backtest (how fast accuracy decays).
- Store forecasts with origin timestamp and model version to evaluate later without look-ahead.

## Report
Horizon and cadence · backtest design (windows, gap) · baselines and skill scores per horizon · coverage of intervals · error by segment · model card (data through date, features, version) · limitations (regime changes, holidays not in history).

Sources (checked 2026-09-29): https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/crossvalidation.html · https://otexts.com/fpp3/ · https://huggingface.co/amazon/chronos-2 · https://github.com/google-research/timesfm · https://pypi.org/project/statsforecast/ · https://pypi.org/project/mlforecast/ · https://pypi.org/project/chronos-forecasting/ · https://pypi.org/project/timesfm/
