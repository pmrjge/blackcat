---
name: dataframes-duckdb
description: Use to transform tabular data — pandas, polars, DuckDB, Parquet/Arrow; dtypes, joins, big files.
---
# Dataframes, DuckDB and SQLite

## Scope
Transforming and validating tables in Python and SQL-over-files. PostgreSQL servers → `postgresql`; MongoDB → `mongodb`; statistics on the result → `data-analysis`; charts → `data-visualization`; training-set hygiene → `dataset-curation`; spreadsheets as deliverables (formulas, formatting, Excel charts) → the `xlsx` skill. Ad-hoc work runs in the sci venv; projects pin versions with `uv add`.

## Versions (PyPI / release pages, 2026-09-29)
| Library | Current | Notes |
|---|---|---|
| pandas | 3.0.6 (3.0.0 on 2026-01-21) | Python ≥ 3.11, NumPy ≥ 1.26, PyArrow ≥ 13 optional |
| polars | 1.44.2 stable; **2.0.0rc2** on PyPI | 2.0 final not released yet — check PyPI before assuming 2.x |
| DuckDB | 1.5.6 (2026-09-28); 1.4.x is LTS (1.4.0 EOL 2026-11-17) | **2.0.0 planned 2026-10-21** (tentative) |
| SQLite | STRICT tables since 3.37.0 | check `sqlite3.sqlite_version` |

Print versions (`pl.__version__`, `pd.__version__`, `duckdb.__version__`) at the top of any analysis; behaviour below depends on them.

## Choosing the engine
- **DuckDB**: SQL over Parquet/CSV/JSON files and dataframes in place, larger-than-memory aggregations, joins across files; also reads Postgres/SQLite via `ATTACH`.
- **polars**: typed pipelines, expression API, lazy plans with predicate/projection pushdown.
- **pandas**: ecosystem interop (statsmodels, sklearn older APIs, plotting), small data, time-series resampling.
- Exchange through Arrow: `pl.from_pandas`, `df.to_arrow()`, `duckdb.sql("… FROM df")` scans pandas/polars/Arrow objects by variable name; pandas 3 has `DataFrame.from_arrow()` and the PyCapsule interface.

## pandas 3 — what breaks silently
- **Copy-on-Write is the only mode**: every indexing result behaves as a copy; chained assignment `df[df.a > 0]["b"] = 1` no longer writes; use `df.loc[df.a > 0, "b"] = 1`. `SettingWithCopyWarning` is gone; defensive `.copy()` calls are unnecessary. `inplace=True` methods now return `self`.
- **Default string dtype `str`** (PyArrow-backed if installed, else object-backed), missing value `NaN`. `df[c].dtype == object` checks break → `pd.api.types.is_string_dtype`. Non-strings can't be assigned into a `str` column.
- **Datetime resolution is inferred**: strings → `datetime64[us]`, `unit="s"` → `[s]`. `astype("int64")` on timestamps can be 1000× smaller than before → `as_unit("ns")` first.
- `zoneinfo` replaces `pytz`; offset aliases `M/Q/Y` removed (`ME/QE/YE`); `Day` is a calendar day; nullable-float arithmetic yields `NA`; groupby `observed=False` passes unobserved groups to `apply`/`agg`.
- New: `pd.col("a") + pd.col("b")` in `assign`/`loc`; `merge(how="left_anti")`.
- Upgrade path: pandas 2.3 warning-free first, then 3.0.

## polars — 2.0 changes to plan for
- `LazyFrame.collect()` defaults to the **streaming engine** in 2.0; `group_by`, joins and `unpivot` no longer guarantee row order → sort explicitly or `maintain_order=True` / `join(..., maintain_order="left")`.
- Choose the engine per query `lf.collect(engine="in-memory")`, process-wide `pl.Config.set_engine_affinity("in-memory")`, or env `POLARS_ENGINE_AFFINITY`.
- Removed/changed in 2.0: `LazyFrame.profile()`, `melt` (use `unpivot`), `with_row_count` (`with_row_index`), `join(join_nulls=)` (`nulls_equal=`), `streaming=` (`engine="streaming"`); `pl.concat(how="horizontal")` needs equal heights; `explode()` drops empty lists by default; signed int + `UInt64` supertype is `Int128`; lossy `is_in` and string→temporal casts raise; file-like objects are not rewound.
- Idioms on any version: `scan_parquet`/`scan_csv` + lazy + `collect` over `read_*`; expressions over `map_elements` (Python UDFs are slow and break streaming); `pl.Enum` for fixed categories; `df.glimpse()` / `lf.explain()` to check pushdown.

## DuckDB
```python
import duckdb
con = duckdb.connect()                               # or duckdb.connect("work.duckdb")
con.sql("SET memory_limit='8GB'; SET threads=8; SET temp_directory='/tmp/duck'")
con.sql("""COPY (SELECT * FROM read_parquet('raw/*.parquet', hive_partitioning=true)
                 WHERE ts >= '2026-01-01')
           TO 'out' (FORMAT parquet, PARTITION_BY (year, month), COMPRESSION zstd)""")
con.sql("ATTACH 'dbname=app host=localhost' AS pg (TYPE postgres, READ_ONLY)")
```
- `read_csv(..., auto_detect=true)` guesses types from a sample: pass `types={…}` or `all_varchar=true` for messy files; check `DESCRIBE`/`SUMMARIZE`.
- Spills to disk past `memory_limit` for most operators; keep `temp_directory` on a fast disk.
- `EXPLAIN ANALYZE` shows pushdown and row counts per operator. `.pl()`, `.df()`, `.arrow()` return results.
- LTS for long-lived pipelines (1.4.x); re-test on 2.0 before upgrading storage files.

## SQLite
- Per connection: `PRAGMA journal_mode=WAL; PRAGMA foreign_keys=ON; PRAGMA busy_timeout=5000;`. One writer at a time even in WAL; readers don't block the writer.
- `CREATE TABLE t(...) STRICT` (3.37+): types limited to INT/INTEGER/REAL/TEXT/BLOB/ANY; lossy inserts raise `SQLITE_CONSTRAINT_DATATYPE`. Without STRICT, type affinity silently stores `'abc'` in an INTEGER column.
- Python's `sqlite3`: use parameters (`?`), `executemany` in one transaction for bulk loads; `con.execute("PRAGMA integrity_check")` after bulk work.

## Joins and aggregates (every engine)
1. Assert key uniqueness on the side that should be unique before joining (`df.select(pl.col(k).is_duplicated().any())`, `df[k].is_unique`, `SELECT k, count(*) … HAVING count(*) > 1`).
2. Reconcile row counts after the join (inner vs left expectations; many-to-many blow-ups). pandas: `merge(validate="one_to_one"|"many_to_one", indicator=True)`.
3. Null keys: pandas matches NaN keys to each other in `merge`; polars and SQL do not (polars `nulls_equal=True` to opt in). State which you rely on.
4. Recompute a key total by a second route (another engine or query) before reporting (`data-analysis` §8).

## Dtypes and time
- Timestamps timezone-aware (`timestamptz`, `pl.Datetime("us", "UTC")`, `tz_localize` then `tz_convert`); never mix naive and aware.
- Integer columns with nulls: pandas nullable `Int64`, polars ints are nullable natively; CSV round-trips lose this — use Parquet.
- Money/decimals: `Decimal`/`DECIMAL(p,s)`, not float. Categoricals: polars `Enum` for known sets, pandas `category` with explicit categories.

## Validation
- Schemas at the boundary: pandera (0.33; pandas and polars backends) or polars `df.match_to_schema` / explicit `schema=` on read; fail loudly.
- Invariants as asserts in the pipeline: non-null keys, ranges, monotonic time, row counts per partition.
- Keep a profile (row count, nulls, min/max per column) before and after each stage in the job folder.

## Big files
Parquet with zstd, 128 MB–1 GB row groups, sorted by the common filter column; hive partitioning on low-cardinality columns only; predicate pushdown via lazy scans or DuckDB; CSV only at the edges. For files larger than RAM, prefer DuckDB or polars streaming over pandas chunking.

## Verify
- Library versions printed; key uniqueness asserted before joins, row counts reconciled after.
- Schemas validated at the boundary; null-key matching and row order stated where they matter.
- Key totals recomputed by a second route; a profile saved before and after each stage.

Sources (checked 2026-09-29): https://pandas.pydata.org/docs/whatsnew/v3.0.0.html · https://docs.pola.rs/releases/upgrade/2 · https://pola.rs/posts/announcing-polars-2 · https://pypi.org/project/polars/ (2.0.0rc2, 1.44.2) · https://duckdb.org/release_calendar.html · https://www.sqlite.org/stricttables.html · https://pypi.org/project/pandera/
