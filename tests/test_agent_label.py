"""Subagent labels (agent_guard.py, STACK_AGENT_LABEL) and the start time a stack agent gets on
SubagentStart (STACK_AGENT_STARTED).

Run: uv run --python 3.12 --with pytest pytest -q tests/test_agent_label.py
"""
import json
import os
import re
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


def hook(ev, env, **knobs):
    p = subprocess.run([sys.executable, str(GUARD)], input=json.dumps(ev), capture_output=True,
                       text=True, env=dict(env, **knobs), timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)["hookSpecificOutput"] if p.stdout.strip() else None


def agent(sid, child, by_type="blackcat", by=None, tool="Agent", **ti):
    ev = {"session_id": sid, "hook_event_name": "PreToolUse", "tool_name": tool,
          "prompt_id": "p1", "tool_use_id": "tu-" + uuid.uuid4().hex[:8], "agent_type": by_type,
          "tool_input": dict({"subagent_type": child, "prompt": "do it"}, **ti)}
    if by:
        ev["agent_id"] = by
    return ev


def sid():
    return "s-" + uuid.uuid4().hex[:8]


def state(env, s):
    return Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / s


def test_unlabelled_call_is_labelled_silently_other_keys_kept(env):
    out = hook(agent(sid(), "scout", description="latest uv version", isolation="worktree",
                     name="uv-check"), env)
    assert set(out) == {"hookEventName", "updatedInput"}       # no decision, no reason
    assert out["updatedInput"] == {"subagent_type": "scout", "prompt": "do it",
                                   "description": "scout: latest uv version",
                                   "isolation": "worktree", "name": "uv-check"}


def test_label_uses_the_canonical_type_and_the_task_alias(env):
    out = hook(agent(sid(), "Code Reviewer", tool="Task", description="T3 review diff"), env)
    assert out["updatedInput"]["description"] == "code-reviewer: T3 review diff"
    assert out["updatedInput"]["subagent_type"] == "Code Reviewer"


@pytest.mark.parametrize("desc", ["coder: fix parser", "Coder : fix parser", "  coder:fix"])
def test_already_labelled_call_has_no_output(env, desc):
    assert hook(agent(sid(), "coder", description=desc), env) is None


def test_missing_and_long_descriptions(env):
    assert hook(agent(sid(), "coder"), env)["updatedInput"]["description"] == "coder"
    long = hook(agent(sid(), "coder", description="word " * 40), env)["updatedInput"]
    assert len(long["description"]) <= 72 and long["description"].startswith("coder: word")


def test_model_strip_and_label_in_one_updated_input(env):
    out = hook(agent(sid(), "coder", description="fix", model="opus", run_in_background=False),
               env)
    assert out["permissionDecision"] == "allow"
    assert "label" not in out["permissionDecisionReason"]
    ui = out["updatedInput"]
    assert ui["description"] == "coder: fix" and "model" not in ui and "run_in_background" not in ui


@pytest.mark.parametrize("mode", ["off", "OFF "])
def test_off(env, mode):
    assert hook(agent(sid(), "coder", description="fix"), env, STACK_AGENT_LABEL=mode) is None


def test_unknown_mode_falls_back_to_description(env):
    out = hook(agent(sid(), "coder", description="fix"), env, STACK_AGENT_LABEL="banner")
    assert out["updatedInput"]["description"] == "coder: fix"


def test_policy_off_still_labels(env):
    out = hook(agent(sid(), "coder", description="fix"), env, STACK_POLICY="off")
    assert out["updatedInput"]["description"] == "coder: fix"


def test_name_mode_numbers_per_type_and_keeps_a_callers_name(env):
    s = sid()
    k = {"STACK_AGENT_LABEL": "name"}
    first = hook(agent(s, "coder", description="a"), env, **k)
    assert set(first) == {"hookEventName", "updatedInput"}
    assert first["updatedInput"]["name"] == "coder-1"
    assert first["updatedInput"]["description"] == "a"           # description untouched
    assert hook(agent(s, "coder", description="b"), env, **k)["updatedInput"]["name"] == "coder-2"
    assert hook(agent(s, "scout", description="c"), env, **k)["updatedInput"]["name"] == "scout-1"
    assert hook(agent(s, "coder", description="d", name="parser"), env, **k) is None
    # the label is registered like a caller's name (SendMessage can address it)
    assert json.loads((state(env, s) / "names" / "coder-1.json").read_text())["type"] == "coder"
    # a name a caller took is skipped
    hook(agent(s, "coder", description="e", name="coder-3"), env, **k)
    assert hook(agent(s, "coder", description="f"), env, **k)["updatedInput"]["name"] == "coder-4"
    # another session starts again at 1
    assert hook(agent(sid(), "coder", description="g"), env, **k)["updatedInput"]["name"] \
        == "coder-1"


def test_name_mode_ledger_hides_the_auto_name(env):
    s = sid()
    k = {"STACK_AGENT_LABEL": "name"}
    pre = agent(s, "coder", description="fix parser")
    ui = hook(pre, env, **k)["updatedInput"]
    post = dict(pre, hook_event_name="PostToolUse", tool_input=ui,
                tool_response={"agentId": "c1", "status": "async_launched"})
    hook(post, env, **k)
    named = agent(s, "coder", description="tests", name="tester")
    hook(named, env, **k)
    text = (state(env, s) / "delegations.md").read_text()
    assert '- coder · "fix parser" · running' in text and "coder-1" not in text
    assert '- coder (name tester) · "tests"' in text


def test_denied_call_is_not_rewritten_and_spends_no_name(env):
    s = sid()
    out = hook(agent(s, "general-purpose", description="anything"), env,
               STACK_AGENT_LABEL="name")
    assert out["permissionDecision"] == "deny" and "updatedInput" not in out
    out = hook(agent(s, "coder", by="o1", by_type="scout", description="x"), env)
    assert out["permissionDecision"] == "deny" and "updatedInput" not in out
    assert not (state(env, s) / "labels").exists()
    assert hook(agent(s, "coder", description="x"), env,
                STACK_AGENT_LABEL="name")["updatedInput"]["name"] == "coder-1"


def test_prefixed_and_unprefixed_calls_give_the_same_ledger_row(env):
    rows = []
    for desc in ("ship it", "orchestrator: ship it"):
        s = sid()
        pre = agent(s, "orchestrator", description=desc)
        out = hook(pre, env)
        ui = out["updatedInput"] if out else pre["tool_input"]
        assert ui["description"] == "orchestrator: ship it"
        hook(dict(pre, hook_event_name="PostToolUse", tool_input=ui,
                  tool_response={"agentId": "o1", "status": "async_launched"}), env)
        text = (state(env, s) / "delegations.md").read_text()
        rows.append([ln for ln in text.splitlines() if ln.startswith("- ")])
    assert rows[0] == rows[1] and '"ship it"' in rows[0][0]


def start(s, aid, atype):
    return {"session_id": s, "hook_event_name": "SubagentStart", "agent_id": aid,
            "agent_type": atype}


def test_subagent_start_gets_its_start_time(env):
    out = hook(start(sid(), "a1", "coder"), env)
    assert out["hookEventName"] == "SubagentStart" and set(out) == {"hookEventName",
                                                                     "additionalContext"}
    assert re.fullmatch(r"Started \d{4}-\d{2}-\d{2} \d{2}:\d{2} \(local\)\.",
                        out["additionalContext"])
    assert hook(start(sid(), "a2", "researcher-copy"), env) is not None


def test_subagent_start_context_only_for_stack_agents_and_switchable(env):
    assert hook(start(sid(), "a1", "claude-test:runner"), env) is None
    assert hook(start(sid(), "a1", "coder"), env, STACK_AGENT_STARTED="0") is None


def test_subagent_start_bookkeeping_still_runs(env):
    s = sid()
    hook(start(s, "a1", "coder"), env)
    reg = json.loads((state(env, s) / "agents" / "a1.json").read_text())
    assert reg["type"] == "coder" and reg.get("started")
