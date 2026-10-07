#!/usr/bin/env bash
# setup.sh: the guided set-up of Apple `container` for the equilibrium isolation images. install.sh --with-eq-container runs it
# as step 10b (from its reviewed snapshot); you can run it yourself from a normal terminal. Bash 3.2 (macOS). Three steps, each
# one only with your consent, each skipped when it is already done:
#   1. the container CLI: Apple's signed installer package (PINS: CONTAINER_PKG_*), fetched over https from GitHub's release
#      hosts only, its size, sha256 and signer checked against the pins, then `sudo installer -pkg <file> -target /`
#      (done: the CLI answers `container --version` with the pinned version or a newer one)
#   2. its service: `container system start --enable-kernel-install` (done: `container system status` answers)
#   3. the images: eq-container.sh install (build.sh unchanged, verify-tools.sh, probe.sh incl. the WALL tunnel probe, the
#      state files; done: every image up to date, then only verification and probe run, and only when something changed)
#
#   setup.sh run [--install-container | --no-install-container] [--start-container-service] [--build-container-images]
#                [--setup-container] [--no-prompt] [--dry-run] -- install [eq-container.sh install options]
#   setup.sh state      what is there, KEY=VALUE lines (no network, no sudo, nothing started or written)
#   setup.sh removal    how to remove the CLI when this script installed it (prints commands; removes nothing)
#
# Consent. On a terminal (stdin, else /dev/tty) the steps still needed are listed first and you type all (every step), step
# (each step shown in full, then a typed yes) or no. --no-prompt never asks. Each flag is consent to its own step only;
# --setup-container to all three; --no-install-container never offers step 1. No consent: the step is skipped and named,
# and nothing is downloaded, run with sudo, started or built for it. Steps 1 and 2 are refused in an agent's shell
# (CLAUDECODE set): run ./install.sh from a normal terminal. Records: $EQ_STATE_DIR/cli.env (the CLI, who installed it),
# setup.env (this run's outcome). The CLI is never removed here: `setup.sh removal` prints Apple's uninstall commands.
# Exit codes (run): the driver's (0 ok, 10 skipped, 12/15/16 failed, 13 an image pin is a placeholder), except: a failed step
# 1 or 2 stops the flow (the driver does not run): 14 the package failed a check (size, sha256, signature; nothing installed)
# | 17 the download or the install failed | 18 the service did not start; a step 1 that could not be offered, when the
# driver then skips for want of the CLI or its service: 13 a CLI pin is a placeholder, 2 a malformed one. 2: usage errors.
set -u

# Absolute paths, never PATH: a sudo, installer, pkgutil or curl planted earlier in PATH never runs, and nothing in the
# environment changes these (tests/test_eq_setup.py rewrites these lines in a copy). This script's own tools come from the
# system directories only; the container CLI is found as eq-container.sh finds it (EQ_CONTAINER_BIN, PATH, the pkg path).
readonly EQS_SUDO=/usr/bin/sudo
readonly EQS_INSTALLER=/usr/sbin/installer
readonly EQS_PKGUTIL=/usr/sbin/pkgutil
readonly EQS_CURL=/usr/bin/curl
readonly EQS_SHASUM=/usr/bin/shasum
readonly EQS_SW_VERS=/usr/bin/sw_vers
readonly EQS_CLI=/usr/local/bin/container
readonly EQS_HOSTS="github.com release-assets.githubusercontent.com objects.githubusercontent.com"
ORIG_PATH=${PATH:-}
PATH=/usr/bin:/bin:/usr/sbin:/sbin
export PATH
here=$(cd "$(dirname "$0")" && pwd -P)

# ---- options ------------------------------------------------------------------------------------------------------------------
CMD=${1:-}; [ $# -eq 0 ] || shift
C_CLI=0; C_SVC=0; C_BUILD=0; NO_CLI=0; NO_PROMPT=0; DRY=0; DRV=()
while [ $# -gt 0 ]; do
  case "$1" in
    --install-container) C_CLI=1;;
    --no-install-container) NO_CLI=1;;
    --start-container-service) C_SVC=1;;
    --build-container-images) C_BUILD=1;;
    --setup-container) C_CLI=1; C_SVC=1; C_BUILD=1;;
    --no-prompt) NO_PROMPT=1;;
    --dry-run) DRY=1;;
    --) shift; DRV=("$@"); break;;
    -h|--help) sed -n '2,26p' "$0"; exit 0;;
    *) echo "setup.sh: unknown option: $1" >&2; exit 2;;
  esac
  shift
done
if [ "$C_CLI$NO_CLI" = 11 ]; then
  echo "setup.sh: --no-install-container contradicts --install-container / --setup-container" >&2; exit 2
fi

if [ -z "${EQ_STATE_DIR:-}" ]; then
  if [ "$(cat "$here/LAYOUT" 2>/dev/null)" = repo ]; then EQ_STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/eq-container"
  else EQ_STATE_DIR="$here/.state"; fi
fi
export EQ_STATE_DIR

note() { printf '  %s\n' "$*"; }
now() { date -u +%FT%TZ; }
env_get() { [ -f "$1" ] || return 0; sed -n "s/^$2=//p" "$1" | head -n 1; }
# STRING SET: 0 when STRING is non-empty and every character is in SET, a literal list (a bracket range would follow the locale)
only() { case "$1" in ""|*[!"$2"]*) return 1;; esac; }
HEX=0123456789abcdef; DIGITS=0123456789; LOWER=abcdefghijklmnopqrstuvwxyz; UPPER=ABCDEFGHIJKLMNOPQRSTUVWXYZ
ver_ok() { only "$1" "$DIGITS." || return 1; case "$1" in .*|*.|*..*) return 1;; esac; }
ver_cmp() { # A B (both ver_ok): -1, 0 or 1
  local a="$1." b="$2." x y
  while [ -n "$a$b" ]; do
    x=${a%%.*}; a=${a#*.}; y=${b%%.*}; b=${b#*.}
    x=$((10#${x:-0})); y=$((10#${y:-0}))
    if [ "$x" -lt "$y" ]; then echo -1; return; fi
    if [ "$x" -gt "$y" ]; then echo 1; return; fi
  done
  echo 0
}
# the version `container --version` names ("container CLI version 1.5.0 (build: release, commit: ...)"); empty when none
cli_version() {
  local v
  v=$("$1" --version 2>/dev/null </dev/null | awk '$1 == "container" && $2 == "CLI" && $3 == "version" { print $4; exit }')
  v=${v%%[!0-9.]*}
  if ver_ok "$v"; then printf '%s\n' "$v"; fi
}
on_orig_path() { # NAME: the first executable NAME in the caller's PATH (absolute entries only)
  local d IFS=:
  set -f
  for d in $ORIG_PATH; do
    case "$d" in /*) ;; *) continue;; esac
    if [ -f "$d/$1" ] && [ -x "$d/$1" ]; then set +f; printf '%s\n' "$d/$1"; return 0; fi
  done
  set +f
  return 1
}

# ---- the pins (lib/eq-container/PINS; read with sed, never sourced) -------------------------------------------------------------
pin() { sed -n "s/^$1=//p" "$here/PINS" 2>/dev/null | head -n 1; }
PV=$(pin CONTAINER_PKG_VERSION); PU=$(pin CONTAINER_PKG_URL); PSIZE=$(pin CONTAINER_PKG_SIZE); PSHA=$(pin CONTAINER_PKG_SHA256)
PSIGNER=$(pin CONTAINER_PKG_SIGNER); PID=$(pin CONTAINER_PKG_ID); PMIN=$(pin CONTAINER_MIN_MACOS)
PKG_NAME=${PU##*/}
PIN_ST=ok; PIN_WHY=""
pins_state() { # PIN_ST ok | placeholder | malformed, PIN_WHY the keys
  local k v
  for k in CONTAINER_PKG_VERSION CONTAINER_PKG_URL CONTAINER_PKG_SIZE CONTAINER_PKG_SHA256 CONTAINER_PKG_SIGNER CONTAINER_PKG_ID \
           CONTAINER_MIN_MACOS; do
    v=$(pin "$k")
    case "$v" in ""|UNSET|*TODO*) PIN_ST=placeholder; PIN_WHY="$PIN_WHY $k";; esac
  done
  [ "$PIN_ST" = ok ] || return 0
  { ver_ok "$PV" && case "$PV" in *.*.*.*) false;; *.*.*) true;; *) false;; esac; } || PIN_WHY="$PIN_WHY CONTAINER_PKG_VERSION"
  case "$PKG_NAME" in "container-installer-signed.pkg"|"container-$PV-installer-signed.pkg") ;; *) PIN_WHY="$PIN_WHY CONTAINER_PKG_URL";; esac
  [ "$PU" = "https://github.com/apple/container/releases/download/$PV/$PKG_NAME" ] || PIN_WHY="$PIN_WHY CONTAINER_PKG_URL"
  { only "$PSIZE" "$DIGITS" && [ "${#PSIZE}" -le 10 ] && [ "$PSIZE" -gt 0 ]; } || PIN_WHY="$PIN_WHY CONTAINER_PKG_SIZE"
  { only "$PSHA" "$HEX" && [ "${#PSHA}" = 64 ]; } || PIN_WHY="$PIN_WHY CONTAINER_PKG_SHA256"
  { only "$PSIGNER" "$UPPER$LOWER$DIGITS .,:()_-" && [ "${#PSIGNER}" -le 200 ]; } || PIN_WHY="$PIN_WHY CONTAINER_PKG_SIGNER"
  only "$PID" "$LOWER$UPPER$DIGITS.-" || PIN_WHY="$PIN_WHY CONTAINER_PKG_ID"
  { only "$PMIN" "$DIGITS" && [ "${#PMIN}" -le 3 ]; } || PIN_WHY="$PIN_WHY CONTAINER_MIN_MACOS"
  [ -z "$PIN_WHY" ] || PIN_ST=malformed
}
pin_commands() { # how to derive the pins yourself (no sudo, nothing installed)
  local url=$PU name=$PKG_NAME
  case "$PIN_WHY" in *CONTAINER_PKG_URL*) url="<the signed .pkg URL on https://github.com/apple/container/releases>"; name=container.pkg;; esac
  note "  derive the values from a normal terminal (downloads the package, installs nothing, no sudo):"
  note "    d=\$(mktemp -d) && curl -q -fL --proto =https -o \"\$d/$name\" '$url' && wc -c < \"\$d/$name\" \\"
  note "      && shasum -a 256 \"\$d/$name\" && /usr/sbin/pkgutil --check-signature \"\$d/$name\"; rm -rf \"\$d\""
  note "  then put into lib/eq-container/PINS: CONTAINER_PKG_SIZE (the wc number), CONTAINER_PKG_SHA256 (it must equal the hash"
  note "  GitHub lists for the asset), CONTAINER_PKG_SIGNER (the text after \"1. \" under Certificate Chain), and commit"
}

# ---- what is there --------------------------------------------------------------------------------------------------------------
CLI=""; CLI_V=""; CLI_ST=missing; CLI_AT_PKG=0; SVC=none; PLAT_WHY=""; MACOS=""
cli_state() { # CLI CLI_V CLI_ST missing|old|ok|newer|unknown|present CLI_AT_PKG
  CLI=${EQ_CONTAINER_BIN:-}
  if [ -z "$CLI" ]; then CLI=$(on_orig_path container) || CLI=$EQS_CLI; fi
  CLI_AT_PKG=0; [ "$CLI" != "$EQS_CLI" ] || CLI_AT_PKG=1
  CLI_V=""; CLI_ST=missing
  if [ -f "$CLI" ] && [ -x "$CLI" ]; then
    CLI_V=$(cli_version "$CLI")
    if [ -z "$CLI_V" ]; then CLI_ST=unknown
    elif ! ver_ok "$PV"; then CLI_ST=present
    else case $(ver_cmp "$CLI_V" "$PV") in -1) CLI_ST=old;; 0) CLI_ST=ok;; *) CLI_ST=newer;; esac; fi
  fi
}
cli_usable() { [ "$CLI_ST" != missing ]; }
svc_state() { SVC=none; cli_usable || return 0; if "$CLI" system status >/dev/null 2>&1 </dev/null; then SVC=running; else SVC=stopped; fi; }
platform() { # PLAT_WHY empty when this Mac can run Apple container (Apple silicon, macOS >= CONTAINER_MIN_MACOS)
  local arch
  PLAT_WHY=""
  arch=${EQ_HOST_ARCH:-$(uname -m)}
  MACOS=$("$EQS_SW_VERS" -productVersion 2>/dev/null </dev/null | head -n 1)
  case "$arch" in arm64|aarch64) ;; *) PLAT_WHY="this Mac is not Apple silicon ($arch)"; return 0;; esac
  if ! ver_ok "$MACOS"; then PLAT_WHY="the macOS version could not be read ($EQS_SW_VERS -productVersion)"
  elif ! ver_ok "$PMIN"; then PLAT_WHY="CONTAINER_MIN_MACOS is not a number in lib/eq-container/PINS"
  elif [ "$(ver_cmp "${MACOS%%.*}" "$PMIN")" = -1 ]; then PLAT_WHY="macOS $MACOS is older than $PMIN, which Apple container needs"; fi
}

# ---- consent ----------------------------------------------------------------------------------------------------------------------
TTY_IN=""
tty_in() { # stdin when it is a terminal, else the controlling terminal; never with --no-prompt or --dry-run
  TTY_IN=""
  [ "$NO_PROMPT$DRY" = 00 ] || return 0
  if test -t 0; then TTY_IN=stdin
  elif { : </dev/tty; } 2>/dev/null && { : >/dev/tty; } 2>/dev/null; then TTY_IN=/dev/tty; fi
}
ANS=""
ask() { # PROMPT: ANS = the line typed (empty without a terminal or at end of input)
  ANS=""
  case "$TTY_IN" in
    stdin) printf '%s' "$1"; IFS= read -r ANS || ANS="";;
    /dev/tty) printf '%s' "$1" >/dev/tty; IFS= read -r ANS </dev/tty || ANS="";;
  esac
  return 0
}
typed_yes() { case "$ANS" in yes|YES|Yes) return 0;; esac; return 1; }
MODE=none   # all | step | none: the answer to the plan (flags are consent on their own)
consent() { # FLAG(0/1) STEP-TEXT-FUNCTION QUESTION: 0 when the step may run; its full text is printed first in any case
  "$2"
  if [ "$1" = 1 ]; then note "  consent: given by flag"; return 0; fi
  case "$MODE" in
    all) note "  consent: you answered all"; return 0;;
    step) ask "  $3 Type yes to run this step (anything else skips it): "; typed_yes && return 0;;
  esac
  return 1
}

# ---- step texts: exactly what each step does -----------------------------------------------------------------------------------
size_mb() { echo $(( (PSIZE + 524288) / 1048576 )); }
show_cli() {
  note "Step: install Apple container $PV (system software for every user of this Mac; needs your administrator password)"
  note "  from     $PU ($(size_mb) MB)"
  note "  checks   GitHub's release hosts only (https), then size $PSIZE, sha256 $PSHA and the signer"
  note "           \"$PSIGNER\" (/usr/sbin/pkgutil --check-signature); any difference: nothing is installed"
  if [ "$CLI_ST" = old ] && [ "$SVC" = running ]; then
    note "  first    $CLI system stop (Apple's rule for an upgrade: the running $CLI_V service stops; if the install then"
    note "           fails, it is started again with --disable-kernel-install)"
  fi
  note "  runs     /usr/bin/sudo /usr/sbin/installer -pkg <the checked file> -target /   (sudo asks for your password itself)"
  note "  writes   /usr/local/bin/{container,container-apiserver,update-container.sh,uninstall-container.sh} and"
  note "           /usr/local/libexec/container/ (package receipt $PID)"
  note "  remove   container system stop; /usr/local/bin/uninstall-container.sh -k   (-d also deletes your container data)"
}
show_svc() {
  note "Step: start the container service"
  note "  runs     $CLI system start --enable-kernel-install"
  note "           it registers the container services with launchd for your user (background processes) and, on the"
  note "           first start, downloads and installs Apple's recommended Linux kernel for the containers"
  note "  stop     container system stop"
}
SEL=""
show_build() {
  note "Step: build the isolation images ($SEL) with Apple container: 10-40 min cold, several GB of disk, network for the build only"
  note "  runs     bash lib/eq-container/eq-container.sh ${DRV[*]} --yes (build.sh, then the tools check and the isolation"
  note "           probe incl. the WALL tunnel probe); an image already up to date is not rebuilt"
  note "  remove   bash lib/eq-container/eq-container.sh uninstall --yes [--purge]"
}

# ---- step 1: the CLI ------------------------------------------------------------------------------------------------------------
TMPD=""; STOPPED=0   # STOPPED 1: this run stopped the old CLI's running service for an upgrade that has not run yet
cleanup() { [ -z "$TMPD" ] || rm -rf "$TMPD"; TMPD=""; }
on_signal() { cleanup; [ "$STOPPED" = 0 ] || note "! the container service this run stopped for the upgrade is still stopped: container system start"; exit "$1"; }
trap cleanup EXIT
trap 'on_signal 130' INT
trap 'on_signal 143' TERM
url_host() { # URL: its host when URL is https://HOST/... with a plain lower-case host (no user, no port)
  local r=${1#https://}
  [ "$r" != "$1" ] || return 1
  r=${r%%/*}
  only "$r" "$LOWER$DIGITS.-" || return 1
  printf '%s\n' "$r"
}
fetch() { # URL OUT: no automatic redirects; every hop (at most 5) https and on EQS_HOSTS; at most the pinned size
  local url=$1 out=$2 hop=0 res code host rc
  while :; do
    host=$(url_host "$url") || { note "! refused: $url is not https://<plain host>/..."; return 1; }
    case " $EQS_HOSTS " in *" $host "*) ;; *) note "! refused: $host is not one of GitHub's release hosts ($EQS_HOSTS)"; return 1;; esac
    rc=0
    res=$("$EQS_CURL" -q --proto =https --proto-redir =https --tlsv1.2 --fail --silent --show-error --max-redirs 0 \
          --connect-timeout 30 --max-time 1800 --max-filesize "$PSIZE" -o "$out" -w '%{http_code} %{redirect_url}' "$url" \
          </dev/null) || rc=$?
    [ "$rc" = 0 ] || { note "! curl failed on $host (exit $rc)"; return 1; }
    code=${res%% *}; url=${res#"$code"}; url=${url# }
    case "$code" in
      200) return 0;;
      301|302|303|307|308)
        hop=$((hop + 1))
        if [ "$hop" -gt 5 ] || [ -z "$url" ]; then note "! refused: more than 5 redirects, or one without a target"; return 1; fi;;
      *) note "! HTTP ${code:-?} from $host"; return 1;;
    esac
  done
}
verify_pkg() { # FILE: size, sha256 and signer equal the pins (else 14)
  local f=$1 sz got sig rc=0 st leaf
  sz=$(wc -c <"$f" 2>/dev/null | tr -d ' ')
  [ "$sz" = "$PSIZE" ] || { note "! REFUSED: the package is $sz bytes, the pin says $PSIZE: nothing installed"; return 14; }
  got=$("$EQS_SHASUM" -a 256 "$f" 2>/dev/null | awk '{ print $1 }')
  [ "$got" = "$PSHA" ] || { note "! REFUSED: sha256 $got differs from the pin $PSHA: nothing installed"; return 14; }
  note "2. size $sz and sha256 $got: equal to the pins"
  sig=$("$EQS_PKGUTIL" --check-signature "$f" 2>&1 </dev/null) || rc=$?
  st=$(printf '%s\n' "$sig" | sed -n 's/^[[:space:]]*Status:[[:space:]]*//p' | head -n 1)
  leaf=$(printf '%s\n' "$sig" | sed -n 's/^[[:space:]]*1\.[[:space:]]*//p' | head -n 1)
  case "$st" in *untrusted*|*revoked*|*expired*|*invalid*|*"no signature"*) rc=1;; "signed "*) ;; *) rc=1;; esac
  if [ "$rc" != 0 ] || [ "$leaf" != "$PSIGNER" ]; then
    note "! REFUSED: pkgutil --check-signature: status \"${st:-none}\", signer \"${leaf:-none}\" (pin \"$PSIGNER\"): nothing installed"
    return 14
  fi
  note "3. signature: $st, signer \"$leaf\""
}
INSTALLED=0; CLI_V_BEFORE=""
install_cli() {
  local f v rv
  TMPD=$(umask 077 && mktemp -d "$EQ_STATE_DIR/pkg.XXXXXX") || { TMPD=""; note "! could not make a private temp dir in $EQ_STATE_DIR"; return 17; }
  f="$TMPD/$PKG_NAME"
  note "1. download $PU"
  ( umask 077 && fetch "$PU" "$f" ) || { cleanup; note "! download failed: nothing installed; retry: ./install.sh --with-eq-container --install-container"; return 17; }
  verify_pkg "$f" || { v=$?; cleanup; pin_check_hint; return "$v"; }
  if [ "$CLI_ST" = old ] && [ "$SVC" = running ]; then
    "$CLI" system stop </dev/null || { cleanup; note "! $CLI system stop failed: nothing installed; stop it yourself, then retry"; return 17; }
    SVC=stopped; STOPPED=1
  fi
  note "4. /usr/bin/sudo /usr/sbin/installer -pkg $f -target /"
  if ! "$EQS_SUDO" "$EQS_INSTALLER" -pkg "$f" -target /; then
    cleanup
    note "! sudo installer failed; retry: ./install.sh --with-eq-container --install-container (or install the signed package yourself)"
    restart_old_svc
    return 17
  fi
  cleanup
  STOPPED=0   # installed: the old service is not started again (the new CLI's service is step 2, with its own consent)
  CLI_V_BEFORE=$CLI_V; INSTALLED=1
  cli_state
  v=$(cli_version "$EQS_CLI")
  rv=$("$EQS_PKGUTIL" --pkg-info "$PID" 2>/dev/null </dev/null | sed -n 's/^version: //p' | head -n 1)
  if [ "$v" != "$PV" ] || [ "$rv" != "$PV" ]; then
    note "! after the install $EQS_CLI --version says ${v:-nothing} and the receipt $PID ${rv:-nothing}, not $PV"
    return 17
  fi
  note "5. $EQS_CLI --version: $v; receipt $PID: $rv"
  return 0
}
# the upgrade failed before the install ran: the service this run stopped runs again (its kernel is there already, so
# --disable-kernel-install downloads nothing); a failed start is named, never retried
restart_old_svc() {
  [ "$STOPPED" = 1 ] || return 0
  STOPPED=0
  if "$CLI" system start --disable-kernel-install </dev/null >/dev/null 2>&1 && "$CLI" system status >/dev/null 2>&1 </dev/null; then
    SVC=running; note "  the container $CLI_V service this run stopped for the upgrade is running again"
  else
    note "! the container service this run stopped for the upgrade is still stopped: container system start"
  fi
}
pin_check_hint() {
  note "  check it yourself (no sudo): shasum -a 256 <the .pkg>; /usr/sbin/pkgutil --check-signature <the .pkg>; if Apple"
  note "  published a new package under the same name, the pins need the values of the new one (lib/eq-container/PINS)"
}

# ---- step 2: the service --------------------------------------------------------------------------------------------------------
start_svc() {
  note "1. $CLI system start --enable-kernel-install"
  if ! "$CLI" system start --enable-kernel-install; then
    note "! container system start failed; retry from a normal terminal: container system start"; return 18
  fi
  if ! "$CLI" system status >/dev/null 2>&1 </dev/null; then
    note "! container system status still fails after the start; retry: container system start"; return 18
  fi
  note "2. container system status: running"
  SVC=running
}

# ---- records ----------------------------------------------------------------------------------------------------------------------
state_dir() { # a real directory of yours, 0700 (install.sh made it already; standalone runs make it)
  if [ -L "$EQ_STATE_DIR" ] || { [ -e "$EQ_STATE_DIR" ] && [ ! -d "$EQ_STATE_DIR" ]; }; then
    note "! $EQ_STATE_DIR is a symlink or not a directory: refused"; return 1
  fi
  if [ ! -d "$EQ_STATE_DIR" ]; then mkdir -p "$(dirname "$EQ_STATE_DIR")" && mkdir -m 700 "$EQ_STATE_DIR" || return 1; fi
  [ -O "$EQ_STATE_DIR" ] || { note "! $EQ_STATE_DIR is not yours: refused"; return 1; }
  chmod 700 "$EQ_STATE_DIR"
}
write_kv() { # FILE CONTENT: atomic, 0600
  ( umask 077 && printf '%s\n' "$2" >"$1.tmp.$$" && mv -f "$1.tmp.$$" "$1" ) 2>/dev/null || note "! could not write $1"
}
cli_record() { # cli.env: the CLI found or installed and who installed it (rewritten only when a field changes)
  local f="$EQ_STATE_DIR/cli.env" by prev sha new old
  by=$(env_get "$f" EQ_CLI_INSTALLED_BY); prev=$(env_get "$f" EQ_CLI_PREVIOUS); sha=$(env_get "$f" EQ_CLI_PKG_SHA256)
  if [ "$INSTALLED" = 1 ]; then by=stack; prev=${CLI_V_BEFORE:-none}; sha=$PSHA
  elif [ -z "$by" ]; then cli_usable || return 0; by=preexisting; prev=""; sha=""; fi
  case "$CLI" in *[![:print:]]*) note "! cli.env not written: the CLI path holds a control character"; return 0;; esac
  new=$(printf 'EQ_CLI_PATH=%s\nEQ_CLI_VERSION=%s\nEQ_CLI_PIN=%s\nEQ_CLI_INSTALLED_BY=%s\nEQ_CLI_PREVIOUS=%s\nEQ_CLI_PKG_SHA256=%s\nEQ_CLI_PKG_ID=%s' \
        "$CLI" "$CLI_V" "$PV" "$by" "$prev" "$sha" "$PID")
  old=$(grep -v '^EQ_CLI_AT=' "$f" 2>/dev/null)
  [ "$new" != "$old" ] || return 0
  write_kv "$f" "$new
EQ_CLI_AT=$(now)"
}

# ---- commands ---------------------------------------------------------------------------------------------------------------------
cmd_state() {
  pins_state; cli_state; svc_state; platform
  printf 'EQ_CLI_PATH=%s\nEQ_CLI_VERSION=%s\nEQ_CLI_STATE=%s\nEQ_CLI_PIN=%s\nEQ_CLI_PINS=%s\nEQ_SERVICE=%s\nEQ_PLATFORM=%s\n' \
    "$CLI" "$CLI_V" "$CLI_ST" "$PV" "$PIN_ST" "$SVC" "${PLAT_WHY:-ok}"
}
cmd_removal() {
  local f="$EQ_STATE_DIR/cli.env" by v prev
  by=$(env_get "$f" EQ_CLI_INSTALLED_BY); v=$(env_get "$f" EQ_CLI_VERSION); prev=$(env_get "$f" EQ_CLI_PREVIOUS)
  case "$by" in
    stack)
      note "Apple container ${v:-?} was installed by ./install.sh (system-wide; it stays). To remove it, from a normal terminal:"
      note "  container system stop; /usr/local/bin/uninstall-container.sh -k   (-k keeps your container data, -d deletes it)"
      case "$prev" in ""|none) ;; *) note "  (it replaced your container $prev; reinstall that from https://github.com/apple/container/releases if you want it back)";; esac ;;
    preexisting) note "Apple container was installed before the stack: left alone." ;;
  esac
  return 0
}
SETUP_STEP=build; SETUP_WHY=""
finish() { # RC: setup.env, then exit RC
  SETUP_WHY=$(printf '%s' "$SETUP_WHY" | tr -c '[:print:]' ' ')
  if [ "$DRY" = 0 ] && [ -d "$EQ_STATE_DIR" ]; then
    write_kv "$EQ_STATE_DIR/setup.env" "EQ_SETUP_RC=$1
EQ_SETUP_STEP=$SETUP_STEP
EQ_SETUP_WHY=$SETUP_WHY
EQ_SETUP_AT=$(now)"
  fi
  exit "$1"
}
stop_at() { # STEP RC WHY: the first stop of steps 1-2 is the one reported when the driver then skips
  if [ "$SETUP_STEP" = build ]; then SETUP_STEP=$1; STOP_RC=$2; SETUP_WHY=$3; fi
}
STOP_RC=0
cmd_run() {
  local a f prev="" need_cli=0 need_svc=0 can_build=0 block="" block_rc=0 due=unknown n=0 rc=0 bflag
  [ "${DRV[0]:-}" = install ] || { echo "setup.sh: run needs -- install [eq-container.sh install options]" >&2; exit 2; }
  SEL=""
  for a in "${DRV[@]}"; do
    case "$prev" in --set) SEL="set $a";; --profiles) SEL="profiles $a";; esac
    case "$a" in --profiles=*) SEL="profiles ${a#--profiles=}";; esac
    prev=$a
  done
  [ -n "$SEL" ] || SEL="profiles core"
  [ "$DRY" = 1 ] || state_dir || exit 10   # a refused state dir gets no record (finish would write through the link)
  # a deferred profile (TOOLS.toml `deferred`: rust, haskell have no image) makes the driver skip the whole install (exit
  # 10), whatever steps 1-2 do: stop before anything is offered, downloaded, run with sudo or started
  case "$SEL" in "profiles "*)
    rc=0; f=$( . "$here/tools.sh" && tm_load "$here/TOOLS.toml" >/dev/null 2>&1 \
      && tm_refuse_deferred "$(printf '%s' "${SEL#profiles }" | tr ',' ' ')" 2>&1 >/dev/null ) || rc=$?
    if [ "$rc" = 10 ]; then
      f=$(printf '%s' "$f" | tr '\n' ' ' | sed 's/ *$//')
      note "! $f"
      stop_at profiles 10 "$f"; finish 10
    fi ;;
  esac
  pins_state; cli_state; svc_state; tty_in

  # what is there
  case "$CLI_ST" in
    ok) note "ok  container CLI $CLI_V at $CLI (pinned $PV)";;
    newer) note "ok  container CLI $CLI_V at $CLI (newer than the pinned $PV: left alone)";;
    present) note "ok  container CLI $CLI_V at $CLI (the version pin is not set: not compared)";;
    unknown) note "! the container CLI at $CLI names no version (container --version): used as found";;
    old) note "! container CLI $CLI_V at $CLI is older than the pinned $PV";;
    missing) note "container CLI: not installed ($CLI)";;
  esac
  case "$SVC" in running) note "ok  container service running";; stopped) note "container service: not running";; esac

  # step 1 needed? (missing, or older than the pin, where Apple's package installs it)
  case "$CLI_ST" in missing|old) [ "$CLI_AT_PKG" = 0 ] || need_cli=1;; esac
  if [ "$CLI_ST" = old ] && [ "$CLI_AT_PKG" = 0 ]; then note "  it is not where Apple's package installs it ($EQS_CLI): update it yourself"; fi
  if [ "$CLI_ST" = missing ] && [ "$CLI_AT_PKG" = 0 ]; then note "  EQ_CONTAINER_BIN names $CLI, which does not exist: nothing is installed over it"; fi
  if [ "$need_cli" = 1 ] && [ "$NO_CLI" = 1 ]; then
    need_cli=0; note "  --no-install-container: Apple container is not offered"; stop_at cli 10 "--no-install-container"
  fi
  if [ "$need_cli" = 1 ]; then
    [ "$PIN_ST" != ok ] || platform
    if [ "$PIN_ST" = placeholder ]; then block="placeholder pin(s) in lib/eq-container/PINS:$PIN_WHY (fail closed: nothing is downloaded)"; block_rc=13
    elif [ "$PIN_ST" = malformed ]; then block="malformed pin(s) in lib/eq-container/PINS:$PIN_WHY (fail closed: nothing is downloaded)"; block_rc=2
    elif [ -n "$PLAT_WHY" ]; then block="$PLAT_WHY"; block_rc=10
    elif [ -n "${CLAUDECODE:-}" ]; then block="this is an agent's shell (CLAUDECODE is set): run ./install.sh --with-eq-container from a normal terminal"; block_rc=10; fi
    if [ -n "$block" ]; then
      note "! Apple container $PV cannot be installed here: $block"
      case "$block_rc" in 13|2) pin_commands;; *) note "  or install the signed package yourself: https://github.com/apple/container/releases";; esac
      stop_at cli "$block_rc" "$block"; need_cli=0
    fi
  fi
  # step 2 needed? (the service is down, or step 1 installs a CLI whose service is not running yet)
  if [ "$SVC" = stopped ] || [ "$need_cli" = 1 ]; then
    need_svc=1
    if [ -n "${CLAUDECODE:-}" ]; then
      note "! the container service is not started from an agent's shell (CLAUDECODE is set): run ./install.sh from a normal terminal"
      stop_at service 10 "agent shell"; need_svc=0
    fi
  fi
  # step 3 possible? (a CLI and a running service, now or after steps 1-2)
  if { cli_usable || [ "$need_cli" = 1 ]; } && { [ "$SVC" = running ] || [ "$need_svc" = 1 ]; }; then can_build=1; fi

  # the plan and its one question: on a terminal, when a needed step has no flag. Images already up to date: no question.
  if [ -n "$TTY_IN" ] && [ "$C_BUILD" = 0 ] && [ "$need_cli$need_svc" = 00 ] && [ "$SVC" = running ]; then
    rc=0; EQ_CONTAINER_BIN=$CLI PATH=$ORIG_PATH "$BASH" "$here/eq-container.sh" build-due "${DRV[@]:1}" </dev/null >/dev/null 2>&1 || rc=$?
    case "$rc" in 0) due=yes;; 1) due=no;; esac
  fi
  if [ -n "$TTY_IN" ] && { { [ "$need_cli" = 1 ] && [ "$C_CLI" = 0 ]; } || { [ "$need_svc" = 1 ] && [ "$C_SVC" = 0 ]; } \
       || { [ "$can_build" = 1 ] && [ "$C_BUILD" = 0 ] && [ "$due" != no ]; }; }; then
    note ""
    note "Equilibrium's container environment: these steps are needed (nothing has run yet):"
    if [ "$need_cli" = 1 ]; then
      n=$((n + 1)); f=$(flagged "$C_CLI")
      note "  $n. install Apple container $PV from GitHub (system software; sudo asks for your administrator password)$f"
    fi
    if [ "$need_svc" = 1 ]; then
      n=$((n + 1)); f=$(flagged "$C_SVC")
      note "  $n. start the container service (container system start: launchd services, a Linux kernel on the first start)$f"
    fi
    if [ "$can_build" = 1 ]; then
      n=$((n + 1)); f=$(flagged "$C_BUILD")
      note "  $n. build the isolation images ($SEL) if missing or stale: 10-40 min cold, several GB of disk$f"
    fi
    note "  then, with no question: verify the tools, run the isolation probe (incl. the WALL tunnel probe), write EQ_ISOLATION"
    note "  and EQ_IMAGE into stack.env; the WALL step (10c) follows. Each step is shown in full before it runs."
    ask "  Type all (run every step), step (ask before each one) or no (skip them; the rest of the install goes on) [all/step/no]: "
    case "$ANS" in all|ALL|All) MODE=all;; step|STEP|Step) MODE=step;; *) MODE=none; note "= no: the container steps are skipped";; esac
  fi

  bflag=--no-build; [ "$C_BUILD" = 0 ] || bflag=--yes
  # dry run: what would happen; the driver's own dry run when the CLI and its service are there now
  if [ "$DRY" = 1 ]; then
    rc=0
    if [ "$need_cli" = 1 ]; then
      show_cli | sed 's/^  /  would: /'
      if [ "$C_CLI" = 1 ]; then note "  (consent: --install-container)"
      else rc=10; note "  (needs consent: a terminal answer, --install-container or --setup-container; without it the step is skipped)"; fi
    fi
    if [ "$need_svc" = 1 ]; then
      show_svc | sed 's/^  /  would: /'
      if [ "$C_SVC" = 1 ]; then note "  (consent: --start-container-service)"
      else rc=10; note "  (needs consent: a terminal answer, --start-container-service or --setup-container; without it the step is skipped)"; fi
    fi
    if [ "$C_BUILD" = 1 ]; then note "would: bash lib/eq-container/eq-container.sh ${DRV[*]} --yes --no-prompt   (image build consented)"
    else note "would: bash lib/eq-container/eq-container.sh ${DRV[*]} --no-build --no-prompt   (no consent to build: a missing or stale image is a skip; consent: --build-container-images, --setup-container or a terminal answer)"; fi
    if cli_usable && [ "$SVC" = running ]; then
      rc=0; EQ_CONTAINER_BIN=$CLI PATH=$ORIG_PATH "$BASH" "$here/eq-container.sh" "${DRV[@]}" "$bflag" --no-prompt --dry-run </dev/null || rc=$?
      exit "$rc"
    fi
    # 0: the steps before the build have their consent; 10: one would be skipped; a blocked step 1 its own code
    [ "$STOP_RC" = 0 ] || rc=$STOP_RC
    note "the image build and its checks would follow once the CLI and its service are up"
    exit "$rc"
  fi

  # step 1
  if [ "$need_cli" = 1 ]; then
    note ""
    if consent "$C_CLI" show_cli "Install Apple container $PV now?"; then
      rc=0; install_cli || rc=$?
      # a failed step stops the flow: nothing is started or built with a CLI this run could not verify
      if [ "$rc" != 0 ]; then stop_at cli "$rc" "the container CLI install stopped (exit $rc)"; cli_record; finish "$rc"; fi
    else
      note "! not installed: Apple container $PV (no consent). Consent: --install-container (this step) or --setup-container (all"
      note "  three), or run ./install.sh --with-eq-container on a terminal and answer; or install the signed package yourself"
      stop_at cli 10 "no consent to install the container CLI"
    fi
  fi
  # step 2, with what step 1 left
  if [ "$need_svc" = 1 ] && cli_usable; then
    svc_state
    if [ "$SVC" = stopped ]; then
      note ""
      if consent "$C_SVC" show_svc "Start the container service now?"; then
        rc=0; start_svc || rc=$?
        if [ "$rc" != 0 ]; then stop_at service "$rc" "container system start failed"; cli_record; finish "$rc"; fi
      else
        note "! not started: the container service (no consent). Start it yourself (container system start) or add"
        note "  --start-container-service (this step) or --setup-container (all three)"
        stop_at service 10 "no consent to start the container services"
      fi
    fi
  fi
  cli_record

  # step 3: the driver builds only with consent (--yes); without it a due build is a skip (--no-build)
  if cli_usable && [ "$SVC" = running ]; then
    if [ "$C_BUILD" = 1 ] || [ "$MODE" = all ]; then
      note ""; show_build; note "  consent: $([ "$C_BUILD" = 1 ] && echo 'given by flag' || echo 'you answered all')"; bflag=--yes
    elif [ "$MODE" = step ]; then
      if [ "$due" = unknown ]; then
        rc=0; EQ_CONTAINER_BIN=$CLI PATH=$ORIG_PATH "$BASH" "$here/eq-container.sh" build-due "${DRV[@]:1}" </dev/null >/dev/null 2>&1 || rc=$?
        [ "$rc" != 1 ] || due=no
      fi
      if [ "$due" != no ]; then
        note ""
        if consent 0 show_build "Build the images now?"; then bflag=--yes; else note "= the image build is skipped (your answer)"; fi
      fi
    fi
  fi
  rc=0
  EQ_CONTAINER_BIN=$CLI PATH=$ORIG_PATH "$BASH" "$here/eq-container.sh" "${DRV[@]}" "$bflag" --no-prompt </dev/null || rc=$?
  # a stop of step 1 or 2 is the outcome only when the driver skipped for want of the CLI or its running service
  if [ "$rc" = 10 ] && [ "$STOP_RC" != 0 ] && ! { cli_usable && [ "$SVC" = running ]; }; then rc=$STOP_RC
  else SETUP_STEP=build; SETUP_WHY=""; [ "$rc" = 0 ] || SETUP_WHY="eq-container exit $rc"; fi
  finish "$rc"
}
flagged() { [ "$1" = 0 ] || printf '  [consent: flag]'; }

case "$CMD" in
  run) cmd_run;;
  state) cmd_state;;
  removal) cmd_removal;;
  ""|-h|--help|help) sed -n '2,26p' "$0"; exit 0;;
  *) echo "setup.sh: unknown command: $CMD (run, state, removal)" >&2; exit 2;;
esac
