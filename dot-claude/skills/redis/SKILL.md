---
name: redis
description: Use for Redis or Valkey — data structures, TTLs, eviction, persistence, locks, streams.
---
# Redis and Valkey
Hub: `db-design`. Redis holds data you can rebuild or afford to lose a second of, unless persistence and replication are configured and tested.

## Versions and licence
- Redis 8.x is current (8.10.2, 2026-09-17; 8.8 and 8.6 branches maintained). Redis 8.0 and later are offered under RSALv2, SSPLv1 or AGPLv3 (pick one). Valkey (Linux Foundation fork of Redis 7.2.4, BSD) is at 9.1.2 (2026-08-31). Commands overlap heavily but newer features differ: check `INFO server` and the docs of the engine you run.
- Managed services and Docker images (`redis:8`, `valkey/valkey:9`) are the usual deployment; bind loopback or a private network and require auth (`sec-hardening` § Local servers).

## Data structures by job
| Job | Structure |
|---|---|
| Cache entry | string or hash with a TTL (`SET k v EX 300`) |
| Counter, rate limit | `INCR` + `EXPIRE` (fixed window) or a sorted set of timestamps (sliding window), done atomically in a Lua script or `MULTI` |
| Leaderboard, priority, time index | sorted set (`ZADD`, `ZRANGE … BYSCORE`) |
| Queue with consumer groups and acks | stream (`XADD`, `XREADGROUP`, `XACK`, `XAUTOCLAIM` for stuck entries) |
| Deduplication, membership | set; probabilistic: Bloom filter / HyperLogLog |
| Object with fields | hash; per-field TTLs with `HEXPIRE` (7.4+) |

- Key naming: `app:entity:id[:field]`; one key per object, not one giant hash. Avoid keys > a few MB and collections with millions of members in one key (slow deletes, replication spikes); `UNLINK` instead of `DEL` for big keys.
- Never `KEYS *` in production: iterate with `SCAN` (and `HSCAN`/`SSCAN`/`ZSCAN`).

## Caching patterns
- Cache-aside: read cache → miss → read DB → `SET … EX ttl`. Invalidate on write (delete the key) rather than updating it, to avoid racing writers.
- Stampede protection: jittered TTLs, a short lock per key while one client recomputes, or serve-stale-while-revalidate.
- Memory: set `maxmemory`; policy `noeviction` (errors on writes when full), `allkeys-lru` (the docs' rule-of-thumb default for caches), `allkeys-lfu`, `allkeys-lrm` (8.6+), `volatile-*` variants (only keys with a TTL; behave like `noeviction` when none have one), `volatile-ttl`. Leave headroom for replication/AOF buffers, which are not counted against `maxmemory`. Watch `keyspace_hits`/`keyspace_misses`, `evicted_keys`, `expired_keys` in `INFO stats`.

## Locks
- Single-instance lock: `SET lock:<name> <random-token> NX PX 30000`; release with a Lua script that deletes only if the value matches your token; keep the work shorter than the TTL or extend it. A Redis lock is advisory and unsafe across failover: protect the resource with a fencing token or a database constraint when correctness matters.

## Persistence and replication
- RDB snapshots (compact, can lose minutes) and/or AOF (`appendfsync everysec`: lose ≤ ~1 s). Pure caches may run without persistence.
- Replicas are asynchronous: acknowledged writes can be lost on failover. Sentinel or Cluster for HA; Cluster shards by hash slot, so multi-key operations need keys in one slot (`{tag}` hash tags).

## Clients
- One pooled client per process; set connect and command timeouts; pipeline batches; Lua scripts (`EVAL`/functions) for atomic read-modify-write.

## Verify
- [ ] Engine and version recorded (`INFO server`), licence fits the deployment.
- [ ] `maxmemory` and policy set deliberately; a fill test shows the expected behavior (evicts or errors).
- [ ] No `KEYS` in code; big-key scan done (`redis-cli --bigkeys`).
- [ ] Restore from RDB/AOF tested if the data matters; lock code tested with an expired-lock race.

## Sources
- Verified 2026-10-02 https://endoflife.date/api/redis.json and https://endoflife.date/api/valkey.json — Redis 8.10.2, Valkey 9.1.2; https://redis.io/blog/redis-8-ga/ — tri-licence from Redis 8.0.
- Verified 2026-10-02 https://redis.io/docs/latest/develop/reference/eviction/ — policy list incl. LRM (8.6+), `allkeys-lru` rule of thumb, `volatile-*` like `noeviction` without TTLs, buffer memory not counted, `INFO` fields.
- Verified 2026-10-02 https://redis.io/docs/latest/operate/rs/release-notes/ — hash-field expiration among 7.4 features.
- Unverified as of 2026-10-02: Valkey's fork point (7.2.4) and licence; `XAUTOCLAIM`, `redis-cli --bigkeys`, persistence and Cluster details (general knowledge — check the docs).
