---
name: game-netcode
description: Use for multiplayer netcode — server authority, prediction, rollback, interpolation.
---
# Game netcode

Baseline: `game-graphics` (fixed timestep, determinism). Engine specifics: `game-engines`. Server hosting: `self-hosting-ops`, `container-images`.

## Pick the model from the game
| game | model |
|---|---|
| shooters, action with many players | server-authoritative + client-side prediction + reconciliation + entity interpolation + lag compensation for hits |
| fighting games, 2–8 players, small state, deterministic sim | rollback (GGPO-style: GGRS in Rust, engine plugins) |
| RTS with thousands of units | deterministic lockstep (send inputs only) |
| co-op, casual, turn-based | server- or host-authoritative with simple state sync; turn-based over reliable messages |
| MMO-scale | interest management/sharding on top of server authority |
Peer-hosted ("listen server") games trust the host: state it when cheating matters.

## Core rules
- The server owns the truth; clients send **inputs** (with sequence numbers and tick), never authoritative state. Validate every input server-side (rates, ranges, cooldowns, line of sight).
- Fixed simulation tick (e.g. 30/60 Hz) on server and clients, decoupled from render rate; tick numbers on every message.
- Prediction: the client simulates its own inputs immediately, keeps a buffer of unacknowledged inputs, and on each authoritative snapshot rewinds to it and replays pending inputs. Correct visual error smoothly (error offset decay), not by snapping.
- Interpolation: remote entities render ~100 ms (2–3 snapshots) in the past, interpolating between snapshots; extrapolate only briefly.
- Lag compensation: the server rewinds hitboxes to the shooter's view time (bounded, e.g. ≤ 200 ms) to resolve hits.
- Rollback: deterministic simulation is mandatory (no floats whose results differ across platforms/compilers unless controlled; fixed-point or strict float settings; no iteration over hash maps; seeded RNG in the state); state save/restore must be cheap; input delay of 1–3 frames trades latency for fewer rollbacks.
- Bandwidth: delta-compress snapshots against the last acknowledged one; quantize (positions to mm, angles to 16 bits); prioritize by relevance; budget bytes per client per tick.

## Transport
- UDP-based with reliability layers per channel: unreliable-sequenced for state, reliable-ordered for events and RPCs. Libraries: GameNetworkingSockets, ENet, Netcode for GameObjects/Entities (Unity), Unreal replication (Iris), Godot `MultiplayerAPI` + ENet/WebRTC, lightyear/renet (Bevy).
- Browsers: WebRTC data channels or WebTransport; WebSocket (TCP) only for turn-based or lobby traffic.
- Encryption and authentication on every connection (DTLS/QUIC or the library's secure mode); session tokens from a backend, never trusting a client-supplied player ID.
- NAT traversal through relays (Steam Datagram Relay, TURN) for P2P.

## Testing
- Simulate bad networks on every feature: latency 50/150/300 ms, jitter, 1–5 % loss, reordering. Tools: `tc netem` (Linux), Network Link Conditioner (macOS), clumsy (Windows) — they need admin rights and change machine-wide network settings: ask the user first and undo after. Prefer the library's built-in network simulator when it has one.
- Determinism tests for rollback/lockstep: run the same input log on two builds/platforms and compare state checksums every tick; desync detection with checksums in production.
- Bots/headless clients for load tests; measure server tick time and bandwidth per client.
- Record and replay input logs to reproduce bugs.

## Security
Server-side validation of everything; rate limits; no secret game state sent to clients that shouldn't see it (wallhacks); anti-cheat is a layer on top, not a substitute. Load tests and scans only against the user's own servers.

## Pitfalls
Simulating on render frames; trusting client positions or hit claims; snapping corrections; RPCs for continuous state; reliable channel for everything (head-of-line blocking); nondeterminism from unordered containers or uninitialized memory in rollback games.

## Verify
Feature tested at 150 ms + 2 % loss without visible snapping beyond the stated tolerance · desync checksums equal across platforms (deterministic models) · bandwidth per client and server tick time measured against budget · server rejects forged inputs in a test.
