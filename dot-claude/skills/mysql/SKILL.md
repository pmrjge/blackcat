---
name: mysql
description: Use for MySQL or MariaDB — InnoDB schema, online DDL, EXPLAIN, locking and isolation, replication.
---
# MySQL and MariaDB
Hub: `db-design` (modeling, engine choice); migrations workflow: `db-migrations`.

## Versions
- MySQL: 8.4 and 9.7 are the LTS lines (9.7.2, 2026-07-28; EOL 2034-04-30); other 9.x releases are short-lived innovation releases. MariaDB: 12.3 is the current LTS (12.3.3), 11.8 the previous one. MySQL and MariaDB have diverged (JSON storage, GTIDs, optimizer, system tables): never assume a feature carries over. `SELECT VERSION();` first.
- Local: Docker `mysql:8.4` / `mariadb:<lts>` with a named volume, or Homebrew; never experiment on production.

## Schema
- InnoDB only. `utf8mb4` with an explicit collation (`utf8mb4_0900_ai_ci` on MySQL 8+; the legacy `utf8` is 3-byte `utf8mb3`). Strict SQL mode on (`STRICT_TRANS_TABLES` is in the default `sql_mode`): without it invalid values are silently truncated.
- Primary key: `BIGINT UNSIGNED AUTO_INCREMENT` or a time-ordered binary UUID (`BINARY(16)`); InnoDB clusters rows by primary key, so random UUIDs fragment the table and every secondary index stores the PK.
- `DATETIME` vs `TIMESTAMP`: `TIMESTAMP` converts to UTC and has a 2038 range limit; store UTC in `DATETIME(6)` with the app owning the zone, or `TIMESTAMP` where the range suffices. Money: `DECIMAL(p,s)`.
- InnoDB creates an index for each foreign key automatically if none exists; still design composite indexes for your queries.

## Queries and plans
- `EXPLAIN FORMAT=TREE` and `EXPLAIN ANALYZE` (8.0.18+; executes the query) — watch `type: ALL` (full scan), `Using filesort`, `Using temporary`, and rows examined ≫ rows returned.
- Composite indexes: equality columns first, then range/sort; a range column stops later columns from being used for seeking. Covering indexes avoid PK lookups.
- `performance_schema` and `sys` schema (`sys.statements_with_runtimes_in_95th_percentile`, `sys.schema_unused_indexes`); slow query log with `long_query_time` for production.
- Pagination by keyset (`WHERE (created_at, id) < (?, ?) ORDER BY created_at DESC, id DESC LIMIT n`), not large `OFFSET`.

## Online DDL (MySQL 8.4)
- `INSTANT` is the default algorithm and can add a column at any position; each instant add/drop creates a row version — 64 maximum in 8.4 (255 as of 9.1.0), tracked in `INFORMATION_SCHEMA.INNODB_TABLES.TOTAL_ROW_VERSIONS`; at the limit, use `COPY`/`INPLACE` (a rebuild resets it). Not for `ROW_FORMAT=COMPRESSED`, tables with `FULLTEXT` indexes, or temporary tables.
- Adding a secondary index is in place and permits concurrent DML (not `FULLTEXT`/`SPATIAL`); changing a column's data type needs `ALGORITHM=COPY` (table rebuild, no concurrent DML); extending a `VARCHAR` is in place only while its length prefix stays 1 byte (< 256 bytes) or stays 2 bytes.
- State the algorithm and lock explicitly (`ALGORITHM=INSTANT` / `ALGORITHM=INPLACE, LOCK=NONE`) so the statement fails instead of silently copying. Every DDL needs a metadata lock: set `lock_wait_timeout` low and check for long transactions first.
- Large tables where native online DDL won't do: gh-ost (triggerless, binlog-based) or pt-online-schema-change (trigger-based) — unverified as of 2026-10-02; check their docs for current compatibility.

## Transactions and locking
- Default isolation is REPEATABLE READ with next-key (gap) locks: range updates lock gaps and can deadlock; keep transactions short, touch rows in a consistent order, retry on deadlock (error 1213) and lock-wait timeout (1205).
- Queues: `SELECT … FOR UPDATE SKIP LOCKED`. Upserts: `INSERT … ON DUPLICATE KEY UPDATE`.

## Operations
- Memory: `innodb_buffer_pool_size` ≈ 50–75 % of RAM on a dedicated host; `innodb_redo_log_capacity` sized for write bursts; measure after each change.
- Backups: logical `mysqldump --single-transaction --routines --triggers` (or MySQL Shell dump utilities) for small/medium data; physical (Percona XtraBackup, MariaDB `mariadb-backup`) for large; binlogs for point-in-time recovery. A backup counts only after a test restore.
- Replication: GTID-based asynchronous or semi-sync; Group Replication / InnoDB Cluster for HA; watch replica lag before and during migrations.
- Security: least-privilege users per app, `caching_sha2_password`, TLS, no `root` from the app, parameterized queries only.

## Verify
- [ ] Version and `sql_mode` recorded; strict mode on.
- [ ] Each new index justified by `EXPLAIN ANALYZE` before/after.
- [ ] DDL states `ALGORITHM`/`LOCK` and was timed on a production-sized copy; row-version count checked for INSTANT changes.
- [ ] Restore of the latest backup tested.

## Sources
- Verified 2026-10-02 https://endoflife.date/api/mysql.json — 8.4 LTS; 9.7 LTS (9.7.2, EOL 2034-04-30); https://endoflife.date/api/mariadb.json — MariaDB 12.3 LTS (12.3.3), 11.8 previous LTS.
- Verified 2026-10-02 https://dev.mysql.com/doc/refman/8.4/en/innodb-online-ddl-operations.html — INSTANT default and any-position add, 64 row versions (255 from 9.1.0), index add in place with concurrent DML, type change COPY only, VARCHAR rule.
- Unverified as of 2026-10-02: `EXPLAIN ANALYZE` since 8.0.18; default collation name; MySQL 8.0 EOL date; the other setting names, error codes and tool notes above (general knowledge — check the manual for the installed version).
