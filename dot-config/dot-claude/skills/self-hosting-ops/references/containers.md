# Containers: Docker Compose or Podman Quadlet

| | Docker + Compose | Podman + Quadlet |
|---|---|---|
| Model | daemon, rootful by default | daemonless, rootless by default |
| Lifecycle | `restart:` policy in compose | systemd units generated from `.container` files |
| Updates | pull + `up -d` (Diun notifications or Renovate PRs; Watchtower is discontinued) | `podman auto-update` with rollback |
| Use when | the project ships a compose file | long-lived services on a systemd host |

## Docker Compose
A complete, validated compose file (Postgres + Forgejo) is in `ops-forgejo`.
- Pin by digest: `docker buildx imagetools inspect <image:tag>` prints the index `Digest:`; write `image:tag@sha256:...`
  (the digest wins; the tag documents intent). Digest pins and auto-update are mutually exclusive by design.
- Publish on `127.0.0.1` only: Docker's published ports bypass ufw/firewalld rules.
- Logs: the default json-file driver never rotates; set `{"log-driver": "local"}` in `/etc/docker/daemon.json`
  (20 MB x 5 files per container; applies to containers created afterwards).
- Healthchecks gate `depends_on`; `docker compose ps` shows health; `docker compose up -d --wait` blocks until healthy.

## Podman Quadlet
Rootless: `~/.config/containers/systemd/forgejo.container`; rootful: `/etc/containers/systemd/`.
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
