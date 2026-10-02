---
name: sec-local-servers
description: Use when a dev server, daemon or MCP server listens on the machine — loopback binding, auth tokens, Host and Origin checks, DNS rebinding.
---
# Secure defaults for local servers
Hub: `secure-coding`.

- Bind `127.0.0.1`/`::1`, not `0.0.0.0`. Docker: `-p 127.0.0.1:8080:8080` — a bare `-p 8080:8080` listens on every interface, and Docker's iptables rules bypass ufw-style host firewalls on Linux.
- Authenticate even on localhost (other local users, processes and web pages can reach it): a ≥ 128-bit random bearer token compared in constant time, or a Unix domain socket with 0600 permissions in a 0700 directory.
- DNS rebinding: reject requests whose `Host`/`Origin` is not in an allowlist (`localhost:<port>`, `127.0.0.1:<port>`).
- CORS: no `Access-Control-Allow-Origin: *` on sensitive routes; never reflect an arbitrary `Origin` together with `Access-Control-Allow-Credentials: true`; allowlist exact origins. WebSockets: check `Origin` on upgrade.
- No exposed debuggers or consoles (Werkzeug debugger, `node --inspect=0.0.0.0`); request logging on; shut down when idle.
- MCP servers over Streamable HTTP have spec-level rules too: `sec-llm-apps`. Exposing a service beyond the machine (Tailscale, reverse proxy): `self-hosting-ops`.

## Verify
- [ ] `lsof -nP -iTCP -sTCP:LISTEN` (macOS) or `ss -ltnp` (Linux) shows the port on 127.0.0.1/::1 only.
- [ ] A request without the token gets 401; a request with `Host: evil.example` or a foreign `Origin` gets rejected.
- [ ] A cross-origin `fetch` from another local port with credentials is refused (no reflected `Origin` + credentials).
