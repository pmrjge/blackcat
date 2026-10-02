---
name: ops-runbooks
description: Use to monitor a self-hosted service, write its runbook, or work through an incident; OpenTelemetry metrics and traces are in obs-otel.
---
# Monitoring, runbooks and incidents

Part of `self-hosting-ops` (principles, secrets). Metrics, traces and SLO alerts beyond simple checks: `obs-otel`.

## Monitoring
- Uptime: Uptime Kuma or Gatus on a different host; add an external check for anything public.
- Jobs: dead-man pings (`ExecStartPost=curl ... /ping/<uuid>`, unit in `ops-systemd-caddy`); alert on a missing ping, not on output.
- Disk: `df -h`, `df -i`, `docker system df`, `du -xh --max-depth=1 /srv | sort -h`; alert at 80%;
  btrfs `btrfs filesystem usage /`.
- SMART: `smartctl -H -A /dev/nvme0n1`, `smartctl -t short /dev/sda`; smartd with
  `DEVICESCAN -a -s (S/../.././02|L/../../6/03) -m <nomailer> -M exec /usr/local/bin/notify` in `/etc/smartd.conf`
  (`-M` works only together with `-m`; service `smartd` on Arch, `smartmontools` on Ubuntu).
- Certificates: `openssl s_client -connect host:443 -servername host </dev/null 2>/dev/null | openssl x509 -noout -enddate`.
- Listeners: `sudo ss -tlnp` shows only 127.0.0.1, the tailnet address, and what you meant to publish.

## Runbook template (`/srv/<svc>/runbook.md`)
```markdown
# <service>
- Purpose, criticality, data owner. Access: URLs, tailnet name, public? (Funnel/Caddy), auth
- Deploy: files in the ops repo, start/stop/restart. Config: files, env var names, secret paths (never values)
- Data: paths, volumes, database, size; backup job; last restore drill (date, duration, result)
- Health: healthcheck, monitors, log commands. Dependencies: DNS, Tailscale, storage, other services
- Upgrade: pin location, procedure, migration notes. Rollback: steps, previous pin
- Known failures: symptom -> fix
```

## Incident checklist
1. Note the time. Suspected data corruption: stop writes (stop the service); delete nothing.
2. Scope: what is down, since when (`journalctl --since`), what changed (ops repo log, package logs, image pulls).
3. Evidence: `systemctl status`, `journalctl -u`, `docker compose ps` / `logs --since 1h`, `df -h`, `free -h`,
   `dmesg -T | tail`, `tailscale status`, certificate expiry.
4. Mitigate: roll back the last change, restart, or restore (to a scratch location first, verify, then swap).
5. Security incident (unexpected access, leaked secret): revoke and rotate credentials, remove public exposure,
   preserve logs, review auth logs and the tailnet's device list.
6. Close: short postmortem in the runbook (timeline, cause, fix, follow-ups) and a monitor or test for it.

## Verify
- Every service has a runbook with all template fields filled (secret paths, never values) and a dated restore drill.
- Monitors green, including one external check for anything public; a missed dead-man ping alerts.
