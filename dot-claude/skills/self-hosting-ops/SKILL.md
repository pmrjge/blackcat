---
name: self-hosting-ops
description: Use for personal services on a Linux box — Tailscale, Forgejo, systemd, Caddy, backups, firewalls.
---
# Self-hosting over Tailscale (and the infrastructure around it)

Verified Sep 2026: Forgejo 16 (15 = LTS) docs and Dockerfiles, Forgejo Runner 13, Tailscale CLI docs, Podman
Quadlet man page, Docker Compose v5 (`docker compose config` on the compose file in `ops-forgejo`), systemd 255
(`systemd-analyze verify` on the units in `ops-systemd-caddy`), restic 0.19.1 and borg 1.4.5 (commands were run).
Latest releases Verified 2026-10-02 (`git ls-remote --tags`): Forgejo 16.0.5 and 15.0.9 (codeberg.org/forgejo/forgejo),
Docker Compose 5.6.0, restic 0.19.1, borg 1.4.5 (borg 2 still 2.0.0b25), Caddy 2.11.6, Tailscale 1.104.0 (github.com).
Forgejo Runner 13: unverified (code.forgejo.org unreachable from the sandbox).

## Principles
- Private by default: services listen on `127.0.0.1` and are reached through the tailnet. Public exposure
  (Funnel or Caddy) is an explicit decision with app-level auth in front.
- Declarative and versioned: compose files, Quadlet/systemd units, Caddyfile, config minus secrets live in an
  ops git repo. Secrets and data never go in it.
- One change at a time, each after a fresh backup and with a written rollback. Ask the user before opening ports,
  enabling Funnel, editing the tailnet policy, deleting volumes/snapshots/backups, or major-version upgrades.
- Layout: `/srv/<svc>/{compose.yaml, .env (600), secrets/ (700; files 600), data/, runbook.md}`. Related skills:
  `linux-workstation` (host setup, firewall, Tailscale client), `git-workflows` (forge CLIs), `container-images`
  (building and scanning images — this skill runs them), `ci-cd-pipelines` (workflow files for the Forgejo
  runner in `ops-forgejo`), `terraform-opentofu` (infrastructure as code).

## Modules (load the one the task touches)
| Module | Load for |
|---|---|
| `ops-tailscale` | serve, Funnel, tags and grants policy, Tailscale SSH, exit nodes, certs |
| `ops-forgejo` | the Forgejo compose stack, app.ini, exposure, admin, Actions runner, dump, upgrades |
| `ops-systemd-caddy` | systemd units and timers, hardening, credentials, journald; Caddy reverse proxy |
| `ops-backups` | restic and borg, database dumps, 3-2-1, append-only remotes, restore drills |
| `k8s-ops` | Kubernetes workloads: manifests, kubectl, Helm/kustomize, debugging, rollbacks |
| `cloud-aws` | AWS CLI and accounts: SSO profiles, IAM, S3, costs, logging |
| `cloud-gcp` | gcloud and projects: ADC, service accounts, Workload Identity, Cloud Run, costs |
| `obs-otel` | OpenTelemetry traces, metrics, logs, the Collector, SLO alerts |
| `net-diagnostics` | layer-by-layer network debugging: DNS, routes, ports, TLS, MTU, packet captures |

Read `references/runbooks.md` for monitoring (uptime, dead-man pings, disk, SMART, certificates), the runbook template and the incident checklist.
Read `references/vpn-firewall.md` for WireGuard by hand and host firewalls (nftables, ufw, firewalld, macOS pf) with safe remote changes (no lockout).
Read `references/net-protocols.md` for protocol facts (DNS records, HTTP, TLS and ACME, IP ranges, IPv6).
Read `references/containers.md` when choosing Docker Compose or Podman Quadlet, pinning images, or running a container as a systemd unit.

## Secrets
- Env files and secret files: `chmod 600`, owned by the service user, git-ignored; commit `.env.example` with
  names only. Compose: `env_file:` or `secrets:` (mounted at `/run/secrets/<name>`, for images with `*_FILE`
  support). systemd: `LoadCredential=` or `EnvironmentFile=` (600).
- Never in: committed compose files, command lines (`ps` shows them), image layers (`docker history`), logs,
  runbooks. Rotate on any exposure and restart dependents.

## Verify
`docker compose config -q`, `systemd-analyze verify`, `caddy validate`, `tailscale serve|funnel status`; healthchecks
healthy; newest backup < ~26 h old, `restic check` passes, a restore drill on record; monitors green; `ss -tlnp` as intended.
Plus the Verify block of every module used.

## Report
Services and versions (tag@digest), exposure (tailnet or public, URLs), files changed (ops repo commit), secrets
touched (names only), backup status and last drill, monitoring added, open risks and follow-ups.
