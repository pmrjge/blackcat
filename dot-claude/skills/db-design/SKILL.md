---
name: db-design
description: Load before choosing a database or designing a schema — engine choice, keys, constraints, indexes from queries.
---
# Database design (hub)

## Scope
- Engine-neutral modeling and the choice of engine; the engine skills hold syntax, tuning and operations. Dataframe and analytical SQL work (DuckDB, Parquet): `dataframes-duckdb`. Query injection and secrets: `sec-web-vulns`, `sec-secrets`.

## Choosing the engine
| Need | Default |
|---|---|
| Application data with relations, constraints, transactions, analytics on the same data | PostgreSQL (`postgresql`) |
| Existing MySQL/MariaDB estate, or a platform that ships it | MySQL (`mysql`) |
| Single process or single machine, embedded, local-first apps, tests of SQLite-backed code | SQLite (`sqlite`) |
| Documents read and written whole, flexible per-record shape, horizontal scale by key | MongoDB (`mongodb`) |
| Cache, rate limits, queues, locks, leaderboards; data you can rebuild | Redis or Valkey (`redis`) |
| Columnar analytics over files | DuckDB (`dataframes-duckdb`) |
| Full-text or hybrid search over documents | a search engine or Postgres full-text (`search-engines`) |

Pick the engine the repository already uses unless a requirement it cannot meet is written down.

## Modeling baseline
- Start from access patterns: list the queries, their frequency and latency budget, and the writes, before drawing tables or documents.
- Relational: normalize to 3NF by default; denormalize only for a measured read path, and keep the copy consistent by transaction, trigger or a rebuild job.
- Keys: a surrogate primary key (identity/auto-increment or time-ordered UUIDv7) plus `UNIQUE` constraints on natural keys; never a mutable business value as the primary key.
- Constraints in the database, not only in the app: `NOT NULL`, `CHECK`, `UNIQUE`, foreign keys. Every constraint the app relies on is one fewer class of corrupt rows.
- Types: instants as timezone-aware timestamps in UTC; money as exact decimals or integer minor units, never floats; enums only for truly fixed sets (lookup tables otherwise); JSON columns for genuinely schemaless parts, not to avoid design.
- Indexes follow queries: one per frequent filter/sort pattern, column order equality → sort → range, confirmed by the engine's plan output; every index costs writes.
- Soft delete, multi-tenancy (tenant id on every row + row-level filters), audit columns (`created_at`, `updated_at`, actor): decide once per schema, apply everywhere.
- Naming: snake_case, consistent singular or plural, no reserved words, foreign key columns named `<table>_id`.

## Modules
| Module | Load when |
|---|---|
| `db-migrations` | changing a live schema: tools, expand/contract, backfills, locks, rollback, testing on a copy |
| `postgresql` | anything PostgreSQL (refs: `references/operations.md`) |
| `mysql` | MySQL or MariaDB: InnoDB, online DDL, replication, tuning |
| `sqlite` | SQLite as an application database: concurrency, schema changes, backups |
| `mongodb` | document modeling, indexes, aggregation, transactions (refs: `references/operations.md`) |
| `redis` | Redis or Valkey: data structures, TTLs, eviction, persistence, locks, streams |

## Verify
- [ ] Access patterns written next to the schema; each frequent query has a supporting index confirmed by a plan (`EXPLAIN`, `explain()`).
- [ ] Constraints present for every invariant the app assumes; a test inserts a violating row and gets an error.
- [ ] Engine version recorded (`SELECT version();`, `db.version()`, `INFO server`) before version-specific advice.
- [ ] Tests run against the real engine (container or local instance), not a stand-in.
