# shellcheck shell=bash disable=SC2034
# lib.sh: shared helpers of lib/eq-container (source it; do not run it): the state dir, the image records, the one place that
# builds a `container run` (eq_run), the digest check before every run (eq_require_image) and the sweep. Bash 3.2 (macOS).
# Backend: Apple `container` (https://github.com/apple/container, CLI 1.5.0): every container is its own lightweight VM.
# Nothing here runs at source time except path resolution and (unless EQ_NO_STATE_WRITE=1) mkdir of the state dir.
#
# Environment (all optional):
#   EQ_STATE_DIR      results, image records, scratch copies, logs (default ./.state; with LAYOUT = repo:
#                     ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-container)
#   EQ_CONTAINER_BIN  the CLI (default: container on PATH, else /usr/local/bin/container)
#   EQ_USER EQ_CPUS EQ_MEMORY EQ_NPROC EQ_TMP_SIZE EQ_WORK_SIZE EQ_CHECK_TIMEOUT   limits of every run (see below)
#   EQ_NO_STATE_WRITE=1   read-only mode (--dry-run, --check, status): no directory is created
#   EQ_WORK_ROOT      where fresh check copies are made (default $EQ_STATE_DIR/work, 0700; refused when $HOME or /)
#   EQ_ALLOW_UNRECORDED=1  eq_require_image accepts NAME:TAG@sha256:DIGEST that no build record covers (the digest is checked)
# /work design (the same as the harness's isolate()): a mount whose target is /work in EQ_RUN_MOUNTS is a SOURCE COPY: eq_run
# binds it read-only at /eqsrc/work and starts `/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"'` on a capped tmpfs /work,
# so nothing the code writes reaches a host directory.
# Exit codes (all scripts): 0 ok | 1 verification failed | 2 usage or configuration error
#   10 container CLI missing, its services not running, or not an arm64 host (the installer treats this as SKIP)
#   11 image missing, stale or not matching its record | 12 image build failed | 13 a pin is an unresolved placeholder

EQ_ISO_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
if [ -z "${EQ_STATE_DIR:-}" ]; then
  if [ "$(cat "$EQ_ISO_DIR/LAYOUT" 2>/dev/null)" = repo ]; then
    EQ_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-container"
  else
    EQ_STATE_DIR="$EQ_ISO_DIR/.state"
  fi
fi
if [ "${EQ_NO_STATE_WRITE:-}" = 1 ]; then
  [ ! -d "$EQ_STATE_DIR" ] || EQ_STATE_DIR=$(cd "$EQ_STATE_DIR" && pwd -P)
  EQ_WORK_ROOT=${EQ_WORK_ROOT:-$EQ_STATE_DIR/work}
else
  mkdir -p "$EQ_STATE_DIR/images" "$EQ_STATE_DIR/results" || { echo "lib.sh: cannot create $EQ_STATE_DIR" >&2; exit 2; }
  chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  EQ_STATE_DIR=$(cd "$EQ_STATE_DIR" && pwd -P)
  EQ_WORK_ROOT=${EQ_WORK_ROOT:-$EQ_STATE_DIR/work}
  mkdir -p "$EQ_WORK_ROOT" && EQ_WORK_ROOT=$(cd "$EQ_WORK_ROOT" && pwd -P)
  if [ "$EQ_WORK_ROOT" = "${HOME:-/}" ] || [ "$EQ_WORK_ROOT" = / ]; then echo "lib.sh: EQ_WORK_ROOT must not be \$HOME or /" >&2; exit 2; fi
  chmod 0700 "$EQ_STATE_DIR" "$EQ_WORK_ROOT" 2>/dev/null || true
fi
case "$EQ_WORK_ROOT" in *,*|*:*) echo "lib.sh: a comma or colon in $EQ_WORK_ROOT breaks --mount; use another path" >&2; exit 2;; esac

eq_die() { echo "error: $*" >&2; exit "${EQ_DIE_RC:-2}"; }
eq_have() { command -v "$1" >/dev/null 2>&1; }

# ---- the CLI ---------------------------------------------------------------------------------------------------------------------
EQ_CONTAINER_BIN=${EQ_CONTAINER_BIN:-}
if [ -z "$EQ_CONTAINER_BIN" ]; then
  if eq_have container; then EQ_CONTAINER_BIN=$(command -v container)
  elif [ -x /usr/local/bin/container ]; then EQ_CONTAINER_BIN=/usr/local/bin/container
  else EQ_CONTAINER_BIN=container; fi
fi
eqc() { "$EQ_CONTAINER_BIN" "$@"; }
eqc_json() { python3 -I "$EQ_ISO_DIR/eqc_json.py" "$@"; }   # every JSON shape of the CLI is read there (and nowhere else)
# eqc_state: sets EQC_OK=1/0 and EQC_WHY; never exits. `container system status` answers only while the services run
# (`container system start`); nothing is started here. An agent's Seatbelt sandbox gets "Operation not permitted" from every
# command that talks to the services (observed 2026-10-05), so run this from a normal terminal.
eqc_state() {
  EQC_OK=0; EQC_WHY=""
  if ! { [ -x "$EQ_CONTAINER_BIN" ] || eq_have "$EQ_CONTAINER_BIN"; }; then
    EQC_WHY="the container CLI was not found (Apple container: https://github.com/apple/container/releases)"; return 0
  fi
  case "${EQ_HOST_ARCH:-$(uname -m)}" in arm64|aarch64) ;; *) EQC_WHY="this host is not arm64 (Apple silicon is required)"; return 0;; esac
  if ! eqc system status >/dev/null 2>&1; then
    EQC_WHY="the container services are not running (run: container system start), or this shell may not reach them (an agent sandbox cannot)"; return 0
  fi
  EQC_OK=1
}
eq_need_container() { eqc_state; [ "$EQC_OK" = 1 ] || { echo "$EQC_WHY" >&2; exit 10; }; }
# the image digest as `container image inspect` reports it (path: eqc_json.py, UNVERIFIED there); 1 when absent or unreadable
eqc_image_digest() { eqc image inspect "$1" 2>/dev/null | eqc_json digest; }

# ---- limits and user (every run; the harness's flags.json `container_*` keys carry the same values) --------------------------------
EQ_USER=${EQ_USER:-10001:10001}
EQ_CPUS=${EQ_CPUS:-2}              # two Lean runs overlap inside check_lean.sh (statement + answer)
EQ_MEMORY=${EQ_MEMORY:-8G}         # the VM's memory: Lean + Mathlib import needs several GB; the tmpfs mounts live in it too
EQ_NPROC=${EQ_NPROC:-512}          # --ulimit nproc (RLIMIT_NPROC of the unprivileged uid; `container run` has no pids limit)
EQ_TMP_SIZE=${EQ_TMP_SIZE:-2G}     # the tmpfs /tmp
EQ_WORK_SIZE=${EQ_WORK_SIZE:-1G}   # the tmpfs /work: the capped copy of the check files
EQ_CHECK_TIMEOUT=${EQ_CHECK_TIMEOUT:-600}
EQ_RUN_ID=${EQ_RUN_ID:-$(date +%y%m%d%H%M%S)-$$}

# ---- image registry: $EQ_STATE_DIR/images/<name>.env (KEY=VALUE, written by build.sh) ------------------------------------------
# Every image is named under the reserved top-level domain .invalid (RFC 6761): a reference that is not present locally can never
# be pulled from a registry by `container run`, it fails to resolve.
EQ_IMAGE_NAMES="full min-lean min-py min-both tc-node tc-rust tc-go tc-julia tc-haskell tc-jvm"
eq_img_default_tag() {
  case "$1" in
    full) echo "eq.invalid/eq-lean:4.34.1-arm64";; min-lean) echo "eq.invalid/eq-lean-min:4.34.1-arm64";;
    min-py) echo "eq.invalid/eq-py-min:4.34.1-arm64";; min-both) echo "eq.invalid/eq-min:4.34.1-arm64";;
    tc-node) echo "eq.invalid/eq-node:arm64";; tc-rust) echo "eq.invalid/eq-rust:arm64";; tc-go) echo "eq.invalid/eq-go:arm64";;
    tc-julia) echo "eq.invalid/eq-julia:arm64";; tc-haskell) echo "eq.invalid/eq-haskell:arm64";; tc-jvm) echo "eq.invalid/eq-jvm:arm64";;
    *) return 1;;
  esac
}
eq_img_get() { # name KEY -> value from the record, empty if none
  local f="$EQ_STATE_DIR/images/$1.env"
  [ -f "$f" ] || return 0
  sed -n "s/^$2=//p" "$f" | head -n 1
}
eq_img_tag() { local t; t=$(eq_img_get "$1" EQ_IMAGE_TAG); echo "${t:-$(eq_img_default_tag "$1")}"; }
eq_pinned_ref() { local t d; t=$(eq_img_get "$1" EQ_IMAGE_TAG); d=$(eq_img_get "$1" EQ_IMAGE_DIGEST); [ -n "$t" ] && [ -n "$d" ] && echo "$t@$d"; }

# eq_require_image REF...: REF is a tag or TAG@sha256:<64 hex>. The digest `container image inspect TAG` reports now must equal the
# one a build record promises for TAG (or the pinned one of REF). No record and no pin -> exit 11 (an image nobody built here is not
# trusted). Sets EQ_IMAGE_DIGEST_NOW. The run itself names the TAG (a locally built image is found by its name, never by digest:
# ClientImage._search in CLI 1.5.0), so eq_run calls this right before every run.
eq_require_image() {
  local ref tag pin want now f
  for ref in "$@"; do
    tag=${ref%@*}; pin=""
    case "$ref" in *@sha256:*) pin=${ref#*@};; esac
    want=""
    for f in "$EQ_STATE_DIR"/images/*.env; do
      [ -f "$f" ] || continue
      if [ "$(sed -n 's/^EQ_IMAGE_TAG=//p' "$f" | head -n 1)" = "$tag" ]; then want=$(sed -n 's/^EQ_IMAGE_DIGEST=//p' "$f" | head -n 1); break; fi
    done
    if [ -z "$want" ]; then
      if [ -n "$pin" ] && [ "${EQ_ALLOW_UNRECORDED:-0}" = 1 ]; then want=$pin
      else echo "error: no build record for $tag in $EQ_STATE_DIR/images (an image built elsewhere is not trusted): build it with build.sh" >&2; exit 11; fi
    fi
    if [ -n "$pin" ] && [ "$pin" != "$want" ]; then echo "error: $ref pins $pin but the record says $want" >&2; exit 11; fi
    now=$(eqc_image_digest "$tag") || { echo "error: image $tag not present (or its digest unreadable): build it with build.sh" >&2; exit 11; }
    if [ "$now" != "$want" ]; then
      echo "error: image $tag is $now but its record says $want (rebuilt or retagged): re-run build.sh --yes" >&2; exit 11
    fi
    EQ_IMAGE_DIGEST_NOW=$now
  done
}

# Flags every container gets (the harness's isolate() argv carries the same set). Only options `container run --help` (1.5.0)
# lists: --rm, --network (the value none: the user's spike), --read-only, --cap-drop ALL, --init, -m, -c, --ulimit, --user,
# --tmpfs, -e, --label, -w. No network, read-only root, no capabilities, an init process, a memory and CPU size for the VM, a
# process-count limit, the unprivileged user, a capped tmpfs /tmp, the fixed environment (never a host variable: every -e entry
# is KEY=VALUE; `-e KEY` alone would inherit it from the host), labels for the sweep. The tmpfs size= and mode= suboptions are
# from docs/volumes.md at tag 1.5.0, not from the help text: probe.sh proves the caps (work_tmpfs_size, work_size_capped).
# EQ_RUN_MEMORY / EQ_RUN_NPROC lower the memory size / process limit for one run (probe.sh's enforcement sub-probes only).
eq_base_flags() {
  EQ_BASE_FLAGS=(
    --rm --network none --read-only --cap-drop ALL --init
    -m "${EQ_RUN_MEMORY:-$EQ_MEMORY}" -c "$EQ_CPUS" --ulimit "nproc=${EQ_RUN_NPROC:-$EQ_NPROC}"
    --user "$EQ_USER" --tmpfs "/tmp:size=$EQ_TMP_SIZE,mode=1777"
    -e LANG=C.UTF-8 -e HOME=/tmp -e TMPDIR=/tmp -e UV_CACHE_DIR=/tmp/uv-cache -e UV_OFFLINE=1 -e UV_NO_CONFIG=1
    -e UV_PYTHON_DOWNLOADS=never
    --label eq-harness=1 --label "eq-run=$EQ_RUN_ID"
    -w /work
  )
}
eq_base_flags

# eq_run NAME TIMEOUT_S cmd...   uses EQ_RUN_MOUNTS (array of --mount args, each type=bind,source=..,target=..[,readonly]; a target
# /work mount is the source copy, see the header; every other one must be readonly), EQ_RUN_STDIN (a file fed to the container,
# with -i), EQ_RUN_IMAGE (a tag or TAG@sha256:..; default the min-both image), EQ_RUN_WORK_SIZE (the /work tmpfs size; default
# $EQ_WORK_SIZE), EQ_RUN_TUNNEL (a WALL channel dir, bound read-write at /eq/tunnel: the tunnel probe only), EQ_RUN_MEMORY,
# EQ_RUN_NPROC. Returns the container's exit code; 124 when the watchdog stopped it (container kill NAME) after TIMEOUT_S.
eq_run() {
  local name=$1 tmo=$2 rc wd flag img tag
  shift 2
  img=${EQ_RUN_IMAGE:-$(eq_img_tag min-both)}
  eq_require_image "$img"
  tag=${img%@*}
  eq_base_flags
  flag="$EQ_WORK_ROOT/.timeout-$name"
  rm -f "$flag"
  local -a stdin_flag=() mv=(${EQ_RUN_MOUNTS[@]+"${EQ_RUN_MOUNTS[@]}"}) mounts=() prefix=()
  local i=0 m src
  while [ "$i" -lt "${#mv[@]}" ]; do
    if [ "${mv[$i]}" = --mount ] && [ $((i + 1)) -lt "${#mv[@]}" ]; then
      m=${mv[$((i + 1))]}
      case "$m" in
        type=bind,source=*,target=/work)
          src=${m#type=bind,source=}; src=${src%,target=/work}
          mounts+=(--mount "type=bind,source=$src,target=/eqsrc/work,readonly")
          prefix=(/bin/sh -c 'cp -R /eqsrc/work/. /work/ && exec "$@"' eq-run)
          i=$((i + 2)); continue;;
        type=bind,source=*,target=*,readonly) mounts+=(--mount "$m"); i=$((i + 2)); continue;;
        *) eq_die "eq_run: mount '$m' is neither the /work source copy nor read-only";;
      esac
    fi
    eq_die "eq_run: EQ_RUN_MOUNTS holds '${mv[$i]}' (only --mount pairs)"
  done
  if [ -n "${EQ_RUN_TUNNEL:-}" ]; then mounts+=(--mount "type=bind,source=$EQ_RUN_TUNNEL,target=/eq/tunnel"); fi
  [ -n "${EQ_RUN_STDIN:-}" ] && stdin_flag=(-i)
  eqc run --name "$name" "${EQ_BASE_FLAGS[@]}" --tmpfs "/work:size=${EQ_RUN_WORK_SIZE:-$EQ_WORK_SIZE},mode=1777" \
    ${mounts[@]+"${mounts[@]}"} ${stdin_flag[@]+"${stdin_flag[@]}"} \
    "$tag" ${prefix[@]+"${prefix[@]}"} "$@" < "${EQ_RUN_STDIN:-/dev/null}" &
  local pid=$!
  # watchdog: polls once a second, detached from stdout so $(eq_run ...) cannot hang on it
  ( i=0
    while [ "$i" -lt "$tmo" ]; do sleep 1; kill -0 "$pid" 2>/dev/null || exit 0; i=$((i + 1)); done
    : > "$flag"; eqc kill "$name" >/dev/null 2>&1 ) >/dev/null 2>&1 &
  wd=$!
  wait "$pid"; rc=$?
  kill "$wd" 2>/dev/null || true
  wait "$wd" 2>/dev/null || true
  if [ -e "$flag" ]; then rc=124; fi
  rm -f "$flag"
  return "$rc"
}

# ids of every container (running or stopped) carrying LABEL=VALUE; 0 when a container NAME exists (container list --all)
eq_list_ids() { eqc list --all --format json 2>/dev/null | eqc_json ids "$1"; }
eq_container_exists() { eqc list --all --format json 2>/dev/null | eqc_json exists "$1"; }
# Kill and remove every container of this run (also from an EXIT/INT trap).
eq_sweep() {
  local ids
  ids=$(eq_list_ids "eq-run=$EQ_RUN_ID") || return 0
  if [ -n "$ids" ]; then
    # shellcheck disable=SC2086
    eqc kill $ids >/dev/null 2>&1 || true
    # shellcheck disable=SC2086
    eqc delete --force $ids >/dev/null 2>&1 || true
  fi
}

# eq_save_image TAG DIR: `container image save --output DIR/image.tar TAG` (read from outside the image: nothing is started)
eq_save_image() {
  local out="$2/image.tar"
  rm -f "$out"
  eqc image save --output "$out" "$1" >/dev/null 2>&1 && [ -s "$out" ] && echo "$out"
}

# eq_write_result KIND RESULT FAILS: $EQ_STATE_DIR/results/KIND.<image>.env, read by doctor.sh and the installer
eq_write_result() {
  local kind=$1 result=$2 fails=${3:-0} san up
  san=$(printf '%s' "$EQ_RUN_IMAGE_REPORT" | tr ':/@' '___')
  up=$(printf '%s' "$kind" | tr '[:lower:]' '[:upper:]')
  {
    echo "${up}_RESULT=$result"
    echo "${up}_AT=$(date -u +%FT%TZ)"
    echo "${up}_IMAGE=$EQ_RUN_IMAGE_REPORT"
    echo "${up}_IMAGE_DIGEST=${EQ_IMAGE_ID_REPORT:-unknown}"
    echo "${up}_FAILS=$fails"
    echo "${up}_BACKEND=container"
    echo "${up}_LIMITS=cpus=$EQ_CPUS memory=$EQ_MEMORY nproc=$EQ_NPROC user=$EQ_USER tmp=$EQ_TMP_SIZE work=$EQ_WORK_SIZE"
  } > "$EQ_STATE_DIR/results/$kind.$san.env.tmp" && mv "$EQ_STATE_DIR/results/$kind.$san.env.tmp" "$EQ_STATE_DIR/results/$kind.$san.env"
}
