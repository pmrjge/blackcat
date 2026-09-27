"""Subprocess-driven tests for dot-claude/hooks/agent_guard.py (stdlib hook).

Run: uv run --with pytest pytest -q tests/test_agent_guard.py
Every test uses a temporary XDG_STATE_HOME; nothing outside the tmp dir is touched.
"""
import json
import os
import re
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
REPEATS = 20
FANOUT = 20

KNOBS = ("STACK_POLICY", "ROUTER_MAX_DISPATCH", "ROUTER_MAX_STEPS", "GOD_PENDING_TTL_S",
         "GOD_IDLE_S", "GOD_LOCK_TTL_S", "SCREEN_LOCK_TTL_S", "STRIP_AGENT_MODEL",
         "STACK_MAX_DEPTH", "STACK_GUARD_LOG", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
         "ROUTER_DISPATCH_WINDOW_S", "STACK_MAX_FANOUT", "STACK_MAX_SELF_FANOUT",
         "STACK_FANOUT_IDLE_S", "STACK_FANOUT_PENDING_TTL_S")


# ---------------------------------------------------------------- harness
@pytest.fixture
def env(tmp_path):
    e = {k: v for k, v in os.environ.items() if k not in KNOBS}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    return e


def state(env, sid):
    return Path(env["XDG_STATE_HOME"]) / "claude-agent-stack" / sid


def sid():
    return "s-" + uuid.uuid4().hex[:12]


def run(ev, env, args=(), extra=None, cmd=None):
    e = dict(env, **(extra or {}))
    data = ev if isinstance(ev, str) else json.dumps(ev)
    argv = cmd or [sys.executable, str(GUARD), *args]
    return subprocess.run(argv, input=data, capture_output=True, text=True, env=e, timeout=60)


def decision(p):
    assert p.returncode == 0, p.stderr
    if not p.stdout.strip():
        return "allow"
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]


def reason(p):
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecisionReason"]


def run_many(evs, env, args=(), extra=None):
    """Start all processes, feed stdin to each, then collect: maximizes overlap."""
    e = dict(env, **(extra or {}))
    procs = [subprocess.Popen([sys.executable, str(GUARD), *args], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=e)
             for _ in evs]
    for p, ev in zip(procs, evs):
        p.stdin.write(json.dumps(ev))
        p.stdin.close()
    out = []
    for p in procs:
        stdout = p.stdout.read()
        stderr = p.stderr.read()
        p.wait(timeout=60)
        p.stdout.close()
        p.stderr.close()
        assert p.returncode == 0, stderr
        out.append("allow" if not stdout.strip() else
                   json.loads(stdout)["hookSpecificOutput"]["permissionDecision"])
    return out


def pre_agent(s, child, parent="", agent_id=None, prompt="p1", **ti_extra):
    ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": "Agent",
          "prompt_id": prompt, "tool_use_id": "tu-" + uuid.uuid4().hex[:8],
          "tool_input": dict({"subagent_type": child, "prompt": "x", "description": "x"},
                             **ti_extra)}
    if parent:
        ev["agent_type"] = parent
    if agent_id:
        ev["agent_id"] = agent_id
    return ev


def post_agent(s, child, child_id, agent_id=None, parent="", status="async_launched",
               name=None, as_string=False, tool_use_id=None):
    tr = {"agentId": child_id, "status": status}
    ev = {"session_id": s, "hook_event_name": "PostToolUse", "tool_name": "Agent",
          "tool_input": {"subagent_type": child, "prompt": "x"},
          "tool_response": json.dumps(tr) if as_string else tr}
    if tool_use_id:
        ev["tool_use_id"] = tool_use_id
    if name:
        ev["tool_input"]["name"] = name
    if agent_id:
        ev["agent_id"], ev["agent_type"] = agent_id, parent
    return ev


def lifecycle(s, event, agent_id, agent_type, **extra):
    return dict({"session_id": s, "hook_event_name": event, "agent_id": agent_id,
                 "agent_type": agent_type}, **extra)


def send(s, to, agent_id=None):
    ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": "SendMessage",
          "tool_input": {"to": to, "message": "more"}}
    if agent_id:
        ev["agent_id"] = agent_id
    return ev


def screen(s, agent_id=None, agent_type="designer"):
    ev = {"session_id": s, "hook_event_name": "PreToolUse",
          "tool_name": "mcp__computer-use__screenshot", "tool_input": {}}
    if agent_id:
        ev["agent_id"], ev["agent_type"] = agent_id, agent_type
    return ev


def god_lock(env, s):
    p = state(env, s) / "god-coder.lock"
    return json.loads(p.read_text()) if p.exists() else None


def age_lock(env, s, name, seconds):
    p = state(env, s) / name
    obj = json.loads(p.read_text())
    obj["ts"] = time.time() - seconds
    p.write_text(json.dumps(obj))


def policy(env):
    return json.loads(run("", env, args=["--print-policy"]).stdout)


# ---------------------------------------------------------------- CLI
def test_print_policy_format(env):
    p = run("", env, args=["--print-policy"])
    assert p.returncode == 0
    d = json.loads(p.stdout)
    assert list(d) == ["policy", "leaves", "agents", "builtins", "self_spawn", "router_tools"]
    assert len(d["agents"]) == 33 and len(set(d["agents"])) == 33
    assert d["builtins"] == ["explore"]
    assert set(d["policy"]) == set(d["agents"])
    assert sorted(d["leaves"]) == sorted(k for k, v in d["policy"].items() if not v)
    assert set(d["policy"]["router"]) == set(d["agents"]) - {"router"}
    assert set(d["policy"]["orchestrator"]) == set(d["policy"]["router"]) - {"orchestrator"} | {
        "explore"}
    assert d["policy"]["main-coder"][0] == "main-coder"
    assert {"ml-engineer", "dl-engineer", "llm-engineer", "ninja-coder", "god-coder"} <= set(
        d["policy"]["main-coder"])
    # escalation chain coder < main-coder < ninja-coder < god-coder
    assert "ninja-coder" not in d["policy"]["coder"] and "god-coder" not in d["policy"]["coder"]
    assert {"ninja-coder", "main-coder", "mathematician", "god-coder"} <= set(
        d["policy"]["ninja-coder"])
    assert {"main-coder", "ninja-coder"} <= set(d["policy"]["god-coder"])
    for eng in ("mlx-engineer", "cuda-engineer", "dl-engineer", "llm-engineer"):
        assert d["policy"][eng].index("ninja-coder") < d["policy"][eng].index("god-coder")
    assert d["policy"]["researcher"][0] == "researcher"
    assert d["policy"]["mlx-engineer"] == d["policy"]["cuda-engineer"]
    for new in ("plan-reviewer", "mlx-engineer", "cuda-engineer", "devops-engineer",
                "data-engineer", "frontend-engineer", "ml-engineer", "dl-engineer",
                "llm-engineer", "data-scientist", "browser-operator", "claude-code-engineer",
                "ninja-coder"):
        assert new in d["agents"]
    assert "senior-coder" not in d["agents"]
    # copies: exactly the agents whose row lists themselves; never these
    assert d["self_spawn"] == sorted(k for k, v in d["policy"].items() if k in v)
    for never in ("router", "orchestrator", "god-coder", "mlx-engineer", "cuda-engineer",
                  "designer", "motion-designer", "devops-engineer", "planner"):
        assert never not in d["self_spawn"]
    for want in ("coder", "main-coder", "ninja-coder", "researcher", "mathematician",
                 "ml-engineer", "dl-engineer", "llm-engineer", "data-scientist"):
        assert want in d["self_spawn"]
    assert {"Agent", "SendMessage", "Workflow", "CronCreate", "Skill"} <= set(d["router_tools"])
    assert not {"Bash", "Read", "Write", "Edit", "WebSearch"} & set(d["router_tools"])


def test_self_test(env):
    p = run("", env, args=["--self-test"])
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.strip() == "agent_guard self-test: ok"


def test_self_test_fails_on_unwritable_state(env, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    p = run("", env, args=["--self-test"], extra={"XDG_STATE_HOME": str(blocker)})
    assert p.returncode == 1 and "FAIL" in p.stdout


# ---------------------------------------------------------------- policy
def test_every_allowed_pair_allowed(env):
    pol = policy(env)["policy"]
    for parent, row in pol.items():
        for child in row:
            ev = (pre_agent(sid(), child, parent="router") if parent == "router" else
                  pre_agent(sid(), child, parent=parent, agent_id="id-" + parent))
            assert decision(run(ev, env)) == "allow", (parent, child)


@pytest.mark.parametrize("parent,child", [
    ("router", "general-purpose"), ("router", "fork"), ("router", "explore"),
    ("router", "statusline-setup"), ("router", "claude"), ("router", "plan"),
    ("router", "router"), ("orchestrator", "general-purpose"), ("orchestrator", "orchestrator"),
    ("main-coder", "general-purpose"), ("main-coder", "fork"),
    ("mlx-engineer", "mlx-engineer"), ("cuda-engineer", "cuda-engineer"),
    ("devops-engineer", "devops-engineer"), ("designer", "designer"),
    ("image-director", "image-director"), ("browser-operator", "scout"),
    ("claude-code-engineer", "claude-code-engineer"), ("data-scientist", "god-coder"),
    ("ml-engineer", "god-coder"), ("planner", "planner"), ("llm-engineer", "designer"),
    ("coder", "main-coder"), ("coder", "god-coder"), ("scout", "coder"),
    ("planner", "coder"), ("plan-reviewer", "coder"), ("researcher", "coder"),
    ("devops-engineer", "god-coder"), ("data-engineer", "designer"),
    ("frontend-engineer", "god-coder"), ("mlx-engineer", "main-coder"),
    ("god-coder", "god-coder"), ("claude-code-guide", "scout"), ("verifier", "coder"),
])
def test_denied_pairs(env, parent, child):
    ev = (pre_agent(sid(), child, parent="router") if parent == "router" else
          pre_agent(sid(), child, parent=parent, agent_id="id-" + parent))
    p = run(ev, env)
    assert decision(p) == "deny"
    assert "Spawn policy" in reason(p)


def test_missing_subagent_type_is_general_purpose(env):
    ev = pre_agent(sid(), "", parent="router")
    del ev["tool_input"]["subagent_type"]
    assert decision(run(ev, env)) == "deny"


def test_normalization(env):
    assert decision(run(pre_agent(sid(), "Explore", parent="Main_Coder", agent_id="x"),
                        env)) == "allow"


@pytest.mark.parametrize("parent", ["", "my-custom-agent"])
def test_unlisted_parent_unrestricted(env, parent):
    assert decision(run(pre_agent(sid(), "general-purpose", parent=parent), env)) == "allow"


# ---------------------------------------------------------------- depth
def test_depth_chain(env):
    s = sid()
    assert decision(run(pre_agent(s, "orchestrator", parent="router"), env)) == "allow"
    run(post_agent(s, "orchestrator", "A1"), env)
    run(post_agent(s, "main-coder", "A2", agent_id="A1", parent="orchestrator"), env)
    run(post_agent(s, "coder", "A3", agent_id="A2", parent="main-coder", as_string=True), env)
    reg = lambda a: json.loads((state(env, s) / "agents" / (a + ".json")).read_text())  # noqa
    assert [reg(a)["depth"] for a in ("A1", "A2", "A3")] == [1, 2, 3]
    assert reg("A3")["parent"] == "A2"
    # L2 may spawn, L3 may not
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="A2"), env)) \
        == "allow"
    p = run(pre_agent(s, "coder", parent="coder", agent_id="A3"), env)
    assert decision(p) == "deny" and "Depth limit" in reason(p)
    # unknown caller: allowed (native limit is authoritative)
    assert decision(run(pre_agent(s, "coder", parent="coder", agent_id="ZZ"), env)) == "allow"
    # child of an unknown caller has null depth and is allowed too (ZZ is a main-coder, so the
    # coder A4 is not a copy and may itself spawn a coder)
    run(post_agent(s, "coder", "A4", agent_id="ZZ", parent="main-coder"), env)
    assert reg("A4")["depth"] is None
    assert decision(run(pre_agent(s, "coder", parent="coder", agent_id="A4"), env)) == "allow"
    # knob
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="A2"), env,
            extra={"STACK_MAX_DEPTH": "2"})
    assert decision(p) == "deny"
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="A2"), env,
            extra={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2"})
    assert decision(p) == "deny"


def test_subagent_start_does_not_clobber_depth(env):
    s = sid()
    run(post_agent(s, "coder", "C1"), env)
    run(lifecycle(s, "SubagentStart", "C1", "coder"), env)
    reg = json.loads((state(env, s) / "agents" / "C1.json").read_text())
    assert reg["depth"] == 1 and reg["type"] == "coder" and "started" in reg


# ---------------------------------------------------------------- router dispatch (M4)
def test_router_dispatch_default_is_three_concurrent(env):
    for _ in range(REPEATS):
        s = sid()
        res = run_many([pre_agent(s, "coder", parent="router") for _ in range(FANOUT)], env)
        assert res.count("allow") == 3, res
        # losers left no fan-out leases or dispatch markers behind
        assert len(list((state(env, s) / "fanout" / "main").iterdir())) == 3
        assert len(list((state(env, s) / "router").iterdir())) == 3


def test_router_dispatch_once_concurrent(env):
    for _ in range(REPEATS):
        s = sid()
        res = run_many([pre_agent(s, "coder", parent="router") for _ in range(FANOUT)], env,
                       extra={"ROUTER_MAX_DISPATCH": "1"})
        assert res.count("allow") == 1, res


def test_router_dispatch_knob_concurrent(env):
    s = sid()
    res = run_many([pre_agent(s, "coder", parent="router") for _ in range(FANOUT)], env,
                   extra={"ROUTER_MAX_DISPATCH": "3"})
    assert res.count("allow") == 3


def test_router_new_prompt_and_rollback(env):
    env["ROUTER_MAX_DISPATCH"] = "1"
    s = sid()
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="p1"), env)) == "allow"
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="p1"), env)) == "deny"
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="p2"), env)) == "allow"
    # PermissionDenied for the router's p1 call frees the slot
    fail = pre_agent(s, "coder", parent="router", prompt="p1")
    fail["hook_event_name"] = "PermissionDenied"
    assert run(fail, env).stdout == ""
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="p1"), env)) == "allow"
    # a subagent's failure does not touch router markers
    sub = pre_agent(s, "coder", parent="coder", agent_id="C9", prompt="p1")
    sub["hook_event_name"] = "PostToolUseFailure"
    run(sub, env)
    assert (state(env, s) / "router" / "dispatch.p1.0").exists()


def test_user_prompt_prunes_other_prompts(env):
    env["ROUTER_MAX_DISPATCH"] = "1"
    s = sid()
    run(pre_agent(s, "coder", parent="router", prompt="p1"), env)
    run({"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": "p2"}, env)
    assert not (state(env, s) / "router" / "dispatch.p1.0").exists()
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="p1"), env)) == "allow"
    # prompt_id absent -> "noprompt" markers, cleared by the next UserPromptSubmit
    ev = pre_agent(s, "coder", parent="router")
    del ev["prompt_id"]
    assert decision(run(ev, env)) == "allow"
    assert decision(run(ev, env)) == "deny"
    run({"session_id": s, "hook_event_name": "UserPromptSubmit"}, env)
    assert decision(run(ev, env)) == "allow"


def test_router_god_rollback_when_dispatch_taken(env):
    env["ROUTER_MAX_DISPATCH"] = "1"
    s = sid()
    assert decision(run(pre_agent(s, "coder", parent="router"), env)) == "allow"
    assert decision(run(pre_agent(s, "god-coder", parent="router"), env)) == "deny"
    assert god_lock(env, s) is None


# ---------------------------------------------------------------- god-coder lock
def test_god_concurrent_spawns_single_winner(env):
    for _ in range(REPEATS):
        s = sid()
        evs = [pre_agent(s, "god-coder", parent="main-coder", agent_id="sc%d" % i)
               for i in range(FANOUT)]
        res = run_many(evs, env)
        assert res.count("allow") == 1, res
        assert god_lock(env, s)["state"] == "pending"


def test_god_confirm_and_release_by_subagent_stop(env):
    s = sid()
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"),
                        env)) == "allow"
    run(lifecycle(s, "SubagentStart", "G1", "god-coder"), env)
    lk = god_lock(env, s)
    assert lk["state"] == "running" and lk["holder"] == "G1" and lk["by"] == "sc"
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "deny"
    p = run(lifecycle(s, "SubagentStop", "X9", "coder"), env)
    assert p.stdout == "" and god_lock(env, s)
    p = run(lifecycle(s, "SubagentStop", "G1", "god-coder"), env)
    assert p.stdout == "" and god_lock(env, s) is None
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "allow"


def test_god_post_tool_use_confirm_and_completed_release(env):
    s = sid()
    run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    run(post_agent(s, "god-coder", "G1", agent_id="sc", parent="main-coder"), env)
    assert god_lock(env, s)["holder"] == "G1"
    run(post_agent(s, "god-coder", "G1", agent_id="sc", parent="main-coder",
                   status="completed"), env)
    assert god_lock(env, s) is None


def test_god_foreground_completed_does_not_recreate(env):
    s = sid()
    run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    run(lifecycle(s, "SubagentStart", "G1", "god-coder"), env)
    run(lifecycle(s, "SubagentStop", "G1", "god-coder"), env)
    run(post_agent(s, "god-coder", "G1", agent_id="sc", parent="main-coder",
                   status="completed"), env)
    assert god_lock(env, s) is None


def test_god_failure_rollback_only_by_owner(env):
    s = sid()
    ev = pre_agent(s, "god-coder", parent="main-coder", agent_id="sc")
    run(ev, env)
    other = dict(ev, agent_id="sc-other", hook_event_name="PostToolUseFailure")
    run(other, env)
    assert god_lock(env, s)["state"] == "pending"
    run(dict(ev, hook_event_name="PermissionDenied"), env)
    assert god_lock(env, s) is None


def test_god_pending_lease_expires(env):
    """M3: a lease left by a call denied elsewhere blocks until GOD_PENDING_TTL_S."""
    s = sid()
    run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "deny"
    age_lock(env, s, "god-coder.lock", 121)
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "allow"
    assert god_lock(env, s)["by"] == "sc2"


def test_god_idle_reclaim(env, tmp_path):
    s = sid()
    tp = tmp_path / "proj" / "main.jsonl"
    sub = tmp_path / "proj" / s / "subagents" / "agent-G1.jsonl"
    sub.parent.mkdir(parents=True)
    sub.write_text("{}\n")
    run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    run(lifecycle(s, "SubagentStart", "G1", "god-coder"), env)
    age_lock(env, s, "god-coder.lock", 1000)
    nxt = dict(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
               transcript_path=str(tp))
    # transcript fresh -> still busy
    assert decision(run(nxt, env)) == "deny"
    old = time.time() - 1000
    os.utime(sub, (old, old))
    assert decision(run(nxt, env)) == "allow"


def test_god_hard_ttl(env):
    s = sid()
    run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    run(lifecycle(s, "SubagentStart", "G1", "god-coder"), env)
    age_lock(env, s, "god-coder.lock", 3600)
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "deny"
    age_lock(env, s, "god-coder.lock", 21601)
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc2"),
                        env)) == "allow"


def test_god_resume_via_sendmessage(env):
    """M2: resuming a finished god-coder takes the lock."""
    s = sid()
    run(pre_agent(s, "god-coder", parent="router"), env)
    run(post_agent(s, "god-coder", "GA"), env)
    run(lifecycle(s, "SubagentStop", "GA", "god-coder"), env)
    assert god_lock(env, s) is None
    assert run(send(s, "GA"), env).stdout == ""
    lk = god_lock(env, s)
    assert lk["state"] == "resumed" and lk["holder"] == "GA" and lk["by"] == "main"
    p = run(pre_agent(s, "god-coder", parent="main-coder", agent_id="sc"), env)
    assert decision(p) == "deny" and "GA" in reason(p)
    assert decision(run(send(s, "GA"), env)) == "allow"
    # a second finished god-coder cannot be resumed meanwhile
    run(post_agent(s, "god-coder", "GB", agent_id="sc", parent="main-coder",
                   status="completed"), env)
    assert decision(run(send(s, "GB"), env)) == "deny"
    # non-god targets untouched
    run(post_agent(s, "coder", "C1"), env)
    before = god_lock(env, s)
    assert run(send(s, "C1"), env).stdout == ""
    assert run(send(s, "unknown-id"), env).stdout == ""
    assert god_lock(env, s) == before
    # resumed run finishes -> released
    run(lifecycle(s, "SubagentStop", "GA", "god-coder"), env)
    assert god_lock(env, s) is None


def test_god_resume_by_name(env):
    s = sid()
    run(pre_agent(s, "god-coder", parent="router", name="Deep Fix"), env)
    run(post_agent(s, "god-coder", "GN", name="Deep Fix", status="completed"), env)
    assert god_lock(env, s) is None
    assert decision(run(send(s, "deep-fix"), env)) == "allow"
    assert god_lock(env, s)["holder"] == "GN"
    assert decision(run(pre_agent(s, "god-coder", parent="main-coder", agent_id="x"),
                        env)) == "deny"


def test_sendmessage_resume_stopped_holder_is_stale(env):
    s = sid()
    run(post_agent(s, "god-coder", "GA"), env)
    run(post_agent(s, "god-coder", "GB", status="completed"), env)
    run(lifecycle(s, "SubagentStop", "GB", "god-coder"), env)
    # lock held by GA (running); force GA's registry to stopped after the lock ts
    reg = state(env, s) / "agents" / "GA.json"
    obj = json.loads(reg.read_text())
    obj["stopped"] = time.time() + 1
    reg.write_text(json.dumps(obj))
    assert decision(run(send(s, "GB"), env)) == "allow"
    assert god_lock(env, s)["holder"] == "GB"


# ---------------------------------------------------------------- screen lock
def test_screen_concurrent_single_holder(env):
    for _ in range(REPEATS):
        s = sid()
        res = run_many([screen(s, agent_id="d%d" % i) for i in range(FANOUT)], env)
        assert res.count("allow") == 1, res


def test_screen_holder_release_and_stale(env):
    s = sid()
    for _ in range(3):
        assert decision(run(screen(s, agent_id="D1"), env)) == "allow"
    p = run(screen(s, agent_id="D2", agent_type="motion-designer"), env)
    assert decision(p) == "deny" and "designer" in reason(p)
    run(lifecycle(s, "SubagentStop", "D2", "motion-designer"), env)
    assert decision(run(screen(s, agent_id="D2"), env)) == "deny"
    run(lifecycle(s, "SubagentStop", "D1", "designer"), env)
    assert decision(run(screen(s, agent_id="D2"), env)) == "allow"
    age_lock(env, s, "screen.lock", 901)
    assert decision(run(screen(s, agent_id="D3"), env)) == "allow"
    assert decision(run(screen(s), env)) == "deny"  # main thread vs D3


# ---------------------------------------------------------------- SessionStart (M1)
@pytest.mark.parametrize("source,cleared", [("compact", False), ("clear", False),
                                            ("startup", True), ("resume", True)])
def test_session_start_sources(env, source, cleared):
    s = sid()
    run(pre_agent(s, "god-coder", parent="router"), env)
    run(post_agent(s, "god-coder", "G1"), env)
    run(screen(s, agent_id="D1"), env)
    p = run({"session_id": s, "hook_event_name": "SessionStart", "source": source}, env)
    assert p.returncode == 0 and p.stdout == ""
    d = state(env, s)
    for f in ("god-coder.lock", "screen.lock", "router"):
        assert (d / f).exists() != cleared, (source, f)
    assert (d / "agents" / "G1.json").exists()  # registry kept


def test_session_start_prunes_old_dirs(env):
    root = Path(env["XDG_STATE_HOME"]) / "claude-agent-stack"
    old, fresh = root / "old-session", root / "fresh-session"
    for d in (old, fresh):
        (d / "agents").mkdir(parents=True)
        (d / "god-coder.lock").write_text("{}")
    t = time.time() - 4 * 86400
    for p in (old / "agents", old / "god-coder.lock", old):
        os.utime(p, (t, t))
    run({"session_id": "cur", "hook_event_name": "SessionStart", "source": "startup"}, env)
    assert not old.exists() and fresh.exists() and (root / "cur").exists()


# ---------------------------------------------------------------- fail-closed (L7)
def test_bad_tool_input_denied(env):
    ev = pre_agent(sid(), "coder", parent="router")
    ev["tool_input"] = "not an object"
    p = run(ev, env)
    assert decision(p) == "deny" and "stack guard error" in reason(p)
    # the escape hatch goes to the user (systemMessage), never to the model (reason)
    assert "STACK_POLICY" not in reason(p)
    assert "STACK_POLICY" in json.loads(p.stdout)["systemMessage"]
    ev["tool_name"] = "SendMessage"
    assert decision(run(ev, env)) == "deny"


def test_policy_off_no_output(env):
    extra = {"STACK_POLICY": "off"}
    s = sid()
    for ev in (pre_agent(s, "general-purpose", parent="router"),
               pre_agent(s, "coder", parent="router"), pre_agent(s, "coder", parent="router"),
               pre_agent(s, "god-coder", parent="scout", agent_id="x"),
               screen(s, agent_id="a"), screen(s, agent_id="b")):
        p = run(ev, env, extra=extra)
        assert p.returncode == 0 and p.stdout == ""
    assert god_lock(env, s) is None
    bad = pre_agent(s, "coder")
    bad["tool_input"] = []
    p = run(bad, env, extra=extra)
    assert p.returncode == 0 and p.stdout == ""
    # model strip still applies
    p = run(pre_agent(s, "coder", model="sonnet"), env, extra=extra)
    assert "updatedInput" in p.stdout


def test_exception_paths(env, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    extra = {"XDG_STATE_HOME": str(blocker)}
    p = run(lifecycle("s", "SubagentStop", "A", "coder"), env, extra=extra)
    assert p.returncode == 0 and p.stdout == "" and "agent_guard" in p.stderr
    p = run({"session_id": "s", "hook_event_name": "SessionStart", "source": "startup"}, env,
            extra=extra)
    assert p.returncode == 0 and p.stdout == ""
    p = run(pre_agent("s", "coder", parent="router"), env, extra=extra)
    assert decision(p) == "deny" and "stack guard error" in reason(p)


def test_unparseable_stdin(env):
    p = run("{not json", env)
    assert p.returncode == 0 and p.stdout == ""
    p = run("{not json", env, args=["router-guard"])
    assert decision(p) == "deny"
    p = run("{not json", env, args=["router-guard"], extra={"STACK_POLICY": "off"})
    assert p.returncode == 0 and p.stdout == ""


# ---------------------------------------------------------------- router-guard mode
def rg(s, tool, prompt="p1", **extra):
    return dict({"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
                 "prompt_id": prompt, "tool_input": {}}, **extra)


def test_router_guard_allowlist(env):
    s = sid()
    for tool in ("Read", "Bash", "Write", "Edit", "WebSearch", "WebFetch", "mcp__exa__search",
                 "TaskOutput", "NotebookEdit", "Monitor"):
        p = run(rg(s, tool), env, args=["router-guard"])
        assert decision(p) == "deny" and "Router only delegates" in reason(p)
    for tool in ("SendMessage", "AskUserQuestion", "mcp__conductor__AskUserQuestion", "ExitPlanMode",
                 "TaskStop", "ListAgents", "ToolSearch",
                 "Skill", "Workflow", "CronCreate", "CronList", "CronDelete", "ScheduleWakeup",
                 "RemoteTrigger", "PushNotification", "SendUserFile"):
        assert decision(run(rg(s, tool, prompt="p-" + tool), env, args=["router-guard"])) \
            == "allow", tool


def test_router_guard_subagent_passes_and_no_substring_bypass(env):
    s = sid()
    assert decision(run(rg(s, "Bash", agent_id="A1", agent_type="coder"), env,
                        args=["router-guard"])) == "allow"
    ev = rg(s, "Bash")
    ev["tool_input"] = {"command": "echo", "agent_id": "fake", "note": '"agent_id"'}
    assert decision(run(ev, env, args=["router-guard"])) == "deny"


def test_router_guard_steps_and_agent_never_denied(env):
    s = sid()
    res = [decision(run(rg(s, "ToolSearch"), env, args=["router-guard"])) for _ in range(9)]
    assert res == ["allow"] * 8 + ["deny"]
    assert decision(run(rg(s, "Agent"), env, args=["router-guard"])) == "allow"
    assert decision(run(rg(s, "ToolSearch", prompt="p2"), env, args=["router-guard"])) == "allow"
    assert decision(run(rg(s, "ToolSearch"), env, args=["router-guard"],
                        extra={"ROUTER_MAX_STEPS": "20"})) == "allow"


def test_router_guard_steps_concurrent(env):
    s = sid()
    res = run_many([rg(s, "ToolSearch") for _ in range(FANOUT)], env, args=["router-guard"])
    assert res.count("allow") == 8


def test_router_hook_command_as_rendered(env, tmp_path):
    """router.md's frontmatter hook runs the interpreter directly (no sh wrapper, no bare
    python3 on PATH): render its command the way install.sh does and run it through a shell."""
    text = (ROOT / "dot-claude" / "agents" / "router.md").read_text()
    m = re.search(r'(?m)^\s+command:\s*"(.*)"\s*$', text)
    assert m, "router.md has no hook command"
    cmd = json.loads('"%s"' % m.group(1))
    assert "__PYTHON3__" in cmd and cmd.rstrip().endswith("router-guard")
    cmd = cmd.replace("__PYTHON3__", sys.executable).replace(
        "__CLAUDE_DIR__", str(ROOT / "dot-claude"))
    s = sid()
    p = run(rg(s, "Read"), env, cmd=["sh", "-c", cmd])
    assert decision(p) == "deny"
    p = run(rg(s, "SendMessage"), env, cmd=["sh", "-c", cmd])
    assert decision(p) == "allow"


# ---------------------------------------------------------------- model strip, logging
def test_model_strip(env):
    p = run(pre_agent(sid(), "coder", parent="router", model="opus"), env)
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "model" not in out["updatedInput"]
    assert out["updatedInput"]["subagent_type"] == "coder"
    p = run(pre_agent(sid(), "coder", parent="router", model="opus"), env,
            extra={"STRIP_AGENT_MODEL": "0"})
    assert p.stdout == ""


def test_guard_log(env):
    s = sid()
    run(lifecycle(s, "SubagentStart", "A", "coder"), env, extra={"STACK_GUARD_LOG": "1"})
    run(lifecycle(s, "SubagentStart", "B", "coder"), env)
    lines = (state(env, s) / "guard.log").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["agent_id"] == "A"


def test_lifecycle_never_outputs_decision(env):
    s = sid()
    for ev in (lifecycle(s, "SubagentStart", "G", "god-coder"),
               lifecycle(s, "SubagentStop", "G", "god-coder"),
               {"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": "p"},
               post_agent(s, "coder", "C")):
        p = run(ev, env)
        assert p.returncode == 0 and p.stdout == ""


# ---------------------------------------------------------------- router dispatch window
def test_router_dispatch_window(env):
    s = sid()
    assert decision(run(pre_agent(s, "scout", parent="router", prompt="w1"), env)) == "allow"
    assert decision(run(pre_agent(s, "oracle", parent="router", prompt="w1"), env)) == "allow"
    # the burst is over once the first dispatch is older than the window
    m = state(env, s) / "router" / "dispatch.w1.0"
    m.write_text(str(time.time() - 120))
    p = run(pre_agent(s, "coder", parent="router", prompt="w1"), env)
    assert decision(p) == "deny" and "together in one message" in reason(p)
    # a longer window lets it through; a new prompt starts a new burst
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="w1"), env,
                        extra={"ROUTER_DISPATCH_WINDOW_S": "600"})) == "allow"
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="w2"), env)) == "allow"
    # a marker caught between O_EXCL create and its timestamp write counts as brand new
    m.write_text("")
    assert decision(run(pre_agent(s, "writer", parent="router", prompt="w1"), env,
                        extra={"ROUTER_MAX_DISPATCH": "5"})) == "allow"


# ---------------------------------------------------------------- copies (self-spawn)
def test_self_spawn_one_generation(env):
    s = sid()
    # router -> coder C1 (a normal agent): C1 may copy itself
    run(post_agent(s, "coder", "C1"), env, extra={})
    ev = pre_agent(s, "coder", parent="coder", agent_id="C1")
    assert decision(run(ev, env)) == "allow"
    run(post_agent(s, "coder", "C2", agent_id="C1", parent="coder"), env)
    reg = json.loads((state(env, s) / "agents" / "C2.json").read_text())
    assert reg["parent"] == "C1" and reg["parent_type"] == "coder" and reg["depth"] == 2
    # C2 is a copy: it cannot copy itself again, but may use its other children
    p = run(pre_agent(s, "coder", parent="coder", agent_id="C2"), env)
    assert decision(p) == "deny" and "Self-copy rule" in reason(p)
    assert decision(run(pre_agent(s, "scout", parent="coder", agent_id="C2"), env)) == "allow"
    # a researcher spawned by the orchestrator is not a copy
    run(post_agent(s, "researcher", "R1", agent_id="O1", parent="orchestrator"), env)
    assert decision(run(pre_agent(s, "researcher", parent="researcher", agent_id="R1"), env)) \
        == "allow"


# ---------------------------------------------------------------- fan-out caps
def test_fanout_cap_concurrent(env):
    for limit in ("8", "5"):
        s = sid()
        evs = [pre_agent(s, "coder", parent="main-coder", agent_id="SC") for _ in range(FANOUT)]
        res = run_many(evs, env, extra={} if limit == "8" else {"STACK_MAX_FANOUT": limit})
        assert res.count("allow") == int(limit), res


def test_self_fanout_cap_concurrent(env):
    s = sid()
    evs = [pre_agent(s, "main-coder", parent="main-coder", agent_id="SC")
           for _ in range(FANOUT)]
    res = run_many(evs, env)
    assert res.count("allow") == 4, res
    p = run(pre_agent(s, "main-coder", parent="main-coder", agent_id="SC"), env)
    assert decision(p) == "deny" and "Copy limit" in reason(p)
    # other children still fit under the overall cap (8)
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="SC"), env)) \
        == "allow"


def test_fanout_lease_lifecycle(env):
    s = sid()
    extra = {"STACK_MAX_FANOUT": "2"}
    ev1 = pre_agent(s, "coder", parent="main-coder", agent_id="SC")
    ev2 = pre_agent(s, "coder", parent="main-coder", agent_id="SC")
    assert decision(run(ev1, env, extra=extra)) == "allow"
    assert decision(run(ev2, env, extra=extra)) == "allow"
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "deny"
    leases = state(env, s) / "fanout" / "SC"
    assert len(list(leases.iterdir())) == 2
    # PostToolUse turns lease 1 into a registered running child; failure drops lease 2
    run(post_agent(s, "coder", "K1", agent_id="SC", parent="main-coder",
                   tool_use_id=ev1["tool_use_id"]), env)
    fail = dict(ev2, hook_event_name="PostToolUseFailure")
    run(fail, env)
    assert list(leases.iterdir()) == []
    reg = json.loads((state(env, s) / "agents" / "K1.json").read_text())
    assert reg["parent"] == "SC" and reg["type"] == "coder" and "spawned" in reg
    # K1 still running -> one slot left
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "allow"
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "deny"
    # K1 stops -> its slot frees up (one unconfirmed scout lease is still pending)
    run(lifecycle(s, "SubagentStop", "K1", "coder"), env)
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "allow"
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "deny"
    # leases never confirmed by PostToolUse expire
    time.sleep(1.1)
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=dict(extra, STACK_FANOUT_PENDING_TTL_S="1"))) == "allow"


def test_fanout_idle_child_not_counted(env):
    s = sid()
    run(post_agent(s, "coder", "K1", agent_id="SC", parent="main-coder"), env)
    path = state(env, s) / "agents" / "K1.json"
    reg = json.loads(path.read_text())
    reg["spawned"] = time.time() - 7200
    path.write_text(json.dumps(reg))
    extra = {"STACK_MAX_FANOUT": "1"}
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="SC"), env,
                        extra=extra)) == "allow"


def test_session_start_marks_children_stopped(env):
    s = sid()
    for i in range(3):
        run(post_agent(s, "coder", "K%d" % i), env)
    extra = {"STACK_MAX_FANOUT": "3"}
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="q1"), env,
                        extra=extra)) == "deny"
    run({"session_id": s, "hook_event_name": "SessionStart", "source": "resume"}, env)
    assert not (state(env, s) / "fanout").exists()
    assert decision(run(pre_agent(s, "coder", parent="router", prompt="q1"), env,
                        extra=extra)) == "allow"
    # a resumed child (SubagentStart) counts again
    run(lifecycle(s, "SubagentStart", "K0", "coder"), env)
    reg = json.loads((state(env, s) / "agents" / "K0.json").read_text())
    assert "stopped" not in reg


def test_fanout_cap_disabled(env):
    s = sid()
    res = run_many([pre_agent(s, "coder", parent="main-coder", agent_id="SC")
                    for _ in range(12)], env, extra={"STACK_MAX_FANOUT": "0"})
    assert res.count("allow") == 12


# ---------------------------------------------------------------- local-file MCP tools
@pytest.fixture
def installed(tmp_path):
    """The guard in an installed layout: <cfg>/hooks/agent_guard.py next to a rendered
    <cfg>/settings.json, a fake HOME with secrets, and a project with a .env."""
    cfg, home, proj = tmp_path / "cfg", tmp_path / "home", tmp_path / "proj"
    (cfg / "hooks").mkdir(parents=True)
    (cfg / "hooks" / "agent_guard.py").write_text(GUARD.read_text())
    settings = (ROOT / "dot-claude" / "settings.json").read_text()
    (cfg / "settings.json").write_text(settings.replace("__CLAUDE_DIR__", str(cfg)))
    (cfg / "stack.env").write_text("EXA_API_KEY=x\n")
    (home / ".ssh").mkdir(parents=True)
    (home / ".ssh" / "id_ed25519").write_text("key")
    (home / ".aws").mkdir()
    (home / ".aws" / "credentials").write_text("key")
    (home / ".netrc").write_text("machine x")
    (proj / "docs").mkdir(parents=True)
    (proj / ".env").write_text("SECRET=1")
    (proj / "notes.md").write_text("# notes")
    (proj / "docs" / "a.md").write_text("# a")
    (proj / "link.md").symlink_to(home / ".ssh" / "id_ed25519")
    return cfg, home, proj


def local_read(env, installed, tool, ti, extra=None):
    cfg, home, proj = installed
    ev = {"session_id": sid(), "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": ti, "cwd": str(proj), "agent_id": "a1", "agent_type": "doc-specialist"}
    return decision(run(ev, env, extra=dict({"HOME": str(home)}, **(extra or {})),
                        cmd=[sys.executable, str(cfg / "hooks" / "agent_guard.py")]))


def test_local_read_guard_ctx_index(env, installed):
    cfg, home, proj = installed
    t = "mcp__context-mode__ctx_index"
    assert local_read(env, installed, t, {"path": str(cfg / "stack.env")}) == "deny"   # //abs rule
    assert local_read(env, installed, t, {"path": "~/.ssh/id_ed25519"}) == "deny"      # ~/ rule
    assert local_read(env, installed, t, {"path": str(home / ".ssh" / "id_ed25519")}) == "deny"
    assert local_read(env, installed, t, {"path": str(home / ".ssh")}) == "deny"       # the dir itself
    assert local_read(env, installed, t, {"path": str(home)}) == "deny"                # holds ~/.ssh
    assert local_read(env, installed, t, {"path": str(cfg)}) == "deny"                 # holds stack.env
    assert local_read(env, installed, t, {"path": ".env"}) == "deny"                   # **/.env, relative
    assert local_read(env, installed, t, {"path": "docs/../.env"}) == "deny"
    assert local_read(env, installed, t, {"path": "link.md"}) == "deny"                # symlink to a key
    assert local_read(env, installed, t, {"path": "notes.md"}) == "allow"
    assert local_read(env, installed, t, {"path": str(proj / "docs" / "a.md")}) == "allow"
    # ctx_index walks a directory it is given: directories are refused outright
    assert local_read(env, installed, t, {"path": str(proj / "docs")}) == "deny"
    assert local_read(env, installed, t, {"path": "."}) == "deny"
    assert local_read(env, installed, t, {"content": "# x", "source": ".env"}) == "allow"
    # scheme-looking strings are relative paths to a tool that doesn't parse URIs
    for sneaky in ("x:/../../home/.ssh/id_ed25519", "file:/../../home/.ssh/id_ed25519",
                   "http://../../home/.ssh/id_ed25519", "C:/../../home/.aws/credentials",
                   "..%2Fhome%2F.netrc", " ../home/.netrc"):
        assert local_read(env, installed, t, {"path": sneaky}) == "deny", sneaky
    assert local_read(env, installed, t, {"path": str(cfg / "stack.env")},
                      extra={"STACK_POLICY": "off"}) == "allow"


def test_local_read_guard_uris_and_other_tools(env, installed):
    cfg, home, proj = installed
    md = "mcp__markitdown__convert_to_markdown"
    assert local_read(env, installed, md, {"uri": "file://" + str(cfg / "stack.env")}) == "deny"
    assert local_read(env, installed, md, {"uri": "file:" + str(home / ".netrc")}) == "deny"
    assert local_read(env, installed, md,
                      {"uri": "file://localhost" + str(home / "%2Essh/id_ed25519")}) == "deny"
    assert local_read(env, installed, md, {"uri": "file://" + str(proj / "notes.md")}) == "allow"
    assert local_read(env, installed, md, {"uri": "https://example.com/.env"}) == "allow"   # remote
    pw = "mcp__playwright__browser_navigate"
    assert local_read(env, installed, pw, {"url": "file://" + str(home / ".aws" / "credentials")}) == "deny"
    assert local_read(env, installed, pw, {"url": "https://example.com"}) == "allow"
    up = "mcp__playwright__browser_file_upload"
    assert local_read(env, installed, up,
                      {"paths": [str(proj / "notes.md"), str(home / ".ssh" / "id_ed25519")]}) == "deny"
    assert local_read(env, installed, "mcp__magg__pw_browser_file_upload",
                      {"paths": [str(proj / "notes.md")]}) == "allow"
    dl = "mcp__magg__docling_convert_document_into_docling_document"
    assert local_read(env, installed, dl, {"source": str(home / ".netrc")}) == "deny"
    assert local_read(env, installed, dl, {"source": "https://example.com/.env"}) == "allow"  # a URL
    for sneaky in (" https://../../home/.netrc", "HTTPS://../../home/.netrc"):   # a path to docling
        assert local_read(env, installed, dl, {"source": sneaky}) == "deny", sneaky
    # tools outside the list are not this guard's business
    assert local_read(env, installed, "mcp__context-mode__ctx_search", {"queries": [".env"]}) == "allow"


def test_local_read_guard_bases_limits_and_classes(env, installed):
    cfg, home, proj = installed
    t = "mcp__context-mode__ctx_index"
    # the agent moved into docs/, but context-mode resolves against the project it started in
    ev_extra = {"CLAUDE_PROJECT_DIR": str(proj)}
    cfg_, home_, proj_ = installed
    moved = (cfg_, home_, proj_ / "docs")
    assert local_read(env, moved, t, {"path": "../../home/.ssh/id_ed25519"}) == "deny"
    assert local_read(env, moved, t, {"path": "../home/.ssh/id_ed25519"}, extra=ev_extra) == "deny"
    # absurd arguments are refused rather than matched against the clock
    assert local_read(env, installed, t, {"path": "a/" * 3000 + "b.md"}) == "deny"
    assert local_read(env, installed, "mcp__playwright__browser_file_upload",
                      {"paths": ["notes.md"] * 300}) == "deny"
    # gitignore character classes
    s = json.loads((cfg / "settings.json").read_text())
    s["permissions"]["deny"].append("Read(~/keys/id_[er]d25519)")
    (cfg / "settings.json").write_text(json.dumps(s))
    (home / "keys").mkdir()
    (home / "keys" / "id_ed25519").write_text("k")
    (home / "keys" / "id_xd25519").write_text("k")
    assert local_read(env, installed, t, {"path": str(home / "keys" / "id_ed25519")}) == "deny"
    assert local_read(env, installed, t, {"path": str(home / "keys" / "id_xd25519")}) == "allow"


def test_local_read_guard_rule_shapes_and_symlinked_anchors(env, installed):
    cfg, home, proj = installed
    t = "mcp__context-mode__ctx_index"
    vault = home / "vault"
    (vault / "gpg").mkdir(parents=True)
    (vault / "gpg" / "key.asc").write_text("k")
    (home / ".gnupg").symlink_to(vault / "gpg")                  # ~/.gnupg kept in a vault folder
    (vault / "token.txt").write_text("t")
    (home / "token.txt").symlink_to(vault / "token.txt")
    (home / "notes").mkdir()
    (home / "notes" / "a.md").write_text("a")
    s = json.loads((cfg / "settings.json").read_text())
    s["permissions"]["deny"] += ["Read(~/.gnupg/)", "Read(~//notes/**)", "Read(~/token.txt)"]
    (cfg / "settings.json").write_text(json.dumps(s))
    assert local_read(env, installed, t, {"path": str(home / ".gnupg" / "key.asc")}) == "deny"  # dir/
    assert local_read(env, installed, t, {"path": str(vault / "gpg" / "key.asc")}) == "deny"    # its target
    assert local_read(env, installed, t, {"path": str(vault / "token.txt")}) == "deny"          # file target
    assert local_read(env, installed, t, {"path": str(home / "notes" / "a.md")}) == "deny"     # a//b
    s["permissions"]["deny"] = ["Read"]                          # Read denied outright
    (cfg / "settings.json").write_text(json.dumps(s))
    assert local_read(env, installed, t, {"path": "notes.md"}) == "deny"


def test_unparseable_pre_tool_use_fails_closed(env):
    deep = "[" * 100000 + "]" * 100000
    raw = '{"hook_event_name": "PreToolUse", "tool_name": "mcp__context-mode__ctx_index", "x": %s}' % deep
    assert decision(run(raw, env)) == "deny"
    p = run('{"hook_event_name": "SubagentStop", "x": %s}' % deep, env)
    assert p.returncode == 0 and not p.stdout.strip()


def test_local_read_guard_project_rules(env, installed):
    cfg, home, proj = installed
    (proj / ".claude").mkdir()
    (proj / ".claude" / "settings.json").write_text(json.dumps(
        {"permissions": {"deny": ["Read(./secrets/**)", "Read(/private.md)"]}}))
    (proj / "secrets").mkdir()
    (proj / "secrets" / "a.txt").write_text("s")
    (proj / "private.md").write_text("p")
    (proj / ".claude" / "private.md").write_text("p")
    t = "mcp__context-mode__ctx_index"
    assert local_read(env, installed, t, {"path": "secrets/a.txt"}) == "deny"
    assert local_read(env, installed, t, {"path": "private.md"}) == "deny"          # /x: <project>/x
    assert local_read(env, installed, t, {"path": ".claude/private.md"}) == "deny"  # (and .claude/x)
    assert local_read(env, installed, t, {"path": "notes.md"}) == "allow"


def test_local_read_guard_hook_wired(env):
    """settings.json routes exactly these tools to the guard."""
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    matchers = [g["matcher"] for g in s["hooks"]["PreToolUse"]]
    rx = next(re.compile("^(?:%s)$" % m) for m in matchers if "ctx_index" in m)
    for tool in ("mcp__context-mode__ctx_index", "mcp__markitdown__convert_to_markdown",
                 "mcp__magg__docling_convert_document_into_docling_document",
                 "mcp__playwright__browser_navigate", "mcp__magg__pw_browser_file_upload"):
        assert rx.match(tool), tool
    for tool in ("mcp__context-mode__ctx_search", "mcp__context-mode__ctx_fetch_and_index", "Read"):
        assert not rx.match(tool), tool
