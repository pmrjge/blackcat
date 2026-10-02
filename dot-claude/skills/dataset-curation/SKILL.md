---
name: dataset-curation
description: Use to build or audit training and eval datasets — licenses, PII, dedup, decontamination, splits.
---
# Dataset curation

## Scope
Text, chat, code and multimodal datasets for training, fine-tuning and evaluation. Training runs → `llm-finetuning`; modeling protocol → `ml-experiment`; eval statistics → `llm-evals`; Hub mechanics → `hf-hub`; exploratory analysis → `data-analysis`. Environment: `__CLAUDE_DIR__/venvs/ml/bin/python` has Datasets, pandas, polars, pyarrow; add tools per project (`uv add datasketch datatrove presidio-analyzer`, or `uv run --with ...`); DuckDB for SQL over Parquet; `mcp__huggingface` to find datasets and read their cards. Legal notes below are orientation, not legal advice — escalate unclear cases.

## 1. Plan before collecting
Write down: the behavior the data should teach or measure; the unit (document, conversation, example, image-text pair); target size and distribution (domains, languages, lengths, difficulty); the eval sets it must never overlap; acceptance thresholds (quality score, dedup and contamination rates, known PII = 0); and the data card skeleton (§12) you will fill as you go.

## 2. Sources, licenses, personal data
Register per source: URL or repo@revision, SPDX license, terms of use, retrieval date, method, attribution requirements, whether personal data is present, opt-outs honored.

| Terms | Train on it | Redistribute the dataset |
|---|---|---|
| CC0 / public domain | yes | yes |
| CC-BY 4.0, ODC-By | yes | yes, with attribution kept per record |
| CC-BY-SA, ODbL | yes | derivatives under the same license |
| CC-BY-NC(-SA) | non-commercial contexts only; model use is contested | non-commercial only |
| Permissive code (MIT, Apache-2.0, BSD) | yes | keep license notices |
| Copyleft code (GPL, AGPL) | contested — follow the project's policy | copyleft obligations |
| Site terms forbidding scraping or ML, "research only", unknown | no, unless terms are cleared | no |
| Model outputs (synthetic) | check the generator's license and terms (some restrict training other models or require naming) | same |

- EU: the general text-and-data-mining exception (Art. 4, Directive (EU) 2019/790) covers lawfully accessible content unless the rightsholder reserved the right in an appropriate way — machine-readable for online content (robots.txt, TDM-reservation metadata, terms). Honor and log reservations. Providers placing general-purpose AI models on the EU market also need a copyright-compliance policy and a public training-content summary (AI Act Art. 53).
- GDPR: personal data needs a lawful basis, purpose limitation and minimization; pseudonymized data is still personal data; special categories (health, religion, etc.) need more; erasure after training is impractical, so minimize before training.
- Code corpora: per-file license detection (ScanCode toolkit), opt-out lists, secret scanning (gitleaks, trufflehog, detect-secrets) before anything else.

## 3–4. Collection, cleaning, deduplication
Read `references/cleaning-dedup.md` when collecting or cleaning raw data (immutable snapshots, extraction, reject logs) or deduplicating (exact hashes, MinHash + LSH).

## 5. Decontamination against evaluation sets
- Index normalized n-grams of every eval set you will report (8–13-grams; GPT-3 used 13, datatrove's `NGramsDecontIndexer`/`NGramsDecontFilter` default to 12); flag training records sharing any (or more than a set fraction of) eval n-grams; remove or quarantine; report counts per eval set.
- datatrove's indexer reads benchmarks through lighteval task definitions; for private or custom eval sets build the index yourself — a set of hashes of normalized n-grams from every prompt and reference answer, then one pass over the training data checking membership.
- Also check gold-answer strings, paraphrases (embedding similarity) for high-stakes evals, and eval items reproduced by synthetic generators.
- Record the corpus cutoff date; prefer evals released after it. Rerun decontamination whenever the corpus or the eval list changes.

## 6. PII and secrets
- Detection: Microsoft Presidio (`AnalyzerEngine().analyze(text=..., language=...)`, `AnonymizerEngine().anonymize(text=..., analyzer_results=...)`). Its default recognizers are English- and US-centric: configure an NLP engine for the target language and add pattern recognizers for local identifiers (national tax ids, IBANs, phone formats). Regexes cover emails, IPs, URLs with credentials (datatrove `PIIFormatter` handles emails and IPs); secret scanners cover code.
- Treatment per category: drop the record, mask with typed placeholders (`<EMAIL>`, `<PERSON>`), or pseudonymize consistently (same surrogate per real value, secret salt). Masking shifts the distribution; pseudonyms preserve structure.
- Measure detector precision and recall on a hand-labeled sample in the target language; false negatives (names above all) are what matter.
- Do not send raw personal data to external APIs for labeling or synthesis without a lawful basis and a processor agreement; use local models (`local-llm-serving`).

## 7. Quality filtering
- Heuristics first: length bounds, symbol/word ratios, share of lines ending in punctuation, repeated n-gram fractions, stop-word presence, language score. datatrove ships `GopherQualityFilter`, `GopherRepetitionFilter`, `C4QualityFilter`, `FineWebQualityFilter`, `LanguageFilter`, `URLFilter`, `FastTextClassifierFilter`.
- Classifiers: train a fastText or small-encoder model on human or LLM-annotated samples (as FineWeb-Edu did with `HuggingFaceFW/fineweb-edu-classifier`); choose the threshold by reading samples around it and by a small train-and-evaluate ablation.
- Instruction/chat data: rubric scoring (correctness, instruction following, completeness, safety), execution-based verification where possible (run the code and tests, check math with sympy), removal of boilerplate refusals and canned disclaimers, category balancing.
- Read 50 random rejects per filter: filters encode biases against dialects, domains and formats. Keep a waterfall table of counts per stage.

## 8–9. Synthetic data, formats
Read `references/synthetic-formats.md` when generating synthetic data (taxonomy grid, structured generation) or choosing a file format (JSONL/Parquet schema, TRL conventions).

## 10. Splits
- Choose the unit of independence first (user, author, document, repository, conversation, patient, time period) and split by group: scikit-learn `GroupShuffleSplit`, `GroupKFold`, `StratifiedGroupKFold`. Use near-duplicate cluster ids as groups.
- Forward-in-time deployment → temporal split (cutoff date, `TimeSeriesSplit`).
- Stratify imbalanced labels or domains; freeze the test set with a hash manifest; tune only on validation.
- LLM evals: private held-out sets, decontaminated against fine-tuning data in both directions.

## 11–12. Labeling, versioning, storage, documentation
Read `references/labeling-versioning.md` when writing labeling guidelines and measuring agreement, or storing and versioning a dataset (Parquet shards, revisions, data cards).

## 13. Checklist before training
- [ ] Every source has recorded license/terms that allow this use; opt-outs honored
- [ ] PII scanned and handled per policy; detector recall measured on a labeled sample
- [ ] Exact + near dedup done, including across splits; rates reported
- [ ] Decontaminated against every eval that will be reported; counts reported
- [ ] Quality filters applied; waterfall recorded; rejects read
- [ ] Synthetic share known, labeled and verified; generator terms checked
- [ ] Format validated: schema, rendered chat template, loss mask, token-length distribution vs context length
- [ ] Splits grouped or temporal as needed; test set frozen with hashes
- [ ] Label agreement at or above the agreed threshold; guideline version recorded
- [ ] Versioned build with manifest, data card and reproducible pipeline

## Verify
Rebuild from raw snapshots and get identical shard hashes; hand-review 100 random final records (quality, PII, format); plant known duplicates and eval items in a test run and confirm removal; assert no group id or near-dup cluster spans two splits; compare token-length statistics with the training context.

## Deliverables
Dataset shards + manifest, data card, pipeline code and config (with tool versions), waterfall table (`| stage | in | out | removed | % | notes |`), source/license register, decontamination and PII reports, agreement report.
