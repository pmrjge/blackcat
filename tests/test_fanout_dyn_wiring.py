"""Dynamic fan-out cap wired into the guard (dynamic fan-out plan, step 5b): STACK_FANOUT_DYN
off | shadow | enforce through agent_guard.py, with stack_fanout.py as the decision core.

Run: uv run --with pytest pytest -q tests/test_fanout_dyn_wiring.py
"""
import contextlib
import importlib.util
import json
import os
import statistics
import time
import uuid

import pytest

from guard_harness import GUARD, Env

SHIPPED_BY_TYPE = ("orchestrator=32,supreme-coder=6,main-coder=6,ninja-coder=5,researcher=4,"
                   "planner=8,plan-reviewer=8")
DYN_FILES = ("fanout-dyn", "fanout-dyn.jsonl", "fanout-dyn-events.jsonl")


def env(mode, **knobs):
    k = dict(dict(STACK_MAX_FANOUT_BY_TYPE=SHIPPED_BY_TYPE, CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=33),
             **knobs)
    if mode is not None:
        k["STACK_FANOUT_DYN"] = mode
    return Env(**k)


def allowed(r):
    assert r.rc == 0, r.stderr
    return r.decision.startswith("allow")


def log_lines(e, name="fanout-dyn.jsonl"):
    p = os.path.join(e.sdir(), name)
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def state(e, agent, kind):
    p = os.path.join(e.sdir(), "fanout-dyn", "%s.%s.json" % (agent, kind))
    return json.load(open(p)) if os.path.exists(p) else None


def write_plan(e, plan, agent="O1", atype="orchestrator", job="job1", tool="Write", path=None):
    """The agent's Write of .claude-work/<job>/plan.dag.json through the `budget` hook; returns the
    additionalContext ("" when none)."""
    content = plan if isinstance(plan, str) else json.dumps(plan)
    ti = {"file_path": path or os.path.join(e.tmp, ".claude-work", job, "plan.dag.json"),
          "content": content}
    if tool != "Write":
        ti = {"file_path": ti["file_path"], "old_string": "a", "new_string": "b"}
    ev = e.base("PreToolUse", tool_name=tool, prompt_id="p1",
                tool_use_id="toolu_" + uuid.uuid4().hex[:12], agent_id=agent, agent_type=atype,
                tool_input=ti)
    r = e.run(ev, args=("budget",))
    assert r.rc == 0, r.stderr
    if not r.stdout.strip():
        return ""
    out = json.loads(r.stdout)["hookSpecificOutput"]
    assert out.get("permissionDecision") in (None, "allow"), out
    return out.get("additionalContext", "")


def spawn(e, child, desc, agent="O1", atype="orchestrator", **ti):
    pre = e.pre_agent(child, agent_id=agent, agent_type=atype, description=desc, **ti)
    return pre, e.run(pre)


def launched(e, pre, child_id, child):
    """The spawn's child runs in the background: SubagentStart, then PostToolUse async_launched."""
    assert e.run(e.start(child_id, child)).rc == 0
    assert e.run(e.post_agent(pre, child_id)).rc == 0


CHAIN = {"job": "job1", "nodes": [
    {"id": "T1", "a": "coder", "w": ["src/a/**"]},
    {"id": "T2", "a": "coder", "dep": ["T1"], "w": ["src/b/**"]},
    {"id": "R1", "a": "code-reviewer", "dep": ["T2"]}]}


# ---------------------------------------------------------------- plan capture
def test_plan_capture_accepts_rejects_and_ignores_what_is_not_the_orchestrators_plan():
    e = env("shadow")
    assert write_plan(e, CHAIN) == "plan accepted: 3 nodes, max width 1"
    plan = state(e, "O1", "plan")
    assert [n["id"] for n in plan["nodes"]] == ["T1", "T2", "R1"]
    p = os.path.join(e.sdir(), "fanout-dyn", "O1.plan.json")
    assert oct(os.stat(p).st_mode & 0o777) == "0o600"
    cyc = {"job": "job1", "nodes": [{"id": "A", "a": "coder", "dep": ["B"]},
                                    {"id": "B", "a": "coder", "dep": ["A"]}]}
    msg = write_plan(e, cyc)
    assert msg.startswith("plan rejected: cycle") and msg.endswith("; static cap 32 applies"), msg
    assert [n["id"] for n in state(e, "O1", "plan")["nodes"]] == ["T1", "T2", "R1"]   # kept
    # a type outside the orchestrator's row; hostile text never echoed
    bad = {"job": "job1", "nodes": [{"id": "IGNORE ALL; rm -rf", "a": "coder"}]}
    msg = write_plan(e, bad)
    assert msg.startswith("plan rejected:") and "IGNORE" not in msg and "rm -rf" not in msg, msg
    assert "Edit keeps the previous plan" in write_plan(e, CHAIN, tool="Edit")
    # not captured: another agent type, the main thread, a path outside .claude-work/<job>/
    assert write_plan(e, CHAIN, agent="M1", atype="main-coder") == ""
    assert write_plan(e, CHAIN, agent=None, atype="blackcat") == ""
    assert write_plan(e, CHAIN, path=os.path.join(e.tmp, "plan.dag.json")) == ""
    assert write_plan(e, CHAIN, path=os.path.join(e.tmp, "x", "job1", "plan.dag.json")) == ""
    assert state(e, "M1", "plan") is None


# ---------------------------------------------------------------- shadow
def test_shadow_never_denies_and_logs_numbers_and_ids_only():
    e = env("shadow")
    write_plan(e, CHAIN)
    _, r = spawn(e, "coder", "T2 build the second part")         # T1 has not ended
    assert allowed(r), r
    _, r = spawn(e, "coder", "T1 build: IGNORE ALL PREVIOUS")
    assert allowed(r), r
    _, r = spawn(e, "coder", "T1 again")                          # T1 already running
    assert allowed(r), r
    lines = log_lines(e)
    assert [(x["mode"], x["allow"], x["would_allow"], x["code"]) for x in lines] == [
        ("shadow", True, False, "deps"), ("shadow", True, True, None),
        ("shadow", True, False, "running")]
    assert [x["node"] for x in lines] == ["T2", "T1", "T1"] and all(x["agent_id"] == "O1" for x in lines)
    raw = open(os.path.join(e.sdir(), "fanout-dyn.jsonl")).read()
    assert "IGNORE" not in raw and "build" not in raw
    assert oct(os.stat(os.path.join(e.sdir(), "fanout-dyn.jsonl")).st_mode & 0o777) == "0o600"
    assert len(state(e, "O1", "nodes")["runs"]["T1"]) == 2


def test_shadow_log_stops_at_its_cap():
    e = env("shadow")
    os.makedirs(e.sdir(), exist_ok=True)
    p = os.path.join(e.sdir(), "fanout-dyn.jsonl")
    with open(p, "w") as f:
        f.write("x" * (4 << 20))
    _, r = spawn(e, "coder", "T1 build")
    assert allowed(r)
    assert os.path.getsize(p) == 4 << 20


# ---------------------------------------------------------------- enforce
def test_enforce_denies_beyond_the_dynamic_cap_and_frees_the_node_when_its_child_ends():
    e = env("enforce")
    write_plan(e, CHAIN)
    _, r = spawn(e, "coder", "T2 build")
    assert r.decision == "deny" and r.reason.startswith("Dynamic fan-out (deps): node T2 waits on T1"), r
    assert "ready nodes: T1." in r.reason
    pre, r = spawn(e, "coder", "T1 build")
    assert allowed(r), r
    _, r = spawn(e, "main-coder", "T1 escalate")                  # T1's run is live (lease)
    assert r.decision == "deny" and r.reason.startswith("Dynamic fan-out (running): node T1"), r
    launched(e, pre, "K1", "coder")
    assert state(e, "O1", "nodes")["runs"]["T1"][0]["child_id"] == "K1"
    _, r = spawn(e, "coder", "T2 build")                          # T1 still live (child K1)
    assert r.decision == "deny" and "(deps)" in r.reason, r
    assert e.run(e.stop("K1", "coder")).rc == 0
    run = state(e, "O1", "nodes")["runs"]["T1"][0]
    assert run["t_end"] is not None and run["outcome"] == "finish"
    _, r = spawn(e, "coder", "T2 build")
    assert allowed(r), r
    # a refused spawn holds no lease and leaves no run
    assert sorted(state(e, "O1", "nodes")["runs"]) == ["T1", "T2"]
    # unplanned spawns pass the plan terms (slack) and the window is not enforced by default
    _, r = spawn(e, "verifier", "check things")
    assert allowed(r), r


def test_enforce_never_allows_what_the_static_cap_refuses():
    e = env("enforce", STACK_MAX_FANOUT_BY_TYPE="orchestrator=1")
    write_plan(e, {"job": "j", "nodes": [{"id": "A", "a": "coder"}, {"id": "B", "a": "coder"}]})
    _, r = spawn(e, "coder", "A build")
    assert allowed(r), r
    _, r = spawn(e, "coder", "B build")                           # B is ready, static cap 1 is full
    assert r.decision == "deny" and r.reason.startswith("Fan-out limit:"), r
    assert [x["node"] for x in log_lines(e)] == ["A"]             # the dynamic layer never ran


# ---------------------------------------------------------------- off
@pytest.mark.parametrize("mode", [None, "off", "OFF "])
def test_off_is_todays_behaviour_and_writes_nothing(mode):
    e = env(mode, STACK_FANOUT_DYN_ENFORCE="node,deps,conflict,budget,aimd", STACK_FANOUT_DYN_W0="1")
    assert write_plan(e, CHAIN) == ""
    for desc in ("T2 build", "T1 build", "T1 again", "T1 more"):
        _, r = spawn(e, "coder", desc)
        assert allowed(r), r
    assert not any(os.path.exists(os.path.join(e.sdir(), f)) for f in DYN_FILES)


def test_policy_off_turns_it_off():
    e = env("enforce", STACK_POLICY="off")
    assert write_plan(e, CHAIN) == ""
    _, r = spawn(e, "coder", "T2 build")
    assert allowed(r)
    assert not any(os.path.exists(os.path.join(e.sdir(), f)) for f in DYN_FILES)


# ---------------------------------------------------------------- scope
def test_only_orchestrators_are_in_scope_never_the_main_thread_or_blackcat():
    e = env("enforce", STACK_FANOUT_DYN_TYPES="orchestrator,blackcat,main",
            STACK_FANOUT_DYN_ENFORCE="aimd", STACK_FANOUT_DYN_W0="1")
    for _ in range(3):
        assert allowed(e.run(e.pre_agent("scout", agent_type="blackcat")))
    for _ in range(3):
        assert allowed(e.run(e.pre_agent("coder", agent_id="M1", agent_type="main-coder")))
    assert log_lines(e) == []
    # the orchestrator is: W0=1 refuses its second running child (aimd enforced here)
    pre, r = spawn(e, "coder", "x one")
    assert allowed(r)
    _, r = spawn(e, "coder", "x two")
    assert r.decision == "deny" and r.reason.startswith("Dynamic fan-out (window): window 1"), r
    assert [x["agent_type"] for x in log_lines(e)] == ["orchestrator", "orchestrator"]


# ---------------------------------------------------------------- D1: aborted runs
def load_guard():
    spec = importlib.util.spec_from_file_location("agent_guard_dyn", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_spawn_a_later_gate_refuses_leaves_no_run_and_the_node_stays_free():
    """SUPREME_ONCE_REASON after fanout_acquire recorded the run: rollback() removes it, so the
    next spawn for the node is allowed by the fan-out layer."""
    g = load_guard()
    e = env("enforce", SUPREME_ONCE_PER_SESSION="1", SUPREME_AFTER_NINJA="0",
            SUPREME_SPAWNERS="orchestrator")
    write_plan(e, {"job": "j", "nodes": [{"id": "S1", "a": "ninja-coder"}]})
    os.makedirs(e.sdir(), exist_ok=True)
    open(os.path.join(e.sdir(), g.SUPREME_ONCE), "w").write("toolu_earlier")
    _, r = spawn(e, "supreme-coder", "S1 last resort")
    assert r.decision == "deny" and r.reason == g.SUPREME_ONCE_REASON, r
    assert log_lines(e)[-1]["allow"] is True                       # the fan-out layer allowed it
    assert (state(e, "O1", "nodes") or {}).get("runs", {}).get("S1") in (None, [])
    assert not os.listdir(os.path.join(e.sdir(), "fanout", "O1"))
    _, r = spawn(e, "ninja-coder", "S1 retry")
    assert allowed(r), r
    assert len(state(e, "O1", "nodes")["runs"]["S1"]) == 1


def test_a_failed_agent_call_removes_its_run():
    e = env("enforce")
    write_plan(e, CHAIN)
    pre, r = spawn(e, "coder", "T1 build")
    assert allowed(r)
    assert e.run(e.fail_agent(pre)).rc == 0
    assert state(e, "O1", "nodes")["runs"].get("T1") in (None, [])
    _, r = spawn(e, "coder", "T1 build")
    assert allowed(r), r


# ---------------------------------------------------------------- K_sess with the dynamic layer
def test_17_foreground_children_and_the_18th_is_allowed():
    e = env("enforce", STACK_FANOUT_SESSION="enforce")
    for i in range(17):
        _, r = spawn(e, "coder", "x %d" % i)
        assert allowed(r), r
        assert e.run(e.start("K%d" % i, "coder")).rc == 0
    _, r = spawn(e, "coder", "x 17")
    assert allowed(r), r
    sess = [json.loads(x) for x in open(os.path.join(e.sdir(), "fanout-session.jsonl"))]
    assert sess[-1]["n"] == 17 and not sess[-1]["full"]
    last = log_lines(e)[-1]
    assert last["allow"] is True and last["terms"]["sess"] == 17 + (33 - 17)
    # past W0=8 running children the window term would refuse (shadow-only term by default)
    assert last["would_allow"] is False and last["code"] == "window" and last["n"] == 17


# ---------------------------------------------------------------- resume
def test_resume_goes_through_the_dynamic_decision():
    for mode, want in (("shadow", "allow"), ("enforce", "deny")):
        e = env(mode, STACK_FANOUT_DYN_ENFORCE="aimd", STACK_FANOUT_DYN_W0="1")
        pre, r = spawn(e, "coder", "x live")
        assert allowed(r)
        launched(e, pre, "K1", "coder")
        pre = e.pre_agent("scout", agent_id="O1", agent_type="orchestrator")
        assert e.run(e.start("K2", "scout")).rc == 0
        assert e.run(e.stop("K2", "scout")).rc == 0
        assert e.run(e.post_agent(pre, "K2", status="completed")).rc == 0
        r = e.run(e.send("K2", agent_id="O1", agent_type="orchestrator"))
        assert r.decision.split("(")[0] == want, (mode, r)
        last = log_lines(e)[-1]
        assert (last["kind"], last["mode"], last["would_allow"], last["code"]) == (
            "resume", mode, False, "window")
        if want == "deny":
            assert r.reason.startswith("Dynamic fan-out (window)"), r
            assert not [f for f in os.listdir(os.path.join(e.sdir(), "fanout", "O1"))
                        if f.startswith("resume-")]


# ---------------------------------------------------------------- AIMD
def test_stop_failure_rate_limit_halves_the_window():
    e = env("shadow")
    pre, r = spawn(e, "coder", "x one")
    assert allowed(r)
    launched(e, pre, "K1", "coder")
    ev = e.base("StopFailure", agent_id="K1", agent_type="coder", error="rate_limit")
    assert e.run(ev).rc == 0
    assert state(e, "O1", "aimd")["w"] == 4                        # W0 8 x beta_rl 0.5
    ev = log_lines(e, "fanout-dyn-events.jsonl")[-1]
    assert (ev["event"], ev["error"], ev["action"], ev["w"]) == ("stop_failure", "rate_limit", "cut", 4)
    run = state(e, "O1", "nodes")["unplanned"]
    assert run == [] or run[0]["outcome"] == "sf_rate_limit"


# ---------------------------------------------------------------- R3: failures are static
def test_an_exception_or_a_lock_timeout_is_the_static_decision(tmp_path, monkeypatch):
    g = load_guard()
    monkeypatch.setenv("STACK_FANOUT_DYN", "enforce")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))
    monkeypatch.delenv("STACK_POLICY", raising=False)
    d = str(tmp_path)
    ev = {"session_id": "s1", "tool_use_id": "toolu_1", "agent_id": "O1",
          "tool_input": {"subagent_type": "coder", "description": "T1 x"}}

    def boom(*_a, **_k):
        raise RuntimeError("injected")

    def decide():
        return g.dyn_spawn(d, ev, "O1", "orchestrator", "coder", 32, 40, time.time(), {},
                           "toolu_1", {})
    # control: n = 40 >= the static cap 32 is refused by the module's ceil term when nothing fails
    assert decide().startswith("Dynamic fan-out (ceil)")
    monkeypatch.setattr(g, "live_leases", boom)
    assert decide() is None
    assert g.dyn_resume(d, ev, "O1", "orchestrator", "coder", 32, 40, time.time(), {}, {}) is None
    monkeypatch.setattr(g, "live_leases", lambda *_a, **_k: [])
    mod = g.fanout_dyn_module()
    monkeypatch.setattr(mod, "dyn_decision", boom)
    assert decide() is None

    @contextlib.contextmanager
    def stuck(*_a, **_k):
        raise g.MutexTimeout("injected")
        yield  # unreachable: makes this a generator for contextmanager
    monkeypatch.setattr(g, "mutex", stuck)
    os.makedirs(os.path.join(d, "fanout-dyn"), exist_ok=True)       # the control wrote nodes
    with open(os.path.join(d, "fanout-dyn", "O1.nodes.json"), "w") as f:
        json.dump({"runs": {"T1": [{"tid": "toolu_1", "child_id": None}]}}, f)
    assert g.dyn_remove_run(d, "O1", "toolu_1") is False          # no raise
    g.dyn_spawn_failed(d, dict(ev, hook_event_name="PostToolUseFailure",
                               error="Concurrent subagent limit reached"), "O1", "toolu_1")
    g.dyn_child_end(d, dict(ev, hook_event_name="StopFailure", error="rate_limit"), "K1")


def test_a_corrupt_state_file_is_the_static_decision():
    e = env("enforce")
    write_plan(e, CHAIN)
    os.makedirs(os.path.join(e.sdir(), "fanout-dyn"), exist_ok=True)
    for f, body in (("O1.nodes.json", '{"runs": {"T2": "x"}, "breaker": 7}'),
                    ("O1.aimd.json", '{"w": "lots"}')):
        with open(os.path.join(e.sdir(), "fanout-dyn", f), "w") as fh:
            fh.write(body)
    _, r = spawn(e, "coder", "T1 build")
    assert allowed(r), r


# ---------------------------------------------------------------- hostile plans
def hostile_plan():
    """32 nodes of long multi-wildcard globs that all overlap, just under the 64 KiB limit."""
    glob = "/".join(["[a-m]*?*[!x]*"] * 18)[:210]
    plan = {"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder", "w": [glob + str(k) for k in range(7)],
                                   "rd": ["**/" + glob[:40]]} for i in range(32)]}
    assert 48 << 10 < len(json.dumps(plan)) < 64 << 10
    return plan


def timed(e, ev, args=()):
    t = time.perf_counter()
    r = e.run(ev, args=args)
    return r, time.perf_counter() - t


def test_hostile_plans_do_not_slow_the_hook_or_deny():
    for bad in ("[" * 20000 + "]" * 20000, "x" * (70 << 10), '{"job": "j", "nodes": ' + "[" * 50 + "]" * 50 + "}"):
        e = env("enforce")
        assert write_plan(e, bad).startswith("plan rejected:")
    e = env("enforce")
    assert write_plan(e, hostile_plan()).startswith("plan accepted: 32 nodes")
    for i in range(8):                       # 8 live nodes whose globs all overlap (conflict not enforced)
        _, r = spawn(e, "coder", "N%d go" % i)
        assert allowed(r), r
    off = env("off")
    for i in range(8):
        assert allowed(spawn(off, "coder", "N%d go" % i)[1])
    on_t, off_t = [], []
    for i in range(5):
        r, t = timed(e, e.pre_agent("coder", agent_id="O1", agent_type="orchestrator",
                                    description="N%d go" % (8 + i)))
        assert allowed(r), r
        on_t.append(t)
        r, t = timed(off, off.pre_agent("coder", agent_id="O1", agent_type="orchestrator",
                                        description="N%d go" % (8 + i)))
        assert allowed(r), r
        off_t.append(t)
    assert statistics.median(on_t) - statistics.median(off_t) < 0.05, (on_t, off_t)
