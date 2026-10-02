# MongoDB operations and drivers (reference)
Read when choosing a shard key, setting up change streams, monitoring or profiling, backing up or restoring, importing/exporting, or configuring drivers and connection pools. Parent: `mongodb` SKILL.md.

## Scale and operations
- Sharding: choose the shard key for high cardinality, low frequency and non-monotonic writes (hashed for monotonic IDs, compound for range queries); a bad key is expensive to fix (resharding exists but costs). Queries without the shard key scatter-gather.
- Change streams for CDC (resume tokens; need replica sets).
- Monitoring: profiler (`db.setProfilingLevel(1, { slowms: 100 })`, `system.profile`), `serverStatus`, WiredTiger cache usage, replication lag (`rs.printSecondaryReplicationInfo()`), Atlas Performance Advisor.
- Backups: `mongodump --archive=app.gz --gzip` / `mongorestore` for logical copies (not consistent across shards without care); filesystem snapshots or Atlas/Ops Manager backups for production. Test restores.
- `mongoimport`/`mongoexport` for JSON/CSV interchange (they don't preserve all BSON types — use `--jsonFormat=canonical`).

## Drivers
- Python: PyMongo 4.x (includes the async API `AsyncMongoClient`; Motor is deprecated in its favor); ODMs Beanie or ODMantic when the repo uses them. Node: the official driver or Mongoose (schemas, middleware). Java: sync/reactive-streams drivers, Spring Data MongoDB. Rust: `mongodb` crate.
- One client per process (it pools connections); set `maxPoolSize`, timeouts (`serverSelectionTimeoutMS`, `timeoutMS` in newer drivers) and `retryWrites=true`.
