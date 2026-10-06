#!/usr/bin/env bash
# eq-container.sh: the installer-facing driver of lib/eq-container (the isolation images of the equilibrium harness, run with
# Apple `container`). install.sh runs it as `bash lib/eq-container/eq-container.sh install ...` for --with-eq-container; you can run
# it yourself from a normal terminal. Bash 3.2 (macOS) compatible.
#
#   eq-container.sh install   [--yes] [--no-prompt] [--dry-run] [--set min | --profiles core,jvm|all]
#                             [--keep-profile conservative|noprivate|slim] [--no-probe] [--force-verify]
#   eq-container.sh check     [--set min | --profiles ..]   images, records and pins still match (exit 0 ok, 11 not ok, 10 no
#                             container; default: the profile core)
#   eq-container.sh status                        what is installed and verified (reads the state files; no container call)
#   eq-container.sh print-env                     EQ_ISOLATION= and EQ_IMAGE= lines for stack.env (exit 1 unless the install is verified)
#   eq-container.sh uninstall [--yes] [--dry-run] [--purge]   remove the images and records (--purge: the state dir too)
#
# install = [the container CLI and its services present] -> build.sh (idempotent; TOOLS.toml pins checked, digests of the base images
# and every tool archive verified in the builder, each image's check stage first) -> verify-tools.sh (labels, locks, re-hash of every tool file from the saved image;
# smoke test of the extension images) -> probe.sh (isolation rows, the image works under the flags, probe.d hooks incl. the WALL
# tunnel) -> state files. Nothing here pushes anything, runs sudo, installs software or starts the container services for you: the
# CLI missing, its services not running (`container system start`) or a non-arm64 host is a WARNING and a skip (exit 10), never a
# failed install. --yes answers the build question only. Without --profiles and --set, the profile `core` is built. Images
# (USER decision 2026-10-06): FROM the pinned distroless cc image or FROM scratch; the Debian image of the former `--set full` is
# gone (refused: exit 2), and the deferred profiles rust and haskell are skipped (exit 10, status skipped, the reason in WHY).
#
# State ($EQ_STATE_DIR, default ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-container in the repo layout):
#   image.env    KEY=VALUE: EQ_ISOLATION, EQ_IMAGE, EQ_CONTAINER_IMAGE_PF/CP/CR (TAG@sha256:...), per-image tag and digest
#   status.env   EQ_CONTAINER_STATUS=ok|skipped|failed, _AT, _WHY, _SET, _PROFILES, _VERIFIED, _PINS_SHA256, _CHECKS_SHA256, _PROBE
#   images/NAME.env, results/{probe,tunnel}.*.env, logs/*.log
# Exit codes: 0 ok | 2 usage | 10 skipped (CLI missing, services down, wrong architecture, no terminal for the build question,
#   build declined, a deferred profile) | 11 check not ok | 12 build failed | 13 unresolved pin (PINS or TOOLS.toml placeholder) | 15 probe failed
#   16 tools verification failed (verify-tools.sh: stale label, lock mismatch, a tool file that does not hash, a smoke test)
set -u
here=$(cd "$(dirname "$0")" && pwd -P)

# ---- options ----------------------------------------------------------------------------------------------------------------
CMD=${1:-}; [ $# -eq 0 ] || shift
YES=0; NO_PROMPT=0; DRY=0; SET=""; PROFILE=""; NO_PROBE=0; FORCE_VERIFY=0; PURGE=0; PROFILES=""
need_value() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "eq-container: $1 needs a value" >&2; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1;;
    --no-prompt) NO_PROMPT=1;;
    --dry-run) DRY=1;;
    --set) need_value "$@"; SET=$2; shift;;
    --profiles) need_value "$@"; PROFILES=$2; shift;;
    --profiles=*) PROFILES=${1#--profiles=}; [ -n "$PROFILES" ] || { echo "eq-container: --profiles needs a value" >&2; exit 2; };;
    --keep-profile) need_value "$@"; PROFILE=$2; shift;;
    --no-probe) NO_PROBE=1;;
    --force-verify) FORCE_VERIFY=1;;
    --purge) PURGE=1;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    *) echo "eq-container: unknown option: $1" >&2; exit 2;;
  esac
  shift
done
case "$SET" in
  ""|min) ;;
  full) echo "eq-container: --set full was removed: the Debian image 'full' is gone (USER decision 2026-10-06, lib/eq-container/DESIGN_DISTROLESS.md); use --profiles core (the default) or --set min" >&2; exit 2;;
  *) echo "eq-container: --set must be min (full was removed)" >&2; exit 2;;
esac
if [ -n "$PROFILES" ] && [ -n "$SET" ]; then echo "eq-container: --set and --profiles exclude each other" >&2; exit 2; fi
# shellcheck disable=SC1091
. "$here/tools.sh"
tm_load "$here/TOOLS.toml" || { echo "eq-container: TOOLS.toml is unreadable" >&2; exit 2; }
if [ -z "$SET" ]; then
  pl=$(tm_expand_profiles "core,${PROFILES:-core}") || exit 2           # core is always part of it: PF, CP, CR need it
  PROFILES=$(printf '%s' "$pl" | tr '\n' ' ' | sed 's/ *$//')
fi

# ---- state dir (same default as lib.sh; computed here because lib.sh creates directories when sourced) ---------------------------
if [ -z "${EQ_STATE_DIR:-}" ]; then
  if [ "$(cat "$here/LAYOUT" 2>/dev/null)" = repo ]; then EQ_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-container"
  else EQ_STATE_DIR="$here/.state"; fi
fi
export EQ_STATE_DIR
STATUS_FILE="$EQ_STATE_DIR/status.env"

say() { printf 'eq-container: %s\n' "$*"; }
warn() { printf 'eq-container: WARN %s\n' "$*" >&2; }
now() { date -u +%FT%TZ; }
env_get() { [ -f "$1" ] || return 0; sed -n "s/^$2=//p" "$1" | head -n 1; }
pins_sha() { cat "$here/PINS" "$here/TOOLS.toml" 2>/dev/null | tm_sha256_stdin; }   # the pinned inputs: PINS and the tools manifest
# the code that verifies and probes the images, and the CLI that runs them: unchanged images skip verification and probe only
# while this is unchanged too (call it after ensure_container: it asks the CLI its version)
checks_sha() {
  { cat "$here/lib.sh" "$here/eqc_json.py" "$here/tools.sh" "$here/verify-tools.sh" "$here/probe.sh" "$here/probe_inner.sh" \
      "$here"/probe.d/*.sh 2>/dev/null
    printf 'CLI %s\n' "$("$EQ_CONTAINER_BIN" --version 2>/dev/null </dev/null | head -n 1)"; } | tm_sha256_stdin
}
profiles_csv() { printf '%s' "$PROFILES" | tr ' ' ','; }

# write_status STATUS WHY [KEY=VALUE ...]: atomic, 0600, only in a real run
write_status() {
  local st=$1 why=$2 kv; shift 2
  [ "$DRY" = 0 ] || return 0
  mkdir -p "$EQ_STATE_DIR" && chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  {
    echo "EQ_CONTAINER_STATUS=$st"
    echo "EQ_CONTAINER_STATUS_AT=$(now)"
    echo "EQ_CONTAINER_STATUS_WHY=$why"
    echo "EQ_CONTAINER_STATUS_SET=${SET:-profiles}"
    [ -z "$PROFILES" ] || echo "EQ_CONTAINER_STATUS_PROFILES=$(profiles_csv)"
    echo "EQ_CONTAINER_STATUS_PINS_SHA256=$(pins_sha)"
    for kv in "$@"; do echo "$kv"; done
  } > "$STATUS_FILE.tmp.$$" && chmod 600 "$STATUS_FILE.tmp.$$" && mv "$STATUS_FILE.tmp.$$" "$STATUS_FILE"
}
skip() { # WHY [advice]: a warning and exit 10; the install of everything else goes on
  warn "$1"; [ -z "${2:-}" ] || warn "$2"
  write_status skipped "$1"
  exit 10
}
# a deferred profile (TOOLS.toml `deferred`: rust, haskell have no image) is a skip with its reason, never a failed install
if [ "$CMD" = install ] && [ -n "$PROFILES" ]; then
  dwhy=$(tm_refuse_deferred "$PROFILES" 2>&1) || skip "$(printf '%s' "$dwhy" | tr '\n' ' ' | sed 's/ *$//')"
fi

# the container CLI, its services and the architecture (the same test as lib.sh eqc_state, without sourcing lib.sh)
EQ_CONTAINER_BIN=${EQ_CONTAINER_BIN:-$(command -v container 2>/dev/null || echo /usr/local/bin/container)}
export EQ_CONTAINER_BIN
ensure_container() {
  [ -x "$EQ_CONTAINER_BIN" ] || skip "the container CLI is not installed" \
    "install Apple container yourself (https://github.com/apple/container/releases, signed .pkg), run: container system start, then re-run; this script never installs it"
  case "${EQ_HOST_ARCH:-$(uname -m)}" in arm64|aarch64) ;; *) skip "this host is not arm64 (the images are linux/arm64; Apple container needs Apple silicon)";; esac
  "$EQ_CONTAINER_BIN" system status >/dev/null 2>&1 || skip "the container services are not running (or this shell cannot reach them)" \
    "run: container system start   (from a normal terminal: an agent sandbox cannot reach the services), then re-run"
}

build_args() { # the flags for build.sh, one per line (none contain spaces)
  if [ -n "$SET" ]; then printf '%s\n' --set "$SET"; else printf '%s\n' --profiles "$(profiles_csv)"; fi
  [ -z "$PROFILE" ] || printf '%s\n' --keep-profile "$PROFILE"
  [ "$YES" = 0 ] || printf '%s\n' --yes
}
run_build() { # extra args...  (bash 3.2: no mapfile)
  local a args=()
  while IFS= read -r a; do args[${#args[@]}]=$a; done <<EOF
$(build_args)
EOF
  bash "$here/build.sh" ${args[@]+"${args[@]}"} "$@"
}
verified_refs() { # the TAG@sha256 refs this install verifies: every image of the profiles (or the set's lean/py), from image.env
  local imf="$EQ_STATE_DIR/image.env" n up t d out=""
  if [ -n "$PROFILES" ]; then
    for n in $(tm_profile_images "$PROFILES"); do
      up=$(printf '%s' "$n" | tr '[:lower:]-' '[:upper:]_')
      t=$(env_get "$imf" "EQ_${up}_TAG"); d=$(env_get "$imf" "EQ_${up}_DIGEST")
      [ -n "$t" ] && [ -n "$d" ] && out="$out $t@$d"
    done
  else
    out="$(env_get "$imf" EQ_CONTAINER_IMAGE_PF) $(env_get "$imf" EQ_CONTAINER_IMAGE_CP)"
  fi
  printf '%s' "$out" | tr ' ' '\n' | sed '/^$/d' | LC_ALL=C sort -u | tr '\n' ',' | sed 's/,$//'
}

# ---- commands ----------------------------------------------------------------------------------------------------------------------
cmd_install() {
  ensure_container
  if [ "$DRY" = 1 ]; then
    say "dry run (state dir $EQ_STATE_DIR; nothing is created):"
    EQ_NO_STATE_WRITE=1 run_build --dry-run || true
    say "would then run: verify-tools.sh and probe.sh against the built images, and write $STATUS_FILE and image.env"
    exit 0
  fi
  mkdir -p "$EQ_STATE_DIR/logs" && chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  # build.sh's own question would go to the log file, so the question is asked here, and only when a build is due
  if [ "$YES" = 0 ] && [ "$NO_PROMPT" = 0 ] && test -t 0; then
    if EQ_NO_STATE_WRITE=1 run_build --dry-run 2>/dev/null | grep -q ' build '; then
      printf 'eq-container: build the images now? 10-40 min, several GB of disk, network for the build only [y/N] '
      read -r ans || ans=""
      case "$ans" in y|Y|yes|YES|Yes) YES=1;; *) skip "the image build was declined";; esac
    fi
  fi
  say "building (${SET:-profiles $(profiles_csv)}) ... (a cold build takes 10-40 minutes and several GB of disk; an up-to-date image is skipped)"
  local rc=0
  # stdin is /dev/null: build.sh would otherwise ask its own question on a terminal, into build.log (--no-prompt hung there)
  run_build > "$EQ_STATE_DIR/logs/build.log" 2>&1 < /dev/null || rc=$?
  tail -n 12 "$EQ_STATE_DIR/logs/build.log"
  case "$rc" in
    0) ;;
    2) skip "the build was not started (no terminal to ask on and no --yes, or an options/pins mismatch: see $EQ_STATE_DIR/logs/build.log)" "re-run with --yes";;
    10) skip "the container services became unavailable during the build";;
    13) write_status failed "unresolved pin"; warn "a pin in PINS or TOOLS.toml is still a placeholder (see above): the bash pins come from bash lib/eq-container/build.sh --resolve-tools (GPG-checked; review, then --write-pin) run from a normal terminal (README.md, checklist D2)"; exit 13;;
    *) write_status failed "build failed (rc $rc)"; warn "build failed (rc $rc); log: $EQ_STATE_DIR/logs/build.log"; exit 12;;
  esac
  local refs prev probe=skipped checks
  refs=$(verified_refs)
  [ -n "$refs" ] || { write_status failed "no image recorded after the build"; warn "no image recorded"; exit 12; }
  prev=$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS_VERIFIED)
  checks=$(checks_sha)
  if [ "$FORCE_VERIFY" = 0 ] && [ "$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS)" = ok ] && [ "$prev" = "$refs" ] \
     && [ "$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS_PINS_SHA256)" = "$(pins_sha)" ] \
     && [ "$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS_CHECKS_SHA256)" = "$checks" ]; then
    say "images unchanged and already verified: verification and probe skipped (--force-verify runs them again)"
    exit 0
  fi
  if [ -n "$PROFILES" ]; then
    say "verifying the tools manifest against the built images (labels, locks, every tool file re-hashed from the saved image) ..."
    if ! bash "$here/verify-tools.sh" --images --deep --inspect --profiles "$(profiles_csv)" > "$EQ_STATE_DIR/logs/verify-tools.log" 2>&1; then
      tail -n 15 "$EQ_STATE_DIR/logs/verify-tools.log"
      write_status failed "tools verification failed"; warn "tools verification failed; log: $EQ_STATE_DIR/logs/verify-tools.log"; exit 16
    fi
    local extras="" n
    for n in $(tm_profile_images "$PROFILES"); do [ "$(tm_get image "$n" profile)" = core ] || extras="$extras$n,"; done
    if [ -n "$extras" ]; then
      say "smoke test of the extension images (${extras%,}) ..."
      if ! bash "$here/verify-tools.sh" --smoke --select "${extras%,}" > "$EQ_STATE_DIR/logs/smoke.log" 2>&1; then
        tail -n 15 "$EQ_STATE_DIR/logs/smoke.log"
        write_status failed "smoke test failed"; warn "smoke test failed; log: $EQ_STATE_DIR/logs/smoke.log"; exit 16
      fi
    fi
    say "tools: verified"
  fi
  if [ "$NO_PROBE" = 0 ]; then
    local pf cp
    pf=$(env_get "$EQ_STATE_DIR/image.env" EQ_CONTAINER_IMAGE_PF); cp=$(env_get "$EQ_STATE_DIR/image.env" EQ_CONTAINER_IMAGE_CP)
    say "probe (network, mounts, secrets, limits, the image works, the WALL tunnel) ..."
    if EQ_PROBE_IMAGES="$pf $cp" bash "$here/probe.sh" > "$EQ_STATE_DIR/logs/probe.log" 2>&1; then probe=PASS
    else tail -n 25 "$EQ_STATE_DIR/logs/probe.log"; write_status failed "probe failed" "EQ_CONTAINER_STATUS_PROBE=FAIL"; warn "probe failed; log: $EQ_STATE_DIR/logs/probe.log"; exit 15; fi
    say "probe: PASS"
  fi
  write_status ok "installed and verified" "EQ_CONTAINER_STATUS_VERIFIED=$refs" "EQ_CONTAINER_STATUS_CHECKS_SHA256=$checks" \
    "EQ_CONTAINER_STATUS_PROBE=$probe"
  say "done. image.env: $EQ_STATE_DIR/image.env"
  exit 0
}

cmd_check() {
  local sel=(--profiles core)
  [ -z "$SET" ] || sel=(--set "$SET")
  [ -z "$PROFILES" ] || sel=(--profiles "$(profiles_csv)")
  EQ_NO_STATE_WRITE=1 bash "$here/build.sh" "${sel[@]}" --check
}

cmd_status() {
  if [ ! -f "$STATUS_FILE" ]; then say "not installed (no $STATUS_FILE)"; exit 1; fi
  sed 's/^/eq-container: /' "$STATUS_FILE"
  [ ! -f "$EQ_STATE_DIR/image.env" ] || sed 's/^/eq-container: /' "$EQ_STATE_DIR/image.env"
  [ "$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS)" = ok ]
}

cmd_print_env() {
  [ "$(env_get "$STATUS_FILE" EQ_CONTAINER_STATUS)" = ok ] || exit 1
  local img; img=$(env_get "$EQ_STATE_DIR/image.env" EQ_IMAGE)
  case "$img" in eq.invalid/*@sha256:*) ;; *) exit 1;; esac
  echo "EQ_ISOLATION=container"
  echo "EQ_IMAGE=$img"
}

cmd_uninstall() {
  if [ "$DRY" = 1 ]; then
    EQ_NO_STATE_WRITE=1 bash "$here/build.sh" --set all --uninstall --dry-run --yes
    [ "$PURGE" = 0 ] || say "would remove $EQ_STATE_DIR (--purge)"
    exit 0
  fi
  local args=(--set all --uninstall) rc=0
  [ "$YES" = 0 ] || args[${#args[@]}]=--yes
  bash "$here/build.sh" "${args[@]}" || rc=$?
  if [ "$rc" = 10 ]; then warn "the container services are unavailable: the images and records stay; start them and run this again"; exit 10; fi
  [ "$rc" = 0 ] || exit "$rc"
  rm -f "$EQ_STATE_DIR/image.env" "$STATUS_FILE"
  if [ "$PURGE" = 1 ]; then
    case "$EQ_STATE_DIR" in
      */eq-container|*/eq-container/) rm -rf "$EQ_STATE_DIR"; say "removed $EQ_STATE_DIR";;
      *) warn "--purge only removes a directory named eq-container; $EQ_STATE_DIR kept";;
    esac
  fi
  exit 0
}

case "$CMD" in
  install) cmd_install;;
  check) cmd_check; exit $?;;
  status) cmd_status; exit $?;;
  print-env) cmd_print_env;;
  uninstall) cmd_uninstall;;
  ""|-h|--help|help) sed -n '2,30p' "$0"; exit 0;;
  *) echo "eq-container: unknown command: $CMD (install, check, status, print-env, uninstall)" >&2; exit 2;;
esac
