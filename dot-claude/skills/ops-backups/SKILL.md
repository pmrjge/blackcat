---
name: ops-backups
description: Use to set up, check or restore backups — restic, borg, database dumps, 3-2-1, restore drills.
---
# Backups with restic or borg

Part of `self-hosting-ops` (principles: ask before deleting snapshots or backups). The nightly systemd unit and timer: `ops-systemd-caddy`. restic 0.19.1 and borg 1.4.5 are current; borg 2 is still beta (2.0.0b25) — Verified 2026-10-02 `git ls-remote --tags` of github.com/restic/restic and github.com/borgbackup/borg.

## Tools and input
- Tools: restic (repos `sftp:user@host:/path`, `rest:https://...`, `s3:...`, `b2:...`, `rclone:...`) or borg 1.4
  (local/ssh). borg 2 is still beta: not for production.
- Consistent input: dump databases first (`docker compose exec -T db pg_dump -U forgejo -Fc forgejo > /srv/backup/forgejo.pgdump`,
  SQLite `sqlite3 app.db ".backup '/srv/backup/app.db'"`) or stop the service briefly. Skip caches and images.

## restic (tested)
Env in `/etc/restic/env` (600: `RESTIC_REPOSITORY`, `RESTIC_PASSWORD_FILE`, backend credentials):
```bash
restic init
restic backup --one-file-system --exclude-caches --tag nightly /srv /etc
restic forget --keep-daily 7 --keep-weekly 4 --keep-monthly 12 --prune
restic check --read-data-subset=5%          # monthly; full --read-data yearly
restic snapshots; restic ls latest | head   # stored paths are what --include matches
restic restore latest --target /tmp/restore --include /srv/forge   # or latest:/srv/forge --target ...
```

## borg 1.4 (tested)
`borg init -e repokey-blake2 <repo>`; `borg create --stats --compression zstd,6 --exclude-caches
--one-file-system '<repo>::{hostname}-{now}' /srv /etc`; `borg prune --list --keep-daily 7 --keep-weekly 4
--keep-monthly 6 <repo>`; `borg compact <repo>`; `borg check <repo>`; `borg key export <repo> <file>`.

## Policy
- 3-2-1: a second copy off-site (object storage, or another host over Tailscale). Against ransomware make the
  remote append-only (`rest-server --append-only`, or `borg serve --append-only` forced in authorized_keys).
- Keep the repo password/key outside the server too (password manager). Losing it loses every backup.
- Restore drill each quarter: restore to a scratch dir or VM, start the service from it, compare, record duration
  and result in the runbook (`ops-runbooks`). An untested backup counts as missing.

## Verify
- Newest snapshot < ~26 h old (`restic snapshots` / `borg list`); `restic check` or `borg check` passes.
- A restore drill on record with date, duration and result.
