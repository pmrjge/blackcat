---
name: dist-systems
description: Use for designs spanning services — timeouts, retries, idempotency, consistency, queues.
---
# Distributed systems design

## Scope
Correctness and failure handling when work spans processes, machines or services: RPC, queues, caches, replicated databases. Model-checking a protocol: `formal-methods` `references/tla.md`. API contracts: `api-design`. Database specifics: `db-design` and its modules.

## Assume these failures
- Messages are lost, duplicated, delayed and reordered; a timeout does not tell you whether the request ran.
- Processes crash between any two steps, including between a database commit and the message that announces it; restarts replay.
- Clocks differ and jump; never order events across machines by wall-clock time alone.
- Partitions happen: decide per operation whether it stays available (accepting stale or conflicting data) or becomes unavailable (preserving consistency).

## Patterns that make failures survivable
- **Timeouts everywhere**, shorter than the caller's; propagate deadlines downstream.
- **Retries** only for idempotent or deduplicated operations, with exponential backoff, full jitter and a retry budget; never retry on 4xx-type errors; avoid retry storms across layers (retry at one layer).
- **Idempotency:** client-generated request ids or idempotency keys stored with the result; natural idempotence (set, not increment); unique constraints as the final guard.
- **Exactly-once is a property of the effect, not the delivery:** at-least-once delivery + idempotent consumers (dedup table keyed by message id, in the same transaction as the effect).
- **Transactional outbox:** write the business row and the outgoing event in one local transaction; a relay publishes from the outbox table. Inbox/dedup on the consumer side.
- **Sagas** for multi-service workflows: each step has a compensating action; orchestrated (a coordinator) or choreographed (events); persist the saga state.
- **Backpressure and load shedding:** bounded queues, reject early (429/503 with `Retry-After`), circuit breakers around failing dependencies, bulkheads (separate pools per dependency).
- **Leases and fencing tokens** for leader election and locks: a lock without a fencing token checked by the resource is advisory (`redis` § Locks).
- **Caches:** define staleness bounds; invalidate on write; protect against stampedes.

## Consistency vocabulary (say which one you need)
- Linearizable (single up-to-date copy), sequential, causal, read-your-writes, monotonic reads, eventual. Serializable isolation is about transactions, linearizability about single objects — they are different guarantees.
- Consensus (Raft, Paxos) for replicated state that must agree; use an existing implementation (etcd, a database's replication) rather than writing one.
- CRDTs for replicas that merge without coordination (counters, sets, text) when conflicts must resolve automatically.

## Observability
- A correlation/trace id on every request and message (OpenTelemetry-style context propagation); structured logs with it; metrics for queue depth, age of oldest message, retry and dead-letter counts.
- Dead-letter queues with alerting and a replay procedure.

## Verify
- [ ] Each cross-process step lists what happens on timeout, duplicate, reorder and crash-after-commit.
- [ ] Fault-injection tests: kill the consumer mid-message, duplicate deliveries, delay responses past the timeout — the end state is correct.
- [ ] Protocols with subtle interleavings are model-checked (`formal-methods` `references/tla.md`) before implementation.
- [ ] Dashboards show queue depth/age, retries and dead letters; alerts exist for each.

Content is general engineering knowledge without version-specific claims; tool names (etcd, OpenTelemetry) are pointers, not version statements.
