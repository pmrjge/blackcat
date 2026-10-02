---
name: ops-tailscale
description: Use for Tailscale on a server — node names, serve and Funnel, tags and grants policy, Tailscale SSH, exit nodes, certificates.
---
# Tailscale for self-hosted services

Part of `self-hosting-ops` (principles: private by default; ask before Funnel or policy edits). Checked against the
Tailscale CLI docs (Sep 2026); Tailscale 1.104.0 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/tailscale/tailscale`). Client install on a workstation: `linux-workstation`.

## Nodes and names
- Server nodes: disable key expiry in the admin console, or join with a tag (`tailscale up --advertise-tags=tag:server`,
  needs `tagOwners`; `set` has no tag flag). Prefer `tailscale set` (changes only the named flags) over `tailscale up`
  (refuses unless every non-default flag is repeated or `--reset` is given).
- MagicDNS names: `<host>.<tailnet>.ts.net`. Enable HTTPS certificates for the tailnet (admin console, DNS) before
  using serve/funnel/cert.

## Serve and Funnel
- **Serve** (tailnet only, automatic TLS):
  `tailscale serve --bg 3000` -> `https://<host>.<tailnet>.ts.net/` proxies to `localhost:3000`;
  `--https=8443`, `--set-path=/app`, raw TCP `tailscale serve --bg --tcp=2222 tcp://localhost:2222`.
  `tailscale serve status`; remove one: repeat the command with `off` (`tailscale serve --https=443 off`); all: `tailscale serve reset`.
- **Funnel** (public internet): same syntax with `tailscale funnel`; ports 443, 8443, 10000 only; a port can't be
  both served and funneled; requires the `funnel` node attribute; `tailscale funnel status`, `... off`, `tailscale funnel reset`.
- `tailscale cert <fqdn>` writes 90-day certs you must renew; prefer serve or Caddy, which renew themselves.

## Policy
Grants syntax; the default policy allows all, tighten it; groups/tags per the admin console:
```json
{"tagOwners": {"tag:server": ["autogroup:admin"]},
 "grants": [{"src": ["autogroup:member"], "dst": ["tag:server"], "ip": ["tcp:443", "tcp:2222"]},
            {"src": ["autogroup:admin"], "dst": ["tag:server"], "ip": ["*"]}],
 "ssh": [{"action": "check", "src": ["autogroup:admin"], "dst": ["tag:server"], "users": ["autogroup:nonroot"]}],
 "nodeAttrs": [{"target": ["tag:public"], "attr": ["funnel"]}]}
```

## SSH and exit nodes
- **Tailscale SSH**: `tailscale set --ssh`; it intercepts port 22 for tailnet traffic only (OpenSSH still serves
  other interfaces; authorized_keys untouched). It captures anything else on 22 from the tailnet, so give a
  forge's SSH another port (2222).
- **Exit node**: `/etc/sysctl.d/99-tailscale.conf` with `net.ipv4.ip_forward = 1` and
  `net.ipv6.conf.all.forwarding = 1`, `sudo sysctl -p /etc/sysctl.d/99-tailscale.conf`,
  `sudo tailscale set --advertise-exit-node`, approve in the admin console (Edit route settings).
  Clients: `tailscale set --exit-node=<host>`; off: `tailscale set --exit-node=`.

## Verify
- `tailscale serve status` and `tailscale funnel status` list exactly the intended mappings; `tailscale status` shows the node with its tag.
- From another tailnet device the HTTPS name answers; from outside the tailnet only funneled ports answer.
