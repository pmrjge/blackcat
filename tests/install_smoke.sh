#!/usr/bin/env bash
# Smoke test for install.sh. Hermetic: a fake `claude` (tests/fake-claude/claude) is put first on
# PATH, every run uses a scratch CLAUDE_CONFIG_DIR and a scratch MCP config (FAKE_CLAUDE_JSON /
# STACK_CLAUDE_JSON), plus --no-deps --no-profile. As a belt-and-braces check the real
# $HOME/.claude, ~/.claude.json and ~/.zshrc are fingerprinted before and after.
set -uo pipefail

SRC_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# install.sh runs only from the main branch of a git checkout and fast-forwards main when started
# anywhere else, so the test never runs it from this checkout: it snapshots the working tree
# (tracked and untracked files, not ignored ones) into a scratch repository on main and installs
# from there. No git command in this test talks to a remote other than scratch ones.
tgit(){ GIT_TERMINAL_PROMPT=0 git -c core.hooksPath=/dev/null -c commit.gpgsign=false -c init.defaultBranch=main \
  -c user.name=smoke -c user.email=smoke@example.invalid "$@" </dev/null; }
# a fresh scratch directory, physical path; aborts instead of falling back to the current directory
scratch_dir(){ local d; d="$(mktemp -d)" && [ -d "$d" ] && (cd "$d" && pwd -P) || { echo "mktemp -d failed" >&2; exit 1; }; }
# remove a directory only if it is one of this test's scratch directories
drop_scratch(){ case "$1" in */tmp.*) [ -d "$1" ] && rm -rf -- "$1" ;; esac; }
SCRATCH_ROOT="$(scratch_dir)" || exit 1
# install.sh keeps its backups in ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups and the
# guard its state next to it: every scratch install of this test writes both under the scratch root.
REAL_BK_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack-backups"
export XDG_STATE_HOME="$SCRATCH_ROOT/state"
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
tgit -C "$HERE" init -q && tgit -C "$HERE" add -A && tgit -C "$HERE" commit -q -m "smoke snapshot" \
  || { echo "could not build the scratch stack repository"; exit 1; }
INSTALL="$HERE/install.sh"
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
# plus the copy types install.sh renders from their base agents (COPY_TYPES)
EXPECTED_AGENTS=$((EXPECTED_AGENTS + $(sed -n 's/^COPY_TYPES = (\(.*\))$/\1/p' "$HERE/install.sh" | grep -o '"[a-z0-9-]*"' | wc -l | tr -d ' ')))
EXPECTED_SKILLS=$(ls -d "$HERE"/dot-claude/skills/*/ | wc -l | tr -d ' ')

echo "== 1. Fresh install into a scratch CLAUDE_CONFIG_DIR"
T1="$(cd "$(mktemp -d)" && pwd -P)"
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
[ -f "$T1/rules/claude-agent-stack.md" ] && [ ! -e "$T1/CLAUDE.md" ] && pass "global rules installed as rules/claude-agent-stack.md (CLAUDE.md left to you)" \
  || failed "rules/claude-agent-stack.md missing, or a CLAUDE.md was written"
grep -qF "$HERE" "$T1/agents/claude-code-engineer.md" && grep -qF "\"repo\": \"$HERE\"" "$T1/.stack-manifest.json" \
  && pass "stack repo path rendered into agents and recorded in the manifest" || failed "stack repo path not rendered/recorded"

grep -qF "$T1/hooks/agent_guard.py" "$T1/settings.json" 2>/dev/null && pass "settings.json hook commands point at \$T/hooks" \
  || failed "settings.json hook commands do not reference $T1/hooks"
grep -qF "$T1/hooks/agent_guard.py\\\" blackcat-guard" "$T1/agents/blackcat.md" 2>/dev/null && pass "blackcat.md hook runs \$T/hooks/agent_guard.py blackcat-guard" \
  || failed "blackcat.md hook command does not run $T1/hooks/agent_guard.py blackcat-guard"
python3 - "$T1/settings.json" "$T1/agents/blackcat.md" <<'PY' && pass "hooks and status line use an absolute interpreter (no bare python3)" || failed "a hook command uses a bare interpreter"
import json, re, sys
s = json.load(open(sys.argv[1]))
cmds = [h["command"] for gs in s["hooks"].values() for g in gs for h in g["hooks"]]
cmds.append(s["statusLine"]["command"])
cmds += re.findall(r'(?m)^\s+command:\s*"(.*agent_guard.*)"', open(sys.argv[2]).read())
bad = [c for c in cmds if not c.lstrip('\\"').startswith("/")]
if bad:
    print("  bare:", bad)
sys.exit(1 if bad else 0)
PY
python3 - "$T1/settings.json" <<'PY' && pass "settings: StopFailure + TaskStop wiring, narrowed magg allow, Exa-safe denies, no-push wiring" || failed "settings wiring/permissions (see above)"
import json, os, sys
s = json.load(open(sys.argv[1]))
h, allow, deny = s["hooks"], s["permissions"]["allow"], s["permissions"]["deny"]
checks = {
    "StopFailure hook": any("agent_guard.py" in json.dumps(g) for g in h.get("StopFailure", [])),
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
                                any(not g.get("matcher") and any(x.get("command", "").startswith('"/') and
                                    x["command"].endswith('/hooks/agent_guard.py" session-env')
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
    "local-file MCP guard": any("ctx_index" in (g.get("matcher") or "") and "agent_guard.py" in json.dumps(g)
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
for f in doctor.sh with-stack-env mcp-headers magg-private statusline.py claude-ultracode; do
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
python3 - "$T1/settings.json" "$HERE/dot-claude/settings.json" <<'PY' && pass "settings: autocompact on at 400K, depth 4, default tool search, lazy MCP, blackcat, shipped skill-listing budget, 500-char cut, 6 user-only skills" || failed "settings.json values (see above)"
import json, sys
s = json.load(open(sys.argv[1]))
frac = json.load(open(sys.argv[2]))["skillListingBudgetFraction"]
env = s["env"]
checks = {
    "agent": s.get("agent") == "blackcat",
    "autoCompactEnabled": s.get("autoCompactEnabled") is True,
    "autoCompactWindow": s.get("autoCompactWindow") == 400000,
    "depth": env.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH") == "4",
    "tool search left at its default": "ENABLE_TOOL_SEARCH" not in env,
    ".env.example writable": "Read(**/.env.*)" not in s["permissions"]["deny"] and "Read(**/.env.local)" in s["permissions"]["deny"],
    "discovery cache": env.get("MCP_DISCOVERY_CACHE") == "1",
    "blackcat dispatch": env.get("BLACKCAT_MAX_DISPATCH") == "8" and env.get("BLACKCAT_MAX_STEPS") == "12",
    "caps and budgets": (env.get("STACK_MAX_FANOUT"), env.get("STACK_MAX_FANOUT_BY_TYPE"), env.get("STACK_MAX_SELF_FANOUT"),
                         env.get("STACK_PROMPT_CTX_BUDGET"), env.get("STACK_SESSION_CTX_BUDGET"),
                         env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"), env.get("STACK_MAX_MCP_CALLS"))
                        == ("3", "orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8", "2", "100000000", "666000000", "32", "64"),
    "skill listing budget": s.get("skillListingBudgetFraction") == frac and 0.01 <= frac <= 0.02
                            and s.get("skillListingMaxDescChars") == 500
                            and s.get("skillOverrides", {}).get("code-review") == "user-invocable-only",
    "no Haiku": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "claude-sonnet-5-5",
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
# every installed agent's "May spawn" sentence (the rendered copy types included) is its POLICY row
python3 "$T1/hooks/agent_guard.py" --print-policy | python3 -c '
import json, os, re, sys
p, d = json.load(sys.stdin), sys.argv[1]
bad = []
for copy in p["copy_types"].values():
    text = open(os.path.join(d, copy + ".md")).read()
    if not re.search(r"(?m)^name: %s$" % re.escape(copy), text):
        bad.append("%s.md: name is not %s" % (copy, copy))
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
' "$T1/agents" && pass "copy types rendered; every May spawn sentence matches POLICY (copies included)" \
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
  TG="$(mktemp -d)"
  out=$(env -u STACK_ALLOW_NON_MACOS CLAUDE_CONFIG_DIR="$TG/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile 2>&1); rc=$?
  { [ "$rc" = 1 ] && printf '%s\n' "$out" | grep -q "macOS only" && [ ! -e "$TG/c" ]; } \
    && pass "refuses to install on $(uname) (macOS only), touching nothing" || failed "non-macOS guard: rc=$rc: $out"
fi

echo "== 2. Second run: agents reported unchanged, no changes, no backup"
nb_before=$(count_backups "$T1")
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
[ "$nb_before" = "$nb_after" ] && grep -q "no changes: the config dir already matches this stack version" "$T1/.install2.log" \
  && grep -qF "nothing changed in $T1 (no backup needed)" "$T1/.install2.log" \
  && pass "a run that changes nothing says so and makes no backup" || failed "no-op run: backups $nb_before -> $nb_after, or no 'no changes' line"
assert_unchanged_real_home

echo "== 3. An edited stack file: replaced by default (the backup keeps it); --no-prune keeps it with a .new"
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
edited_before="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --no-prune >"$T1/.install3b.log" 2>&1
edited_after="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
[ "$edited_before" = "$edited_after" ] && pass "--no-prune: edited coder.md kept as-is" || failed "--no-prune overwrote the edited coder.md"
[ -f "$T1/agents/coder.md.new" ] && pass "--no-prune: .new copy of the rendered coder.md was written" || failed "no .new copy found for the modified coder.md"
grep -qF "$T1/agents/coder.md.new" "$T1/.install3b.log" && pass "the final summary lists the pending coder.md.new" || failed "pending .new not listed at the end"
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --no-prune --force >"$T1/.install4.log" 2>&1
edited_forced="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
if [ "$edited_forced" != "$edited_before" ] && ! grep -q '<!-- local edit -->' "$T1/agents/coder.md"; then
  pass "--no-prune --force overwrote the modified coder.md"
else
  failed "--no-prune --force did not overwrite the modified coder.md"
fi
[ ! -f "$T1/agents/coder.md.new" ] && pass "stale coder.md.new removed once the file is back in sync" || failed "stale coder.md.new left behind"
assert_unchanged_real_home

echo "== 4. Settings merge: pins, concurrency, compaction overrides; magg catalog merge"
T2="$(cd "$(mktemp -d)" && pwd -P)"
export FAKE_CLAUDE_JSON="$T2/fake-claude.json" STACK_CLAUDE_JSON="$T2/fake-claude.json"
mkdir -p "$T2/magg"
# docling edited by the user (replaced: the backup keeps it), a server of their own (kept), and two
# entries exactly as an earlier stack version shipped them (mlflow disabled, playwright left enabled
# by magg): updated.
cat > "$T2/magg/config.json" <<'JSON'
{"servers": {"docling": {"source": "x", "command": "my-docling", "enabled": true},
             "mine": {"source": "y", "command": "my-server", "enabled": true},
             "mlflow": {"source": "https://mlflow.org/docs/latest/genai/mcp/", "prefix": "mlflow", "command": "uv", "args": ["run", "--with", "mlflow[mcp]>=3.5.1", "mlflow", "mcp", "run"], "notes": "MLflow trace search and management for LLM/agent evaluation. Needs MLFLOW_TRACKING_URI in stack.env (e.g. http://127.0.0.1:5000 or a file:// store).", "enabled": false},
             "playwright": {"source": "https://github.com/microsoft/playwright-mcp", "prefix": "pw", "command": "npx", "args": ["-y", "@playwright/mcp@latest"], "notes": "Scripted browser automation (forms, logins, JS-heavy pages) when WebFetch/Jina/Spider are not enough."}}}
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
env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = "claude-haiku-4-5"
env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = "claude-opus-4-1[1m]"
env["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"] = "12"
env["CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION"] = "5"
env["DISABLE_AUTO_COMPACT"] = "1"
env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = "200000"
s["autoCompactWindow"] = 300000                   # the earlier stack value
s["permissions"]["allow"].append("Bash(ls *)")
s["permissions"]["allow"].append("mcp__magg")      # what earlier stack versions shipped
s["permissions"]["deny"].append("Read(**/.env.*)")
env["ENABLE_TOOL_SEARCH"] = "true"
json.dump(s, open(p, "w"), indent=2)
PY
python3 - "$T2/.stack-manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1]))
for k in ("settings_env", "settings_permissions", "settings_set_if_absent"):
    m.pop(k, None)                                   # an install from before these were recorded
json.dump(m, open(sys.argv[1], "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$T2" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T2/.install2.log" 2>&1
python3 - "$T2/settings.json" "$HERE/dot-claude/settings.json" "$T2/magg/config.json" <<'PY'
import json, sys
dst, shipped_path, magg = sys.argv[1], sys.argv[2], sys.argv[3]
s = json.load(open(dst))
env = s.get("env", {})
shipped = json.load(open(shipped_path)).get("env", {})
ok = True
def check(cond, good, bad):
    global ok
    print("  %s  %s" % ("PASS" if cond else "FAIL", good if cond else bad))
    ok = ok and cond
check(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "claude-sonnet-5-5", "a Haiku pin is replaced by Sonnet 5.5 (the stack runs no Haiku)",
      "ANTHROPIC_DEFAULT_HAIKU_MODEL=%r" % env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
check("ANTHROPIC_DEFAULT_OPUS_MODEL" not in env, "[1m]-suffixed pin removed", "[1m] pin kept")
check("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" not in env, "no-op CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION dropped", "no-op var kept")
check(env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS") == shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS reset to shipped %s" % shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "concurrency not reset (%r)" % env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"))
check("DISABLE_AUTO_COMPACT" not in env and "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env,
      "auto-compaction overrides removed", "auto-compaction overrides kept")
check(s.get("autoCompactWindow") == 400000 and s.get("autoCompactEnabled") is True,
      "autoCompactWindow back to 400000", "autoCompactWindow=%r" % s.get("autoCompactWindow"))
check("Bash(ls *)" in s["permissions"]["allow"], "user's own allow rule kept", "user's allow rule lost")
m = json.load(open(magg))["servers"]
check(m["docling"]["command"] != "my-docling" and m["docling"]["enabled"] is False
      and m.get("mine") == {"source": "y", "command": "my-server", "enabled": True},
      "magg: the stack's docling entry is the stack's (disabled); the user's own server untouched",
      "magg: docling %r, mine %r" % (m["docling"], m.get("mine")))
check(all(k in m for k in ("duckdb", "arxiv", "jupyter", "mlflow", "playwright", "lean")),
      "magg: new catalog entries added", "magg: catalog entries missing: %s" % sorted(m))
check("--no-project" in m["mlflow"]["args"] and m["mlflow"]["enabled"] is False,
      "magg: untouched legacy mlflow entry updated (state kept)", "magg: mlflow entry %r" % m["mlflow"])
check("--isolated" in m["playwright"]["args"] and m["playwright"]["enabled"] is False,
      "magg: legacy playwright updated and disabled again", "magg: playwright entry %r" % m["playwright"])
check("ENABLE_TOOL_SEARCH" not in env, "old ENABLE_TOOL_SEARCH=true retracted", "ENABLE_TOOL_SEARCH kept: %r" % env.get("ENABLE_TOOL_SEARCH"))
check("Read(**/.env.*)" not in s["permissions"]["deny"] and "Read(**/.env.local)" in s["permissions"]["deny"],
      "old Read(**/.env.*) deny retracted (narrower rules shipped)", "Read(**/.env.*) still denied")
check("mcp__magg" not in s["permissions"]["allow"] and "mcp__magg__magg_list_servers" in s["permissions"]["allow"],
      "retired blanket mcp__magg allow rule retracted", "blanket mcp__magg still allowed")
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
T3="$(cd "$(mktemp -d)" && pwd -P)"
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
cp "$HERE/stack.env.example" "$T3/stack.env"; chmod 600 "$T3/stack.env"
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
unexpected=$(printf '%s\n' "$out" | grep 'FAIL' | grep -vE 'sci venv|magg missing|huetension missing|uvx missing|uv missing|node missing|npx missing')
if [ -n "$unexpected" ]; then
  failed "doctor.sh reported unexpected FAILs:"; printf '%s\n' "$unexpected" | sed 's/^/    /'
else
  pass "doctor.sh: only expected FAILs (--no-deps skipped venv/magg)"
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
budget=$(python3 -c 'import json, sys; print(int(1000000 * 3 * json.load(open(sys.argv[1]))["skillListingBudgetFraction"]))' "$HERE/dot-claude/settings.json")
printf '%s\n' "$out" | grep -qE "ok    skill listing: $((nsk - 1)) skills, ~[0-9]+ of $budget characters" \
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
# history it copied): the shipped matcher passes, one without fork fails
printf '%s\n' "$out" | grep -q 'ok    SessionStart guard matcher covers startup, resume and fork' \
  && pass "doctor.sh: SessionStart guard matcher covers fork" \
  || failed "doctor.sh: SessionStart matcher line: $(printf '%s\n' "$out" | grep 'SessionStart')"
T3F="$(scratch_dir)" || exit 1
cp -R "$T3/." "$T3F/"
python3 - "$T3F/settings.json" <<'PY'
import json, sys
p = sys.argv[1]
s = json.load(open(p))
for g in s["hooks"]["SessionStart"]:
    if "agent_guard.py" in json.dumps(g) and "session-env" not in json.dumps(g):
        g["matcher"] = "startup|resume"
json.dump(s, open(p, "w"), indent=2)
PY
outf=$(CLAUDE_CONFIG_DIR="$T3F" bash "$T3F/bin/doctor.sh" 2>&1)
printf '%s\n' "$outf" | grep -q 'FAIL  SessionStart guard matcher startup|resume misses fork — rerun install.sh' \
  && pass "doctor.sh fails a SessionStart guard matcher without fork" \
  || failed "doctor.sh: no FAIL for a SessionStart matcher without fork: $(printf '%s\n' "$outf" | grep 'SessionStart')"
drop_scratch "$T3F"
assert_unchanged_real_home

echo "== 8. Regressions: rc lines, empty keys, key-preserving migration, settings merge, CLAUDE_CONFIG_DIR"
T4="$(cd "$(mktemp -d)" && pwd -P)"
cat > "$T4/.zshrc" <<'RC'
alias cas='cd ~/Projects/claude-agent-stack && git pull'   # my shortcut
[ -f "/old/.claude/stack.env" ] && { set -a; . "/old/.claude/stack.env"; set +a; }  # claude-agent-stack
export EDITOR=vi
RC
export FAKE_CLAUDE_JSON="$T4/fake-claude.json" STACK_CLAUDE_JSON="$T4/fake-claude.json"
echo '{"mcpServers":{"exa":{"type":"http","url":"https://mcp.exa.ai/mcp","headers":{"x-api-key":"exa-only-in-config-1234"}},"jina":{"type":"http","url":"https://mcp.jina.ai/v1?exclude_tools=search_jina_blog","headersHelper":"/opt/op/jina-headers"}}}' > "$FAKE_CLAUDE_JSON"
mkdir -p "$T4/.claude"; { cat "$HERE/stack.env.example"; echo 'OPENAI_API_KEY=sk-mine-123'; echo 'MY_DIR=$HOME/work'; } > "$T4/.claude/stack.env"
chmod 600 "$T4/.claude/stack.env"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-plugins --no-deps >"$T4/.install.log" 2>&1 \
  && pass "install with profile step (scratch HOME) exits 0" || { failed "install with profile step failed"; tail -n 30 "$T4/.install.log"; }
grep -q "alias cas=" "$T4/.zshrc" && pass "unrelated rc line mentioning claude-agent-stack kept" || failed "unrelated rc line deleted"
[ "$(grep -c '# claude-agent-stack$' "$T4/.zshrc")" = 1 ] && grep -q 'with-stack-env" --print-env --reveal sh' "$T4/.zshrc" \
  && pass "old stack line replaced by exactly one new line" || failed "rc stack line not replaced exactly once"
B8="$(latest_backup "$T4/.claude")"
rcf="$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["rc"][sys.argv[2]]["file"])' "$B8/backup.json" "$T4/.zshrc" 2>/dev/null)"
[ -n "$rcf" ] && grep -q "alias cas=" "$B8/rc/$rcf" && ! grep -q 'with-stack-env' "$B8/rc/$rcf" && [ "$(fmode "$B8/rc/$rcf")" = 0o600 ] \
  && pass "rc file backed up (0600, the version before the edit) into the run's backup" || failed "no rc backup in [$B8]"
[ "$(readlink "$T4/.local/bin/claude-ninja")" = "$T4/.claude/bin/claude-ultracode" ] \
  && [ "$(readlink "$T4/.local/bin/claude-god")" = "$T4/.claude/bin/claude-ultracode" ] \
  && pass "claude-ninja and claude-god linked into ~/.local/bin" || failed "ultracode launchers not linked"
FAKE_CLAUDE_LOG="$T4/.fake.log" "$T4/.local/bin/claude-god" -p hello >/dev/null 2>&1
python3 - "$T4/.fake.log" <<'PY' && pass "claude-god starts god-coder as the main thread at ultracode, workflows pre-approved" || failed "claude-god arguments: $(tail -n 1 "$T4/.fake.log" 2>/dev/null)"
import json, sys
args = json.loads(open(sys.argv[1]).read().splitlines()[-1])
want = ["--agent", "god-coder", "--effort", "ultracode", "--settings", '{"permissions":{"allow":["Workflow"]}}', "-p", "hello"]
sys.exit(0 if args == want else 1)
PY
rcline="$(grep '# claude-agent-stack$' "$T4/.zshrc")"
out=$(env -i HOME="$T4" PATH="$PATH" HF_TOKEN=hf_user_token bash -c "$rcline
printf '%s' \"\$HF_TOKEN\"")
[ "$out" = hf_user_token ] && pass "empty HF_TOKEN= in stack.env no longer blanks an exported token" || failed "HF_TOKEN clobbered: [$out]"
out=$(env -i HOME="$T4" PATH="$PATH" bash -c "$rcline
printf '%s' \"\${EXA_API_KEY:-unset}\"")
[ "$out" = unset ] && pass "profile line exports only the CLI keys (EXA_API_KEY stays out of the shell)" || failed "profile line exported EXA_API_KEY"
out=$(env -i HOME="$T4" PATH="$PATH" bash -c "$rcline
printf '%s' \"\${OPENAI_API_KEY:-unset}\"")
[ "$out" = sk-mine-123 ] && grep -q '^STACK_EXPORT=".*OPENAI_API_KEY"$' "$T4/.claude/stack.env" \
  && pass "upgrade from the set -a line: your own stack.env variables stay exported (STACK_EXPORT)" || failed "own variable no longer exported: [$out]"
! grep -q '^STACK_EXPORT=.*MY_DIR' "$T4/.claude/stack.env" && grep -q 'MY_DIR use \$VAR expansion' "$T4/.install.log" \
  && pass "a \$VAR value is not claimed as exported; the installer says to move it" || failed "\$VAR value handling in the STACK_EXPORT migration"
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
    if g.get("matcher") == "Agent":
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
shipped = sum("agent_guard.py" in json.dumps(g) for g in json.load(open(sys.argv[2]))["hooks"]["PreToolUse"])
cmds = [h.get("command") for g in s["hooks"]["PreToolUse"] for h in g.get("hooks", [])]
ok = ("my-audit.sh" in cmds and sum("agent_guard.py" in (c or "") for c in cmds) == shipped and s["env"]["BLACKCAT_MAX_STEPS"] == "12"
      and s["env"]["STACK_FANOUT_IDLE_S"] == "900"
      and s["env"].get("ENABLE_TOOL_SEARCH") == "auto:5" and s.get("agent") == "claude"
      and s.get("skillListingBudgetFraction") == 0.05)
sys.exit(0 if ok else 1)
PY
grep -q "Olá" "$T4/dotfiles/settings.json" && pass "non-ASCII kept as-is" || failed "non-ASCII re-escaped"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >/dev/null 2>&1
[ "$(grep -c '# claude-agent-stack$' "$T4/.zshrc")" = 1 ] && pass "third run: still one rc line" || failed "rc line duplicated"
# the upgrade from the set -a profile line rewrites stack.env (STACK_EXPORT) and the rc file: a
# restore puts both back exactly
T4R="$(scratch_dir)" || exit 1
printf 'export EDITOR=vi\n[ -f "/old/.claude/stack.env" ] && { set -a; . "/old/.claude/stack.env"; set +a; }  # claude-agent-stack\n' > "$T4R/.zshrc"
mkdir -p "$T4R/.claude"; { cat "$HERE/stack.env.example"; echo 'OPENAI_API_KEY=sk-mine-123'; } > "$T4R/.claude/stack.env"; chmod 600 "$T4R/.claude/stack.env"
cp -p "$T4R/.zshrc" "$T4R/zshrc.before"; cp -p "$T4R/.claude/stack.env" "$T4R/env.before"
HOME="$T4R" FAKE_CLAUDE_JSON="$T4R/f.json" STACK_CLAUDE_JSON="$T4R/f.json" CLAUDE_CONFIG_DIR="$T4R/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >"$T4R/i.log" 2>&1
grep -q '^STACK_EXPORT=' "$T4R/.claude/stack.env" && ! cmp -s "$T4R/.zshrc" "$T4R/zshrc.before" \
  && HOME="$T4R" CLAUDE_CONFIG_DIR="$T4R/.claude" "$INSTALL" --restore latest >"$T4R/r.log" 2>&1 \
  && cmp -s "$T4R/.zshrc" "$T4R/zshrc.before" && cmp -s "$T4R/.claude/stack.env" "$T4R/env.before" \
  && [ -z "$(ls -A "$T4R/.claude/agents" 2>/dev/null)" ] \
  && pass "--restore undoes the profile upgrade: rc file and stack.env byte-identical again, stack files gone" \
  || { failed "restore after the profile upgrade"; tail -n 8 "$T4R/r.log" | sed 's/^/    /'; }
drop_scratch "$T4R"
# fresh CLAUDE_CONFIG_DIR without STACK_CLAUDE_JSON: the plan must read <dir>/.claude.json even before it exists
T5="$(cd "$(mktemp -d)" && pwd -P)"
plan=$(env -u STACK_CLAUDE_JSON CLAUDE_CONFIG_DIR="$T5" "$INSTALL" --mcp-plan 2>&1)
printf '%s\n' "$plan" | grep -qF "config read for the plan: $T5/.claude.json" && pass "--mcp-plan reads \$CLAUDE_CONFIG_DIR/.claude.json" \
  || failed "--mcp-plan read the wrong config: $(printf '%s\n' "$plan" | grep 'config read')"
# stack.env referencing an unset variable must not abort the installer (bash 3.2 even exited 0)
mkdir -p "$T5/c"; sed 's#^IMAGE_STUDIO_OUT_DIR=.*#IMAGE_STUDIO_OUT_DIR=$XDG_PICTURES_DIR/studio#' "$HERE/stack.env.example" \
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
printf '# an old install\n' > "$T5/c/mcp/opper_image_mcp.py"
printf '# an old install\n' > "$T5/c/mcp/openrouter_image_mcp.py"
FAKE_CLAUDE_JSON="$T5/f.json" STACK_CLAUDE_JSON="$T5/f.json" CLAUDE_CONFIG_DIR="$T5/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5/.log2" 2>&1
B5="$(latest_backup "$T5/c")"
if [ ! -e "$T5/c/mcp/opper_image_mcp.py" ] && [ ! -e "$T5/c/mcp/openrouter_image_mcp.py" ] \
   && [ -f "$B5/files/mcp/opper_image_mcp.py" ] && [ -f "$B5/files/mcp/openrouter_image_mcp.py" ] \
   && grep -qx '  - mcp/opper_image_mcp.py  (images come from image-studio now)' "$T5/.log2" \
   && grep -qx '  - mcp/openrouter_image_mcp.py  (images come from image-studio now)' "$T5/.log2"; then
  pass "the retired Opper and OpenRouter image servers are removed, listed and kept in the backup"
else
  failed "an old image server was not removed"; grep -E '^  [-~] |^removed' "$T5/.log2" | sed 's/^/    /'
fi
printf '# an old install\n' > "$T5/c/mcp/openrouter_image_mcp.py"
printf '\n# my edit: args ["run", "--script", "%s/mcp/openrouter_image_mcp.py"]\n' "$T5/c" >> "$T5/c/agents/image-director.md"
FAKE_CLAUDE_JSON="$T5/f.json" STACK_CLAUDE_JSON="$T5/f.json" CLAUDE_CONFIG_DIR="$T5/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --no-prune >"$T5/.log3" 2>&1
if [ -f "$T5/c/mcp/openrouter_image_mcp.py" ] && grep -q '# my edit' "$T5/c/agents/image-director.md" \
   && grep -qF 'note: mcp/openrouter_image_mcp.py: images come from image-studio now — kept (--no-prune)' "$T5/.log3"; then
  pass "--no-prune: an edited agent and the older image server it starts are kept, with a note"
else
  failed "--no-prune removed the older image server or the edited agent"; grep -i -E 'openrouter|note' "$T5/.log3" | sed 's/^/    /'
fi
# stack.env written by earlier versions (Opper → OpenRouter-only → Lumenfall): the image lines are
# brought up to date, the models appended set to the defaults, nothing of the user's changed
T5B="$(cd "$(mktemp -d)" && pwd -P)"; mkdir -p "$T5B/c"
cat > "$T5B/c/stack.env" <<'ENV'
# my own header line
# Opper gateway — image generation/editing (image-director). https://platform.opper.ai
OPPER_API_KEY=op-mine-123
# Default image model and output folder (optional)
OPPER_IMAGE_MODEL=bytedance:ap/seedream-5-pro
OPPER_IMAGE_OUT_DIR=$HOME/Pictures/opper
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
# Lumenfall — generate_svg: Recraft V4.1 Pro SVG for logos, icons, illustrations and other graphics
# (about $0.30 an image). https://lumenfall.ai/app
#LUMENFALL_API_KEY=
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
   && grep -q 'appended the image models, set to the defaults' "$T5B/.log" && grep -q 'brought the image lines' "$T5B/.log" \
   && ! grep -q 'note: stack.env sets' "$T5B/.log"; then
  pass "stack.env from earlier versions: image lines brought up to date, models set, values kept, backup made"
else
  failed "stack.env from earlier versions"; sed 's/^/    /' "$E"; grep -i 'stack.env' "$T5B/.log" | sed 's/^/    /'
fi
cp -p "$E" "$T5B/after1.env"
FAKE_CLAUDE_JSON="$T5B/f.json" STACK_CLAUDE_JSON="$T5B/f.json" CLAUDE_CONFIG_DIR="$T5B/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5B/.log2" 2>&1
cmp -s "$E" "$T5B/after1.env" && ! grep -qE '^  (stack.env|note): ' "$T5B/.log2" \
  && pass "stack.env: a second run changes nothing" || failed "stack.env: a second run changed it: $(diff "$T5B/after1.env" "$E" | head -5)"
printf 'LUMENFALL_API_KEY=lf-mine-9\nOPPER_IMAGE_MODEL=acme/my-choice\n' >> "$E"
FAKE_CLAUDE_JSON="$T5B/f.json" STACK_CLAUDE_JSON="$T5B/f.json" CLAUDE_CONFIG_DIR="$T5B/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5B/.log3" 2>&1
if grep -q '^LUMENFALL_API_KEY=lf-mine-9$' "$E" && grep -q '^OPPER_IMAGE_MODEL=acme/my-choice$' "$E" \
   && grep -q "note: stack.env sets LUMENFALL_API_KEY, which image-studio doesn't read" "$T5B/.log3" \
   && grep -q "note: stack.env sets OPPER_IMAGE_MODEL, which image-studio doesn't read (generate_image's model is IMAGE_STUDIO_IMAGE_MODEL)" "$T5B/.log3" \
   && ! grep -q 'lf-mine-9' "$T5B/.log3"; then
  pass "stack.env: settings of yours that nothing reads are kept and named, never printed"
else
  failed "stack.env: retired settings of the user"; grep -i 'stack.env' "$T5B/.log3" | sed 's/^/    /'
fi
# first install over the user's own CLAUDE.md (kept) and a same-named skill of their own (the
# stack owns skills/: replaced, the backup keeps it)
T6="$(cd "$(mktemp -d)" && pwd -P)"; printf '# my rules\n- my NAS is 192.168.1.20\n' > "$T6/CLAUDE.md"
mkdir -p "$T6/skills/data-analysis"
printf -- '---\nname: data-analysis\ndescription: my own steps\n---\nMy own analysis steps.\n' > "$T6/skills/data-analysis/SKILL.md"
CLAUDE_CONFIG_DIR="$T6" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T6/.log" 2>&1
grep -q 192.168.1.20 "$T6/CLAUDE.md" && [ ! -e "$T6/CLAUDE.md.new" ] && [ -f "$T6/rules/claude-agent-stack.md" ] \
  && pass "user's own CLAUDE.md untouched; the stack's rules load from rules/claude-agent-stack.md" || failed "user's own CLAUDE.md changed, or rules missing"
B6="$(latest_backup "$T6")"
! grep -q 'My own analysis steps' "$T6/skills/data-analysis/SKILL.md" && [ ! -e "$T6/skills/data-analysis/SKILL.md.new" ] \
  && grep -q 'My own analysis steps' "$B6/files/skills/data-analysis/SKILL.md" \
  && grep -qx "  ~ skills/data-analysis/SKILL.md  (a same-named file that isn't the stack's)" "$T6/.log" \
  && pass "same-named personal skill replaced by the stack's, listed, and kept in the backup" || failed "personal skill not replaced/listed/backed up"
# the stack's own (unedited) CLAUDE.md from an earlier version goes (the backup keeps it)
T7="$(cd "$(mktemp -d)" && pwd -P)"
sed "s#__CLAUDE_DIR__#$T7#g; s#__HOME__#$HOME#g" "$HERE/legacy/be5b940/CLAUDE.md" > "$T7/CLAUDE.md"
cp "$T7/CLAUDE.md" "$T7/CLAUDE.md.new"
CLAUDE_CONFIG_DIR="$T7" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T7/.log" 2>&1
B7="$(latest_backup "$T7")"
[ ! -e "$T7/CLAUDE.md" ] && [ ! -e "$T7/CLAUDE.md.new" ] && [ -f "$B7/files/CLAUDE.md" ] && [ -f "$B7/files/CLAUDE.md.new" ] \
  && [ -f "$T7/rules/claude-agent-stack.md" ] && ! grep -q 'Merge each' "$T7/.log" \
  && grep -q '^  - CLAUDE.md  (the stack.s old rules file' "$T7/.log" \
  && pass "the stack's old CLAUDE.md (and its leftover .new) removed into the backup, rules installed" || failed "legacy stack CLAUDE.md not removed"
T9="$(cd "$(mktemp -d)" && pwd -P)"
{ sed "s#__CLAUDE_DIR__#$T9#g" "$HERE/legacy/be5b940/CLAUDE.md"; printf '\n## Mine\n- my NAS is 192.168.1.20\n'; } > "$T9/CLAUDE.md"
CLAUDE_CONFIG_DIR="$T9" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T9/.log" 2>&1
grep -q 192.168.1.20 "$T9/CLAUDE.md" && grep -q 'CLAUDE.md .*kept (it has lines of your own)' "$T9/.log" \
  && pass "an untracked CLAUDE.md with lines of your own is kept (with advice)" || failed "CLAUDE.md with the user's own lines was retired"
cp "$B7/files/CLAUDE.md" "$T7/CLAUDE.md"     # the user deliberately puts it back
CLAUDE_CONFIG_DIR="$T7" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T7/.log2" 2>&1
[ -f "$T7/CLAUDE.md" ] && pass "CLAUDE.md migration runs once: a restored CLAUDE.md is left alone" || failed "a restored CLAUDE.md was moved again"
assert_unchanged_real_home
# a tracked CLAUDE.md the user trimmed (two stack rules deleted) is theirs: kept, not retired
T10="$(cd "$(mktemp -d)" && pwd -P)"
sed "s#__CLAUDE_DIR__#$T10#g" "$HERE/legacy/be5b940/CLAUDE.md" > "$T10/full.md"
python3 - "$T10" <<'PY'
import hashlib, json, os, sys
t = sys.argv[1]
full = open(os.path.join(t, "full.md")).read()
json.dump({"files": {"CLAUDE.md": hashlib.sha256(full.encode()).hexdigest()}}, open(os.path.join(t, ".stack-manifest.json"), "w"))
open(os.path.join(t, "CLAUDE.md"), "w").write("".join(l for l in full.splitlines(True) if "European Portuguese" not in l and "is an expert" not in l))
PY
CLAUDE_CONFIG_DIR="$T10" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T10/.log" 2>&1
[ -f "$T10/CLAUDE.md" ] && grep -q 'CLAUDE.md .*kept' "$T10/.log" \
  && pass "a tracked CLAUDE.md you trimmed is kept (only a hash match is retired)" || failed "trimmed tracked CLAUDE.md was retired"
assert_unchanged_real_home
# senior-coder became main-coder: the old file goes whatever its state (the backup keeps it), listed
# as renamed; --no-prune keeps an edited one with a note, and doctor flags it.
T11="$(cd "$(mktemp -d)" && pwd -P)"; T12="$(cd "$(mktemp -d)" && pwd -P)"
mkdir -p "$T11/agents" "$T12/agents"
CLAUDE_CONFIG_DIR="$T11" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1   # learn the render
python3 - "$T11" "$HERE" <<'PY'
import os, re, sys
t, here = sys.argv[1:3]
# render the legacy template the way the installer does: take the substitutions from a rendered agent
coder = open(os.path.join(t, "agents", "coder.md")).read()
uv = re.search(r'command: "([^"]*/uv)"', coder).group(1)
old = open(os.path.join(here, "legacy", "be5b940", "agents", "senior-coder.md")).read()
open(os.path.join(t, "agents", "senior-coder.md"), "w").write(old.replace("__UV__", uv).replace("__CLAUDE_DIR__", t))
PY
cp "$T11/agents/senior-coder.md" "$T11/agents/senior-coder.md.new"
T13="$(cd "$(mktemp -d)" && pwd -P)"; mkdir -p "$T13/agents"
sed 's#__UV__#/opt/somewhere-else/bin/uv#g; s#__CLAUDE_DIR__#/Users/someone/.claude#g' \
  "$HERE/legacy/be5b940/agents/senior-coder.md" > "$T13/agents/senior-coder.md"
CLAUDE_CONFIG_DIR="$T13" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T13/.log" 2>&1
[ ! -e "$T13/agents/senior-coder.md" ] && [ -f "$(latest_backup "$T13")/files/agents/senior-coder.md" ] \
  && grep -qx '  - agents/senior-coder.md  (renamed: now agents/main-coder.md)' "$T13/.log" \
  && pass "an untracked old senior-coder.md rendered with other paths is removed as renamed (backup keeps it)" \
  || failed "old senior-coder.md with other rendered paths not removed: $(grep senior "$T13/.log")"
CLAUDE_CONFIG_DIR="$T11" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T11/.log" 2>&1
B11="$(latest_backup "$T11")"
[ ! -e "$T11/agents/senior-coder.md" ] && [ ! -e "$T11/agents/senior-coder.md.new" ] \
  && [ -f "$B11/files/agents/senior-coder.md" ] && [ -f "$B11/files/agents/senior-coder.md.new" ] \
  && grep -qx '  - agents/senior-coder.md  (renamed: now agents/main-coder.md)' "$T11/.log" \
  && pass "old senior-coder.md (and its .new) removed: it is now main-coder" || failed "old senior-coder.md not removed"
printf -- '---\nname: senior-coder\ndescription: "x"\nmodel: claude-opus-5-5\n---\nmine\n' > "$T12/agents/senior-coder.md"
python3 - "$T12" <<'PY'
import json, os, sys
t = sys.argv[1]
json.dump({"files": {"agents/senior-coder.md": "0" * 64}}, open(os.path.join(t, ".stack-manifest.json"), "w"))
PY
CLAUDE_CONFIG_DIR="$T12" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --no-prune >"$T12/.log" 2>&1
[ -f "$T12/agents/senior-coder.md" ] && grep -q 'mine' "$T12/agents/senior-coder.md" \
  && grep -qF 'note: agents/senior-coder.md: renamed: now agents/main-coder.md — kept (--no-prune)' "$T12/.log" \
  && pass "--no-prune: an edited senior-coder.md is kept with a note" || failed "edited senior-coder.md under --no-prune"
"$T12/bin/doctor.sh" >"$T12/.doctor" 2>&1
grep -q "senior-coder.md is the stack's old name for main-coder" "$T12/.doctor" \
  && pass "doctor flags the kept senior-coder.md" || failed "doctor does not flag senior-coder.md"
# the main-thread router became blackcat: an old router.md goes, and the settings
# follow the rename ("agent": "router", a tuned ROUTER_* knob, the Agent(router) deny rule)
T14="$(cd "$(mktemp -d)" && pwd -P)"
CLAUDE_CONFIG_DIR="$T14" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >/dev/null 2>&1
python3 - "$T14" <<'PY'
import hashlib, json, os, sys
t = sys.argv[1]
old = open(os.path.join(t, "agents", "blackcat.md")).read().replace("name: blackcat", "name: router")
open(os.path.join(t, "agents", "router.md"), "w").write(old)
ren = lambda k: k.replace("BLACKCAT_", "ROUTER_")
deny = lambda xs: [x.replace("Agent(blackcat)", "Agent(router)") for x in xs]
mp = os.path.join(t, ".stack-manifest.json"); m = json.load(open(mp))
m["files"]["agents/router.md"] = hashlib.sha256(old.encode()).hexdigest()
m["settings_env"] = {ren(k): v for k, v in m["settings_env"].items()}
m["settings_set_if_absent"]["agent"] = "router"
m["settings_permissions"]["deny"] = deny(m["settings_permissions"]["deny"])
json.dump(m, open(mp, "w"))
sp = os.path.join(t, "settings.json"); s = json.load(open(sp))
s["agent"] = "router"
s["env"] = {ren(k): v for k, v in s["env"].items()}
s["env"]["ROUTER_MAX_STEPS"] = "20"
s["env"]["ROUTER_DISPATCH_WINDOW_S"] = "45"
s["permissions"]["deny"] = deny(s["permissions"]["deny"])
json.dump(s, open(sp, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$T14" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T14/.log" 2>&1
[ ! -e "$T14/agents/router.md" ] && [ -f "$(latest_backup "$T14")/files/agents/router.md" ] \
  && grep -qx '  - agents/router.md  (renamed: now agents/blackcat.md)' "$T14/.log" \
  && pass "an old router.md is removed as renamed: it is now blackcat" || failed "old router.md not removed"
python3 - "$T14/settings.json" <<'PY' && pass "settings follow router -> blackcat: agent, tuned knob moved, defaults and deny rule" || failed "router settings not migrated"
import json, sys
s = json.load(open(sys.argv[1])); e = s["env"]; deny = s["permissions"]["deny"]
ok = (s.get("agent") == "blackcat" and e.get("BLACKCAT_MAX_STEPS") == "12" and e.get("BLACKCAT_DISPATCH_WINDOW_S") == "45"
      and e.get("BLACKCAT_MAX_DISPATCH") == "8"
      and not any(k.startswith("ROUTER_") for k in e) and "Agent(blackcat)" in deny and "Agent(router)" not in deny)
sys.exit(0 if ok else 1)
PY
assert_unchanged_real_home
rm -rf "$T4" "$T5" "$T6" "$T7" "$T9" "$T10" "$T11" "$T12" "$T13" "$T14"

echo "== 9. macOS render (simulated): the After Effects server only once it is built"
T8="$(cd "$(mktemp -d)" && pwd -P)"
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
# f) a clone whose only checkout is on a feature branch: it switches to main and fast-forwards
tgit clone -q "$R0/remote.git" "$R0/solo" && tgit -C "$R0/solo" switch -q -c feat3
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

echo "== 12. One copy of each skill: plugin duplicates of synced skills and retired plugins disabled by default (fake claude)"
TD="$(scratch_dir)" || exit 1
mkdir -p "$TD/c/skills/synced/0000-sync/docx" "$TD/c/skills/synced/0000-sync/skill-creator"
printf -- '---\nname: docx\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/docx/SKILL.md"
printf -- '---\nname: skill-creator\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/skill-creator/SKILL.md"
printf '{"enabledPlugins": {"document-skills@anthropic-agent-skills": true, "skill-creator@claude-plugins-official": true, "mcp-server-dev@claude-plugins-official": true}}\n' > "$TD/c/settings.json"
FAKE_CLAUDE_LOG="$TD/calls0.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile --keep-plugin-duplicates >"$TD/i0.log" 2>&1
if ! grep -qF '"disable"' "$TD/calls0.log" && ! grep -qF '"install", "document-skills@' "$TD/calls0.log" \
   && grep -qF 'plugin document-skills@anthropic-agent-skills duplicates the synced anthropic-skills:docx/xlsx/pptx/pdf in the skill listing (kept: --keep-plugin-duplicates)' "$TD/i0.log" \
   && grep -qF 'plugin mcp-server-dev@claude-plugins-official overlaps the stack' "$TD/i0.log"; then
  pass "--keep-plugin-duplicates: duplicate and retired plugins stay enabled, each named"
else
  failed "plugins touched under --keep-plugin-duplicates"; grep -i plugin "$TD/i0.log" | sed 's/^/    /'
fi
FAKE_CLAUDE_LOG="$TD/calls.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile --with-extra-plugins >"$TD/i.log" 2>&1
deduped_is(){ python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("plugins_deduped") == sys.argv[2:] else 1)' "$TD/c/.stack-manifest.json" "$@"; }
BD="$(latest_backup "$TD/c")"
if grep -qF '["plugin", "disable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls.log" \
   && grep -qF '["plugin", "disable", "skill-creator@claude-plugins-official", "--scope", "user"]' "$TD/calls.log" \
   && grep -qF '["plugin", "disable", "mcp-server-dev@claude-plugins-official", "--scope", "user"]' "$TD/calls.log" \
   && ! grep -qF '"install", "document-skills@' "$TD/calls.log" && ! grep -qF '"install", "skill-creator@' "$TD/calls.log" \
   && grep -qF '["plugin", "install", "math-olympiad@claude-plugins-official", "--scope", "user"]' "$TD/calls.log" \
   && grep -qF 'To undo: claude plugin enable document-skills@anthropic-agent-skills --scope user' "$TD/i.log" \
   && grep -qF 'To undo: claude plugin enable skill-creator@claude-plugins-official --scope user' "$TD/i.log" \
   && grep -qF 'To undo: claude plugin enable mcp-server-dev@claude-plugins-official --scope user' "$TD/i.log" \
   && deduped_is document-skills@anthropic-agent-skills mcp-server-dev@claude-plugins-official skill-creator@claude-plugins-official \
   && python3 -c 'import json, sys; sys.exit(0 if sorted(json.load(open(sys.argv[1]))["plugins_disabled"]) == sys.argv[2:] else 1)' \
        "$BD/backup.json" document-skills@anthropic-agent-skills mcp-server-dev@claude-plugins-official skill-creator@claude-plugins-official; then
  pass "default: duplicates and mcp-server-dev disabled (not installed), math-olympiad installed, undo printed, recorded in manifest and backup"
else
  failed "default plugin dedupe"; tail -n 14 "$TD/i.log" | sed 's/^/    /'
fi
rm -rf "$TD/c/skills/synced/0000-sync/docx"
FAKE_CLAUDE_LOG="$TD/calls2.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile >"$TD/i2.log" 2>&1
if grep -qF '["plugin", "enable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls2.log" \
   && ! grep -qF '"enable", "skill-creator@' "$TD/calls2.log" \
   && deduped_is mcp-server-dev@claude-plugins-official skill-creator@claude-plugins-official; then
  pass "a deduped plugin is re-enabled once its synced skill is gone; the others stay disabled"
else
  failed "re-enable after the synced skill went away"; grep -i plugin "$TD/i2.log" | sed 's/^/    /'
fi
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
    s["env"].pop(k)
s["env"].update({"STACK_MAX_FANOUT": "8", "STACK_MAX_SELF_FANOUT": "4", "BLACKCAT_MAX_DISPATCH": "3",
                 "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "32"})
json.dump(s, open(p, "w"), indent=2)
PY
tgit -C "$TR/repo" commit -qam "rollback" || failed "could not commit the rollback repository"
CLAUDE_CONFIG_DIR="$TR/c" "$TR/repo/install.sh" --no-mcp --no-plugins --no-deps --no-profile >"$TR/r.log" 2>&1
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
grep -q 'retracted stack skillOverrides for code-review, fewer-permission-prompts, init, keybindings-help, security-review' "$TR/r.log" \
  && grep -q 'retracted stack setting skillListingMaxDescChars=500' "$TR/r.log" \
  && pass "rollback: each retraction is reported" || failed "rollback retraction messages: $(grep -i retract "$TR/r.log")"
assert_unchanged_real_home
drop_scratch "$TR"

echo "== 14. Copy types: researcher-copy and coder-copy rendered from their base agents"
TC="$(scratch_dir)" || exit 1
CLAUDE_CONFIG_DIR="$TC/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$TC/i.log" 2>&1
python3 - "$TC/c/agents" <<'PY' && pass "copies: own name and short description, same tools/model/maxTurns/mcpServers, May spawn = base minus base and copies, body names no copy" || failed "copy-type rendering"
import os, re, sys
d = sys.argv[1]
def fm(text):
    head = text.split("\n---\n", 1)[0]
    return {m.group(1): m.group(2) for m in re.finditer(r"(?m)^([A-Za-z]+): ?(.*)$", head)}, head
def may(text):
    m = re.search(r"May spawn:\s*([^.]*)\.", text)
    if not m:
        return []
    parts, cur, depth = [], "", 0
    for ch in m.group(1):
        depth += (ch in "([") - (ch in ")]")
        if ch == "," and depth == 0:
            parts.append(cur.strip()); cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [re.match(r"[A-Za-z0-9_-]+", p).group(0).lower() for p in parts if p]
ok = True
for base in ("researcher", "coder"):
    b, c = (open(os.path.join(d, n + ".md")).read() for n in (base, base + "-copy"))
    (bf, bh), (cf, ch) = fm(b), fm(c)
    checks = {
        "name": cf.get("name") == base + "-copy",
        "description": cf.get("description") == '"Copy of %s for one independent part; spawned only by %s."' % (base, base),
        "same frontmatter": all(cf.get(k) == bf.get(k) for k in ("tools", "model", "effort", "maxTurns", "color")),
        "same mcpServers": bh.partition("mcpServers:")[2] == ch.partition("mcpServers:")[2],
        "base lists its copy": base + "-copy" in may(b) and base not in may(b),
        "copy May spawn": may(c) == [x for x in may(b) if x != base and not x.endswith("-copy")],
        "copy note": "You are a copy of %s" % base in c,
        # a copy spawns no copies: its body names no <type>-copy agent (the base body's
        # "sub-tasks can go to coder-copy agents" lines are rewritten away)
        "copy body names no -copy": not re.search(r"[A-Za-z0-9_]-copy\b", c.split("\n---\n", 1)[1]),
        "base body still names its copy": base + "-copy" in b.split("\n---\n", 1)[1],
    }
    for k, v in checks.items():
        if not v:
            print("    %s-copy: %s wrong" % (base, k)); ok = False
sys.exit(0 if ok else 1)
PY
grep -q 'agents/researcher-copy.md *installed' "$TC/i.log" && grep -q 'agents/coder-copy.md *installed' "$TC/i.log" \
  && pass "copies are installed and tracked like the other agents" || failed "copies not installed: $(grep -- '-copy' "$TC/i.log")"
assert_unchanged_real_home
drop_scratch "$TC"

echo "== 15. A drifted config: --dry-run, default prune, one backup that restores exactly, idempotence, --no-prune"
TX="$(scratch_dir)" || exit 1
# one line per file or link under a config dir (relpath, kind, sha256, mode), Claude Code's own state
# and the legacy in-config backups aside
cat > "$TX/fingerprint.py" <<'PY'
import hashlib, os, stat, sys
root, out = sys.argv[1], []
skip = {"projects", "sessions", "statsig", "todos", "shell-snapshots", "venvs", "plugins"}
for d, dirs, files in os.walk(root):
    rel_d = os.path.relpath(d, root)
    top = rel_d.split(os.sep)[0]
    if top in skip or top.startswith("backup-"):
        dirs[:] = []
        continue
    for f in sorted(files) + sorted(x for x in dirs if os.path.islink(os.path.join(d, x))):
        p, rel = os.path.join(d, f), os.path.normpath(os.path.join(rel_d, f))
        if rel.startswith("backup-") or rel.startswith(".install"):
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
make_dirty(){ # stale, renamed, modified and unknown files; duplicated hooks and rules; junk
  local T="$1"
  cp "$HERE/legacy/be5b940/agents/senior-coder.md" "$T/agents/senior-coder.md"
  printf -- '---\nname: my-own\ndescription: mine\n---\nhello\n' > "$T/agents/my-own.md"
  printf '\n<!-- local edit -->\n' >> "$T/agents/coder.md"
  cp "$T/agents/coder.md" "$T/agents/coder.md.new"
  mkdir -p "$T/agents/team"; printf -- '---\nname: team-a\ndescription: x\n---\n' > "$T/agents/team/a.md"
  mkdir -p "$T/skills/old-skill"; printf -- '---\nname: old-skill\ndescription: old\n---\n' > "$T/skills/old-skill/SKILL.md"
  printf 'my notes\n' > "$T/skills/python-engineering/notes.md"
  printf '\nlocal tweak\n' >> "$T/skills/python-engineering/SKILL.md"
  mkdir -p "$T/skills/synced/abc/docx"; printf -- '---\nname: docx\ndescription: synced\n---\n' > "$T/skills/synced/abc/docx/SKILL.md"
  printf '#!/bin/sh\n' > "$T/hooks/router-guard.sh"
  printf '# old\n' > "$T/mcp/opper_image_mcp.py"
  printf '#!/bin/sh\necho mine\n' > "$T/hooks/my-hook.sh"; chmod +x "$T/hooks/my-hook.sh"
  printf '# My rule\n- be nice\n' > "$T/rules/my-rule.md"
  cp "$T/rules/claude-agent-stack.md" "$T/rules/claude-agent-stack.md.new"
  printf '{}' > "$T/settings.json.tmp"
  mkdir -p "$T/backup-20250101-000000-abc"; printf 'EXA_API_KEY=fake-legacy\n' > "$T/backup-20250101-000000-abc/stack.env"
  chmod 644 "$T/backup-20250101-000000-abc/stack.env"
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
json.dump(mf, open(man, "w"), indent=2, sort_keys=True)
PY
}
xrun "$TX/c" "$TX/0.log" && fp "$TX/c" > "$TX/fp.clean" || failed "15: clean install failed"
make_dirty "$TX/c"
fp "$TX/c" > "$TX/fp.dirty"; nb0=$(count_backups "$TX/c")
xrun "$TX/c" "$TX/dry.log" --dry-run; rc=$?
fp "$TX/c" > "$TX/fp.dry"
[ "$rc" = 0 ] && cmp -s "$TX/fp.dirty" "$TX/fp.dry" && [ "$(count_backups "$TX/c")" = "$nb0" ] \
  && [ -d "$TX/c/backup-20250101-000000-abc" ] && grep -q 'Dry run done: nothing was changed' "$TX/dry.log" \
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
  - agents/coder.md.new  (leftover render of a stack file)
  - agents/my-own.md  (not shipped by the stack: yours or another tool's)
  - agents/senior-coder.md  (renamed: now agents/main-coder.md)
  - agents/team/  (not shipped by the stack: yours or another tool's)
  - hooks/router-guard.sh  (blackcat.md runs agent_guard.py directly now)
  - mcp/opper_image_mcp.py  (images come from image-studio now)
  - rules/claude-agent-stack.md.new  (leftover render of a stack file)
  - settings.json.tmp  (leftover of an interrupted install)
  - skills/old-skill/  (not shipped by the stack: yours or another tool's)
  - skills/python-engineering/notes.md  (not part of the stack's python-engineering skill)
  - magg catalog: oldsrv  (no longer shipped by the stack)
  - settings.json hooks.PreToolUse[Bash]: "/usr/bin/python3" "/old/config/hooks/agent_guard.py" no-push  (an earlier copy of the stack's guard hook; the current one replaces it)
  - settings.json hooks.Notification: "/usr/bin/python3" "/old/hooks/agent_guard.py"  (the stack's guard no longer runs on it)
  - settings.json hooks  (2 duplicate hook entries)
  - settings.json permissions.allow  (1 duplicate rule)
  ~ agents/coder.md  (edited since the last install)
  ~ skills/python-engineering/SKILL.md  (edited since the last install)
  ~ magg catalog: docling  (differed from the stack's entry)
EOF_WANT
[ -z "$missing" ] && pass "pruned and listed: stale, renamed, modified, unknown files, junk, magg entries, duplicate hooks and rules" \
  || { failed "listing is missing:$missing"; sed 's/^/    /' "$TX/list.real"; }
python3 - "$TX/c" "$HERE" "$B15" "$BK_ROOT" "$EXPECTED_AGENTS" <<'PY' && pass "after the prune: only the stack's agents and skills, user hook/rule/magg entry kept, no duplicates, sandbox on, stack.env 0600, backup 0700/0600, legacy backup moved out" || failed "post-prune state (see above)"
import json, os, stat, sys
c, here, b, bk, n_agents = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
bad = []
def check(ok, what):
    if not ok:
        bad.append(what)
mode = lambda p: stat.S_IMODE(os.lstat(p).st_mode)
agents = sorted(os.listdir(os.path.join(c, "agents")))
check(len(agents) == n_agents and all(a.endswith(".md") for a in agents), "agents/: %s" % agents[:5])
check("<!-- local edit -->" not in open(os.path.join(c, "agents", "coder.md")).read(), "coder.md edit kept")
shipped = sorted(d for d in os.listdir(os.path.join(here, "dot-claude", "skills")) if os.path.isdir(os.path.join(here, "dot-claude", "skills", d)))
check(sorted(os.listdir(os.path.join(c, "skills"))) == sorted(shipped + ["synced"]), "skills/ != shipped + synced")
check(os.path.isfile(os.path.join(c, "skills", "synced", "abc", "docx", "SKILL.md")), "synced skill touched")
check(not os.path.exists(os.path.join(c, "skills", "python-engineering", "notes.md")), "extra skill file kept")
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
check(not os.path.exists(os.path.join(c, "backup-20250101-000000-abc")), "legacy backup left in the config dir")
leg = os.path.join(bk, "legacy", "backup-20250101-000000-abc")
check(os.path.isdir(leg) and mode(leg) == 0o700 and mode(os.path.join(leg, "stack.env")) == 0o600, "legacy backup not moved/locked down")
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
  && pass "--restore latest puts the drifted config back byte- and mode-exactly (the legacy backup aside)" \
  || failed "restore not exact (rc=$rc): $(diff "$TX/fp.dirty" "$TX/fp.restored" | head -8)"
xrun "$TX/c" "$TX/reprune.log"
cmp -s "$TX/fp.pruned" <(fp "$TX/c") && pass "installing again after the restore gives the same pruned config" \
  || failed "re-install after restore differs: $(diff "$TX/fp.pruned" <(fp "$TX/c") | head -5)"
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
# --no-prune over the same drift: nothing of the user's goes, edits kept with a .new beside them
xrun "$TX/n" "$TX/n0.log" && make_dirty "$TX/n"
xrun "$TX/n" "$TX/n.log" --no-prune; rc=$?
python3 - "$TX/n" <<'PY' && [ "$rc" = 0 ] && pass "--no-prune keeps old, unknown and edited files (edits get a .new), still removes duplicates and temp junk" || failed "--no-prune (rc=$rc; see above)"
import json, os, sys
n = sys.argv[1]
keep = ["agents/senior-coder.md", "agents/my-own.md", "agents/team/a.md", "skills/old-skill/SKILL.md",
        "skills/python-engineering/notes.md", "hooks/router-guard.sh", "mcp/opper_image_mcp.py",
        "agents/coder.md.new", "skills/python-engineering/SKILL.md.new"]
bad = [k for k in keep if not os.path.exists(os.path.join(n, k))]
if "<!-- local edit -->" not in open(os.path.join(n, "agents", "coder.md")).read():
    bad.append("coder.md edit lost")
if os.path.exists(os.path.join(n, "settings.json.tmp")):
    bad.append("settings.json.tmp kept")
m = json.load(open(os.path.join(n, "magg", "config.json")))["servers"]
if "oldsrv" not in m or m["docling"]["command"] != "my-docling":
    bad.append("magg entries changed")
s = json.load(open(os.path.join(n, "settings.json")))
if len(s["permissions"]["allow"]) != len(set(s["permissions"]["allow"])):
    bad.append("duplicate permissions kept")
if bad:
    print("    " + ", ".join(bad))
sys.exit(1 if bad else 0)
PY
grep -qF 'note: agents/my-own.md: not shipped by the stack: yours or another tool'"'"'s — kept (--no-prune)' "$TX/n.log" \
  && grep -qF 'note: magg catalog: oldsrv is no longer shipped (kept: --no-prune)' "$TX/n.log" \
  && pass "--no-prune names what it kept" || failed "--no-prune notes: $(grep 'note:' "$TX/n.log" | head -5)"
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
for f in --dry-run --no-prune --restore --print-managed-settings --keep-plugin-duplicates --force; do
  printf '%s\n' "$help" | grep -q -- "$f" || failed "--help does not mention $f"
done
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
# a per-skill symlink (skills/ itself a real dir) is replaced by the stack's skill: default, --no-prune
# and --dry-run agree; the link's target is never written (the backup keeps the link)
xrun "$TX/k" "$TX/k0.log"
mkdir -p "$TX/outK"; cp -R "$TX/k/skills/python-engineering/." "$TX/outK/"; printf '\nmine\n' >> "$TX/outK/SKILL.md"
rm -rf "$TX/k/skills/python-engineering"; ln -s "$TX/outK" "$TX/k/skills/python-engineering"
fp "$TX/outK" > "$TX/fp.k0"
xrun "$TX/k" "$TX/k1.log" --dry-run; rcd=$?
cp -R "$TX/k" "$TX/k2"; rm -rf "$TX/k2/skills/python-engineering"; ln -s "$TX/outK" "$TX/k2/skills/python-engineering"
xrun "$TX/k2" "$TX/k3.log" --no-prune; rcn=$?
xrun "$TX/k" "$TX/k2.log"; rc=$?
BK="$(latest_backup "$TX/k")"
[ "$rcd" = 0 ] && [ "$rc" = 0 ] && [ "$rcn" = 0 ] && cmp -s "$TX/fp.k0" <(fp "$TX/outK") \
  && [ -d "$TX/k/skills/python-engineering" ] && [ ! -L "$TX/k/skills/python-engineering" ] \
  && [ -f "$TX/k/skills/python-engineering/SKILL.md" ] && [ -L "$BK/files/skills/python-engineering" ] \
  && pass "a per-skill symlink: the stack's skill replaces the link (default, --no-prune, --dry-run agree); its target is untouched" \
  || failed "per-skill symlink (rc=$rc, dry=$rcd, no-prune=$rcn): $(grep -i 'refus' "$TX/k1.log" "$TX/k2.log" "$TX/k3.log" | head -3)"
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
# --force alone no longer writes through a link; --no-prune --write-through-links keeps an edited stack file
xrun "$TX/y" "$TX/y7.log" --force; rc=$?
[ "$rc" != 0 ] && grep -q 'rerun with --write-through-links' "$TX/y7.log" \
  && pass "a symlinked dir with --force alone still stops" || failed "symlinked dir with --force alone (rc=$rc)"
xrun "$TX/y" "$TX/y8.log" --write-through-links
mkdir -p "$TX/outS2"; cp -R "$TX/y/skills/." "$TX/outS2/" 2>/dev/null
rm -rf "$TX/y/skills"; ln -s "$TX/outS2" "$TX/y/skills"
printf '\n<!-- kept edit -->\n' >> "$TX/outS2/python-engineering/SKILL.md"
xrun "$TX/y" "$TX/y9.log" --no-prune --write-through-links; rc=$?
[ "$rc" = 0 ] && grep -q 'kept edit' "$TX/outS2/python-engineering/SKILL.md" && [ -f "$TX/outS2/python-engineering/SKILL.md.new" ] \
  && pass "--no-prune --write-through-links keeps the edited stack SKILL.md and drops a .new render next to it" \
  || failed "--no-prune --write-through-links (rc=$rc): $(tail -3 "$TX/y9.log")"
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
# L2: a saved symlink whose target leaves the config dir comes back only with --force
xrun "$TX/r" "$TX/r0.log"
printf 'ext\n' > "$TX/ext-target.md"; ln -s "$TX/ext-target.md" "$TX/r/agents/ext.md"
xrun "$TX/r" "$TX/r1.log"; BR="$(latest_backup "$TX/r")"
xrun "$TX/r" "$TX/r2.log" --restore "$BR"; rc2=$?
skipped=0; [ ! -e "$TX/r/agents/ext.md" ] && [ ! -L "$TX/r/agents/ext.md" ] && grep -q 'skipped agents/ext.md: it was a link to' "$TX/r2.log" && skipped=1
xrun "$TX/r" "$TX/r3.log" --restore "$BR" --force; rc3=$?
[ "$rc2" = 0 ] && [ "$skipped" = 1 ] && [ "$rc3" = 0 ] && [ "$(readlink "$TX/r/agents/ext.md")" = "$TX/ext-target.md" ] \
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
for f in dot-claude/hooks/agent_guard.py dot-claude/agents/coder.md requirements/sci.in; do
  GIT_INDEX_FILE="$TX/idx" tgit -C "$HERE" update-index --cacheinfo "100755,$blob,$f"
done
old_commit="$(tgit -C "$HERE" commit-tree "$(GIT_INDEX_FILE="$TX/idx" tgit -C "$HERE" write-tree)" -p HEAD -m earlier </dev/null)"
set_commit "$old_commit"
xrun "$TX/r" "$TX/s1.log" --dry-run
set_commit "0123456789abcdef0123456789abcdef01234567"
xrun "$TX/r" "$TX/s2.log" --dry-run
grep -q "changes to the stack's shipped files and installer since the last install" "$TX/s1.log" \
  && grep -q 'dot-claude/hooks/agent_guard.py' "$TX/s1.log" && grep -q 'dot-claude/agents/coder.md' "$TX/s1.log" \
  && grep -q 'requirements/sci.in' "$TX/s1.log" && grep -q "which this repo doesn't have" "$TX/s2.log" \
  && pass "an install shows the diff of everything it ships since the recorded commit (and warns on an unknown one)" \
  || failed "supply-chain diff: $(grep -i 'since the last install\|repo doesn' "$TX/s1.log" "$TX/s2.log" | head -3)"
# on a terminal the run asks before applying those changes: "n" applies nothing, --yes doesn't ask
cat > "$TX/tty_run.py" <<'PY'
import os, select, subprocess, sys
answer, log, argv = sys.argv[1].encode(), sys.argv[2], sys.argv[3:]
m, s = os.openpty()
p = subprocess.Popen(argv, stdin=s, stdout=s, stderr=s, close_fds=True)
buf, answered = b"", False
while True:                  # the slave stays open here: no EIO while the child's output is read
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
set_commit "$old_commit"; nb=$(count_backups "$TX/r"); fp "$TX/r" > "$TX/fp.s0"
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/tty_run.py" n "$TX/s3.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile; rc3=$?
cmp -s "$TX/fp.s0" <(fp "$TX/r") && [ "$(count_backups "$TX/r")" = "$nb" ]; same3=$?
FAKE_CLAUDE_JSON="$TX/f.json" STACK_CLAUDE_JSON="$TX/f.json" CLAUDE_CONFIG_DIR="$TX/r" \
  python3 "$TX/tty_run.py" n "$TX/s4.log" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --yes; rc4=$?
[ "$rc3" != 0 ] && grep -q 'Apply the plan above' "$TX/s3.log" && grep -q 'not applied. Nothing in' "$TX/s3.log" \
  && [ "$same3" = 0 ] && [ "$rc4" = 0 ] && ! grep -q 'Apply the plan above' "$TX/s4.log" \
  && pass "on a terminal: changed stack files are confirmed before applying ('n' changes nothing; --yes skips the question)" \
  || failed "supply-chain confirmation (rc=$rc3/$rc4, unchanged after 'n': $same3): $(grep -ai 'apply the plan\|not applied' "$TX/s3.log" "$TX/s4.log" | head -3)"
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
CLAUDE_CONFIG_DIR="$TB/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$TB/new.log" 2>&1; rc=$?
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
if not any(not g.get("matcher") and any(x.get("command", "").endswith('agent_guard.py" session-env')
                                        for x in g["hooks"]) for g in s["hooks"]["SessionStart"]):
    bad.append("session-env hook")
if bad:
    print("   ", bad)
sys.exit(1 if bad else 0)
PY
out=$(CLAUDE_CONFIG_DIR="$TB/c" bash "$TB/c/bin/doctor.sh" 2>&1)
printf '%s\n' "$out" | grep -q "ok    sandboxed Bash env: session-env SessionStart hook wired" \
  && ! printf '%s\n' "$out" | grep -q "settings.json env sets\|sandbox-writable package cache" \
  && pass "doctor.sh: the session-env hook is wired, no cache env in settings" \
  || failed "doctor.sh session-env check: $(printf '%s\n' "$out" | grep -i 'session-env\|env sets' | head -3)"
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

echo
echo "== Summary: $PASS passed, $FAIL failed"
rm -rf "$T1" "$T2" "$T3"
drop_scratch "$SCRATCH_ROOT"
[ "$FAIL" -eq 0 ]
