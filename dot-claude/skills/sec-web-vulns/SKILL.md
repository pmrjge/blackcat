---
name: sec-web-vulns
description: Use when untrusted input reaches a sink — SQL/shell injection, path traversal, SSRF, XSS, CSRF, deserialization; auth is sec-authn-authz.
---
# Vulnerability classes and safe patterns
Hub: `secure-coding` (input principles, checklist, report format). Version notes are marked Verified or unverified (see Sources).

- **SQL injection (CWE-89):** parameters only — `cur.execute("SELECT * FROM t WHERE id = %s", (uid,))` (psycopg) or `?` (sqlite3). Identifiers via an allowlist or `psycopg.sql.Identifier`. ORM raw fragments (`text()`, raw SQL helpers) need the same care.
- **Command and argument injection (CWE-78, CWE-88):** no shell — `subprocess.run(["git", "log", "--", path], check=True)`; Node `execFile`/`spawn` without `shell: true`; Rust `Command` is shell-free. Put `--` before user operands so they cannot become options (e.g. `--upload-pack=...`). Never interpolate into `sh -c`.
- **Template injection (CWE-1336):** never compile user input as a template; pass it as data; Jinja2 with `autoescape=select_autoescape()`; untrusted templates only in `jinja2.sandbox.SandboxedEnvironment`.
- **Path traversal and link races (CWE-22, CWE-59, CWE-367):** resolve and confine (snippet below). Against a local attacker who can swap path components between check and use, open relative to a directory handle without following links: Linux `openat2` with `RESOLVE_BENEATH`/`RESOLVE_NO_SYMLINKS`, Go 1.24+ `os.Root` (unverified), Rust `cap-std`. Archives: validate every member name (zip slip) and cap total size and count; Python `tarfile` extraction with `filter="data"` (the default only from 3.14; Verified, see Sources).
- **SSRF (CWE-918):** any server-side fetch of a user-influenced URL (webhooks, link previews, importers, OAuth metadata, agent fetch tools). Allowlist schemes and hosts where possible; otherwise resolve once, reject non-public addresses, connect to the vetted IP, and re-validate every redirect (or disable redirects). Validate the resolved address, not the string — decimal/octal/hex IPs, IPv4-mapped IPv6 and userinfo tricks defeat string checks. Server-side fetchers belong behind an egress proxy that enforces this (e.g. Smokescreen).
- **XSS (CWE-79), CSRF (CWE-352):** framework auto-escaping; no `innerHTML`/`dangerouslySetInnerHTML`/`v-html` with untrusted data; DOMPurify when HTML is required; Markdown renderers with raw HTML disabled or sanitized output. Strict CSP: `script-src 'nonce-<random>' 'strict-dynamic'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'`, plus `require-trusted-types-for 'script'` where supported and `X-Content-Type-Options: nosniff`. State-changing requests: SameSite cookies + CSRF token + `Origin` check.
- **Deserialization (CWE-502):** never load untrusted `pickle`/`joblib`/`shelve`/`marshal`, `yaml.load` without a safe loader, `numpy.load(allow_pickle=True)`, `torch.load(weights_only=False)` (the default has been `True` since PyTorch 2.6 — keep it; unverified), Java `ObjectInputStream`, .NET `BinaryFormatter`, PHP `unserialize`, Ruby `Marshal`. Use JSON/protobuf/MessagePack with schema validation, `yaml.safe_load`, safetensors for weights. `trust_remote_code=True` executes repository code — pin a reviewed revision.
- **XXE and entity bombs (CWE-611, CWE-776):** Python `defusedxml`; lxml `XMLParser(resolve_entities=False, no_network=True)` set explicitly; Java `setFeature("http://apache.org/xml/features/disallow-doctype-decl", true)`.
- **ReDoS (CWE-1333):** nested or overlapping quantifiers (`(a+)+`, `(a|aa)*`) on untrusted text. Use linear-time engines (RE2 via `google-re2`, Rust `regex`, Go `regexp`, .NET `RegexOptions.NonBacktracking`); Python `re` has no timeout — cap input length, use atomic groups/possessive quantifiers (3.11+; unverified).
- **Integer overflow and truncation (CWE-190, CWE-681):** allocation sizes (`n * size`), width/sign conversions, Rust release-mode wrapping, NumPy fixed-width types. Use `checked_mul`/`try_from`, `__builtin_mul_overflow` or C23 `ckd_mul`.
- **TOCTOU and temp files (CWE-367, CWE-377):** no `os.access()`/`exists()` before `open()` — open and handle the error; `O_CREAT|O_EXCL` for create-if-absent; `fstat` the opened descriptor; `tempfile.mkstemp()`/`NamedTemporaryFile()`/`TemporaryDirectory()` (never `tempfile.mktemp()` or fixed `/tmp` names); shell: `tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT`.
- **Also:** open redirects (allowlist targets), mass assignment (explicit field allowlists), business-logic races (transactions, unique constraints), log and header injection (strip CR/LF). MongoDB operator injection: `mongodb`.

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

## Verify
- [ ] Every attacker-controlled input traced to its sinks; each sink uses the safe pattern above.
- [ ] One abuse-case test per sink class found (injection string, `../` path, private-IP URL, `<script>` payload) fails before the fix and passes after.
- [ ] Parsers of untrusted bytes have a fuzz target (`test-fuzzing`).

## Sources
- Verified 2026-10-02 https://docs.python.org/3/library/tarfile.html — "Changed in version 3.14: Set the default extraction filter to `data`".
- Unverified as of 2026-10-02: Go 1.24 `os.Root`; PyTorch 2.6 `weights_only=True` default; Python 3.11 atomic groups and possessive quantifiers.
