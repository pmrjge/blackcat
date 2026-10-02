---
name: api-design
description: Use for designing or changing HTTP, gRPC or event APIs — resources, errors, pagination, idempotency, versioning.
---
# API design

## Scope
HTTP/JSON, gRPC and event (message) interfaces between services or to clients. Contract tests and schema fuzzing: `test-contract-snapshot`. AuthN/Z: `sec-authn-authz`. Retries, idempotency and delivery guarantees across services: `dist-systems`.

## Contract first
- Write the contract before the code: OpenAPI for HTTP (3.1/3.2), `.proto` for gRPC, AsyncAPI or a schema registry for events. Generate server stubs/clients or validate requests against it; the contract file lives in the repo and is reviewed like code.
- Lint the contract in CI (e.g. Spectral for OpenAPI, `buf lint` for protobuf — commands unverified as of 2026-10-02) and diff it against the released version for breaking changes (oasdiff, `buf breaking`).

## Resource and method design (HTTP)
- Nouns for resources, HTTP methods for actions with their semantics: GET safe and cacheable, PUT/DELETE idempotent, POST neither, PATCH partial (JSON Merge Patch or JSON Patch — say which).
- Status codes by meaning: 200/201 (with `Location`)/204, 400 malformed, 401 unauthenticated, 403 forbidden, 404 not found (also for objects the caller may not see), 409 conflict, 412 precondition failed, 422 semantically invalid, 429 rate-limited (with `Retry-After`), 5xx only for server faults.
- Errors in one machine-readable shape everywhere: Problem Details (`application/problem+json`: `type`, `title`, `status`, `detail`, `instance`, plus extension fields such as per-field errors). Never leak stack traces or internal ids.
- Pagination: cursor/keyset (`?after=<opaque cursor>&limit=`) over offset for large or changing collections; return the next cursor; cap `limit`.
- Filtering and sorting: explicit allowlisted fields; document defaults; stable sort with a unique tiebreaker.
- Concurrency control: `ETag` + `If-Match` on updates (412 on mismatch) to prevent lost updates.
- Idempotent retries for POST: an `Idempotency-Key` header stored with the response for a window (the IETF header draft is expired, so document your semantics); same key + different body → 422/409.
- Long operations: 202 + a status resource (or webhooks), never a request that hangs for minutes.
- Times in RFC 3339 UTC; money as decimal strings or integer minor units with a currency; ids opaque strings.

## gRPC and events
- Protobuf evolution: never reuse or renumber field numbers (mark removed ones `reserved`), add fields as optional, don't change types; use well-known types for time and durations; deadlines on every call; map errors to canonical status codes with details.
- Events: past-tense names (`order.paid`), an envelope with id, type, time, source and schema version (CloudEvents-style); consumers tolerate unknown fields and duplicates; publish through an outbox (`dist-systems`).

## Versioning and change
- Additive changes are compatible (new optional fields, new endpoints, new enum values only if clients were told to tolerate unknowns). Breaking: removing/renaming fields, tightening validation, changing types, defaults or semantics.
- Prefer evolving one version; when a break is unavoidable, a new major version (`/v2` or a media-type version) runs alongside the old with a published deprecation window (`Deprecation`/`Sunset` headers — header status unverified as of 2026-10-02).
- Clients: be liberal in what you accept (ignore unknown fields), strict in what you send.

## Verify
- [ ] Contract file updated in the same change; lint clean; breaking-change diff against the last release reviewed (empty, or a new major version).
- [ ] Every endpoint documents auth, errors (with examples), pagination, limits and idempotency.
- [ ] Contract tests or schema-based tests pass (`test-contract-snapshot`); a client generated from the contract compiles.

## Sources
- Verified 2026-10-02 https://spec.openapis.org/oas/ — OpenAPI 3.2.1 is the latest published version (3.2.0 before it).
- Verified 2026-10-02 https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/ — Idempotency-Key header: draft-07 (2025-10-15), expired, not an RFC.
- Unverified as of 2026-10-02: RFC numbers for Problem Details (RFC 9457) and HTTP Semantics (RFC 9110); oasdiff/buf/Spectral command syntax.
