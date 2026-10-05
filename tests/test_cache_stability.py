"""Prompt-cache stability (Stage 4 L1): the static prompt files carry no volatile text
(tests/cache_stability_lint.py) and the hooks that inject text at the start of a context
(SessionStart, SubagentStart) inject the same bytes on every run, but for the declared slots."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def _load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


lint = _load("cache_stability_lint")
guard_harness = _load("guard_harness")

ROOT = HERE.parent
SETTINGS = ROOT / "dot-claude" / "settings.json"
HOOKS = ROOT / "dot-claude" / "hooks"


# ---------------------------------------------------------------------------- static files
MODEL_VEC = "runs claude-opus-5-5 now"          # lint_agents.MODEL_ID_LINES allows this line


def test_shipped_prompt_files_are_clean():
    r = subprocess.run([sys.executable, str(HERE / "cache_stability_lint.py")], capture_output=True,
                       text=True, cwd=ROOT, check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert r.stdout.startswith("cache_stability_lint: ok (")


@pytest.mark.parametrize("text,kind", [
    ("as of 2026-10-05 the cap is", "date"),
    ("checked on Oct 5, 2026", "date"),
    ("checked 5 October 2026", "date"),
    ("as of Oct 2026 the cap is", "date"),
    ("as of October 2026 the cap is", "date"),
    ("as of Sept. 2026 the cap is", "date"),
    ("as of 2026-10 the cap is", "date"),
    ("released 2026-10, see notes", "date"),
    ("at 2026-10-05T09:42Z", "iso-datetime"),
    ("ran at 09:42:17 local", "clock-time"),
    ("ts 1790000000 written", "epoch"),
    ("session 4e2da3ce-e2f4-4971-aac5-a67f2dcf252e", "uuid"),
    ("see agent-a4f03c8319b534bde", "agent-id"),
    ("tool toolu_01AbCdEfGhIjKlMnOpQr", "api-id"),
    ("fixed in commit 7d12c58", "commit"),
    ("tree 7d12c589e41197f788249babb5fe2cf7d485ba23", "commit"),
    (MODEL_VEC, "model-id"),
    ("Claude Code 2.1.287 added", "version"),
    ("needs v1.2.3-rc1", "version"),
    ("now: !`date` here", "shell-injection"),
    ("id ${CLAUDE_SESSION_ID}", "session-var"),
])
def test_volatile_patterns_hit(text, kind):
    assert kind in [k for k, _ in lint.scan_line(text)], lint.scan_line(text)


@pytest.mark.parametrize("text", [
    "ratio 3:1 and C++17, Python 3.13, TS 7 vs 6",
    "an HH:MM time and YYYY-MM-DD dates",
    "the `!` operator, `println!` and `vec!`",
    "colour #deadbe, hash abcdefab, 1234567890ab",
    "opus and sonnet families, no haiku",
    "`date '+%F %R'` at the end",
    "paths like a/1.2.3/b and lib.so.1",
    "budget 5,200 chars; 26/31 misses; 12.6%",
    "the 2026-27 season, C++20, 2026-13 is no month, port 2020-8080",
    "you may 2026 nothing, Octal 2026, Mayday 2026, March 26",
])
def test_ordinary_text_passes(text):
    assert lint.scan_line(text) == []


def _tree(tmp_path, files):
    for rel, text in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return lint.lint(tmp_path)


AGENT = ('---\nname: x\ndescription: "Does x."\nmodel: sonnet\nmcpServers:\n  - pw:\n'
         '      args: ["@playwright/mcp@0.0.82"]\n---\n\nBody line.\n')
SKILL = '---\nname: s\ndescription: Use for s.\n---\n\nAs of 2026-10-05 the tool is 1.2.3.\n'


def test_clean_seed_tree_passes(tmp_path):
    found, n = _tree(tmp_path, {"dot-claude/agents/x.md": AGENT, "dot-claude/skills/s/SKILL.md": SKILL,
                                "dot-claude/rules/r.md": "# rules\nNo dates.\n"})
    assert (found, n) == ([], 3)


@pytest.mark.parametrize("rel,text,line,kind", [
    ("dot-claude/agents/x.md", AGENT + "Today is 2026-10-05.\n", 11, "date"),
    ("dot-claude/agents/x.md", AGENT.replace("Does x.", "Does x (v2.3.4)."), 3, "version"),
    ("dot-claude/skills/s/SKILL.md", SKILL.replace("Use for s.", "Use for s, as of 2026-10-05."), 3, "date"),
    ("dot-claude/skills/s/SKILL.md", SKILL.replace("Use for s.", ">-\n  Use for s\n  at 12:00:01."), 5,
     "clock-time"),
    ("dot-claude/rules/r.md", "# rules\nsession 4e2da3ce-e2f4-4971-aac5-a67f2dcf252e\n", 2, "uuid"),
    ("dot-claude/rules/r.md", "# rules\nPrices as of Oct 2026.\n", 2, "date"),
    ("dot-claude/CLAUDE.managed.md", "keep\n" + MODEL_VEC + "\n", 2, "model-id"),
])
def test_seeded_volatile_text_is_reported_with_its_line(tmp_path, rel, text, line, kind):
    base = {"dot-claude/agents/x.md": AGENT, "dot-claude/skills/s/SKILL.md": SKILL}
    found, _ = _tree(tmp_path, dict(base, **{rel: text}))
    assert [(f["path"], f["line"], f["kind"]) for f in found] == [(rel, line, kind)]


def test_cli_lists_path_line_and_fails(tmp_path):
    _tree(tmp_path, {"dot-claude/rules/r.md": "a\nrun !`git log -1`\n"})
    r = subprocess.run([sys.executable, str(HERE / "cache_stability_lint.py"), "--root", str(tmp_path)],
                       capture_output=True, text=True, check=False)
    assert r.returncode == 1 and r.stdout == "dot-claude/rules/r.md:2: shell-injection: !`git log -1`\n"


def test_allowlist_needs_path_kind_and_text(tmp_path, monkeypatch):
    files = {"dot-claude/rules/r.md": "pinned 1.2.3\nother 4.5.6\n"}
    monkeypatch.setitem(lint.ALLOW, ("dot-claude/rules/r.md", "version", "1.2.3"), "test")
    found, _ = _tree(tmp_path, files)
    assert [f["match"] for f in found] == ["4.5.6"]


# ---------------------------------------------------------------------------- early hooks
# Events whose hook text lands at the start of a context, before any tool result (hooks.md).
EARLY_EVENTS = ("SessionStart", "SubagentStart", "Setup", "InstructionsLoaded")
# The only volatile text an early hook may inject, with why it is harmless: the SubagentStart
# `Started <local time>` line is fixed for the run and sits in the first user message after the
# spawn's brief, which differs per spawn anyway, so no cached prefix depends on it (Stage 4 L1
# audit: no miss attributable to it, within a run or across spawns).
SLOTS = {"SubagentStart": re.compile(r"^Started \d{4}-\d\d-\d\d \d\d:\d\d \(local\)\.$", re.MULTILINE)}
VARIANTS = ({}, {"STACK_REPORT_FORMAT": "json"}, {"STACK_AGENT_STARTED": "0"})
CLOCKS = ("UTC", "Asia/Kathmandu")       # 5 h 45 min apart: the local time always differs


def early_hooks():
    """{(event, command after the stack-hook launcher)} of the shipped settings."""
    s = json.loads(SETTINGS.read_text(encoding="utf-8"))
    out = set()
    for ev in EARLY_EVENTS:
        for group in s.get("hooks", {}).get(ev, []):
            for h in group.get("hooks", []):
                cmd = h.get("command", "")
                tail = cmd.split('bin/stack-hook"', 1)[1] if 'bin/stack-hook"' in cmd else cmd
                out.add((ev, " ".join(x for x in tail.split() if x != "--fail-closed")))
    return out


def context(stdout):
    if not stdout.strip():
        return None
    return json.loads(stdout).get("hookSpecificOutput", {}).get("additionalContext")


def unstable(event, a, b):
    """Problems between two runs' additionalContext of one early hook (None = no context)."""
    if a is None and b is None:
        return []
    if (a is None) != (b is None):
        return ["context on one run only"]
    rx = SLOTS.get(event)
    ma, mb = (rx.sub("<slot>", a), rx.sub("<slot>", b)) if rx else (a, b)
    probs = [] if ma == mb else [f"differs between runs: {ma[:120]!r} vs {mb[:120]!r}"]
    probs += [f"{k}: {m}" for line in ma.splitlines() for k, m in lint.scan_line(line)]
    return probs


def test_unstable_flags_dynamic_hook_text():
    assert unstable("SessionStart", "Session s-1 at 09:42:17", "Session s-2 at 10:01:55") != []
    assert unstable("SessionStart", "x", None) == ["context on one run only"]
    assert unstable("SessionStart", "Static.", "Static.") == []
    assert unstable("SessionStart", "Started 2026-10-05 09:42 (local).", "Started 2026-10-05 09:43 (local).")
    assert unstable("SubagentStart", "Started 2026-10-05 09:42 (local).\nR",
                    "Started 2026-10-05 15:27 (local).\nR") == []
    assert unstable("SubagentStart", "Started 2026-10-05 09:42 (local). id 7",
                    "Started 2026-10-05 09:42 (local). id 8") != []


def _guard(event, extra, clock, **kw):
    e = guard_harness.Env()
    ev = e.start(kw["aid"], kw["atype"]) if event == "SubagentStart" else e.base(event, source=kw["source"])
    r = e.run(ev, extra=dict(extra, TZ=clock))
    assert r.rc == 0, r.stderr
    return r.stdout


def probe_guard_session_start():
    for src in ("startup", "resume", "clear", "fork"):    # compact: a new context, digest by design
        for v in VARIANTS:
            yield "SessionStart", *(context(_guard("SessionStart", v, c, source=src)) for c in CLOCKS)


def probe_guard_subagent_start():
    for atype in ("coder", "orchestrator"):
        for v in VARIANTS:
            a, b = (context(_guard("SubagentStart", v, c, aid=f"a{i:07d}", atype=atype))
                    for i, c in enumerate(CLOCKS))
            if v.get("STACK_AGENT_STARTED") != "0":
                assert a != b, "the probe must move the clock"   # else it could not see a time
            yield "SubagentStart", a, b


def _silent(argv, extra, event):
    def run(tmp):
        env = dict(os.environ, HOME=tmp, XDG_STATE_HOME=os.path.join(tmp, "state"),
                   CLAUDE_ENV_FILE=os.path.join(tmp, "env.sh"), **extra)
        ev = {"session_id": "s-" + os.path.basename(tmp), "hook_event_name": event,
              "agent_id": "a1", "agent_type": "coder"}
        if event == "SessionStart":
            ev["source"] = "startup"
        p = subprocess.run([sys.executable, *argv], input=json.dumps(ev), capture_output=True,
                           text=True, env=env, timeout=60, check=False)
        return context(p.stdout)
    return run


def probe_guard_session_env(tmp_path):
    run = _silent([str(HOOKS / "agent_guard.py"), "session-env"], {}, "SessionStart")   # Bash env file only
    yield "SessionStart", run(str(tmp_path / "a")), run(str(tmp_path / "b"))


def probe_usage_start(tmp_path):
    # never prints (stack_usage.py main: "hooks: never fail, never print"); collection off so no
    # detached collector starts from a test
    run = _silent([str(HOOKS / "stack_usage.py"), "start"], {"STACK_USAGE_COLLECT": "0"}, "SubagentStart")
    yield "SubagentStart", run(str(tmp_path / "a")), run(str(tmp_path / "b"))


PROBES = {
    ("SessionStart", "agent_guard"): lambda tmp: probe_guard_session_start(),
    ("SessionStart", "agent_guard session-env"): probe_guard_session_env,
    ("SubagentStart", "agent_guard"): lambda tmp: probe_guard_subagent_start(),
    ("SubagentStart", "stack_usage start"): probe_usage_start,
}


def test_silent_probes_send_their_own_event(tmp_path, monkeypatch):
    """Each subprocess probe feeds its hook the event it is filed under (a SubagentStart hook
    gets hook_event_name SubagentStart)."""
    sent = []

    def fake_run(argv, input, **kw):
        sent.append(json.loads(input)["hook_event_name"])
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    for key in (("SessionStart", "agent_guard session-env"), ("SubagentStart", "stack_usage start")):
        sent.clear()
        assert [ev for ev, _, _ in PROBES[key](tmp_path)] == [key[0]]
        assert sent == [key[0]] * 2, key


def test_every_early_hook_has_a_probe():
    """A new SessionStart/SubagentStart hook fails here until it gets a probe below."""
    assert early_hooks() == set(PROBES)


@pytest.mark.parametrize("key", sorted(PROBES), ids=lambda k: f"{k[0]}:{k[1]}")
def test_early_hook_text_is_stable(key, tmp_path):
    for i, (event, a, b) in enumerate(PROBES[key](tmp_path)):
        assert unstable(event, a, b) == [], (key, i)
