---
name: tabular-ml
description: Load before modeling tabular data — gradient boosting, categoricals, early stopping, calibration.
---
# Tabular ML

## Scope
Supervised models on rows × features. Experiment protocol (splits, seeds, ablations, uncertainty) → `ml-experiment` (load it too); dataset hygiene → `dataset-curation`; dataframe work → `dataframes-duckdb`; forecasting → `time-series-forecasting`; causal questions → `causal-inference`; deployment → `model-export`. Versions (PyPI, 2026-09-29): scikit-learn 1.9.1, XGBoost 3.4.x, LightGBM 4.7.0, CatBoost 1.2.10, Optuna 5.0.0, SHAP 0.52.0, TabPFN package 9.0.0.

## 1. Baseline ladder (report every rung)
dummy (prior/mean) → linear/logistic with proper preprocessing → GBM with defaults + early stopping → tuned GBM → TabPFN on small/medium data → ensembles only if they beat the best single model beyond noise. Each rung on the same CV splits with the same metric and its uncertainty.

## 2. Splits and leakage
- Split by the real deployment boundary: time (train past, validate future), group (`GroupKFold` by customer/patient/site), or stratified for i.i.d. classification. Nested CV (outer for estimate, inner for tuning) when data is small.
- Everything fitted on data (imputers, scalers, target encoders, feature selection, SMOTE) goes inside a `Pipeline` so it is refit per fold; never fit on the full data first.
- Target leakage audit: features computed after the label time, IDs that encode the label, duplicates across splits.

## 3. Libraries — parameters and categoricals
| | XGBoost 3.4 | LightGBM 4.7 | CatBoost 1.2 |
|---|---|---|---|
| Categoricals | native; **`enable_categorical` defaults to True since 3.3** (pandas `category`/polars `Enum` columns); `max_cat_to_onehot` | native via pandas `category` or `categorical_feature=`; `min_data_per_group`, `cat_smooth` | best default for high-cardinality: `cat_features=[…]`, ordered target statistics built in |
| Early stopping | `XGBClassifier(early_stopping_rounds=100, n_estimators=10_000)` + `eval_set` | `callbacks=[lgb.early_stopping(100)]` | `early_stopping_rounds=100`, `eval_set` |
| Key knobs | `max_depth` or `max_leaves`+`grow_policy="lossguide"`, `learning_rate`, `min_child_weight`, `subsample`, `colsample_bytree`, `reg_lambda` | `num_leaves` (< 2^max_depth), `min_data_in_leaf`, `feature_fraction`, `bagging_fraction`+`bagging_freq`, `lambda_l2` | `depth`, `learning_rate`, `l2_leaf_reg`, `iterations` |
| GPU | `device="cuda"` | `device_type="cuda"` build | `task_type="GPU"` |
| Notes | Python ≥ 3.12 since 3.3; `gblinear` deprecated; polars needs `Enum` support | overfits small data with large `num_leaves` | slower to train, strong defaults |

- Early stopping uses a validation fold **inside** the training portion of each CV split — never the test fold. Refit on the full training data with `n_estimators = best_iteration` (scaled up slightly for more data) or average fold models.
- High-cardinality categoricals in linear models: CV-safe target encoding (`sklearn.preprocessing.TargetEncoder`, which cross-fits internally) — never plain mean encoding on the full data.
- Monotonic constraints (`monotone_constraints`) when the domain requires them (price ↑ → demand ↓); interaction constraints for interpretability.

## 4. Hyperparameter search (Optuna 5)
- Defaults changed in 5.0: `TPESampler` is multivariate with `constant_liar` by default and is also the default for multi-objective (replacing NSGA-II); `optuna.multi_objective` and `set_system_attr`/`system_attrs` removed; `constraints_func` deprecated for `trial.set_constraint()`; RDB/Journal storage timestamps now UTC.
- Search spaces (log scale where it matters): learning_rate 1e-3–0.3 (log), depth 3–10 or num_leaves 15–255, min_child_weight/min_data_in_leaf, subsample and colsample 0.5–1, L2 1e-3–10 (log). Tune with early stopping on, so `n_estimators` is not a search dimension.
- Pruning (`MedianPruner`, `HyperbandPruner`) with per-fold reporting; `study.optimize(..., n_trials=…, timeout=…)`; persist to SQLite (`storage="sqlite:///study.db"`) to resume; seed the sampler.
- The tuned score is optimistic: estimate on the outer fold or a held-out set.

## 5. Imbalanced classes
Keep the natural distribution in validation/test. Prefer class weights (`scale_pos_weight`, `class_weight="balanced"`) or no rebalancing plus threshold tuning over resampling; if resampling, only inside the training fold. Metrics: PR-AUC and recall at the operating precision, not accuracy; choose the threshold from the decision's cost ratio (`sklearn.model_selection.TunedThresholdClassifierCV`) and report it.

## 6. Calibration (scikit-learn 1.9)
- Check first: reliability diagram (`CalibrationDisplay.from_estimator`), Brier score, log loss on held-out data.
- `CalibratedClassifierCV(method="sigmoid"|"isotonic"|"temperature", ensemble="auto")`. Sigmoid for small calibration sets; isotonic needs ≳ 1000 samples; temperature scaling is native multiclass and preserves argmax.
- Already-fitted model: `CalibratedClassifierCV(FrozenEstimator(fitted), method=…)` fitted on data disjoint from training (`from sklearn.frozen import FrozenEstimator`), replacing the old `cv="prefit"` idiom.
- GBMs trained with log loss are often close to calibrated; resampling or class weights break calibration — recalibrate after.

## 7. Interpretation
- SHAP `TreeExplainer` for tree models (XGBoost also has built-in `predict(..., pred_contribs=True)`; QuadratureTreeSHAP since 3.3); global summary + dependence plots; explain on held-out data.
- Permutation importance (`sklearn.inspection.permutation_importance`) on the validation set, with repeats; correlated features share or steal importance — group them or drop-column test.
- Importances are associations with the model's output, not causal effects.

## 8. TabPFN (checked 2026-09-29)
- Package `tabpfn` 9.0.0; default model **TabPFN-3.5** (also 3.5-Fast; TabPFN-3/2.6/2.5 selectable via `ModelVersion`), up to ~1M rows and 20k features per the README; sklearn API `TabPFNClassifier`/`TabPFNRegressor`. GPU recommended (≈ 8–16 GB); CPU practical only for a few thousand rows.
- **Licences**: code Apache-2.0; TabPFN-2.5/2.6/3/3.5 **weights are non-commercial** (commercial use needs an enterprise licence); TabPFN-2 weights are Apache-2.0 + attribution. Weights are gated: accept the licence at ux.priorlabs.ai and set `TABPFN_TOKEN` for headless runs.
- Use as a strong small-data baseline in the same CV; check that its preprocessing doesn't see the test fold (fit per fold like any estimator).

## 9. Pipelines and error analysis
- `ColumnTransformer` + `Pipeline`; `set_output(transform="pandas"|"polars")` to keep column names; `make_column_selector` by dtype.
- Error analysis by slice (segment, time, feature bins) with counts and CIs; look at the largest-loss examples; check performance drift across time folds.

## Report
Data and split design · baseline ladder table (metric ± CI per model) · chosen model, params and best iteration · calibration plot and Brier · threshold and its cost rationale · top features with the caveat · slices where it fails · versions and seed.

Sources (checked 2026-09-29): https://xgboost.readthedocs.io/en/stable/changes/v3.3.0.html · https://lightgbm.readthedocs.io/en/latest/Parameters-Tuning.html · https://scikit-learn.org/stable/modules/calibration.html · https://github.com/optuna/optuna/releases/tag/v5.0.0 · https://github.com/PriorLabs/TabPFN · local check: xgboost 3.4.1 `enable_categorical=True`, scikit-learn 1.9.1 `CalibratedClassifierCV` signature
