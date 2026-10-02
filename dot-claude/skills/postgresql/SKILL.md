---
name: postgresql
description: Use for PostgreSQL — schema, indexes, EXPLAIN, vacuum, locks, safe migrations, pgvector, replication.
---
# PostgreSQL

## Scope and baseline
- Covers PostgreSQL as an application database and analytics store. Engine-neutral modeling and engine choice in `db-design`; migration workflow in `db-migrations`; generic SQL analysis in `data-analysis`; embeddings retrieval design in `rag-agents`; secrets handling in `secure-coding`.
- `references/operations.md` — read when tuning vacuum/bloat, partitioning, pooling (PgBouncer), memory settings, backups, replication, major upgrades or picking extensions.
- Versions: **18 is current** (Sep 2025, 18.6), 17 (17.11) and 16 (16.15) supported, no 19 yet; a major lasts five years. Verified 2026-10-02 https://endoflife.date/api/postgresql.json. `SELECT version();` before advising anything version-specific.
- PostgreSQL 18 notes: asynchronous I/O (`io_method`), `uuidv7()`, virtual generated columns (the default kind), `OLD`/`NEW` in `RETURNING`, B-tree skip scan, `EXPLAIN ANALYZE` shows buffers by default, OAuth authentication, `pg_upgrade --swap`. Check the release notes for anything else.
- Local: Postgres.app or `brew install postgresql@18`, or Docker `postgres:18` with a named volume. Never run experiments against production; `EXPLAIN ANALYZE` executes the statement.

## psql
- Connect with a service or URI; secrets in `~/.pgpass` (chmod 600) or `PGPASSWORD` from the environment, never in scripts or command lines.
- `\d+ table`, `\di+`, `\dt schema.*`, `\df`, `\dx` (extensions), `\x auto`, `\timing on`, `\e`, `\copy … to/from` (client-side files), `\watch 2`, `\gexec`.
- Scripts: `psql -X -v ON_ERROR_STOP=1 --single-transaction -f migration.sql`.

## Schema design
- Keys: `bigint generated always as identity`, or `uuid` (`uuidv7()` on 18 for index locality). Natural keys get `UNIQUE` constraints, not primary keys, unless stable.
- Types: `timestamptz` (never `timestamp` for instants), `text` + `CHECK (length(x) <= n)` rather than `varchar(n)`, `numeric` for money, `jsonb` (not `json`) for semi-structured data with a GIN index when queried, arrays sparingly, enums only for truly fixed sets (lookup table otherwise).
- Constraints are free correctness: `NOT NULL`, `CHECK`, `UNIQUE`, `EXCLUDE USING gist` (non-overlapping ranges), foreign keys — and **index every foreign-key column** on the referencing side (Postgres doesn't).
- Naming: snake_case, plural or singular consistently; no reserved words.

## Indexes
| Need | Index |
|---|---|
| Equality, range, sort, prefix `LIKE 'x%'` (C collation or `text_pattern_ops`) | B-tree (default); column order = equality columns first, then range/sort |
| Subset of rows (`WHERE deleted_at IS NULL`) | partial index |
| Computed predicate (`lower(email)`) | expression index |
| Index-only scans | `INCLUDE (cols)` covering index; needs a well-vacuumed visibility map |
| `jsonb` containment, arrays, full-text | GIN (`jsonb_path_ops` for `@>` only) |
| Substring / fuzzy text | GIN or GiST with `pg_trgm` |
| Ranges, geometry, nearest neighbour | GiST / SP-GiST |
| Huge append-only time series | BRIN on the time column |
| Vectors | pgvector HNSW (`vector_cosine_ops` etc.) or IVFFlat |
- Build on live tables with `CREATE INDEX CONCURRENTLY` (not in a transaction; check for `INVALID` indexes after a failure and drop them).
- Find unused (`pg_stat_user_indexes.idx_scan = 0` over a representative period) and duplicate indexes; each index slows writes and vacuum.

## Reading plans
- `EXPLAIN (ANALYZE, BUFFERS, SETTINGS) …` (BUFFERS is implied on 18). Compare estimated vs actual rows per node: 10× off → statistics problem (`ANALYZE`, raise the column's statistics target, `CREATE STATISTICS` for correlated columns).
- Watch for: `Seq Scan` with `Rows Removed by Filter` large on a selective predicate (missing index), `Sort Method: external merge` or hash `Batches > 1` (work_mem too small for that query), nested loops with huge `loops=` (bad estimate), `Heap Fetches` on index-only scans (vacuum), `Buffers: shared read` high (cold cache vs hot).
- Workload view: `pg_stat_statements` (top by `total_exec_time`, `mean_exec_time`, calls); `auto_explain` with `log_min_duration` for slow production queries.
- Rewrite before tuning: `EXISTS` over `IN (subquery)` with NULLs, keyset pagination (`WHERE (created_at, id) < ($1, $2) ORDER BY … LIMIT n`) over `OFFSET`, avoid functions on indexed columns, CTEs are inlined unless `MATERIALIZED`.

## Migrations without downtime
- Always `SET lock_timeout = '5s'` (and `statement_timeout`) in migrations; retry rather than queue behind a long query while blocking everyone.
- Safe patterns: `ADD COLUMN` with a constant default is metadata-only (11+); `NOT NULL` via `ADD CONSTRAINT … CHECK (x IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → `SET NOT NULL`; foreign keys `NOT VALID` then `VALIDATE`; indexes `CONCURRENTLY`; renames and type changes via expand/contract (`db-migrations`).
- Dangerous: changing a column type (rewrite), `ALTER TABLE … SET NOT NULL` on a big table without the CHECK trick, adding a volatile default, `CLUSTER`, `VACUUM FULL`.
- Tools, expand/contract, backfills, rollback and testing on a copy: `db-migrations`.

## Transactions and concurrency
- Default READ COMMITTED; REPEATABLE READ or SERIALIZABLE need retry loops on SQLSTATE `40001` (and `40P01` deadlocks).
- Queues: `SELECT … FOR UPDATE SKIP LOCKED LIMIT n`. Upserts: `INSERT … ON CONFLICT (key) DO UPDATE`; `MERGE` (15+, `RETURNING` since 17). Advisory locks for app-level mutexes.
- Keep transactions short; never hold one open across network calls to other services.

## Security
Roles with least privilege (app role owns nothing it doesn't need; separate migration role), `REVOKE CREATE ON SCHEMA public FROM PUBLIC` (default since 15), row-level security for multi-tenant tables, `scram-sha-256` auth, TLS for remote connections, parameterized queries only (psycopg 3 `%s` placeholders, asyncpg `$1`, JDBC `?`) — never string-built SQL.

## Drivers and tests
psycopg 3 (sync/async, `COPY` support) or asyncpg in Python; SQLAlchemy 2 for ORM; node-postgres; JDBC with HikariCP. Tests against a real Postgres (Testcontainers, a Docker service, or a per-test transaction rolled back), never SQLite as a stand-in.

## Agent access in this stack
psql via Bash is the default. db-engineer runs the `postgres` server inline (Postgres MCP Pro, `postgres-mcp==0.3.0 --access-mode=restricted`: read-only queries, EXPLAIN plans, index recommendations, health checks) with `DATABASE_URI` from stack.env; for other agents mcp-broker mounts the same server from the magg catalog on request. Verified 2026-10-02 .claude-work/agents-p2/mcp-vetting.md (https://pypi.org/project/postgres-mcp/, https://registry.npmjs.org/mongodb-mcp-server).

## Checklist
Version known · plan read with actuals and buffers · index justified by a plan · FK columns indexed · migration lock-safe with lock_timeout and tested on a copy · backups restore-tested · no secrets in files.
