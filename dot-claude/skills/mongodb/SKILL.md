---
name: mongodb
description: Load before modeling, querying, indexing, tuning, migrating or operating MongoDB — document design, validation, ESR indexes, aggregation, transactions, replication, sharding.
---
# MongoDB

## Scope and baseline
- Covers MongoDB as an application database (Community, Enterprise, Atlas). Relational design lives in `postgresql`; vector-retrieval design in `rag-agents`.
- Versions (endoflife.date, Sep 2026): 8.3 (May 2026) and 8.2 (Sep 2025) are the newest; 8.0 is the widely deployed major. `db.version()` first. Minor "rapid releases" reach Atlas before self-managed builds.
- Local: `brew tap mongodb/brew && brew install mongodb-community`, Docker `mongodb/mongodb-community-server`, or `atlas deployments setup --type local` (Atlas CLI, includes Search). Transactions and change streams need a replica set — even locally run a single-node set (`mongod --replSet rs0` then `rs.initiate()`).

## mongosh essentials
`mongosh "mongodb://127.0.0.1:27017/app"` (credentials from the environment, never on the command line in shared logs); `show dbs`, `use app`, `show collections`, `db.c.find({…}).sort({…}).limit(20)`, `db.c.countDocuments({…})`, `db.c.getIndexes()`, `db.c.stats()`, `db.currentOp()`, `db.killOp(id)`, `--eval` and `--file` for scripts, `EJSON.stringify` for exact types.

## Modeling (access patterns first)
- List the queries and their frequency before designing documents. Data read together is stored together.
- **Embed** when the child is owned by the parent, bounded in size, and read with it (addresses, line items). **Reference** when it is shared, unbounded or updated independently (users ↔ orders).
- Hard limit: 16 MB per document; practical limit much lower. **Unbounded arrays** (comments on a post, events on a device) are the classic anti-pattern — use the bucket pattern (one document per device-hour), a child collection, or the subset pattern (latest N embedded, rest referenced).
- Other patterns: extended reference (copy the few fields you display), computed (maintain totals on write), schema versioning (`schemaVersion` field + lazy migration), polymorphic collections with a type discriminator.
- Types matter: dates as BSON `Date` (not strings), money as `Decimal128`, IDs as `ObjectId` consistently (a string "abc" never matches `ObjectId("abc…")`), Int32 vs Int64 vs Double explicit where it matters.
- Validation: `$jsonSchema` validator on the collection (`collMod` to change), `validationLevel: "moderate"` during migrations, `validationAction: "error"` once clean.

## Indexes and explain
- **ESR rule** for compound indexes: Equality fields, then Sort fields, then Range fields.
- Kinds: compound, multikey (arrays; only one array field per compound index), partial (`partialFilterExpression`), unique (with partial for "unique if present"), TTL (`expireAfterSeconds` on a Date field), wildcard (unknown field names), text (basic; prefer Atlas Search for real search), 2dsphere, hidden (test removal safely), clustered collections.
- `db.c.find(q).sort(s).explain("executionStats")`: want `IXSCAN`, `totalKeysExamined ≈ totalDocsExamined ≈ nReturned`. `COLLSCAN`, a blocking `SORT` stage, or examined ≫ returned → index problem. `$indexStats` shows usage; drop unused indexes (every index costs writes and RAM).
- Build indexes on large live collections in a quiet window; rolling builds on replica sets when the build is heavy.

## Aggregation pipelines
- `$match` and `$sort` first (they can use indexes only at the start), then `$project`/`$set`, `$group`, `$lookup` (with `let`/`pipeline` for filtered joins; index the foreign field), `$unwind`, `$facet`, `$bucket`, `$setWindowFields`, `$densify`/`$fill`, `$merge`/`$out` for materialized results.
- Stages have a 100 MB memory limit per stage unless `allowDiskUse: true` (default on in recent versions for some stages — check explain). Test pipelines with `explain` too.
- Atlas Search (`$search`) and Atlas Vector Search (`$vectorSearch`) run on mongot; recent Community/Enterprise releases added them in preview — check your version before designing around them.

## Consistency and transactions
- Write concern `w: "majority"` for durability (default in modern versions), `j: true` implied; read concern `majority`/`snapshot`; read preference `primary` unless stale reads are acceptable.
- Multi-document transactions work on replica sets and sharded clusters; keep them short (default 60 s limit), retry on `TransientTransactionError` and commit on `UnknownTransactionCommitResult` (drivers' `withTransaction` does both). Prefer a document design that makes the update single-document atomic.
- Causal consistency via sessions when reading your own writes from secondaries.

## Scale and operations
- Sharding: choose the shard key for high cardinality, low frequency and non-monotonic writes (hashed for monotonic IDs, compound for range queries); a bad key is expensive to fix (resharding exists but costs). Queries without the shard key scatter-gather.
- Change streams for CDC (resume tokens; need replica sets).
- Monitoring: profiler (`db.setProfilingLevel(1, { slowms: 100 })`, `system.profile`), `serverStatus`, WiredTiger cache usage, replication lag (`rs.printSecondaryReplicationInfo()`), Atlas Performance Advisor.
- Backups: `mongodump --archive=app.gz --gzip` / `mongorestore` for logical copies (not consistent across shards without care); filesystem snapshots or Atlas/Ops Manager backups for production. Test restores.
- `mongoimport`/`mongoexport` for JSON/CSV interchange (they don't preserve all BSON types — use `--jsonFormat=canonical`).

## Drivers
- Python: PyMongo 4.x (includes the async API `AsyncMongoClient`; Motor is deprecated in its favor); ODMs Beanie or ODMantic when the repo uses them. Node: the official driver or Mongoose (schemas, middleware). Java: sync/reactive-streams drivers, Spring Data MongoDB. Rust: `mongodb` crate.
- One client per process (it pools connections); set `maxPoolSize`, timeouts (`serverSelectionTimeoutMS`, `timeoutMS` in newer drivers) and `retryWrites=true`.

## Security
Authentication on (SCRAM-SHA-256 or x.509), TLS, `bindIp` restricted, least-privilege roles per app, field-level or queryable encryption for sensitive fields when required. **Query injection**: never pass user-supplied objects straight into filters — a JSON body `{"$ne": null}` becomes an operator; validate types and strip `$`-prefixed keys. Avoid `$where` and server-side JavaScript.

## Agent access in this stack
mongosh via Bash is the default. The `mongodb` catalog server (official, `--readOnly`, telemetry off) is mounted on request by mcp-broker with `MDB_MCP_CONNECTION_STRING` from stack.env — find, aggregate, explain, schema sampling and index listing only.

## Checklist
Access patterns written down · no unbounded arrays · types consistent · validator in place · every frequent query has an ESR index confirmed by explain · transactions short with retries · backup restore-tested · no user input used as a raw filter.
