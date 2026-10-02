# Collection, cleaning and deduplication

Part of `dataset-curation`.

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
