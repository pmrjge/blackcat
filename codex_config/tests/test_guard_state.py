"""The stateful half of codex_guard (DESIGN.md §5 rows: caps, web taint, send_input routing; Phase 4b
spawn tree): counters under the state dir with flock (also across concurrent processes), the spawn
tree from PostToolUse(spawn_agent) and SubagentStart, taint propagation, the computer-use lock, and
the fail-closed paths (catch-all, unreadable event or policy)."""
from __future__ import annotations

import concurrent.futures
import json

import pytest

from _guard_helpers import (Guard, Stack, bash, decision, event, interpreter, pre, reason, run_stub)


@pytest.fixture
def stack(tmp_path):
    return Stack(tmp_path, python=interpreter())


@pytest.fixture
def guard(stack, monkeypatch):
    return Guard(stack, monkeypatch)


def spawn(guard, caller, caller_id, target, tuid, child_id=None, response=None):
    """PreToolUse + PostToolUse of one spawn_agent call; then the child's SubagentStart."""
    ti = {"agent_type": target, "message": "go"}
    ev = pre("spawn_agent", ti, agent_type=caller, agent_id=caller_id, tool_use_id=tuid)
    out = guard.pre(ev)
    assert decision(out) != "deny", reason(out)
    resp = response if response is not None else (json.dumps({"agent_id": child_id}) if child_id
                                                  else "")
    post = event("post_tool_use", tool_name="spawn_agent", tool_input=ti, agent_type=caller,
                 agent_id=caller_id, tool_use_id=tuid, tool_response=resp)
    guard.observe("post_tool_use", post)
    if child_id:
        guard.observe("subagent_start", event("subagent_start", agent_id=child_id, agent_type=target))


def main_spawn(guard, target, tuid, child_id, response=None):
    ti = {"agent_type": target, "message": "go"}
    assert decision(guard.pre(pre("spawn_agent", ti, agent_type=None, tool_use_id=tuid))) != "deny"
    post = event("post_tool_use", tool_name="spawn_agent", tool_input=ti, agent_type=None,
                 tool_use_id=tuid, tool_response=response if response is not None else
                 {"agent_id": child_id})
    guard.observe("post_tool_use", post)
    guard.observe("subagent_start", event("subagent_start", agent_id=child_id, agent_type=target))


def send(guard, tool, target_id, caller=None, caller_id=None):
    return guard.pre(pre("multi_agent_v1" + tool, {"id": target_id, "message": "m"},
                         agent_type=caller, agent_id=caller_id))


def remember(guard, agent, aid):
    return guard.pre(pre("mcp__neural-memory__nmem_remember", {"content": "fact"}, agent_type=agent,
                         agent_id=aid))


# ---------------------------------------------------------------- web taint
def test_web_ingesting_role_never_writes_memory(guard):
    out = remember(guard, "researcher", "r1")
    assert decision(out) == "deny" and "web-taint" in reason(out)


def test_web_mcp_call_taints_the_caller(guard):
    assert remember(guard, "coder", "c1") is None
    assert guard.pre(pre("mcp__exa__web_search_exa", {"query": "q"}, agent_type="coder",
                         agent_id="c1")) is None
    assert decision(remember(guard, "coder", "c1")) == "deny"
    assert remember(guard, "coder", "c2") is None             # another coder is clean


def test_non_web_server_does_not_taint(guard):
    guard.pre(pre("mcp__neural-memory__nmem_recall", {"q": "x"}, agent_type="coder", agent_id="c1"))
    assert remember(guard, "coder", "c1") is None
    guard.pre(pre("mcp__libdocs__get_docs", {"id": "x"}, agent_type="coder", agent_id="c1"))
    assert decision(remember(guard, "coder", "c1")) == "deny"   # unlisted servers taint (fail closed)


def test_taint_flows_from_a_child_report_and_into_spawns(guard):
    main_spawn(guard, "python-engineer", "t1", "pe1")
    spawn(guard, "python-engineer", "pe1", "coder", "t2", child_id="c1")
    guard.pre(pre("mcp__exa__search", {}, agent_type="coder", agent_id="c1"))   # c1 tainted
    guard.observe("subagent_stop", event("subagent_stop", agent_id="c1", agent_type="coder"))
    assert decision(remember(guard, "designer", "x")) != "deny"            # unrelated agent
    # pe1 got c1's report: it may not write memory; its next child starts tainted
    spawn(guard, "python-engineer", "pe1", "coder", "t3", child_id="c2")
    assert decision(remember(guard, "coder", "c2")) == "deny"


def test_taint_flows_both_ways_along_send_input(guard):
    main_spawn(guard, "researcher", "t1", "r1")
    main_spawn(guard, "coder", "t2", "c1")
    # BlackCat (clean) messages the tainted researcher: BlackCat is tainted, then taints the coder
    assert send(guard, "send_input", "r1") is None
    assert send(guard, "send_input", "c1") is None
    assert decision(remember(guard, "coder", "c1")) == "deny"


def test_waiting_on_a_tainted_child_taints_the_waiter(guard):
    main_spawn(guard, "python-engineer", "t1", "pe1")
    spawn(guard, "python-engineer", "pe1", "coder", "t2", child_id="c1")
    assert guard.pre(pre("mcp__exa__crawl", {}, agent_type="coder", agent_id="c1")) is None
    guard.pre(pre("multi_agent_v1wait_agent", {"ids": ["c1"]}, agent_type="python-engineer",
                  agent_id="pe1"))
    spawn(guard, "python-engineer", "pe1", "coder", "t3", child_id="c9")
    assert decision(remember(guard, "coder", "c9")) == "deny"


# ---------------------------------------------------------------- send_input / resume routing
def test_send_input_routed_against_the_spawn_tree(guard):
    main_spawn(guard, "python-engineer", "t1", "pe1")
    spawn(guard, "python-engineer", "pe1", "coder", "t2", child_id="c1")
    main_spawn(guard, "coder", "t3", "c2")
    assert send(guard, "send_input", "c1", "python-engineer", "pe1") is None      # own child
    assert send(guard, "send_input", "pe1", "coder", "c1") is None                # own parent
    out = send(guard, "send_input", "c2", "python-engineer", "pe1")               # not its child
    assert decision(out) == "deny" and "routing" in reason(out)
    out = send(guard, "send_input", "ghost", "python-engineer", "pe1")            # unknown id
    assert decision(out) == "deny"
    assert decision(guard.pre(pre("multi_agent_v1send_input", {"message": "m"}, agent_type=None))) \
        == "deny"
    assert send(guard, "send_input", "c2") is None                                # BlackCat's child


def test_resume_follows_the_row_and_close_only_own_children(guard):
    main_spawn(guard, "coder", "t1", "c1")
    main_spawn(guard, "python-engineer", "t2", "pe1")
    assert send(guard, "resume_agent", "c1", "python-engineer", "pe1") is None    # coder in its row
    out = send(guard, "close_agent", "c1", "python-engineer", "pe1")
    assert decision(out) == "deny"
    assert send(guard, "close_agent", "c1") is None


def test_spawn_tree_without_a_parsable_response_uses_subagent_start(guard):
    main_spawn(guard, "coder", "t1", "c1", response="spawned, but no id here")
    assert send(guard, "send_input", "c1") is None


@pytest.mark.parametrize("response", [{"result": {"agent_id": "c7"}}, '{"id": "c7"}',
                                      "agent_id: c7", [{"content": {"thread_id": "c7"}}]])
def test_spawn_response_shapes_parsed_defensively(guard, response):
    ti = {"agent_type": "coder", "message": "go"}
    guard.pre(pre("spawn_agent", ti, agent_type=None, tool_use_id="u7"))
    guard.observe("post_tool_use", event("post_tool_use", tool_name="spawn_agent", tool_input=ti,
                                         agent_type=None, tool_use_id="u7", tool_response=response))
    assert send(guard, "send_input", "c7") is None


# ---------------------------------------------------------------- caps
def test_tool_call_cap_per_agent(guard):
    for _ in range(6):                         # coder's max_tool_calls is 6 in the fixture
        assert guard.pre(bash("ls", agent_type="coder", agent_id="c1")) is None
    out = guard.pre(bash("ls", agent_type="coder", agent_id="c1"))
    assert decision(out) == "deny" and "6 tool calls" in reason(out)
    assert guard.pre(bash("ls", agent_type="coder", agent_id="c2")) is None


def test_mcp_caps_per_agent_and_session(tmp_path, monkeypatch):
    stack = Stack(tmp_path, guard_overrides={"caps": {"mcp_calls_per_agent": 2,
                                                      "mcp_calls_per_session": 3}})
    guard = Guard(stack, monkeypatch)
    call = lambda aid: guard.pre(pre("mcp__libdocs__x", {}, agent_type="python-engineer",
                                     agent_id=aid))
    assert call("a") is None and call("a") is None
    assert "mcp_calls_per_agent" in reason(call("a"))
    assert call("b") is None
    assert "mcp_calls_per_session" in reason(call("c"))


def test_spawn_cap_per_caller_per_prompt(tmp_path, monkeypatch):
    stack = Stack(tmp_path, guard_overrides={"caps": {"spawns_per_prompt": 2,
                                                      "spawns_per_prompt_by_type": {"blackcat": 1}}})
    guard = Guard(stack, monkeypatch)
    sp = lambda caller, aid: guard.pre(pre("spawn_agent", {"agent_type": "coder"}, agent_type=caller,
                                           agent_id=aid))
    assert sp("python-engineer", "p1") is None and sp("python-engineer", "p1") is None
    assert "fan-out cap" in reason(sp("python-engineer", "p1"))
    assert sp(None, None) is None and decision(sp(None, None)) == "deny"
    guard.observe("user_prompt_submit", event("user_prompt_submit", agent_type=None))
    assert sp(None, None) is None and sp("python-engineer", "p1") is None


def test_caps_hold_under_concurrent_processes(stack):
    """24 hook processes at once, through the sh stub, against an MCP cap of 10: exactly 10 pass."""
    stack.guard["caps"] = {"mcp_calls_per_agent": 10}
    stack.write_policy()
    ev = pre("mcp__libdocs__x", {"q": 1}, agent_type="python-engineer", agent_id="pe1")
    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        results = list(pool.map(lambda _: run_stub(stack, "pre_tool_use", ev), range(24)))
    assert all(rc == 0 for rc, _, _ in results), [e for _, _, e in results][:2]
    allowed = sum(1 for _, out, _ in results if out is None)
    assert allowed == 10
    state = json.loads((stack.state / "sessions" / "s-1" / "state.json").read_text())
    assert state["mcp_agent"]["a:pe1"] == 10 and state["calls"]["a:pe1"] == 10


# ---------------------------------------------------------------- computer-use lock
def test_one_agent_at_a_time_on_computer_use(guard):
    cu = lambda aid, sid="s-1": guard.pre(pre("mcp__computer-use__screenshot", {}, agent_type="designer",
                                              agent_id=aid, session_id=sid))
    assert cu("d1") is None and cu("d1") is None
    out = cu("d2")
    assert decision(out) == "deny" and "one agent at a time" in reason(out)
    assert decision(cu("d3", sid="s-2")) == "deny"           # across sessions too
    guard.observe("subagent_stop", event("subagent_stop", agent_id="d1", agent_type="designer"))
    assert cu("d2") is None
    guard.observe("session_end", event("session_end"))
    assert cu("d3", sid="s-2") is None


# ---------------------------------------------------------------- fail closed
def test_unreadable_event_denied(guard):
    rc, out = guard.run("pre_tool_use", b"{not json")
    assert rc == 0 and decision(out) == "deny"
    rc, out = guard.run("permission_request", b"[1, 2]")
    assert out["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def test_unreadable_policy_denied(tmp_path, monkeypatch):
    stack = Stack(tmp_path)
    (stack.policy_dir / "agents.json").write_text("{broken")
    guard = Guard(stack, monkeypatch)
    out = guard.pre(bash("ls"))
    assert decision(out) == "deny" and "policy cannot be read" in reason(out)
    stack.agents = {"schema": 1, "agents": {"coder": {"shell": "yes"}}, "blackcat": {}}
    stack.write_policy()
    assert decision(guard.pre(bash("ls"))) == "deny"


def test_internal_error_is_a_deny(guard, monkeypatch):
    def boom(*a, **k):
        raise ZeroDivisionError("boom")
    monkeypatch.setattr(guard.mod, "decide_pre", boom)
    monkeypatch.setattr(guard.mod, "decide_permission", boom)
    out = guard.pre(bash("ls"))
    assert decision(out) == "deny" and "internal error" in reason(out) and "boom" in reason(out)
    assert guard.perm(event("permission_request"))["hookSpecificOutput"]["decision"]["behavior"] \
        == "deny"


def test_state_lock_busy_is_a_deny(guard, monkeypatch):
    monkeypatch.setattr(guard.mod, "LOCK_WAIT_S", 0.05)
    import fcntl
    import os
    folder = guard.stack.state / "sessions" / "s-1"
    folder.mkdir(parents=True)
    fd = os.open(str(folder / ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        out = guard.pre(bash("ls"))
        assert decision(out) == "deny" and "lock is busy" in reason(out)
    finally:
        os.close(fd)


@pytest.mark.parametrize("mode", ["post_tool_use", "subagent_start", "subagent_stop",
                                  "user_prompt_submit", "session_start", "session_end"])
def test_observe_events_never_block(guard, monkeypatch, mode):
    monkeypatch.setattr(guard.mod, "observe", lambda ctx: 1 / 0)
    assert guard.run(mode, event(mode)) == (0, None)
    assert guard.run(mode, b"garbage") == (0, None)


def test_usage_errors_exit_2(guard):
    assert guard.mod.run(["bogus"], None, None) == 2
    assert guard.mod.run([], None, None) == 2


def test_self_test(stack):
    import subprocess
    p = subprocess.run([str(stack.bin_dir / "stack-python"), str(stack.guard_py), "--self-test"],
                       capture_output=True, text=True, env=stack.env(), timeout=60)
    assert p.returncode == 0, p.stdout + p.stderr
    assert p.stdout.count("ok  ") == 3
    assert not (stack.state / "sessions" / "self-test").exists()   # a throwaway state dir
    (stack.policy_dir / "guard.json").unlink()
    p = subprocess.run([str(stack.bin_dir / "stack-python"), str(stack.guard_py), "--self-test"],
                       capture_output=True, text=True, env=stack.env(), timeout=60)
    assert p.returncode == 1
