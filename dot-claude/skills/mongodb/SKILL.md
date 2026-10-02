---
name: mongodb
description: Use for MongoDB — document modeling, validation, ESR indexes, aggregation, transactions.
---
# MongoDB

## Scope and baseline
- Covers MongoDB as an application database (Community, Enterprise, Atlas). Engine choice and engine-neutral modeling in `db-design`; relational design in `postgresql`; migrations workflow in `db-migrations`; vector-retrieval design in `rag-agents`.
- `references/operations.md` — read when choosing a shard key, using change streams, monitoring/profiling, backups and restores, `mongoimport`/`mongoexport`, or driver and pool settings.
- Versions: endoflife.date lists 9.0 (2026-09-30, 9.0.2) as the newest cycle, then 8.3 (May 2026, 8.3.11); 8.2 reached EOL 2026-07-31; 8.0 (8.0.32, EOL 2029-10-31) is the widely deployed major. Verified 2026-10-02 https://endoflife.date/api/mongodb.json — check 9.0 release notes before relying on new features. `db.version()` first. Minor "rapid releases" reach Atlas before self-managed builds.
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

## Security
Authentication on (SCRAM-SHA-256 or x.509), TLS, `bindIp` restricted, least-privilege roles per app, field-level or queryable encryption for sensitive fields when required. **Query injection**: never pass user-supplied objects straight into filters — a JSON body `{"$ne": null}` becomes an operator; validate types and strip `$`-prefixed keys. Avoid `$where` and server-side JavaScript.

## Agent access in this stack
mongosh via Bash is the default. db-engineer runs the official `mongodb` server inline (`mongodb-mcp-server@3.0.5 --readOnly`, telemetry disabled) with `MDB_MCP_CONNECTION_STRING` from stack.env — find, aggregate, explain, schema sampling and index listing only; for other agents mcp-broker mounts the same server from the magg catalog on request. Verified 2026-10-02 .claude-work/agents-p2/mcp-vetting.md (https://pypi.org/project/postgres-mcp/, https://registry.npmjs.org/mongodb-mcp-server).

## Verify
Access patterns written down · no unbounded arrays · types consistent · validator in place · every frequent query has an ESR index confirmed by explain · transactions short with retries · backup restore-tested · no user input used as a raw filter.
