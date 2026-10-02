# Labeling, versioning, storage, documentation

Part of `dataset-curation`.

## 11. Labeling
- Guidelines: task definition; each label with positive, negative and boundary examples; a decision procedure for ambiguous items; an explicit "unsure" option; common mistakes. Version them.
- Pilot 50–100 items with ≥2 annotators, measure agreement, revise, repeat until stable.
- Agreement: Cohen's κ for two raters (`sklearn.metrics.cohen_kappa_score`, `weights="quadratic"` for ordinal labels); Fleiss' κ for a fixed number of raters per item (`statsmodels.stats.inter_rater.aggregate_raters` → `fleiss_kappa`); Krippendorff's α for any number of raters and missing labels (`krippendorff.alpha(reliability_data=..., level_of_measurement="nominal")` — the package defaults to `"interval"`, wrong for categories). Report per-label confusion too; κ depends on prevalence.
- Production: seeded gold items to monitor annotators, adjudication of disagreements, LLM pre-labels only after measuring agreement with humans, with a control subset labeled blind.

## 12. Versioning, storage, documentation
- Parquet with zstd, shards of ~100–500 MB; inspect with DuckDB or polars. `datasets`: `load_dataset("parquet", data_files=...)`, `Dataset.push_to_hub(repo_id, private=True)`, consumers pin a revision (`hf-hub`).
- A dataset version = source snapshot hashes + pipeline commit + config; ship a manifest (rows and sha256 per shard) and a changelog. Large files: Hub repos (Xet storage) or DVC.
- Data card / datasheet: motivation; composition (sizes, languages, domains, synthetic share); collection; preprocessing waterfall; licenses and attribution; personal-data handling; known biases and gaps; intended and out-of-scope uses; maintenance and contact. Hub dataset cards carry YAML metadata (`license`, `language`, `task_categories`, `size_categories`, `pretty_name`, `configs`); the Hub serves Croissant metadata at `https://huggingface.co/api/datasets/<repo>/croissant`.
