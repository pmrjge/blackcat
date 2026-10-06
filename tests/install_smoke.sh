#!/usr/bin/env bash
# Smoke test for install.sh. Hermetic: a fake `claude` (tests/fake-claude/claude) is put first on
# PATH, every run uses a scratch CLAUDE_CONFIG_DIR and a scratch MCP config (FAKE_CLAUDE_JSON /
# STACK_CLAUDE_JSON), plus --no-deps --no-profile. As a belt-and-braces check the real
# $HOME/.claude, ~/.claude.json and ~/.zshrc are fingerprinted before and after.
set -uo pipefail
# No controlling terminal (install.sh asks on /dev/tty when it has one): the cases that need one make
# their own pty; nothing waits on the terminal you run this from.
if [ -z "${SMOKE_NO_CTTY:-}" ] && { : </dev/tty; } 2>/dev/null; then
  exec env SMOKE_NO_CTTY=1 python3 - "$0" "$@" <<'PY'
import os, signal, subprocess, sys
p = subprocess.Popen(["bash"] + sys.argv[1:], stdin=subprocess.DEVNULL, start_new_session=True)
try:
    sys.exit(p.wait())
except KeyboardInterrupt:
    os.killpg(p.pid, signal.SIGTERM)
    sys.exit(130)
PY
fi

SRC_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# install.sh runs only from the main branch of a git checkout and fast-forwards main when started
# anywhere else, so the test never runs it from this checkout: it snapshots the working tree
# (tracked and untracked files, not ignored ones) into a scratch repository on main and installs
# from there. No git command in this test talks to a remote other than scratch ones.
tgit(){ GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null -c commit.gpgsign=false -c init.defaultBranch=main \
  -c user.name=smoke -c user.email=smoke@example.invalid "$@" </dev/null; }
# a fresh scratch directory, physical path; aborts instead of falling back to the current directory
scratch_dir(){ local d; d="$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && [ -d "$d" ] && (cd "$d" && pwd -P) || { echo "mktemp -d failed" >&2; exit 1; }; }
# remove a directory only if it is one of this test's scratch directories
drop_scratch(){ case "$1" in */tmp.*) [ -d "$1" ] && rm -rf -- "$1" ;; esac; }
SCRATCH_ROOT="$(scratch_dir)" || exit 1
# install.sh keeps its backups in ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups and the
# guard its state next to it: every scratch install of this test writes both under the scratch root.
REAL_BK_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack-backups"
export XDG_STATE_HOME="$SCRATCH_ROOT/state"
# Run from a sandboxed Claude Code shell, the cache variables name ~/.cache/claude-sandbox, which
# install.sh drops (CWE-427); uv would then fall back to ~/.cache/uv, which the sandbox can't write.
# The smoke drops them too and gives uv a scratch cache (a plain terminal run sets none of them).
for v in $(compgen -e); do
  [ "$v" = PATH ] || case "${!v}" in *"$HOME/.cache/claude-sandbox"*)
    unset "$v"; [ "$v" = UV_CACHE_DIR ] && export UV_CACHE_DIR="$SCRATCH_ROOT/uv-cache" ;; esac
done
BK_ROOT="$XDG_STATE_HOME/claude-agent-stack-backups"
HERE="$SCRATCH_ROOT/claude-agent-stack"
python3 - "$SRC_REPO" "$HERE" <<'PY'
import os, shutil, subprocess, sys
src, dst = sys.argv[1:3]
out = subprocess.run(["git", "-C", src, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                     stdout=subprocess.PIPE, check=True).stdout.decode()
for rel in filter(None, out.split("\0")):
    s = os.path.join(src, rel)
    if not os.path.lexists(s):          # deleted in the working tree
        continue
    d = os.path.join(dst, rel)
    os.makedirs(os.path.dirname(d), exist_ok=True)
    shutil.copy2(s, d, follow_symlinks=False)
PY
# gc.auto 0, maintenance.auto false: no detached auto maintenance packs the loose objects while install.sh's git fsck reads them
tgit -C "$HERE" init -q && tgit -C "$HERE" config gc.auto 0 && tgit -C "$HERE" config maintenance.auto false \
  && tgit -C "$HERE" add -A && tgit -C "$HERE" commit -q -m "smoke snapshot" \
  || { echo "could not build the scratch stack repository"; exit 1; }
INSTALL="$HERE/install.sh"
# The installer links uv's managed Python 3.13 as bin/stack-python (S2); the cases that run it with a
# scratch HOME would hide uv's Pythons (and a real run would download one): point uv at the real dir.
if [ -z "${UV_PYTHON_INSTALL_DIR:-}" ] && command -v uv >/dev/null 2>&1; then
  UV_PYTHON_INSTALL_DIR="$(uv python dir 2>/dev/null || true)"; [ -n "$UV_PYTHON_INSTALL_DIR" ] && export UV_PYTHON_INSTALL_DIR
fi
export PATH="$HERE/tests/fake-claude:$PATH"
# install.sh is macOS-only; this test also runs on Linux (CI, containers) through its escape hatch.
export STACK_ALLOW_NON_MACOS=1
# Run from a Claude Code session with the stack installed, STACK_ENV_FILE points at the real
# stack.env: the scratch installs' mcp-headers would serve (and a failure would print) a real key.
# Unset it, and every real credential this session's own environment might carry, so a scratch
# install's helpers only ever see the fake keys this test writes into its own scratch stack.env.
unset STACK_ENV_FILE
unset EXA_API_KEY JINA_API_KEY HF_TOKEN WANDB_API_KEY OPENROUTER_API_KEY OPPER_API_KEY \
      SPIDER_API_KEY GITHUB_TOKEN GH_TOKEN
unset HF_HOME HF_TOKEN_PATH XDG_CACHE_HOME
PASS=0
FAIL=0
pass(){ printf '  PASS  %s\n' "$*"; PASS=$((PASS + 1)); }
failed(){ printf '  FAIL  %s\n' "$*"; FAIL=$((FAIL + 1)); }
sha(){ if command -v shasum >/dev/null 2>&1; then shasum -a 256 "$@"; else sha256sum "$@"; fi; }
# A key-bearing helper's raw stdout must never land in this test's own output (even a fake,
# scratch-only key): summarize it as a length + short hash instead.
redacted(){ printf 'len=%d sha256=%s' "${#1}" "$(printf '%s' "$1" | sha | cut -d' ' -f1 | cut -c1-16)"; }
# GNU stat reads -f as "file system status", so pick the dialect once.
if stat -c '%n' / >/dev/null 2>&1; then
  fstat(){ stat -c '%n %s %Y' "$1" 2>/dev/null; }
else
  fstat(){ stat -f '%N %z %m' "$1" 2>/dev/null; }
fi

hash_tree() {
  # Fingerprint only what install.sh could ever write (CLAUDE.md, settings.json, agents/, rules/,
  # skills/, hooks/, bin/, mcp/, magg/, stack.env, .stack-manifest.json, venvs/, stack-plugins/, backup-*), not
  # Claude Code's own live state under the real ~/.claude, which changes constantly.
  local p="$1"
  if [ -d "$p" ]; then
    (
      cd "$p" 2>/dev/null || exit 0
      for entry in CLAUDE.md settings.json stack.env .stack-manifest.json agents rules skills hooks bin mcp magg venvs stack-plugins; do
        [ -e "$entry" ] || continue
        find "$entry" -maxdepth 2 2>/dev/null | while IFS= read -r f; do fstat "$f"; done
      done
      find . -maxdepth 1 -name 'backup-*' 2>/dev/null
    ) | sort | sha | awk '{print $1}'
  elif [ -f "$p" ]; then
    sha "$p" 2>/dev/null | awk '{print $1}'
  else
    echo "absent"
  fi
}

# ~/.claude.json: only the MCP entries (user scope and per project), what `claude mcp` from an install
# could change. Every running Claude Code session rewrites the rest of the file (counters, caches),
# so a whole-file hash fails whenever another session is active during the run.
cj_digest(){ [ -f "$1" ] || { echo absent; return; }
  python3 -c 'import hashlib, json, sys, time
for _ in range(5):
    try:
        d = json.load(open(sys.argv[1]))
        break
    except ValueError:
        time.sleep(0.2)                      # caught mid-write by a live session
else:
    print("unreadable"); sys.exit(0)
keep = {"mcpServers": d.get("mcpServers"),
        "projects": {k: v.get("mcpServers") for k, v in sorted((d.get("projects") or {}).items())
                     if isinstance(v, dict) and v.get("mcpServers")}}
print(hashlib.sha256(json.dumps(keep, sort_keys=True).encode()).hexdigest())' "$1"; }
REAL_CLAUDE_HASH_BEFORE="$(hash_tree "$HOME/.claude")"
REAL_CJ_HASH_BEFORE="$(cj_digest "$HOME/.claude.json")"
REAL_ZSHRC_HASH_BEFORE="$(hash_tree "$HOME/.zshrc")"
real_backups(){ ls -1A "$REAL_BK_ROOT" 2>/dev/null | sha | awk '{print $1}'; }
REAL_BK_BEFORE="$(real_backups)"

assert_unchanged_real_home() {
  [ "$(hash_tree "$HOME/.claude")" = "$REAL_CLAUDE_HASH_BEFORE" ] && pass "real \$HOME/.claude unchanged" \
    || failed "real \$HOME/.claude CHANGED"
  [ "$(cj_digest "$HOME/.claude.json")" = "$REAL_CJ_HASH_BEFORE" ] && pass "real ~/.claude.json MCP entries unchanged" \
    || failed "real ~/.claude.json MCP entries CHANGED"
  [ "$(hash_tree "$HOME/.zshrc")" = "$REAL_ZSHRC_HASH_BEFORE" ] && pass "real ~/.zshrc unchanged" \
    || failed "real ~/.zshrc CHANGED"
  [ "$(real_backups)" = "$REAL_BK_BEFORE" ] && pass "real installer backups ($REAL_BK_ROOT) unchanged" \
    || failed "real installer backups CHANGED: $REAL_BK_ROOT"
}
# the newest backup install.sh made of config dir $1 ("" when none), and how many it has
latest_backup(){ python3 -B "$HERE/lib/install_state.py" latest "$1" "$BK_ROOT"; }
count_backups(){ python3 -B -c 'import sys; sys.path.insert(0, sys.argv[1]); import install_state as st
print(len(st.backups_of(sys.argv[2], sys.argv[3])))' "$HERE/lib" "$1" "$BK_ROOT"; }
fmode(){ python3 -c 'import os, sys; print(oct(os.lstat(sys.argv[1]).st_mode & 0o777))' "$1"; }

EXPECTED_AGENTS=$(ls "$HERE"/dot-claude/agents/*.md | wc -l | tr -d ' ')
EXPECTED_SKILLS=$(ls -d "$HERE"/dot-claude/skills/*/ | wc -l | tr -d ' ')

echo "== 1. Fresh install into a scratch CLAUDE_CONFIG_DIR"
T1="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
export FAKE_CLAUDE_JSON="$T1/fake-claude.json" STACK_CLAUDE_JSON="$T1/fake-claude.json"
if CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install.log" 2>&1; then
  pass "install.sh exits 0"
else
  failed "install.sh exited non-zero (see $T1/.install.log)"
  tail -n 40 "$T1/.install.log"
fi

n=$(ls "$T1"/agents/*.md 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = "$EXPECTED_AGENTS" ] && pass "$n agent files installed" || failed "expected $EXPECTED_AGENTS agent files, got $n"
n=$(ls -d "$T1"/skills/*/ 2>/dev/null | wc -l | tr -d ' ')
[ "$n" = "$EXPECTED_SKILLS" ] && pass "$n skills installed" || failed "expected $EXPECTED_SKILLS skills, got $n"
grep -q "$EXPECTED_AGENTS/$EXPECTED_AGENTS agents installed" "$T1/.install.log" && pass "installer reports $EXPECTED_AGENTS/$EXPECTED_AGENTS agents" \
  || failed "installer did not report $EXPECTED_AGENTS/$EXPECTED_AGENTS agents"

if grep -rlE '__[A-Z_]+__' "$T1"/agents "$T1"/rules "$T1"/skills "$T1/settings.json" "$T1/magg/config.json" 2>/dev/null | grep -v '/synced/' >/dev/null; then
  failed "unresolved __PLACEHOLDER__ left in installed files: $(grep -rlE '__[A-Z_]+__' "$T1"/agents "$T1"/rules "$T1"/skills "$T1/settings.json" "$T1/magg/config.json" 2>/dev/null | tr '\n' ' ')"
else
  pass "no unresolved placeholders"
fi
[ -f "$T1/magg/k8s-mcp.toml" ] && pass "magg/k8s-mcp.toml installed" || failed "magg/k8s-mcp.toml not installed"
# a fresh install creates CLAUDE.md holding only the stack's block (lib/claude_md_block.py): one begin
# and one end marker line around the rendered dot-claude/CLAUDE.block.md, nothing else
[ -f "$T1/rules/claude-agent-stack.md" ] && [ "$(grep -c '^<!-- claude-agent-stack: begin ' "$T1/CLAUDE.md" 2>/dev/null)" = 1 ] \
  && [ "$(sed -n '$p' "$T1/CLAUDE.md")" = '<!-- claude-agent-stack: end -->' ] && grep -qF "$HERE" "$T1/CLAUDE.md" \
  && ! grep -qE '__[A-Z_]+__' "$T1/CLAUDE.md" && grep -qE '^  CLAUDE.md \(the stack.s block\) +created$' "$T1/.install.log" \
  && pass "global rules installed as rules/claude-agent-stack.md; CLAUDE.md created with only the stack's block" \
  || failed "rules/claude-agent-stack.md missing, or CLAUDE.md is not exactly the stack's block"
grep -qF "$HERE" "$T1/agents/claude-code-engineer.md" && grep -qF "\"repo\": \"$HERE\"" "$T1/.stack-manifest.json" \
  && pass "stack repo path rendered into agents and recorded in the manifest" || failed "stack repo path not rendered/recorded"

grep -qF "/bin/sh \\\"$T1/bin/stack-hook\\\" --fail-closed agent_guard no-push" "$T1/settings.json" 2>/dev/null \
  && pass "settings.json hook commands run \$T/bin/stack-hook (fail-closed guard entries)" \
  || failed "settings.json hook commands do not run $T1/bin/stack-hook"
grep -qF "$T1/bin/stack-hook\\\" --fail-closed agent_guard blackcat-guard" "$T1/agents/blackcat.md" 2>/dev/null && pass "blackcat.md hook runs \$T/bin/stack-hook --fail-closed agent_guard blackcat-guard" \
  || failed "blackcat.md hook command does not run $T1/bin/stack-hook --fail-closed agent_guard blackcat-guard"
[ -x "$T1/bin/stack-python" ] && "$T1/bin/stack-python" -c 'import sys; sys.exit(sys.version_info < (3, 13))' \
  && [ -f "$T1/hooks/__pycache__/agent_guard.$("$T1/bin/stack-python" -c 'import sys; print(sys.implementation.cache_tag)').pyc" ] \
  && pass "bin/stack-python is Python >= 3.13 and the guard's bytecode is precompiled" \
  || failed "bin/stack-python missing/old or hooks/__pycache__ not compiled"
python3 - "$T1/settings.json" "$T1/agents/blackcat.md" <<'PY' && pass "hooks and status line use an absolute interpreter (no bare python3)" || failed "a hook command uses a bare interpreter"
import json, re, sys
s = json.load(open(sys.argv[1]))
cmds = [h["command"] for gs in s["hooks"].values() for g in gs for h in g["hooks"]]
cmds.append(s["statusLine"]["command"])
cmds += [json.loads('"%s"' % c) for c in re.findall(r'(?m)^\s+command:\s*"(.*agent_guard.*)"', open(sys.argv[2]).read())]
bad = [c for c in cmds if not c.lstrip('\\"').startswith("/")]
if bad:
    print("  bare:", bad)
sys.exit(1 if bad else 0)
PY
python3 - "$T1/settings.json" <<'PY' && pass "settings: StopFailure + PreCompact + TaskStop wiring, narrowed magg allow, Exa-safe denies, no-push wiring" || failed "settings wiring/permissions (see above)"
import json, os, sys
s = json.load(open(sys.argv[1]))
h, allow, deny = s["hooks"], s["permissions"]["allow"], s["permissions"]["deny"]
checks = {
    "StopFailure hook": any("agent_guard" in json.dumps(g) for g in h.get("StopFailure", [])),
    "PreCompact hook + SessionStart compact": any("agent_guard" in json.dumps(g) for g in h.get("PreCompact", []))
                                              and any("compact" in str(g.get("matcher") or "").split("|")
                                                      for g in h["SessionStart"]),
    "PostToolUse TaskStop": any("TaskStop" in (g.get("matcher") or "") for g in h["PostToolUse"]),
    "no blanket mcp__magg": "mcp__magg" not in allow,
    "magg catalog tools allowed": "mcp__magg__docling_*" in allow and "mcp__magg__arxiv_*" in allow,
    "magg enable/duckdb/jupyter/ros/qiskit ask": {"mcp__magg__magg_enable_server", "mcp__magg__duckdb_*",
                                       "mcp__magg__jupyter_*", "mcp__magg__ros_*",
                                       "mcp__magg__qiskit_*", "mcp__magg__docspace_*"} <= set(s["permissions"]["ask"]) and
                                      "mcp__magg__magg_enable_server" not in allow,
    "sandbox caches Bash-only": not any(k in s["env"] for k in ("UV_CACHE_DIR", "npm_config_cache",
                                        "PRE_COMMIT_HOME", "GIT_CONFIG_COUNT", "GIT_CONFIG_KEY_0")) and
                                s["sandbox"]["filesystem"]["allowWrite"] == ["~/.cache/claude-sandbox"] and
                                any(not g.get("matcher") and any(x.get("command", "").startswith('/bin/sh "/') and
                                    x["command"].endswith('/bin/stack-hook" agent_guard session-env')
                                    for x in g["hooks"]) for g in h["SessionStart"]),
    "MCP cache is denyWrite": any(p.endswith("/claude-agent-stack-cache") and p.startswith("/")
                                  for p in s["sandbox"]["filesystem"]["denyWrite"]),
    # R3-STATE: the guard's state dir where the guard keeps it ($XDG_STATE_HOME), not ~/.local/state
    "guard state dir protected at $XDG_STATE_HOME": (
        os.environ["XDG_STATE_HOME"] + "/claude-agent-stack" in s["sandbox"]["filesystem"]["denyWrite"]
        and "Edit(/" + os.environ["XDG_STATE_HOME"] + "/claude-agent-stack/**)" in deny
        and ".local/state" not in json.dumps([s["sandbox"], deny])),
    "failIfUnavailable": s["sandbox"].get("failIfUnavailable") is True,
    "config .claude.json read-deny": any(r.endswith("/.claude.json)") and r.startswith("Read(//") for r in deny),
    "local-file MCP guard": any("ctx_index" in (g.get("matcher") or "") and "agent_guard" in json.dumps(g)
                                for g in h["PreToolUse"]),
    "context-mode exec denied": {"mcp__context-mode__ctx_execute", "mcp__context-mode__ctx_batch_execute"} <= set(deny),
    "neural-memory allowed": "mcp__neural-memory" in allow and "mcp__context-mode__ctx_search" in allow,
    "no-push hook unfiltered on Bash|Monitor": any(
        "no-push" in json.dumps(g) and {"Bash", "Monitor"} <= set((g.get("matcher") or "").split("|"))
        and not any(x.get("if") for x in g["hooks"]) for g in h["PreToolUse"]),
    "push and forge-write denies": {"Bash(git push *)", "Bash(gh pr create *)", "Bash(gh pr merge *)",
                                    "Bash(tea pulls merge *)", "Bash(fj pr merge *)"} <= set(deny),
}
bad = [k for k, v in checks.items() if not v]
if bad:
    print("  settings mismatch: " + ", ".join(bad))
sys.exit(1 if bad else 0)
PY
grep -q "Read(/$T1/stack.env)" "$T1/settings.json" 2>/dev/null && pass "deny rule contains Read(//\$T/stack.env)" \
  || failed "settings.json deny list missing Read(//$T1/stack.env)"
for f in doctor.sh with-stack-env mcp-headers magg-private statusline.py claude-ultracode stack_sdk.py; do
  [ -x "$T1/bin/$f" ] && pass "bin/$f installed and executable" || failed "bin/$f missing or not executable"
done
python3 - "$T1" <<'PY' && pass "skills are dynamic: no agent preloads one, every agent has Skill, one Skill allow rule" || failed "skills still tied to agents (see above)"
import glob, json, os, re, sys
t = sys.argv[1]
bad = []
for f in glob.glob(os.path.join(t, "agents", "*.md")):
    head = open(f).read().split("\n---\n", 1)[0]
    if re.search(r"(?m)^skills:", head) or not re.search(r"(?m)^tools:.*\bSkill\b", head):
        bad.append(os.path.basename(f))
allow = json.load(open(os.path.join(t, "settings.json")))["permissions"]["allow"]
if "Skill" not in allow or any(r.startswith("Skill(") for r in allow):
    bad.append("settings.json allow: %s" % [r for r in allow if r.startswith("Skill")])
if bad:
    print("  " + ", ".join(bad))
sys.exit(1 if bad else 0)
PY
for f in libdocs_mcp.py image_studio_mcp.py neural_memory_mcp.py; do
  [ -f "$T1/mcp/$f" ] && pass "mcp/$f installed" || failed "mcp/$f missing"
done
[ ! -e "$T1/mcp/openrouter_image_mcp.py" ] && [ ! -e "$T1/mcp/opper_image_mcp.py" ] \
  && pass "no older image server installed" || failed "an older image server was installed"
grep -q "$T1/mcp/image_studio_mcp.py" "$T1/agents/image-director.md" && grep -q "$T1/mcp/image_studio_mcp.py" "$T1/agents/designer.md" \
  && ! grep -rqE "opper_image_mcp|openrouter_image_mcp|openrouter-image|opper-image" "$T1/agents" "$T1/settings.json" \
  && pass "image-studio rendered into image-director and designer; no older image server left" \
  || failed "image-studio not rendered, or an older image server still referenced"
grep -q "$T1/mcp/neural_memory_mcp.py" "$T1/agents/ninja-coder.md" && grep -q 'context-mode@1.0.169' "$T1/agents/researcher.md" \
  && pass "neural-memory and context-mode rendered into the agents that use them" || failed "neural-memory/context-mode not rendered"
# N4: every local stdio MCP server of every agent runs with the stack's own (denyWrite) caches
python3 - "$T1/agents" "$BK_ROOT" <<'PY' && pass "every agent's stdio MCP server has UV_CACHE_DIR/npm_config_cache in the protected cache" || failed "MCP cache env missing (see above)"
import glob, os, re, sys
agents, bk = sys.argv[1], sys.argv[2]
cache = bk[:-len("-backups")] + "-cache"
bad, seen = [], 0
for p in sorted(glob.glob(os.path.join(agents, "*.md"))):
    front = open(p).read().split("\n---", 1)[0]
    for m in re.finditer(r"(?m)^  - ([A-Za-z0-9_-]+):\n((?:      .*\n?)+)", front):
        body = m.group(2)
        if "command:" not in body:
            continue
        seen += 1
        for k, sub in (("UV_CACHE_DIR", "uv"), ("npm_config_cache", "npm")):
            if '        %s: "%s/%s"' % (k, cache, sub) not in body:
                bad.append("%s:%s %s" % (os.path.basename(p), m.group(1), k))
if bad or not seen:
    print("   ", bad[:6], "servers seen:", seen)
sys.exit(1 if bad or not seen else 0)
PY
out=$(XDG_STATE_HOME="$T1/state" "$T1/bin/magg-private" /bin/echo --env-pass --config "$T1/magg/config.json" serve)
priv=$(printf '%s\n' "$out" | sed -n 's/^--env-pass --config \(.*\) serve$/\1/p')
[ -n "$priv" ] && [ "$priv" != "$T1/magg/config.json" ] && cmp -s "$priv" "$T1/magg/config.json" \
  && pass "magg-private runs magg on a private copy of the catalog" || failed "magg-private: [$out]"
python3 - "$T1/settings.json" "$HERE/dot-claude/settings.json" <<'PY' && pass "settings: autocompact on at the shipped window, depth 8, default tool search, lazy MCP, blackcat, shipped skill-listing budget, 500-char cut, 6 user-only bundled skills, hidden hub modules, Plan by default" || failed "settings.json values (see above)"
import json, os, re, sys
def stack_models(p):
    """stack.env.example's Claude model IDs (the single source)."""
    return {m.group(1): m.group(2) for m in (re.match(r"(ANTHROPIC_DEFAULT_[A-Z]+_MODEL)=(\S+)", l) for l in open(p)) if m}
s = json.load(open(sys.argv[1]))
frac = json.load(open(sys.argv[2]))["skillListingBudgetFraction"]
env = s["env"]
example_models = stack_models(os.path.join(os.path.dirname(os.path.dirname(sys.argv[2])), "lib", "stack.env.example"))
checks = {
    "agent": s.get("agent") == "blackcat",
    "autoCompactEnabled": s.get("autoCompactEnabled") is True,
    "autoCompactWindow": s.get("autoCompactWindow") == json.load(open(sys.argv[2]))["autoCompactWindow"],
    "depth": env.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH") == "8",
    "tool search left at its default": "ENABLE_TOOL_SEARCH" not in env,
    ".env.example writable": "Read(**/.env.*)" not in s["permissions"]["deny"] and "Read(**/.env.local)" in s["permissions"]["deny"],
    "discovery cache": env.get("MCP_DISCOVERY_CACHE") == "1",
    "blackcat steps, no dispatch cap": "BLACKCAT_MAX_DISPATCH" not in env and env.get("BLACKCAT_MAX_STEPS") == "24",
    "caps and budgets": (env.get("STACK_MAX_FANOUT"), env.get("STACK_MAX_FANOUT_BY_TYPE"),
                         env.get("STACK_PROMPT_CTX_BUDGET"), env.get("STACK_SESSION_CTX_BUDGET"),
                         env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"), env.get("STACK_MAX_MCP_CALLS"))
                        == ("3", "orchestrator=32,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8", None, None, "128", "64"),
    "skill listing budget": s.get("skillListingBudgetFraction") == frac and 0.01 <= frac <= 0.02
                            and s.get("skillListingMaxDescChars") == 250
                            and s.get("skillOverrides", {}).get("code-review") == "user-invocable-only"
                            and s.get("skillOverrides", {}).get("rust-async") == "user-invocable-only",
    "Claude models from stack.env (no Haiku)": all(env.get(k) == v for k, v in example_models.items())
                                               and len(example_models) == 3
                                               and "haiku" not in example_models["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
    "Plan as the default permission mode": s["permissions"].get("defaultMode") == "plan",
    "image limit hooks": any("image-limit" in json.dumps(g) for g in s["hooks"]["PostToolUse"])
                         and any("image-limit" in json.dumps(g) for g in s["hooks"]["PreToolUse"]),
}
bad = [k for k, ok in checks.items() if not ok]
if bad:
    print("  settings mismatch: " + ", ".join(bad))
sys.exit(1 if bad else 0)
PY
if [ "$(uname)" = "Darwin" ]; then
  grep -q 'illustrator-mcp-server' "$T1/agents/designer.md" && pass "macOS: designer keeps the Illustrator MCP" || failed "macOS: Illustrator MCP missing from designer.md"
else
  python3 - "$T1/agents/designer.md" "$T1/agents/motion-designer.md" <<'PY' && pass "non-macOS render leaves out the Adobe MCP servers" || failed "non-macOS render still starts Adobe MCP servers"
import re, sys
bad = [f for f in sys.argv[1:] if re.search(r"illustrator|premiere|after-effects", open(f).read().split("---")[1])]
sys.exit(1 if bad else 0)
PY
  python3 - "$T1/agents/motion-designer.md" <<'PY' && pass "motion-designer frontmatter still valid without mcpServers" || failed "motion-designer frontmatter broken"
import sys
fm = open(sys.argv[1]).read().split("---")[1]
sys.exit(0 if "mcpServers:" not in fm and "mcp__premiere" not in fm and "\ncolor: pink" in fm else 1)
PY
fi
python3 "$T1/hooks/agent_guard.py" --self-test >/dev/null 2>&1 && pass "installed agent_guard --self-test ok (agent files match POLICY)" \
  || failed "installed agent_guard --self-test failed: $(python3 "$T1/hooks/agent_guard.py" --self-test 2>&1)"
# the read gate: installed, its self-test passes, and settings.json runs it once on Read|Grep|Glob|Bash
python3 "$T1/hooks/read_gate.py" --self-test >/dev/null 2>&1 && python3 - "$T1/settings.json" "$T1" <<'PY' \
  && pass "read gate installed, self-test ok, wired once on PreToolUse Read|Grep|Glob|Bash" \
  || failed "read gate: self-test or settings wiring (python3 $T1/hooks/read_gate.py --self-test)"
import json, sys
s = json.load(open(sys.argv[1]))
g = [g for g in s["hooks"]["PreToolUse"] if "read_gate" in json.dumps(g)]
sys.exit(0 if len(g) == 1 and g[0]["matcher"] == "Read|Grep|Glob|Bash"
         and g[0]["hooks"][0]["command"] == '/bin/sh "%s/bin/stack-hook" read_gate' % sys.argv[2] else 1)
PY
# every installed agent's "May spawn" sentence is its POLICY row
python3 "$T1/hooks/agent_guard.py" --print-policy | python3 -c '
import json, os, re, sys
p, d = json.load(sys.stdin), sys.argv[1]
bad = []
for a, row in p["policy"].items():
    if a == "blackcat":
        continue
    m = re.search(r"May spawn:\s*([^.]*)\.", open(os.path.join(d, a + ".md")).read())
    s = re.sub(r"\([^()]*\)", "", m.group(1)) if m else ""        # drop parenthetical notes
    got = {re.match(r"\s*([A-Za-z0-9_-]*)", x).group(1).lower() for x in s.split(",")} - {""}
    if got != set(row):
        bad.append("%s: May spawn %s != POLICY %s" % (a, sorted(got), sorted(row)))
print("\n".join("    " + b for b in bad))
sys.exit(1 if bad else 0)
' "$T1/agents" && pass "every May spawn sentence matches POLICY" \
  || failed "a May spawn sentence differs from POLICY (see above)"
B1="$(latest_backup "$T1")"
python3 - "$B1" "$T1" <<'PY' && pass "first install: one backup outside the config dir (0700, backup.json 0600) listing what it added" \
  || failed "first install backup: [$B1]"
import json, os, stat, sys
b, t = sys.argv[1:3]
meta = json.load(open(os.path.join(b, "backup.json")))
mode = lambda p: stat.S_IMODE(os.lstat(p).st_mode)
ok = (b and not b.startswith(t) and mode(b) == 0o700 and mode(os.path.join(b, "backup.json")) == 0o600
      and meta["reason"] == "install" and meta["config_dir"] == t and not meta["entries"]
      and "agents/blackcat.md" in meta["added"] and "settings.json" in meta["added"])
sys.exit(0 if ok else 1)
PY
grep -qF "restore it: $INSTALL --restore $B1" "$T1/.install.log" && pass "the run prints the backup and its restore command" \
  || failed "no restore command printed: $(grep -i restore "$T1/.install.log")"
python3 - "$T1/settings.json" "$BK_ROOT" <<'PY' && pass "backups are denied to agents (Read/Edit deny rules, sandbox denyRead/denyWrite)" || failed "backup root not denied in settings.json"
import json, sys
s, bk = json.load(open(sys.argv[1])), sys.argv[2]
fs = s["sandbox"]["filesystem"]
deny = s["permissions"]["deny"]
sys.exit(0 if ("Read(/%s/**)" % bk in deny and "Edit(/%s/**)" % bk in deny
               and bk in fs["denyRead"] and bk in fs["denyWrite"]) else 1)
PY
assert_unchanged_real_home

if [ "$(uname)" != "Darwin" ]; then
  TG="$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")"
  out=$(env -u STACK_ALLOW_NON_MACOS CLAUDE_CONFIG_DIR="$TG/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile 2>&1); rc=$?
  { [ "$rc" = 1 ] && printf '%s\n' "$out" | grep -q "macOS only" && [ ! -e "$TG/c" ]; } \
    && pass "refuses to install on $(uname) (macOS only), touching nothing" || failed "non-macOS guard: rc=$rc: $out"
fi

echo "== 2. Second run: agents reported unchanged, no changes, no backup"
nb_before=$(count_backups "$T1")
LIVE="$XDG_STATE_HOME/claude-agent-stack/limits/live.json"
live_before=$( [ -f "$LIVE" ] && sha "$LIVE" | cut -d' ' -f1 )
if CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install2.log" 2>&1; then
  if grep -qE '^  (agents/|rules/).* unchanged$' "$T1/.install2.log" \
     && ! grep -qE '^  (agents/|rules/).* (installed|overwritten)' "$T1/.install2.log"; then
    pass "second run: all agent/rules entries unchanged"
  else
    failed "second run did not report all files unchanged (see $T1/.install2.log)"
  fi
else
  failed "second install.sh run exited non-zero"
fi
nb_after=$(count_backups "$T1")
[ -n "$live_before" ] && [ "$(sha "$LIVE" | cut -d' ' -f1)" = "$live_before" ] \
  && pass "learned limits: live.json seeded by the first run, byte-identical after the second" \
  || failed "learned limits: live.json missing after the first run or rewritten by the second"
[ "$nb_before" = "$nb_after" ] && grep -q "no changes: the config dir already matches this stack version" "$T1/.install2.log" \
  && grep -qF "nothing changed in $T1 (no backup needed)" "$T1/.install2.log" \
  && pass "a run that changes nothing says so and makes no backup" || failed "no-op run: backups $nb_before -> $nb_after, or no 'no changes' line"
# a hook script install.sh's STACK_HOOK_RE misses is kept as the user's and appended again on a re-run
dup_hooks=$(python3 -c 'import json, sys
for ev, gs in json.load(open(sys.argv[1])).get("hooks", {}).items():
    for g in gs:
        for x in g.get("hooks", []):
            print("%s [%s] %s" % (ev, g.get("matcher", ""), x.get("command")))' "$T1/settings.json" | sort | uniq -d)
[ -z "$dup_hooks" ] && pass "after a re-run each hook command appears once per event and matcher" \
  || { failed "hook commands duplicated after a re-run:"; printf '%s\n' "$dup_hooks" | sed 's/^/    /'; }
assert_unchanged_real_home

echo "== 3. An edited stack file: replaced (the backup keeps it); --no-prune and a bare --force are usage errors"
printf '\n<!-- local edit -->\n' >> "$T1/agents/coder.md"
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install3.log" 2>&1
B3="$(latest_backup "$T1")"
! grep -q '<!-- local edit -->' "$T1/agents/coder.md" && [ ! -e "$T1/agents/coder.md.new" ] \
  && grep -q '<!-- local edit -->' "$B3/files/agents/coder.md" && [ "$(fmode "$B3/files/agents/coder.md")" = 0o600 ] \
  && grep -qx '  ~ agents/coder.md  (edited since the last install)' "$T1/.install3.log" \
  && grep -qF "restore it: $INSTALL --restore $B3" "$T1/.install3.log" \
  && pass "edited coder.md replaced, listed under 'replaced', the edit kept in the backup (0600)" \
  || failed "default run over an edited coder.md: $(grep -F 'coder.md' "$T1/.install3.log" | head -3)"
printf '\n<!-- local edit -->\n' >> "$T1/agents/coder.md"
edited_before="$(sha "$T1/agents/coder.md" | awk '{print $1}')"; nb3="$(count_backups "$T1")"
for opt in --no-prune --force; do
  CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile "$opt" >"$T1/.install3b.log" 2>&1; rc=$?
  case "$opt" in --no-prune) want='--no-prune was removed: the installer always prunes' ;; *) want='--force works only with --restore' ;; esac
  [ "$rc" = 2 ] && grep -qF -- "$want" "$T1/.install3b.log" && [ "$(sha "$T1/agents/coder.md" | awk '{print $1}')" = "$edited_before" ] \
    && [ ! -e "$T1/agents/coder.md.new" ] && [ "$(count_backups "$T1")" = "$nb3" ] \
    && pass "$opt: a usage error (exit 2) that changes nothing" || failed "$opt (rc=$rc): $(tail -n 2 "$T1/.install3b.log")"
done
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install4.log" 2>&1
! grep -q '<!-- local edit -->' "$T1/agents/coder.md" && pass "the next plain run replaces the edited coder.md again" \
  || failed "plain run after the usage errors kept the edit"
assert_unchanged_real_home

echo "== 4. Settings merge: pins, concurrency, compaction overrides; magg catalog merge"
T2="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
export FAKE_CLAUDE_JSON="$T2/fake-claude.json" STACK_CLAUDE_JSON="$T2/fake-claude.json"
mkdir -p "$T2/magg"
# docling edited by the user (replaced: the backup keeps it) and a server of their own (kept).
cat > "$T2/magg/config.json" <<'JSON'
{"servers": {"docling": {"source": "x", "command": "my-docling", "enabled": true},
             "mine": {"source": "y", "command": "my-server", "enabled": true}}}
JSON
CLAUDE_CONFIG_DIR="$T2" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T2/.install.log" 2>&1
B4="$(latest_backup "$T2")"
grep -q '"my-docling"' "$B4/files/magg/config.json" 2>/dev/null \
  && grep -qx "  ~ magg catalog: docling  (differed from the stack's entry)" "$T2/.install.log" \
  && pass "magg: an edited stack entry is replaced and listed; the backup keeps the old catalog" \
  || failed "magg: edited docling entry not replaced/listed/backed up: $(grep -i magg "$T2/.install.log")"
python3 - "$T2/settings.json" <<'PY'
import json, sys
p = sys.argv[1]
s = json.load(open(p))
env = s.setdefault("env", {})
env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "claude-haiku-old"      # fictitious IDs: the lint keeps real ones
env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "claude-opus-old[1m]"    # in stack.env.example
env["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"] = "12"
env["CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION"] = "5"
env["DISABLE_AUTO_COMPACT"] = "1"
env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "200000"
s["autoCompactWindow"] = 300000                   # the earlier stack value
s["permissions"]["allow"].append("Bash(ls *)")
s["permissions"]["allow"].remove("mcp__lean")      # an install from before the lean/mobilebuild/computer-use allows
s["permissions"]["ask"].append("mcp__mobilebuild") # the user's own rule: keep prompting for that server
json.dump(s, open(p, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$T2" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T2/.install2.log" 2>&1
python3 - "$T2/settings.json" "$HERE/dot-claude/settings.json" "$T2/magg/config.json" <<'PY'
import json, os, re, sys
def example_models(p):
    """stack.env.example's Claude model IDs (the single source)."""
    return {m.group(1): m.group(2) for m in (re.match(r"(ANTHROPIC_DEFAULT_[A-Z]+_MODEL)=(\S+)", l) for l in open(p)) if m}
dst, shipped_path, magg = sys.argv[1], sys.argv[2], sys.argv[3]
s = json.load(open(dst))
env = s.get("env", {})
shipped = json.load(open(shipped_path)).get("env", {})
ok = True
def check(cond, good, bad):
    global ok
    print("  %s  %s" % ("PASS" if cond else "FAIL", good if cond else bad))
    ok = ok and cond
models = example_models(os.path.join(os.path.dirname(os.path.dirname(shipped_path)), "lib", "stack.env.example"))
check(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == models["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
      "a Haiku pin is replaced by stack.env's haiku slot (the stack runs no Haiku)",
      "ANTHROPIC_DEFAULT_HAIKU_MODEL=%r" % env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
check(env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == models["ANTHROPIC_DEFAULT_OPUS_MODEL"],
      "[1m]-suffixed pin replaced by stack.env's ID", "ANTHROPIC_DEFAULT_OPUS_MODEL=%r" % env.get("ANTHROPIC_DEFAULT_OPUS_MODEL"))
check("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" not in env, "no-op CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION dropped", "no-op var kept")
check(env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS") == shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS reset to shipped %s" % shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "concurrency not reset (%r)" % env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"))
check("DISABLE_AUTO_COMPACT" not in env and "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env,
      "auto-compaction overrides removed", "auto-compaction overrides kept")
check(s.get("autoCompactWindow") == json.load(open(shipped_path))["autoCompactWindow"] and s.get("autoCompactEnabled") is True,
      "autoCompactWindow back to the shipped value", "autoCompactWindow=%r" % s.get("autoCompactWindow"))
check("Bash(ls *)" in s["permissions"]["allow"], "user's own allow rule kept", "user's allow rule lost")
check("mcp__lean" in s["permissions"]["allow"] and "mcp__mobilebuild" in s["permissions"]["ask"],
      "new MCP allow rule added on upgrade; the user's ask rule on an allowed server kept (ask beats allow)",
      "MCP rules after upgrade: lean allowed %r, mobilebuild ask kept %r" % (
          "mcp__lean" in s["permissions"]["allow"], "mcp__mobilebuild" in s["permissions"]["ask"]))
m = json.load(open(magg))["servers"]
check(m["docling"]["command"] != "my-docling" and m["docling"]["enabled"] is False
      and m.get("mine") == {"source": "y", "command": "my-server", "enabled": True},
      "magg: the stack's docling entry is the stack's (disabled); the user's own server untouched",
      "magg: docling %r, mine %r" % (m["docling"], m.get("mine")))
check(all(k in m for k in ("duckdb", "arxiv", "jupyter", "mlflow", "playwright", "lean")),
      "magg: new catalog entries added", "magg: catalog entries missing: %s" % sorted(m))
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && pass "settings/magg merge block" || failed "settings/magg merge block (see messages above)"
python3 - "$T2/settings.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["permissions"]["deny"].append("Read(**/.env.*)")    # the user wants the broad rule back
s["env"]["ENABLE_TOOL_SEARCH"] = "true"               # e.g. a gateway that forwards tool_reference
json.dump(s, open(sys.argv[1], "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$T2" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T2/.install3.log" 2>&1
python3 - "$T2/settings.json" <<'PY' && pass "retired values the user adds back stay (retractions apply once)" || failed "a re-added retired value was retracted again"
import json, sys
s = json.load(open(sys.argv[1]))
sys.exit(0 if "Read(**/.env.*)" in s["permissions"]["deny"] and s["env"].get("ENABLE_TOOL_SEARCH") == "true" else 1)
PY
assert_unchanged_real_home

echo "== 5. --mcp-plan changes nothing and reports add/migrate/keep"
T3="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
FAKE_CJ="$T3/fake-claude.json"
export FAKE_CLAUDE_JSON="$FAKE_CJ" STACK_CLAUDE_JSON="$FAKE_CJ"
cat > "$FAKE_CJ" <<'JSON'
{
  "mcpServers": {
    "exa": {"type": "http", "url": "https://mcp.exa.ai/mcp", "headers": {"x-api-key": "plaintext-exa-key-123"}},
    "wolfram": {"type": "http", "url": "https://example.com/not-wolfram"}
  }
}
JSON
FAKE_CJ_BEFORE="$(sha "$FAKE_CJ" | awk '{print $1}')"
cp "$HERE/lib/stack.env.example" "$T3/stack.env"; chmod 600 "$T3/stack.env"
plan_out="$(CLAUDE_CONFIG_DIR="$T3" "$INSTALL" --mcp-plan 2>"$T3/.mcpplan.err")"
[ "$FAKE_CJ_BEFORE" = "$(sha "$FAKE_CJ" | awk '{print $1}')" ] && pass "--mcp-plan made no changes to the MCP config" \
  || failed "--mcp-plan modified the MCP config"
[ ! -e "$T3/agents" ] && [ ! -e "$T3/settings.json" ] && pass "--mcp-plan installed nothing" || failed "--mcp-plan installed files"
for want in "migrate[[:space:]]+exa" "add[[:space:]]+jina" "keep[[:space:]]+wolfram" "add[[:space:]]+huggingface"; do
  printf '%s\n' "$plan_out" | grep -qE "^$want([[:space:]]|$)" && pass "--mcp-plan: $want" \
    || { failed "--mcp-plan: expected '$want' in:"; printf '%s\n' "$plan_out" | sed 's/^/    /'; }
done
printf '%s\n' "$plan_out" | grep -qE '^[a-z]+[[:space:]]+wandb' && failed "--mcp-plan: wandb planned without WANDB_API_KEY" \
  || pass "--mcp-plan: wandb skipped without WANDB_API_KEY"
assert_unchanged_real_home

echo "== 6. MCP registration through (fake) claude mcp: keys never stored, plaintext migrated"
sed -i.bak 's/^EXA_API_KEY=.*/EXA_API_KEY=exa-from-stack-env/; s/^WANDB_API_KEY=.*/WANDB_API_KEY=wb-from-stack-env/' "$T3/stack.env" && rm -f "$T3/stack.env.bak"
if CLAUDE_CONFIG_DIR="$T3" "$INSTALL" --no-plugins --no-deps --no-profile >"$T3/.install.log" 2>&1; then
  pass "install with MCP registration exits 0"
else
  failed "install with MCP registration failed (see $T3/.install.log)"; tail -n 30 "$T3/.install.log"
fi
python3 - "$FAKE_CJ" "$T3" <<'PY'
import json, sys
cfg, T = sys.argv[1], sys.argv[2]
s = json.load(open(cfg))["mcpServers"]
ok = True
def check(cond, good, bad):
    global ok
    print("  %s  %s" % ("PASS" if cond else "FAIL", good if cond else bad))
    ok = ok and cond
helper = '"%s/bin/mcp-headers"' % T
for name in ("exa", "jina", "huggingface", "wandb"):
    hh = str((s.get(name) or {}).get("headersHelper", ""))
    check(hh.startswith('"/') and hh.endswith(" " + helper) and "headers" not in s[name],
          "%s registered with headersHelper, no static headers" % name, "%s entry wrong: %r" % (name, s.get(name)))
check(s["wolfram"]["url"] == "https://example.com/not-wolfram", "foreign wolfram entry left alone", "wolfram entry overwritten")
raw = open(cfg).read()
check("plaintext-exa-key-123" not in raw and "exa-from-stack-env" not in raw and "wb-from-stack-env" not in raw,
      "no API key stored in the MCP config", "an API key is stored in the MCP config")
sys.exit(0 if ok else 1)
PY
[ $? -eq 0 ] && pass "MCP registration block" || failed "MCP registration block (see messages above)"
out=$(CLAUDE_CONFIG_DIR="$T3" "$T3/bin/mcp-headers" exa --reveal)
[ "$out" = '{"x-api-key": "exa-from-stack-env"}' ] && pass "installed mcp-headers serves the key from stack.env" \
  || failed "mcp-headers output: $(redacted "$out")"
redout=$(CLAUDE_CONFIG_DIR="$T3" "$T3/bin/mcp-headers" exa)
[ "$redout" != '{"x-api-key": "exa-from-stack-env"}' ] && printf '%s' "$redout" | grep -q '<redacted:' \
  && pass "mcp-headers without --reveal redacts the key" || failed "mcp-headers without --reveal: $(redacted "$redout")"
plan2="$(CLAUDE_CONFIG_DIR="$T3" "$INSTALL" --mcp-plan 2>/dev/null)"
if printf '%s\n' "$plan2" | grep -E '^(add|migrate|replace)[[:space:]]' >/dev/null; then
  failed "re-plan after registration is not idempotent:"; printf '%s\n' "$plan2" | sed 's/^/    /'
else
  pass "re-plan after registration: everything keep (idempotent)"
fi
assert_unchanged_real_home

echo "== 7. doctor.sh against the installed scratch dir"
out=$(CLAUDE_CONFIG_DIR="$T3" bash "$T3/bin/doctor.sh" 2>&1)
unexpected=$(printf '%s\n' "$out" | grep 'FAIL' | grep -vE 'sci venv|tools venv|magg missing|huetension missing|uvx missing|uv missing|node missing|npx missing')
if [ -n "$unexpected" ]; then
  failed "doctor.sh reported unexpected FAILs:"; printf '%s\n' "$unexpected" | sed 's/^/    /'
else
  pass "doctor.sh: only expected FAILs (--no-deps skipped venv/magg)"
fi
# a catalog-only server install.sh builds only with cargo (serial) is a WARN when missing, never a
# FAIL, and names the pinned install command from its catalog notes
SERIAL_V=$(python3 -c 'import json, re, sys
n = json.load(open(sys.argv[1]))["servers"]["serial"]["notes"]
print(re.search(r"cargo install serial-mcp@(\S+) --locked", n).group(1))' "$HERE/dot-claude/magg/config.json")
if [ -x "$HOME/.cargo/bin/serial-mcp" ] \
   || printf '%s\n' "$out" | grep 'WARN  .*/serial-mcp missing — MCP server of magg catalog: serial' \
        | grep -qF "rerun ./install.sh with cargo on PATH, or run: cargo install serial-mcp@$SERIAL_V --locked)"; then
  pass "doctor.sh: a missing cargo-built catalog server is a WARN with its pinned install command"
else
  failed "doctor.sh serial-mcp line: $(printf '%s\n' "$out" | grep serial-mcp)"
fi
printf '%s\n' "$out" | grep -q "agent files present" && pass "doctor.sh: agent files check ran" || failed "doctor.sh: agent files check missing"
{ printf '%s\n' "$out" | grep -q 'ok    settings.json PreToolUse(Agent) enforces the policy' \
  && printf '%s\n' "$out" | grep -q 'ok    token budgets wired: PreToolUse "\*" runs agent_guard.py budget' \
  && printf '%s\n' "$out" | grep -q 'ok    token budgets: agent_guard budget check: '; } \
  && pass "doctor.sh: policy probe skips the budget hook; budget wiring and --check-budget checks ran" \
  || failed "doctor.sh: policy/budget lines: $(printf '%s\n' "$out" | grep -i 'PreToolUse(Agent)\|budget')"
[ "$(printf '%s\n' "$out" | grep -cE 'ok    settings.json PreToolUse\((Bash|Monitor)\) no[- ](push|forge)|ok    no-push hook sees every')" = 4 ] \
  && pass "doctor.sh: no-push probes (plain, bash -c, Monitor forge write, no if filter)" \
  || failed "doctor.sh: no-push probe lines: $(printf '%s\n' "$out" | grep -i 'no-push\|forge')"
{ printf '%s\n' "$out" | grep -q 'ok    settings.json PreToolUse blackcat-guard --settings enforces the policy' \
  && printf '%s\n' "$out" | grep -q 'ok    blackcat.md blackcat-guard enforces the policy' \
  && printf '%s\n' "$out" | grep -q 'ok    settings.json PreToolUse(Bash) read-only reviewers enforces the policy'; } \
  && pass "doctor.sh: blackcat-guard (frontmatter and settings wiring) and read-only reviewer probes deny" \
  || failed "doctor.sh: blackcat-guard/read-only probe lines: $(printf '%s\n' "$out" | grep -i 'blackcat-guard\|read-only')"
nsk=$(ls -d "$HERE"/dot-claude/skills/*/ | wc -l | tr -d ' ')
# hub modules hidden by skillOverrides (user-invocable-only or off) are not listed
nhid=$(python3 -c 'import json, os, sys; so = json.load(open(sys.argv[1])).get("skillOverrides", {}); print(sum(1 for k, v in so.items() if v in ("user-invocable-only", "off") and os.path.isdir(os.path.join(sys.argv[2], k))))' "$HERE/dot-claude/settings.json" "$HERE/dot-claude/skills")
budget=$(python3 -c 'import json, sys; print(int(1000000 * 3 * json.load(open(sys.argv[1]))["skillListingBudgetFraction"]))' "$HERE/dot-claude/settings.json")
# user commands (disable-model-invocation: true) are not listed either
ncmd=$(grep -l '^disable-model-invocation: *true' "$HERE"/dot-claude/skills/*/SKILL.md | wc -l | tr -d ' ')
printf '%s\n' "$out" | grep -qE "ok    skill listing: $((nsk - ncmd - nhid)) skills, ~[0-9]+ of $budget characters" \
  && pass "doctor.sh: skill listing within its budget" || failed "doctor.sh: skill listing line: $(printf '%s\n' "$out" | grep 'skill listing')"
printf '%s\n' "$out" | grep -q "exa-from-stack-env" && failed "doctor.sh printed a key value" || pass "doctor.sh never prints key values"
# GitHub credentials agents could use: reported by presence, never by value (its own HOME: no real file)
T3C="$(scratch_dir)" || exit 1
mkdir -p "$T3C/gh"; printf 'github.com:\n    oauth_token: gho_SMOKESECRET2\n    user: x\n' > "$T3C/gh/hosts.yml"
printf 'https://x:SMOKESECRET3@github.com\n' > "$T3C/.git-credentials"
outc=$(HOME="$T3C" GH_CONFIG_DIR="$T3C/gh" GH_TOKEN=SMOKESECRET1 CLAUDE_CONFIG_DIR="$T3" bash "$T3/bin/doctor.sh" 2>&1)
printf '%s\n' "$outc" | grep -q 'WARN  GH_TOKEN is set in this environment' \
  && printf '%s\n' "$outc" | grep -q "plain text in $T3C/gh/hosts.yml" \
  && printf '%s\n' "$outc" | grep -q "$T3C/.git-credentials holds a github.com credential" \
  && ! printf '%s\n' "$outc" | grep -q 'SMOKESECRET' \
  && pass "doctor.sh: GitHub credentials by presence only (env token, gh hosts.yml, ~/.git-credentials), no value printed" \
  || failed "doctor.sh credential presence: $(printf '%s\n' "$outc" | grep -i 'token\|credential' | sed 's/SMOKESECRET[0-9]*/<value>/g' | head -4)"
drop_scratch "$T3C"
# SessionStart must reach the guard for fork too (a fork's token count starts at the end of the
# history it copied) and compact (the compaction digest): the shipped matcher passes, one without
# them fails
printf '%s\n' "$out" | grep -q 'ok    SessionStart guard matcher covers startup, resume, fork and compact' \
  && pass "doctor.sh: SessionStart guard matcher covers fork and compact" \
  || failed "doctor.sh: SessionStart matcher line: $(printf '%s\n' "$out" | grep 'SessionStart')"
T3F="$(scratch_dir)" || exit 1
cp -R "$T3/." "$T3F/"
python3 - "$T3F/settings.json" <<'PY'
import json, sys
p = sys.argv[1]
s = json.load(open(p))
for g in s["hooks"]["SessionStart"]:
    if "agent_guard" in json.dumps(g) and "session-env" not in json.dumps(g):
        g["matcher"] = "startup|resume"
json.dump(s, open(p, "w"), indent=2)
PY
outf=$(CLAUDE_CONFIG_DIR="$T3F" bash "$T3F/bin/doctor.sh" 2>&1)
printf '%s\n' "$outf" | grep -q 'FAIL  SessionStart guard matcher startup|resume misses fork, compact — rerun install.sh' \
  && pass "doctor.sh fails a SessionStart guard matcher without fork or compact" \
  || failed "doctor.sh: no FAIL for a SessionStart matcher without fork: $(printf '%s\n' "$outf" | grep 'SessionStart')"
drop_scratch "$T3F"
assert_unchanged_real_home

echo "== 8. Regressions: rc lines, empty keys, key-preserving migration, settings merge, CLAUDE_CONFIG_DIR"
T4="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
cat > "$T4/.zshrc" <<'RC'
alias cas='cd ~/Projects/claude-agent-stack && git pull'   # my shortcut
[ -f "/old/.claude/stack.env" ] && { set -a; . "/old/.claude/stack.env"; set +a; }  # claude-agent-stack
export EDITOR=vi
RC
export FAKE_CLAUDE_JSON="$T4/fake-claude.json" STACK_CLAUDE_JSON="$T4/fake-claude.json"
echo '{"mcpServers":{"exa":{"type":"http","url":"https://mcp.exa.ai/mcp","headers":{"x-api-key":"exa-only-in-config-1234"}},"jina":{"type":"http","url":"https://mcp.jina.ai/v1?exclude_tools=search_jina_blog","headersHelper":"/opt/op/jina-headers"}}}' > "$FAKE_CLAUDE_JSON"
mkdir -p "$T4/.claude"; { cat "$HERE/lib/stack.env.example"; echo 'OPENAI_API_KEY=sk-mine-123'; echo 'MY_DIR=$HOME/work'; } > "$T4/.claude/stack.env"
chmod 600 "$T4/.claude/stack.env"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-plugins --no-deps >"$T4/.install.log" 2>&1 \
  && pass "install with profile step (scratch HOME) exits 0" || { failed "install with profile step failed"; tail -n 30 "$T4/.install.log"; }
# the Playwright MCP's --output-dir: created 0700 under HOME (doctor.sh FAILs while it is missing)
pw_out="$T4/.cache/claude-sandbox/playwright-mcp"
pw_doc="$(HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" bash "$T4/.claude/bin/doctor.sh" 2>&1)"
[ -d "$pw_out" ] && [ "$(fmode "$pw_out")" = 0o700 ] && [ "$(fmode "$T4/.cache/claude-sandbox")" = 0o700 ] \
  && ! printf '%s\n' "$pw_doc" | grep -q 'playwright-mcp missing' \
  && pass "the Playwright MCP output dir doctor expects is created (0700, scratch HOME)" \
  || failed "playwright-mcp output dir: [$(fmode "$pw_out" 2>&1)] $(printf '%s\n' "$pw_doc" | grep 'playwright-mcp')"
T4D="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
HOME="$T4D" CLAUDE_CONFIG_DIR="$T4D/.claude" "$INSTALL" --dry-run --no-mcp --no-plugins --no-deps --no-profile >"$T4D/.log" 2>&1 \
  && [ ! -e "$T4D/.cache/claude-sandbox/playwright-mcp" ] \
  && { pass "--dry-run creates no Playwright output dir"; rm -rf "$T4D"; } || failed "--dry-run and the Playwright output dir (see $T4D/.log)"
# --dry-run with the plugins step runs no language server (a rustup proxy writes ~/.rustup, julia
# ~/.julia): found counts, LanguageServer.jl by its environment's Project.toml; a fresh HOME stays empty
T4R="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
mkdir -p "$T4R/stubs" "$T4R/home" "$T4R/depot/environments/claude-lsp"
printf '[deps]\nLanguageServer = "2b0e0bc5-e4fd-59b4-8912-456d1b03d8d7"\n' >"$T4R/depot/environments/claude-lsp/Project.toml"
for t in rust-analyzer rustup cargo julia; do
  printf '#!/bin/sh\necho "%s $*" >>"%s/ran.log"\nmkdir -p "$HOME/.%s"\n' "$t" "$T4R" "$t" >"$T4R/stubs/$t"; chmod +x "$T4R/stubs/$t"
done
HOME="$T4R/home" CLAUDE_CONFIG_DIR="$T4R/home/.claude" JULIA_DEPOT_PATH="$T4R/depot:" PATH="$T4R/stubs:$PATH" \
  "$INSTALL" --dry-run --no-mcp --no-deps --no-profile >"$T4R/.log" 2>&1 \
  && [ ! -e "$T4R/ran.log" ] && [ -z "$(ls -A "$T4R/home")" ] \
  && grep -q 'would: claude plugin install rust-analyzer-lsp@claude-plugins-official' "$T4R/.log" \
  && grep -q 'would: claude plugin install julia-lsp@agent-stack' "$T4R/.log" \
  && { pass "--dry-run runs no language server and leaves a fresh HOME empty"; rm -rf "$T4R"; } \
  || failed "--dry-run ran [$(cat "$T4R/ran.log" 2>/dev/null)] or wrote HOME [$(ls -A "$T4R/home")] (see $T4R/.log)"
grep -q "alias cas=" "$T4/.zshrc" && pass "unrelated rc line mentioning claude-agent-stack kept" || failed "unrelated rc line deleted"
[ "$(grep -c '# claude-agent-stack$' "$T4/.zshrc")" = 1 ] && grep -q 'with-stack-env" --print-env --reveal sh' "$T4/.zshrc" \
  && pass "old stack line replaced by exactly one new line" || failed "rc stack line not replaced exactly once"
B8="$(latest_backup "$T4/.claude")"
rcf="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["rc"][sys.argv[2]]["file"])' "$B8/backup.json" "$T4/.zshrc" 2>/dev/null)"
[ -n "$rcf" ] && grep -q "alias cas=" "$B8/rc/$rcf" && ! grep -q 'with-stack-env' "$B8/rc/$rcf" && [ "$(fmode "$B8/rc/$rcf")" = 0o600 ] \
  && pass "rc file backed up (0600, the version before the edit) into the run's backup" || failed "no rc backup in [$B8]"
[ "$(readlink "$T4/.local/bin/claude-ninja")" = "$T4/.claude/bin/claude-ultracode" ] \
  && pass "claude-ninja linked into ~/.local/bin" || failed "ultracode launcher not linked"
FAKE_CLAUDE_LOG="$T4/.fake.log" "$T4/.local/bin/claude-ninja" -p hello >/dev/null 2>&1
python3 - "$T4/.fake.log" <<'PY' && pass "claude-ninja starts ninja-coder as the main thread at ultracode in Plan, workflows pre-approved" || failed "claude-ninja arguments: $(tail -n 1 "$T4/.fake.log" 2>/dev/null)"
import json, sys
args = json.loads(open(sys.argv[1]).read().splitlines()[-1])
want = ["--agent", "ninja-coder", "--effort", "ultracode", "--settings", '{"permissions":{"allow":["Workflow"]}}',
        "--permission-mode", "plan", "-p", "hello"]
sys.exit(0 if args == want else 1)
PY
rcline="$(grep '# claude-agent-stack$' "$T4/.zshrc")"
out=$(env -i HOME="$T4" PATH="$PATH" HF_TOKEN=hf_user_token bash -c "$rcline
printf '%s' \"\$HF_TOKEN\"")
[ "$out" = hf_user_token ] && pass "empty HF_TOKEN= in stack.env no longer blanks an exported token" || failed "HF_TOKEN clobbered: [$out]"
out=$(env -i HOME="$T4" PATH="$PATH" bash -c "$rcline
printf '%s' \"\${EXA_API_KEY:-unset}\"")
[ "$out" = unset ] && pass "profile line exports only the CLI keys (EXA_API_KEY stays out of the shell)" || failed "profile line exported EXA_API_KEY"
python3 - "$FAKE_CLAUDE_JSON" <<'PY' && pass "a user's own headersHelper is kept" || failed "the user's own headersHelper was replaced"
import json, sys
sys.exit(0 if json.load(open(sys.argv[1]))["mcpServers"]["jina"].get("headersHelper") == "/opt/op/jina-headers" else 1)
PY
out=$(env -i HOME="$T4" PATH="$PATH" GITHUB_TOKEN=gh_x CLAUDE_CONFIG_DIR="$T4/.claude" "$T4/.claude/bin/with-stack-env" --only EXA_API_KEY \
  sh -c 'printf "%s|%s|%s" "${EXA_API_KEY:-}" "${OPENROUTER_API_KEY:-none}" "${GITHUB_TOKEN:-}"')
[ "$out" = "exa-only-in-config-1234|none|gh_x" ] && pass "with-stack-env --only adds just the named key" \
  || failed "with-stack-env --only: $(redacted "$out")"
grep -q '^EXA_API_KEY=exa-only-in-config-1234$' "$T4/.claude/stack.env" && pass "plaintext exa key copied to stack.env before migration" \
  || failed "plaintext exa key lost on migration"
migout=$(CLAUDE_CONFIG_DIR="$T4/.claude" "$T4/.claude/bin/mcp-headers" exa --reveal)
[ "$migout" = '{"x-api-key": "exa-only-in-config-1234"}' ] \
  && pass "migrated exa still authenticates through the helper" || failed "helper lost the exa key: $(redacted "$migout")"
grep -q 'exa-only-in-config-1234' "$FAKE_CLAUDE_JSON" && failed "key still in the MCP config" || pass "key no longer in the MCP config"
# user edits settings: own hook inside the stack's Agent group, a tuned knob, an owned knob changed; symlinked file
mkdir -p "$T4/dotfiles"
python3 - "$T4/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
for g in s["hooks"]["PreToolUse"]:
    if "Agent" in (g.get("matcher") or "").split("|"):
        g["hooks"].append({"type": "command", "command": "my-audit.sh"})
s["env"]["BLACKCAT_MAX_STEPS"] = "20"         # owned: reset to the stack's value
s["env"]["STACK_FANOUT_IDLE_S"] = "900"        # a tunable knob: kept
s["env"]["ENABLE_TOOL_SEARCH"] = "auto:5"
s["agent"] = "claude"
s["skillListingBudgetFraction"] = 0.05
s["statusLine"] = {"type": "command", "command": "echo 'Olá'"}
json.dump(s, open(p, "w"), indent=2, ensure_ascii=False)
PY
mv "$T4/.claude/settings.json" "$T4/dotfiles/settings.json"; ln -s "$T4/dotfiles/settings.json" "$T4/.claude/settings.json"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >"$T4/.install2.log" 2>&1
[ -L "$T4/.claude/settings.json" ] && pass "symlinked settings.json stays a symlink" || failed "settings.json symlink replaced"
python3 - "$T4/.claude/settings.json" "$HERE/dot-claude/settings.json" <<'PY' && pass "user hook in the stack's group, tuned knobs and own main agent kept" || failed "settings merge dropped user changes"
import json, sys
s = json.load(open(sys.argv[1]))
shipped = sum("agent_guard" in json.dumps(g) for g in json.load(open(sys.argv[2]))["hooks"]["PreToolUse"])
cmds = [h.get("command") for g in s["hooks"]["PreToolUse"] for h in g.get("hooks", [])]
ok = ("my-audit.sh" in cmds and sum("agent_guard" in (c or "") for c in cmds) == shipped and s["env"]["BLACKCAT_MAX_STEPS"] == "24"
      and s["env"]["STACK_FANOUT_IDLE_S"] == "900"
      and s["env"].get("ENABLE_TOOL_SEARCH") == "auto:5" and s.get("agent") == "claude"
      and s.get("skillListingBudgetFraction") == 0.05)
sys.exit(0 if ok else 1)
PY
grep -q "Olá" "$T4/dotfiles/settings.json" && pass "non-ASCII kept as-is" || failed "non-ASCII re-escaped"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >/dev/null 2>&1
[ "$(grep -c '# claude-agent-stack$' "$T4/.zshrc")" = 1 ] && pass "third run: still one rc line" || failed "rc line duplicated"
# an old profile line is rewritten (the rc file is backed up): a restore puts it back exactly
T4R="$(scratch_dir)" || exit 1
printf 'export EDITOR=vi\n[ -f "/old/.claude/stack.env" ] && { set -a; . "/old/.claude/stack.env"; set +a; }  # claude-agent-stack\n' > "$T4R/.zshrc"
mkdir -p "$T4R/.claude"; { cat "$HERE/lib/stack.env.example"; echo 'OPENAI_API_KEY=sk-mine-123'; } > "$T4R/.claude/stack.env"; chmod 600 "$T4R/.claude/stack.env"
cp -p "$T4R/.zshrc" "$T4R/zshrc.before"; cp -p "$T4R/.claude/stack.env" "$T4R/env.before"
HOME="$T4R" FAKE_CLAUDE_JSON="$T4R/f.json" STACK_CLAUDE_JSON="$T4R/f.json" CLAUDE_CONFIG_DIR="$T4R/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >"$T4R/i.log" 2>&1
! cmp -s "$T4R/.zshrc" "$T4R/zshrc.before" \
  && HOME="$T4R" CLAUDE_CONFIG_DIR="$T4R/.claude" "$INSTALL" --restore latest >"$T4R/r.log" 2>&1 \
  && cmp -s "$T4R/.zshrc" "$T4R/zshrc.before" && cmp -s "$T4R/.claude/stack.env" "$T4R/env.before" \
  && [ -z "$(ls -A "$T4R/.claude/agents" 2>/dev/null)" ] \
  && pass "--restore undoes the profile line rewrite: rc file and stack.env byte-identical again, stack files gone" \
  || { failed "restore after the profile upgrade"; tail -n 8 "$T4R/r.log" | sed 's/^/    /'; }
drop_scratch "$T4R"
# fresh CLAUDE_CONFIG_DIR without STACK_CLAUDE_JSON: the plan must read <dir>/.claude.json even before it exists
T5="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
plan=$(env -u STACK_CLAUDE_JSON CLAUDE_CONFIG_DIR="$T5" "$INSTALL" --mcp-plan 2>&1)
printf '%s\n' "$plan" | grep -qF "config read for the plan: $T5/.claude.json" && pass "--mcp-plan reads \$CLAUDE_CONFIG_DIR/.claude.json" \
  || failed "--mcp-plan read the wrong config: $(printf '%s\n' "$plan" | grep 'config read')"
# stack.env referencing an unset variable must not abort the installer (bash 3.2 even exited 0)
mkdir -p "$T5/c"; sed 's#^IMAGE_STUDIO_OUT_DIR=.*#IMAGE_STUDIO_OUT_DIR=$XDG_PICTURES_DIR/studio#' "$HERE/lib/stack.env.example" \
  | grep -vE 'MOTHERDUCK_TOKEN|STACK_EXPORT' > "$T5/c/stack.env"
FAKE_CLAUDE_JSON="$T5/f.json" STACK_CLAUDE_JSON="$T5/f.json" CLAUDE_CONFIG_DIR="$T5/c" "$INSTALL" --no-plugins --no-deps --no-profile >"$T5/.log" 2>&1 \
  && grep -q 'Done. Next' "$T5/.log" && pass "stack.env with an unset \$VAR: install completes" || failed "unset \$VAR in stack.env aborted the install"
FAKE_CLAUDE_JSON="$T5/f.json" STACK_CLAUDE_JSON="$T5/f.json" CLAUDE_CONFIG_DIR="$T5/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1
if [ "$(grep -c '^#MOTHERDUCK_TOKEN=' "$T5/c/stack.env")" = 1 ] && [ "$(grep -c '^#STACK_EXPORT=' "$T5/c/stack.env")" = 1 ] \
   && grep -q '^IMAGE_STUDIO_OUT_DIR=\$XDG_PICTURES_DIR/studio$' "$T5/c/stack.env" && grep -q 'added by install.sh' "$T5/c/stack.env"; then
  pass "stack.env upgrade: new variables appended once, commented out; your lines untouched"
else
  failed "stack.env upgrade append"; tail -n 12 "$T5/c/stack.env" | sed 's/^/    /'
fi
# A stack.env from before the Claude model variables: the missing ones are appended set to
# stack.env.example's IDs, a value you wrote stays as written, and step 7 copies them into
# settings.json's env. Later runs append nothing; a stack.env change reaches settings.json, while a
# value you set in settings.json yourself is kept.
T16="$(scratch_dir)"; mkdir -p "$T16/c"
grep -vE '^ANTHROPIC_DEFAULT_(OPUS|SONNET|HAIKU)_MODEL=' "$HERE/lib/stack.env.example" > "$T16/c/stack.env"
echo 'ANTHROPIC_DEFAULT_OPUS_MODEL=my-opus-pin  # mine' >> "$T16/c/stack.env"
CLAUDE_CONFIG_DIR="$T16/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T16/.log1" 2>&1
cp "$T16/c/stack.env" "$T16/env.after1"
CLAUDE_CONFIG_DIR="$T16/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T16/.log2" 2>&1
python3 - "$T16/c/settings.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["env"]["ANTHROPIC_DEFAULT_SONNET_MODEL"] = "my-settings-sonnet"
json.dump(s, open(sys.argv[1], "w"), indent=2)
PY
sed -i.bak 's/^ANTHROPIC_DEFAULT_OPUS_MODEL=.*/ANTHROPIC_DEFAULT_OPUS_MODEL=my-opus-2/' "$T16/c/stack.env" && rm -f "$T16/c/stack.env.bak"
CLAUDE_CONFIG_DIR="$T16/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T16/.log3" 2>&1
python3 - "$T16" "$HERE/lib/stack.env.example" <<'PY' && pass "stack.env upgrade: Claude model variables appended once with the stack's IDs, your value kept; settings.json env follows stack.env, a settings.json value of yours stays" || failed "Claude model variables in stack.env / settings.json (see above)"
import json, os, re, sys
t, example = sys.argv[1], sys.argv[2]
ex = {m.group(1): m.group(2) for m in (re.match(r"(ANTHROPIC_DEFAULT_[A-Z]+_MODEL)=(\S+)", l) for l in open(example)) if m}
after1 = open(os.path.join(t, "env.after1")).read()
log1 = open(os.path.join(t, ".log1")).read()
lines = after1.splitlines()
checks = {
    "three IDs in the example": len(ex) == 3,
    "your opus line untouched, once": [l for l in lines if "ANTHROPIC_DEFAULT_OPUS_MODEL" in l]
                                      == ["ANTHROPIC_DEFAULT_OPUS_MODEL=my-opus-pin  # mine"],
    "sonnet and haiku appended live, once": all(
        [l for l in lines if l.lstrip("#").startswith(k + "=")] == ["%s=%s" % (k, ex[k])]
        for k in ("ANTHROPIC_DEFAULT_SONNET_MODEL", "ANTHROPIC_DEFAULT_HAIKU_MODEL")),
    "the append is reported": "stack.env: appended the Claude model variables, set to the stack's IDs: "
                              "ANTHROPIC_DEFAULT_SONNET_MODEL, ANTHROPIC_DEFAULT_HAIKU_MODEL" in log1,
    "second run appends nothing": "appended the Claude model variables" not in open(os.path.join(t, ".log2")).read(),
}
env = json.load(open(os.path.join(t, "c", "settings.json")))["env"]
checks.update({
    "settings follow a stack.env change": env.get("ANTHROPIC_DEFAULT_OPUS_MODEL") == "my-opus-2",
    "a settings.json value of yours is kept": env.get("ANTHROPIC_DEFAULT_SONNET_MODEL") == "my-settings-sonnet"
        and "kept your env ANTHROPIC_DEFAULT_SONNET_MODEL=my-settings-sonnet" in open(os.path.join(t, ".log3")).read(),
    "haiku slot from stack.env": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == ex["ANTHROPIC_DEFAULT_HAIKU_MODEL"],
})
bad = [k for k, v in checks.items() if not v]
if bad:
    print("   ", bad)
sys.exit(1 if bad else 0)
PY
drop_scratch "$T16"
# stack.env written by earlier versions (Opper → OpenRouter-only → image-studio): the image comment
# lines are brought up to date, the models appended set to the defaults, nothing of the user's changed
T5B="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"; mkdir -p "$T5B/c"
cat > "$T5B/c/stack.env" <<'ENV'
# my own header line
# Opper gateway — image generation/editing (image-director). https://platform.opper.ai
OPPER_API_KEY=op-mine-123
EXA_API_KEY=exa-mine

# --- added by install.sh 2026-09-26: new in stack.env.example (uncomment to use) ---
# OpenRouter — the stack's only image model: Recraft V4.1 Pro Vector, SVG output only (designer,
# image-director; about $0.30 an image from your OpenRouter credits). https://openrouter.ai/settings/keys
#OPENROUTER_API_KEY=
# Where generated SVGs go when an agent names no folder (optional)
#OPENROUTER_IMAGE_OUT_DIR=$HOME/Pictures/recraft

# --- added by install.sh 2026-09-27: new in stack.env.example (uncomment to use) ---
# Images (designer, image-director) come from image-studio, one tool per provider, each billed to its
# own account; a missing key disables only its tool.
# Where generated images go when an agent names no folder (optional; an older
# OPENROUTER_IMAGE_OUT_DIR line still works)
#IMAGE_STUDIO_OUT_DIR=$HOME/Pictures/image-studio
ENV
chmod 600 "$T5B/c/stack.env"; cp -p "$T5B/c/stack.env" "$T5B/before.env"
FAKE_CLAUDE_JSON="$T5B/f.json" STACK_CLAUDE_JSON="$T5B/f.json" CLAUDE_CONFIG_DIR="$T5B/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5B/.log" 2>&1
E="$T5B/c/stack.env"
B5B="$(latest_backup "$T5B/c")"
mode(){ python3 -c 'import os, sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$1"; }
if grep -q '^OPPER_API_KEY=op-mine-123$' "$E" && grep -q '^EXA_API_KEY=exa-mine$' "$E" && grep -q '^# my own header line$' "$E" \
   && ! grep -qiE 'lumenfall|seedream|OPPER_IMAGE_|only image model|Opper gateway|SVGs go' "$E" \
   && grep -q '^# Opper — generate_image: photographs and other raster images. https://platform.opper.ai$' "$E" \
   && grep -q '^# OpenRouter — generate_svg (vector art) and edit_image (edits, retouching, composites).$' "$E" \
   && [ "$(grep -c '^IMAGE_STUDIO_SVG_MODEL=recraft/recraft-v4.1-pro-vector$' "$E")" = 1 ] \
   && [ "$(grep -c '^IMAGE_STUDIO_IMAGE_MODEL=openai/gpt-image-2.5-sunburst$' "$E")" = 1 ] \
   && [ "$(grep -c '^IMAGE_STUDIO_EDIT_MODEL=sourceful/riverflow-v2.5-pro$' "$E")" = 1 ] \
   && grep -q '^#OPENROUTER_API_KEY=$' "$E" && grep -q '^#IMAGE_STUDIO_OUT_DIR=' "$E" && grep -q '^#JINA_API_KEY=$' "$E" \
   && cmp -s "$T5B/before.env" "$B5B/files/stack.env" && [ "$(mode "$E")" = 0o600 ] \
   && [ "$(mode "$B5B/files/stack.env")" = 0o600 ] && [ "$(mode "$B5B")" = 0o700 ] \
   && grep -q 'appended the image models, set to the defaults' "$T5B/.log" && grep -q 'brought the image lines' "$T5B/.log"; then
  pass "stack.env from earlier versions: image lines brought up to date, models set, values kept, backup made"
else
  failed "stack.env from earlier versions"; sed 's/^/    /' "$E"; grep -i 'stack.env' "$T5B/.log" | sed 's/^/    /'
fi
cp -p "$E" "$T5B/after1.env"
FAKE_CLAUDE_JSON="$T5B/f.json" STACK_CLAUDE_JSON="$T5B/f.json" CLAUDE_CONFIG_DIR="$T5B/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5B/.log2" 2>&1
cmp -s "$E" "$T5B/after1.env" && ! grep -qE '^  (stack.env|note): ' "$T5B/.log2" \
  && pass "stack.env: a second run changes nothing" || failed "stack.env: a second run changed it: $(diff "$T5B/after1.env" "$E" | head -5)"
# first install over the user's own CLAUDE.md (kept) and a same-named skill of their own (the
# stack owns skills/: replaced, the backup keeps it)
T6="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"; printf '# my rules\n- my NAS is 192.168.1.20\n' > "$T6/CLAUDE.md"
mkdir -p "$T6/skills/data-analysis"
printf -- '---\nname: data-analysis\ndescription: my own steps\n---\nMy own analysis steps.\n' > "$T6/skills/data-analysis/SKILL.md"
CLAUDE_CONFIG_DIR="$T6" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T6/.log" 2>&1
# the stack's block is appended after one blank line; the user's lines stay byte for byte before it
head -c "$(printf '# my rules\n- my NAS is 192.168.1.20\n\n' | wc -c)" "$T6/CLAUDE.md" | cmp -s - <(printf '# my rules\n- my NAS is 192.168.1.20\n\n') \
  && [ "$(sed -n '4p' "$T6/CLAUDE.md" | cut -c1-31)" = '<!-- claude-agent-stack: begin ' ] && [ ! -e "$T6/CLAUDE.md.new" ] \
  && [ -f "$T6/rules/claude-agent-stack.md" ] && grep -qE '^  CLAUDE.md \(the stack.s block\) +added$' "$T6/.log" \
  && pass "user's own CLAUDE.md kept byte for byte, the stack's block appended; rules from rules/claude-agent-stack.md" \
  || failed "user's own CLAUDE.md changed outside the block, the block missing, or rules missing"
B6="$(latest_backup "$T6")"
! grep -q 'My own analysis steps' "$T6/skills/data-analysis/SKILL.md" && [ ! -e "$T6/skills/data-analysis/SKILL.md.new" ] \
  && grep -q 'My own analysis steps' "$B6/files/skills/data-analysis/SKILL.md" \
  && grep -qx "  ~ skills/data-analysis/SKILL.md  (a same-named file that isn't the stack's)" "$T6/.log" \
  && pass "same-named personal skill replaced by the stack's, listed, and kept in the backup" || failed "personal skill not replaced/listed/backed up"
assert_unchanged_real_home
rm -rf "$T4" "$T5" "$T6"

echo "== 9. macOS render (simulated): the After Effects server only once it is built"
T8="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/smoke.XXXXXX")" && pwd -P)"
mkdir -p "$T8/pyfake"; printf 'import sys\nsys.platform = "darwin"\n' > "$T8/pyfake/sitecustomize.py"
PYTHONPATH="$T8/pyfake" CLAUDE_CONFIG_DIR="$T8/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T8/.log" 2>&1
python3 - "$T8/c/agents/motion-designer.md" "$T8/c/agents/designer.md" <<'PY' && pass "darwin without --with-adobe: premiere and illustrator kept, after-effects left out" || failed "darwin render of the Adobe servers"
import sys
md, de = (open(f).read().split("---")[1] for f in sys.argv[1:3])
sys.exit(0 if "premiere-pro-mcp" in md and "after-effects" not in md and "illustrator-mcp-server" in de else 1)
PY
mkdir -p "$T8/c/mcp/vendor/after-effects-mcp/build"; echo '// built' > "$T8/c/mcp/vendor/after-effects-mcp/build/index.js"
PYTHONPATH="$T8/pyfake" CLAUDE_CONFIG_DIR="$T8/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T8/.log2" 2>&1
grep -q 'after-effects-mcp/build/index.js' "$T8/c/agents/motion-designer.md" && grep -q 'agents/motion-designer.md *overwritten$' "$T8/.log2" \
  && pass "once built, a rerun adds the After Effects server to motion-designer" || failed "After Effects server not added after the build"
assert_unchanged_real_home
rm -rf "$T8"

echo "== 10. Main-branch rule: fast-forward into main from a branch or worktree, never push"
R0="$(scratch_dir)" || exit 1
REAL_GIT="$(command -v git)"
mkdir -p "$R0/shim"
printf '#!/bin/sh\nprintf "%%s\\n" "$*" >> "%s/git-calls.log"\nexec "%s" "$@"\n' "$R0" "$REAL_GIT" > "$R0/shim/git"
chmod +x "$R0/shim/git"
tgit clone -q --bare "$HERE" "$R0/remote.git" && tgit clone -q "$R0/remote.git" "$R0/repo" || failed "scratch clone"
# A clone copies no repo config, but it does take $HERE's loose objects (gc.auto 0 there keeps them loose): turn
# automatic gc and maintenance off in every clone too, or a commit there (or install.sh's own switch and merge)
# starts a detached repack while install.sh's git fsck reads the objects ("unable to mmap ... No such file").
no_auto_gc(){ local r; for r in "$@"; do tgit -C "$r" config gc.auto 0 && tgit -C "$r" config maintenance.auto false || return 1; done; }
auto_gc_off(){ local r; for r in "$@"; do
  [ "$(git -C "$r" config gc.auto)" = 0 ] && [ "$(git -C "$r" config maintenance.auto)" = false ] || return 1; done; }
no_auto_gc "$R0/remote.git" "$R0/repo" || failed "scratch clone: could not turn automatic gc off"
remote_refs(){ git -C "$R0/remote.git" for-each-ref --format='%(refname) %(objectname)' | sha | awk '{print $1}'; }
REMOTE_BEFORE="$(remote_refs)"
run_from(){ # run_from <checkout> <config dir> [flags...]
  local dir="$1" cfg="$2"; shift 2
  PATH="$R0/shim:$PATH" CLAUDE_CONFIG_DIR="$cfg" FAKE_CLAUDE_JSON="$R0/f.json" STACK_CLAUDE_JSON="$R0/f.json" \
    "$dir/install.sh" --no-mcp --no-plugins --no-deps --no-profile "$@"
}
main_sha(){ git -C "$R0/repo" rev-parse main; }
# a) a linked worktree on a feature branch with one new commit; main checked out in the primary
tgit -C "$R0/repo" worktree add -q -b feat "$R0/wt-feat"
echo feat > "$R0/wt-feat/SMOKE_FEAT.txt"; tgit -C "$R0/wt-feat" add SMOKE_FEAT.txt; tgit -C "$R0/wt-feat" commit -q -m feat
FEAT="$(git -C "$R0/wt-feat" rev-parse HEAD)"
run_from "$R0/wt-feat" "$R0/ca" >"$R0/a.log" 2>&1; rc=$?
if [ "$rc" = 0 ] && [ "$(main_sha)" = "$FEAT" ] && [ -f "$R0/repo/SMOKE_FEAT.txt" ] \
   && grep -q 'fast-forwarded main to feat' "$R0/a.log" && grep -qF "\"repo\": \"$R0/repo\"" "$R0/ca/.stack-manifest.json"; then
  pass "from a feature worktree: main fast-forwarded (ff-only), install ran from the main checkout"
else
  failed "feature worktree run: rc=$rc main=$(main_sha) feat=$FEAT"; tail -n 15 "$R0/a.log" | sed 's/^/    /'
fi
# b) diverged history: refused before anything is installed
tgit -C "$R0/repo" worktree add -q -b div "$R0/wt-div" "$FEAT~1"
echo div > "$R0/wt-div/SMOKE_DIV.txt"; tgit -C "$R0/wt-div" add SMOKE_DIV.txt; tgit -C "$R0/wt-div" commit -q -m div
run_from "$R0/wt-div" "$R0/cb" >"$R0/b.log" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(main_sha)" = "$FEAT" ] && [ ! -e "$R0/cb" ] && grep -q 'have diverged' "$R0/b.log" && grep -q 'rebase main' "$R0/b.log" \
  && pass "diverged branch: refused with the rebase fix, main and the config dir untouched" \
  || { failed "diverged branch: rc=$rc"; tail -n 12 "$R0/b.log" | sed 's/^/    /'; }
# c) untracked work in the feature worktree: refused
tgit -C "$R0/repo" worktree add -q -b dirty "$R0/wt-dirty"
echo x > "$R0/wt-dirty/SMOKE_UNTRACKED.txt"
run_from "$R0/wt-dirty" "$R0/cc" >"$R0/c.log" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(main_sha)" = "$FEAT" ] && [ ! -e "$R0/cc" ] && grep -q 'uncommitted or untracked files' "$R0/c.log" \
  && pass "untracked files in the branch checkout: refused, nothing merged or installed" \
  || { failed "dirty branch: rc=$rc"; tail -n 8 "$R0/c.log" | sed 's/^/    /'; }
# d) uncommitted changes in the main checkout block the fast-forward, and are kept
mv "$R0/wt-dirty/SMOKE_UNTRACKED.txt" "$R0/wt-dirty/SMOKE_D.txt"
tgit -C "$R0/wt-dirty" add SMOKE_D.txt; tgit -C "$R0/wt-dirty" commit -q -m d
echo edited >> "$R0/repo/SMOKE_FEAT.txt"
run_from "$R0/wt-dirty" "$R0/cd" >"$R0/d.log" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(main_sha)" = "$FEAT" ] && [ ! -e "$R0/cd" ] && grep -q 'main checkout at .* has uncommitted changes' "$R0/d.log" \
  && grep -q edited "$R0/repo/SMOKE_FEAT.txt" && pass "uncommitted changes in the main checkout: refused, and left as they were" \
  || { failed "dirty main: rc=$rc"; tail -n 8 "$R0/d.log" | sed 's/^/    /'; }
tgit -C "$R0/repo" checkout -q -- SMOKE_FEAT.txt
# e) --mcp-plan changes nothing, so off main it refuses instead of merging
run_from "$R0/wt-dirty" "$R0/ce" --mcp-plan >"$R0/e.log" 2>&1; rc=$?
[ "$rc" = 1 ] && [ "$(main_sha)" = "$FEAT" ] && grep -q -- '--mcp-plan changes nothing' "$R0/e.log" \
  && pass "--mcp-plan off main: refused, main not moved" || { failed "--mcp-plan off main: rc=$rc"; tail -n 5 "$R0/e.log" | sed 's/^/    /'; }
# e2) so do --print-managed-settings and --restore: main not moved, the branch checkout not switched
for fl in --print-managed-settings --restore; do
  run_from "$R0/wt-dirty" "$R0/ce" "$fl" >"$R0/e2.log" 2>&1; rc=$?
  [ "$rc" = 1 ] && [ "$(main_sha)" = "$FEAT" ] && [ "$(git -C "$R0/wt-dirty" symbolic-ref --short HEAD)" = dirty ] \
    && grep -q -- "$fl [a-z ]*nothing" "$R0/e2.log" \
    && pass "$fl off main: refused, main not moved" || { failed "$fl off main: rc=$rc"; tail -n 5 "$R0/e2.log" | sed 's/^/    /'; }
done
# f) a clone whose only checkout is on a feature branch: it switches to main and fast-forwards
tgit clone -q "$R0/remote.git" "$R0/solo" && no_auto_gc "$R0/solo" && tgit -C "$R0/solo" switch -q -c feat3
auto_gc_off "$R0/remote.git" "$R0/repo" "$R0/solo" \
  && pass "scratch clones: automatic gc and maintenance off (no detached repack races install.sh's git fsck)" \
  || failed "scratch clones: automatic gc or maintenance left on"
echo f > "$R0/solo/SMOKE_F.txt"; tgit -C "$R0/solo" add SMOKE_F.txt; tgit -C "$R0/solo" commit -q -m f3
F3="$(git -C "$R0/solo" rev-parse HEAD)"
run_from "$R0/solo" "$R0/cf" >"$R0/f.log" 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$R0/solo" symbolic-ref --short HEAD)" = main ] && [ "$(git -C "$R0/solo" rev-parse main)" = "$F3" ] \
  && [ -f "$R0/cf/.stack-manifest.json" ] && pass "single checkout on a feature branch: switched to main, fast-forwarded, installed" \
  || { failed "single checkout: rc=$rc"; tail -n 10 "$R0/f.log" | sed 's/^/    /'; }
# g) never a push: the remote is untouched, git was never asked to push, install.sh has no push
[ "$(remote_refs)" = "$REMOTE_BEFORE" ] && pass "the remote's refs are unchanged" || failed "the remote's refs CHANGED"
python3 - "$R0/git-calls.log" <<'PY' && pass "no push or send-pack among the installer's git calls" || failed "the installer ran a push-like git command"
import sys
bad = []
for line in open(sys.argv[1]):
    w, i = line.split(), 0
    while i < len(w) and w[i].startswith("-"):
        i += 2 if w[i] in ("-C", "-c") else 1
    if i < len(w) and w[i] in ("push", "send-pack"):
        bad.append(line.strip())
if bad:
    print("\n".join("    " + b for b in bad))
sys.exit(1 if bad else 0)
PY
python3 - "$HERE/install.sh" "$HERE/dot-claude/hooks" <<'PY' && pass "install.sh contains no git push" || failed "install.sh contains a git push"
import sys
sys.path.insert(0, sys.argv[2])
import agent_guard as G
bad = [l for l in open(sys.argv[1]) if not l.lstrip().startswith("#") and G.git_push_in(l)]
print("".join("    " + b for b in bad), end="")
sys.exit(1 if bad else 0)
PY
out=$(cd "$R0/repo" && bash -c 'eval "$(sed -n "/^repo_git()/,/^}/p" install.sh)"; repo_git -C . push origin main' 2>&1); rc=$?
[ "$rc" = 97 ] && printf '%s' "$out" | grep -q 'never pushes' && pass "repo_git refuses push" || failed "repo_git push guard: rc=$rc $out"
[ "$(remote_refs)" = "$REMOTE_BEFORE" ] && pass "the remote's refs are still unchanged" || failed "the remote's refs CHANGED"
# settings: worktree.baseRef is the stack's ("head"); the user's other worktree keys stay
python3 - "$R0/ca/settings.json" <<'PY'
import json, sys
s = json.load(open(sys.argv[1]))
s["worktree"] = {"baseRef": "fresh", "symlinkDirectories": ["node_modules"]}
json.dump(s, open(sys.argv[1], "w"), indent=2)
PY
run_from "$R0/repo" "$R0/ca" >"$R0/g.log" 2>&1
python3 - "$R0/ca/settings.json" <<'PY' && grep -q 'set worktree.baseRef="head"' "$R0/g.log" \
  && pass "worktree.baseRef reset to head, the user's symlinkDirectories kept" || failed "worktree settings merge"
import json, sys
w = json.load(open(sys.argv[1])).get("worktree")
sys.exit(0 if w == {"baseRef": "head", "symlinkDirectories": ["node_modules"]} else 1)
PY
assert_unchanged_real_home
drop_scratch "$R0"

echo "== 11. Code intelligence: the stack's local LSP marketplace (plugins step, fake claude)"
TL="$(scratch_dir)" || exit 1
mkdir -p "$TL/bin"
# stand-ins for the language servers (julia exits 0: LanguageServer.jl "found")
for b in haskell-language-server-wrapper lake metals julia; do printf '#!/bin/sh\nexit 0\n' > "$TL/bin/$b"; chmod +x "$TL/bin/$b"; done
lsp_run(){ PATH="$TL/bin:$PATH" FAKE_CLAUDE_LOG="$TL/calls.log" CLAUDE_CONFIG_DIR="$TL/c" \
  "$INSTALL" --no-mcp --no-deps --no-profile >"$TL/$1" 2>&1; }
lsp_run a.log
if diff -rq "$HERE/dot-claude/stack-plugins" "$TL/c/stack-plugins" >/dev/null 2>&1 \
   && grep -qF "[\"plugin\", \"marketplace\", \"add\", \"$TL/c/stack-plugins\"]" "$TL/calls.log"; then
  pass "stack-plugins copied to the config dir and registered as a directory marketplace"
else
  failed "stack marketplace not installed/registered"; tail -n 12 "$TL/a.log" | sed 's/^/    /'
fi
n=0; for p in haskell-lsp julia-lsp lean-lsp metals-lsp; do
  grep -qF "[\"plugin\", \"install\", \"$p@agent-stack\", \"--scope\", \"user\"]" "$TL/calls.log" && n=$((n + 1))
done
[ "$n" = 4 ] && pass "haskell/julia/lean/metals LSP plugins installed from agent-stack when their servers exist" \
  || failed "only $n of 4 agent-stack LSP plugins installed"
# a local edit of the installed marketplace is backed up and replaced by the next run
echo '{}' > "$TL/c/stack-plugins/plugins/lean-lsp/.claude-plugin/plugin.json"
lsp_run b.log
if diff -rq "$HERE/dot-claude/stack-plugins" "$TL/c/stack-plugins" >/dev/null 2>&1 \
   && grep -qx '{}' "$(latest_backup "$TL/c")/files/stack-plugins/plugins/lean-lsp/.claude-plugin/plugin.json" 2>/dev/null; then
  pass "re-run restores stack-plugins and keeps the edited copy in the backup"
else
  failed "stack-plugins not restored or not backed up"
fi
python3 - "$HERE/dot-claude/stack-plugins" <<'PY' && pass "every marketplace entry has a plugin.json with a strict-valid lspServers config" \
  || failed "stack-plugins manifests"
import json, os, sys
root = sys.argv[1]
m = json.load(open(os.path.join(root, ".claude-plugin", "marketplace.json")))
ALLOWED = {"command", "extensionToLanguage", "args", "transport", "env", "initializationOptions", "settings",
           "workspaceFolder", "startupTimeout", "shutdownTimeout", "restartOnCrash", "maxRestarts", "diagnostics"}
for e in m["plugins"]:
    pj = json.load(open(os.path.join(root, e["source"], ".claude-plugin", "plugin.json")))
    assert pj["name"] == e["name"], e["name"]
    for name, cfg in pj["lspServers"].items():
        assert set(cfg) <= ALLOWED, (name, set(cfg) - ALLOWED)
        assert cfg["command"] and " " not in cfg["command"], name
        assert cfg["extensionToLanguage"] and all(k.startswith(".") for k in cfg["extensionToLanguage"]), name
PY
assert_unchanged_real_home
drop_scratch "$TL"

echo "== 12. One copy of each skill: plugin duplicates of synced skills disabled by default; Anthropic skill plugins installed (fake claude)"
TD="$(scratch_dir)" || exit 1
# the fake writes enabledPlugins on install/enable/disable as the real CLI does: install.sh leaves out a
# plugin it installed before that enabledPlugins no longer names (`claude plugin uninstall`)
export FAKE_CLAUDE_PLUGINS=1
mkdir -p "$TD/c/skills/synced/0000-sync/docx" "$TD/c/skills/synced/0000-sync/skill-creator"
printf -- '---\nname: docx\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/docx/SKILL.md"
printf -- '---\nname: skill-creator\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/skill-creator/SKILL.md"
printf '{"enabledPlugins": {"document-skills@anthropic-agent-skills": true, "skill-creator@claude-plugins-official": true, "mcp-server-dev@claude-plugins-official": true}}\n' > "$TD/c/settings.json"
FAKE_CLAUDE_LOG="$TD/calls0.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile --keep-plugin-duplicates >"$TD/i0.log" 2>&1
if ! grep -qF '"disable"' "$TD/calls0.log" && ! grep -qF '"install", "document-skills@' "$TD/calls0.log" \
   && grep -qF 'plugin document-skills@anthropic-agent-skills duplicates the synced anthropic-skills:docx/xlsx/pptx/pdf in the skill listing (kept: --keep-plugin-duplicates)' "$TD/i0.log" \
   && ! grep -qF '"install", "mcp-server-dev@' "$TD/calls0.log" && ! grep -qF '"install", "skill-creator@' "$TD/calls0.log" \
   && grep -qF '["plugin", "install", "session-report@claude-plugins-official", "--scope", "user"]' "$TD/calls0.log" \
   && grep -qF '["plugin", "install", "math-olympiad@claude-plugins-official", "--scope", "user"]' "$TD/calls0.log"; then
  pass "--keep-plugin-duplicates: duplicate plugins stay enabled, each named; enabled Anthropic plugins left alone, missing ones installed"
else
  failed "plugins touched under --keep-plugin-duplicates"; grep -i plugin "$TD/i0.log" | sed 's/^/    /'
fi
FAKE_CLAUDE_LOG="$TD/calls.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile --with-extra-plugins >"$TD/i.log" 2>&1
deduped_is(){ python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("plugins_deduped") == sys.argv[2:] else 1)' "$TD/c/.stack-manifest.json" "$@"; }
BD="$(latest_backup "$TD/c")"
if grep -qF '["plugin", "disable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls.log" \
   && grep -qF '["plugin", "disable", "skill-creator@claude-plugins-official", "--scope", "user"]' "$TD/calls.log" \
   && ! grep -qF '"mcp-server-dev@' "$TD/calls.log" \
   && ! grep -qF '"install", "document-skills@' "$TD/calls.log" && ! grep -qF '"install", "skill-creator@' "$TD/calls.log" \
   && ! grep -qF '"math-olympiad@' "$TD/calls.log" \
   && python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1]))["enabledPlugins"].get("math-olympiad@claude-plugins-official") is True else 1)' "$TD/c/settings.json" \
   && grep -qF 'To undo: claude plugin enable document-skills@anthropic-agent-skills --scope user' "$TD/i.log" \
   && grep -qF 'To undo: claude plugin enable skill-creator@claude-plugins-official --scope user' "$TD/i.log" \
   && deduped_is document-skills@anthropic-agent-skills skill-creator@claude-plugins-official \
   && python3 -c 'import json, sys; sys.exit(0 if sorted(json.load(open(sys.argv[1]))["plugins_disabled"]) == sys.argv[2:] else 1)' \
        "$BD/backup.json" document-skills@anthropic-agent-skills skill-creator@claude-plugins-official; then
  pass "default (--with-extra-plugins still accepted): duplicates disabled (not installed), mcp-server-dev and math-olympiad (installed by the first run) kept enabled, undo printed, recorded in manifest and backup"
else
  failed "default plugin dedupe"; tail -n 14 "$TD/i.log" | sed 's/^/    /'
fi
rm -rf "$TD/c/skills/synced/0000-sync/docx"
FAKE_CLAUDE_LOG="$TD/calls2.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile >"$TD/i2.log" 2>&1
if grep -qF '["plugin", "enable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls2.log" \
   && ! grep -qF '"enable", "skill-creator@' "$TD/calls2.log" \
   && deduped_is skill-creator@claude-plugins-official; then
  pass "a deduped plugin is re-enabled once its synced skill is gone; the others stay disabled"
else
  failed "re-enable after the synced skill went away"; grep -i plugin "$TD/i2.log" | sed 's/^/    /'
fi
unset FAKE_CLAUDE_PLUGINS
assert_unchanged_real_home
drop_scratch "$TD"

echo "== 13. Rollback: settings the stack stops shipping are retracted through the manifest"
TR="$(scratch_dir)" || exit 1
CLAUDE_CONFIG_DIR="$TR/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1
python3 - "$TR/c/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["skillOverrides"]["my-skill"] = "off"        # the user's own override
s["skillOverrides"]["simplify"] = "on"         # the user changed a stack override
json.dump(s, open(p, "w"), indent=2)
PY
# the rollback: a stack repository whose settings.json is the older one (no listing cut, no
# overrides, no budget knobs, the old caps), committed on main as install.sh requires
cp -R "$HERE" "$TR/repo"
python3 - "$TR/repo/dot-claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
for k in ("skillListingMaxDescChars", "skillOverrides"):
    s.pop(k)
s["skillListingBudgetFraction"] = 0.025
s["autoCompactWindow"] = 800000
for k in ("STACK_MAX_FANOUT_BY_TYPE", "STACK_PROMPT_CTX_BUDGET", "STACK_SESSION_CTX_BUDGET"):
    s["env"].pop(k, None)           # the two budgets are learned limits now: not shipped either way
s["env"].update({"STACK_MAX_FANOUT": "8",
                 "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "32"})
json.dump(s, open(p, "w"), indent=2)
PY
tgit -C "$TR/repo" commit -qam "rollback" || failed "could not commit the rollback repository"
# (--yes: the config dir was installed from another repo, so the stack "changed" and there is no terminal)
CLAUDE_CONFIG_DIR="$TR/c" "$TR/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TR/r.log" 2>&1
python3 - "$TR/c/settings.json" <<'PY' && pass "rollback: stack-only keys and knobs retracted or restored, the user's own overrides kept" || { failed "rollback retraction"; grep -i 'retract\|kept' "$TR/r.log" | sed 's/^/    /'; }
import json, sys
s = json.load(open(sys.argv[1])); e = s["env"]
ok = ("skillListingMaxDescChars" not in s and s.get("skillOverrides") == {"my-skill": "off", "simplify": "on"}
      and s.get("skillListingBudgetFraction") == 0.025 and s.get("autoCompactWindow") == 800000
      and not any(k in e for k in ("STACK_MAX_FANOUT_BY_TYPE", "STACK_PROMPT_CTX_BUDGET", "STACK_SESSION_CTX_BUDGET"))
      and e.get("STACK_MAX_FANOUT") == "8" and e.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS") == "32")
if not ok:
    print("   ", json.dumps({k: s.get(k) for k in ("skillListingMaxDescChars", "skillOverrides",
                                                   "skillListingBudgetFraction", "autoCompactWindow")}))
sys.exit(0 if ok else 1)
PY
python3 -c 'import re, sys; m = re.search(r"retracted stack skillOverrides for (.*) \(no longer shipped\)", open(sys.argv[1]).read()); got = set(m.group(1).split(", ")) if m else set(); sys.exit(0 if {"code-review", "fewer-permission-prompts", "init", "keybindings-help", "security-review", "rust-async"} <= got and "simplify" not in got else 1)' "$TR/r.log" \
  && grep -q 'retracted stack setting skillListingMaxDescChars=250' "$TR/r.log" \
  && pass "rollback: each retraction is reported" || failed "rollback retraction messages: $(grep -i retract "$TR/r.log")"
assert_unchanged_real_home
drop_scratch "$TR"

echo "== 13b. skillOverrides entries an earlier version shipped are retracted per skill (block still shipped)"
TN="$(scratch_dir)" || exit 1
# the earlier version: the current settings plus two "name-only" entries (as phase 2 once shipped)
cp -R "$HERE" "$TN/repo"
python3 - "$TN/repo/dot-claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["skillOverrides"].update({"postgresql": "name-only", "mongodb": "name-only"})
json.dump(s, open(p, "w"), indent=2)
PY
tgit -C "$TN/repo" commit -qam "name-only era" || failed "could not commit the earlier repository"
CLAUDE_CONFIG_DIR="$TN/c" "$TN/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1
python3 - "$TN/c/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["skillOverrides"]["mongodb"] = "off"          # the user changed a stack entry: it stays theirs
json.dump(s, open(p, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$TN/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TN/r.log" 2>&1
python3 - "$TN/c/settings.json" "$HERE/dot-claude/settings.json" <<'PY' && pass "name-only entries no longer shipped are retracted; a changed one and the shipped ones stay" || { failed "per-skill skillOverrides retraction"; grep -i 'retract\|kept' "$TN/r.log" | sed 's/^/    /'; }
import json, sys
so = json.load(open(sys.argv[1])).get("skillOverrides", {})
want = dict(json.load(open(sys.argv[2])).get("skillOverrides", {}), mongodb="off")
if so != want:
    print("   ", json.dumps(so))
sys.exit(0 if so == want else 1)
PY
grep -q 'retracted stack skillOverrides for postgresql (no longer shipped)' "$TN/r.log" \
  && pass "per-skill retraction is reported" || failed "per-skill retraction message: $(grep -i retract "$TN/r.log")"
assert_unchanged_real_home
drop_scratch "$TN"

echo "== 13c. permissions.defaultMode: plan shipped; the earlier shipped bypassPermissions moved once, a mode you chose kept"
TP="$(scratch_dir)" || exit 1
# the earlier version shipped bypassPermissions, and its installer overwrote the mode on every run
cp -R "$HERE" "$TP/repo"
python3 - "$TP/repo/dot-claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["permissions"]["defaultMode"] = "bypassPermissions"
json.dump(s, open(p, "w"), indent=2)
PY
tgit -C "$TP/repo" commit -qam "bypassPermissions era" || failed "could not commit the earlier repository"
for c in old mine lost; do
  CLAUDE_CONFIG_DIR="$TP/$c" "$TP/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1
done
# manifests from before settings_permission_scalars (the mode comes from the recorded commit's
# settings.json); "mine" chose acceptEdits after that install; "fresh" has a settings.json of its own
# and no install yet
mkdir -p "$TP/fresh" && printf '{"permissions": {"defaultMode": "auto"}}\n' > "$TP/fresh/settings.json"
python3 - "$TP" <<'PY'
import json, os, sys
for c in ("old", "mine", "lost"):
    m = os.path.join(sys.argv[1], c, ".stack-manifest.json"); d = json.load(open(m))
    d.pop("settings_permission_scalars", None); json.dump(d, open(m, "w"), indent=2)
p = os.path.join(sys.argv[1], "mine", "settings.json"); s = json.load(open(p))
s["permissions"]["defaultMode"] = "acceptEdits"; json.dump(s, open(p, "w"), indent=2)
PY
# the upgrade: the same repository moves on to plan; the bypassPermissions commit stays in its history
tgit -C "$TP/repo" checkout -q HEAD~1 -- dot-claude/settings.json && tgit -C "$TP/repo" commit -qam "plan era" \
  || failed "could not commit the plan-era repository"
for c in old mine fresh; do
  CLAUDE_CONFIG_DIR="$TP/$c" "$TP/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TP/$c.log" 2>&1
done
dmode(){ python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("permissions", {}).get("defaultMode"))' "$1/settings.json"; }
[ "$(dmode "$TP/old")" = plan ] && grep -qF 'set permissions.defaultMode="plan" (was "bypassPermissions", the stack'"'"'s earlier default)' "$TP/old.log" \
  && grep -qF 'note: default permission mode is now plan; you were on bypassPermissions by default; Shift+Tab or ExitPlanMode to change it' "$TP/old.log" \
  && python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("settings_permission_scalars") == {"defaultMode": "plan"} else 1)' "$TP/old/.stack-manifest.json" \
  && pass "upgrade: the earlier shipped bypassPermissions becomes plan, with the notice; the manifest records plan" \
  || { failed "defaultMode upgrade from the earlier shipped value: $(dmode "$TP/old")"; grep -i 'defaultMode\|permission mode' "$TP/old.log" | sed 's/^/    /'; }
[ "$(dmode "$TP/mine")" = acceptEdits ] && grep -qF 'kept your permissions.defaultMode="acceptEdits" (the stack'"'"'s: "plan")' "$TP/mine.log" \
  && ! grep -q 'permission mode is now plan' "$TP/mine.log" \
  && [ "$(dmode "$TP/fresh")" = auto ] && grep -qF 'kept your permissions.defaultMode="auto"' "$TP/fresh.log" \
  && pass "a mode you chose (after an install, or before the first one) is kept and reported" \
  || { failed "defaultMode chosen by the user: $(dmode "$TP/mine") / $(dmode "$TP/fresh")"; grep -i 'defaultMode' "$TP/mine.log" "$TP/fresh.log" | sed 's/^/    /'; }
# back to bypassPermissions by choice: later runs keep it, and the notice does not come back
python3 - "$TP/old/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p)); s["permissions"]["defaultMode"] = "bypassPermissions"; json.dump(s, open(p, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$TP/old" "$TP/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TP/old2.log" 2>&1
[ "$(dmode "$TP/old")" = bypassPermissions ] && grep -qF 'kept your permissions.defaultMode="bypassPermissions"' "$TP/old2.log" \
  && ! grep -q 'permission mode is now plan' "$TP/old2.log" \
  && pass "bypassPermissions set back by you is kept on the next run; the notice is shown once" \
  || failed "defaultMode restored to bypassPermissions: $(dmode "$TP/old")"
# an install from a repository that lacks the recorded commit can't tell the old default from a choice: kept
CLAUDE_CONFIG_DIR="$TP/lost" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TP/lost.log" 2>&1
[ "$(dmode "$TP/lost")" = bypassPermissions ] && grep -q "can't tell the stack's earlier default from your choice" "$TP/lost.log" \
  && pass "an unknown last-install commit: bypassPermissions kept, and the installer says why" \
  || { failed "defaultMode with an unknown last-install commit: $(dmode "$TP/lost")"; grep -i 'defaultMode' "$TP/lost.log" | sed 's/^/    /'; }
# a rollback through an older installer: it rewrites the commit and the mode (bypassPermissions) but keeps
# the manifest's settings_permission_scalars it doesn't know; the record counts only for its own commit
CLAUDE_CONFIG_DIR="$TP/rb" "$TP/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile --yes >/dev/null 2>&1
python3 - "$TP/rb" "$(tgit -C "$TP/repo" rev-parse HEAD~1)" <<'PY'
import json, os, sys
m = os.path.join(sys.argv[1], ".stack-manifest.json"); d = json.load(open(m)); d["commit"] = sys.argv[2]; json.dump(d, open(m, "w"))
p = os.path.join(sys.argv[1], "settings.json"); s = json.load(open(p)); s["permissions"]["defaultMode"] = "bypassPermissions"; json.dump(s, open(p, "w"))
PY
CLAUDE_CONFIG_DIR="$TP/rb" "$TP/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TP/rb.log" 2>&1
[ "$(dmode "$TP/rb")" = plan ] && grep -q 'permission mode is now plan' "$TP/rb.log" \
  && pass "rollback through an older installer: its bypassPermissions moves to plan again" \
  || failed "stale settings_permission_scalars kept bypassPermissions: $(dmode "$TP/rb")"
assert_unchanged_real_home
drop_scratch "$TP"

echo "== 14. No copy types: install.sh renders no <type>-copy agent (retired 2026-10-04)"
TC="$(scratch_dir)" || exit 1
CLAUDE_CONFIG_DIR="$TC/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$TC/i.log" 2>&1
if ls "$TC/c/agents/"*-copy.md >/dev/null 2>&1 || grep -q -- '-copy.md' "$TC/i.log"; then
  failed "a copy-type agent was rendered: $(ls "$TC/c/agents/" | grep -- '-copy')"
else
  pass "no copy-type agent files rendered or tracked"
fi
assert_unchanged_real_home
drop_scratch "$TC"

echo "== 15. A drifted config: --dry-run, prune, one backup that restores exactly, idempotence"
TX="$(scratch_dir)" || exit 1
# one line per file or link under a config dir (relpath, kind, sha256, mode), Claude Code's own state
# aside
cat > "$TX/fingerprint.py" <<'PY'
import hashlib, os, stat, sys
root, out = sys.argv[1], []
skip = {"projects", "sessions", "statsig", "todos", "shell-snapshots", "venvs", "plugins"}
for d, dirs, files in os.walk(root):
    rel_d = os.path.relpath(d, root)
    top = rel_d.split(os.sep)[0]
    if top in skip:
        dirs[:] = []
        continue
    for f in sorted(files) + sorted(x for x in dirs if os.path.islink(os.path.join(d, x))):
        p, rel = os.path.join(d, f), os.path.normpath(os.path.join(rel_d, f))
        if rel.startswith(".install"):
            continue
        if os.path.islink(p):
            out.append("%s L %s" % (rel, os.readlink(p)))
        else:
            h = hashlib.sha256(open(p, "rb").read()).hexdigest()[:16]
            out.append("%s F %s %o" % (rel, h, stat.S_IMODE(os.stat(p).st_mode)))
print("\n".join(sorted(out)))
PY
fp(){ python3 "$TX/fingerprint.py" "$1"; }
xrun(){ local c="$1" log="$2"; shift 2
  FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile "$@" >"$log" 2>&1; }
# the list a run prints: the lines under "replaced:" and "removed: not part of the stack"
listing(){ awk '/^(removed: not part of the stack|replaced: )/{on=1; print; next} on && /^  [-~] /{print; next} {on=0}' "$1"; }
make_dirty(){ # stale, modified and unknown files; duplicated hooks and rules; junk
  local T="$1"
  printf -- '---\nname: my-own\ndescription: mine\n---\nhello\n' > "$T/agents/my-own.md"
  printf '\n<!-- local edit -->\n' >> "$T/agents/coder.md"
  cp "$T/agents/coder.md" "$T/agents/coder.md.new"
  mkdir -p "$T/agents/team"; printf -- '---\nname: team-a\ndescription: x\n---\n' > "$T/agents/team/a.md"
  # agents an earlier stack version installed (manifest hashes, written below): one unedited, one edited since
  printf -- '---\nname: retired-agent\ndescription: old\n---\n' > "$T/agents/retired-agent.md"
  printf -- '---\nname: retired-edited\ndescription: old, edited\n---\n' > "$T/agents/retired-edited.md"
  mkdir -p "$T/skills/old-skill"; printf -- '---\nname: old-skill\ndescription: old\n---\n' > "$T/skills/old-skill/SKILL.md"
  printf 'my notes\n' > "$T/skills/python-engineering/notes.md"
  printf '\nlocal tweak\n' >> "$T/skills/python-engineering/SKILL.md"
  # skills an earlier stack version installed (manifest hashes, written below): one unedited, one
  # edited since, and an unedited extra file inside a shipped skill
  mkdir -p "$T/skills/retired-skill/refs" "$T/skills/retired-edited"
  printf -- '---\nname: retired-skill\ndescription: old\n---\n' > "$T/skills/retired-skill/SKILL.md"
  printf 'old ref\n' > "$T/skills/retired-skill/refs/a.md"
  printf -- '---\nname: retired-edited\ndescription: old\n---\n' > "$T/skills/retired-edited/SKILL.md"
  printf 'my own file\n' > "$T/skills/retired-edited/mine.md"
  printf 'old ref\n' > "$T/skills/retired-edited/ref.md"
  printf 'old reference\n' > "$T/skills/python-engineering/old-ref.md"
  mkdir -p "$T/skills/synced/abc/docx"; printf -- '---\nname: docx\ndescription: synced\n---\n' > "$T/skills/synced/abc/docx/SKILL.md"
  printf '#!/bin/sh\necho mine\n' > "$T/hooks/my-hook.sh"; chmod +x "$T/hooks/my-hook.sh"
  printf '# My rule\n- be nice\n' > "$T/rules/my-rule.md"
  printf '{}' > "$T/settings.json.tmp"
  chmod 644 "$T/stack.env"                       # world-readable keys: the plan repairs the mode
  python3 - "$T/settings.json" "$T/magg/config.json" "$T/.stack-manifest.json" <<'PY'
import json, sys
sp, mp, man = sys.argv[1:4]
s = json.load(open(sp))
g = {"matcher": "Write", "hooks": [{"type": "command", "command": "/bin/echo mine"}]}
s["hooks"].setdefault("PostToolUse", []).extend([g, dict(g)])
s["hooks"]["PreToolUse"].append({"matcher": "Bash", "hooks": [
    {"type": "command", "command": "\"/usr/bin/python3\" \"/old/config/hooks/agent_guard.py\" no-push"},
    {"type": "command", "command": "/bin/echo shared"}, {"type": "command", "command": "/bin/echo shared"}]})
s["hooks"]["Notification"] = [{"hooks": [{"type": "command", "command": "\"/usr/bin/python3\" \"/old/hooks/agent_guard.py\""}]}]
s["permissions"]["allow"] += ["Bash(ls *)", "Bash(ls *)"]
s["sandbox"]["enabled"] = False
s["sandbox"]["filesystem"]["allowWrite"].append("~/my-cache")
json.dump(s, open(sp, "w"), indent=2)
m = json.load(open(mp))
m["servers"]["mine"] = {"source": "y", "command": "my-server"}
m["servers"]["docling"]["command"] = "my-docling"
m["servers"]["oldsrv"] = {"source": "z", "command": "old"}
json.dump(m, open(mp, "w"), indent=2)
mf = json.load(open(man))
mf.setdefault("magg_shipped", {})["oldsrv"] = "0000000000000000"
import hashlib, os
c = os.path.dirname(man)
h = lambda rel: hashlib.sha256(open(os.path.join(c, rel), "rb").read()).hexdigest()
for rel in ("skills/retired-skill/SKILL.md", "skills/retired-skill/refs/a.md", "skills/python-engineering/old-ref.md",
            "skills/retired-edited/ref.md", "agents/retired-agent.md"):
    mf["files"][rel] = h(rel)                                   # installed by the stack, unedited
mf["files"]["skills/retired-edited/SKILL.md"] = "0" * 64       # installed by the stack, edited since
mf["files"]["agents/retired-edited.md"] = "0" * 64
json.dump(mf, open(man, "w"), indent=2, sort_keys=True)
PY
}
xrun "$TX/c" "$TX/0.log" && fp "$TX/c" > "$TX/fp.clean" || failed "15: clean install failed"
make_dirty "$TX/c"
fp "$TX/c" > "$TX/fp.dirty"; nb0=$(count_backups "$TX/c")
xrun "$TX/c" "$TX/dry.log" --dry-run; rc=$?
fp "$TX/c" > "$TX/fp.dry"
[ "$rc" = 0 ] && cmp -s "$TX/fp.dirty" "$TX/fp.dry" && [ "$(count_backups "$TX/c")" = "$nb0" ] \
  && grep -q 'Dry run done: nothing was changed' "$TX/dry.log" \
  && pass "--dry-run over a drifted config changes nothing and makes no backup" \
  || failed "--dry-run changed something (rc=$rc): $(diff "$TX/fp.dirty" "$TX/fp.dry" | head -5)"
xrun "$TX/c" "$TX/real.log"; rc=$?
B15="$(latest_backup "$TX/c")"
listing "$TX/dry.log" > "$TX/list.dry"; listing "$TX/real.log" > "$TX/list.real"
[ "$rc" = 0 ] && [ -s "$TX/list.real" ] && cmp -s "$TX/list.dry" "$TX/list.real" \
  && pass "the real run lists exactly what --dry-run listed" || failed "dry-run list != real list: $(diff "$TX/list.dry" "$TX/list.real" | head -6)"
missing=""
while IFS= read -r want; do
  grep -qxF -- "$want" "$TX/real.log" || missing="$missing
    $want"
done <<'EOF_WANT'
removed: not part of the stack
  - agents/retired-agent.md  (no longer shipped by the stack)
  - settings.json.tmp  (leftover of an interrupted install)
  - skills/python-engineering/old-ref.md  (no longer part of the stack's python-engineering skill)
  - skills/retired-edited/ref.md  (no longer shipped by the stack)
  - skills/retired-skill/  (no longer shipped by the stack)
  - magg catalog: oldsrv  (no longer shipped by the stack)
  - settings.json hooks.PreToolUse[Bash]: "/usr/bin/python3" "/old/config/hooks/agent_guard.py" no-push  (an earlier copy of the stack's guard hook; the current one replaces it)
  - settings.json hooks.Notification: "/usr/bin/python3" "/old/hooks/agent_guard.py"  (the stack's guard no longer runs on it)
  - settings.json hooks  (2 duplicate hook entries)
  - settings.json permissions.allow  (1 duplicate rule)
  ~ agents/coder.md  (edited since the last install)
  ~ skills/python-engineering/SKILL.md  (edited since the last install)
  ~ magg catalog: docling  (differed from the stack's entry)
  note: agents/coder.md.new: kept (not installed by the stack: yours)
  note: agents/my-own.md: kept (not installed by the stack: yours)
  note: agents/retired-edited.md: kept (edited since the stack installed it)
  note: agents/team/a.md: kept (not installed by the stack: yours)
  note: skills/old-skill/: kept (not installed by the stack: yours or another tool's)
  note: skills/python-engineering/notes.md: kept (not installed by the stack: yours)
  note: skills/retired-edited/SKILL.md: kept (edited since the stack installed it)
  note: skills/retired-edited/mine.md: kept (not installed by the stack: yours)
EOF_WANT
[ -z "$missing" ] && pass "pruned and listed: stale, modified, unknown files, junk, magg entries, duplicate hooks and rules" \
  || { failed "listing is missing:$missing"; sed 's/^/    /' "$TX/list.real"; }
python3 - "$TX/c" "$HERE" "$B15" "$BK_ROOT" "$EXPECTED_AGENTS" <<'PY' && pass "after the prune: the stack's agents and skills plus the user's own and edited ones, user hook/rule/magg entry kept, no duplicates, sandbox on, stack.env 0600, backup 0700/0600" || failed "post-prune state (see above)"
import json, os, stat, sys
c, here, b, bk, n_agents = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
bad = []
def check(ok, what):
    if not ok:
        bad.append(what)
mode = lambda p: stat.S_IMODE(os.lstat(p).st_mode)
agents = sorted(os.listdir(os.path.join(c, "agents")))
extra = sorted(a for a in agents if not os.path.isfile(os.path.join(here, "dot-claude", "agents", a)))
check(len(agents) == n_agents + 4 and extra == ["coder.md.new", "my-own.md", "retired-edited.md", "team"],
      "agents/ beyond the stack's: %s" % extra)
check("<!-- local edit -->" not in open(os.path.join(c, "agents", "coder.md")).read(), "coder.md edit kept")
shipped = sorted(d for d in os.listdir(os.path.join(here, "dot-claude", "skills")) if os.path.isdir(os.path.join(here, "dot-claude", "skills", d)))
check(sorted(os.listdir(os.path.join(c, "skills"))) == sorted(shipped + ["synced", "old-skill", "retired-edited"]),
      "skills/ != shipped + synced + the user's two")
check(os.path.isfile(os.path.join(c, "skills", "old-skill", "SKILL.md")), "an untracked skill of the user's removed")
check(sorted(os.listdir(os.path.join(c, "skills", "retired-edited"))) == ["SKILL.md", "mine.md"], "retired-edited: %s"
      % os.listdir(os.path.join(c, "skills", "retired-edited")))
check(not os.path.exists(os.path.join(c, "skills", "python-engineering", "old-ref.md")), "an unedited stack leftover kept")
check(os.path.isfile(os.path.join(c, "skills", "synced", "abc", "docx", "SKILL.md")), "synced skill touched")
check(open(os.path.join(c, "skills", "python-engineering", "notes.md")).read() == "my notes\n", "the user's file in a skill removed")
check("local tweak" not in open(os.path.join(c, "skills", "python-engineering", "SKILL.md")).read(), "skill edit kept")
check(os.path.isfile(os.path.join(c, "hooks", "my-hook.sh")) and os.path.isfile(os.path.join(c, "rules", "my-rule.md")),
      "the user's own hook or rule removed")
s = json.load(open(os.path.join(c, "settings.json")))
for ev, groups in s["hooks"].items():
    canon = [json.dumps(g, sort_keys=True) for g in groups]
    check(len(canon) == len(set(canon)), "duplicate hook groups in %s" % ev)
    for g in groups:
        cmds = [json.dumps(h, sort_keys=True) for h in g.get("hooks", [])]
        check(len(cmds) == len(set(cmds)), "duplicate hooks in a %s group" % ev)
check("/old/" not in json.dumps(s["hooks"]) and "Notification" not in s["hooks"], "stale guard hooks kept")
check(any("/bin/echo mine" in json.dumps(g) for g in s["hooks"].get("PostToolUse", [])), "the user's own hook group lost")
for k, v in s["permissions"].items():
    if isinstance(v, list):
        check(len(v) == len(set(v)), "duplicate permissions.%s" % k)
check(s["sandbox"]["enabled"] is True and "~/my-cache" in s["sandbox"]["filesystem"]["allowWrite"], "sandbox merge")
m = json.load(open(os.path.join(c, "magg", "config.json")))["servers"]
check("mine" in m and "oldsrv" not in m and m["docling"]["command"] != "my-docling", "magg: %s" % sorted(m))
check(mode(os.path.join(c, "stack.env")) == 0o600, "stack.env mode %o" % mode(os.path.join(c, "stack.env")))
check(mode(b) == 0o700, "backup dir mode")
for root, dirs, files in os.walk(os.path.join(b, "files")):
    for d in dirs:
        check(mode(os.path.join(root, d)) == 0o700, "backup subdir mode")
    for f in files:
        p = os.path.join(root, f)
        check(os.path.islink(p) or mode(p) == 0o600, "backup file %s mode %o" % (f, mode(p)))
if bad:
    print("   ", "\n    ".join(bad))
sys.exit(1 if bad else 0)
PY
fp "$TX/c" > "$TX/fp.pruned"; nb1=$(count_backups "$TX/c")
xrun "$TX/c" "$TX/again.log"
cmp -s "$TX/fp.pruned" <(fp "$TX/c") && [ "$(count_backups "$TX/c")" = "$nb1" ] \
  && grep -q 'no changes: the config dir already matches this stack version' "$TX/again.log" \
  && pass "second run after the prune: no changes, no backup" || failed "second run after the prune changed something"
xrun "$TX/c" "$TX/dry2.log" --dry-run
grep -q 'no changes: the config dir already matches this stack version' "$TX/dry2.log" && cmp -s "$TX/fp.pruned" <(fp "$TX/c") \
  && pass "--dry-run on an up-to-date config: no changes" || failed "--dry-run on an up-to-date config"
xrun "$TX/c" "$TX/rdry.log" --restore latest --dry-run
cmp -s "$TX/fp.pruned" <(fp "$TX/c") && [ "$(count_backups "$TX/c")" = "$nb1" ] && grep -q 'Dry run done: nothing was restored' "$TX/rdry.log" \
  && pass "--restore --dry-run prints the plan and restores nothing" || failed "--restore --dry-run changed something"
xrun "$TX/c" "$TX/restore.log" --restore latest; rc=$?
fp "$TX/c" > "$TX/fp.restored"
[ "$rc" = 0 ] && cmp -s "$TX/fp.dirty" "$TX/fp.restored" && grep -q "restoring $B15" "$TX/restore.log" \
  && grep -q 'undo this restore:' "$TX/restore.log" \
  && pass "--restore latest puts the drifted config back byte- and mode-exactly" \
  || failed "restore not exact (rc=$rc): $(diff "$TX/fp.dirty" "$TX/fp.restored" | head -8)"
xrun "$TX/c" "$TX/reprune.log"
cmp -s "$TX/fp.pruned" <(fp "$TX/c") && pass "installing again after the restore gives the same pruned config" \
  || failed "re-install after restore differs: $(diff "$TX/fp.pruned" <(fp "$TX/c") | head -5)"
# a replaced MCP entry whose `claude mcp remove` fails (already gone): the restore goes on (set -e)
BM="$(latest_backup "$TX/c")"
STACK_MCP_ENTRY='{"type": "http", "url": "https://example.invalid/mcp"}' \
  python3 "$HERE/lib/install_state.py" record "$BM" mcp_replaced smoke-mcp
python3 "$HERE/lib/install_state.py" record "$BM" plugins_disabled smoke-plugin@smoke
FAKE_CLAUDE_FAIL_REMOVE=1 xrun "$TX/c" "$TX/rmcp.log" --restore "$BM"; rc=$?
[ "$rc" = 0 ] && grep -q '+ put back MCP server smoke-mcp' "$TX/rmcp.log" && grep -q '+ re-enabled plugin smoke-plugin@smoke' "$TX/rmcp.log" \
  && grep -q 'undo this restore:' "$TX/rmcp.log" \
  && pass "--restore goes on when claude mcp remove fails: entry put back, plugin re-enabled, undo printed" \
  || { failed "--restore stopped at a failing claude mcp remove (rc=$rc)"; tail -n 6 "$TX/rmcp.log" | sed 's/^/    /'; }
xrun "$TX/c" "$TX/reprune2.log"
# a backup.json that names paths outside the config scope is refused before anything changes
BEVIL="$(latest_backup "$TX/c")"
python3 - "$BEVIL/backup.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m["reason"] = "install"
m["added"] = ["../outside.txt"]
json.dump(m, open(sys.argv[1], "w"))
PY
touch "$TX/outside.txt"
xrun "$TX/c" "$TX/evil.log" --restore "$BEVIL"; rc=$?
[ "$rc" != 0 ] && [ -f "$TX/outside.txt" ] && grep -q 'outside the config scope' "$TX/evil.log" && cmp -s "$TX/fp.pruned" <(fp "$TX/c") \
  && pass "--restore refuses a backup.json naming paths outside the config scope" || failed "path traversal through backup.json (rc=$rc)"
# a stack script symlinked out of the config dir (a dev checkout): never written through — not by
# --dry-run, not by the real run, which replaces the link with the stack's file (the backup keeps it)
mkdir -p "$TX/outside"; printf 'mine\n' > "$TX/outside/doctor.sh"; chmod 644 "$TX/outside/doctor.sh"
rm -f "$TX/c/bin/doctor.sh"; ln -s "$TX/outside/doctor.sh" "$TX/c/bin/doctor.sh"
xrun "$TX/c" "$TX/ln-dry.log" --dry-run; xrun "$TX/c" "$TX/ln.log"
BL="$(latest_backup "$TX/c")"
[ "$(cat "$TX/outside/doctor.sh")" = mine ] && [ "$(fmode "$TX/outside/doctor.sh")" = 0o644 ] \
  && [ ! -L "$TX/c/bin/doctor.sh" ] && [ -x "$TX/c/bin/doctor.sh" ] && [ "$(readlink "$BL/files/bin/doctor.sh")" = "$TX/outside/doctor.sh" ] \
  && pass "a symlinked stack script: the link's target is never written; the link is replaced and kept in the backup" \
  || failed "symlinked bin/doctor.sh written through or not replaced"
# a symlinked config dir: --dry-run renders the same paths as the real run
mkdir -p "$TX/lreal"; ln -s "$TX/lreal" "$TX/l"
xrun "$TX/l" "$TX/l1.log"; xrun "$TX/l" "$TX/l2.log" --dry-run
grep -q 'no changes: the config dir already matches this stack version' "$TX/l2.log" \
  && pass "symlinked config dir: --dry-run after a real run reports no changes" || failed "symlinked config dir: dry-run differs from the real run"
# --print-managed-settings: JSON only on stdout, nothing installed, no claude needed
out="$(CLAUDE_CONFIG_DIR="$TX/m" PATH="/usr/bin:/bin" "$INSTALL" --print-managed-settings 2>"$TX/m.err")"; rc=$?
printf '%s' "$out" | python3 -c 'import json, sys; d = json.load(sys.stdin); sys.exit(0 if d["hooks"]["PreToolUse"] and d["permissions"]["deny"] and d["sandbox"]["enabled"] and d["sandbox"]["failIfUnavailable"] is True and "__" not in json.dumps(d) and any("gh/hosts.yml" in r for r in d["permissions"]["deny"]) else 1)' \
  && [ "$rc" = 0 ] && [ ! -e "$TX/m" ] && grep -q 'install it yourself' "$TX/m.err" \
  && pass "--print-managed-settings: valid JSON on stdout, instructions on stderr, nothing written" \
  || failed "--print-managed-settings (rc=$rc): $(printf '%s' "$out" | head -c 200)"
help="$("$INSTALL" --help)"
for f in --dry-run --restore --print-managed-settings --keep-plugin-duplicates --force; do
  printf '%s\n' "$help" | grep -q -- "$f" || failed "--help does not mention $f"
done
printf '%s\n' "$help" | grep -q -- '--no-prune' && failed "--help still mentions the removed --no-prune"
printf '%s\n' "$help" | grep -q 'removed: not part of the stack\|backed up' && pass "--help documents the new flags and the backup" \
  || failed "--help lacks the prune/backup paragraph"

echo "== 16. Hardening: manifest paths, symlinked scope dirs, the backup root, restored links, the shipped commit"
# N-MANIFEST: a manifest key that climbs out of the staging dir stops the install before anything changes
xrun "$TX/v" "$TX/v0.log"
python3 - "$TX/v/.stack-manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m["files"]["hooks/../../../../victim.txt"] = "0" * 64     # relative to the staging dir: $XDG_STATE_HOME
json.dump(m, open(sys.argv[1], "w"))
PY
printf 'keep\n' > "$XDG_STATE_HOME/victim.txt"
fp "$TX/v" > "$TX/fp.v"
xrun "$TX/v" "$TX/v1.log"; rc=$?
[ "$rc" != 0 ] && [ "$(cat "$XDG_STATE_HOME/victim.txt")" = keep ] && cmp -s "$TX/fp.v" <(fp "$TX/v") \
  && grep -q 'names paths outside the stack' "$TX/v1.log" \
  && pass "a manifest key with .. stops the install; the file it names and the config dir are untouched" \
  || failed "manifest traversal (rc=$rc): $(grep -i 'manifest\|refus' "$TX/v1.log" | head -3)"
rm -f "$XDG_STATE_HOME/victim.txt"
# a manifest key that names a whole scope dir ("bin", "mcp") stops the install too: nothing is wiped
python3 - "$TX/v/.stack-manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
m["files"] = {k: v for k, v in m["files"].items() if ".." not in k}
m["files"]["bin"] = m["files"]["mcp"] = "0" * 64
json.dump(m, open(sys.argv[1], "w"))
PY
fp "$TX/v" > "$TX/fp.v2"
xrun "$TX/v" "$TX/v2.log"; rc=$?; xrun "$TX/v" "$TX/v3.log" --dry-run; rc3=$?
[ "$rc" != 0 ] && [ "$rc3" != 0 ] && cmp -s "$TX/fp.v2" <(fp "$TX/v") && grep -q "names paths outside the stack.*'bin'" "$TX/v2.log" \
  && [ -f "$TX/v/bin/doctor.sh" ] && [ -f "$TX/v/mcp/libdocs_mcp.py" ] \
  && pass "a manifest key naming a whole scope dir (bin, mcp) stops the install (and --dry-run); nothing is wiped" \
  || failed "bare scope-dir manifest keys (rc=$rc/$rc3): $(grep -i 'manifest\|refus' "$TX/v2.log" | head -3)"
# a per-skill symlink (skills/ itself a real dir) is replaced by the stack's skill: the run and
# --dry-run agree; the link's target is never written (the backup keeps the link)
xrun "$TX/k" "$TX/k0.log"
mkdir -p "$TX/outK"; cp -R "$TX/k/skills/python-engineering/." "$TX/outK/"; printf '\nmine\n' >> "$TX/outK/SKILL.md"
rm -rf "$TX/k/skills/python-engineering"; ln -s "$TX/outK" "$TX/k/skills/python-engineering"
fp "$TX/outK" > "$TX/fp.k0"
xrun "$TX/k" "$TX/k1.log" --dry-run; rcd=$?
xrun "$TX/k" "$TX/k2.log"; rc=$?
BK="$(latest_backup "$TX/k")"
[ "$rcd" = 0 ] && [ "$rc" = 0 ] && cmp -s "$TX/fp.k0" <(fp "$TX/outK") \
  && [ -d "$TX/k/skills/python-engineering" ] && [ ! -L "$TX/k/skills/python-engineering" ] \
  && [ -f "$TX/k/skills/python-engineering/SKILL.md" ] && [ -L "$BK/files/skills/python-engineering" ] \
  && pass "a per-skill symlink: the stack's skill replaces the link (the run and --dry-run agree); its target is untouched" \
  || failed "per-skill symlink (rc=$rc, dry=$rcd): $(grep -i 'refus' "$TX/k1.log" "$TX/k2.log" | head -3)"
# N-SYMLINK: a symlinked skills/ (a dotfiles checkout) is never pruned; without --write-through-links the run stops
xrun "$TX/y" "$TX/y0.log"
mkdir -p "$TX/outS"; cp -R "$TX/y/skills/." "$TX/outS/"
printf 'precious\n' > "$TX/outS/precious.txt"; mkdir -p "$TX/outS/user-owned"; printf 'x\n' > "$TX/outS/user-owned/SKILL.md"
printf '\n<!-- my edit -->\n' >> "$TX/outS/python-engineering/SKILL.md"
rm -rf "$TX/y/skills"; ln -s "$TX/outS" "$TX/y/skills"
fp "$TX/outS" > "$TX/fp.o0"; fp "$TX/y" > "$TX/fp.y0"; nby=$(count_backups "$TX/y")
xrun "$TX/y" "$TX/y1.log"; rc=$?
[ "$rc" != 0 ] && cmp -s "$TX/fp.o0" <(fp "$TX/outS") && cmp -s "$TX/fp.y0" <(fp "$TX/y") && [ "$(count_backups "$TX/y")" = "$nby" ] \
  && grep -q 'rerun with --write-through-links' "$TX/y1.log" \
  && pass "symlinked skills/: without --write-through-links the run stops; nothing changes on either side" || failed "symlinked skills/ without --write-through-links (rc=$rc)"
xrun "$TX/y" "$TX/y2.log" --dry-run; rc=$?
[ "$rc" != 0 ] && cmp -s "$TX/fp.o0" <(fp "$TX/outS") && cmp -s "$TX/fp.y0" <(fp "$TX/y") \
  && grep -q "skills/ is a symlink to $(cd "$TX/outS" && pwd -P)" "$TX/y2.log" \
  && grep -q 'skills/precious.txt: kept' "$TX/y2.log" && ! grep -q '^  - skills/' "$TX/y2.log" \
  && grep -q 'the real run would stop: symlinked dir(s) above: rerun with --write-through-links' "$TX/y2.log" \
  && pass "symlinked skills/: --dry-run shows the plan (nothing removed there, what it keeps), then exits 1 like the real run" \
  || failed "symlinked skills/ --dry-run (rc=$rc): $(grep -i 'would stop\|dry run done' "$TX/y2.log")"
xrun "$TX/y" "$TX/y2b.log" --dry-run --write-through-links; rc=$?
[ "$rc" = 0 ] && ! grep -q 'would stop' "$TX/y2b.log" && grep -q 'Dry run done' "$TX/y2b.log" \
  && pass "symlinked skills/: --dry-run --write-through-links exits 0" || failed "--dry-run --write-through-links (rc=$rc)"
xrun "$TX/y" "$TX/y3.log" --write-through-links; rc=$?
BY="$(latest_backup "$TX/y")"
[ "$rc" = 0 ] && [ -L "$TX/y/skills" ] && [ -f "$TX/outS/precious.txt" ] && [ -f "$TX/outS/user-owned/SKILL.md" ] \
  && ! grep -q 'my edit' "$TX/outS/python-engineering/SKILL.md" && grep -q 'my edit' "$BY/files/skills/python-engineering/SKILL.md" \
  && pass "symlinked skills/ with --write-through-links: the stack's files written through the link (backed up), nothing of yours removed" \
  || failed "symlinked skills/ --write-through-links (rc=$rc)"
# the same for agents/
xrun "$TX/y" "$TX/y4.log" --write-through-links
mkdir -p "$TX/outA"; cp -R "$TX/y/agents/." "$TX/outA/"; printf -- '---\nname: mine\ndescription: x\n---\n' > "$TX/outA/mine.md"
rm -rf "$TX/y/agents"; ln -s "$TX/outA" "$TX/y/agents"
xrun "$TX/y" "$TX/y5.log"; rc5=$?; xrun "$TX/y" "$TX/y6.log" --write-through-links; rc6=$?
[ "$rc5" != 0 ] && [ "$rc6" = 0 ] && [ -f "$TX/outA/mine.md" ] && [ -L "$TX/y/agents" ] \
  && pass "symlinked agents/: stops without --write-through-links; with it, your agent there stays" || failed "symlinked agents/ (rc=$rc5/$rc6)"
printf 'my coder\n' > "$TX/my-coder.md"; rm -f "$TX/outA/coder.md"; ln -s "$TX/my-coder.md" "$TX/outA/coder.md"
xrun "$TX/y" "$TX/y6b.log" --write-through-links; rc=$?
[ "$rc" = 0 ] && [ -L "$TX/outA/coder.md" ] && [ "$(readlink "$TX/outA/coder.md")" = "$TX/my-coder.md" ] \
  && [ "$(cat "$TX/my-coder.md")" = "my coder" ] \
  && grep -q 'agents/coder.md: kept (a link inside your symlinked agents/)' "$TX/y6b.log" \
  && pass "a file link inside a symlinked agents/: stays your link, its target never written (named in the notes)" \
  || failed "file link inside symlinked agents/ (rc=$rc): $(grep -i 'coder.md' "$TX/y6b.log" | head -3)"
# --force without --restore is a usage error: it never writes through a link
xrun "$TX/y" "$TX/y7.log" --force; rc=$?
[ "$rc" = 2 ] && grep -q -- '--force works only with --restore' "$TX/y7.log" \
  && pass "a symlinked dir with --force alone stops (a usage error)" || failed "symlinked dir with --force alone (rc=$rc)"
xrun "$TX/y" "$TX/y8.log" --write-through-links
mkdir -p "$TX/outS2"; cp -R "$TX/y/skills/." "$TX/outS2/" 2>/dev/null
rm -rf "$TX/y/skills"; ln -s "$TX/outS2" "$TX/y/skills"
# a link inside the symlinked skills/ (skills/python-engineering -> pe-local, yours): never written
# through (the file there would be unsaved), named in the notes; a restore of that run removes nothing of it
rm -rf "$TX/outS2/pe-local"; mv "$TX/outS2/python-engineering" "$TX/outS2/pe-local"
printf 'my own pe\n' > "$TX/outS2/pe-local/SKILL.md"; ln -s pe-local "$TX/outS2/python-engineering"
fp "$TX/outS2/pe-local" > "$TX/fp.pl"
printf '\nedited\n' >> "$TX/y/rules/claude-agent-stack.md"      # so this run makes a backup of its own
xrun "$TX/y" "$TX/y10.log" --write-through-links; rc=$?
BY2="$(latest_backup "$TX/y")"
xrun "$TX/y" "$TX/y11.log" --restore "$BY2"; rcr=$?
[ "$rc" = 0 ] && [ "$rcr" = 0 ] && cmp -s "$TX/fp.pl" <(fp "$TX/outS2/pe-local") \
  && [ "$(readlink "$TX/outS2/python-engineering")" = pe-local ] \
  && grep -q 'skills/python-engineering: kept (a link inside your symlinked skills/)' "$TX/y10.log" \
  && [ "$(grep -c 'skills/python-engineering: kept' "$TX/y10.log")" = 1 ] \
  && pass "a link inside a symlinked skills/: its target is never written, and a restore leaves it alone" \
  || failed "link inside symlinked skills/ (rc=$rc/$rcr): $(grep -i 'python-engineering\|refus' "$TX/y10.log" "$TX/y11.log" | head -4)"
# L4 + L1: the backup root must be a real directory (a symlink there is refused); the working copy
# (stack.env included) lives inside it, and a --dry-run that created the root removes it again
mkdir -p "$SCRATCH_ROOT/st-l4" "$TX/elsewhere"; ln -s "$TX/elsewhere" "$SCRATCH_ROOT/st-l4/claude-agent-stack-backups"
XDG_STATE_HOME="$SCRATCH_ROOT/st-l4" xrun "$TX/y" "$TX/l4.log" --dry-run --write-through-links; rc=$?
[ "$rc" != 0 ] && grep -q 'is a symlink or not a directory' "$TX/l4.log" && [ -z "$(ls -A "$TX/elsewhere")" ] \
  && pass "a symlinked backup root is refused, never followed" || failed "symlinked backup root (rc=$rc)"
XDG_STATE_HOME="$SCRATCH_ROOT/st-fresh" xrun "$TX/w" "$TX/w.log" --dry-run; rc=$?
[ "$rc" = 0 ] && grep -q "staged in $SCRATCH_ROOT/st-fresh/claude-agent-stack-backups/.work." "$TX/w.log" \
  && [ ! -e "$SCRATCH_ROOT/st-fresh/claude-agent-stack-backups" ] \
  && pass "the working copy lives in the private backup root; a --dry-run that created the root removes it" \
  || failed "work dir location / dry-run leftovers (rc=$rc): $(grep 'staged in' "$TX/w.log")"
# L2: a saved symlink whose target leaves the config dir comes back only with --force (a link where a
# stack agent goes: the install replaces it, the backup keeps the link; a link of yours under another
# name is never removed, so it never needs restoring)
xrun "$TX/r" "$TX/r0.log"
printf 'ext\n' > "$TX/ext-target.md"; rm -f "$TX/r/agents/coder.md"; ln -s "$TX/ext-target.md" "$TX/r/agents/coder.md"
xrun "$TX/r" "$TX/r1.log"; BR="$(latest_backup "$TX/r")"
xrun "$TX/r" "$TX/r2.log" --restore "$BR"; rc2=$?
skipped=0; [ -f "$TX/r/agents/coder.md" ] && [ ! -L "$TX/r/agents/coder.md" ] && grep -q 'skipped agents/coder.md: it was a link to' "$TX/r2.log" && skipped=1
xrun "$TX/r" "$TX/r3.log" --restore "$BR" --force; rc3=$?
[ "$rc2" = 0 ] && [ "$skipped" = 1 ] && [ "$rc3" = 0 ] && [ "$(readlink "$TX/r/agents/coder.md")" = "$TX/ext-target.md" ] \
  && pass "restore: a link pointing outside the config dir is skipped (named), restored with --force" \
  || failed "restore of an outside link (rc=$rc2/$rc3, skipped=$skipped)"
# N-SUPPLY: the manifest records the shipped commit; an older one shows the guard/settings changes since
head_full="$(git -C "$HERE" rev-parse HEAD)"
python3 -c 'import json, sys; sys.exit(0 if json.load(open(sys.argv[1])).get("commit") == sys.argv[2] else 1)' \
  "$TX/r/.stack-manifest.json" "$head_full" && pass "the manifest records the installed commit" || failed "manifest commit missing"
set_commit(){ python3 - "$TX/r/.stack-manifest.json" "$1" <<'PY'
import json, sys
m = json.load(open(sys.argv[1])); m["commit"] = sys.argv[2]; json.dump(m, open(sys.argv[1], "w"))
PY
}
# an "earlier install": a commit (off every branch) whose guard, an agent and a requirements file
# differ from HEAD's (R3-SUPPLY: the whole shipped tree counts, not only the guard and settings)
blob="$(printf '# an earlier file\n' | tgit -C "$HERE" hash-object -w --stdin)"
GIT_INDEX_FILE="$TX/idx" tgit -C "$HERE" read-tree HEAD
for f in dot-claude/hooks/agent_guard.py dot-claude/agents/coder.md requirements/sci.in lib/stack.env.example \
         assets/blackcat-hero.jpg; do
  GIT_INDEX_FILE="$TX/idx" tgit -C "$HERE" update-index --cacheinfo "100755,$blob,$f"
done
old_commit="$(tgit -C "$HERE" commit-tree "$(GIT_INDEX_FILE="$TX/idx" tgit -C "$HERE" write-tree)" -p HEAD -m earlier </dev/null)"
set_commit "$old_commit"
xrun "$TX/r" "$TX/s1.log" --dry-run
set_commit "0123456789abcdef0123456789abcdef01234567"
xrun "$TX/r" "$TX/s2.log" --dry-run
grep -q "changes to the stack's shipped files and installer since the last install" "$TX/s1.log" \
  && grep -q 'dot-claude/hooks/agent_guard.py' "$TX/s1.log" && grep -q 'dot-claude/agents/coder.md' "$TX/s1.log" \
  && grep -q 'requirements/sci.in' "$TX/s1.log" && grep -q 'lib/stack.env.example' "$TX/s1.log" \
  && ! grep -q 'blackcat-hero' "$TX/s1.log" && grep -q "which this repo doesn't have" "$TX/s2.log" \
  && pass "an install shows the diff of everything it ships since the recorded commit, not the README images (and warns on an unknown one)" \
  || failed "supply-chain diff: $(grep -i 'since the last install\|repo doesn' "$TX/s1.log" "$TX/s2.log" | head -3)"
# on a terminal the run asks before applying those changes: "n" applies nothing, --yes doesn't ask
cat > "$TX/tty_run.py" <<'PY'
import os, select, subprocess, sys
# answers: comma-separated, one per [y/N] question in order (the target question comes first)
answers, log, argv = sys.argv[1].encode().split(b","), sys.argv[2], sys.argv[3:]
m, s = os.openpty()
p = subprocess.Popen(argv, stdin=s, stdout=s, stderr=s, close_fds=True)
buf, answered = b"", 0
while True:                  # the slave stays open here: no EIO while the child's output is read
    r, _, _ = select.select([m], [], [], 0.5)
    if m in r:
        buf += os.read(m, 65536)
        if answered < len(answers) and buf.count(b"[y/N]") > answered:
            os.write(m, answers[answered] + b"\n")
            answered += 1
    elif p.poll() is not None:
        break
os.close(s)
rc = p.wait()
open(log, "wb").write(buf)
sys.exit(rc)
PY
set_commit "$old_commit"; nb=$(count_backups "$TX/r"); fp "$TX/r" > "$TX/fp.s0"
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/tty_run.py" y,n "$TX/s3.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile; rc3=$?
cmp -s "$TX/fp.s0" <(fp "$TX/r") && [ "$(count_backups "$TX/r")" = "$nb" ]; same3=$?
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/tty_run.py" n "$TX/s4.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes; rc4=$?
[ "$rc3" != 0 ] && grep -q 'The stack changed since the last install' "$TX/s3.log" \
  && grep -q 'stopped before changing anything. Nothing in' "$TX/s3.log" && ! grep -q '2/11' "$TX/s3.log" \
  && [ "$same3" = 0 ] && [ "$rc4" = 0 ] && ! grep -q 'The stack changed since the last install' "$TX/s4.log" \
  && pass "on a terminal: changed stack files are confirmed before step 2 ('n' changes nothing; --yes skips the question)" \
  || failed "supply-chain confirmation (rc=$rc3/$rc4, unchanged after 'n': $same3): $(grep -ai 'stack changed since\|stopped before' "$TX/s3.log" "$TX/s4.log" | head -3)"
# R4: no terminal at all (stdin /dev/null, no controlling terminal): the run stops unless --yes
cat > "$TX/noctty_run.py" <<'PY'
import subprocess, sys
log, argv = sys.argv[1], sys.argv[2:]
with open(log, "wb") as out:
    sys.exit(subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                            start_new_session=True).returncode)
PY
# R4: stderr piped (`2>&1 | tee`) and stdin /dev/null, but a controlling terminal: asked there
cat > "$TX/ctty_run.py" <<'PY'
import fcntl, os, select, subprocess, sys, termios
answer, log, argv = sys.argv[1].encode(), sys.argv[2], sys.argv[3:]
m, s = os.openpty()


def own_terminal():
    os.setsid()
    fcntl.ioctl(s, termios.TIOCSCTTY, 0)


out = open(log + ".out", "wb")
p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                     preexec_fn=own_terminal, pass_fds=(s,))
buf, answered = b"", False
while True:
    r, _, _ = select.select([m], [], [], 0.5)
    data = b""
    if m in r:
        try:
            data = os.read(m, 65536)        # a terminal hung up when its session ends: EOF or EIO
        except OSError:
            pass
        buf += data
        if not answered and b"[y/N]" in buf:
            os.write(m, answer + b"\n")
            answered = True
    if not data and p.poll() is not None:
        break
os.close(s)
rc = p.wait()
open(log, "wb").write(buf)
sys.exit(rc)
PY
set_commit "$old_commit"; nb=$(count_backups "$TX/r"); fp "$TX/r" > "$TX/fp.s5"
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/noctty_run.py" "$TX/s5.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile; rc5=$?
cmp -s "$TX/fp.s5" <(fp "$TX/r") && [ "$(count_backups "$TX/r")" = "$nb" ]; same5=$?
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/noctty_run.py" "$TX/s6.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes; rc6=$?
[ "$rc5" != 0 ] && [ "$same5" = 0 ] && grep -q 'no terminal to ask: rerun with --yes' "$TX/s5.log" && ! grep -q '2/11' "$TX/s5.log" \
  && [ "$rc6" = 0 ] && ! grep -q 'no terminal to ask' "$TX/s6.log" \
  && pass "no terminal: changed stack files stop the run unless --yes (nothing changed; --yes installs)" \
  || failed "no-terminal supply confirmation (rc=$rc5/$rc6, unchanged: $same5): $(grep -a 'terminal\|stopped' "$TX/s5.log" "$TX/s6.log" | head -3)"
set_commit "$old_commit"; nb=$(count_backups "$TX/r"); fp "$TX/r" > "$TX/fp.s7"
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/ctty_run.py" n "$TX/s7.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile; rc7=$?
cmp -s "$TX/fp.s7" <(fp "$TX/r") && [ "$(count_backups "$TX/r")" = "$nb" ]; same7=$?
[ "$rc7" != 0 ] && [ "$same7" = 0 ] && grep -q 'The stack changed since the last install' "$TX/s7.log" \
  && grep -q 'stopped before changing anything' "$TX/s7.log.out" \
  && pass "stderr piped, stdin /dev/null: the question goes to the controlling terminal ('n' changes nothing)" \
  || failed "controlling-terminal supply confirmation (rc=$rc7, unchanged: $same7): $(cat "$TX/s7.log" "$TX/s7.log.out" 2>/dev/null | grep -a 'stack changed\|stopped\|terminal' | head -3)"
assert_unchanged_real_home
drop_scratch "$TX"

echo "== 17. Sandboxed Bash env: cache dirs and git credential reset leave settings env (upgrade retracts them)"
TB="$(scratch_dir)" || exit 1
cp -R "$HERE" "$TB/repo"
python3 - "$TB/repo/dot-claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))           # the settings an earlier version shipped
s["env"].update({"UV_CACHE_DIR": "__HOME__/.cache/claude-sandbox/uv",
                 "npm_config_cache": "__HOME__/.cache/claude-sandbox/npm",
                 "PRE_COMMIT_HOME": "__HOME__/.cache/claude-sandbox/pre-commit",
                 "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "credential.helper", "GIT_CONFIG_VALUE_0": ""})
s["sandbox"]["filesystem"]["allowWrite"] = ["~/.cache", "~/Library/Caches", "~/.cargo/registry", "~/.cargo/git",
                                            "~/go/pkg", "~/.gradle/caches", "~/.m2/repository",
                                            "~/.bun/install/cache", "~/.matplotlib"]
s["hooks"]["SessionStart"] = s["hooks"]["SessionStart"][:1]
json.dump(s, open(p, "w"), indent=2)
PY
tgit -C "$TB/repo" commit -qam "older settings" || failed "could not commit the older repository"
CLAUDE_CONFIG_DIR="$TB/c" "$TB/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile >"$TB/old.log" 2>&1
python3 - "$TB/c/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
s["sandbox"]["filesystem"]["allowWrite"].append("~/my-cache")      # yours: kept
json.dump(s, open(p, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$TB/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes >"$TB/new.log" 2>&1; rc=$?
python3 - "$TB/c/settings.json" <<'PY' && [ "$rc" = 0 ] && grep -q 'retracted stack env UV_CACHE_DIR=' "$TB/new.log" \
  && grep -q 'retracted stack env GIT_CONFIG_COUNT=1' "$TB/new.log" \
  && grep -q 'retracted sandbox.filesystem.allowWrite entries the stack no longer ships: ~/.cache, ~/Library/Caches' "$TB/new.log" \
  && pass "upgrade: cache and git env retracted from settings env, the old cache dirs from allowWrite (yours kept), session-env hook added" \
  || failed "upgrade retraction (rc=$rc): $(grep -i 'retract' "$TB/new.log" | head -4)"
import json, sys
s = json.load(open(sys.argv[1]))
e, fs = s["env"], s["sandbox"]["filesystem"]
bad = [k for k in ("UV_CACHE_DIR", "npm_config_cache", "PRE_COMMIT_HOME", "GIT_CONFIG_COUNT",
                   "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0") if k in e]
if fs["allowWrite"] != ["~/my-cache", "~/.cache/claude-sandbox"]:
    bad.append("allowWrite %s" % fs["allowWrite"])
if "~/Library/Caches/Coursier" not in fs["denyWrite"]:
    bad.append("Coursier denyWrite")
if not any(not g.get("matcher") and any(x.get("command", "").endswith('stack-hook" agent_guard session-env')
                                        for x in g["hooks"]) for g in s["hooks"]["SessionStart"]):
    bad.append("session-env hook")
if bad:
    print("   ", bad)
sys.exit(1 if bad else 0)
PY
# R4: a session whose session-env failed is reported by doctor.sh (the guard records it per session)
mkdir -p "$XDG_STATE_HOME/claude-agent-stack/smoke-failed"
printf '{"state": "failed", "reason": "no CLAUDE_ENV_FILE from Claude Code", "ts": %s}\n' "$(date +%s)" \
  > "$XDG_STATE_HOME/claude-agent-stack/smoke-failed/session-env.json"
out=$(CLAUDE_CONFIG_DIR="$TB/c" bash "$TB/c/bin/doctor.sh" 2>&1)
rm -rf "$XDG_STATE_HOME/claude-agent-stack/smoke-failed"
printf '%s\n' "$out" | grep -q "ok    sandboxed Bash env: session-env SessionStart hook wired" \
  && printf '%s\n' "$out" | grep -q "ok    session-env hook writes the sandbox env (probe in a temp dir)" \
  && printf '%s\n' "$out" | grep -q "WARN  session-env failed in 1 of the last .* (latest smoke-fa: no CLAUDE_ENV_FILE" \
  && ! printf '%s\n' "$out" | grep -q "settings.json env sets\|sandbox-writable package cache" \
  && pass "doctor.sh: the session-env hook is wired and works (probe), a session where it failed is reported" \
  || failed "doctor.sh session-env check: $(printf '%s\n' "$out" | grep -i 'session-env\|env sets' | head -4)"
# a first install (no manifest yet) retracts nothing of yours: ~/.cache stays in your allowWrite
mkdir -p "$TB/f" && printf '{"sandbox": {"filesystem": {"allowWrite": ["~/.cache"]}}}\n' > "$TB/f/settings.json"
CLAUDE_CONFIG_DIR="$TB/f" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$TB/first.log" 2>&1; rc=$?
[ "$rc" = 0 ] && ! grep -q 'retracted sandbox' "$TB/first.log" \
  && python3 -c 'import json, sys; fs = json.load(open(sys.argv[1]))["sandbox"]["filesystem"]; sys.exit("~/.cache" not in fs["allowWrite"])' "$TB/f/settings.json" \
  && pass "a first install keeps your own allowWrite entries (no manifest: nothing to retract)" \
  || failed "first install over your allowWrite (rc=$rc): $(grep -i 'retract' "$TB/first.log" | head -2)"
mkdir -p "$TB/home" && printf 'export KEEP=1' >"$TB/envfile"
for _ in 1 2; do
  echo '{"hook_event_name":"SessionStart","source":"clear"}' | HOME="$TB/home" CLAUDE_ENV_FILE="$TB/envfile" \
    python3 "$TB/c/hooks/agent_guard.py" session-env
done
got=$(env -i HOME="$TB/home" PATH="$PATH" GIT_CONFIG_PARAMETERS="'user.name=smoke' 'credential.helper=osxkeychain'" MAVEN_OPTS="-Xmx1g" bash -c \
  '. "$1"; printf "%s|%s|%s|%s|%s\n" "$KEEP" "$UV_CACHE_DIR" "$MAVEN_OPTS" "$(git config --get user.name)" "$(git config --get-all credential.helper | tail -n 1)"' _ "$TB/envfile")
[ "$got" = "1|$TB/home/.cache/claude-sandbox/uv|-Xmx1g -Dmaven.repo.local=$TB/home/.cache/claude-sandbox/m2|smoke|" ] \
  && [ "$(grep -c 'claude-agent-stack: sandboxed Bash caches' "$TB/envfile")" = 1 ] && [ -d "$TB/home/.cache/claude-sandbox" ] \
  && pass "session-env: exports appended once to CLAUDE_ENV_FILE (other lines kept); -c settings and MAVEN_OPTS kept; credential helpers reset" \
  || failed "session-env script: [$got] $(grep -c 'sandboxed Bash caches' "$TB/envfile")"
assert_unchanged_real_home
drop_scratch "$TB"

echo "== 18. serial-mcp: built with cargo at the catalog's pin, once; skipped without cargo, in --dry-run, --mcp-plan, --no-deps"
# The tools step runs without --no-deps here, so every tool it would install or call is a stub on
# PATH (exit 0) and cargo is a fake that records its arguments and creates the binary under --root.
# HOME is scratch per case: the catalog's command is __HOME__/.cargo/bin/serial-mcp.
TS="$(scratch_dir)" || exit 1
mkdir -p "$TS/stubs" "$TS/cargo" "$TS/farm"
for b in uv uvx node npx npm brew magg huetension; do printf '#!/bin/sh\nexit 0\n' > "$TS/stubs/$b"; chmod +x "$TS/stubs/$b"; done
cat > "$TS/cargo/cargo" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$CARGO_LOG"
root=""; prev=""
for a in "$@"; do [ "$prev" = --root ] && root="$a"; prev="$a"; done
[ -n "$root" ] || exit 1
v=$(printf '%s\n' "$*" | sed -n 's/.*serial-mcp@\([^ ]*\).*/\1/p')
mkdir -p "$root/bin" && printf '#!/bin/sh\nexit 0\n' > "$root/bin/serial-mcp" && chmod +x "$root/bin/serial-mcp"
printf '{"installs":{"serial-mcp %s (registry+https://github.com/rust-lang/crates.io-index)":{}}}\n' "$v" > "$root/.crates2.json"
SH
chmod +x "$TS/cargo/cargo"
# PATH without any real cargo: a directory holding one is replaced by links to its other commands
NOCARGO_PATH=""; farmed=0
IFS=: read -r -a _dirs <<<"$PATH"
for d in "${_dirs[@]}"; do
  if [ -n "$d" ] && [ -e "$d/cargo" ]; then
    for f in "$d"/*; do b="${f##*/}"; [ "$b" = cargo ] || [ -e "$TS/farm/$b" ] || ln -s "$f" "$TS/farm/$b"; done
    [ "$farmed" = 1 ] || NOCARGO_PATH="$NOCARGO_PATH${NOCARGO_PATH:+:}$TS/farm"; farmed=1
  else
    NOCARGO_PATH="$NOCARGO_PATH${NOCARGO_PATH:+:}$d"
  fi
done
export CARGO_LOG="$TS/cargo.log" FAKE_CLAUDE_JSON="$TS/fake-claude.json" STACK_CLAUDE_JSON="$TS/fake-claude.json"
: > "$CARGO_LOG"; echo '{}' > "$FAKE_CLAUDE_JSON"
# the stub uv finds no Python: the hooks' 3.13 (bin/stack-python) comes from the real uv, through
# the installer's STACK_PYTHON override
PY313="$(uv python find --system --managed-python --no-project --no-config 3.13 2>/dev/null </dev/null || true)"
srun(){ local home="$1" path="$2" log="$3"; shift 3; mkdir -p "$home"
  HOME="$home" PATH="$path" CLAUDE_CONFIG_DIR="$home/.claude" STACK_PYTHON="$PY313" \
    "$INSTALL" --no-mcp --no-plugins --no-profile "$@" >"$TS/$log" 2>&1; }
ncalls(){ wc -l <"$CARGO_LOG" | tr -d ' '; }
WANT="install serial-mcp@$SERIAL_V --locked --root $TS/h1/.cargo"
srun "$TS/h1" "$TS/cargo:$TS/stubs:$NOCARGO_PATH" r1.log; rc=$?
[ "$rc" = 0 ] && [ "$(ncalls)" = 1 ] && [ "$(head -n 1 "$CARGO_LOG")" = "$WANT" ] && [ -x "$TS/h1/.cargo/bin/serial-mcp" ] \
  && grep -qF "+ serial-mcp $SERIAL_V in $TS/h1/.cargo/bin" "$TS/r1.log" \
  && pass "serial-mcp: cargo called once with: $WANT" \
  || { failed "serial-mcp install (rc=$rc, $(ncalls) cargo calls: $(head -n 2 "$CARGO_LOG" | tr '\n' '|'))"; grep -i 'serial\|cargo' "$TS/r1.log" | sed 's/^/    /'; }
srun "$TS/h1" "$TS/cargo:$TS/stubs:$NOCARGO_PATH" r2.log; rc=$?
[ "$rc" = 0 ] && [ "$(ncalls)" = 1 ] && grep -qF "skip serial-mcp (found: $TS/h1/.cargo/bin/serial-mcp, from rustup/cargo)" "$TS/r2.log" \
  && pass "serial-mcp: a re-run with the pinned binary in place doesn't call cargo" \
  || failed "serial-mcp re-run (rc=$rc, $(ncalls) cargo calls): $(grep -i 'serial' "$TS/r2.log" | head -2)"
sed -i.bak "s/serial-mcp $SERIAL_V /serial-mcp 0.0.1 /" "$TS/h1/.cargo/.crates2.json" && rm -f "$TS/h1/.cargo/.crates2.json.bak"
srun "$TS/h1" "$TS/cargo:$TS/stubs:$NOCARGO_PATH" r3.log; rc=$?
# the skip rule: a present serial-mcp of another version is left alone, with a WARN naming the command
[ "$rc" = 0 ] && [ "$(ncalls)" = 1 ] && grep -qF "WARN serial-mcp 0.0.1 found, the catalog pins $SERIAL_V; left alone" "$TS/r3.log" \
  && pass "serial-mcp: another version already installed is left alone (WARN with the cargo command)" \
  || failed "serial-mcp other version (rc=$rc, $(ncalls) cargo calls): $(grep -i 'serial' "$TS/r3.log" | head -2)"
: > "$CARGO_LOG"
srun "$TS/h2" "$TS/cargo:$TS/stubs:$NOCARGO_PATH" d.log --dry-run; rc=$?
[ "$rc" = 0 ] && [ "$(ncalls)" = 0 ] && [ ! -e "$TS/h2/.cargo" ] \
  && grep -qF "would: cargo install serial-mcp@$SERIAL_V --locked --root $TS/h2/.cargo" "$TS/d.log" \
  && pass "serial-mcp: --dry-run lists the cargo build and runs nothing" \
  || failed "serial-mcp --dry-run (rc=$rc, $(ncalls) cargo calls): $(grep -i 'serial' "$TS/d.log" | head -2)"
HOME="$TS/h2" PATH="$TS/cargo:$TS/stubs:$NOCARGO_PATH" CLAUDE_CONFIG_DIR="$TS/h2/.claude" STACK_PYTHON="$PY313" "$INSTALL" --mcp-plan >"$TS/p.log" 2>&1; rc=$?
[ "$rc" = 0 ] && [ "$(ncalls)" = 0 ] && [ ! -e "$TS/h2/.cargo" ] && pass "serial-mcp: --mcp-plan never calls cargo" \
  || failed "serial-mcp --mcp-plan (rc=$rc, $(ncalls) cargo calls)"
srun "$TS/h2" "$TS/cargo:$TS/stubs:$NOCARGO_PATH" n.log --no-deps; rc=$?
[ "$rc" = 0 ] && [ "$(ncalls)" = 0 ] && [ ! -e "$TS/h2/.cargo" ] && pass "serial-mcp: --no-deps never calls cargo" \
  || failed "serial-mcp --no-deps (rc=$rc, $(ncalls) cargo calls)"
srun "$TS/h3" "$TS/stubs:$NOCARGO_PATH" c.log; rc=$?
[ "$rc" = 0 ] && [ ! -e "$TS/h3/.cargo" ] && [ "$(grep -c 'serial-mcp: skipped, no cargo' "$TS/c.log")" = 1 ] \
  && grep -qF "cargo install serial-mcp@$SERIAL_V --locked --root $TS/h3/.cargo" "$TS/c.log" \
  && pass "serial-mcp: without cargo, one line names the skipped build; the install goes on" \
  || failed "serial-mcp without cargo (rc=$rc): $(grep -i 'serial\|cargo' "$TS/c.log" | head -3)"
unset CARGO_LOG
assert_unchanged_real_home
drop_scratch "$TS"

echo "== 19. Install target: --config-dir, precedence, banner, refusals, the question, spaces, clone paths"
TG="$(scratch_dir)"
mkdir -p "$TG/home/.ssh" "$TG/home/.claude" && echo k > "$TG/home/.ssh/id_ed25519"
# every case: scratch HOME and state, no STACK_CLAUDE_JSON (the banner shows the .claude.json the
# target implies), no terminal on stdin unless the case makes a pty
tg_run(){ local log="$1"; shift
  env -u STACK_CLAUDE_JSON HOME="$TG/home" SHELL=/bin/zsh FAKE_CLAUDE_JSON="$TG/fake.json" "$@" </dev/null >"$log" 2>&1; }
# precedence: the flag beats CLAUDE_CONFIG_DIR; a real install into a path with a space
tg_run "$TG/p1.log" env CLAUDE_CONFIG_DIR="$TG/env dir" "$INSTALL" --config-dir "$TG/flag dir" \
  --no-mcp --no-plugins --no-deps --no-profile; rc=$?
# every guard hook command, split as the shell splits it, keeps the spaced launcher path as one word
hooks_split_ok(){ python3 - "$1" "$2" <<'PY'
import json, shlex, sys
s, want = json.load(open(sys.argv[1])), sys.argv[2]
cmds = [h["command"] for gs in s["hooks"].values() for g in gs for h in g["hooks"] if "agent_guard" in h["command"]]
sys.exit(0 if cmds and all(want in shlex.split(c) for c in cmds) else 1)
PY
}
hooks_split_ok "$TG/flag dir/settings.json" "$TG/flag dir/bin/stack-hook" 2>/dev/null; hooks_ok=$?
[ "$rc" = 0 ] && [ -f "$TG/flag dir/agents/coder.md" ] && [ ! -e "$TG/env dir" ] && [ "$hooks_ok" = 0 ] \
  && grep -qF "install target: $TG/flag dir" "$TG/p1.log" && grep -q 'chosen by: --config-dir' "$TG/p1.log" \
  && grep -qF "Claude Code's .claude.json for it: $TG/flag dir/.claude.json" "$TG/p1.log" \
  && grep -qF "CLAUDE_CONFIG_DIR=$TG/env dir in this shell is overridden for this run" "$TG/p1.log" \
  && pass "--config-dir beats CLAUDE_CONFIG_DIR; installs into a path with a space; hooks quote it; banner names target, source, .claude.json" \
  || failed "--config-dir precedence / space install (rc=$rc, hooks $hooks_ok): $(grep -i 'target\|chosen\|refus' "$TG/p1.log" | head -4)"
grep -qF "export CLAUDE_CONFIG_DIR='$TG/flag dir'" "$TG/p1.log" && grep -q '~/.zshrc' "$TG/p1.log" \
  && grep -q 'reinstall with --config-dir' "$TG/p1.log" \
  && [ "$(grep -c "export CLAUDE_CONFIG_DIR='$TG/flag dir'" "$TG/p1.log")" = 2 ] \
  && pass "non-default target: export line, profile file and the reinstall-to-move warning, in the banner and after the install" \
  || failed "non-default warning missing: $(grep -i 'export CLAUDE_CONFIG_DIR\|zshrc' "$TG/p1.log" | head -3)"
out=$(env -u CLAUDE_CONFIG_DIR HOME="$TG/home" bash "$TG/flag dir/bin/doctor.sh" </dev/null 2>&1)
printf '%s\n' "$out" | grep -qF "WARN  this install is in $TG/flag dir, not ~/.claude, and CLAUDE_CONFIG_DIR is unset" \
  && pass "doctor.sh warns when a non-default install is not what CLAUDE_CONFIG_DIR names" \
  || failed "doctor.sh: no warning for a non-default install with CLAUDE_CONFIG_DIR unset"
# --config-dir=PATH form, ~ expansion, and the env fallback (dry runs change nothing)
tg_run "$TG/p2.log" "$INSTALL" --dry-run --config-dir='~/alt' --no-mcp --no-plugins --no-deps --no-profile; rc2=$?
tg_run "$TG/p3.log" env CLAUDE_CONFIG_DIR="$TG/only env" "$INSTALL" --dry-run --no-mcp --no-plugins --no-deps --no-profile; rc3=$?
tg_run "$TG/p4.log" env -u CLAUDE_CONFIG_DIR "$INSTALL" --dry-run --no-mcp --no-plugins --no-deps --no-profile; rc4=$?
[ "$rc2" = 0 ] && grep -qF "install target: $TG/home/alt" "$TG/p2.log" && [ ! -e "$TG/home/alt" ] \
  && [ "$rc3" = 0 ] && grep -qF "install target: $TG/only env" "$TG/p3.log" && grep -q 'chosen by: CLAUDE_CONFIG_DIR' "$TG/p3.log" \
  && grep -qF ".claude.json for it: $TG/only env/.claude.json" "$TG/p3.log" \
  && [ "$rc4" = 0 ] && grep -qF "install target: $TG/home/.claude" "$TG/p4.log" && grep -q 'chosen by: the default' "$TG/p4.log" \
  && grep -qF ".claude.json for it: $TG/home/.claude.json" "$TG/p4.log" && ! grep -q 'non-default config folder' "$TG/p4.log" \
  && pass "--config-dir=~/alt expands ~; CLAUDE_CONFIG_DIR is the fallback; ~/.claude the default (with ~/.claude.json, no warning)" \
  || failed "precedence/banner (rc=$rc2/$rc3/$rc4): $(grep -h 'install target\|chosen by' "$TG/p2.log" "$TG/p3.log" "$TG/p4.log" | head -6)"
# no question without a terminal: a non-default target proceeds
! grep -q 'Install into' "$TG/p1.log" "$TG/p3.log" && pass "no terminal: no question, the run proceeds with the banner" \
  || failed "a run without a terminal asked about the target"
# refusals: exit 2, nothing created
mkdir -p "$TG/ro" && chmod 500 "$TG/ro"; echo x > "$TG/afile"; ln -s "$HERE/dot-claude" "$TG/into-repo"
mkdir -p "$TG/foreign" && echo x > "$TG/foreign/photo.jpg"; mkdir -p "$TG/real/inner" && ln -s "$TG/real/inner" "$TG/lnk"
bad=""
for t in / "$TG/home" "$TG/home/.ssh" "$HERE" "$HERE/dot-claude" "$TG/into-repo" "$TG/afile" "$TG/ro" \
         "$TG/ro/sub" "$TG/lnk/../x" "$(printf '%s/new\nline' "$TG")" "$TG/a\$b"; do
  tg_run "$TG/r.log" "$INSTALL" --config-dir "$t" --no-mcp --no-plugins --no-deps --no-profile; rc=$?
  { [ "$rc" = 2 ] && grep -q 'refusing\|control character\|symlink before' "$TG/r.log"; } || bad="$bad [$t rc=$rc]"
done
tg_run "$TG/r2.log" "$INSTALL" --config-dir "$TG/foreign" --no-mcp --no-plugins --no-deps --no-profile; rcf=$?
tg_run "$TG/r3.log" "$INSTALL" --config-dir "$TG/foreign" --yes --no-mcp --no-plugins --no-deps --no-profile; rcy=$?
[ -z "$bad" ] && [ ! -e "$TG/ro/sub" ] && [ "$(ls "$TG/foreign")" = photo.jpg ] \
  && [ "$rcf" = 2 ] && grep -q 'no Claude Code files' "$TG/r2.log" && [ "$rcy" = 2 ] \
  && pass "refused with exit 2: /, HOME, ~/.ssh, the repo, a symlink into it, a file, a read-only dir, '..' through a symlink, newline and \$; a foreign non-empty dir without a terminal (also with --yes)" \
  || failed "refusals:$bad foreign rc=$rcf/$rcy $(tail -n 2 "$TG/r2.log")"
chmod 700 "$TG/ro"
# the refusal comes before the main-branch rule: from a side branch, main is not fast-forwarded and
# the checkout stays on its branch
cp -R "$HERE" "$TG/br clone" && tgit -C "$TG/br clone" switch -q -c side \
  && tgit -C "$TG/br clone" commit -q --allow-empty -m side
m0="$(tgit -C "$TG/br clone" rev-parse main)"
tg_run "$TG/b.log" "$TG/br clone/install.sh" --config-dir "$TG/foreign" --no-mcp --no-plugins --no-deps --no-profile; rcb=$?
[ "$rcb" = 2 ] && [ "$(tgit -C "$TG/br clone" rev-parse main)" = "$m0" ] \
  && [ "$(tgit -C "$TG/br clone" symbolic-ref --short HEAD)" = side ] \
  && pass "a refused target stops before the main-branch rule (main not moved, branch not switched)" \
  || failed "main-branch rule ran before the target refusal (rc=$rcb): $(tail -n 2 "$TG/b.log")"
# --config-dir followed by another option is a missing value, not a folder named --yes
tg_run "$TG/m.log" "$INSTALL" --config-dir --yes --dry-run; rcm=$?
[ "$rcm" = 2 ] && grep -q -- '--config-dir needs a path' "$TG/m.log" && [ ! -e "./--yes" ] \
  && pass "--config-dir with an option after it: exit 2, 'needs a path'" \
  || failed "--config-dir --yes (rc=$rcm): $(head -n 2 "$TG/m.log")"
# a foreign folder named by CLAUDE_CONFIG_DIR (a CI run's log in it, say) is a warning, not a refusal
tg_run "$TG/e.log" env CLAUDE_CONFIG_DIR="$TG/foreign" "$INSTALL" --dry-run --no-mcp --no-plugins --no-deps --no-profile; rce=$?
[ "$rce" = 0 ] && grep -q 'CLAUDE_CONFIG_DIR names a non-empty folder with no Claude Code files' "$TG/e.log" \
  && pass "CLAUDE_CONFIG_DIR naming a foreign folder: warned, not refused (today's non-interactive runs keep working)" \
  || failed "CLAUDE_CONFIG_DIR foreign folder (rc=$rce): $(tail -n 2 "$TG/e.log")"
# the question: the answer parser with an injected answer, then a real pty when the sandbox allows one
printf 'y\n' | python3 "$HERE/lib/install_state.py" ask 'Q? [y/N] ' >/dev/null; a1=$?
printf '\n' | python3 "$HERE/lib/install_state.py" ask 'Q? [y/N] ' >/dev/null; a2=$?
python3 "$HERE/lib/install_state.py" ask 'Q? [y/N] ' </dev/null >/dev/null; a3=$?
[ "$a1" = 0 ] && [ "$a2" = 1 ] && [ "$a3" = 1 ] && pass "the target question: y proceeds, Enter and EOF answer No" \
  || failed "ask: y=$a1 enter=$a2 eof=$a3"
cat > "$TG/pty.py" <<'PY'
import os, select, subprocess, sys
answer, log, argv = sys.argv[1].encode(), sys.argv[2], sys.argv[3:]
try:
    m, s = os.openpty()
except OSError as e:
    print("openpty: %s" % e)
    sys.exit(77)
p = subprocess.Popen(argv, stdin=s, stdout=s, stderr=s, close_fds=True)
buf, answered = b"", False
while True:
    r, _, _ = select.select([m], [], [], 0.5)
    if m in r:
        buf += os.read(m, 65536)
        if not answered and b"[y/N]" in buf:
            os.write(m, answer + b"\n")
            answered = True
    elif p.poll() is not None:
        break
os.close(s)
rc = p.wait()
open(log, "wb").write(buf)
sys.exit(rc)
PY
env -u STACK_CLAUDE_JSON HOME="$TG/home" SHELL=/bin/zsh FAKE_CLAUDE_JSON="$TG/fake.json" \
  python3 "$TG/pty.py" n "$TG/q1.log" "$INSTALL" --config-dir "$TG/asked" --no-mcp --no-plugins --no-deps --no-profile >"$TG/q1.err" 2>&1; q1=$?
if [ "$q1" = 77 ]; then
  echo "  SKIP  the target question on a real pty: $(cat "$TG/q1.err") (the answer parser is tested above)"
else
  env -u STACK_CLAUDE_JSON HOME="$TG/home" SHELL=/bin/zsh FAKE_CLAUDE_JSON="$TG/fake.json" \
    python3 "$TG/pty.py" y "$TG/q2.log" "$INSTALL" --config-dir "$TG/asked" --no-mcp --no-plugins --no-deps --no-profile; q2=$?
  env -u STACK_CLAUDE_JSON HOME="$TG/home" SHELL=/bin/zsh FAKE_CLAUDE_JSON="$TG/fake.json" \
    python3 "$TG/pty.py" n "$TG/q3.log" "$INSTALL" --config-dir "$TG/asked2" --no-prompt --no-mcp --no-plugins --no-deps --no-profile; q3=$?
  [ "$q1" = 1 ] && grep -q "Install into $TG/asked? \[y/N\]" "$TG/q1.log" && grep -q 'why you are asked' "$TG/q1.log" \
    && [ ! -e "$TG/asked" ] && [ "$q2" = 0 ] && [ -f "$TG/asked/agents/coder.md" ] \
    && [ "$q3" = 0 ] && ! grep -q 'Install into' "$TG/q3.log" \
    && pass "on a terminal: a non-default target is asked first ('n' stops before anything exists, 'y' installs; --no-prompt skips it)" \
    || failed "target question on a pty (n=$q1 y=$q2 no-prompt=$q3): $(grep -a 'Install into\|stopped' "$TG/q1.log" | head -2)"
fi
# the clone anywhere: through a symlinked directory, a symlink to install.sh, and a path with a space
cp -R "$HERE" "$TG/my clone"
ln -s "$TG/my clone" "$TG/clone link"; mkdir -p "$TG/bin dir"; ln -s "$TG/my clone/install.sh" "$TG/bin dir/stack-install"
tg_run "$TG/c1.log" "$TG/clone link/install.sh" --dry-run --config-dir "$TG/c1" --no-mcp --no-plugins --no-deps --no-profile; c1=$?
tg_run "$TG/c2.log" "$TG/bin dir/stack-install" --dry-run --config-dir "$TG/c2" --no-mcp --no-plugins --no-deps --no-profile; c2=$?
tg_run "$TG/c3.log" "$TG/my clone/install.sh" --config-dir "$TG/c3 target" --no-mcp --no-plugins --no-deps --no-profile; c3=$?
[ "$c1" = 0 ] && grep -qF "stack repo: $TG/clone link (branch main)" "$TG/c1.log" \
  && [ "$c2" = 0 ] && grep -qF "stack repo: $TG/my clone (branch main)" "$TG/c2.log" \
  && [ "$c3" = 0 ] && grep -qF "$TG/my clone" "$TG/c3 target/agents/claude-code-engineer.md" \
  && hooks_split_ok "$TG/c3 target/settings.json" "$TG/c3 target/bin/stack-hook" \
  && pass "clone anywhere: via a symlinked dir, via a symlink to install.sh, from a path with a space (rendered into the agents)" \
  || failed "clone paths (rc=$c1/$c2/$c3): $(grep -h 'stack repo\|install.sh:' "$TG/c1.log" "$TG/c2.log" "$TG/c3.log" | head -4)"
assert_unchanged_real_home
drop_scratch "$TG"

echo "== 20. --with-lsp: jdtls from step 2's brew batch (LSP group), rust-analyzer and kotlin-lsp from Homebrew, a log per failure, a cause per missing server"
# Runs without --no-deps (as §18): brew is a fake that logs its arguments and "installs" each name as a
# command in $TW/brewbin (a name in BREW_FAIL fails, with an error line); the other tools are stubs.
# PATH is those, the fake claude and the system dirs: no real language server, brew, rustup or npm.
# Every step-2 group is off; LSP is left unset, so --with-lsp decides it.
TW="$(scratch_dir)" || exit 1
mkdir -p "$TW/stubs" "$TW/brewbin"
for b in uv uvx node npx npm magg huetension; do printf '#!/bin/sh\nexit 0\n' > "$TW/stubs/$b"; chmod +x "$TW/stubs/$b"; done
cat > "$TW/stubs/brew" <<'SH'
#!/bin/sh
printf '%s\n' "$*" >> "$BREW_LOG"
case "$1" in
  list) t=formula; [ "$2" = --cask ] && t=cask; sed -n "s/^$t //p" "$BREW_BIN/.state" 2>/dev/null; exit 0 ;;
  install) ;;
  *) exit 0 ;;
esac
shift; t=formula; [ "$1" = --cask ] && { t=cask; shift; }
for n in "$@"; do case " $BREW_FAIL " in *" $n "*) echo "Error: simulated failure installing $n"; exit 1 ;; esac; done
for n in "$@"; do printf '#!/bin/sh\nexit 0\n' > "$BREW_BIN/$n" && chmod +x "$BREW_BIN/$n" && echo "$t $n" >> "$BREW_BIN/.state"; done
SH
chmod +x "$TW/stubs/brew"
[ -n "${PY313:-}" ] || PY313="$(uv python find --system --managed-python --no-project --no-config 3.13 2>/dev/null </dev/null || true)"
TW_PATH="$TW/brewbin:$TW/stubs:$HERE/tests/fake-claude:/usr/bin:/bin:/usr/sbin:/sbin"
# wrun HOME LOG BREW_FAIL ARGS...: one install into a scratch HOME; brew's and claude's calls logged next to LOG
wrun(){ local home="$1" log="$2" fail="$3"; shift 3; mkdir -p "$home"; rm -f "$TW/brewbin"/* "$TW/brewbin/.state"
  env -u STACK_INSTALL_LSP ${LSP_SET:+STACK_INSTALL_LSP=$LSP_SET} HOME="$home" PATH="$TW_PATH" CLAUDE_CONFIG_DIR="$home/.claude" STACK_PYTHON="$PY313" \
    FAKE_CLAUDE_JSON="$TW/$log.json" STACK_CLAUDE_JSON="$TW/$log.json" FAKE_CLAUDE_LOG="$TW/$log.claude" \
    BREW_LOG="$TW/$log.brew" BREW_BIN="$TW/brewbin" BREW_FAIL="$fail" STACK_INSTALL_MAXFILES=0 \
    DEVTOOLS_BREW_CANDIDATES="" DEVTOOLS_SYSTEM_DIRS="" DEVTOOLS_PATH_HELPER="" DEVTOOLS_PKGUTIL="" DEVTOOLS_MDFIND="" \
    STACK_INSTALL_DEPS=0 STACK_INSTALL_DEVTOOLS=0 STACK_INSTALL_UV=0 STACK_INSTALL_NODE=0 STACK_INSTALL_RUST=0 \
    STACK_INSTALL_HASKELL=0 STACK_INSTALL_JULIA=0 STACK_INSTALL_SCALA=0 STACK_INSTALL_JAVA=0 STACK_INSTALL_LATEX=0 \
    STACK_INSTALL_CXX=0 STACK_INSTALL_GO=0 STACK_INSTALL_LEAN=0 STACK_INSTALL_POSTGRES=0 STACK_INSTALL_MONGODB=0 \
    "$INSTALL" --no-mcp --no-profile "$@" </dev/null >"$TW/$log" 2>&1; }
plugin_installed(){ grep -qF "[\"plugin\", \"install\", \"$1@claude-plugins-official\", \"--scope\", \"user\"]" "$2"; }
for r in r1 r2 r3 r4 r5; do echo '{}' > "$TW/$r.json"; done
# r1: everything Homebrew has works except the kotlin-lsp cask
wrun "$TW/h1" r1 "kotlin-lsp" --with-lsp; rc=$?
# A kept log is gone after a run from a Claude Code shell (install.sh replaces that TMPDIR with its
# work dir, removed at exit): the line naming it and the log's printed end are what is checked then.
klog="$(sed -n 's/^  ! kotlin-lsp: brew install --cask kotlin-lsp failed (log \(.*\))$/\1/p' "$TW/r1" | head -n 1)"
[ "$rc" = 0 ] && [ "$(grep -cx 'install jdtls' "$TW/r1.brew")" = 1 ] && grep -qF '+ jdtls (brew)' "$TW/r1" \
  && plugin_installed jdtls-lsp "$TW/r1.claude" \
  && grep -qx 'install rust-analyzer' "$TW/r1.brew" && grep -qF '+ rust-analyzer (brew install rust-analyzer)' "$TW/r1" \
  && plugin_installed rust-analyzer-lsp "$TW/r1.claude" \
  && pass "--with-lsp: jdtls in step 2's batch (once), rust-analyzer from Homebrew without rustup, both plugins enabled" \
  || { failed "--with-lsp routes (rc=$rc): brew [$(tr '\n' '|' <"$TW/r1.brew")]"; grep -i 'jdtls\|rust-analyzer\|language server' "$TW/r1" | sed 's/^/    /'; }
[ -n "$klog" ] && { [ ! -e "$klog" ] || grep -q 'simulated failure installing kotlin-lsp' "$klog"; } && grep -qx 'install --cask kotlin-lsp' "$TW/r1.brew" \
  && grep -qF "    kotlin-lsp: brew install --cask kotlin-lsp failed (log $klog)" "$TW/r1" \
  && grep -qF '      Error: simulated failure installing kotlin-lsp' "$TW/r1" \
  && ! plugin_installed kotlin-lsp "$TW/r1.claude" \
  && pass "--with-lsp: a failed install names its kept log (and shows its end); the closing line repeats the cause" \
  || { failed "kotlin-lsp failure line/log [$klog]"; grep -i 'kotlin' "$TW/r1" | sed 's/^/    /'; }
grep -q '^  - no language server for:.* pyright-langserver' "$TW/r1" \
  && grep -qF '    pyright-langserver: npm install -g --ignore-scripts pyright@1.1.414 ran, but pyright-langserver still does not run (log ' "$TW/r1" \
  && grep -qF '    haskell-language-server-wrapper: no ghcup' "$TW/r1" && grep -qF '    lake: comes with elan' "$TW/r1" \
  && ! grep -q 'install.sh --with-lsp' "$TW/r1" && ! grep -qi 'Java: brew install jdtls' "$TW/r1" \
  && pass "--with-lsp: every missing server gets its own cause; no line says to use --with-lsp" \
  || { failed "--with-lsp closing lines"; sed -n '/no language server for/,/^  [^ ]/p' "$TW/r1" | sed 's/^/    /'; grep -n 'with-lsp' "$TW/r1" | sed 's/^/    /'; }
# r2: jdtls fails in step 2 (batch, then by name) and once more in step 10, which names its own log
wrun "$TW/h2" r2 "jdtls" --with-lsp; rc=$?
jlog="$(sed -n 's/^  ! jdtls: brew install jdtls failed (log \(.*\))$/\1/p' "$TW/r2" | head -n 1)"
[ "$rc" = 0 ] && [ "$(grep -cx 'install jdtls' "$TW/r2.brew")" = 3 ] && grep -qF '! jdtls: brew install failed' "$TW/r2" \
  && [ -n "$jlog" ] && { [ ! -e "$jlog" ] || grep -q 'simulated failure installing jdtls' "$jlog"; } \
  && grep -qF '      Error: simulated failure installing jdtls' "$TW/r2" \
  && grep -qF "    jdtls: brew install jdtls failed (log $jlog)" "$TW/r2" && ! plugin_installed jdtls-lsp "$TW/r2.claude" \
  && pass "--with-lsp: jdtls failing in step 2 gets one more try in step 10; the cause names that log" \
  || { failed "jdtls failure (rc=$rc): brew [$(tr '\n' '|' <"$TW/r2.brew")] log [$jlog]"; grep -i 'jdtls' "$TW/r2" | sed 's/^/    /'; }
# r3: without --with-lsp the LSP group stays off and the closing line names --with-lsp (with jdtls)
wrun "$TW/h3" r3 ""; rc=$?
[ "$rc" = 0 ] && ! grep -q 'jdtls\|rust-analyzer\|kotlin-lsp' "$TW/r3.brew" && grep -q '^  groups off:.* LSP' "$TW/r3" \
  && grep -q '^  - no language server for:.* jdtls.*(./install.sh --with-lsp installs pyright, typescript-language-server, rust-analyzer, jdtls and kotlin-lsp' "$TW/r3" \
  && pass "without --with-lsp: no language server installed, LSP among the groups off, the hint names jdtls" \
  || { failed "without --with-lsp (rc=$rc): brew [$(tr '\n' '|' <"$TW/r3.brew")]"; grep -i 'groups off\|language server' "$TW/r3" | sed 's/^/    /'; }
# r4: --dry-run --with-lsp lists the routes and runs no install
wrun "$TW/h4" r4 "" --with-lsp --dry-run; rc=$?
[ "$rc" = 0 ] && ! grep -q '^install' "$TW/r4.brew" && [ -z "$(ls -A "$TW/brewbin")" ] \
  && grep -qF 'would: HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install jdtls' "$TW/r4" \
  && grep -qF 'would: rust-analyzer ← rustup component add rust-analyzer (no rustup: brew install rust-analyzer)' "$TW/r4" \
  && grep -qF 'would: kotlin-lsp ← brew install --cask kotlin-lsp' "$TW/r4" \
  && ! grep -qF 'would: haskell-language-server-wrapper' "$TW/r4" && ! grep -qF 'would: metals' "$TW/r4" \
  && grep -q '^  - no language server for:.* (dry run: a real run tries the routes below)' "$TW/r4" \
  && pass "--dry-run --with-lsp: jdtls in the brew batch line, one would: line per server, nothing installed" \
  || { failed "--dry-run --with-lsp (rc=$rc): brew [$(tr '\n' '|' <"$TW/r4.brew")]"; grep -i 'would\|language server' "$TW/r4" | sed 's/^/    /'; }
# r5: STACK_INSTALL_LSP=0 keeps jdtls out of a --with-lsp run; the closing line says so
LSP_SET=0 wrun "$TW/h5" r5 "" --with-lsp --dry-run; rc=$?
[ "$rc" = 0 ] && ! grep -q 'would: .*brew install.* jdtls' "$TW/r5" && grep -q '^  groups off:.* LSP' "$TW/r5" \
  && grep -qF '    jdtls: brew install jdtls (STACK_INSTALL_LSP=0 keeps it out of step 2)' "$TW/r5" \
  && pass "--with-lsp with STACK_INSTALL_LSP=0: no jdtls in step 2, the closing line names the knob" \
  || { failed "STACK_INSTALL_LSP=0 (rc=$rc)"; grep -i 'jdtls\|groups off' "$TW/r5" | sed 's/^/    /'; }
assert_unchanged_real_home
drop_scratch "$TW"

echo
echo "== Summary: $PASS passed, $FAIL failed"
rm -rf "$T1" "$T2" "$T3"
drop_scratch "$SCRATCH_ROOT"
[ "$FAIL" -eq 0 ]
