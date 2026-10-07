# PostgreSQL operations (reference)
Read when tuning vacuum or bloat, partitioning, connection pooling, memory settings, backups, replication, major upgrades or choosing extensions. Parent: `postgresql` SKILL.md.

## MVCC, vacuum, bloat
- Updates write new row versions; autovacuum reclaims them. Long-running or idle-in-transaction sessions block cleanup: set `idle_in_transaction_session_timeout`, find them in `pg_stat_activity`.
- Hot tables: per-table `autovacuum_vacuum_scale_factor` (e.g. 0.02) and `autovacuum_vacuum_cost_limit`; monitor `n_dead_tup`, `last_autovacuum`; transaction-ID age (`age(datfrozenxid)`) for wraparound.
- `VACUUM FULL` rewrites and locks the table — use pg_repack for online compaction.

## Scale and operations
- Partitioning (declarative RANGE/LIST/HASH) for very large tables with a natural pruning key (time); indexes are per partition; detach/drop old partitions instead of `DELETE`.
- Connections are processes: keep `max_connections` modest and put PgBouncer (transaction pooling: no session state such as `SET`, advisory session locks or temp tables across statements) or the driver's pool in front.
- Memory starting points: `shared_buffers` ≈ 25 % RAM, `effective_cache_size` ≈ 50–75 % RAM, `work_mem` small globally (per sort/hash node per connection) and raised per query/role, `maintenance_work_mem` 1–2 GB for index builds, `random_page_cost` 1.1 on SSD. Measure after each change.
- Backups: `pg_dump -Fc` (or `-Fd -j 8`) + `pg_restore -j 8` for logical; `pg_basebackup` + WAL archiving (pgBackRest, Barman, WAL-G) for point-in-time recovery. A backup counts only after a test restore.
- Replication: streaming (physical) for HA/read replicas; logical (publications/subscriptions) for selective replication and near-zero-downtime major upgrades. `pg_upgrade --link` (or `--swap` on 18) for in-place upgrades; run `vacuumdb --all --analyze-in-stages` afterwards (18 carries planner statistics over, still verify).

## Extensions worth knowing
pg_stat_statements, pg_trgm, pgvector (HNSW `m`, `ef_construction`; `SET hnsw.ef_search`; filter + vector queries may need iterative scans — check the pgvector version's docs), PostGIS, pgcrypto, citext, TimescaleDB, pg_partman, pg_cron, pg_repack, hypopg (hypothetical indexes).
