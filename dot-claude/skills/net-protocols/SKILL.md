---
name: net-protocols
description: Use for the protocol facts behind a network design or fix — DNS records, HTTP semantics, TLS and ACME, private ranges, IPv6.
---
# Network protocols: the working facts

Part of `self-hosting-ops` (principles). Debugging commands: `net-diagnostics`; web security headers and CORS in depth: `secure-coding`.

## DNS
- Records: `A`/`AAAA` (addresses), `CNAME` (alias; not at the zone apex and not next to other records of the same name — use the provider's ALIAS/flattening at the apex), `MX`, `TXT` (SPF, DKIM, verification), `SRV`, `CAA` (which CAs may issue), `NS`.
- TTL: lower it (e.g. 300 s) a full old-TTL period before a planned change, raise it again after; caches keep the old answer until the TTL runs out — "propagation" is cache expiry.
- Mail authentication: SPF (`v=spf1 … -all`), DKIM (selector TXT record), DMARC (`_dmarc` TXT, start with `p=none` and reports).

## HTTP
- HTTP/1.1 (one request at a time per connection), HTTP/2 (multiplexed over one TCP connection, needs TLS in browsers), HTTP/3 (over QUIC on UDP 443; advertised with `Alt-Svc`).
- Status codes: 301/308 permanent and 302/307 temporary redirects (307/308 keep the method); 401 = not authenticated, 403 = authenticated but not allowed; 409 conflict; 429 rate limited (honour `Retry-After`); 502/504 = the proxy could not reach the upstream or it timed out.
- Caching: `Cache-Control: max-age=…, immutable` for fingerprinted assets, `no-cache` (revalidate) for HTML, `no-store` for private data; validators `ETag` / `If-None-Match` give 304s.
- CORS is enforced by browsers only: the server lists allowed origins in `Access-Control-Allow-Origin`; credentials forbid `*`. It is not an access control for non-browser clients.

## TLS and certificates
- TLS 1.3 (and 1.2 for older clients); certificates name hosts in the Subject Alternative Name; servers send the full chain minus the root; SNI selects the certificate per hostname.
- ACME challenges: HTTP-01 (port 80 reachable), DNS-01 (TXT record; the only one for wildcards and hosts not reachable from the internet), TLS-ALPN-01 (port 443). Caddy and `tailscale serve` handle this automatically.
- `Strict-Transport-Security` (HSTS) pins browsers to HTTPS for its `max-age`; add `preload` only when every subdomain serves HTTPS for good.

## Addresses
- Private IPv4: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`; carrier-grade NAT `100.64.0.0/10` (Tailscale gives nodes addresses there); loopback `127.0.0.0/8`; link-local `169.254.0.0/16` (also cloud metadata at 169.254.169.254).
- IPv6: global unicast `2000::/3`, unique local `fc00::/7` (`fd00::/8` in practice), link-local `fe80::/10` (needs a zone, `fe80::1%en0`), loopback `::1`; hosts usually configure themselves (SLAAC) and have several addresses. A dual-stack service must listen and be firewalled on both families.
- TCP for reliable streams; UDP for DNS, QUIC, WireGuard, media. NAT rewrites addresses on the way out; inbound connections need a port forward, a relay or a tunnel.

## Verify
- Every protocol claim used in a design or fix is checked against the live system (`dig`, `curl -v`, `openssl s_client`) as in `net-diagnostics`, not assumed.
