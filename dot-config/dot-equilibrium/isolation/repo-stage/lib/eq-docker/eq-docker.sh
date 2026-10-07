#!/usr/bin/env bash
# eq-docker.sh: the installer-facing driver of lib/eq-docker (the isolation images of the equilibrium harness). install.sh runs it
# as `bash lib/eq-docker/eq-docker.sh install ...` for --with-eq-docker; you can run it yourself. Bash 3.2 (macOS) compatible.
#
#   eq-docker.sh install   [--yes] [--install-docker] [--docker-via cask|colima] [--no-prompt] [--dry-run]
#                          [--set min|dl|full | --profiles core,jvm,db|all] [--wait-daemon SECONDS]
#                          [--keep-profile conservative|noprivate|slim] [--no-spike] [--no-probe] [--force-verify]
#   eq-docker.sh check     [--set .. | --profiles ..]   images, records and pins still match (exit 0 ok, 11 not ok, 10 docker unavailable)
#   eq-docker.sh status                        what is installed and verified (reads the state files; no docker call)
#   eq-docker.sh print-env                     EQ_ISOLATION= and EQ_IMAGE= lines for stack.env (exit 1 unless the install is verified)
#   eq-docker.sh uninstall [--yes] [--dry-run] [--purge] [--prune-cache]   remove the images and records (--purge: the state dir too)
#
# install = [offer Docker if missing] -> bounded wait for the daemon -> build.sh (idempotent; TOOLS.toml pins checked, digests of the
# base image and every tool archive verified in the builder) -> verify-tools.sh (labels, locks, host-side re-hash of every tool
# file; smoke test of the extension images) -> spike.sh --builtin -> probe.sh (+ probe.d hooks) -> state files. Nothing here
# pushes anything, runs sudo, or touches ~/.docker/config.json. Docker missing or its daemon down (after the bounded wait) is a
# WARNING and a skip (exit 10), never a failed install. Docker is installed by Homebrew only after explicit consent: an answer on
# the terminal, or --install-docker; --yes alone is NOT consent (it only answers the build question). Homebrew itself is never
# installed here. --profiles selects TOOLS.toml profiles (core is always built: the minimum the item classes PF, CP, CR need;
# `all` = every profile not marked explicit, so not mongo); without --profiles and --set the behaviour is the one before profiles.
# Nothing is pulled: images are built locally, so no registry digest of an eq image exists to verify; the verified digests are the
# base image's (PINS), every tool archive's sha256 (TOOLS.toml, checked in the builder) and the built image's ID (recorded, rechecked).
#
# State ($EQ_STATE_DIR, default ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/eq-docker in the repo layout):
#   image.env    machine-readable (KEY=VALUE): EQ_ISOLATION, EQ_IMAGE, EQ_DOCKER_IMAGE_PF/CP/CR, per-image tag/id/olean hash
#   status.env   EQ_DOCKER_STATUS=ok|skipped|failed, _AT, _WHY, _SET, _VERIFIED_IDS, _PINS_SHA256, _SPIKE, _PROBE
#   images/NAME.env, results/*.env, logs/*.log, image.json
# Exit codes: 0 ok | 2 usage | 10 skipped (docker missing/down/wrong arch, no consent, no terminal) | 11 check not ok or image missing
#   12 build failed | 13 unresolved pin (PINS or TOOLS.toml placeholder) | 14 spike failed | 15 probe failed
#   16 tools verification failed (verify-tools.sh: stale label, lock mismatch, a tool file that does not hash, a smoke test)
set -u
here=$(cd "$(dirname "$0")" && pwd -P)
DEFAULT_SET=min      # the maintainer flips this after RUNBOOK_MINIMAL.md section 3 (min = FROM scratch; dl; full)

# ---- options ----------------------------------------------------------------------------------------------------------------
CMD=${1:-}; [ $# -eq 0 ] || shift
YES=0; INSTALL_DOCKER=0; VIA=cask; NO_PROMPT=0; DRY=0; SET=$DEFAULT_SET; SET_GIVEN=0; PROFILE=""; NO_SPIKE=0; NO_PROBE=0; FORCE_VERIFY=0
PURGE=0; PRUNE=0; PROFILES=""; WAIT_S=${EQ_DOCKER_WAIT_S:-90}; POLL_S=${EQ_DOCKER_WAIT_POLL:-3}   # 90 s: an estimate, not measured
need_value() { [ $# -ge 2 ] && [ -n "$2" ] || { echo "eq-docker: $1 needs a value" >&2; exit 2; }; }   # usage error = exit 2 (`${2:?}` exits 1)
while [ $# -gt 0 ]; do
  case "$1" in
    --yes|-y) YES=1;;
    --install-docker) INSTALL_DOCKER=1;;
    --docker-via) need_value "$@"; VIA=$2; shift;;
    --no-prompt) NO_PROMPT=1;;
    --dry-run) DRY=1;;
    --set) need_value "$@"; SET=$2; SET_GIVEN=1; shift;;
    --profiles) need_value "$@"; PROFILES=$2; shift;;
    --profiles=*) PROFILES=${1#--profiles=};;
    --wait-daemon) need_value "$@"; WAIT_S=$2; shift;;
    --keep-profile) need_value "$@"; PROFILE=$2; shift;;
    --no-spike) NO_SPIKE=1;;
    --no-probe) NO_PROBE=1;;
    --force-verify) FORCE_VERIFY=1;;
    --purge) PURGE=1;;
    --prune-cache) PRUNE=1;;
    -h|--help) sed -n '2,30p' "$0"; exit 0;;
    *) echo "eq-docker: unknown option: $1" >&2; exit 2;;
  esac
  shift
done
case "$VIA" in cask|colima) ;; *) echo "eq-docker: --docker-via must be cask or colima" >&2; exit 2;; esac
case "$SET" in min|dl|full) ;; *) echo "eq-docker: --set must be min, dl or full" >&2; exit 2;; esac
case "$WAIT_S$POLL_S" in *[!0-9]*|"") echo "eq-docker: --wait-daemon / EQ_DOCKER_WAIT_POLL need whole seconds" >&2; exit 2;; esac
[ "$POLL_S" -gt 0 ] || POLL_S=1
if [ -n "$PROFILES" ]; then
  [ "$SET_GIVEN" = 0 ] || { echo "eq-docker: --set and --profiles exclude each other" >&2; exit 2; }
  # shellcheck disable=SC1091
  . "$here/tools.sh"
  tm_load "$here/TOOLS.toml" || { echo "eq-docker: TOOLS.toml is unreadable" >&2; exit 2; }
  pl=$(tm_expand_profiles "core,$PROFILES") || exit 2          # core is always part of it: PF, CP, CR need it
  PROFILES=$(printf '%s' "$pl" | tr '\n' ' ' | sed 's/ *$//')
fi

# ---- state dir (same default as lib.sh; computed here because lib.sh creates directories when sourced) ---------------------------
if [ -z "${EQ_STATE_DIR:-}" ]; then
  if [ "$(cat "$here/LAYOUT" 2>/dev/null)" = repo ]; then EQ_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-docker"
  else EQ_STATE_DIR="$here/.state"; fi
fi
export EQ_STATE_DIR
STATUS_FILE="$EQ_STATE_DIR/status.env"

say() { printf 'eq-docker: %s\n' "$*"; }
warn() { printf 'eq-docker: WARN %s\n' "$*" >&2; }
sha256_stdin() { if command -v shasum >/dev/null 2>&1; then shasum -a 256 | cut -d' ' -f1; else sha256sum | cut -d' ' -f1; fi; }
now() { date -u +%FT%TZ; }
env_get() { [ -f "$1" ] || return 0; sed -n "s/^$2=//p" "$1" | head -n 1; }
pins_sha() { cat "$here/PINS" "$here/TOOLS.toml" 2>/dev/null | sha256_stdin; }   # the pinned inputs: PINS and the tools manifest

# write_status STATUS WHY [KEY=VALUE ...]: atomic, 0600, only in a real run
write_status() {
  local st=$1 why=$2; shift 2
  [ "$DRY" = 0 ] || return 0
  mkdir -p "$EQ_STATE_DIR" && chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  {
    echo "EQ_DOCKER_STATUS=$st"
    echo "EQ_DOCKER_STATUS_AT=$(now)"
    echo "EQ_DOCKER_STATUS_WHY=$why"
    echo "EQ_DOCKER_STATUS_SET=$SET"
    [ -z "$PROFILES" ] || echo "EQ_DOCKER_STATUS_PROFILES=$(printf '%s' "$PROFILES" | tr ' ' ',')"
    echo "EQ_DOCKER_STATUS_PINS_SHA256=$(pins_sha)"
    local kv; for kv in "$@"; do echo "$kv"; done
  } > "$STATUS_FILE.tmp.$$" && chmod 600 "$STATUS_FILE.tmp.$$" && mv "$STATUS_FILE.tmp.$$" "$STATUS_FILE"
}
skip() { # WHY [advice]: a warning and exit 10; the install of everything else goes on
  warn "$1"; [ -z "${2:-}" ] || warn "$2"
  write_status skipped "$1"
  exit 10
}

# ---- Docker: find it, and offer to install it (prompt or --install-docker only) ------------------------------------------------
APP_DIRS=${EQ_DOCKER_APP_DIRS-/Applications/Docker.app $HOME/Applications/Docker.app}
EXTRA_BIN_DIRS=${EQ_DOCKER_BIN_DIRS-$HOME/.docker/bin /Applications/Docker.app/Contents/Resources/bin /usr/local/bin /opt/homebrew/bin}
BREW_DIRS=${EQ_BREW_DIRS-/opt/homebrew/bin /usr/local/bin}
have() { command -v "$1" >/dev/null 2>&1; }
app_present() { local d; for d in $APP_DIRS; do [ -d "$d" ] && return 0; done; return 1; }
add_path_for() { # tool: append the first dir of EXTRA_BIN_DIRS / BREW_DIRS holding it to PATH (this process only)
  local d; have "$1" && return 0
  for d in $EXTRA_BIN_DIRS $BREW_DIRS; do [ -x "$d/$1" ] && { PATH="$PATH:$d"; export PATH; return 0; }; done
  return 1
}
daemon_up() { docker info >/dev/null 2>&1; }
# wait_daemon: a bounded wait (WAIT_S seconds, polling every POLL_S) for a daemon that is starting; 0 when it answers, 1 on timeout.
# Nothing is started for the user. No wait in a dry run, none when WAIT_S is 0.
wait_daemon() {
  local waited=0
  daemon_up && return 0
  [ "$DRY" = 0 ] && [ "$WAIT_S" -gt 0 ] || return 1
  say "waiting up to ${WAIT_S}s for the Docker daemon (start Docker Desktop or colima if it is not running; nothing is started for you)"
  while [ "$waited" -lt "$WAIT_S" ]; do
    sleep "$POLL_S"; waited=$((waited + POLL_S))
    if daemon_up; then say "the Docker daemon answered after ${waited}s"; return 0; fi
  done
  return 1
}
daemon_arch_ok() { case "$(docker info --format '{{.Architecture}}' 2>/dev/null)" in aarch64|arm64) return 0;; esac; return 1; }

offer_text() {
  cat <<EOF
eq-docker: Docker is not installed. The equilibrium harness can run model-written code in Docker containers (no network,
eq-docker: read-only root, dropped capabilities). This script can install it with Homebrew:
EOF
  if [ "$VIA" = cask ]; then
    cat <<EOF
eq-docker:   brew install --cask docker-desktop      (Docker Desktop; names checked with brew info on 2026-10-04)
eq-docker:   - needs administrator rights: the cask links binaries into /usr/local/bin and Docker Desktop's first launch may ask
eq-docker:     for your macOS password (privileged helper). UNVERIFIED here; read the prompts.
eq-docker:   - LICENCE: Docker Desktop is free for personal use, education, non-commercial open source and small businesses
eq-docker:     (under 250 employees AND under US\$10M revenue); larger organisations need a paid subscription
eq-docker:     (https://www.docker.com/pricing/). UNVERIFIED here: read Docker's terms before accepting them at first launch.
eq-docker:   - afterwards you start Docker Desktop yourself once (open -a Docker); nothing is started for you.
eq-docker:   Alternative without Docker Desktop: re-run with --docker-via colima  (brew install colima docker docker-buildx).
EOF
  else
    cat <<EOF
eq-docker:   brew install colima docker docker-buildx   (formulae checked with brew info on 2026-10-04; colima needs lima)
eq-docker:   - afterwards: start the VM yourself, e.g.  colima start --cpu 4 --memory 16 --disk 120   (sizes are a suggestion)
eq-docker:     and add "cliPluginsExtraDirs": ["\$(brew --prefix)/lib/docker/cli-plugins"] to ~/.docker/config.json (docker-buildx's
eq-docker:     caveat); this script never edits ~/.docker/config.json.
EOF
  fi
}

ensure_docker() {
  add_path_for docker || true
  if have docker; then
    if daemon_up || wait_daemon; then
      daemon_arch_ok || skip "docker daemon architecture is not aarch64 (the images are linux/arm64)"
      return 0
    fi
    if app_present; then skip "the Docker daemon is not reachable" "start Docker Desktop (open -a Docker), wait until it says running, then re-run"; fi
    if have colima; then skip "the Docker daemon is not reachable" "start it: colima start   (then re-run)"; fi
    skip "the Docker daemon is not reachable (docker info failed)" "start your Docker engine (Docker Desktop, colima, OrbStack), then re-run"
  fi
  # no docker CLI at all
  if app_present; then skip "Docker Desktop is installed but its docker CLI was not found" "start Docker Desktop once (open -a Docker) so it links its CLI, then re-run"; fi
  add_path_for brew || skip "Docker is not installed and Homebrew is not available" \
    "install Docker (Docker Desktop: https://www.docker.com/products/docker-desktop, or colima) yourself; this script never installs Homebrew"
  if [ "$DRY" = 1 ]; then
    say "would offer to install Docker with Homebrew ($VIA): a prompt on the terminal, or --install-docker; --yes alone is not consent"
    exit 0
  fi
  local consent=0 ans=""
  if [ "$INSTALL_DOCKER" = 1 ]; then consent=1
  elif [ "$NO_PROMPT" = 0 ] && test -t 0; then
    offer_text
    printf 'eq-docker: install Docker now with Homebrew? [y/N] '
    read -r ans || ans=""
    case "$ans" in y|Y|yes|YES|Yes) consent=1;; esac
  fi
  [ "$consent" = 1 ] || skip "Docker is not installed and there was no consent to install it (a yes on the terminal, or --install-docker; --yes is not enough)" \
    "install Docker yourself or re-run with --install-docker"
  [ "$INSTALL_DOCKER" = 0 ] || offer_text
  local pkgs
  if [ "$VIA" = cask ]; then
    brew info --cask docker-desktop >/dev/null 2>&1 || skip "Homebrew does not know the cask docker-desktop (checked 2026-10-04 with brew 7.0.7; names change)" "install Docker Desktop from docker.com"
    say "brew install --cask docker-desktop"
    brew install --cask docker-desktop || skip "brew install --cask docker-desktop failed" "see the Homebrew output above; install Docker yourself and re-run"
  else
    pkgs="colima docker docker-buildx"
    for p in $pkgs; do brew info --formula "$p" >/dev/null 2>&1 || skip "Homebrew does not know the formula $p (checked 2026-10-04 with brew 7.0.7)" "install colima, docker and docker-buildx yourself"; done
    say "brew install $pkgs"
    # shellcheck disable=SC2086
    brew install $pkgs || skip "brew install $pkgs failed" "see the Homebrew output above; install them yourself and re-run"
  fi
  add_path_for docker || true
  if have docker && wait_daemon; then
    daemon_arch_ok || skip "docker daemon architecture is not aarch64 (the images are linux/arm64)"
    return 0
  fi
  if [ "$VIA" = cask ]; then skip "Docker was installed but is not running yet" "start Docker Desktop (open -a Docker), accept its terms, wait until it says running, then re-run ./install.sh --with-eq-docker"
  else skip "Docker was installed but no engine is running yet" "start colima (colima start --cpu 4 --memory 16 --disk 120), add the cliPluginsExtraDirs line, then re-run ./install.sh --with-eq-docker"; fi
}

# ---- build.sh flag assembly ------------------------------------------------------------------------------------------------------
profiles_csv() { printf '%s' "$PROFILES" | tr ' ' ','; }
build_args() { # prints the flags for build.sh (one per line, none contain spaces)
  if [ -n "$PROFILES" ]; then printf '%s\n' --profiles "$(profiles_csv)"; else printf '%s\n' --set "$SET"; fi
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

selected_tags() { # sets LEAN_TAG PY_TAG from image.env + the records
  local sl sp
  sl=$(env_get "$EQ_STATE_DIR/image.env" EQ_SELECT_LEAN); sp=$(env_get "$EQ_STATE_DIR/image.env" EQ_SELECT_PY)
  LEAN_TAG=$(env_get "$EQ_STATE_DIR/images/${sl:-none}.env" EQ_IMAGE_TAG); PY_TAG=$(env_get "$EQ_STATE_DIR/images/${sp:-none}.env" EQ_IMAGE_TAG)
  LEAN_ID=$(env_get "$EQ_STATE_DIR/images/${sl:-none}.env" EQ_IMAGE_ID); PY_ID=$(env_get "$EQ_STATE_DIR/images/${sp:-none}.env" EQ_IMAGE_ID)
}
all_ids() { # comma-joined image IDs that this install verified: of every image of the profiles, else the lean and python image
  local n out=""
  if [ -z "$PROFILES" ]; then printf '%s' "$LEAN_ID,$PY_ID"; return 0; fi
  for n in $(tm_profile_images "$PROFILES"); do out="$out,$(env_get "$EQ_STATE_DIR/images/$n.env" EQ_IMAGE_ID)"; done
  printf '%s' "${out#,}"
}

# ---- commands ----------------------------------------------------------------------------------------------------------------------
cmd_install() {
  ensure_docker
  if [ "$DRY" = 1 ]; then
    say "dry run (state dir $EQ_STATE_DIR; nothing is created):"
    EQ_NO_STATE_WRITE=1 run_build --dry-run || true
    say "would then run: spike.sh --builtin and probe.sh against the built images, and write $STATUS_FILE and image.env"
    exit 0
  fi
  mkdir -p "$EQ_STATE_DIR" && chmod 700 "$EQ_STATE_DIR" 2>/dev/null || true
  mkdir -p "$EQ_STATE_DIR/logs"
  # build.sh's own question would go to the log file, so the question is asked here, and only when a build is due
  if [ "$YES" = 0 ] && [ "$NO_PROMPT" = 0 ] && test -t 0; then
    if EQ_NO_STATE_WRITE=1 run_build --dry-run 2>/dev/null | grep -q ' build '; then
      printf 'eq-docker: build the Docker images now? 10-40 min, several GB of disk, network for the build only [y/N] '
      read -r ans || ans=""
      case "$ans" in y|Y|yes|YES|Yes) YES=1;; *) skip "the image build was declined";; esac
    fi
  fi
  say "building ($SET) ... (a cold build takes 10-40 minutes and several GB of disk; an up-to-date image is skipped)"
  local rc=0
  run_build > "$EQ_STATE_DIR/logs/build.log" 2>&1 || rc=$?
  tail -n 12 "$EQ_STATE_DIR/logs/build.log"
  case "$rc" in
    0) ;;
    2) skip "the build was not started (no terminal to ask on and no --yes, or an options/pins mismatch: see $EQ_STATE_DIR/logs/build.log)" "re-run with --yes";;
    10) skip "docker became unavailable during the build";;
    13) write_status failed "unresolved pin"; warn "a pin in PINS is still a placeholder (see above): a maintainer step, RUNBOOK_MINIMAL.md"; exit 13;;
    *) write_status failed "build failed (rc $rc)"; warn "build failed (rc $rc); log: $EQ_STATE_DIR/logs/build.log"; exit 12;;
  esac
  selected_tags
  if [ -z "$LEAN_TAG" ]; then write_status failed "no lean image recorded after the build"; warn "no lean image recorded"; exit 12; fi
  local ids prev spike=skipped probe=skipped
  ids=$(all_ids)
  prev=$(env_get "$STATUS_FILE" EQ_DOCKER_STATUS_VERIFIED_IDS)
  if [ "$FORCE_VERIFY" = 0 ] && [ "$(env_get "$STATUS_FILE" EQ_DOCKER_STATUS)" = ok ] && [ "$prev" = "$ids" ] \
     && [ "$(env_get "$STATUS_FILE" EQ_DOCKER_STATUS_PINS_SHA256)" = "$(pins_sha)" ]; then
    say "images unchanged and already verified ($ids): spike and probe skipped (--force-verify runs them again)"
    exit 0
  fi
  if [ -n "$PROFILES" ]; then
    say "verifying the tools manifest against the built images (labels, locks, every tool file re-hashed from outside) ..."
    if ! bash "$here/verify-tools.sh" --images --deep --inspect --profiles "$(profiles_csv)" > "$EQ_STATE_DIR/logs/verify-tools.log" 2>&1; then
      tail -n 15 "$EQ_STATE_DIR/logs/verify-tools.log"
      write_status failed "tools verification failed"; warn "tools verification failed; log: $EQ_STATE_DIR/logs/verify-tools.log"; exit 16
    fi
    say "tools: verified"
    local extras="" n
    for n in $(tm_profile_images "$PROFILES"); do [ "$(tm_get image "$n" profile)" = core ] || extras="$extras$n,"; done
    if [ -n "$extras" ]; then
      say "smoke test of the extension images (${extras%,}) ..."
      if ! bash "$here/verify-tools.sh" --smoke --select "${extras%,}" > "$EQ_STATE_DIR/logs/smoke.log" 2>&1; then
        tail -n 15 "$EQ_STATE_DIR/logs/smoke.log"
        write_status failed "smoke test failed"; warn "smoke test failed; log: $EQ_STATE_DIR/logs/smoke.log"; exit 16
      fi
      say "smoke: PASS"
    fi
  fi
  if [ "$NO_SPIKE" = 0 ]; then
    say "spike (does the image work under the hardening flags?) ..."
    if EQ_IMAGE="$LEAN_TAG" EQ_IMAGE_PY="${PY_TAG:-$LEAN_TAG}" bash "$here/spike.sh" --builtin > "$EQ_STATE_DIR/logs/spike.log" 2>&1; then spike=PASS
    else spike=FAIL; tail -n 15 "$EQ_STATE_DIR/logs/spike.log"; write_status failed "spike failed" "EQ_DOCKER_STATUS_SPIKE=FAIL"; warn "spike failed; log: $EQ_STATE_DIR/logs/spike.log"; exit 14; fi
    say "spike: PASS"
  fi
  if [ "$NO_PROBE" = 0 ]; then
    say "probe (network, mounts, secrets, limits) ..."
    if EQ_IMAGE="$LEAN_TAG" EQ_IMAGE_PY="${PY_TAG:-$LEAN_TAG}" bash "$here/probe.sh" > "$EQ_STATE_DIR/logs/probe.log" 2>&1; then probe=PASS
    else probe=FAIL; tail -n 15 "$EQ_STATE_DIR/logs/probe.log"; write_status failed "probe failed" "EQ_DOCKER_STATUS_SPIKE=$spike" "EQ_DOCKER_STATUS_PROBE=FAIL"; warn "probe failed; log: $EQ_STATE_DIR/logs/probe.log"; exit 15; fi
    say "probe: PASS"
  fi
  write_status ok "installed and verified" "EQ_DOCKER_STATUS_VERIFIED_IDS=$ids" "EQ_DOCKER_STATUS_SPIKE=$spike" "EQ_DOCKER_STATUS_PROBE=$probe"
  say "done. image.env: $EQ_STATE_DIR/image.env"
  exit 0
}

cmd_check() {
  add_path_for docker || true
  local sel=(--set "$SET")
  [ -z "$PROFILES" ] || sel=(--profiles "$(profiles_csv)")
  EQ_NO_STATE_WRITE=1 bash "$here/build.sh" "${sel[@]}" --check
  local rc=$?
  return "$rc"
}

cmd_status() {
  if [ ! -f "$STATUS_FILE" ]; then say "not installed (no $STATUS_FILE)"; exit 1; fi
  sed 's/^/eq-docker: /' "$STATUS_FILE"
  [ ! -f "$EQ_STATE_DIR/image.env" ] || sed 's/^/eq-docker: /' "$EQ_STATE_DIR/image.env"
  [ "$(env_get "$STATUS_FILE" EQ_DOCKER_STATUS)" = ok ]
}

cmd_print_env() {
  [ "$(env_get "$STATUS_FILE" EQ_DOCKER_STATUS)" = ok ] || exit 1
  local img; img=$(env_get "$EQ_STATE_DIR/image.env" EQ_IMAGE)
  [ -n "$img" ] || exit 1
  echo "EQ_ISOLATION=docker"
  echo "EQ_IMAGE=$img"
}

cmd_uninstall() {
  add_path_for docker || true
  if [ "$DRY" = 1 ]; then
    EQ_NO_STATE_WRITE=1 bash "$here/build.sh" --set all --uninstall --dry-run --yes
    [ "$PURGE" = 0 ] || say "would remove $EQ_STATE_DIR (--purge)"
    exit 0
  fi
  local args=(--set all --uninstall)
  [ "$YES" = 0 ] || args[${#args[@]}]=--yes
  [ "$PRUNE" = 0 ] || args[${#args[@]}]=--prune-cache
  local rc=0
  bash "$here/build.sh" "${args[@]}" || rc=$?
  if [ "$rc" = 10 ]; then warn "docker is unavailable: the images and records stay; start Docker and run this again"; exit 10; fi
  [ "$rc" = 0 ] || exit "$rc"
  rm -f "$EQ_STATE_DIR/image.env" "$EQ_STATE_DIR/image.json" "$STATUS_FILE"
  if [ "$PURGE" = 1 ]; then
    case "$EQ_STATE_DIR" in
      */eq-docker|*/eq-docker/) rm -rf "$EQ_STATE_DIR"; say "removed $EQ_STATE_DIR";;
      *) warn "--purge only removes a directory named eq-docker; $EQ_STATE_DIR kept";;
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
  *) echo "eq-docker: unknown command: $CMD (install, check, status, print-env, uninstall)" >&2; exit 2;;
esac
