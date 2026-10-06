#!/bin/sh
# entry-pg.sh: the only start-up step of the eq-pg image (runs under the pinned static busybox ash, as the unprivileged DB user).
# NEVER RUN BY THE AGENT THAT WROTE IT: UNVERIFIED until RUNBOOK_MINIMAL.md "extension images" step passes.
# A PostgreSQL server needs an initialised data directory and a password, and an image without a shell cannot do both in one
# container, so this 20-line script is the documented, hash-pinned (TOOLS.toml entry-pg) use of busybox sh in a server image.
#  - data lives on a tmpfs (compose.yaml mounts /var/lib/eq-pg), so nothing survives the container and nothing is shared between runs;
#  - the superuser password is the per-run throwaway EQ_DB_PASSWORD (eq-compose.sh generates it for each run, never writes it to
#    a file in the repository); it reaches initdb through a pwfile on the tmpfs, which is removed at once, and is unset before postgres
#    starts, so the server process never holds it in its environment;
#  - authentication is scram-sha-256 for every connection (initdb --auth); listening on all interfaces is safe only because the
#    container sits on the internal-only compose network (internal: true, no published ports).
set -eu
: "${EQ_DB_PASSWORD:?EQ_DB_PASSWORD is not set (eq-compose.sh generates it for every run)}"
PGDATA=${PGDATA:-/var/lib/eq-pg/data}
case "$PGDATA" in /var/lib/eq-pg/*) ;; *) echo "entry-pg: PGDATA must be under /var/lib/eq-pg (a tmpfs)" >&2; exit 2;; esac
if [ -e "$PGDATA/PG_VERSION" ]; then echo "entry-pg: $PGDATA is already initialised; the data directory must be a fresh tmpfs" >&2; exit 2; fi
umask 077
pw=/tmp/eq-pgpw
printf '%s\n' "$EQ_DB_PASSWORD" > "$pw"
initdb -D "$PGDATA" -U eq --auth=scram-sha-256 --pwfile="$pw" --encoding=UTF8 --locale=C
rm -f "$pw"
unset EQ_DB_PASSWORD
exec postgres -D "$PGDATA" -c listen_addresses='*' -c unix_socket_directories=/run/eq-pg \
  -c password_encryption=scram-sha-256 -c max_connections=20 -c shared_buffers=64MB -c fsync=off -c synchronous_commit=off \
  -c full_page_writes=off -c log_destination=stderr -c logging_collector=off
