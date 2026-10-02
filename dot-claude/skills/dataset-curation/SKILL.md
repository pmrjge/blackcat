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

## 3. Collection and cleaning
- Raw snapshots are immutable (`raw/` + sha256 manifest); every step is a script producing a new versioned artifact with a reject log (reason, count, sample ids).
- Extraction: HTML → text with boilerplate removal (datatrove `Trafilatura` extractor), PDFs via docling/pdfplumber; keep structure (headings, lists, code blocks, tables as Markdown).
- Normalization: repair mojibake (ftfy), Unicode normalization chosen deliberately (NFC is safe; NFKC rewrites ligatures, full-width forms and math symbols), whitespace and control characters; language identification; token-length bounds with the target tokenizer.
- Validate every record against a schema (pydantic or JSON Schema) and fail loudly on drift.
- Profile before and after each stage (DuckDB reads JSONL and Parquet directly):
```sql
SELECT count(*) AS n, count(DISTINCT md5(text)) AS exact_unique,
       quantile_cont(length(text), [0.01, 0.5, 0.99]) AS char_len_q,
       sum(CASE WHEN text IS NULL OR trim(text) = '' THEN 1 ELSE 0 END) AS empty
FROM read_json_auto('data/raw/*.jsonl');
```
- Pipelines at scale: datatrove (`uv add "datatrove[processing,io]"`; the extras carry the filter dependencies). Every filter takes an `exclusion_writer`, which gives the reject log for free:
```python
from datatrove.executor import LocalPipelineExecutor
from datatrove.pipeline.readers import JsonlReader
from datatrove.pipeline.filters import LanguageFilter, GopherRepetitionFilter, GopherQualityFilter
from datatrove.pipeline.writers import JsonlWriter, ParquetWriter
from datatrove.utils.typeshelper import Languages

LocalPipelineExecutor(pipeline=[
    JsonlReader("data/raw", text_key="text", id_key="id"),
    LanguageFilter(languages=[Languages.english, Languages.portuguese], exclusion_writer=JsonlWriter("data/rejects/lang")),
    GopherRepetitionFilter(exclusion_writer=JsonlWriter("data/rejects/repetition")),
    GopherQualityFilter(exclusion_writer=JsonlWriter("data/rejects/quality")),
    ParquetWriter("data/filtered", compression="zstd"),
], tasks=8, workers=8, logging_dir="logs/filter").run()
```

## 4. Deduplication
- Exact: hash normalized text (sha256/xxhash); also dedup by canonical URL or id; keep the earliest or most authoritative copy.
- Near-duplicate: MinHash over shingles (word 5-grams for prose, token n-grams for code) + LSH banding. With b bands of r rows, P(candidate | Jaccard s) = 1 − (1 − sʳ)ᵇ and the threshold is ≈ (1/b)^(1/r); datatrove's defaults (5-grams, 14 buckets × 8 hashes) put it near 0.72. Confirm candidates with exact Jaccard, cluster (union-find) and keep one per cluster.
```python
from datasketch import MinHash, MinHashLSH
def signature(text, n=5, num_perm=128):
    t = text.lower().split()
    m = MinHash(num_perm=num_perm)
    m.update_batch(" ".join(t[i:i + n]).encode() for i in range(max(1, len(t) - n + 1)))
    return m
lsh, kept = MinHashLSH(threshold=0.8, num_perm=128), []
for key, text in records:                # unique keys; keeps the first of each near-dup group
    m = signature(text)
    if not lsh.query(m):
        lsh.insert(key, m); kept.append(key)
```
  Beyond a few million documents use datatrove's stages (`MinhashDedupSignature` → `MinhashDedupBuckets` → `MinhashDedupCluster` → `MinhashDedupFilter`).
- Repeated spans (boilerplate paragraphs, license headers): exact-substring dedup via suffix arrays (datatrove `ESDatasetToSequence`/`ESMergeSequences`/`ESRangeRemover`) or sentence-level dedup (`SentenceDedupSignature` …).
- Semantic dedup (embedding cosine above a threshold) for paraphrase-heavy synthetic sets — inspect what it removes.
- Deduplicate train against validation/test jointly; a near-duplicate of a test item in train is leakage.

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

## 8. Synthetic data
1. Diversity by design: a taxonomy grid (topic × task type × difficulty × persona/format), real seed examples, varied instructions; sampling temperature adds surface variety, not coverage.
2. Structured generation; store generator model, prompt version, seed and parameters on every record; mark `source: synthetic`.
3. Verify: programmatic checks first, then an LLM judge with a rubric from a different model family than the generator, then human spot checks. Reject rather than repair.
4. Dedup (exact, near, semantic) and decontaminate — generators reproduce benchmark items.
5. Model collapse: training recursively on model outputs erodes the tails of the distribution (Shumailov et al., Nature 2024); keeping real data and accumulating rather than replacing data across generations avoids the collapse in controlled studies (Gerstgrasser et al., 2024). Track diversity (distinct-n, embedding coverage, topic entropy) per generation.
6. Check the generator's license and terms before using outputs for training.

## 9. Formats
- JSONL or Parquet with an explicit schema, UTF-8, a stable `id` and metadata columns (source, license, language, created_at, generator, filters passed, split).
- TRL conventions: standard (`text`; `prompt` + `completion`; `prompt` + `chosen` + `rejected`; unpaired `prompt` + `completion` + `label`) or conversational (`messages` as `{role, content}` lists; the same keys holding message lists). Tool-calling datasets add a `tools` column of JSON schemas typed `Json()` in `datasets.Features`. SFTTrainer takes language-modeling or prompt-completion data, DPOTrainer preference, GRPOTrainer and RLOOTrainer prompt-only, KTOTrainer unpaired preference.
- Keep conversations unrendered; render with the target model's template at training time (`tokenizer.apply_chat_template(messages, tokenize=False)`), inspect rendered samples and the assistant-only loss mask (`llm-finetuning`).
- Multimodal: media as files or URIs plus content hashes (or `datasets` `Image`/`Audio` features in Parquet), with per-asset license, resolution/duration and captions in separate fields.

## 10. Splits
- Choose the unit of independence first (user, author, document, repository, conversation, patient, time period) and split by group: scikit-learn `GroupShuffleSplit`, `GroupKFold`, `StratifiedGroupKFold`. Use near-duplicate cluster ids as groups.
- Forward-in-time deployment → temporal split (cutoff date, `TimeSeriesSplit`).
- Stratify imbalanced labels or domains; freeze the test set with a hash manifest; tune only on validation.
- LLM evals: private held-out sets, decontaminated against fine-tuning data in both directions.

## 11. Labeling
- Guidelines: task definition; each label with positive, negative and boundary examples; a decision procedure for ambiguous items; an explicit "unsure" option; common mistakes. Version them.
- Pilot 50–100 items with ≥2 annotators, measure agreement, revise, repeat until stable.
- Agreement: Cohen's κ for two raters (`sklearn.metrics.cohen_kappa_score`, `weights="quadratic"` for ordinal labels); Fleiss' κ for a fixed number of raters per item (`statsmodels.stats.inter_rater.aggregate_raters` → `fleiss_kappa`); Krippendorff's α for any number of raters and missing labels (`krippendorff.alpha(reliability_data=..., level_of_measurement="nominal")` — the package defaults to `"interval"`, wrong for categories). Report per-label confusion too; κ depends on prevalence.
- Production: seeded gold items to monitor annotators, adjudication of disagreements, LLM pre-labels only after measuring agreement with humans, with a control subset labeled blind.

## 12. Versioning, storage, documentation
- Parquet with zstd, shards of ~100–500 MB; inspect with DuckDB or polars. `datasets`: `load_dataset("parquet", data_files=...)`, `Dataset.push_to_hub(repo_id, private=True)`, consumers pin a revision (`hf-hub`).
- A dataset version = source snapshot hashes + pipeline commit + config; ship a manifest (rows and sha256 per shard) and a changelog. Large files: Hub repos (Xet storage) or DVC.
- Data card / datasheet: motivation; composition (sizes, languages, domains, synthetic share); collection; preprocessing waterfall; licenses and attribution; personal-data handling; known biases and gaps; intended and out-of-scope uses; maintenance and contact. Hub dataset cards carry YAML metadata (`license`, `language`, `task_categories`, `size_categories`, `pretty_name`, `configs`); the Hub serves Croissant metadata at `https://huggingface.co/api/datasets/<repo>/croissant`.

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
