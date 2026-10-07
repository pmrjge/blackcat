#!/bin/sh
# entry-mongo.sh: the only start-up step of the eq-mongo image (pinned static busybox ash, unprivileged DB user).
# NEVER RUN BY THE AGENT THAT WROTE IT: UNVERIFIED until RUNBOOK_MINIMAL.md "extension images" step passes.
# mongod has no `initdb`: authentication needs a first user, which is created through the localhost exception. Sequence:
#  1. mongod on 127.0.0.1 only, no auth, data on a tmpfs (/var/lib/eq-mongo, mounted by compose.yaml);
#  2. mongosh (same image) creates the root user eq with the per-run throwaway EQ_DB_PASSWORD, read from the environment by
#     the JavaScript itself (never spliced into the command line, so it is not in `ps` and cannot be injected);
#  3. that instance is shut down and mongod is exec'ed again with --auth on all interfaces (safe only on the internal-only network).
# The password is unset before the final exec. Nothing survives the container (tmpfs); nothing is shared between runs.
set -eu
: "${EQ_DB_PASSWORD:?EQ_DB_PASSWORD is not set (eq-compose.sh generates it for every run)}"
D=/var/lib/eq-mongo
S=/run/eq-mongo
[ -z "$(ls -A "$D" 2>/dev/null)" ] || { echo "entry-mongo: $D is not empty; the data directory must be a fresh tmpfs" >&2; exit 2; }
umask 077
mongod --dbpath "$D" --bind_ip 127.0.0.1 --port 27017 --unixSocketPrefix "$S" --logpath /tmp/mongod-init.log --fork >/dev/null
n=0
until mongosh --quiet --host 127.0.0.1 --port 27017 --eval 'db.adminCommand({ping: 1}).ok' >/dev/null 2>&1; do
  n=$((n + 1)); [ "$n" -lt 60 ] || { echo "entry-mongo: mongod did not come up" >&2; exit 1; }
  sleep 1
done
mongosh --quiet --host 127.0.0.1 --port 27017 --eval \
  'db.getSiblingDB("admin").createUser({user: "eq", pwd: process.env.EQ_DB_PASSWORD, roles: [{role: "root", db: "admin"}]})' >/dev/null
mongod --dbpath "$D" --shutdown >/dev/null
unset EQ_DB_PASSWORD
exec mongod --dbpath "$D" --auth --bind_ip_all --port 27017 --unixSocketPrefix "$S" --wiredTigerCacheSizeGB 0.25
