#!/usr/bin/env bash
# dot-config/dot-codex_config/install.sh: the Codex port of the claude-agent-stack installer (DESIGN.md §7.3).
# Not an entry point: the repository's ./install.sh --codex runs it (with STACK_CODEX_VIA_TOP=1).
# Orchestration only (bash 3.2): every conversion, merge and comparison is a Python module of
# dot-config/dot-codex_config/lib, run as `$PY -I <path in the private source snapshot>`.
#
#   ./install.sh --codex --dry-run          show the plan, change nothing
#   ./install.sh --codex --diff             compare the rendered stack with the live CODEX_HOME, by area
#   ./install.sh --codex [--yes]            install (asks first unless --yes)
#   ./install.sh --codex --restore [DIR|latest] [--force] [--force-config] [--dry-run] [--yes]
#   ./install.sh --codex --print-requirements   write the optional machine-wide tier into
#                                   dot-config/dot-codex_config/build/ and print the root commands (never runs them)
#   ./install.sh --codex --doctor           hook trust, manifest drift, skill links (exit 1: untrusted hooks)
# Options: see usage() below. Never pushes, never runs sudo, never writes /etc.
set -euo pipefail
umask 077

# the only entry point is the repository's ./install.sh --codex, which sets STACK_CODEX_VIA_TOP=1
if [ "${STACK_CODEX_VIA_TOP:-}" != 1 ]; then
  echo "use ./install.sh --codex [options] from the repository root: dot-config/dot-codex_config/install.sh is not an entry point" >&2
  exit 2
fi
unset STACK_CODEX_VIA_TOP
ENTRY="./install.sh --codex"

usage() {
  cat <<'EOF'
usage: ./install.sh --codex [options]   (from the repository root)
  --dry-run                  plan only: nothing is written (CODEX_HOME is only created when it is ~/.codex)
  --diff                     compare the rendered stack with the live CODEX_HOME, by area; change nothing
  --restore [DIR|latest]     put CODEX_HOME and the skill links back as before an install (default: latest)
      --force                  also put back saved symlinks that point outside CODEX_HOME
      --force-config           restore config.toml even though it changed since the install
  --yes, -y                  do not ask before changing anything
  --no-prompt                never ask: a run that needs an answer stops unless --yes is given
  --codex-home PATH          CODEX_HOME (default: $CODEX_HOME, else ~/.codex)
  --skills-root PATH|none    where the skill links go (default: ~/.agents/skills; none: no links)
  --profile-name NAME        profile name (only: codex)
  --no-agents-md             do not write the stack's block into AGENTS.md
  --no-mcp                   write no MCP servers
  --legacy-sandbox           sandbox_mode instead of the stack's permission profile
  --git-allow-rules          also write the git allow rules
  --no-escalation            no escalated-command prompts for git
  --with-rollout-budget      add the rollout token budget
  --ide-default              write the profile into config.toml (EVERY Codex session on this machine:
                             CLI without a profile, IDE, desktop app); needs --yes or an answer y
  --no-ide-default           remove those regions again
  --no-astra-profile         do not write the codex-astra profile
  --force                    overwrite a config.toml region edited since the install (restore: see above)
  --print-requirements       write dot-config/dot-codex_config/build/requirements.toml + managed-hooks/
                             and print the root commands for the optional machine-wide tier (never runs them)
  --doctor                   check hook trust, manifest drift and links; exit 1 if a stack hook is untrusted
  -h, --help                 this text
EOF
}
usage_err() { echo "$ENTRY: $1" >&2; usage >&2; exit 2; }
fail() { echo "$ENTRY: $1" >&2; exit "${2:-1}"; }
say() { printf '%s\n' "$*"; }
note() { printf '  %s\n' "$*"; }

# ---- arguments ----------------------------------------------------------------------------------
DRY_RUN=0; DIFF=0; RESTORE=""; FORCE=0; FORCE_CONFIG=0; ASSUME_YES=0; NO_PROMPT=0
CH_SET=0; CH_ARG=""; SKILLS_ROOT=""; PROFILE_NAME=codex
NO_AGENTS_MD=0; NO_MCP=0; LEGACY_SANDBOX=0; GIT_ALLOW=0; NO_ESCALATION=0; ROLLOUT=0
IDE=""; NO_ASTRA=0; PRINT_REQ=0; DOCTOR=0
need_val() { [ "$1" -ge 2 ] || usage_err "$2 needs a value"; }
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --diff) DIFF=1 ;;
    --restore)
      RESTORE=latest
      if [ $# -gt 1 ]; then case "$2" in -*|"") ;; *) RESTORE=$2; shift ;; esac; fi ;;
    --restore=*) RESTORE=${1#*=}; [ -n "$RESTORE" ] || usage_err "--restore= needs a value" ;;
    --force) FORCE=1 ;;
    --force-config) FORCE_CONFIG=1 ;;
    --yes|-y) ASSUME_YES=1 ;;
    --no-prompt) NO_PROMPT=1 ;;
    --codex-home) need_val $# --codex-home; CH_SET=1; CH_ARG=$2; shift ;;
    --codex-home=*) CH_SET=1; CH_ARG=${1#*=} ;;
    --skills-root) need_val $# --skills-root; SKILLS_ROOT=$2; shift ;;
    --skills-root=*) SKILLS_ROOT=${1#*=} ;;
    --profile-name) need_val $# --profile-name; PROFILE_NAME=$2; shift ;;
    --profile-name=*) PROFILE_NAME=${1#*=} ;;
    --no-agents-md) NO_AGENTS_MD=1 ;;
    --no-mcp) NO_MCP=1 ;;
    --legacy-sandbox) LEGACY_SANDBOX=1 ;;
    --git-allow-rules) GIT_ALLOW=1 ;;
    --no-escalation) NO_ESCALATION=1 ;;
    --with-rollout-budget) ROLLOUT=1 ;;
    --ide-default) [ "$IDE" != no ] || usage_err "--ide-default and --no-ide-default together"; IDE=yes ;;
    --no-ide-default) [ "$IDE" != yes ] || usage_err "--ide-default and --no-ide-default together"; IDE=no ;;
    --no-astra-profile) NO_ASTRA=1 ;;
    --print-requirements) PRINT_REQ=1 ;;
    --doctor) DOCTOR=1 ;;
    -h|--help) usage; exit 0 ;;
    *) usage_err "unknown option: $1" ;;
  esac
  shift
done
[ "$CH_SET" = 0 ] || [ -n "$CH_ARG" ] || usage_err "--codex-home needs a non-empty path"
case "$PROFILE_NAME" in
  [A-Za-z0-9]*) case "$PROFILE_NAME" in *[!A-Za-z0-9_-]*) usage_err "--profile-name: letters, digits, - and _ only" ;; esac ;;
  *) usage_err "--profile-name: letters, digits, - and _ only, starting with a letter or digit" ;;
esac
[ "$PROFILE_NAME" = codex ] || usage_err "--profile-name: only \`codex\` is supported in this version: the engine's scope names codex.config.toml"
case "$SKILLS_ROOT" in ""|none|/*) ;; *) usage_err "--skills-root takes an absolute path or none" ;; esac
case "$RESTORE" in ""|latest|/*) ;; *) RESTORE="$PWD/$RESTORE" ;; esac
[ "$(( (${#RESTORE} > 0 ? 1 : 0) + PRINT_REQ + DOCTOR ))" -le 1 ] || usage_err "--restore, --print-requirements and --doctor are separate runs"
if [ -n "$RESTORE" ] || [ "$PRINT_REQ" = 1 ] || [ "$DOCTOR" = 1 ]; then
  [ "$DIFF" = 0 ] || usage_err "--diff compares an install; it does not combine with --restore, --doctor or --print-requirements"
fi
[ "$FORCE_CONFIG" = 0 ] || [ -n "$RESTORE" ] || usage_err "--force-config works only with --restore"

# ---- interpreter, work dir, source snapshot -----------------------------------------------------
case "${HOME:-}" in /*) ;; *) fail "HOME is not set to an absolute path" 2 ;; esac
H=$HOME
PY="${STACK_PYTHON:-}"
if [ -z "$PY" ]; then
  command -v uv >/dev/null 2>&1 || fail "no Python: set STACK_PYTHON to a Python >= 3.11, or install uv (https://docs.astral.sh/uv/) and run: uv python install 3.13"
  PY=$(uv python find --no-project --no-config 3.13 2>/dev/null </dev/null) \
    || fail "uv found no Python 3.13: run  uv python install 3.13  (or set STACK_PYTHON to a Python >= 3.11)"
fi
case "$PY" in /*) ;; *) PY=$(command -v "$PY" 2>/dev/null || true) ;; esac
if [ -z "$PY" ] || ! "$PY" -I -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1 </dev/null; then
  fail "STACK_PYTHON or uv's Python 3.13 is not a working Python >= 3.11 (the installer needs tomllib): set STACK_PYTHON to one"
fi

HERE=$(cd "$(dirname "$0")" && pwd -P)
REPO=$(cd "$HERE/../.." && pwd -P)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/codex-install.XXXXXX") || fail "cannot create a work folder under ${TMPDIR:-/tmp}"
cleanup() { if [ -n "${WORK:-}" ] && [ -d "$WORK" ]; then rm -rf -- "$WORK"; fi; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# the repository is read ONCE here; every later step reads and runs $SRC (no --allow-dirty: an edit
# not committed stops the run)
if ! COMMIT=$("$PY" -I "$HERE/lib/source_snapshot.py" "$REPO" "$WORK/src"); then
  fail "stopped at the source snapshot (above). Nothing was changed."
fi
SRC="$WORK/src"
CL="$SRC/dot-config/dot-codex_config/lib"
STATE_PY="$CL/codex_state.py"
cs() { "$PY" -I "$STATE_PY" "$@"; }

STATE_ROOT="${XDG_STATE_HOME:-$H/.local/state}"
case "$STATE_ROOT" in /*) ;; *) fail "XDG_STATE_HOME is not an absolute path" 2 ;; esac
STATE_DIR="$STATE_ROOT/codex-agent-stack"
BACKUP_ROOT="$STATE_ROOT/codex-agent-stack-backups"

# ---- step 2: CODEX_HOME (refusals exit 2 with the reason) ---------------------------------------
repos=("$REPO")
LOGICAL=$(cd "$(dirname "$0")/../.." && pwd) && [ "$LOGICAL" = "$REPO" ] || repos+=("$LOGICAL")
rc=0
if [ "$CH_SET" = 1 ]; then HOME_OUT=$(cs home 1 "$CH_ARG" "${repos[@]}") || rc=$?
else HOME_OUT=$(cs home 0 "" "${repos[@]}") || rc=$?; fi
[ "$rc" = 0 ] || exit "$rc"
CH=""; CH_SOURCE=""; CH_CREATED=0
while IFS=$'\t' read -r k v; do
  case "$k" in
    path) CH=$v ;; source) CH_SOURCE=$v ;; created) CH_CREATED=$v ;;
    warn) echo "$ENTRY: warning: $v" >&2 ;;
  esac
done <<<"$HOME_OUT"
[ -n "$CH" ] || fail "codex_state home returned no path"
[ "$CH_CREATED" != 1 ] || note "created $CH (0700)"
say "CODEX_HOME: $CH ($CH_SOURCE)"

# ---- the single-purpose runs ---------------------------------------------------------------------
if [ "$DOCTOR" = 1 ]; then
  rc=0
  "$PY" -I "$CL/doctor.py" --codex-home "$CH" --home "$H" || rc=$?
  exit "$rc"
fi

if [ "$PRINT_REQ" = 1 ]; then
  # writes only into dot-config/dot-codex_config/build (git-ignored); the root commands are printed, never run
  "$PY" -I "$CL/requirements.py" --codex-home "$CH" --home "$H" --src "$SRC" \
    --out "$REPO/dot-config/dot-codex_config/build" --state-dir "$STATE_DIR"
  exit 0
fi

# ask "<question>": 0 = yes. --yes answers yes; --no-prompt never asks; else the terminal (stdin and
# stderr, or the controlling terminal); with none the run stops (never proceed unasked)
ask() {
  [ "$ASSUME_YES" = 0 ] || return 0
  if [ "$NO_PROMPT" = 1 ]; then echo "$ENTRY: $1 --no-prompt forbids asking: rerun with --yes." >&2; return 1; fi
  local ans=""
  if [ -t 0 ] && [ -t 2 ]; then printf '%s [y/N] ' "$1" >&2; read -r ans || true
  elif { : </dev/tty; } 2>/dev/null && { : >/dev/tty; } 2>/dev/null; then printf '%s [y/N] ' "$1" >/dev/tty; read -r ans </dev/tty || true
  else echo "$ENTRY: $1 There is no terminal to ask: rerun with --yes." >&2; return 1; fi
  case "$ans" in y|Y|yes|YES|Yes) return 0 ;; *) return 1 ;; esac
}

# ---- --restore: skill links first, then the engine -----------------------------------------------
if [ -n "$RESTORE" ]; then
  RFLAGS=()
  [ "$FORCE" = 0 ] || RFLAGS+=(--force)
  [ "$FORCE_CONFIG" = 0 ] || RFLAGS+=(--force-config)
  mkdir "$WORK/r1" "$WORK/r2"
  # a dry run first: it makes every refusal (changed config.toml, foreign backup) before any link moves,
  # and names the backup folder the links are undone from
  say "Restore plan:"
  cs restore "$CH" "$RESTORE" "$BACKUP_ROOT" "$WORK/r1" "$COMMIT" "$H" --dry-run ${RFLAGS[@]+"${RFLAGS[@]}"} \
    || fail "nothing was restored."
  BDIR=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1]))["backup"])' "$WORK/r1/restore.json")
  if [ "$DRY_RUN" = 1 ]; then say "Dry run done: nothing was restored."; exit 0; fi
  ask "Put $CH and its skill links back as they were before the install in $BDIR?" || fail "stopped before changing anything. Nothing in $CH was changed."
  if [ -f "$BDIR/skill-links.json" ]; then
    "$PY" -I "$CL/skill_links.py" restore "$BDIR" || fail "skill links: see above; CODEX_HOME was not restored (fix the links, then rerun --restore)."
  fi
  cs restore "$CH" "$RESTORE" "$BACKUP_ROOT" "$WORK/r2" "$COMMIT" "$H" ${RFLAGS[@]+"${RFLAGS[@]}"} \
    || fail "the engine's restore failed after the skill links were put back (above); rerun --restore."
  # what the install left outside the engine's scope: the interpreter link and bytecode, once the stack is gone
  if [ -d "$CH/stack" ] && [ ! -L "$CH/stack" ] && [ ! -e "$CH/stack/bin/codex-hook" ]; then
    rm -f -- "$CH/stack/bin/stack-python"
    rm -rf -- "$CH/stack/hooks/__pycache__"
    rmdir "$CH/stack/bin" "$CH/stack/hooks" "$CH/stack" 2>/dev/null || true
  fi
  UNDO=$("$PY" -I -c 'import json,sys; print(json.load(open(sys.argv[1])).get("undo") or "")' "$WORK/r2/restore.json" 2>/dev/null || true)
  say "Restored from $BDIR."
  [ -z "$UNDO" ] || note "undo this restore: $ENTRY --restore $UNDO"
  exit 0
fi

# ---- step 2b: the Codex CLI, when there is one ---------------------------------------------------
MIN_CODEX=0.160.1
ver_ge() {   # ver_ge A B: numeric dotted compare, A >= B
  local IFS=. a b i
  read -r -a a <<<"$1"; read -r -a b <<<"$2"
  for i in 0 1 2; do
    [ "${a[$i]:-0}" -eq "${b[$i]:-0}" ] && continue
    [ "${a[$i]:-0}" -gt "${b[$i]:-0}" ]; return
  done
}
CODEX_BIN=$(command -v codex 2>/dev/null || true)
if [ -n "$CODEX_BIN" ]; then
  cv=$("$CODEX_BIN" --version </dev/null 2>/dev/null | sed -n 's/.*\([0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*\).*/\1/p' | head -n 1 || true)
  if [ -z "$cv" ]; then
    echo "$ENTRY: warning: could not read the version of $CODEX_BIN; the Codex checks are skipped" >&2
    CODEX_BIN=""
  elif ! ver_ge "$cv" "$MIN_CODEX"; then
    fail "codex $cv is older than $MIN_CODEX, the version this stack was verified against: update Codex (npm i -g @openai/codex, or brew upgrade codex). Nothing was changed."
  else
    note "codex $cv ($CODEX_BIN)"
  fi
else
  echo "$ENTRY: warning: no codex on PATH; the rule examples are not checked against it" >&2
fi

# ---- step 3: stage the live CODEX_HOME ------------------------------------------------------------
S="$WORK/stage"; SNAP="$WORK/snapshot.json"; PLAN_JSON="$WORK/plan.json"
mkdir "$S"
cs stage "$CH" "$S" "$SNAP" || fail "stage failed (above). Nothing was changed."

# ---- step 4: render ------------------------------------------------------------------------------
RARGS=(--src "$SRC" --stage "$S" --work "$WORK" --codex-home "$CH" --home "$H" --state-dir "$STATE_DIR"
       --profile-name "$PROFILE_NAME" --codex "${CODEX_BIN:-none}")
[ -z "$SKILLS_ROOT" ] || RARGS+=(--skills-root "$SKILLS_ROOT")
UV=$(command -v uv 2>/dev/null || true)
[ -z "$UV" ] || RARGS+=(--uv "$UV")
# wandb's server needs a key: presence only (a non-empty WANDB_API_KEY line), the value is never read into a variable
if grep -Eqs "^[[:space:]]*(export[[:space:]]+)?WANDB_API_KEY=[[:space:]]*(\"[^\"]|'[^']|[^\"'[:space:]#])" "$CH/stack.env"; then
  RARGS+=(--with-wandb)
fi
[ "$NO_AGENTS_MD" = 0 ] || RARGS+=(--no-agents-md)
[ "$NO_MCP" = 0 ] || RARGS+=(--no-mcp)
[ "$LEGACY_SANDBOX" = 0 ] || RARGS+=(--legacy-sandbox)
[ "$GIT_ALLOW" = 0 ] || RARGS+=(--git-allow-rules)
[ "$NO_ESCALATION" = 0 ] || RARGS+=(--no-escalation)
[ "$ROLLOUT" = 0 ] || RARGS+=(--with-rollout-budget)
[ "$IDE" != yes ] || RARGS+=(--ide-default)
[ "$IDE" != no ] || RARGS+=(--no-ide-default)
[ "$NO_ASTRA" = 0 ] || RARGS+=(--no-astra-profile)
[ "$FORCE" = 0 ] || RARGS+=(--force)
"$PY" -I "$CL/render.py" "${RARGS[@]}" || fail "render failed (above). Nothing was changed."
# the mode this run resolved (the flag, else the one config.toml shows: a flagless re-run keeps it)
IDE_MODE=$("$PY" -I -c 'import json, sys; print("yes" if json.load(open(sys.argv[1])).get("ide_default") is True else "no")' "$WORK/options.json") \
  || fail "render wrote no readable options.json. Nothing was changed."

# ---- step 5: validate the stage -------------------------------------------------------------------
say "Validate:"
cs validate "$S" || fail "the rendered stack does not validate (above). Nothing was changed."
GUARD="$S/stack/hooks/codex_guard.py"
if ! ST=$(PYTHONDONTWRITEBYTECODE=1 "$PY" -I "$GUARD" --self-test 2>&1 </dev/null); then
  printf '%s\n' "$ST" | sed 's/^/    /' >&2
  fail "the guard's self-test failed. Nothing was changed."
fi
EVENT='{"session_id":"install-check","turn_id":"t","cwd":"/","hook_event_name":"PreToolUse","model":"m","permission_mode":"default","tool_name":"Bash","tool_input":{"command":"git push origin main"},"tool_use_id":"u-push","transcript_path":null}'
PUSH_OUT=$(printf '%s' "$EVENT" | XDG_STATE_HOME="$WORK/guard-state" PYTHONDONTWRITEBYTECODE=1 "$PY" -I "$GUARD" pre_tool_use 2>&1) || true
case "$PUSH_OUT" in
  *'"permissionDecision":"deny"'*) note "guard self-test passed; a synthetic PreToolUse git push is denied" ;;
  *) printf '%s\n' "$PUSH_OUT" | head -n 5 | sed 's/^/    /' >&2; fail "the staged guard did not deny a synthetic git push. Nothing was changed." ;;
esac

# ---- step 6: manifest, plans ----------------------------------------------------------------------
cs manifest "$S" "$COMMIT" "$WORK" || fail "manifest failed (above). Nothing was changed."
OLDMF=-
if [ -f "$CH/.stack-manifest.json" ] && [ ! -L "$CH/.stack-manifest.json" ]; then
  cp -- "$CH/.stack-manifest.json" "$WORK/old-manifest.json" && OLDMF="$WORK/old-manifest.json"
fi
NEWMF="$S/.stack-manifest.json"

if [ "$DIFF" = 1 ]; then
  say "Differences, rendered stack against $CH (nothing is changed):"
  "$PY" -I "$CL/codex_diff.py" "$CH" "$S" "$WORK/links.json"
  exit 0
fi

# what changed in the sources since the last install (the supply review)
prev=""
if [ "$OLDMF" != - ]; then
  prev=$("$PY" -I -c 'import json,re,sys
try:
    v = json.load(open(sys.argv[1])).get("commit") or ""
except Exception:
    v = ""
print(v if re.fullmatch(r"[0-9a-f]{7,64}", str(v)) else "")' "$OLDMF" 2>/dev/null || true)
fi
if [ -n "$prev" ] && [ "$prev" != "$COMMIT" ]; then
  # against the snapshot's commit, never HEAD
  # first line: the paths to review (a pre-move commit adds the old ones); then the diff --stat
  SUP=$("$PY" -I - "$CL/source_snapshot.py" "$REPO" "$prev" "$COMMIT" <<'PY' || true
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ss", sys.argv[1])
ss = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ss)
r = ss.changes_since(sys.argv[2], sys.argv[3], sys.argv[4])
if r is None:
    print("?")
else:
    print(" ".join(dict.fromkeys("lib" if p.startswith("lib/") else p for p in ss.review_paths(sys.argv[2], sys.argv[3]))))
    print(r.rstrip("\n"))
PY
)
  SUP_PATHS=${SUP%%$'\n'*}
  [ "$SUP" = "?" ] || { SUP=${SUP#"$SUP_PATHS"}; SUP=${SUP#$'\n'}; }
  if [ "$SUP" = "?" ]; then
    note "! the last install shipped commit ${prev:0:12}, which this repository does not have: review the stack's files before applying"
  elif [ -n "$SUP" ]; then
    say "Changes to the stack's files since the last install (${prev:0:12}..${COMMIT:0:12}):"
    printf '%s\n' "$SUP" | head -n 40 | sed 's/^/      /'
    note "review: git -C '$REPO' diff ${prev:0:12} ${COMMIT:0:12} -- $SUP_PATHS"
  fi
fi

say "Plan:"
cs plan "$CH" "$S" "$WORK/build-report.json" "$PLAN_JSON" "$SNAP" || fail "plan failed (above). Nothing was changed."
SL="$CL/skill_links.py"
say "Skill links:"
LINKS_OUT=$("$PY" -I "$SL" plan "$WORK/links.json" "$OLDMF") || fail "skill links: see above. Nothing was changed."
printf '%s\n' "$LINKS_OUT"
PLAN_EMPTY=$("$PY" -I -c 'import json,sys; p=json.load(open(sys.argv[1])); print(0 if (p["added"] or p["changed"] or p["removed"]) else 1)' "$PLAN_JSON")
LINKS_EMPTY=1
if grep -Eq '^  [-+~] ' <<<"$LINKS_OUT"; then LINKS_EMPTY=0; fi

retrust_list() { cs retrust "$OLDMF" "$NEWMF"; }
print_retrust() {   # $1: the verb phrase
  local keys n
  keys=$(retrust_list) || return 0
  if [ -z "$keys" ]; then say "Hooks: no hook definition changed: no re-trust needed."; return 0; fi
  n=$(printf '%s\n' "$keys" | wc -l | tr -d ' ')
  say "Hooks: $1 re-trust $n hook(s) in /hooks:"
  printf '%s\n' "$keys" | sed 's/^/      /'
}

if [ "$DRY_RUN" = 1 ]; then
  print_retrust "after an install you would need to"
  say "Dry run done: nothing was applied."
  exit 0
fi

# ---- step 7: confirm, back up, apply ---------------------------------------------------------------
B=""
if [ "$PLAN_EMPTY" = 1 ] && [ "$LINKS_EMPTY" = 1 ]; then
  say "Nothing to change: CODEX_HOME and the skill links already match this stack version."
else
  if [ "$IDE" = yes ]; then
    say "! --ide-default writes the profile into $CH/config.toml: it changes EVERY Codex session on this machine"
    say "  (the CLI without a profile, the IDE extension and the ChatGPT desktop app), not only 'codex --profile $PROFILE_NAME'."
    say "  Undo: $ENTRY --no-ide-default, or $ENTRY --restore."
    ask "Apply the plan above, including --ide-default?" || fail "stopped before changing anything. Nothing in $CH was changed."
  else
    ask "Apply the plan above to $CH?" || fail "stopped before changing anything. Nothing in $CH was changed."
  fi
  if [ "$PLAN_EMPTY" = 0 ]; then
    cs apply "$CH" "$S" "$PLAN_JSON" "$BACKUP_ROOT" "$COMMIT" "$WORK/backup-dir" "$SNAP" || fail "apply failed (above)."
    B=$(cat "$WORK/backup-dir")
  fi
  # ---- step 8: skill links, recorded in the same backup folder -------------------------------------
  if [ "$LINKS_EMPTY" = 0 ]; then
    [ -n "$B" ] || B=$(cs new-backup "$CH" "$BACKUP_ROOT" "$COMMIT")
    if ! "$PY" -I "$SL" apply "$WORK/links.json" "$OLDMF" "$B"; then
      fail "the skill links failed (above) after CODEX_HOME was updated; fix that and rerun, or undo with: $ENTRY --restore $B"
    fi
  fi
  [ -z "$B" ] || say "Backup: $B   (undo: $ENTRY --restore $B)"
fi

# ---- step 9: stack-python, bytecode, hook trust --------------------------------------------------
STACK="$CH/stack"
if [ -d "$STACK/bin" ] && [ ! -L "$STACK" ]; then
  # a REAL interpreter binary: /usr/bin/python3 is a shim that dispatches on argv[0] and exits 72
  # (which denies every gated call), so its path is never the target
  TARGET=$("$PY" -I -c 'import os, sys; print(os.path.realpath(sys.executable))')
  if [ "$TARGET" = /usr/bin/python3 ] || [ ! -x "$TARGET" ]; then
    fail "the hook interpreter ($TARGET) is not a real Python binary: set STACK_PYTHON to a uv-managed Python 3.13 (uv python find 3.13) and rerun."
  fi
  ln -s -- "$TARGET" "$STACK/bin/.stack-python.$$" && mv -f -- "$STACK/bin/.stack-python.$$" "$STACK/bin/stack-python"
  note "$STACK/bin/stack-python -> $TARGET"
fi
if [ -d "$STACK/hooks" ] && [ ! -L "$STACK" ]; then
  PRECOMPILE='import py_compile,sys; [py_compile.compile(f, doraise=True, invalidation_mode=py_compile.PycInvalidationMode.CHECKED_HASH) for f in sys.argv[1:]]'
  set -- "$STACK"/hooks/*.py
  if [ -e "$1" ]; then
    for interp in "$STACK/bin/stack-python" /usr/bin/python3; do
      [ -x "$interp" ] || continue
      if "$interp" -I -c "$PRECOMPILE" "$@" >"$WORK/precompile.log" 2>&1 </dev/null; then
        note "hook bytecode compiled for $interp"
      else
        note "! bytecode for $interp failed (the hooks still run, compiling on first use): $(head -n 1 "$WORK/precompile.log")"
      fi
    done
  fi
fi
print_retrust "re-trust:"

# ---- user steps ----------------------------------------------------------------------------------
echo
say "Next steps (yours; the installer never trusts hooks or logs in for you):"
if [ "$IDE_MODE" = yes ]; then
  say "  1. Run plain 'codex' (no profile), then /hooks and trust the stack's hooks whose source is config.toml."
  say "     Restart the IDE (and the desktop app, if you use it)."
else
  say "  1. Run: codex --profile $PROFILE_NAME   then /hooks and trust the stack's hooks."
fi
say "  2. Run: $ENTRY --doctor   (exit 0 only when every stack hook is trusted; repeat after every 're-trust' above)."
if [ -f "$S/codex-astra.config.toml" ]; then
  if [ "$IDE_MODE" = yes ]; then
    say "  3. Optional Astra: codex --profile codex-astra (it overlays config.toml, whose trusted hooks it uses)."
  else
    say "  3. Optional Astra: codex --profile codex-astra, then /hooks (its own hooks need trust too)."
  fi
  say "     COST: each session started with it bills the six top-tier agents at Astra rates (\$10 / \$50 per 1M tokens)."
fi
OVR=$("$PY" -I -c 'import json, sys
def walk(v):
    if isinstance(v, str):
        if "AGENTS.override" in v:
            print(v)
    elif isinstance(v, dict):
        for x in v.values():
            walk(x)
    elif isinstance(v, list):
        for x in v:
            walk(x)
try:
    walk(json.load(open(sys.argv[1])))
except Exception:
    pass' "$WORK/build-report.json" 2>/dev/null || true)
if [ -n "$OVR" ]; then
  printf '  ! %s\n' "$OVR"
elif [ "$NO_AGENTS_MD" = 0 ] && [ -e "$CH/AGENTS.override.md" ]; then
  say "  ! $CH/AGENTS.override.md exists and shadows AGENTS.md: the stack's global rules block is NOT read until you remove or merge it."
fi
if [ "$IDE_MODE" = yes ]; then
  say "The guard is INACTIVE until you trust its hooks: run plain \`codex\` (no profile), then \`/hooks\`."
else
  say "The guard is INACTIVE until you trust its hooks: run \`codex --profile $PROFILE_NAME\`, then \`/hooks\`."
fi
