---
name: sqlite
description: Use for SQLite as an application database — WAL, concurrency, busy timeouts, schema changes, backups.
---
# SQLite as an application database
Hub: `db-design`. Connection pragmas (`journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout`), `STRICT` tables and Python `sqlite3` bulk loading: `dataframes-duckdb` § SQLite. This module covers running an app on it.

## Version
- Latest SQLite is 3.53.4 (2026-07-24). The library is whatever the language runtime links: check `select sqlite_version();` (Python: `sqlite3.sqlite_version`), not the CLI's version.

## Fit
- Good: one machine, many readers, modest write rate, embedded and local-first apps, edge/serverless with a replicated file, test fixtures for SQLite-backed code. Not good: many machines writing to one file, network filesystems (NFS/SMB locking is unreliable), very high concurrent write throughput.
- Not a stand-in for PostgreSQL or MySQL in tests of code that targets them (types, locking and SQL dialect differ).

## Concurrency
- One writer at a time, even in WAL; readers don't block the writer. Start write transactions with `BEGIN IMMEDIATE` so the write lock is taken up front — a deferred transaction that upgrades from read to write can fail with `SQLITE_BUSY` regardless of `busy_timeout`.
- Keep write transactions short; batch many inserts in one transaction (orders of magnitude faster than autocommit per row).
- One connection per thread (or a pool); in async servers, funnel writes through one writer task or connection.
- WAL grows until checkpointed: long-lived readers prevent checkpoints; monitor the `-wal` file size and run `PRAGMA wal_checkpoint(TRUNCATE)` in quiet periods if it grows.

## Schema changes
- `ALTER TABLE` supports only: rename table, rename column, add column, drop column, and (3.53.0+) set/drop `NOT NULL`. `ADD COLUMN` cannot add a `PRIMARY KEY`/`UNIQUE` column, a non-constant default or a `STORED` generated column; a `NOT NULL` column needs a non-NULL default. `DROP COLUMN` fails if the column is indexed, part of a key, `UNIQUE`, used by a foreign key, a `CHECK`, a generated column, a partial index, a trigger or a view.
- Anything else (type change, constraints, reordering) uses the 12-step rebuild — in this order:
```sql
PRAGMA foreign_keys=OFF;
BEGIN;
-- save: SELECT type, sql FROM sqlite_schema WHERE tbl_name='X';
CREATE TABLE new_X (...);               -- desired shape
INSERT INTO new_X SELECT ... FROM X;
DROP TABLE X;
ALTER TABLE new_X RENAME TO X;          -- never rename the old table first: it corrupts trigger/view/FK references
-- recreate indexes, triggers, views
PRAGMA foreign_key_check;
COMMIT;
PRAGMA foreign_keys=ON;
```
- Migration tools: the repo's (Alembic batch mode for SQLite, sqlx, dbmate, Django) — check that they implement this rebuild for unsupported changes.

## Backups and replication
- Never copy the database file while it is open for writing (the `-wal` file holds committed data). Use the online backup API (`.backup` in the CLI, `Connection.backup` in Python) or `VACUUM INTO 'backup.db'`, then verify the copy with `PRAGMA integrity_check`.
- Streaming replication to object storage: Litestream; test a restore.

## Verify
- [ ] Runtime SQLite version recorded.
- [ ] Concurrent-write test: N writers with `BEGIN IMMEDIATE` and `busy_timeout` finish without `SQLITE_BUSY` errors.
- [ ] Schema change tested on a copy, `PRAGMA foreign_key_check` and `PRAGMA integrity_check` clean.
- [ ] Backup restored and checked once.

## Sources
- Verified 2026-10-02 https://endoflife.date/api/sqlite.json — 3.53.4 (2026-07-24).
- Verified 2026-10-02 https://www.sqlite.org/lang_altertable.html — supported ALTER forms, `NOT NULL` set/drop in 3.53.0, ADD/DROP COLUMN limits, the 12-step procedure and the rename-order warning.
- Unverified as of 2026-10-02: `BEGIN IMMEDIATE`/`SQLITE_BUSY` upgrade behavior, `VACUUM INTO` (3.27), checkpoint pragma, Litestream status, Alembic batch mode (general knowledge — check the docs).
