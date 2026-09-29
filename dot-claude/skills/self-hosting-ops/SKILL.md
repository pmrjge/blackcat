---
name: self-hosting-ops
description: Load before deploying, exposing, backing up, upgrading or debugging a personal service on a Linux box over Tailscale — Forgejo, Docker/Podman, systemd, Caddy, restic/borg.
---
# Self-hosting over Tailscale

Verified Sep 2026: Forgejo 16 (15 = LTS) docs and Dockerfiles, Forgejo Runner 13, Tailscale CLI docs, Podman
Quadlet man page, Docker Compose v5 (`docker compose config` on the file below), systemd 255
(`systemd-analyze verify` on the units below), restic 0.19.1 and borg 1.4.5 (commands below were run).

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
  runner registered below), `terraform-opentofu` (infrastructure as code).

## Tailscale
- Server nodes: disable key expiry in the admin console, or join with a tag (`tailscale up --advertise-tags=tag:server`,
  needs `tagOwners`; `set` has no tag flag). Prefer `tailscale set` (changes only the named flags) over `tailscale up`
  (refuses unless every non-default flag is repeated or `--reset` is given).
- MagicDNS names: `<host>.<tailnet>.ts.net`. Enable HTTPS certificates for the tailnet (admin console, DNS) before
  using serve/funnel/cert.
- **Serve** (tailnet only, automatic TLS):
  `tailscale serve --bg 3000` -> `https://<host>.<tailnet>.ts.net/` proxies to `localhost:3000`;
  `--https=8443`, `--set-path=/app`, raw TCP `tailscale serve --bg --tcp=2222 tcp://localhost:2222`.
  `tailscale serve status`; remove one: repeat the command with `off` (`tailscale serve --https=443 off`); all: `tailscale serve reset`.
- **Funnel** (public internet): same syntax with `tailscale funnel`; ports 443, 8443, 10000 only; a port can't be
  both served and funneled; requires the `funnel` node attribute; `tailscale funnel status`, `... off`, `tailscale funnel reset`.
- **Policy** (grants syntax; the default policy allows all, tighten it; groups/tags per the admin console):
  ```json
  {"tagOwners": {"tag:server": ["autogroup:admin"]},
   "grants": [{"src": ["autogroup:member"], "dst": ["tag:server"], "ip": ["tcp:443", "tcp:2222"]},
              {"src": ["autogroup:admin"], "dst": ["tag:server"], "ip": ["*"]}],
   "ssh": [{"action": "check", "src": ["autogroup:admin"], "dst": ["tag:server"], "users": ["autogroup:nonroot"]}],
   "nodeAttrs": [{"target": ["tag:public"], "attr": ["funnel"]}]}
  ```
- **Tailscale SSH**: `tailscale set --ssh`; it intercepts port 22 for tailnet traffic only (OpenSSH still serves
  other interfaces; authorized_keys untouched). It captures anything else on 22 from the tailnet, so give a
  forge's SSH another port (2222).
- **Exit node**: `/etc/sysctl.d/99-tailscale.conf` with `net.ipv4.ip_forward = 1` and
  `net.ipv6.conf.all.forwarding = 1`, `sudo sysctl -p /etc/sysctl.d/99-tailscale.conf`,
  `sudo tailscale set --advertise-exit-node`, approve in the admin console (Edit route settings).
  Clients: `tailscale set --exit-node=<host>`; off: `tailscale set --exit-node=`.
- `tailscale cert <fqdn>` writes 90-day certs you must renew; prefer serve or Caddy, which renew themselves.

## Containers
| | Docker + Compose | Podman + Quadlet |
|---|---|---|
| Model | daemon, rootful by default | daemonless, rootless by default |
| Lifecycle | `restart:` policy in compose | systemd units generated from `.container` files |
| Updates | pull + `up -d` (Diun notifications or Renovate PRs; Watchtower is discontinued) | `podman auto-update` with rollback |
| Use when | the project ships a compose file | long-lived services on a systemd host |

Compose (validated with `docker compose config -q`):
```yaml
name: forge
services:
  db:
    image: ${PG_IMAGE:?pin tag@sha256}          # e.g. docker.io/library/postgres:18@sha256:<digest>
    restart: unless-stopped
    environment: {POSTGRES_USER: forgejo, POSTGRES_DB: forgejo, POSTGRES_PASSWORD_FILE: /run/secrets/db_password}
    secrets: [db_password]
    volumes: ["./data/db:/var/lib/postgresql"]  # 18+; up to 17 the path is /var/lib/postgresql/data
    healthcheck: {test: ["CMD-SHELL", "pg_isready -U forgejo -d forgejo"], interval: 10s, timeout: 5s, retries: 5, start_period: 30s}
  forgejo:
    image: ${FORGEJO_IMAGE:?pin tag@sha256}     # codeberg.org/forgejo/forgejo:15@sha256:<digest>
    restart: unless-stopped
    depends_on: {db: {condition: service_healthy}}
    env_file: [./forgejo.env]                   # FORGEJO__database__PASSWD=..., chmod 600
    environment:
      {USER_UID: "1000", USER_GID: "1000", FORGEJO__database__DB_TYPE: postgres,
       FORGEJO__database__HOST: "db:5432", FORGEJO__database__NAME: forgejo, FORGEJO__database__USER: forgejo}
    volumes: ["./data/forgejo:/data"]
    ports: ["127.0.0.1:3000:3000", "127.0.0.1:2222:22"]
    healthcheck: {test: ["CMD", "curl", "-fsS", "http://localhost:3000/api/healthz"], interval: 30s, timeout: 5s, retries: 3}
secrets:
  db_password: {file: ./secrets/db_password}
```
- Pin by digest: `docker buildx imagetools inspect <image:tag>` prints the index `Digest:`; write `image:tag@sha256:...`
  (the digest wins; the tag documents intent). Digest pins and auto-update are mutually exclusive by design.
- Publish on `127.0.0.1` only: Docker's published ports bypass ufw/firewalld rules.
- Logs: the default json-file driver never rotates; set `{"log-driver": "local"}` in `/etc/docker/daemon.json`
  (20 MB x 5 files per container; applies to containers created afterwards).
- Healthchecks gate `depends_on`; `docker compose ps` shows health; `docker compose up -d --wait` blocks until healthy.

Quadlet (rootless; `~/.config/containers/systemd/forgejo.container`; rootful: `/etc/containers/systemd/`):
```ini
[Unit]
Description=Forgejo (rootless image)
[Container]
Image=codeberg.org/forgejo/forgejo:15-rootless
ContainerName=forgejo
UserNS=keep-id
PublishPort=127.0.0.1:3000:3000
PublishPort=127.0.0.1:2222:2222
Volume=%h/forgejo:/var/lib/gitea
EnvironmentFile=%h/forgejo/forgejo.env
HealthCmd=curl -fsS http://localhost:3000/api/healthz
HealthInterval=30s
AutoUpdate=registry
[Service]
Restart=on-failure
[Install]
WantedBy=default.target
```
`UserNS=keep-id` maps your UID to the same UID inside; the rootless image runs as 1000:1000, so a host UID other
than 1000 needs `UserNS=keep-id:uid=1000,gid=1000` for sane bind-mount ownership.
`systemctl --user daemon-reload && systemctl --user start forgejo` (`systemctl enable` doesn't apply: the
generator honours `[Install]`); `loginctl enable-linger <user>` so it runs without a login. Unit missing after the
reload means a syntax error: `systemd-analyze --user --generators=true verify forgejo.service`.
Updates: `podman auto-update --dry-run`, `systemctl --user enable --now podman-auto-update.timer`; rollback on a failed
restart works best with sd_notify readiness (`--sdnotify=container`), which most images don't send.

## Forgejo
- Versions (Sep 2026): 16.x stable (support ends 2026-10-29), 15.x LTS (to 2027-07-15). A quiet personal forge runs
  the LTS major tag, pinned by digest.
- Images: standard (`/data` volume, app.ini at `/data/gitea/conf/app.ini`, OpenSSH on 22, runs as `git`) and
  `-rootless` (`/var/lib/gitea` volume, app.ini at `/var/lib/gitea/custom/conf/app.ini`, built-in SSH on 2222,
  user 1000:1000). Both ship curl; health endpoint `/api/healthz`. Binary + systemd install: follow the docs.
- Env overrides: `FORGEJO__<section>__<KEY>=value`; a variable whose name ends in `__FILE` reads the value from
  that file. Values can't be deleted via env: edit app.ini.
- app.ini essentials: `[server]` `DOMAIN` and `SSH_DOMAIN = forge.<tailnet>.ts.net`, `ROOT_URL = https://forge.<tailnet>.ts.net/`,
  `HTTP_PORT = 3000`, `SSH_PORT = 2222` (the port shown in clone URLs), `LFS_START_SERVER = true`, `OFFLINE_MODE = true`;
  `[database] DB_TYPE = postgres` (sqlite3 is fine for one user; WAL by default); `[security] INSTALL_LOCK = true`,
  secrets via `SECRET_KEY_URI`/`INTERNAL_TOKEN_URI = file:/path`; `[service] DISABLE_REGISTRATION = true`,
  `REQUIRE_SIGNIN_VIEW = true`; `[session] COOKIE_SECURE = true`; `[actions] ENABLED = true`.
- Exposure: `tailscale serve --bg 3000` (HTTPS) and `tailscale serve --bg --tcp=2222 tcp://localhost:2222` (SSH),
  so both stay bound to localhost. Clone: `https://forge.<tailnet>.ts.net/<owner>/<repo>.git` with an access token
  (credential helper, never in the URL) or `ssh://git@forge.<tailnet>.ts.net:2222/<owner>/<repo>.git` with a key
  added in user settings. `ROOT_URL`/`SSH_PORT` must match what clients use or clone URLs break.
- Admin user: `docker compose exec -u git forgejo forgejo admin user create --admin --username <u> --email <e> --random-password`
  (rootless image: no `-u git`). Health: `forgejo doctor check --all` (`--fix` only after reading the output).
- Actions runner (Forgejo Runner 13, binary `forgejo-runner`; `forgejo-runner register` is deprecated):
  1. Register at the narrowest scope in the UI (repo/org/user settings -> Actions -> Runners -> Create new runner)
     to get a UUID and token; or offline on the Forgejo host with a 40-hex secret (`openssl rand -hex 20`):
     `forgejo forgejo-cli actions register --name <runner> --scope <org> --secret <hex>` (prints the UUID;
     the token is the secret).
  2. Runner host: `forgejo-runner generate-config > config.yml`; under `server.connections.<name>` set `url`,
     `uuid`, `token`; labels `<name>:docker://<image@digest>`; `runner.capacity`; `container.network`.
  3. Run `forgejo-runner daemon -c config.yml` as a dedicated `runner` user via the upstream systemd unit
     (`contrib/forgejo-runner.service`); Docker socket via the docker group, or rootless Podman via
     `container.docker_host: unix:///run/user/<uid>/podman/podman.sock`.
  4. Security: a `host` label runs jobs as the runner user without isolation; `container.privileged: true` gives
     root on the runner host. Neither for untrusted code; outside contributors' PRs need approval; keep the
     runner off the Forgejo host if repositories accept outside PRs; ephemeral runners where feasible.
- Backup: primary = DB dump + restic of `data/`; portable secondary before upgrades:
  `docker compose exec -u git forgejo forgejo dump --type tar.zst --file /data/dumps/forgejo-$(date +%F).tar.zst`
  (create `data/forgejo/dumps` owned by the container's git user first; `--skip-repository`, `--skip-lfs-data`,
  ... shrink it). Restore from a dump is manual: unpack repos and data,
  load the SQL into an empty DB, fix ownership, run `forgejo doctor check --all`.
- Upgrade: release notes -> backup -> bump the pinned tag/digest in git -> `docker compose pull && docker compose up -d`
  -> watch logs for migrations -> smoke test (login, clone, push, one Actions job). Migrations are one-way:
  rolling back means restoring DB and data, then the old image. Postgres majors (e.g. 17 -> 18) need
  dump/restore or `pg_upgrade`, never just a new image tag.

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

## Backups
- Tools: restic (repos `sftp:user@host:/path`, `rest:https://...`, `s3:...`, `b2:...`, `rclone:...`) or borg 1.4
  (local/ssh). borg 2 is still beta: not for production.
- Consistent input: dump databases first (`docker compose exec -T db pg_dump -U forgejo -Fc forgejo > /srv/backup/forgejo.pgdump`,
  SQLite `sqlite3 app.db ".backup '/srv/backup/app.db'"`) or stop the service briefly. Skip caches and images.
- restic (tested), env in `/etc/restic/env` (600: `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE`, backend credentials):
  ```bash
  restic init
  restic backup --one-file-system --exclude-caches --tag nightly /srv /etc
  restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
  restic check --read-data-subset=5%          # monthly; full --read-data yearly
  restic snapshots; restic ls latest | head   # stored paths are what --include matches
  restic restore latest --target /tmp/restore --include /srv/forge   # or latest:/srv/forge --target ...
  ```
- borg 1.4 (tested): `borg init -e repokey-blake2 <repo>`; `borg create --stats --compression zstd,6 --exclude-caches
  --one-file-system '<repo>::{hostname}-{now}' /srv /etc`; `borg prune --list --keep-daily 7 --keep-weekly 4
  --keep-monthly 6 <repo>`; `borg compact <repo>`; `borg check <repo>`; `borg key export <repo> <file>`.
- 3-2-1: a second copy off-site (object storage, or another host over Tailscale). Against ransomware make the
  remote append-only (`rest-server --append-only`, or `borg serve --append-only` forced in authorized_keys).
- Keep the repo password/key outside the server too (password manager). Losing it loses every backup.
- Restore drill each quarter: restore to a scratch dir or VM, start the service from it, compare, record duration
  and result in the runbook. An untested backup counts as missing.

## Monitoring
- Uptime: Uptime Kuma or Gatus on a different host; add an external check for anything public.
- Jobs: dead-man pings (`ExecStartPost=curl ... /ping/<uuid>` as above); alert on a missing ping, not on output.
- Disk: `df -h`, `df -i`, `docker system df`, `du -xh --max-depth=1 /srv | sort -h`; alert at 80%;
  btrfs `btrfs filesystem usage /`.
- SMART: `smartctl -H -A /dev/nvme0n1`, `smartctl -t short /dev/sda`; smartd with
  `DEVICESCAN -a -s (S/../.././02|L/../../6/03) -m <nomailer> -M exec /usr/local/bin/notify` in `/etc/smartd.conf`
  (`-M` works only together with `-m`; service `smartd` on Arch, `smartmontools` on Ubuntu).
- Certificates: `openssl s_client -connect host:443 -servername host </dev/null 2>/dev/null | openssl x509 -noout -enddate`.
- Listeners: `sudo ss -tlnp` shows only 127.0.0.1, the tailnet address, and what you meant to publish.

## Secrets
- Env files and secret files: `chmod 600`, owned by the service user, git-ignored; commit `.env.example` with
  names only. Compose: `env_file:` or `secrets:` (mounted at `/run/secrets/<name>`, for images with `*_FILE`
  support). systemd: `LoadCredential=` or `EnvironmentFile=` (600).
- Never in: committed compose files, command lines (`ps` shows them), image layers (`docker history`), logs,
  runbooks. Rotate on any exposure and restart dependents.

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
`docker compose config -q`, `systemd-analyze verify`, `caddy validate`, `tailscale serve|funnel status`; healthchecks
healthy; newest backup < ~26 h old, `restic check` passes, a restore drill on record; monitors green; `ss -tlnp` as intended.

## Report
Services and versions (tag@digest), exposure (tailnet or public, URLs), files changed (ops repo commit), secrets
touched (names only), backup status and last drill, monitoring added, open risks and follow-ups.
