---
name: ops-systemd-caddy
description: Load for systemd units, timers and hardening, or a Caddy reverse proxy with automatic HTTPS.
---
# systemd services and Caddy

Part of `self-hosting-ops` (principles, secrets). Quadlet container units: `self-hosting-ops` `references/containers.md`. Caddy 2.11.6 is current (Verified 2026-10-02 `git ls-remote --tags https://github.com/caddyserver/caddy`).

## systemd
```ini
# /etc/systemd/system/restic-backup.service  (verified with systemd-analyze verify)
[Unit]
Description=restic backup of /srv and /etc
Wants=network-online.target
After=network-online.target
OnFailure=notify-failure@%n.service
[Service]
Type=oneshot
EnvironmentFile=/etc/restic/env
ExecStartPre=/usr/local/bin/pre-backup-dumps
ExecStart=/usr/bin/restic backup --one-file-system --exclude-caches --tag nightly /srv /etc
ExecStart=/usr/bin/restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
ExecStartPost=/usr/bin/curl -fsS -m 10 --retry 3 -o /dev/null https://<healthchecks-host>/ping/<uuid>
Nice=10
IOSchedulingClass=idle
ProtectSystem=strict
CacheDirectory=restic
Environment=RESTIC_CACHE_DIR=/var/cache/restic
ReadWritePaths=/srv/backup
PrivateTmp=true
NoNewPrivileges=true

# /etc/systemd/system/restic-backup.timer
[Timer]
OnCalendar=*-*-* 03:15:00
RandomizedDelaySec=20m
Persistent=true
[Install]
WantedBy=timers.target
```
- Timers over cron: missed runs catch up (`Persistent=true`), logs land in the journal, dependencies and
  `OnFailure=` work. `notify-failure@.service`: a `Type=oneshot` unit whose `ExecStart` posts `%i failed on %H` to
  your ntfy/healthchecks endpoint.
- Hardening for long-running native services: `DynamicUser=yes` (+ `StateDirectory=`), `ProtectSystem=strict`,
  `ProtectHome=yes`, `PrivateTmp=yes`, `PrivateDevices=yes`, `NoNewPrivileges=yes`, `RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX`,
  `SystemCallFilter=@system-service`, `CapabilityBoundingSet=` (empty), `UMask=0077`; score with
  `systemd-analyze security <unit>`; change vendor units with `systemctl edit <unit>` (drop-ins).
- Secrets for services: `LoadCredential=api-key:/etc/<svc>/api-key` (readable at `$CREDENTIALS_DIRECTORY/api-key`),
  or `systemd-creds encrypt` + `LoadCredentialEncrypted=`.
- Checks: `systemd-analyze verify <files>`, `systemd-analyze calendar '<expr>'`, `systemctl list-timers`,
  `journalctl -u <unit> --since -1h -p warning`. Journal size: `/etc/systemd/journald.conf.d/size.conf` with
  `[Journal]` + `SystemMaxUse=1G`; `journalctl --disk-usage`.

## Caddy (public service on your own domain)
```caddyfile
git.example.com {
	encode zstd gzip
	reverse_proxy 127.0.0.1:3000
}
```
- Automatic HTTPS needs DNS A/AAAA to the host, ports 80 and 443 reachable, a persistent data dir.
  `caddy fmt --overwrite <file>`, `caddy validate --config /etc/caddy/Caddyfile`, `sudo systemctl reload caddy`.
- A site named `<host>.<tailnet>.ts.net` gets its certificate from the local tailscaled (Caddy >= 2.5); a non-root
  Caddy needs `TS_PERMIT_CERT_UID=caddy` in `/etc/default/tailscaled`. For tailnet-only access `tailscale serve` is simpler.
- Before going public: registration closed, 2FA for admins, admin UI kept private, updates on a schedule,
  `ROOT_URL` switched to the public URL.

## Verify
- `systemd-analyze verify <unit files>` clean; `systemd-analyze security <unit>` reviewed; `systemctl list-timers` shows the next run.
- `caddy validate --config /etc/caddy/Caddyfile` passes; the site answers over HTTPS with a valid certificate.
