---
name: ops-forgejo
description: Use to deploy or run Forgejo — compose stack, app.ini, Actions runner, dumps, upgrades.
---
# Forgejo on a personal server

Part of `self-hosting-ops` (principles, secrets). Containers in general: `self-hosting-ops` `references/containers.md`. Exposure: `ops-tailscale`; public on your own domain: Caddy in `ops-systemd-caddy`. Backups: `ops-backups`.

## Compose stack (validated with `docker compose config -q`)
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

## Forgejo
- Versions (Sep 2026): 16.x stable (support ends 2026-10-29), 15.x LTS (to 2027-07-15). A quiet personal forge runs
  the LTS major tag, pinned by digest. Latest tags 16.0.5 and 15.0.9 (Verified 2026-10-02 `git ls-remote --tags https://codeberg.org/forgejo/forgejo.git`); the support dates: unverified since Sep 2026.
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

## Actions runner (Forgejo Runner 13, binary `forgejo-runner`; `forgejo-runner register` is deprecated)
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

## Dumps and upgrades
- Backup: primary = DB dump + restic of `data/` (`ops-backups`); portable secondary before upgrades:
  `docker compose exec -u git forgejo forgejo dump --type tar.zst --file /data/dumps/forgejo-$(date +%F).tar.zst`
  (create `data/forgejo/dumps` owned by the container's git user first; `--skip-repository`, `--skip-lfs-data`,
  ... shrink it). Restore from a dump is manual: unpack repos and data,
  load the SQL into an empty DB, fix ownership, run `forgejo doctor check --all`.
- Upgrade: release notes -> backup -> bump the pinned tag/digest in git -> `docker compose pull && docker compose up -d`
  -> watch logs for migrations -> smoke test (login, clone, push, one Actions job). Migrations are one-way:
  rolling back means restoring DB and data, then the old image. Postgres majors (e.g. 17 -> 18) need
  dump/restore or `pg_upgrade`, never just a new image tag.

## Verify
- `docker compose config -q`; `docker compose ps` shows both services healthy; `forgejo doctor check --all` clean.
- Smoke test after any change: login, clone over HTTPS and SSH, push, one Actions job.
