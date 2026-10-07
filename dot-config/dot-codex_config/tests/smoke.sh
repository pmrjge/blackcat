#!/usr/bin/env bash
# codex_config/tests/smoke.sh: the Codex installer end to end, on a scratch HOME and CODEX_HOME.
#
#   codex_config/tests/smoke.sh        (from a clean, committed checkout: the installer snapshots HEAD)
#
# Runs: --dry-run (writes nothing), --diff, apply with --yes, a second run (nothing to change), --diff and
# --dry-run after it (no differences), --doctor (exit 1: the hooks are untrusted), --ide-default without an
# answer (refused), --ide-default --yes, --no-ide-default --yes, --restore latest --yes. Only the fake
# codex (tests/fake-codex) is ever on PATH ahead of anything else; no real codex runs. The real ~/.codex,
# ~/.agents and the Codex state folders are fingerprinted before and after (listing and sha256, read-only;
# auth.json by size only); the smoke fails if any changed. SMOKE_KEEP=1 keeps the scratch folder.
set -euo pipefail
umask 077

HERE=$(cd "$(dirname "$0")" && pwd -P)
REPO=$(cd "$HERE/../.." && pwd -P)
INSTALL="$REPO/codex_config/install.sh"
REAL_HOME=${HOME:?HOME is not set}
REAL_CODEX_HOME=${CODEX_HOME:-$REAL_HOME/.codex}
REAL_STATE=${XDG_STATE_HOME:-$REAL_HOME/.local/state}

FAILS=0
ok() { printf 'ok    %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; FAILS=$((FAILS + 1)); }
check() { local what=$1; shift; if "$@"; then ok "$what"; else bad "$what"; fi; }

# fingerprint PATH: one sha256 over the sorted listing (type, path, sha256 | link target); "absent" when
# there is nothing. auth.json counts by size: its bytes are a credential this smoke has no reason to read.
# A second argument "nopyc" leaves __pycache__ out: Python 3.9 orders the constant frozensets of a module
# by its per-process hash seed, so a recompiled guard.pyc differs byte for byte between two runs.
fingerprint() {
  if [ ! -e "$1" ] && [ ! -L "$1" ]; then echo absent; return 0; fi
  find "$1" -print0 | LC_ALL=C sort -z | while IFS= read -r -d '' p; do
    case "$p" in */__pycache__|*/__pycache__/*) [ "${2:-}" != nopyc ] || continue ;; esac
    if [ -L "$p" ]; then printf 'L %s -> %s\n' "$p" "$(readlink "$p")"
    elif [ -f "$p" ]; then
      case "$p" in
        */auth.json) printf 'F %s size %s\n' "$p" "$(wc -c <"$p" | tr -d ' ')" ;;
        *) printf 'F %s %s\n' "$p" "$(shasum -a 256 <"$p" | cut -d' ' -f1)" ;;
      esac
    else printf 'D %s\n' "$p"; fi
  done | shasum -a 256 | cut -d' ' -f1
}
real_prints() {
  fingerprint "$REAL_CODEX_HOME"
  fingerprint "$REAL_HOME/.agents"
  fingerprint "$REAL_STATE/codex-agent-stack"
  fingerprint "$REAL_STATE/codex-agent-stack-backups"
}
REAL_BEFORE=$(real_prints)

# The installer's Python, resolved with the REAL HOME: under the scratch HOME uv sees no managed
# interpreters (they live under the real ~/.local/share/uv), so it is handed over as STACK_PYTHON.
SMOKE_PY=${STACK_PYTHON:-$(uv python find 3.13 2>/dev/null || true)}
[ -n "$SMOKE_PY" ] && [ -x "$SMOKE_PY" ] || { echo "smoke: no Python 3.13 (uv python install 3.13, or set STACK_PYTHON)" >&2; exit 1; }

# ---- scratch environment ----------------------------------------------------------------------------
SCR=$(mktemp -d "${TMPDIR:-/tmp}/codex-smoke.XXXXXX")
cleanup() { if [ "${SMOKE_KEEP:-0}" = 1 ]; then echo "scratch kept: $SCR"; else rm -rf -- "$SCR"; fi; }
trap cleanup EXIT
SHOME="$SCR/home"
CH="$SHOME/.codex"
mkdir -p "$CH" "$SHOME/.agents/skills" "$SHOME/.local/state" "$SCR/tmp"
chmod 700 "$CH"
[ "$SHOME" != "$REAL_HOME" ] && [ "$CH" != "$REAL_CODEX_HOME" ] || { echo "smoke: scratch HOME equals the real one" >&2; exit 1; }

run() {   # run <name> args...: install.sh in the scratch environment; output in $SCR/<name>.out, status in RC
  local name=$1; shift
  RC=0
  env -u CLAUDE_CONFIG_DIR HOME="$SHOME" CODEX_HOME="$CH" XDG_STATE_HOME="$SHOME/.local/state" TMPDIR="$SCR/tmp" \
    STACK_PYTHON="$SMOKE_PY" PATH="$HERE/fake-codex:$PATH" bash "$INSTALL" --codex-home "$CH" "$@" </dev/null >"$SCR/$name.out" 2>&1 || RC=$?
}
out_has() { grep -Eq -- "$2" "$SCR/$1.out"; }
out_lacks() { ! grep -Eq -- "$2" "$SCR/$1.out"; }
show_tail() { tail -n 25 "$SCR/$1.out" | sed 's/^/      /'; }
step() {   # step <name> <expected rc> args...
  local name=$1 want=$2; shift 2
  run "$name" "$@"
  if [ "$RC" = "$want" ]; then ok "$name: exit $RC"; else bad "$name: exit $RC, wanted $want"; show_tail "$name"; fi
}
SCRATCH_STATE() { fingerprint "$CH" nopyc; fingerprint "$SHOME/.agents" nopyc; fingerprint "$SHOME/.local/state" nopyc; }

# ---- the runs ------------------------------------------------------------------------------------------
B0=$(SCRATCH_STATE)
step dry-run 0 --dry-run
check "dry-run writes nothing" test "$B0" = "$(SCRATCH_STATE)"
step diff-first 0 --diff
check "diff names the areas" out_has diff-first '^profiles:'
check "diff writes nothing" test "$B0" = "$(SCRATCH_STATE)"

step apply 0 --yes
check "apply: profile written" test -f "$CH/codex.config.toml"
check "apply: manifest written" test -f "$CH/.stack-manifest.json"
check "apply: stack-python is a link" test -L "$CH/stack/bin/stack-python"
check "apply: stack-python is not the /usr/bin/python3 shim" test "$(readlink "$CH/stack/bin/stack-python")" != /usr/bin/python3
check "apply: stack-python runs" "$CH/stack/bin/stack-python" -I -c 'import sys; sys.exit(sys.version_info < (3, 9))'
check "apply: hook bytecode precompiled" test -d "$CH/stack/hooks/__pycache__"
check "apply: skills linked into the scratch ~/.agents" test -n "$(find "$SHOME/.agents/skills" -maxdepth 1 -type l -print -quit)"
check "apply: a re-trust list is printed" out_has apply 're-trust [0-9]+ hook'
check "apply: stack.env is 0600" test "$(stat -f %Lp "$CH/stack.env" 2>/dev/null || stat -c %a "$CH/stack.env")" = 600
check "apply: config.toml has no stack region" test ! -f "$CH/config.toml" -o -z "$(grep -s 'claude-agent-stack: begin' "$CH/config.toml" || true)"

B1=$(SCRATCH_STATE)
step again 0 --yes
check "second run: nothing to change" out_has again 'Nothing to change'
check "second run changes nothing" test "$B1" = "$(SCRATCH_STATE)"
step dry-run-after 0 --dry-run
check "dry-run after apply plans no changes" out_has dry-run-after 'no changes'
step diff-after 0 --diff
check "diff after apply shows no difference" out_lacks diff-after '^    [-+~] '

step doctor 1 --doctor
check "doctor reports the untrusted hooks" out_has doctor 'untrusted'

B2=$(SCRATCH_STATE)
run ide-refused --ide-default --no-prompt
check "--ide-default without --yes is refused" test "$RC" != 0
check "--ide-default refusal says it changes every session" out_has ide-refused 'EVERY Codex session'
check "--ide-default refusal changes nothing" test "$B2" = "$(SCRATCH_STATE)"
step ide-on 0 --ide-default --yes
check "--ide-default: region A written first" grep -q '^# >>> claude-agent-stack: begin A' <(head -n 1 "$CH/config.toml")
check "--ide-default: config.toml holds both regions" test "$(grep -c 'claude-agent-stack: \(begin\|end\) [AB]' "$CH/config.toml")" = 4
step ide-off 0 --no-ide-default --yes
check "--no-ide-default removes the regions" test -z "$(grep -s 'claude-agent-stack: \(begin\|end\) [AB]' "$CH/config.toml" || true)"

step restore 0 --restore latest --yes
check "restore: output names the backup" out_has restore 'Restored from '

# ---- the real folders ---------------------------------------------------------------------------------
check "real ~/.codex, ~/.agents and the Codex state folders are unchanged" test "$REAL_BEFORE" = "$(real_prints)"

if [ "$FAILS" -ne 0 ]; then echo "smoke: $FAILS check(s) failed"; exit 1; fi
echo "smoke: all checks passed"
