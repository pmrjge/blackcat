"""The delegation ledger (agent_guard.py): spawns/<tool_use_id>.json + delegations.md, the hint
BlackCat gets after a dispatch, and `agent_guard.py delegations`.

Run: uv run --with pytest pytest -q tests/test_delegation_ledger.py
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
PREFIXES = ("STACK_", "BLACKCAT_", "GOD_", "SCREEN_", "STRIP_", "CLAUDE_CODE_MAX")


@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if not k.startswith(PREFIXES)}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    return e


def run(ev, env, args=()):
    p = subprocess.run([sys.executable, str(GUARD), *args],
                       input="" if ev is None else json.dumps(ev),
                       capture_output=True, text=True, env=env, timeout=60)
    return p


def hook(ev, env):
    p = run(ev, env)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout) if p.stdout.strip() else None


def ledger(env, sid):
    return (Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / sid / "delegations.md").read_text()


def call(sid, event, child, tid, task, by=None, by_type="blackcat", **extra):
    ev = {"session_id": sid, "hook_event_name": event, "tool_name": "Agent", "prompt_id": "p1",
          "tool_use_id": tid, "agent_type": by_type,
          "tool_input": {"subagent_type": child, "description": task, "prompt": "x"}}
    if by:
        ev["agent_id"] = by
    ev.update(extra)
    return ev


def post(sid, child, tid, task, child_id, status, **kw):
    return call(sid, "PostToolUse", child, tid, task,
                tool_response={"agentId": child_id, "status": status}, **kw)


def labelled(out, child, task):
    """An allowed call's only output: the silent label rewrite (STACK_AGENT_LABEL)."""
    hso = out["hookSpecificOutput"]
    return set(hso) == {"hookEventName", "updatedInput"} and \
        hso["updatedInput"]["description"] == "%s: %s" % (child, task)


def test_tree_states_and_hint(env):
    s = "s-" + uuid.uuid4().hex[:8]
    assert labelled(hook(call(s, "PreToolUse", "orchestrator", "t1", "Ship landing page"), env),
                    "orchestrator", "Ship landing page")
    out = hook(post(s, "orchestrator", "t1", "Ship landing page", "orc1", "async_launched"), env)
    ctx = out["hookSpecificOutput"]["additionalContext"]
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert ctx.split(" ")[4].endswith(os.path.join(s, "delegations.md"))
    sub = {"by": "orc1", "by_type": "orchestrator"}
    for tid, child, task in (("t2", "designer", "T1 hero visuals"),
                             ("t3", "frontend-engineer", "T2 build page"),
                             ("t4", "coder", "T3 copy edits")):
        assert labelled(hook(call(s, "PreToolUse", child, tid, task, **sub), env), child, task)
    # a subagent's PostToolUse gets no hint; a finished child, a failed call, one still launching
    assert hook(post(s, "designer", "t2", "T1 hero visuals", "des1", "completed", **sub),
                env) is None
    hook(call(s, "PostToolUseFailure", "frontend-engineer", "t3", "T2 build page", **sub), env)
    text = ledger(env, s)
    assert '- orchestrator · "Ship landing page" · running' in text
    assert '  - designer · "T1 hero visuals" · finished' in text
    assert '  - frontend-engineer · "T2 build page" · failed' in text
    assert '  - coder · "T3 copy edits" · launching' in text
    # the orchestrator stops: finished
    hook({"session_id": s, "hook_event_name": "SubagentStop", "agent_id": "orc1",
          "agent_type": "orchestrator"}, env)
    assert '- orchestrator · "Ship landing page" · finished' in ledger(env, s)


def test_no_hint_for_leaf_dispatch_or_other_main_threads(env):
    s = "s-" + uuid.uuid4().hex[:8]
    hook(call(s, "PreToolUse", "scout", "t1", "Latest Rust version"), env)
    assert hook(post(s, "scout", "t1", "Latest Rust version", "sc1", "async_launched"), env) is None
    assert '- scout · "Latest Rust version" · running' in ledger(env, s)
    # a main thread that is not BlackCat (claude-ninja, a plain session) gets no output
    hook(call(s, "PreToolUse", "orchestrator", "t2", "Plan it", by_type="ninja-coder"), env)
    assert hook(post(s, "orchestrator", "t2", "Plan it", "o2", "async_launched",
                     by_type="ninja-coder"), env) is None
    assert '- orchestrator · "Plan it" · running' in ledger(env, s)


def test_label_prefix_leaves_the_row_unchanged(env):
    """PreToolUse records the caller's description, PostToolUse sees the labelled one; a caller
    that labels its own call gets the same row."""
    s = "s-" + uuid.uuid4().hex[:8]
    hook(call(s, "PreToolUse", "scout", "t1", "Latest Rust version"), env)
    hook(post(s, "scout", "t1", "scout: Latest Rust version", "sc1", "async_launched"), env)
    assert hook(call(s, "PreToolUse", "coder", "t2", "coder: fix parser"), env) is None
    hook(post(s, "coder", "t2", "coder: fix parser", "c1", "async_launched"), env)
    text = ledger(env, s)
    assert '- scout · "Latest Rust version" · running' in text
    assert '- coder · "fix parser" · running' in text and "coder: fix" not in text


def test_denied_call_is_not_recorded(env):
    s = "s-" + uuid.uuid4().hex[:8]
    out = hook(call(s, "PreToolUse", "general-purpose", "t1", "anything", by="o1",
                    by_type="orchestrator"), env)
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert not (Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / s / "spawns").exists()


def test_foreground_child_linked_at_start(env, tmp_path):
    """A foreground child reports through PostToolUse only when done; SubagentStart links it to
    its call through meta.json's toolUseId, so its own delegations nest under it."""
    s = "s-" + uuid.uuid4().hex[:8]
    proj = tmp_path / "proj"
    (proj / s / "subagents").mkdir(parents=True)
    transcript = proj / (s + ".jsonl")
    transcript.write_text("{}\n")
    (proj / s / "subagents" / "agent-cod1.meta.json").write_text(
        json.dumps({"agentType": "main-coder", "spawnDepth": 2, "toolUseId": "t2",
                    "parentAgentId": "orc1"}))
    hook(call(s, "PreToolUse", "orchestrator", "t1", "Refactor parser"), env)
    hook(post(s, "orchestrator", "t1", "Refactor parser", "orc1", "async_launched"), env)
    hook(call(s, "PreToolUse", "main-coder", "t2", "T1 split module", by="orc1",
              by_type="orchestrator", run_in_background=False), env)
    hook({"session_id": s, "hook_event_name": "SubagentStart", "agent_id": "cod1",
          "agent_type": "main-coder", "transcript_path": str(transcript)}, env)
    hook(call(s, "PreToolUse", "explore", "t3", "Find call sites", by="cod1",
              by_type="main-coder"), env)
    text = ledger(env, s)
    assert '  - main-coder · "T1 split module" · running' in text and "id cod1" in text
    assert '    - explore · "Find call sites" · launching' in text


def test_cli(env):
    s = "s-" + uuid.uuid4().hex[:8]
    hook(call(s, "PreToolUse", "orchestrator", "t1", "Ship\nit `now`"), env)
    p = run(None, env, args=["delegations"])
    assert p.returncode == 0 and '- orchestrator · "Ship it now" · launching' in p.stdout
    rows = json.loads(run(None, env, args=["delegations", s, "--json"]).stdout)
    assert rows[0]["type"] == "orchestrator" and rows[0]["depth"] == 0
    assert rows[0]["by_type"] == "blackcat" and rows[0]["state"] == "launching"
    assert run(None, env, args=["delegations", "nosuch"]).returncode == 1


def test_self_test_covers_ledger(env):
    p = run(None, env, args=["--self-test"])
    assert p.returncode == 0 and "ok" in p.stdout, p.stdout + p.stderr
