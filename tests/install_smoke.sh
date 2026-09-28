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

REAL_CLAUDE_HASH_BEFORE="$(hash_tree "$HOME/.claude")"
REAL_CJ_HASH_BEFORE="$(hash_tree "$HOME/.claude.json")"
REAL_ZSHRC_HASH_BEFORE="$(hash_tree "$HOME/.zshrc")"

assert_unchanged_real_home() {
  [ "$(hash_tree "$HOME/.claude")" = "$REAL_CLAUDE_HASH_BEFORE" ] && pass "real \$HOME/.claude unchanged" \
    || failed "real \$HOME/.claude CHANGED"
  [ "$(hash_tree "$HOME/.claude.json")" = "$REAL_CJ_HASH_BEFORE" ] && pass "real ~/.claude.json unchanged" \
    || failed "real ~/.claude.json CHANGED"
  [ "$(hash_tree "$HOME/.zshrc")" = "$REAL_ZSHRC_HASH_BEFORE" ] && pass "real ~/.zshrc unchanged" \
    || failed "real ~/.zshrc CHANGED"
}

EXPECTED_AGENTS=$(ls "$HERE"/dot-claude/agents/*.md | wc -l | tr -d ' ')
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
import json, sys
s = json.load(open(sys.argv[1]))
h, allow, deny = s["hooks"], s["permissions"]["allow"], s["permissions"]["deny"]
checks = {
    "StopFailure hook": any("agent_guard.py" in json.dumps(g) for g in h.get("StopFailure", [])),
    "PostToolUse TaskStop": any("TaskStop" in (g.get("matcher") or "") for g in h["PostToolUse"]),
    "no blanket mcp__magg": "mcp__magg" not in allow,
    "magg catalog tools allowed": "mcp__magg__magg_enable_server" in allow and "mcp__magg__docling_*" in allow,
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
out=$(XDG_STATE_HOME="$T1/state" "$T1/bin/magg-private" /bin/echo --env-pass --config "$T1/magg/config.json" serve)
priv=$(printf '%s\n' "$out" | sed -n 's/^--env-pass --config \(.*\) serve$/\1/p')
[ -n "$priv" ] && [ "$priv" != "$T1/magg/config.json" ] && cmp -s "$priv" "$T1/magg/config.json" \
  && pass "magg-private runs magg on a private copy of the catalog" || failed "magg-private: [$out]"
python3 - "$T1/settings.json" <<'PY' && pass "settings: autocompact on at 800K, depth 4, default tool search, lazy MCP, blackcat, skill listing 2.5%" || failed "settings.json values (see above)"
import json, sys
s = json.load(open(sys.argv[1]))
env = s["env"]
checks = {
    "agent": s.get("agent") == "blackcat",
    "autoCompactEnabled": s.get("autoCompactEnabled") is True,
    "autoCompactWindow": s.get("autoCompactWindow") == 800000,
    "depth": env.get("CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH") == "4",
    "tool search left at its default": "ENABLE_TOOL_SEARCH" not in env,
    ".env.example writable": "Read(**/.env.*)" not in s["permissions"]["deny"] and "Read(**/.env.local)" in s["permissions"]["deny"],
    "discovery cache": env.get("MCP_DISCOVERY_CACHE") == "1",
    "blackcat dispatch": env.get("BLACKCAT_MAX_DISPATCH") == "3",
    "skill listing budget": s.get("skillListingBudgetFraction") == 0.025,
    "no Haiku": env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "claude-sonnet-5",
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
assert_unchanged_real_home

if [ "$(uname)" != "Darwin" ]; then
  TG="$(mktemp -d)"
  out=$(env -u STACK_ALLOW_NON_MACOS CLAUDE_CONFIG_DIR="$TG/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile 2>&1); rc=$?
  { [ "$rc" = 1 ] && printf '%s\n' "$out" | grep -q "macOS only" && [ ! -e "$TG/c" ]; } \
    && pass "refuses to install on $(uname) (macOS only), touching nothing" || failed "non-macOS guard: rc=$rc: $out"
fi

echo "== 2. Second run: agents reported unchanged"
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
nb_before=$(ls -d "$T1"/backup-* | wc -l | tr -d ' ')
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install2b.log" 2>&1
nb_after=$(ls -d "$T1"/backup-* | wc -l | tr -d ' ')
[ "$nb_before" = "$nb_after" ] && grep -q "no duplicate kept" "$T1/.install2b.log" \
  && pass "a run that changes nothing keeps no duplicate backup" || failed "backup folders grew on a no-op run ($nb_before -> $nb_after)"
assert_unchanged_real_home

echo "== 3. Manual edit is kept, with a .new copy, until --force"
printf '\n<!-- local edit -->\n' >> "$T1/agents/coder.md"
edited_before="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T1/.install3.log" 2>&1
edited_after="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
[ "$edited_before" = "$edited_after" ] && pass "edited coder.md kept as-is" || failed "edited coder.md was overwritten without --force"
[ -f "$T1/agents/coder.md.new" ] && pass ".new copy of the rendered coder.md was written" || failed "no .new copy found for the modified coder.md"
grep -qF "$T1/agents/coder.md.new" "$T1/.install3.log" && pass "the final summary lists the pending coder.md.new" || failed "pending .new not listed at the end"
CLAUDE_CONFIG_DIR="$T1" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile --force >"$T1/.install4.log" 2>&1
edited_forced="$(sha "$T1/agents/coder.md" | awk '{print $1}')"
if [ "$edited_forced" != "$edited_before" ] && ! grep -q '<!-- local edit -->' "$T1/agents/coder.md"; then
  pass "--force overwrote the modified coder.md"
else
  failed "--force did not overwrite the modified coder.md"
fi
[ ! -f "$T1/agents/coder.md.new" ] && pass "stale coder.md.new removed once the file is back in sync" || failed "stale coder.md.new left behind"
assert_unchanged_real_home

echo "== 4. Settings merge: pins, concurrency, compaction overrides; magg catalog merge"
T2="$(cd "$(mktemp -d)" && pwd -P)"
export FAKE_CLAUDE_JSON="$T2/fake-claude.json" STACK_CLAUDE_JSON="$T2/fake-claude.json"
mkdir -p "$T2/magg"
# docling edited by the user (kept), a server of their own (kept), and two entries exactly as an
# earlier stack version shipped them (mlflow disabled, playwright left enabled by magg): updated.
cat > "$T2/magg/config.json" <<'JSON'
{"servers": {"docling": {"source": "x", "command": "my-docling", "enabled": true},
             "mine": {"source": "y", "command": "my-server", "enabled": true},
             "mlflow": {"source": "https://mlflow.org/docs/latest/genai/mcp/", "prefix": "mlflow", "command": "uv", "args": ["run", "--with", "mlflow[mcp]>=3.5.1", "mlflow", "mcp", "run"], "notes": "MLflow trace search and management for LLM/agent evaluation. Needs MLFLOW_TRACKING_URI in stack.env (e.g. http://127.0.0.1:5000 or a file:// store).", "enabled": false},
             "playwright": {"source": "https://github.com/microsoft/playwright-mcp", "prefix": "pw", "command": "npx", "args": ["-y", "@playwright/mcp@latest"], "notes": "Scripted browser automation (forms, logins, JS-heavy pages) when WebFetch/Jina/Spider are not enough."}}}
JSON
CLAUDE_CONFIG_DIR="$T2" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T2/.install.log" 2>&1
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
s["autoCompactWindow"] = 300000
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
check(env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL") == "claude-sonnet-5", "a Haiku pin is replaced by Sonnet 5 (the stack runs no Haiku)",
      "ANTHROPIC_DEFAULT_HAIKU_MODEL=%r" % env.get("ANTHROPIC_DEFAULT_HAIKU_MODEL"))
check("ANTHROPIC_DEFAULT_OPUS_MODEL" not in env, "[1m]-suffixed pin removed", "[1m] pin kept")
check("CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION" not in env, "no-op CLAUDE_CODE_MAX_SUBAGENTS_PER_SESSION dropped", "no-op var kept")
check(env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS") == shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS reset to shipped %s" % shipped["CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"],
      "concurrency not reset (%r)" % env.get("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"))
check("DISABLE_AUTO_COMPACT" not in env and "CLAUDE_CODE_AUTO_COMPACT_WINDOW" not in env,
      "auto-compaction overrides removed", "auto-compaction overrides kept")
check(s.get("autoCompactWindow") == 800000 and s.get("autoCompactEnabled") is True,
      "autoCompactWindow back to 800000", "autoCompactWindow=%r" % s.get("autoCompactWindow"))
check("Bash(ls *)" in s["permissions"]["allow"], "user's own allow rule kept", "user's allow rule lost")
m = json.load(open(magg))["servers"]
check(m["docling"]["command"] == "my-docling" and m["docling"]["enabled"] is True and "mine" in m,
      "magg: user's catalog entries untouched", "magg: user entries modified")
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
[ "$(printf '%s\n' "$out" | grep -cE 'ok    settings.json PreToolUse\((Bash|Monitor)\) no[- ](push|forge)|ok    no-push hook sees every')" = 4 ] \
  && pass "doctor.sh: no-push probes (plain, bash -c, Monitor forge write, no if filter)" \
  || failed "doctor.sh: no-push probe lines: $(printf '%s\n' "$out" | grep -i 'no-push\|forge')"
nsk=$(ls -d "$HERE"/dot-claude/skills/*/ | wc -l | tr -d ' ')
printf '%s\n' "$out" | grep -qE "ok    skill listing: $((nsk - 1)) skills, ~[0-9]+ of 75000 characters" \
  && pass "doctor.sh: skill listing within its budget" || failed "doctor.sh: skill listing line: $(printf '%s\n' "$out" | grep 'skill listing')"
printf '%s\n' "$out" | grep -q "exa-from-stack-env" && failed "doctor.sh printed a key value" || pass "doctor.sh never prints key values"
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
ls "$T4"/.claude/backup-*/rc/.zshrc >/dev/null 2>&1 && pass "rc file backed up before editing" || failed "no rc backup"
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
# user edits settings: own hook inside the stack's Agent group, tuned knob, old BLACKCAT_MAX_DISPATCH default; symlinked file
mkdir -p "$T4/dotfiles"
python3 - "$T4/.claude/settings.json" <<'PY'
import json, sys
p = sys.argv[1]; s = json.load(open(p))
for g in s["hooks"]["PreToolUse"]:
    if g.get("matcher") == "Agent":
        g["hooks"].append({"type": "command", "command": "my-audit.sh"})
s["env"]["BLACKCAT_MAX_STEPS"] = "20"
s["env"]["BLACKCAT_MAX_DISPATCH"] = "3"
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
ok = ("my-audit.sh" in cmds and sum("agent_guard.py" in (c or "") for c in cmds) == shipped and s["env"]["BLACKCAT_MAX_STEPS"] == "20"
      and s["env"].get("ENABLE_TOOL_SEARCH") == "auto:5" and s.get("agent") == "claude"
      and s.get("skillListingBudgetFraction") == 0.05)
sys.exit(0 if ok else 1)
PY
grep -q "Olá" "$T4/dotfiles/settings.json" && pass "non-ASCII kept as-is" || failed "non-ASCII re-escaped"
HOME="$T4" CLAUDE_CONFIG_DIR="$T4/.claude" "$INSTALL" --no-mcp --no-plugins --no-deps >/dev/null 2>&1
[ "$(grep -c '# claude-agent-stack$' "$T4/.zshrc")" = 1 ] && pass "third run: still one rc line" || failed "rc line duplicated"
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
if [ ! -e "$T5/c/mcp/opper_image_mcp.py" ] && [ ! -e "$T5/c/mcp/openrouter_image_mcp.py" ] \
   && ls "$T5/c"/backup-*/retired/mcp/opper_image_mcp.py "$T5/c"/backup-*/retired/mcp/openrouter_image_mcp.py >/dev/null 2>&1 \
   && grep -q 'retired mcp/opper_image_mcp.py' "$T5/.log2" && grep -q 'retired mcp/openrouter_image_mcp.py' "$T5/.log2"; then
  pass "the retired Opper and OpenRouter image servers move into the backup"
else
  failed "an old image server was not retired"; grep -i -E 'retired|kept' "$T5/.log2" | sed 's/^/    /'
fi
printf '# an old install\n' > "$T5/c/mcp/openrouter_image_mcp.py"
printf '\n# my edit: args ["run", "--script", "%s/mcp/openrouter_image_mcp.py"]\n' "$T5/c" >> "$T5/c/agents/image-director.md"
FAKE_CLAUDE_JSON="$T5/f.json" STACK_CLAUDE_JSON="$T5/f.json" CLAUDE_CONFIG_DIR="$T5/c" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T5/.log3" 2>&1
if [ -f "$T5/c/mcp/openrouter_image_mcp.py" ] && grep -q 'kept mcp/openrouter_image_mcp.py: image-director.md' "$T5/.log3"; then
  pass "an edited agent that still starts the older image server keeps it"
else
  failed "older image server retired under an agent that still uses it"; grep -i -E 'openrouter|kept' "$T5/.log3" | sed 's/^/    /'
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
mode(){ python3 -c 'import os, sys; print(oct(os.stat(sys.argv[1]).st_mode & 0o777))' "$1"; }
if grep -q '^OPPER_API_KEY=op-mine-123$' "$E" && grep -q '^EXA_API_KEY=exa-mine$' "$E" && grep -q '^# my own header line$' "$E" \
   && ! grep -qiE 'lumenfall|seedream|OPPER_IMAGE_|only image model|Opper gateway|SVGs go' "$E" \
   && grep -q '^# Opper — generate_image: photographs and other raster images. https://platform.opper.ai$' "$E" \
   && grep -q '^# OpenRouter — generate_svg (vector art) and edit_image (edits, retouching, composites).$' "$E" \
   && [ "$(grep -c '^IMAGE_STUDIO_SVG_MODEL=recraft/recraft-v4.1-pro-vector$' "$E")" = 1 ] \
   && [ "$(grep -c '^IMAGE_STUDIO_IMAGE_MODEL=openai/gpt-image-2.5-sunburst$' "$E")" = 1 ] \
   && [ "$(grep -c '^IMAGE_STUDIO_EDIT_MODEL=sourceful/riverflow-v2.5-pro$' "$E")" = 1 ] \
   && grep -q '^#OPENROUTER_API_KEY=$' "$E" && grep -q '^#IMAGE_STUDIO_OUT_DIR=' "$E" && grep -q '^#JINA_API_KEY=$' "$E" \
   && cmp -s "$T5B/before.env" "$T5B"/c/backup-*/stack.env && [ "$(mode "$E")" = 0o600 ] \
   && [ "$(mode "$(ls "$T5B"/c/backup-*/stack.env)")" = 0o600 ] \
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
# first install over the user's own CLAUDE.md and a same-named skill of their own: both kept
T6="$(cd "$(mktemp -d)" && pwd -P)"; printf '# my rules\n- my NAS is 192.168.1.20\n' > "$T6/CLAUDE.md"
mkdir -p "$T6/skills/data-analysis"
printf -- '---\nname: data-analysis\ndescription: my own steps\n---\nMy own analysis steps.\n' > "$T6/skills/data-analysis/SKILL.md"
CLAUDE_CONFIG_DIR="$T6" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T6/.log" 2>&1
grep -q 192.168.1.20 "$T6/CLAUDE.md" && [ ! -e "$T6/CLAUDE.md.new" ] && [ -f "$T6/rules/claude-agent-stack.md" ] \
  && pass "user's own CLAUDE.md untouched; the stack's rules load from rules/claude-agent-stack.md" || failed "user's own CLAUDE.md changed, or rules missing"
grep -q 'My own analysis steps' "$T6/skills/data-analysis/SKILL.md" && [ -f "$T6/skills/data-analysis/SKILL.md.new" ] \
  && grep -qF "$T6/skills/data-analysis/SKILL.md.new" "$T6/.log" \
  && pass "same-named personal skill kept; the stack's version waits in SKILL.md.new (listed at the end)" || failed "personal skill overwritten or not reported"
# the stack's own (unedited) CLAUDE.md from an earlier version is retired into the backup
T7="$(cd "$(mktemp -d)" && pwd -P)"
sed "s#__CLAUDE_DIR__#$T7#g; s#__HOME__#$HOME#g" "$HERE/legacy/be5b940/CLAUDE.md" > "$T7/CLAUDE.md"
cp "$T7/CLAUDE.md" "$T7/CLAUDE.md.new"
CLAUDE_CONFIG_DIR="$T7" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T7/.log" 2>&1
[ ! -e "$T7/CLAUDE.md" ] && [ ! -e "$T7/CLAUDE.md.new" ] && ls "$T7"/backup-*/retired/CLAUDE.md >/dev/null 2>&1 \
  && [ -f "$T7/rules/claude-agent-stack.md" ] && ! grep -q 'Merge each' "$T7/.log" \
  && pass "the stack's old CLAUDE.md (and its leftover .new) retired into the backup, rules installed" || failed "legacy stack CLAUDE.md not retired"
T9="$(cd "$(mktemp -d)" && pwd -P)"
{ sed "s#__CLAUDE_DIR__#$T9#g" "$HERE/legacy/be5b940/CLAUDE.md"; printf '\n## Mine\n- my NAS is 192.168.1.20\n'; } > "$T9/CLAUDE.md"
CLAUDE_CONFIG_DIR="$T9" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T9/.log" 2>&1
grep -q 192.168.1.20 "$T9/CLAUDE.md" && grep -q 'CLAUDE.md .*kept (it has lines of your own)' "$T9/.log" \
  && pass "an untracked CLAUDE.md with lines of your own is kept (with advice)" || failed "CLAUDE.md with the user's own lines was retired"
cp "$(ls "$T7"/backup-*/retired/CLAUDE.md | head -n 1)" "$T7/CLAUDE.md"     # the user deliberately restores it
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
# senior-coder became main-coder: the old unedited file is retired (tracked by hash, or untracked
# and identical to the version the Mac's installer rendered); an edited tracked one is kept.
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
[ ! -e "$T13/agents/senior-coder.md" ] && ls "$T13"/backup-*/retired/agents/senior-coder.md >/dev/null 2>&1 \
  && pass "an untracked old senior-coder.md rendered with other paths is recognised and retired" \
  || failed "old senior-coder.md with other rendered paths not retired: $(grep senior "$T13/.log")"
CLAUDE_CONFIG_DIR="$T11" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T11/.log" 2>&1
[ ! -e "$T11/agents/senior-coder.md" ] && [ ! -e "$T11/agents/senior-coder.md.new" ] \
  && ls "$T11"/backup-*/retired/agents/senior-coder.md >/dev/null 2>&1 && grep -q 'senior-coder.md *retired — it is now agents/main-coder.md' "$T11/.log" \
  && pass "untracked old senior-coder.md (and its .new) retired: it is now main-coder" || failed "old senior-coder.md not retired"
printf -- '---\nname: senior-coder\ndescription: "x"\nmodel: claude-opus-5-5\n---\nmine\n' > "$T12/agents/senior-coder.md"
python3 - "$T12" <<'PY'
import json, os, sys
t = sys.argv[1]
json.dump({"files": {"agents/senior-coder.md": "0" * 64}}, open(os.path.join(t, ".stack-manifest.json"), "w"))
PY
CLAUDE_CONFIG_DIR="$T12" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T12/.log" 2>&1
[ -f "$T12/agents/senior-coder.md" ] && grep -q "senior-coder.md *kept (it differs from the stack's version)" "$T12/.log" \
  && ! grep -q 'senior-coder' "$T12/.stack-manifest.json" \
  && pass "an edited senior-coder.md is kept with a note and dropped from the manifest" || failed "edited senior-coder.md handling"
"$T12/bin/doctor.sh" >"$T12/.doctor" 2>&1
grep -q "senior-coder.md is the stack's old name for main-coder" "$T12/.doctor" \
  && pass "doctor flags the kept senior-coder.md" || failed "doctor does not flag senior-coder.md"
# the main-thread router became blackcat: an unedited tracked router.md is retired, and the settings
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
s["permissions"]["deny"] = deny(s["permissions"]["deny"])
json.dump(s, open(sp, "w"), indent=2)
PY
CLAUDE_CONFIG_DIR="$T14" "$INSTALL" --no-mcp --no-plugins --no-deps --no-profile >"$T14/.log" 2>&1
[ ! -e "$T14/agents/router.md" ] && ls "$T14"/backup-*/retired/agents/router.md >/dev/null 2>&1 \
  && grep -q 'router.md *retired — it is now agents/blackcat.md' "$T14/.log" \
  && pass "an unedited router.md is retired: it is now blackcat" || failed "old router.md not retired"
python3 - "$T14/settings.json" <<'PY' && pass "settings follow router -> blackcat: agent, tuned knob moved, defaults and deny rule" || failed "router settings not migrated"
import json, sys
s = json.load(open(sys.argv[1])); e = s["env"]; deny = s["permissions"]["deny"]
ok = (s.get("agent") == "blackcat" and e.get("BLACKCAT_MAX_STEPS") == "20" and e.get("BLACKCAT_MAX_DISPATCH") == "3"
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
   && grep -qx '{}' "$TL"/c/backup-*/stack-plugins/plugins/lean-lsp/.claude-plugin/plugin.json 2>/dev/null; then
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

echo "== 12. Plugin copies of claude.ai-synced skills: disabled only with --dedupe-plugins (fake claude)"
TD="$(scratch_dir)" || exit 1
mkdir -p "$TD/c/skills/synced/0000-sync/docx" "$TD/c/skills/synced/0000-sync/skill-creator"
printf -- '---\nname: docx\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/docx/SKILL.md"
printf -- '---\nname: skill-creator\ndescription: x\n---\n' > "$TD/c/skills/synced/0000-sync/skill-creator/SKILL.md"
printf '{"enabledPlugins": {"document-skills@anthropic-agent-skills": true, "skill-creator@claude-plugins-official": true}}\n' > "$TD/c/settings.json"
FAKE_CLAUDE_LOG="$TD/calls0.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile >"$TD/i0.log" 2>&1
if ! grep -qF '"disable"' "$TD/calls0.log" && ! grep -qF '"install", "document-skills@' "$TD/calls0.log" \
   && grep -qF 'install.sh --dedupe-plugins disables it' "$TD/i0.log"; then
  pass "without --dedupe-plugins: duplicate plugins stay enabled and the flag is suggested"
else
  failed "duplicate plugins touched without --dedupe-plugins"; grep -i plugin "$TD/i0.log" | sed 's/^/    /'
fi
FAKE_CLAUDE_LOG="$TD/calls.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile --with-extra-plugins --dedupe-plugins >"$TD/i.log" 2>&1
deduped_is(){ python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("plugins_deduped") == sys.argv[2:] else 1)' "$TD/c/.stack-manifest.json" "$@"; }
if grep -qF '["plugin", "disable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls.log" \
   && grep -qF '["plugin", "disable", "skill-creator@claude-plugins-official", "--scope", "user"]' "$TD/calls.log" \
   && ! grep -qF '"install", "document-skills@' "$TD/calls.log" && ! grep -qF '"install", "skill-creator@' "$TD/calls.log" \
   && grep -qF 'To undo: claude plugin enable document-skills@anthropic-agent-skills --scope user' "$TD/i.log" \
   && grep -qF 'To undo: claude plugin enable skill-creator@claude-plugins-official --scope user' "$TD/i.log" \
   && deduped_is document-skills@anthropic-agent-skills skill-creator@claude-plugins-official; then
  pass "--dedupe-plugins: both disabled (not installed), re-enable commands printed, recorded in the manifest"
else
  failed "--dedupe-plugins handling"; tail -n 12 "$TD/i.log" | sed 's/^/    /'
fi
rm -rf "$TD/c/skills/synced/0000-sync/docx"
FAKE_CLAUDE_LOG="$TD/calls2.log" CLAUDE_CONFIG_DIR="$TD/c" "$INSTALL" --no-mcp --no-deps --no-profile >"$TD/i2.log" 2>&1
if grep -qF '["plugin", "enable", "document-skills@anthropic-agent-skills", "--scope", "user"]' "$TD/calls2.log" \
   && ! grep -qF '"enable", "skill-creator@' "$TD/calls2.log" && deduped_is skill-creator@claude-plugins-official; then
  pass "a deduped plugin is re-enabled once its synced skill is gone; the other stays disabled"
else
  failed "re-enable after the synced skill went away"; grep -i plugin "$TD/i2.log" | sed 's/^/    /'
fi
assert_unchanged_real_home
drop_scratch "$TD"

echo
echo "== Summary: $PASS passed, $FAIL failed"
rm -rf "$T1" "$T2" "$T3"
drop_scratch "$SCRATCH_ROOT"
[ "$FAIL" -eq 0 ]
