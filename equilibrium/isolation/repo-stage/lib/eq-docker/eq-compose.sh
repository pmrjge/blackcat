#!/usr/bin/env bash
# shellcheck disable=SC2012,SC2153  # SC2012: the mode string of one directory; SC2153: EQ_IMAGE_CP is exported by the loop above
# eq-compose.sh: the one way to start compose.yaml. Bash 3.2 ok. UNVERIFIED against a real daemon (RUNBOOK_MINIMAL.md "compose").
#   ./eq-compose.sh [--profiles LIST] [--work DIR] [--tunnel DIR] [--run-id ID] [--no-deep] ACTION [docker compose args...]
#   ACTION: config (validate; prints nothing secret) | run SERVICE [cmd...] | up [args] | down | ps | logs [args]
#   --profiles   TOOLS.toml profiles (core is always included; `all` = every profile not marked explicit, so not mongo)
#   --work DIR   the per-run copy of the files (an absolute directory you own, not a symlink, not $HOME or an ancestor); required for run/up
#   --tunnel DIR ONE WALL channel directory (<tunnel_root>/<run_id>/c<32 hex>, created by eq_wall.open_channel for this call): required
#                explicit argument, NO default (EQ_TUNNEL_DIR, the tunnel ROOT the harness uses, is never read). Absolute, owned by you, mode
#                0700, not a symlink, named c<32 hex>, holding .channel.json and no subdirectory. A root or run directory is refused: it would
#                show the container every channel's token (WALL_DESIGN.md section 3 and 12.8). Adds compose.wall.yaml (the one mount
#                /eq/tunnel). Without --tunnel no tunnel is mounted. With --tunnel only `run SERVICE` is allowed (`up` is refused, exit 2).
#   --no-deep    skip the host-side re-hash of every installed tool file (verify-tools.sh --deep) before the run
# Before run/up it (1) checks docker and the compose plugin, (2) runs verify-tools.sh --images --deep for the selected profiles (fails
# closed: exit 11 stale or mismatching image, 13 pending pin), (3) takes each image from its build record, refuses a tag whose ID
# is not the recorded one and gives compose that ID (sha256:...), not the tag, (4) generates the per-run database credential for the db/mongo profiles into THIS process's environment only
# (never a file, never printed), (5) runs `docker compose -p eq-<run id>` and always removes the project (containers, network) at the end.
# It never mounts anything the compose files do not name and never passes the host environment on beyond the variables set here.
# Exit: 0 ok | 2 usage | 10 docker or the compose plugin missing | 11/13 from verify-tools.sh | the compose command's own code.
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
# shellcheck disable=SC1091
. "$here/tools.sh"

PROFILES=""; WORK=""; TUNNEL=""; DEEP=1
while [ $# -gt 0 ]; do
  case "$1" in
    --profiles|--work|--tunnel|--run-id)      # an option without its value is a usage error (exit 2; `${2:?}` would exit 1)
      [ $# -ge 2 ] && [ -n "$2" ] || { echo "eq-compose: $1 needs a value" >&2; exit 2; }
      case "$1" in
        --profiles) PROFILES=$2;; --work) WORK=$2;; --tunnel) TUNNEL=$2;;
        --run-id) EQ_RUN_ID=$2; export EQ_RUN_ID;;
      esac
      shift;;
    --no-deep) DEEP=0;;
    -h|--help) sed -n '2,17p' "$0"; exit 0;;
    --) shift; break;;
    -*) echo "eq-compose: unknown option: $1" >&2; exit 2;;
    *) break;;
  esac
  shift
done
ACTION=${1:-}; [ $# -eq 0 ] || shift
case "$ACTION" in config|run|up|down|ps|logs) ;; "") echo "eq-compose: an action is needed (config, run, up, down, ps, logs)" >&2; exit 2;; *) echo "eq-compose: unknown action: $ACTION" >&2; exit 2;; esac
case "$ACTION" in run) [ $# -gt 0 ] || { echo "eq-compose: run needs a service name" >&2; exit 2; };; esac

tm_load "$here/TOOLS.toml" || exit 2
exp=$(tm_expand_profiles "core,${PROFILES:-core}") || exit 2
PROFILES=$(printf '%s' "$exp" | tr '\n' ' ' | sed 's/ *$//')
SEL_IMAGES=$(tm_profile_images "$PROFILES" | tr '\n' ' ')

good_dir() { # absolute directory, no comma, not a symlink, not $HOME or an ancestor of it, not /
  local d=$1 real
  case "$d" in /*) ;; *) return 1;; esac
  case "$d" in *,*) return 1;; esac
  [ -d "$d" ] && [ ! -L "$d" ] || return 1
  real=$(cd "$d" && pwd -P) || return 1
  [ "$real" != / ] || return 1
  case "${HOME:-/nonexistent}/" in "$real"/*) return 1;; esac
  return 0
}

# good_channel DIR: the layout eq_wall.open_channel creates (EQ-T/wall/eq_wall.py CHANNEL_RE, CHANNEL_FILE): a directory named c plus 32 hex
# digits that holds the regular file .channel.json and no subdirectory (a tunnel root holds run directories, a run directory holds channels)
good_channel() {
  local d=$1 base e
  base=${d##*/}
  [ "${#base}" = 33 ] && [ "${base%"${base#c}"}" = c ] && [ -z "$(printf '%s' "${base#c}" | tr -d '0-9a-f')" ] || return 1
  [ -f "$d/.channel.json" ] && [ ! -L "$d/.channel.json" ] || return 1
  for e in "$d"/* "$d"/.[!.]*; do
    [ -d "$e" ] && return 1
  done
  return 0
}

EQ_NO_STATE_WRITE=1
export EQ_NO_STATE_WRITE
# shellcheck disable=SC1091
. "$here/lib.sh"
eq_need_docker
docker compose version >/dev/null 2>&1 || { echo "eq-compose: the docker compose plugin is not available (docker compose version failed)" >&2; exit 10; }

files=(-f "$here/compose.yaml")
if [ -n "$TUNNEL" ]; then
  good_dir "$TUNNEL" || { echo "eq-compose: the tunnel directory must be an absolute directory (not a symlink, not your home)" >&2; exit 2; }
  [ -O "$TUNNEL" ] && [ "$(ls -ld "$TUNNEL" | cut -c1-10)" = "drwx------" ] || { echo "eq-compose: the tunnel directory must be owned by you with mode 0700" >&2; exit 2; }
  good_channel "$TUNNEL" || { echo "eq-compose: --tunnel must name ONE channel directory (c<32 hex> with .channel.json, no subdirectory), not the tunnel root or a run directory: it would expose every channel's token" >&2; exit 2; }
  export EQ_TUNNEL_CHANNEL=$TUNNEL
  files=("${files[@]}" -f "$here/compose.wall.yaml")
fi
# one channel carries one container: `up` would start every service of the profiles on the same channel (same token, same quota)
[ "$ACTION" != up ] || [ -z "$TUNNEL" ] || { echo "eq-compose: --tunnel works only with 'run SERVICE' (one container per channel)" >&2; exit 2; }

case "$ACTION" in
  run|up)
    [ -n "$WORK" ] || { echo "eq-compose: $ACTION needs --work DIR (the per-run copy of the files)" >&2; exit 2; }
    good_dir "$WORK" || { echo "eq-compose: --work must be an absolute directory (not a symlink, not your home or an ancestor, no comma)" >&2; exit 2; }
    export EQ_WORK_DIR=$WORK
    # (2) the tools: manifest hashes, image labels, in-image locks, host-side re-hash of every installed tool file
    vt=(--images --profiles "$PROFILES"); [ "$DEEP" = 0 ] || vt=(--images --deep --profiles "$PROFILES")
    bash "$here/verify-tools.sh" "${vt[@]}" || exit $?;;
  *) export EQ_WORK_DIR=${WORK:-/eq-work-placeholder};;
esac

# (3) image references: every service's variable is set (compose interpolates the whole file); an unselected service gets a name that
# cannot start; a selected one gets the recorded tag, refused unless the daemon's ID for it is the recorded ID
for img in $(tm_names image); do
  svc=$(tm_get image "$img" service); up=$(printf '%s' "$svc" | tr '[:lower:]' '[:upper:]')
  export "EQ_IMAGE_$up=eq-unselected:none"
done
for img in $SEL_IMAGES; do
  svc=$(tm_get image "$img" service); up=$(printf '%s' "$svc" | tr '[:lower:]' '[:upper:]')
  tag=$(eq_img_tag "$img"); rec=$(eq_img_get "$img" EQ_IMAGE_ID)
  if [ "$ACTION" = run ] || [ "$ACTION" = up ]; then
    id=$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null || true)
    [ -n "$rec" ] && [ "$id" = "$rec" ] || { echo "eq-compose: image $tag is not the recorded build of $img (rebuild: build.sh --profiles $PROFILES)" >&2; exit 11; }
  fi
  export "EQ_IMAGE_$up=${id:-$tag}"   # run/up: the verified ID, which a re-tag between the check and the start cannot change; config/ps/...: the tag
done
export EQ_IMAGE_CR=$EQ_IMAGE_CP

# (4) the per-run database credential: this process's environment only
case " $PROFILES " in
  *" db "*|*" mongo "*)
    if [ "$ACTION" = config ]; then EQ_DB_PASSWORD="placeholder-not-a-secret"
    else EQ_DB_PASSWORD=$(od -An -N24 -tx1 /dev/urandom | tr -d ' \n'); fi;;
  *) EQ_DB_PASSWORD="unused-$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')";;
esac
export EQ_DB_PASSWORD
COMPOSE_PROFILES=$(printf '%s' "$PROFILES" | tr ' ' ',')
export COMPOSE_PROFILES
proj="eq-$EQ_RUN_ID"

case "$ACTION" in
  config)
    docker compose "${files[@]}" -p "$proj" config --quiet || exit $?
    echo "eq-compose: compose files OK (profiles: $COMPOSE_PROFILES)"
    exit 0;;
  down) exec docker compose "${files[@]}" -p "$proj" down --volumes --remove-orphans "$@";;
  ps|logs) exec docker compose "${files[@]}" -p "$proj" "$ACTION" "$@";;
esac
# (5) run / up: the project (containers and its network) is removed whatever happens
cleanup() { docker compose "${files[@]}" -p "$proj" down --volumes --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT INT TERM
if [ "$ACTION" = run ]; then docker compose "${files[@]}" -p "$proj" run --rm "$@"; else docker compose "${files[@]}" -p "$proj" up "$@"; fi
