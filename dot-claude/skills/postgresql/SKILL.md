---
name: postgresql
description: Load before designing, querying, tuning, migrating, backing up or upgrading a PostgreSQL database — psql, schema and types, indexes (B-tree, GIN, GiST, BRIN, partial, covering), EXPLAIN ANALYZE reading, statistics, MVCC and vacuum, locks and zero-downtime migrations, isolation and retries, partitioning, pgvector and PostGIS, pooling, replication, security.
---
# PostgreSQL

## Scope and baseline
- Covers PostgreSQL as an application database and analytics store. Generic SQL analysis in `data-analysis`; embeddings retrieval design in `rag-agents`; secrets handling in `secure-coding`.
- Versions (endoflife.date, Sep 2026): **18 is current** (Sep 2025, 18.6), 17 and 16 supported; a major lasts five years. `SELECT version();` before advising anything version-specific.
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

## MVCC, vacuum, bloat
- Updates write new row versions; autovacuum reclaims them. Long-running or idle-in-transaction sessions block cleanup: set `idle_in_transaction_session_timeout`, find them in `pg_stat_activity`.
- Hot tables: per-table `autovacuum_vacuum_scale_factor` (e.g. 0.02) and `autovacuum_vacuum_cost_limit`; monitor `n_dead_tup`, `last_autovacuum`; transaction-ID age (`age(datfrozenxid)`) for wraparound.
- `VACUUM FULL` rewrites and locks the table — use pg_repack for online compaction.

## Migrations without downtime
- Always `SET lock_timeout = '5s'` (and `statement_timeout`) in migrations; retry rather than queue behind a long query while blocking everyone.
- Safe patterns: `ADD COLUMN` with a constant default is metadata-only (11+); `NOT NULL` via `ADD CONSTRAINT … CHECK (x IS NOT NULL) NOT VALID` → `VALIDATE CONSTRAINT` → `SET NOT NULL`; foreign keys `NOT VALID` then `VALIDATE`; indexes `CONCURRENTLY`; renames via expand/contract (new column, dual write, backfill in batches, switch reads, drop old).
- Dangerous: changing a column type (rewrite), `ALTER TABLE … SET NOT NULL` on a big table without the CHECK trick, adding a volatile default, `CLUSTER`, `VACUUM FULL`.
- Migration tools: follow the repo (Alembic, Flyway, Liquibase, sqlx, dbmate, Prisma). Every migration reversible and tested on a copy with production-like volume.

## Transactions and concurrency
- Default READ COMMITTED; REPEATABLE READ or SERIALIZABLE need retry loops on SQLSTATE `40001` (and `40P01` deadlocks).
- Queues: `SELECT … FOR UPDATE SKIP LOCKED LIMIT n`. Upserts: `INSERT … ON CONFLICT (key) DO UPDATE`; `MERGE` (15+, `RETURNING` since 17). Advisory locks for app-level mutexes.
- Keep transactions short; never hold one open across network calls to other services.

## Scale and operations
- Partitioning (declarative RANGE/LIST/HASH) for very large tables with a natural pruning key (time); indexes are per partition; detach/drop old partitions instead of `DELETE`.
- Connections are processes: keep `max_connections` modest and put PgBouncer (transaction pooling: no session state such as `SET`, advisory session locks or temp tables across statements) or the driver's pool in front.
- Memory starting points: `shared_buffers` ≈ 25 % RAM, `effective_cache_size` ≈ 50–75 % RAM, `work_mem` small globally (per sort/hash node per connection) and raised per query/role, `maintenance_work_mem` 1–2 GB for index builds, `random_page_cost` 1.1 on SSD. Measure after each change.
- Backups: `pg_dump -Fc` (or `-Fd -j 8`) + `pg_restore -j 8` for logical; `pg_basebackup` + WAL archiving (pgBackRest, Barman, WAL-G) for point-in-time recovery. A backup counts only after a test restore.
- Replication: streaming (physical) for HA/read replicas; logical (publications/subscriptions) for selective replication and near-zero-downtime major upgrades. `pg_upgrade --link` (or `--swap` on 18) for in-place upgrades; run `vacuumdb --all --analyze-in-stages` afterwards (18 carries planner statistics over, still verify).

## Extensions worth knowing
pg_stat_statements, pg_trgm, pgvector (HNSW `m`, `ef_construction`; `SET hnsw.ef_search`; filter + vector queries may need iterative scans — check the pgvector version's docs), PostGIS, pgcrypto, citext, TimescaleDB, pg_partman, pg_cron, pg_repack, hypopg (hypothetical indexes).

## Security
Roles with least privilege (app role owns nothing it doesn't need; separate migration role), `REVOKE CREATE ON SCHEMA public FROM PUBLIC` (default since 15), row-level security for multi-tenant tables, `scram-sha-256` auth, TLS for remote connections, parameterized queries only (psycopg 3 `%s` placeholders, asyncpg `$1`, JDBC `?`) — never string-built SQL.

## Drivers and tests
psycopg 3 (sync/async, `COPY` support) or asyncpg in Python; SQLAlchemy 2 for ORM; node-postgres; JDBC with HikariCP. Tests against a real Postgres (Testcontainers, a Docker service, or a per-test transaction rolled back), never SQLite as a stand-in.

## Agent access in this stack
psql via Bash is the default. The `postgres` catalog server (Postgres MCP Pro, restricted/read-only mode: EXPLAIN plans, index recommendations, health checks) is mounted on request by mcp-broker with `DATABASE_URI` from stack.env.

## Checklist
Version known · plan read with actuals and buffers · index justified by a plan · FK columns indexed · migration lock-safe with lock_timeout and tested on a copy · backups restore-tested · no secrets in files.
