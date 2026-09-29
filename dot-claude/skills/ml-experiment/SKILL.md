---
name: ml-experiment
description: Load before running or comparing any model, training run or evaluation — framing, leakage-safe splits, baselines, seeds, tracking, ablations, comparisons with uncertainty.
---
# ML experiment protocol

## 1. Frame before code
Write these into `./.claude-work/<job>/experiment.md` first:
- Question the experiment answers and the decision it informs.
- Unit of prediction, target, and the metric that reflects the decision (plus a guard metric: latency, memory, calibration, fairness slice…).
- Data: source, version/snapshot, size, time range. Compute budget: device, memory, wall time.
- Success criterion stated in advance ("≥ +1.0 F1 over baseline, CI excludes 0").

## 2. Splits that mirror deployment
- Temporal data → time-based split (train past, test future), never random.
- Grouped data (users, sessions, patients, documents, repos) → group split; no group in two splits.
- Deduplicate before splitting (exact and near duplicates); check train/test overlap explicitly.
- Leakage checklist: features computed with future information, target encodings fitted on full data, normalization fitted before the split, labels leaking through IDs or timestamps, test-set reuse during tuning.
- The test set is touched once, at the end. Tune on validation or with (nested) CV.

## 3. Baselines
Always report: a trivial baseline (majority class, last value, mean), a simple strong baseline (logistic/linear, gradient boosting with defaults, the unmodified pretrained model), and the published or previous best when one exists.

## 4. Reproducibility
- Seed everything (Python, NumPy, framework, data loader workers); record library versions (`uv.lock` or `uv pip freeze` into the run folder) and git commit.
- One run = one folder: config, command line, logs, metrics JSON, artifacts. Never overwrite a run folder.
- Deterministic data order for comparisons; note any non-determinism you could not remove (atomics on GPU, MPS kernels).

## 5. Tracking
Use what the project already uses (W&B via `mcp__wandb` or the `wandb` library, MLflow via the `mlflow` library or the mlflow MCP mounted by mcp-broker). Otherwise append one row per run to `results.md` (below). Never log secrets or raw personal data.

## 6. Comparing runs
- Same data, same eval code, same metric implementation. Change one variable per ablation.
- Small differences need spread: ≥ 3 seeds (or CV folds) and mean ± std, or a paired bootstrap CI over test examples. Say "no detectable difference" when the interval covers 0.
- Report cost next to quality: parameters, train time, peak memory, inference latency/throughput.
- Look at errors, not only aggregates: worst slices, confusion pairs, a sample of failures.

## 7. Results table (results.md)
```
| run | change vs baseline | metric (mean ± std or CI) | guard metric | seeds | time | peak mem | notes |
|---|---|---|---|---|---|---|---|
```
Close with: conclusion (does it meet the success criterion?), threats to validity, next experiment.

## 8. Parallel experiments
Independent configurations may run in parallel (background jobs, or separate agents) only when they do not compete for the same accelerator (two jobs on one GPU or one Mac's unified memory corrupt timings and can OOM). CPU-only sweeps can run in parallel; accelerator runs go one at a time or to separate hosts.

Related skills: `training-debug` (a run misbehaves), `data-visualization` (curves and comparisons), `dataset-curation` (data quality and splits), `numerical-methods` (precision and reproducibility), `tabular-ml` and `time-series-forecasting` (domain procedures), `distributed-training` (multi-GPU), `model-export` (deployment artifacts).
