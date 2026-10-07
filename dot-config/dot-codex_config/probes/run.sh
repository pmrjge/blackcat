#!/bin/bash
# Phase 0 probe kit (dot-config/dot-codex_config/DESIGN.md section 9). The USER runs this with Codex installed.
# Everything happens in a scratch CODEX_HOME and scratch HOME under ${TMPDIR:-/tmp}; the real ~/.codex,
# ~/.agents and /etc are never written, and auth files are never copied (you log in inside the scratch home).
# This script itself never starts Codex except `codex --version`; it prints the commands YOU run.
#
#   run.sh --list             one line per probe
#   run.sh --dry-run          print every file it would write and every command you would run (no prompts)
#   run.sh --probe P7b        one probe       (default: all, P2 first because it trusts the hooks)
#   run.sh --help
# Env: CODEX_HOME may name the scratch home to use; it must not exist or be an empty dir; ~/.codex is refused.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
FIX=$HERE/fixtures
IDS="P1 P2 P3 P4 P5 P6 P7 P7b P8 P9 P10 P11 P12 P13"
ORDER="P2 P1 P3 P4 P5 P6 P7 P7b P8 P9 P10 P11 P12 P13"

title_of() {
  case "$1" in
    P1) echo "profile hooks fire only with --profile (U4 observed: hook command via shell or argv)";;
    P2) echo "where /hooks writes trust: config.toml or the profile file (U1)";;
    P3) echo "agent_type present in a subagent's PreToolUse";;
    P4) echo "hyphenated role names accepted as agent_type (U2)";;
    P5) echo "roles load via [agents.x].config_file";;
    P6) echo "profile MCP servers load";;
    P7) echo "permission profile from the profile file: CODEX_HOME read-only, auth.json unreadable (U5)";;
    P7b) echo ".git write grant inside a permission profile (U6)";;
    P8) echo "a forbidden prefix_rule blocks an in-sandbox git push";;
    P9) echo "hooks run unsandboxed (U3)";;
    P10) echo "symlinked skills are listed";;
    P11) echo "IDE ignores the profile and reads hooks.state trust written by the CLI (U9, manual)";;
    P12) echo "/hooks, /model, project-trust writes keep comments and append outside stack regions (U13)";;
    P13) echo "PreToolUse tool_name of multi-agent tools, update_plan, request_user_input, view_image (U10, U11)";;
    *) return 1;;
  esac
}

usage() { sed -n '2,14p' "$0" | sed 's/^# \{0,1\}//'; }

MODE=run; ONLY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --list) MODE=list;;
    --dry-run) MODE=dry;;
    --probe) shift; [ $# -gt 0 ] || { echo "run.sh: --probe needs an id" >&2; exit 2; }
             ONLY=$(echo "$1" | sed 's/^p/P/; s/B$/b/');;
    -h|--help) usage; exit 0;;
    *) echo "run.sh: unknown argument: $1" >&2; exit 2;;
  esac
  shift
done

if [ "$MODE" = list ]; then
  for id in $IDS; do printf '%-4s %s\n' "$id" "$(title_of "$id")"; done
  exit 0
fi
if [ -n "$ONLY" ]; then
  case " $IDS " in *" $ONLY "*) ;; *) echo "run.sh: unknown probe: $ONLY (see --list)" >&2; exit 2;; esac
fi

# ---------------------------------------------------------------- safety
canon() {  # physical path of a possibly missing path
  local p=$1 d b
  if [ -d "$p" ]; then (cd "$p" && pwd -P); return; fi
  d=$(dirname "$p"); b=$(basename "$p")
  if [ -d "$d" ]; then echo "$(cd "$d" && pwd -P)/$b"; else echo "$p"; fi
}
REAL_HOME=$(canon "${HOME:?HOME is unset}")
inside() { case "$1/" in "$2"/*) return 0;; esac; return 1; }   # $1 equal to or under $2
refuse_if_protected() {  # $1 = path, $2 = what
  local c; c=$(canon "$1")
  if [ "$c" = "/" ] || [ "$c" = "$REAL_HOME" ] \
     || inside "$c" "$REAL_HOME/.codex" || inside "$c" "$REAL_HOME/.agents" \
     || inside "$c" /etc || inside "$c" /private/etc; then
    echo "run.sh: refusing $2 = $1 (the real ~/.codex, ~/.agents, \$HOME or /etc are never used)." >&2
    echo "        Unset CODEX_HOME or point it at a new, empty scratch directory." >&2
    exit 3
  fi
  if [ -e "$c" ] && { [ ! -d "$c" ] || [ -n "$(ls -A "$c" 2>/dev/null)" ]; }; then
    echo "run.sh: refusing $2 = $1: it exists and is not an empty directory this script created." >&2
    exit 3
  fi
}
if [ -n "${CODEX_HOME:-}" ]; then refuse_if_protected "$CODEX_HOME" CODEX_HOME; fi

ROOT=$(mktemp -d "${TMPDIR:-/tmp}/codex-probes.XXXXXX")
ROOT=$(cd "$ROOT" && pwd -P)
refuse_if_protected_root() { local c; c=$(canon "$ROOT"); if inside "$c" "$REAL_HOME/.codex" || inside "$c" "$REAL_HOME/.agents" || inside "$c" /etc; then rm -rf "$ROOT"; echo "run.sh: scratch dir would be inside a protected path" >&2; exit 3; fi; }
refuse_if_protected_root
if [ "$MODE" = dry ]; then
  trap 'rm -rf "$ROOT"' EXIT
  CH=$ROOT/codex-home
  [ -z "${CODEX_HOME:-}" ] || echo "(dry run) CODEX_HOME=$CODEX_HOME accepted; files below go to a temp dir that is removed."
else
  CH=${CODEX_HOME:-$ROOT/codex-home}
fi
HOMEX=$ROOT/home; WORK=$ROOT/work; LOGS=$ROOT/logs; BIN=$ROOT/bin
LOG=$LOGS/hooks.jsonl; RES=$ROOT/results.tsv; REPORT=$ROOT/report.json
SKILLS=$HOMEX/.agents/skills
ENVP="env HOME=$HOMEX CODEX_HOME=$CH PROBE_U4=expanded"

# ---------------------------------------------------------------- helpers
say() { printf '%s\n' "$*"; }
emit_note() { say "  write: $1"; }
render() {  # render SRC DST  (token substitution)
  mkdir -p "$(dirname "$2")"
  sed -e "s|@ROOT@|$ROOT|g" -e "s|@CODEX_HOME@|$CH|g" -e "s|@WORK@|$WORK|g" -e "s|@HOME@|$HOMEX|g" "$1" > "$2"
  emit_note "$2"
}
render_cat() { local dst=$1; shift; local f; : > "$dst"
  for f in "$@"; do sed -e "s|@ROOT@|$ROOT|g" -e "s|@CODEX_HOME@|$CH|g" -e "s|@WORK@|$WORK|g" -e "s|@HOME@|$HOMEX|g" "$f" >> "$dst"; done
  emit_note "$dst"; }
copyf() { mkdir -p "$(dirname "$2")"; cp "$1" "$2"; emit_note "$2"; }
putf() { mkdir -p "$(dirname "$1")"; cat > "$1"; emit_note "$1"; }
cmd() { say "      \$ $*"; }
step() { say "    $1) $2"; }
interactive() { [ "$MODE" = run ]; }
wait_enter() { if interactive; then printf '    [press Enter when done] '; read -r _ || true; else say "    (wait for you to finish)"; fi; }
ANS=u
ask() {  # ask "question"  -> ANS=y|n|u
  ANS=u
  if interactive; then
    printf '    ? %s [y/n/skip] ' "$1"; local a=""; read -r a || a=""
    case "$a" in y|Y|yes) ANS=y;; n|N|no) ANS=n;; esac
  else say "    ? $1 [y/n/skip]"; fi
}
clean() { printf '%s' "$1" | tr '\t\n\r' '   ' | cut -c1-600; }
record() {  # record ID RESULT EVIDENCE NOTES
  if interactive; then printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$(clean "$3")" "$(clean "${4:-}")" >> "$RES"; fi
  interactive && say "    => $1: $2 -- $(clean "$3")" || true
}
mark() { printf '### %s\n' "$1" >> "$LOG"; }
sect() { awk -v m="### $1" '$0==m{on=1;next} /^### /{on=0} on' "$LOG" 2>/dev/null || true; }
cnt() { local n; n=$(sect "$1" | grep -Ec "$2" || true); echo "${n:-0}"; }
vals() { sect "$1" | grep -Eo "$2" | sort -u | tr '\n' ' ' || true; }

codex_exec() {  # codex_exec MARKER PROFILE PROMPTFILE OUTNAME
  local m=$1 prof=$2 pf=$3 out=$LOGS/$4
  mark "$m"
  local pa=""; [ -z "$prof" ] || pa="--profile $prof "
  cmd "$ENVP codex ${pa}exec --skip-git-repo-check -C $WORK \"\$(cat $pf)\" 2>&1 | tee $out"
}
prompt() { putf "$ROOT/prompts/$1.txt"; }

# ---------------------------------------------------------------- scratch layout
setup_base() {
  say "== Scratch layout"
  say "  scratch root : $ROOT"
  say "  CODEX_HOME   : $CH"
  say "  HOME (scratch): $HOMEX   skills root: $SKILLS"
  mkdir -p "$CH" "$HOMEX" "$LOGS" "$BIN" "$WORK" "$SKILLS" "$ROOT/outside" "$ROOT/prompts"
  chmod 700 "$CH"
  : > "$LOG"; : > "$RES"
  render "$FIX/hooklog.sh" "$BIN/hooklog.sh"
  copyf "$FIX/mcp_echo.py" "$BIN/mcp_echo.py"
  copyf "$FIX/config.base.toml" "$CH/config.toml"
  render_cat "$CH/probe.config.toml" "$FIX/profile.probe.toml" "$FIX/hooks.snippet.toml"
  render_cat "$CH/probe-perm.config.toml" "$FIX/profile.probe-perm.toml" "$FIX/hooks.snippet.toml"
  render_cat "$CH/probe-git.config.toml" "$FIX/profile.probe-git.toml" "$FIX/hooks.snippet.toml"
  copyf "$FIX/roles/probe_worker.toml" "$CH/probe-roles/probe_worker.toml"
  copyf "$FIX/roles/probe-worker.toml" "$CH/probe-roles/probe-worker.toml"
  copyf "$FIX/pixel.png" "$WORK/pixel.png"
  putf "$HOMEX/.gitconfig" <<'G'
[user]
	name = probe
	email = probe@example.invalid
[init]
	defaultBranch = main
G
  export GIT_CONFIG_GLOBAL=$HOMEX/.gitconfig GIT_CONFIG_NOSYSTEM=1
  git -c init.defaultBranch=main init -q "$WORK"
  git -C "$WORK" -c user.name=probe -c user.email=probe@example.invalid commit -q --allow-empty -m base
  git init -q --bare "$ROOT/remote.git"
  git -C "$WORK" remote add probe-origin "$ROOT/remote.git"
  say "  git: $WORK (work repo) and $ROOT/remote.git (local bare remote, never a network remote)"
  say
}

preamble() {
  say "== Codex"
  local v
  if v=$(codex --version 2>&1); then say "  codex --version: $v"; CODEX_VERSION=$v
  else say "  codex --version failed or codex not on PATH: $v"; CODEX_VERSION="unavailable"; fi
  say
  say "== Login (once, in the scratch home; this script never copies auth files)"
  cmd "$ENVP codex login"
  if interactive; then
    printf '    [press Enter once logged in, or to continue without login] '; read -r _ || true
    if [ -f "$CH/auth.json" ]; then say "  auth.json present in the scratch home."; else say "  no auth.json yet: probes that start a model session will give 'unknown'."; fi
  fi
  say
}

trust_step() {  # make the logging hooks trusted via /hooks (TUI)
  say "  Trust the hooks (TUI):"
  step 1 "start the profile session"; cmd "$ENVP codex --profile probe -C $WORK"
  step 2 "type /hooks, trust every listed hook (PreToolUse, PermissionRequest, PostToolUse, SubagentStart, SubagentStop, UserPromptSubmit, SessionStart), then quit"
  wait_enter
}
trust_where() {
  local a="no" b="no" keys
  grep -qs 'hooks.state' "$CH/config.toml" && a=yes || true
  grep -qs 'hooks.state' "$CH/probe.config.toml" && b=yes || true
  keys=$(grep -hs '^\[hooks.state' "$CH/config.toml" "$CH/probe.config.toml" | head -3 | tr '\n' ' ' || true)
  echo "config.toml=$a probe.config.toml=$b ${keys}"
}
ensure_trust() {
  if [ "$MODE" = dry ]; then say "  (needs the hooks trusted: P2's /hooks step; asked for automatically when missing)"; return 0; fi
  if ! trust_where | grep -q '=yes'; then
    say "  hooks are not trusted yet in this scratch home."; trust_step
  fi
}

# ---------------------------------------------------------------- probes
p_P1() {
  ensure_trust
  prompt P1 <<'T'
Run the shell command: echo p1-run
Then reply with the single word done. Do not do anything else.
T
  say "  Run both (a: no profile, b: profile):"
  step a "no --profile: no hook may fire"; codex_exec P1/noprofile "" "$ROOT/prompts/P1.txt" P1a.out; wait_enter
  step b "with --profile probe: hooks must fire"; codex_exec P1/profile probe "$ROOT/prompts/P1.txt" P1b.out; wait_enter
  local na nb a2
  na=$(cnt P1/noprofile '^(PreToolUse|SessionStart|UserPromptSubmit|PostToolUse)'); nb=$(cnt P1/profile '^(PreToolUse|SessionStart|UserPromptSubmit|PostToolUse)')
  a2=$(vals P1/profile '^#meta .*arg2=[^ ]*' | sed 's/.*arg2=//' | head -c 80)
  local u4="U4 unobserved"
  case "$a2" in *expanded*) u4="U4: command went through a shell (arg2 expanded)";; *'$PROBE_U4'*) u4="U4: command split into argv (arg2 literal)";; esac
  if [ "$nb" -gt 0 ] && [ "$na" -eq 0 ]; then record P1 pass "profile run: $nb hook lines; no-profile run: $na" "$u4"
  elif [ "$na" -gt 0 ]; then record P1 fail "hooks fired WITHOUT --profile ($na lines): hooks leak into plain codex" "$u4"
  else record P1 unknown "profile run produced no hook lines (hooks untrusted, not logged in, or exec differs)" "$u4"; fi
}

p_P2() {
  say "  Before: $(trust_where)"
  trust_step
  local w; w=$(trust_where)
  if echo "$w" | grep -q '=yes'; then record P2 pass "trust records: $w" "U1 answer: see which file holds [hooks.state]; both=yes means config.toml and profile file"
  else record P2 unknown "no [hooks.state] in config.toml or probe.config.toml after /hooks" "trust not given, or written elsewhere (find $CH -name '*.toml' | xargs grep -l state)"; fi
}

spawn_prompt() {  # spawn_prompt ID ROLE ECHO
  prompt "$1" <<T
Use the spawn_agent tool exactly once with agent_type (role) $2 and this message: run the shell command echo $3, then reply with the word done.
Then wait for it with wait_agent and reply with the word finished. Do not run any shell command yourself.
T
}
role_run() {  # role_run ID ROLE
  ensure_trust
  spawn_prompt "$1" "$2" "$1-sub"
  say "  Spawn the role from the profile session:"
  codex_exec "$1" probe "$ROOT/prompts/$1.txt" "$1.out"; wait_enter
}
p_P3() {
  role_run P3 probe_worker
  local n s v
  n=$(cnt P3 '^PreToolUse.*"agent_type": *"[^"]+"'); s=$(cnt P3 '^SubagentStart')
  v=$(vals P3 '"agent_type": *"[^"]*"')
  if [ "$n" -gt 0 ]; then record P3 pass "PreToolUse carried agent_type: $v" "F9 confirmed live"
  elif [ "$s" -gt 0 ]; then record P3 fail "subagent ran ($s SubagentStart) but no PreToolUse had agent_type" "design fallback needed (DESIGN F9 / section 5)"
  else record P3 unknown "no subagent started (model did not spawn; see $LOGS/P3.out)" "the spawn_agent argument names may differ"; fi
}
p_P4() {
  role_run P4 probe-worker
  local n s
  n=$(cnt P4 '"agent_type": *"probe-worker"'); s=$(cnt P4 '^SubagentStart')
  if [ "$n" -gt 0 ]; then record P4 pass "agent_type probe-worker observed (hyphen kept)" "U2: keep hyphenated names"
  elif [ "$s" -gt 0 ]; then record P4 fail "subagent started but agent_type is: $(vals P4 '"agent_type": *"[^"]*"')" "U2 fallback: map - to _ (INTERFACES role_name_style)"
  else
    ask "Did spawn_agent report an error about the role name probe-worker (not found / invalid)?"
    if [ "$ANS" = y ]; then record P4 fail "spawn rejected the hyphenated role" "U2 fallback: map - to _"
    else record P4 unknown "no subagent started and no confirmed role error (see $LOGS/P4.out)" ""; fi
  fi
}
p_P5() {
  role_run P5 probe_worker
  local t s
  t=$(cnt P5 '^SubagentStop.*PROBE-ROLE-OK'); s=$(cnt P5 '^SubagentStop')
  if [ "$t" -gt 0 ] || grep -qs 'PROBE-ROLE-OK' "$LOGS/P5.out"; then record P5 pass "role file instructions applied (PROBE-ROLE-OK seen)" "config_file role layer works"
  elif [ "$s" -gt 0 ]; then
    ask "Did the subagent's reply start with PROBE-ROLE-OK?"
    case "$ANS" in y) record P5 pass "user confirmed PROBE-ROLE-OK" "";; n) record P5 fail "subagent ran without the role's developer_instructions" "";; *) record P5 unknown "SubagentStop seen, token not found, no answer" "";; esac
  else record P5 unknown "no subagent stopped" ""; fi
}
p_P6() {
  ensure_trust
  prompt P6 <<'T'
Call the MCP tool probe_echo (server probe_echo) with text hello-p6 and tell me what it returned. Do not run shell commands.
T
  rm -f "$LOGS/mcp.log" 2>/dev/null || true
  codex_exec P6 probe "$ROOT/prompts/P6.txt" P6.out; wait_enter
  local init=0 lst=0 call=0
  if [ -f "$LOGS/mcp.log" ]; then
    grep -q 'method=initialize' "$LOGS/mcp.log" && init=1 || true
    grep -q 'method=tools/list' "$LOGS/mcp.log" && lst=1 || true
    grep -q 'tools/call text=hello-p6' "$LOGS/mcp.log" && call=1 || true
  fi
  local names; names=$(vals P6 '"tool_name": *"[^"]*mcp[^"]*"')
  if [ "$call" = 1 ]; then record P6 pass "server started, listed and was called; hook tool_name: ${names:-none}" "MCP tool_name shape for the guard allowlist"
  elif [ "$init" = 1 ]; then record P6 pass "server started (initialize=$init tools/list=$lst) but the model did not call it" "loaded; call not observed"
  elif [ ! -s "$LOGS/P6.out" ]; then record P6 unknown "no captured output: the run did not happen or produced nothing (login?)" ""
  else record P6 fail "mcp.log has no initialize: profile [mcp_servers] did not load (python3 on PATH? run P1 first)" ""; fi
}

p_P7() {
  ensure_trust
  rm -f "$CH/p7-write-test" "$WORK/p7-ws"
  [ -f "$CH/auth.json" ] || say "  note: no auth.json in the scratch home (not logged in): the auth.json read check will be 'unknown'."
  prompt P7 <<T
Run these four shell commands separately, one tool call each, and report each exit status and output:
1. head -c 1 $CH/config.toml | wc -c
2. touch $CH/p7-write-test
3. head -c 8 $CH/auth.json 2>&1 | wc -c
4. touch $WORK/p7-ws
Do not try to work around any failure.
T
  say "  Run with the permission profile:"
  codex_exec P7 probe-perm "$ROOT/prompts/P7.txt" P7.out; wait_enter
  local ws=no wr=no
  [ -e "$WORK/p7-ws" ] && ws=yes || true
  [ -e "$CH/p7-write-test" ] && wr=yes || true
  if [ "$ws" = no ]; then record P7 unknown "control failed: workspace write p7-ws not created (profile not applied, or run did not happen)" "see $LOGS/P7.out"; return; fi
  local rd=u
  if [ -f "$CH/auth.json" ]; then
    ask "Did command 3 (head -c 8 auth.json | wc -c) print 0, i.e. auth.json was NOT readable?"; rd=$ANS
  fi
  ask "Did command 1 print 1, i.e. CODEX_HOME config.toml WAS readable?"; local rc=$ANS
  local ev="CODEX_HOME write created=$wr (must be no); auth.json unreadable=$rd; CODEX_HOME readable=$rc; workspace write=$ws"
  if [ "$wr" = no ] && [ "$rd" = y ] && [ "$rc" = y ]; then record P7 pass "$ev" "U5 settled: explicit read entry holds and auth.json deny outranks it"
  elif [ "$wr" = yes ] || [ "$rd" = n ] || [ "$rc" = n ]; then record P7 fail "$ev" "U5 negative: use the guard (apply_patch + shell path checks) as the primary control"
  else record P7 unknown "$ev" ""; fi
}

p_P7b() {
  ensure_trust
  prompt P7b <<T
Run this shell command and report its exit status and output:
git -C $WORK -c user.name=p -c user.email=p@example.invalid commit --allow-empty -m p7b-commit
Do not try to work around any failure.
T
  codex_exec P7b probe-git "$ROOT/prompts/P7b.txt" P7b.out; wait_enter
  if git -C "$WORK" log --format=%s 2>/dev/null | grep -q '^p7b-commit$'; then record P7b pass "commit p7b-commit exists: .git writable in the permission profile" "U6: git policy can allow in-sandbox commits (DESIGN 4.3)"
  else
    ask "Did Codex report the commit failed (permission denied / read-only .git)?"
    if [ "$ANS" = y ]; then record P7b fail ".git write grant not honoured" "U6: commits need an unsandboxed escalation path (DESIGN 4.3 fallback)"
    else record P7b unknown "no commit and no confirmed failure (see $LOGS/P7b.out)" ""; fi
  fi
}

p_P8() {
  ensure_trust
  putf "$CH/rules/probe.rules" < "$FIX/probe.rules"
  git -C "$WORK" -c user.name=p -c user.email=p@example.invalid commit -q --allow-empty -m p8-base 2>/dev/null || true
  prompt P8 <<T
Run exactly this shell command once and report the result: git push probe-origin HEAD:main
Do not try any other way of pushing.
T
  say "  Optional rule check first (parses the rules file, no network):"
  cmd "$ENVP codex execpolicy check --rules $CH/rules/probe.rules -- git push probe-origin HEAD:main"
  codex_exec P8 probe-git "$ROOT/prompts/P8.txt" P8.out; wait_enter
  local pushed=no attempted=u
  git --git-dir="$ROOT/remote.git" rev-parse --verify -q refs/heads/main >/dev/null 2>&1 && pushed=yes || true
  if [ "$pushed" = yes ]; then record P8 fail "the push reached $ROOT/remote.git: forbidden rule did not block" "prefix_rule forbidden is not enforced for in-sandbox git; keep the guard hook as the control"; return; fi
  ask "Did Codex attempt the push and report it blocked/forbidden by a rule (not a network or other error)?"
  case "$ANS" in y) record P8 pass "remote has no refs; blocked by rule (user-confirmed)" "forbidden rules hold";;
    n) record P8 unknown "remote has no refs but the block was not attributed to the rule" "see $LOGS/P8.out";;
    *) record P8 unknown "remote has no refs; attribution unanswered" "";; esac
}

p_P9() {
  ensure_trust
  rm -f "$ROOT"/outside/hook-wrote-* 2>/dev/null || true
  prompt P9 <<'T'
Run the shell command: echo p9
Then reply with the single word done.
T
  say "  Run under the permission profile (sandboxed shell, restricted filesystem); the hook itself tries to write outside it and read auth.json:"
  codex_exec P9 probe-perm "$ROOT/prompts/P9.txt" P9.out; wait_enter
  local w r
  w=$(sect P9 | grep -c '^#meta .*write_outside=ok' || true); r=$(sect P9 | grep -c '^#meta .*read_auth=ok' || true)
  if ls "$ROOT"/outside/hook-wrote-* >/dev/null 2>&1; then
    record P9 pass "hook wrote outside the sandbox roots ($w meta lines write_outside=ok; read_auth=ok in $r)" "U3: hooks are unsandboxed; guard state dir needs no sandbox grant"
  elif [ "$(cnt P9 '^#meta')" -gt 0 ]; then record P9 fail "hook ran but could not write outside (write_outside=fail)" "U3: hooks are sandboxed; grant the guard state dir in the permission profile"
  else record P9 unknown "no hook ran (untrusted, or P7 control also fails)" ""; fi
}

p_P10() {
  ensure_trust
  copyf "$FIX/skills/probe-skill/SKILL.md" "$ROOT/skill-src/probe-skill/SKILL.md"
  ln -sfn "$ROOT/skill-src/probe-skill" "$SKILLS/probe-skill"; emit_note "$SKILLS/probe-skill -> $ROOT/skill-src/probe-skill (symlink)"
  prompt P10 <<'T'
List the exact names of all skills available to you whose name starts with probe-. Reply with the names only, or the word none.
T
  codex_exec P10 probe "$ROOT/prompts/P10.txt" P10.out; wait_enter
  if grep -qs 'probe-skill' "$LOGS/P10.out"; then record P10 pass "probe-skill listed through the symlinked folder" "F5: symlinked skills followed"
  else
    ask "Does /skills (or the model's reply) list probe-skill?"
    case "$ANS" in y) record P10 pass "user confirmed" "";; n) record P10 fail "symlinked skill folder not listed" "installer must copy skill folders instead of linking";; *) record P10 unknown "not in the captured output (note: the first line of a reply may be cut by tee)" "";; esac
  fi
}

p_P11() {
  say "  Manual (IDE extension). Hooks go in config.toml itself (the --ide-default shape) so no profile is involved."
  local keep=$CH/config.toml.pre-p11
  cp "$CH/config.toml" "$keep"
  render_cat "$CH/config.toml" "$FIX/config.p11.toml" "$FIX/hooks.snippet.toml"
  mark P11/cli
  step 1 "trust from the CLI, no --profile"; cmd "$ENVP codex -C $WORK"
  step 2 "type /hooks, trust all hooks, quit (keys now in config.toml hooks.state)"
  wait_enter
  mark P11/ide
  step 3 "start the IDE extension with the same scratch env (VS Code example), open $WORK, log in inside it if asked, start a chat and ask: run echo p11"
  cmd "$ENVP code -n $WORK"
  step 4 "note whether the extension shows its own hook-review/trust prompt, then close it"
  wait_enter
  local n; n=$(cnt P11/ide '^PreToolUse')
  ask "Did the IDE show its OWN hook-review prompt (asked to trust the hooks again)?"; local prompted=$ANS
  if [ "$n" -gt 0 ] && [ "$prompted" = n ]; then record P11 pass "IDE fired $n PreToolUse hooks from trust written by the CLI, no extra prompt" "U9: sharing hooks.state works"
  elif [ "$n" -gt 0 ]; then record P11 pass "IDE fired $n hooks; own prompt shown=$prompted" "U9: trust shared, IDE prompt: $prompted"
  elif [ "$prompted" = y ]; then record P11 fail "IDE did not run the hooks without its own review" "U9: IDE needs its own trust step; document it"
  else record P11 unknown "no IDE hook lines (IDE not started with the scratch env, or not logged in)" "manual probe"; fi
  mv "$keep" "$CH/config.toml"; say "  config.toml restored to the base file (hooks.state records written meanwhile are lost with it)."
}

p_P12() {
  local keep=$CH/config.toml.pre-p12 ref=$ROOT/p12.ref
  cp "$CH/config.toml" "$keep"
  render_cat "$ref.a" "$FIX/config.p12.toml" "$FIX/hooks.snippet.toml"
  { cat "$ref.a"; echo "# <<< claude-agent-stack: end B <<<"; } > "$ref"; rm -f "$ref.a"
  cp "$ref" "$CH/config.toml"; emit_note "$CH/config.toml (stack regions A and B, comments)"
  say "  Codex rewrites this file now:"
  step 1 "start the CLI, no profile"; cmd "$ENVP codex -C $WORK"
  step 2 "answer the project-trust question for $WORK if asked (trust it)"
  step 3 "type /hooks and trust every hook in region B"
  step 4 "type /model, pick any model (and effort) and confirm; then quit"
  wait_enter
  local f=$CH/config.toml marks comm regionA regionB outside
  marks=$(grep -Ec '^# (>>>|<<<) claude-agent-stack' "$f" || true)
  comm=$(grep -Ec 'user comment above|stack comment inside|user comment between' "$f" || true)
  regionA=same; regionB=same
  awk '/begin A/{on=1} on{print} /end A/{on=0}' "$f" > "$ROOT/p12.A.now"; awk '/begin A/{on=1} on{print} /end A/{on=0}' "$ref" > "$ROOT/p12.A.ref"
  awk '/begin B/{on=1} on{print} /end B/{on=0}' "$f" > "$ROOT/p12.B.now"; awk '/begin B/{on=1} on{print} /end B/{on=0}' "$ref" > "$ROOT/p12.B.ref"
  cmp -s "$ROOT/p12.A.now" "$ROOT/p12.A.ref" || regionA=CHANGED
  cmp -s "$ROOT/p12.B.now" "$ROOT/p12.B.ref" || regionB=CHANGED
  outside=$(awk '/begin [AB]/{on=1} !on{print} /end [AB]/{on=0}' "$f" | grep -E '^\[(hooks\.state|projects)|^model *=' | tr '\n' ' ' || true)
  local ev="markers=$marks (want 4) comments=$comm (want 3) regionA=$regionA regionB=$regionB; new keys outside regions: ${outside:-none}"
  if [ "$marks" = 4 ] && [ "$comm" = 3 ] && [ "$regionA" = same ] && [ "$regionB" = same ] && [ -n "$outside" ]; then record P12 pass "$ev" "U13: writes keep comments and land outside the regions"
  elif [ -z "$outside" ]; then record P12 unknown "$ev" "Codex wrote nothing recognisable: did /hooks, /model and project trust complete?"
  else record P12 fail "$ev" "U13 negative: rely on the drift check (DESIGN 7.6), expect re-render after Codex writes"; fi
  cp "$f" "$ROOT/p12.after.toml"; say "  kept the rewritten file as $ROOT/p12.after.toml"
  mv "$keep" "$CH/config.toml"
}

p_P13() {
  ensure_trust
  prompt P13 <<'T'
Call each of these tools once, in this order, with minimal valid arguments, and ignore failures (continue with the next):
spawn_agent (role probe_worker, message: reply with the word hi), wait_agent, send_input (to that agent, message: hi again), resume_agent, close_agent,
update_plan (a one-step plan), request_user_input (ask one yes/no question), view_image (path pixel.png in the working directory).
Reply with the word done at the end.
T
  codex_exec P13 probe "$ROOT/prompts/P13.txt" P13.out; wait_enter
  local names t missing=""
  names=$(sect P13 | grep '^PreToolUse' | grep -Eo '"tool_name": *"[^"]*"' | sed 's/.*: *"//; s/"$//' | sort -u | tr '\n' ' ' || true)
  for t in spawn_agent wait_agent send_input resume_agent close_agent update_plan request_user_input view_image; do
    case "$names" in *"$t"*) ;; *) missing="$missing $t";; esac
  done
  local nx; nx=$(echo "$names" | tr ' ' '\n' | grep -vc '^$' || true)
  local note="U10: matcher .* matched $nx distinct tool names; U11: tools the model called but absent here opt out of hooks"
  if [ -z "$missing" ]; then record P13 pass "tool_names seen: $names" "$note"
  elif [ -n "$names" ]; then record P13 unknown "seen: $names; not seen:$missing (model may not have called them, or they bypass hooks: check $LOGS/P13.out)" "$note"
  else record P13 unknown "no PreToolUse lines at all" "$note"; fi
}

# ---------------------------------------------------------------- report
json_str() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' | tr '\t\n\r' '   '; }
write_report() {
  local first=1 id r e n
  {
    printf '{\n  "meta": {"codex_version": "%s", "scratch_root": "%s", "date": "%s"},\n  "probes": {\n' \
      "$(json_str "${CODEX_VERSION:-unknown}")" "$(json_str "$ROOT")" "$(date '+%F %R')"
    for id in $IDS; do
      line=$(awk -F'\t' -v id="$id" '$1==id{l=$0} END{print l}' "$RES")
      [ -n "$line" ] || continue
      r=$(echo "$line" | cut -f2); e=$(echo "$line" | cut -f3); n=$(echo "$line" | cut -f4)
      [ "$first" = 1 ] || printf ',\n'; first=0
      printf '    "%s": {"result": "%s", "evidence": "%s", "notes": "%s"}' "$id" "$r" "$(json_str "$e")" "$(json_str "$n")"
    done
    printf '\n  }\n}\n'
  } > "$REPORT"
}

# ---------------------------------------------------------------- main
say "Codex Phase 0 probe kit (mode: $MODE)"
setup_base
preamble
if [ -n "$ONLY" ]; then run_ids=$ONLY; else run_ids=$ORDER; fi
for id in $run_ids; do
  say "== $id: $(title_of "$id")"
  "p_$id"
  say
done
if interactive; then
  write_report
  say "Report: $REPORT"
  say "Paste it back (it holds no credentials). Scratch root: $ROOT (delete it when done)."
  say "Still untested here: U7 (omit_tools_from), U8: Phase 5 smoke covers them."
else
  say "Dry run finished: no codex session was started; nothing was written outside the removed temp dir."
fi
