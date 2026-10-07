# shellcheck shell=bash disable=SC2034
# Shared helpers for build.sh, spike.sh, probe.sh, reverify.sh, compare-images.sh, trace-reads.sh (source it; do not run
# it). Compatible with macOS bash 3.2. Nothing here runs at import time except path resolution and mkdir of the state dir.
#
# Environment (all optional; every default is relative to this directory or to $EQ_STATE_DIR, never to a user path):
#   EQ_STATE_DIR   results, image records, scratch copies, logs        (default: <this dir>/.state; in the repo layout, where
#                  the file LAYOUT next to this one says "repo": ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-docker)
#   EQ_ITEMS       the equilibrium pools (items/) for PF/CP/CR/ES runs  (default: <this dir>/../items, may be absent)
#   EQ_PROFILE     full | min | dl   which image set the run scripts target   (default: full)
#                  full = eq-lean (Debian slim, everything); min = the FROM-scratch images; dl = the distroless-based lean
#                  image (eq-lean-dl) with the scratch py/both images
#   EQ_IMAGE       OVERRIDE of the PF/lean image (a tag, an image ID sha256:<64 hex>, or name@sha256:<digest>). spike.sh,
#                  probe.sh, reverify.sh and trace-reads.sh all take it from here; it wins over EQ_PROFILE. When EQ_IMAGE is
#                  set and EQ_IMAGE_PY / EQ_IMAGE_BOTH are not, those two default to EQ_IMAGE as well, so a lean-only image
#                  meets only lean checks (reverify.sh then defaults to --stages pf).
#   EQ_IMAGE_PY    image for CP/CR/ES checks     EQ_IMAGE_BOTH  image able to run lean AND python (PF dev selftest)
#   EQ_USER EQ_CPUS EQ_MEMORY EQ_PIDS EQ_TMPFS_OPTS EQ_CHECK_TIMEOUT EQ_SECCOMP (path to a seccomp profile JSON)
#   EQ_NO_STATE_WRITE=1   read-only import: create no directory (build.sh sets it for --dry-run and --check; the driver for status)
#   EQ_WORK_ROOT   where fresh check copies are made; must be under a path Docker Desktop shares (default $EQ_STATE_DIR/work).
#                  It is chmod 0700 (the copies hold reference proofs); refused when it is $HOME or /.
#   EQ_WORK_TMPFS  options of the capped tmpfs every container gets at /work (default rw,nosuid,nodev,exec,size=1g,mode=1777)
#   EQ_ALLOW_UNRECORDED=1  let eq_require_image accept an image that no build record covers (default: exit 11; a manual image)
# /work design (the same as the harness's isolate()): a mount whose target is /work in EQ_RUN_MOUNTS is a SOURCE COPY. eq_run
# mounts it read-only at /eqsrc/work and starts `/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"'`, so the code under test
# writes only to the capped tmpfs /work and never to a host directory (nothing it writes reaches the host).
# Exit codes (all scripts): 0 ok | 1 verification failed | 2 usage or configuration error | 3 incomplete (resume)
#   10 docker missing, daemon down or wrong architecture (the installer treats this as SKIP, never as an install failure)
#   11 image missing, stale or not matching its record | 12 image build failed | 13 a pin is an unresolved placeholder

EQ_ISO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if [ -z "${EQ_STATE_DIR:-}" ]; then
  if [ "$(cat "$EQ_ISO_DIR/LAYOUT" 2>/dev/null)" = repo ]; then
    EQ_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-docker"
  else
    EQ_STATE_DIR="$EQ_ISO_DIR/.state"
  fi
fi
if [ "${EQ_NO_STATE_WRITE:-}" = 1 ]; then
  # read-only mode (--dry-run, --check, status): no directory is created; paths are resolved only where they exist
  [ ! -d "$EQ_STATE_DIR" ] || EQ_STATE_DIR=$(cd "$EQ_STATE_DIR" && pwd -P)
  EQ_WORK_ROOT=${EQ_WORK_ROOT:-$EQ_STATE_DIR/work}
else
  mkdir -p "$EQ_STATE_DIR/images" "$EQ_STATE_DIR/results" || { echo "lib.sh: cannot create $EQ_STATE_DIR" >&2; exit 2; }
  chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  EQ_STATE_DIR=$(cd "$EQ_STATE_DIR" && pwd -P)
  EQ_WORK_ROOT=${EQ_WORK_ROOT:-$EQ_STATE_DIR/work}
  mkdir -p "$EQ_WORK_ROOT" && EQ_WORK_ROOT=$(cd "$EQ_WORK_ROOT" && pwd -P)
  # the check copies hold reference proofs: nobody but the owner may list or read them (F10)
  if [ "$EQ_WORK_ROOT" = "${HOME:-/}" ] || [ "$EQ_WORK_ROOT" = / ]; then echo "lib.sh: EQ_WORK_ROOT must not be \$HOME or /" >&2; exit 2; fi
  chmod 0700 "$EQ_STATE_DIR" "$EQ_WORK_ROOT" 2>/dev/null || true
fi
EQ_ITEMS=${EQ_ITEMS:-$EQ_ISO_DIR/../items}
if [ -d "$EQ_ITEMS" ]; then EQ_ITEMS=$(cd "$EQ_ITEMS" && pwd -P); else EQ_ITEMS=""; fi
case "$EQ_WORK_ROOT$EQ_ITEMS" in *,*) echo "lib.sh: a comma in $EQ_WORK_ROOT or $EQ_ITEMS breaks --mount; use other paths" >&2; exit 2;; esac

eq_die() { echo "error: $*" >&2; exit "${EQ_DIE_RC:-2}"; }
eq_have() { command -v "$1" >/dev/null 2>&1; }
# eq_now_ms: wall clock in milliseconds (perl's Time::HiRes ships with macOS; whole seconds x 1000 when perl is missing)
eq_now_ms() { perl -MTime::HiRes=time -e 'printf "%d\n", time * 1000' 2>/dev/null || echo $(( $(date +%s) * 1000 )); }
eq_need_items() { [ -n "$EQ_ITEMS" ] && [ -d "$EQ_ITEMS/PF" ] || eq_die "equilibrium pools not found: set EQ_ITEMS to the items/ directory"; }

# ---- limits and user (defaults sized for a Docker VM with 16 CPUs / 253 GiB; override per machine)
EQ_USER=${EQ_USER:-10001:10001}
EQ_CPUS=${EQ_CPUS:-2}                  # two Lean runs overlap inside check_lean.sh (statement + answer)
EQ_MEMORY=${EQ_MEMORY:-8g}             # Lean + Mathlib import: several GB peak per check (page cache of the oleans is shared)
EQ_PIDS=${EQ_PIDS:-512}
EQ_TMPFS_OPTS=${EQ_TMPFS_OPTS:-rw,nosuid,nodev,exec,size=2g}
EQ_WORK_TMPFS=${EQ_WORK_TMPFS:-rw,nosuid,nodev,exec,size=1g,mode=1777}   # /work: the capped copy of the check files (F4)
EQ_CHECK_TIMEOUT=${EQ_CHECK_TIMEOUT:-600}
EQ_RUN_ID=${EQ_RUN_ID:-$(date +%y%m%d%H%M%S)-$$}
EQ_SECCOMP=${EQ_SECCOMP:-}

# ---- image registry: $EQ_STATE_DIR/images/<name>.env (KEY=VALUE, written by build.sh). names: full min-lean min-py min-both
EQ_IMAGE_NAMES="full min-lean min-py min-both dl-lean tc-node tc-rust tc-go tc-julia tc-haskell tc-jvm tc-pg tc-mongo"
eq_img_default_tag() {
  case "$1" in
    full) echo "eq-lean:4.34.1-arm64";; min-lean) echo "eq-lean-min:4.34.1-arm64";;
    min-py) echo "eq-py-min:4.34.1-arm64";; min-both) echo "eq-min:4.34.1-arm64";;
    dl-lean) echo "eq-lean-dl:4.34.1-arm64";;
    # extension images (TOOLS.toml): the tag only names the build; the record's image ID is the identity
    tc-node) echo "eq-node:arm64";; tc-rust) echo "eq-rust:arm64";; tc-go) echo "eq-go:arm64";; tc-julia) echo "eq-julia:arm64";;
    tc-haskell) echo "eq-haskell:arm64";; tc-jvm) echo "eq-jvm:arm64";; tc-pg) echo "eq-pg:arm64";; tc-mongo) echo "eq-mongo:arm64";;
    *) return 1;;
  esac
}
eq_img_get() { # name KEY -> value from the record, empty if none
  local f="$EQ_STATE_DIR/images/$1.env"
  [ -f "$f" ] || return 0
  sed -n "s/^$2=//p" "$f" | head -n 1
}
eq_img_tag() { local t; t=$(eq_img_get "$1" EQ_IMAGE_TAG); echo "${t:-$(eq_img_default_tag "$1")}"; }
eq_expected_id() { # REF [ID] -> the image ID a build record promises for REF (empty: no record covers it)
  # A record covers REF when (1) its tag is REF, (2) its image ID is ID, the ID the daemon reports for REF (REF is that ID or
  # another tag of the same image), (3) REF is name@sha256:<digest> and the digest is the record's manifest digest, or
  # (4) in the source layout only: the legacy $EQ_ISO_DIR/.image.env of the first build names REF as its tag.
  local f t i d ref=$1 id=${2:-}
  for f in "$EQ_STATE_DIR"/images/*.env; do
    [ -f "$f" ] || continue
    t=$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)
    if [ "$t" = "$ref" ]; then sed -n 's/^EQ_IMAGE_ID=//p' "$f" | head -n 1; return 0; fi
  done
  for f in "$EQ_STATE_DIR"/images/*.env; do
    [ -f "$f" ] || continue
    i=$(sed -n 's/^EQ_IMAGE_ID=//p' "$f" | head -n 1)
    d=$(sed -n 's/^EQ_IMAGE_MANIFEST_DIGEST=//p' "$f" | head -n 1)
    if [ -n "$id" ] && [ "$i" = "$id" ]; then echo "$i"; return 0; fi
    case "$ref" in *@sha256:*) if [ -n "$d" ] && [ "${ref#*@}" = "$d" ]; then echo "$i"; return 0; fi;; esac
  done
  f="$EQ_ISO_DIR/.image.env"
  if [ -f "$f" ] && [ "$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)" = "$ref" ]; then sed -n 's/^EQ_IMAGE_ID=//p' "$f" | head -n 1; return 0; fi
  return 0
}

EQ_PROFILE=${EQ_PROFILE:-full}
EQ_PY_EXPLICIT=0; [ -z "${EQ_IMAGE_PY:-}" ] || EQ_PY_EXPLICIT=1    # did the caller name a python image itself?
case "$EQ_PROFILE" in
  full) EQ_IMAGE_TAG=${EQ_IMAGE:-$(eq_img_tag full)}
        EQ_IMAGE_PY=${EQ_IMAGE_PY:-$EQ_IMAGE_TAG}; EQ_IMAGE_BOTH=${EQ_IMAGE_BOTH:-$EQ_IMAGE_TAG};;
  min)  EQ_IMAGE_TAG=${EQ_IMAGE:-$(eq_img_tag min-lean)}
        EQ_IMAGE_PY=${EQ_IMAGE_PY:-$(eq_img_tag min-py)}; EQ_IMAGE_BOTH=${EQ_IMAGE_BOTH:-$(eq_img_tag min-both)};;
  dl)   EQ_IMAGE_TAG=${EQ_IMAGE:-$(eq_img_tag dl-lean)}
        EQ_IMAGE_PY=${EQ_IMAGE_PY:-$(eq_img_tag min-py)}; EQ_IMAGE_BOTH=${EQ_IMAGE_BOTH:-$(eq_img_tag min-both)};;
  *) echo "lib.sh: EQ_PROFILE must be full, min or dl" >&2; exit 2;;
esac
EQ_IMAGE_SOURCE="profile $EQ_PROFILE"
[ -z "${EQ_IMAGE:-}" ] || EQ_IMAGE_SOURCE="EQ_IMAGE override"
export EQ_IMAGE_TAG EQ_IMAGE_PY EQ_IMAGE_BOTH EQ_PROFILE EQ_IMAGE_SOURCE EQ_PY_EXPLICIT

eq_need_docker() {
  eq_have docker || { echo "docker CLI not found in PATH" >&2; exit 10; }
  docker info >/dev/null 2>&1 || { echo "docker daemon not reachable (docker info; docker context use desktop-linux)" >&2; exit 10; }
  local arch
  arch=$(docker info --format '{{.Architecture}}' 2>/dev/null)
  case "$arch" in aarch64|arm64) ;; *) echo "docker daemon architecture is '$arch', expected aarch64" >&2; exit 10;; esac
}

# eq_require_image REF...: each ref must exist AND be an image a build record covers (eq_expected_id: tag, image ID or manifest
# digest), with the recorded ID equal to the daemon's. No record -> exit 11 unless EQ_ALLOW_UNRECORDED=1 (F9: an image nobody
# built here is not trusted by default). The inspected ID is remembered: eq_run starts the container from that ID, so a tag
# moved after this check cannot change what runs.
EQ_REQ_N=0; EQ_REQ_TAGS=(); EQ_REQ_IDS=()
eq_resolve_image() { # REF -> the ID eq_require_image verified for REF, else REF itself
  local i=0
  while [ "$i" -lt "$EQ_REQ_N" ]; do
    if [ "${EQ_REQ_TAGS[$i]}" = "$1" ]; then echo "${EQ_REQ_IDS[$i]}"; return 0; fi
    i=$((i + 1))
  done
  echo "$1"
}
eq_require_image() {
  local tag id want
  [ $# -gt 0 ] || set -- "$EQ_IMAGE_TAG"
  for tag in "$@"; do
    id=$(docker image inspect --format '{{.Id}}' "$tag" 2>/dev/null) || { echo "error: image $tag not found: run ./build.sh first" >&2; exit 11; }
    want=$(eq_expected_id "$tag" "$id")
    if [ -z "$want" ] && [ "${EQ_ALLOW_UNRECORDED:-0}" != 1 ]; then
      echo "error: no build record for $tag in $EQ_STATE_DIR/images (an image built elsewhere is not trusted). Build it with ./build.sh, or set EQ_ALLOW_UNRECORDED=1 to accept it knowingly." >&2
      exit 11
    fi
    if [ -n "$want" ] && [ "$id" != "$want" ]; then
      echo "error: image $tag is $id but its record says $want (rebuilt or retagged). Re-run ./build.sh --yes or delete $EQ_STATE_DIR/images deliberately." >&2
      exit 11
    fi
    EQ_REQ_TAGS[EQ_REQ_N]=$tag; EQ_REQ_IDS[EQ_REQ_N]=$id; EQ_REQ_N=$((EQ_REQ_N + 1))
    if [ "$tag" = "$EQ_IMAGE_TAG" ]; then EQ_IMAGE_ID_NOW=$id; fi
  done
  EQ_IMAGE_ID_NOW=${EQ_IMAGE_ID_NOW:-$id}
}

# Flags every container gets (the harness's isolate() argv carries the same set: --pull never, --init, --stop-timeout, the log
# options, the fixed container environment, a capped tmpfs /work). Mounts are added by the caller (EQ_RUN_MOUNTS) and eq_run
# adds the /work tmpfs; nothing else is ever mounted. The -e entries are constants, never a host variable (F7: they match the
# harness's CONTAINER_ENV). The log options bound what a container that prints without end can write to the daemon (F5).
eq_base_flags() {
  EQ_BASE_FLAGS=(
    --rm --init --pull never
    --network none --read-only --cap-drop ALL --security-opt no-new-privileges
    --pids-limit "$EQ_PIDS" --memory "$EQ_MEMORY" --memory-swap "$EQ_MEMORY" --cpus "$EQ_CPUS"
    --user "$EQ_USER" --tmpfs "/tmp:$EQ_TMPFS_OPTS"
    --stop-timeout 1
    --log-driver json-file --log-opt max-size=1m --log-opt max-file=1
    -e LANG=C.UTF-8 -e HOME=/tmp -e TMPDIR=/tmp -e UV_CACHE_DIR=/tmp/uv-cache -e UV_OFFLINE=1 -e UV_NO_CONFIG=1
    -e UV_PYTHON_DOWNLOADS=never
    --label eq-harness=1 --label "eq-run=$EQ_RUN_ID"
    -w /work
  )
  if [ -n "$EQ_SECCOMP" ]; then
    [ -f "$EQ_SECCOMP" ] || eq_die "EQ_SECCOMP file not found: $EQ_SECCOMP"
    EQ_BASE_FLAGS=("${EQ_BASE_FLAGS[@]}" --security-opt "seccomp=$EQ_SECCOMP")
  fi
}
eq_base_flags

# eq_run NAME TIMEOUT_S cmd...   uses EQ_RUN_MOUNTS (array of --mount args; a target=/work mount is the source copy, see the
# header), EQ_RUN_EXTRA (extra docker flags; later flags override earlier ones, except mounts), EQ_RUN_STDIN (file fed to the
# container), EQ_RUN_IMAGE (default $EQ_IMAGE_TAG; started by the ID eq_require_image verified), EQ_RUN_WORK_TMPFS (options of
# the /work tmpfs for this call; default $EQ_WORK_TMPFS).
# Returns the container's exit code; 124 if the watchdog killed it (docker kill NAME) after TIMEOUT_S.
eq_run() {
  local name=$1 tmo=$2 rc wd flag img
  shift 2
  img=$(eq_resolve_image "${EQ_RUN_IMAGE:-$EQ_IMAGE_TAG}")
  flag="$EQ_WORK_ROOT/.timeout-$name"
  rm -f "$flag"
  local -a stdin_flag=() mv=(${EQ_RUN_MOUNTS[@]+"${EQ_RUN_MOUNTS[@]}"}) mounts=() prefix=()
  local i=0 m src
  while [ "$i" -lt "${#mv[@]}" ]; do
    if [ "${mv[$i]}" = --mount ] && [ $((i + 1)) -lt "${#mv[@]}" ]; then
      m=${mv[$((i + 1))]}
      case "$m" in
        type=bind,source=*,target=/work)
          # F4: the host copy is read-only at /eqsrc/work; the container copies it into its own capped tmpfs /work
          src=${m#type=bind,source=}; src=${src%,target=/work}
          mounts+=(--mount "type=bind,source=$src,target=/eqsrc/work,readonly")
          prefix=(/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"' eq-run)
          i=$((i + 2)); continue;;
      esac
    fi
    mounts+=("${mv[$i]}"); i=$((i + 1))
  done
  [ -n "${EQ_RUN_STDIN:-}" ] && stdin_flag=(-i)
  docker run --name "$name" "${EQ_BASE_FLAGS[@]}" --tmpfs "/work:${EQ_RUN_WORK_TMPFS:-$EQ_WORK_TMPFS}" \
    ${EQ_RUN_EXTRA[@]+"${EQ_RUN_EXTRA[@]}"} ${mounts[@]+"${mounts[@]}"} ${stdin_flag[@]+"${stdin_flag[@]}"} \
    "$img" ${prefix[@]+"${prefix[@]}"} "$@" < "${EQ_RUN_STDIN:-/dev/null}" &
  local pid=$!
  # watchdog: polls once a second (no long-lived sleep child), detached from stdout so $(eq_run ...) cannot hang on it
  ( i=0
    while [ "$i" -lt "$tmo" ]; do sleep 1; kill -0 "$pid" 2>/dev/null || exit 0; i=$((i + 1)); done
    : > "$flag"; docker kill "$name" >/dev/null 2>&1 ) >/dev/null 2>&1 &
  wd=$!
  wait "$pid"; rc=$?
  kill "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  if [ -e "$flag" ]; then rc=124; fi
  rm -f "$flag"
  return "$rc"
}

# Kill and remove every container of this run (also from an EXIT/INT trap).
eq_sweep() {
  local ids
  ids=$(docker ps -aq --filter "label=eq-run=$EQ_RUN_ID" 2>/dev/null) || return 0
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    docker kill $ids >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    docker rm -f $ids >/dev/null 2>&1 || true
  fi
}

# Containers left by an earlier run (other run ids): reported, never removed automatically.
eq_orphans() {
  docker ps -a --filter label=eq-harness=1 --format '{{.Names}} ({{.Status}})' 2>/dev/null
}

# eq_write_result KIND RESULT FAILS: $EQ_STATE_DIR/results/KIND.<image>.env, read by doctor.sh / the installer.
eq_write_result() {
  local kind=$1 result=$2 fails=${3:-0} san up
  san=$(printf '%s' "$EQ_RUN_IMAGE_REPORT" | tr ':/@' '___')
  up=$(printf '%s' "$kind" | tr '[:lower:]' '[:upper:]')
  {
    echo "${up}_RESULT=$result"
    echo "${up}_AT=$(date -u +%FT%TZ)"
    echo "${up}_IMAGE=$EQ_RUN_IMAGE_REPORT"
    echo "${up}_IMAGE_ID=${EQ_IMAGE_ID_REPORT:-unknown}"
    echo "${up}_FAILS=$fails"
    echo "${up}_BACKEND=docker"
    echo "${up}_LIMITS=cpus=$EQ_CPUS memory=$EQ_MEMORY pids=$EQ_PIDS user=$EQ_USER seccomp=${EQ_SECCOMP:-docker-default}"
  } > "$EQ_STATE_DIR/results/$kind.$san.env.tmp" && mv "$EQ_STATE_DIR/results/$kind.$san.env.tmp" "$EQ_STATE_DIR/results/$kind.$san.env"
}

# eq_pf_check ITEM KIND MODE
#   KIND ref|wrong (items/PF/oracle/{ref,wrong}/ITEM.lean), MODE oracle|public
#   oracle: the fixture copy gets items/PF/check_lean.sh + EqVerify.lean (what oracle.py runs: the current checker)
#   public: the fixture exactly as shipped (what a member's copy holds)
# Sets PF_SCORE (1|0|timeout|err), PF_RC, PF_SECS (whole seconds), PF_MS (milliseconds, container start included),
# PF_DETAIL. The copy is fresh and world-readable under the 0700 work root, mounted read-only (it is deleted after).
eq_pf_check() {
  local item=$1 kind=$2 mode=$3 ans copy t0 ms0 verdict
  PF_MS=0
  ans="$EQ_ITEMS/PF/oracle/$kind/$item.lean"
  [ -f "$ans" ] || { PF_SCORE=err; PF_RC=-; PF_SECS=0; PF_DETAIL="missing $ans"; return 0; }
  [ -d "$EQ_ITEMS/PF/fixtures/$item" ] || { PF_SCORE=err; PF_RC=-; PF_SECS=0; PF_DETAIL="missing fixture $item"; return 0; }
  copy=$(mktemp -d "$EQ_WORK_ROOT/pf-$item-$kind.XXXXXX") || { PF_SCORE=err; PF_RC=-; PF_SECS=0; PF_DETAIL="mktemp failed"; return 0; }
  cp -R "$EQ_ITEMS/PF/fixtures/$item/." "$copy/"
  if [ "$mode" = oracle ]; then cp "$EQ_ITEMS/PF/check_lean.sh" "$EQ_ITEMS/PF/EqVerify.lean" "$copy/"; fi
  cp "$ans" "$copy/Answer.lean"
  chmod -R a+rX "$copy"   # read-only source copy: the container copies it into its own tmpfs /work (see eq_run)
  EQ_RUN_MOUNTS=(--mount "type=bind,source=$copy,target=/work"
                 --mount "type=bind,source=$EQ_ITEMS/PF/fixtures/$item,target=/fixture,readonly")
  EQ_RUN_EXTRA=()
  EQ_RUN_STDIN=""
  t0=$SECONDS; ms0=$(eq_now_ms)
  eq_run "eq-$EQ_RUN_ID-$item-$kind-$mode" "$EQ_CHECK_TIMEOUT" bash check_lean.sh Answer.lean > "$copy.out" 2> "$copy.err"
  PF_RC=$?
  PF_SECS=$((SECONDS - t0)); PF_MS=$(( $(eq_now_ms) - ms0 ))
  verdict=$(tail -n 1 "$copy.out" 2>/dev/null)
  if [ "$PF_RC" = 0 ] && [ "$verdict" = PASS ]; then PF_SCORE=1; PF_DETAIL=PASS
  elif [ "$PF_RC" = 1 ] && [ "${verdict#FAIL}" != "$verdict" ]; then PF_SCORE=0; PF_DETAIL=$verdict
  elif [ "$PF_RC" = 124 ]; then PF_SCORE=timeout; PF_DETAIL="killed after ${EQ_CHECK_TIMEOUT}s"
  else PF_SCORE=err; PF_DETAIL="rc=$PF_RC $verdict $(tail -c 300 "$copy.err" 2>/dev/null)"; fi
  PF_DETAIL=$(printf '%s' "$PF_DETAIL" | tr '\t\n\r' '   ' | cut -c1-300)
  rm -rf "$copy" "$copy.out" "$copy.err"
  return 0
}
