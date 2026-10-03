"""Session slot guard K_sess (dynamic fan-out plan, step 3 / D0): STACK_FANOUT_SESSION=off|shadow|enforce
against CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS, for every caller including the main thread.

Run: uv run --with pytest pytest -q tests/test_fanout_session.py
"""
import fcntl
import importlib.util
import json
import os
import time

import pytest

from guard_harness import GUARD, Env

# the shipped per-type table (guard_harness's BASELINE lowers it for older mechanics tests)
SHIPPED_BY_TYPE = ("orchestrator=32,supreme-coder=6,main-coder=6,ninja-coder=5,researcher=4,"
                   "planner=8,plan-reviewer=8")
SESSION_TEXT = "Session limit: %d of %d subagent slots in use (CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS)."


def env(mode, maxc=33, **knobs):
    k = dict(STACK_MAX_FANOUT_BY_TYPE=SHIPPED_BY_TYPE, CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=maxc, **knobs)
    if mode is not None:
        k["STACK_FANOUT_SESSION"] = mode
    return Env(**k)


def log_lines(e):
    p = os.path.join(e.sdir(), "fanout-session.jsonl")
    if not os.path.exists(p):
        return []
    with open(p) as f:
        return [json.loads(x) for x in f if x.strip()]


def leases(e, caller):
    folder = os.path.join(e.sdir(), "fanout", caller)
    return sorted(f[:-5] for f in os.listdir(folder)) if os.path.isdir(folder) else []


def allowed(r):
    assert r.rc == 0, r.stderr
    return r.decision.startswith("allow")


def bg_child(e, child_id, child, caller=None, caller_type="blackcat"):
    """A child running in the background: SubagentStart, then PostToolUse async_launched (registry
    record with the call's tool_use_id, no lease)."""
    pre = e.pre_agent(child, agent_id=caller, agent_type=caller_type)
    assert e.run(e.start(child_id, child)).rc == 0
    assert e.run(e.post_agent(pre, child_id)).rc == 0


def fg_child(e, child_id, child, caller=None, caller_type="blackcat"):
    """A foreground child: its spawn allowed (a live lease), then its SubagentStart record (no
    tool_use_id)."""
    r = e.run(e.pre_agent(child, agent_id=caller, agent_type=caller_type))
    assert allowed(r), r
    assert e.run(e.start(child_id, child)).rc == 0


def finished_child(e, child_id, child, caller=None, caller_type="blackcat"):
    """A child that ran in the foreground, stopped and reported back (resumable)."""
    pre = e.pre_agent(child, agent_id=caller, agent_type=caller_type)
    assert e.run(e.start(child_id, child)).rc == 0
    assert e.run(e.stop(child_id, child)).rc == 0
    assert e.run(e.post_agent(pre, child_id, status="completed")).rc == 0


# ---------------------------------------------------------------- (i) no double counting
def test_foreground_children_count_once_lease_not_subagentstart_record():
    """MAXC 33: 17 foreground children, each with a live lease and a SubagentStart record (no
    tool_use_id). The 18th spawn is allowed and sees n_sess = 17, not 34."""
    e = env("enforce")
    for i in range(17):
        fg_child(e, "K%d" % i, "coder", caller="O1", caller_type="orchestrator")
    assert len(leases(e, "O1")) == 17
    assert all(e.reg("K%d" % i) and not e.reg("K%d" % i).get("tool_use_id") for i in range(17))
    r = e.run(e.pre_agent("coder", agent_id="O1", agent_type="orchestrator"))
    assert allowed(r), r
    last = log_lines(e)[-1]
    assert (last["kind"], last["mode"], last["n"], last["maxc"], last["full"]) == ("spawn", "enforce", 17, 33, False)
    assert last["agent_id"] == "O1" and last["agent_type"] == "orchestrator"
    # the count is exact: with MAXC 18 the 18 live leases leave no slot for a 19th
    r = e.run(e.pre_agent("coder", agent_id="O1", agent_type="orchestrator"),
              extra={"CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS": "18"})
    assert r.decision == "deny" and r.reason.startswith(SESSION_TEXT % (18, 18)), r


# ---------------------------------------------------------------- (ii) every caller, idle included
def build_33(e):
    """8 BlackCat children in the background (6 main-coders, a researcher, a coder) and 25
    children of the main-coders: 33 live. M1..M5's 23 children run in the background (M1's three
    idle for 2 h, which the per-parent count drops and the session count keeps); M6's 2 are
    foreground leases."""
    mcs = ["M%d" % i for i in range(1, 7)]
    for m in mcs:
        bg_child(e, m, "main-coder")
    bg_child(e, "R1", "researcher")
    bg_child(e, "C1", "coder")
    for m, k in zip(mcs[:5], (5, 5, 5, 4, 4)):
        for j in range(k):
            bg_child(e, "%s-%d" % (m, j), "coder", caller=m, caller_type="main-coder")
    for j in range(3):
        e.age_reg("M1-%d" % j, 7200)
    for j in range(2):
        fg_child(e, "M6-%d" % j, "coder", caller="M6", caller_type="main-coder")
    return mcs


def test_main_coder_under_its_own_cap_is_refused_at_the_session_limit():
    e = env("enforce")
    build_33(e)
    assert log_lines(e)[-1]["n"] == 32           # M6's second child was the 33rd slot
    r = e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder"))
    assert r.decision == "deny" and r.reason == (
        SESSION_TEXT % (33, 33) + " Wait for a task notification before spawning more, or do this part yourself."), r
    assert leases(e, "M6") and len(leases(e, "M6")) == 2          # a refused call leaves no lease
    # M1's three idle children still hold session slots ("33", not "30"), though M1's own count
    # (cap 6) drops them
    r = e.run(e.pre_agent("coder", agent_id="M1", agent_type="main-coder"))
    assert r.decision == "deny" and "Session limit: 33 of 33" in r.reason, r
    # the main thread too
    r = e.run(e.pre_agent("scout", agent_type="blackcat"))
    assert r.decision == "deny" and "Session limit: 33 of 33" in r.reason, r
    assert leases(e, "main") == []
    # one child stops: one slot frees
    assert e.run(e.stop("M2-0", "coder")).rc == 0
    assert allowed(e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder")))
    r = e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder"))
    assert r.decision == "deny" and "Session limit: 33 of 33" in r.reason, r


@pytest.mark.parametrize("mode", ["shadow", None, "bogus"])
def test_shadow_counts_and_logs_but_never_denies(mode):
    """shadow (also the default, and what an unknown value means) gives today's decisions."""
    e = env(mode)
    build_33(e)
    for _ in range(2):
        assert allowed(e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder")))
    assert allowed(e.run(e.pre_agent("scout", agent_type="blackcat")))
    tail = log_lines(e)[-3:]
    assert [x["n"] for x in tail] == [33, 34, 35] and all(x["full"] and x["mode"] == "shadow" for x in tail)
    # M6's own cap (6) still applies as today: 4 children now, 2 more, then the fan-out limit
    for _ in range(2):
        assert allowed(e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder")))
    r = e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder"))
    assert r.decision == "deny" and r.reason.startswith("Fan-out limit:"), r


def test_off_is_todays_behaviour_no_lock_no_count_no_log():
    e = env("off")
    build_33(e)
    assert log_lines(e) == []
    for _ in range(2):
        assert allowed(e.run(e.pre_agent("coder", agent_id="M6", agent_type="main-coder")))
    # the main thread's spawn takes no lock: a stuck fanout mutex does not delay it
    fd = os.open(os.path.join(e.sdir(), "fanout.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        t0 = time.monotonic()
        assert allowed(e.run(e.pre_agent("scout", agent_type="blackcat")))
        assert time.monotonic() - t0 < 4.0
    finally:
        os.close(fd)
    assert len(leases(e, "main")) == 1 and log_lines(e) == []


def test_policy_off_turns_the_guard_off():
    e = env("enforce", maxc=1, STACK_POLICY="off")
    bg_child(e, "M1", "main-coder")
    assert allowed(e.run(e.pre_agent("coder", agent_type="blackcat")))
    assert log_lines(e) == []


def test_a_stuck_lock_gives_the_main_thread_todays_lock_free_decision():
    """R3: when only the session guard wanted the lock, a lock timeout is the static decision
    (allowed, lease written), never a refusal."""
    e = env("enforce", maxc=1)
    bg_child(e, "M1", "main-coder")            # the session is full
    fd = os.open(os.path.join(e.sdir(), "fanout.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        r = e.run(e.pre_agent("scout", agent_type="blackcat"))
    finally:
        os.close(fd)
    assert allowed(r) and "timed out" in r.stderr, r
    assert len(leases(e, "main")) == 1


# ---------------------------------------------------------------- (iii) resumes
def resumable(e):
    """MAXC 3: one live background child of BlackCat and four finished ones."""
    bg_child(e, "L1", "main-coder")
    for i in range(4):
        finished_child(e, "X%d" % i, "scout")


def test_parallel_main_thread_resumes_respect_the_session_limit():
    e = env("enforce", maxc=3)
    resumable(e)
    xs = ["X%d" % i for i in range(4)]
    res = e.run_many([e.send(x, agent_type="blackcat") for x in xs])
    assert sorted(r.decision.split("(")[0] for r in res) == ["allow", "allow", "deny", "deny"], res
    assert all(r.reason == SESSION_TEXT % (3, 3) + " Wait for a task notification, then resume it."
               for r in res if r.decision == "deny")
    assert len(leases(e, "main")) == 2 and all(x.startswith("resume-") for x in leases(e, "main"))
    # the two reservations hold their slots: a new spawn is refused too
    r = e.run(e.pre_agent("scout", agent_type="blackcat"))
    assert r.decision == "deny" and "Session limit: 3 of 3" in r.reason, r
    # a resumed agent's SubagentStart turns its reservation into a live background child: same count
    ok = [x for x, r in zip(xs, res) if allowed(r)]
    assert e.run(e.start(ok[0], "scout")).rc == 0
    assert len(leases(e, "main")) == 1 and e.reg(ok[0]).get("bg") is True
    r = e.run(e.send([x for x in xs if x not in ok][0], agent_type="blackcat"))
    assert r.decision == "deny" and "Session limit: 3 of 3" in r.reason, r
    # one stops: the refused resume now fits
    assert e.run(e.stop("L1", "main-coder")).rc == 0
    assert allowed(e.run(e.send([x for x in xs if x not in ok][0], agent_type="blackcat")))


def test_main_thread_resumes_shadow_allows_all_and_off_reserves_nothing():
    e = env("shadow", maxc=3)
    resumable(e)
    res = e.run_many([e.send("X%d" % i, agent_type="blackcat") for i in range(4)])
    assert all(allowed(r) for r in res), res
    assert sorted(x["n"] for x in log_lines(e) if x["kind"] == "resume") == [1, 2, 3, 4]
    e = env("off", maxc=3)
    resumable(e)
    res = e.run_many([e.send("X%d" % i, agent_type="blackcat") for i in range(4)])
    assert all(allowed(r) for r in res), res
    assert leases(e, "main") == [] and log_lines(e) == []


def test_subagent_resume_checks_the_session_before_its_own_cap():
    e = env("enforce", maxc=2)
    bg_child(e, "M1", "main-coder")
    finished_child(e, "K1", "scout", caller="M1", caller_type="main-coder")
    bg_child(e, "C1", "coder")                 # 2 of 2 slots: M1 and C1
    r = e.run(e.send("K1", agent_id="M1", agent_type="main-coder"))
    assert r.decision == "deny" and "Session limit: 2 of 2" in r.reason, r
    assert leases(e, "M1") == []


# ---------------------------------------------------------------- unit: the count fails to static
def load_guard():
    spec = importlib.util.spec_from_file_location("agent_guard_ksess", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_failing_count_is_the_static_decision(tmp_path, monkeypatch):
    g = load_guard()

    def boom(*_a, **_k):
        raise RuntimeError("injected")
    monkeypatch.setattr(g, "session_slots", boom)
    assert g.session_check(str(tmp_path), {}, time.time(), {}, ("enforce", 1), "spawn") is None
    assert not (tmp_path / "fanout-session.jsonl").exists()


def test_session_guard_modes(monkeypatch):
    g = load_guard()
    for k in ("STACK_POLICY", "STACK_FANOUT_SESSION", "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS"):
        monkeypatch.delenv(k, raising=False)
    assert g.session_guard() == ("shadow", 20)
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "33")
    assert g.session_guard() == ("shadow", 33)
    monkeypatch.setenv("STACK_FANOUT_SESSION", " Enforce ")
    assert g.session_guard() == ("enforce", 33)
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "0")
    assert g.session_guard() is None
    monkeypatch.setenv("CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS", "33")
    monkeypatch.setenv("STACK_POLICY", "off")
    assert g.session_guard() is None
    monkeypatch.delenv("STACK_POLICY")
    monkeypatch.setenv("STACK_FANOUT_SESSION", "off")
    assert g.session_guard() is None
