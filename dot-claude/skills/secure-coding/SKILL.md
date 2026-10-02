---
name: secure-coding
description: Load before writing or reviewing code that handles untrusted input, secrets, auth, crypto, dependencies or LLM tools.
---
# Secure coding (hub)

## Scope and ground rules
- Covers: designing, writing and reviewing software that resists attack — web/API code, CLIs, data pipelines, local servers, LLM and agent applications, MCP servers.
- Related: `review-protocol` (severity rubric and review report format), `test-fuzzing` (fuzzing parsers of untrusted input), `rag-agents` (agent and RAG design), `claude-code-extensions` (permission rules and hooks in this stack).
- Ground rules: test only code and systems you own or are authorized to test; proof-of-concepts run locally against your own instance; never exfiltrate real data; when a scanner finds a secret, report its location and type, not its value.

## Input handling principles (always)
- Parse, don't sanitize: convert input into typed values at the boundary (pydantic, serde with `deny_unknown_fields`, zod), allowlists over denylists, limits on size, depth, count and time.
- Canonicalize before checking (Unicode normalization, path resolution, URL parsing) and use exactly the representation you checked.
- Encode for the sink at output time (HTML, SQL, shell, URL, JSON, logs). Fail closed; errors reveal nothing internal.
- Deny by default; least privilege for every credential, process and tool; no secret in code, logs, argv, URLs or prompts.

## Modules (load the one that matches the work)
| Module | Load when |
|---|---|
| `sec-threat-model` | starting a design or review: assets, entry points, trust boundaries, STRIDE, abuse cases |
| `sec-web-vulns` | code reaches a sink: SQL, shell, templates, paths, SSRF, XSS/CSRF, deserialization, XXE, ReDoS, overflow, TOCTOU |
| `sec-secrets` | storing, passing, logging or scanning secrets; leak response; randomness and token comparison |
| `sec-supply-chain` | adding, locking, auditing or publishing dependencies; cooldowns, install scripts, provenance |
| `sec-authn-authz` | sessions, JWTs, OAuth/OIDC, object-level authorization, password hashing, least privilege |
| `sec-crypto` | encryption, signatures, hashing, key handling, TLS settings |
| `sec-llm-apps` | LLM or agent apps, tool use, prompt injection, exfiltration channels, MCP servers |
| `sec-hardening` | locking down a service, container, host or CI runner after the code is right; dev servers, daemons and MCP servers listening locally |
| `sec-detection` | writing detection: security logging, SAST rules, Sigma/host rules, canaries |
| `sec-incident-response` | something may be compromised: triage, containment, evidence, rotation, postmortem |

## Review checklist
- [ ] Threat model written: assets, entry points, trust boundaries, top abuse cases.
- [ ] Every attacker-controlled input traced to its sinks: SQL, shell, filesystem, template, HTML, URL fetch, deserializer, regex, allocation size.
- [ ] Authentication on every entry point; authorization per object and per function; deny by default.
- [ ] No secrets in code, history, logs, argv, URLs or images; gitleaks/trufflehog clean.
- [ ] Lockfiles enforced; audits clean or triaged with reachability; new dependencies vetted by name and provenance.
- [ ] Crypto through vetted libraries: AEAD with correct nonces, argon2id/bcrypt, CSPRNG, TLS verification on.
- [ ] Local servers: loopback bind, auth, Host/Origin checks, CORS allowlist.
- [ ] LLM/agent: no side effect without confirmation, egress allowlist, no auto-rendered remote images, sandboxed execution, path guards, MCP servers vetted and pinned.
- [ ] Abuse-case tests present; parsers of untrusted input fuzzed.

## Report
Use the `review-protocol` format and severity rubric; every finding adds the CWE, an exploit scenario (preconditions → steps → impact), evidence (file:line, local PoC or scanner output), a code-level fix and the test that fails before and passes after.
```
VERDICT: pass | pass-with-fixes | fail
FINDINGS (most severe first):
- [CRITICAL] CWE-89 app/db.py:42 — user id concatenated into SQL — any user reads all rows with "' OR 1=1 --" — parameterize the query — test_user_lookup_rejects_injection
CHECKED: files and flows reviewed; scanners run (name + version)
NOT CHECKED: what remains unverified
TOP 3 HARDENING ACTIONS: ...
```
