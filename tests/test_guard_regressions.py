"""Regression tests for the 2026-09-26 hook review (liveness, god-coder singleton, id joins).
Run: uv run --python 3.12 --with pytest pytest -q tests/test_guard_regressions.py
GUARD=/path/to/agent_guard.py points them at another copy of the hook.
"""
import os
import time

import pytest

from guard_harness import Env

GOD = "god-coder"


def spawn_god(e, cid="G1", caller=None, ctype=None, prompt="q1", **ti):
    pre = e.pre_agent(GOD, agent_id=caller, agent_type=ctype or ("router" if not caller else "main-coder"),
                      prompt=prompt, **ti)
    r = e.run(pre)
    if r.decision.startswith("allow"):
        e.run(e.start(cid, GOD))
        e.run(e.post_agent(pre, cid))
    return r


def test_f1_god_lock_kept_while_holder_waits_for_its_children():
    e = Env()
    spawn_god(e)
    pre = e.pre_agent("main-coder", agent_id="G1", agent_type=GOD)
    e.run(pre)
    e.run(e.start("SC1", "main-coder"))
    e.run(e.post_agent(pre, "SC1"))
    e.sub_transcript("G1", age=960)
    e.sub_transcript("SC1", age=5)
    e.age_lock(960)
    assert e.run(e.pre_agent(GOD, agent_id="SC1", agent_type="main-coder")).decision == "deny"
    assert e.lock()["holder"] == "G1"


def test_f1_subagentstop_of_old_holder_does_not_free_other_callers_lease():
    e = Env()
    spawn_god(e)
    e.sub_transcript("G1", age=901)
    e.age_lock(901)
    assert e.run(e.pre_agent(GOD, agent_id="SC", agent_type="main-coder")).decision.startswith("allow")
    e.run(e.stop("G1", GOD))
    assert e.lock() and e.lock()["by"] == "SC"


def test_f2_taskstop_releases_god_lock():
    e = Env()
    spawn_god(e)
    e.run(e.base("PostToolUse", tool_name="TaskStop", tool_use_id="toolu_x",
                 tool_input={"task_id": "G1"}, tool_response={"task_id": "G1", "task_type": "local_agent"}))
    assert e.lock() is None


def test_f2_stopfailure_releases_god_lock():
    e = Env()
    spawn_god(e)
    e.run(e.base("StopFailure", agent_id="G1", agent_type=GOD, error="rate_limit"))
    assert e.lock() is None


def test_f3_refused_resume_expires_like_pending():
    e = Env()
    spawn_god(e, cid="GA")
    e.run(e.stop("GA", GOD, transcript=e.sub_transcript("GA", age=0)))
    assert e.run(e.send("GA")).decision.startswith("allow")
    e.age_reg("GA", 700, keys=("spawned", "started", "stopped"))
    e.sub_transcript("GA", age=700)
    e.age_lock(121)
    assert e.run(e.pre_agent(GOD, agent_id="SC", agent_type="main-coder")).decision.startswith("allow")


def test_f3_name_holder_expires():
    e = Env()
    pre = e.pre_agent(GOD, agent_type="router", name="deep fix")
    e.run(pre)
    e.run(e.fail_agent(pre))
    e.run(e.send("deep fix"))
    assert e.lock()["holder"] == "name:deep-fix"
    e.age_lock(121)
    assert e.run(e.pre_agent(GOD, agent_id="SC", agent_type="main-coder")).decision.startswith("allow")


def test_f4_no_double_count_while_post_tool_use_runs():
    e = Env(STACK_MAX_FANOUT=2)
    pre = e.pre_agent("coder", agent_id="SC", agent_type="main-coder")
    e.run(pre)
    p = e.spawn(e.post_agent(pre, "A1"), patch={"fanout_release": {"before": 1.0}})
    time.sleep(0.4)
    r = e.run(e.pre_agent("coder", agent_id="SC", agent_type="main-coder"))
    p.wait()
    assert r.decision.startswith("allow"), r


def test_f5_no_running_lock_for_an_already_stopped_god_coder():
    e = Env()
    pre = e.pre_agent(GOD, agent_id="SC", agent_type="main-coder")
    e.run(pre)
    e.run(e.start("G1", GOD))
    p = e.spawn(e.post_agent(pre, "G1"), patch={"god_confirm": {"before": 1.0}})
    time.sleep(0.4)
    e.run(e.stop("G1", GOD, transcript=e.sub_transcript("G1", age=0)))
    p.wait()
    assert e.lock() is None


@pytest.mark.parametrize("spelling", ["GodCoder", "god.coder", "god--coder", "GOD_CODER"])
def test_f6_all_spellings_of_god_coder_take_the_lock(spelling):
    e = Env()
    spawn_god(e, caller="SC")
    assert e.run(e.pre_agent(spelling)).decision == "deny"


def test_f7_remote_isolation_denied():
    e = Env()
    assert e.run(e.pre_agent("coder", agent_type="router", isolation="remote")).decision == "deny"
    assert e.run(e.pre_agent("coder", agent_type="router", isolation="worktree", prompt="q2")).decision.startswith("allow")


def test_f8_internal_subagentstop_creates_no_registry_entry():
    e = Env()
    e.run(e.stop("int-1", "router"))
    assert not os.path.isdir(os.path.join(e.sdir(), "agents")) or not os.listdir(os.path.join(e.sdir(), "agents"))


def test_f9_prefixed_hook_ids_join_with_tool_response_ids():
    e = Env()
    pre = e.pre_agent("coder", agent_type="router")
    e.run(pre)
    e.run(e.post_agent(pre, "a4d2c8f1"))
    e.run(e.start("agent-a4d2c8f1", "coder"))
    e.run(e.stop("agent-a4d2c8f1", "coder"))
    assert e.reg("a4d2c8f1").get("stopped")


# ---------------------------------------------------------------- L7: SendMessage resumes
def spawned(e, child, cid, caller=None, ctype=None, name=None):
    ti = {"name": name} if name else {}
    pre = e.pre_agent(child, agent_id=caller, agent_type=ctype or ("router" if not caller else None), **ti)
    r = e.run(pre)
    assert r.decision.startswith("allow"), r
    e.run(e.start(cid, child))
    e.run(e.post_agent(pre, cid))
    return cid


def test_l7_resuming_a_finished_agent_follows_the_spawn_policy():
    e = Env()
    spawned(e, "orchestrator", "O1")
    spawned(e, "security-auditor", "SA1", caller="O1", ctype="orchestrator", name="audit")
    spawned(e, "coder", "C1", caller="O1", ctype="orchestrator")
    # running target: a message, not a resume
    assert e.run(e.send("SA1", agent_id="C1", agent_type="coder")).decision.startswith("allow")
    e.run(e.stop("SA1", "security-auditor"))
    for to in ("SA1", "agent-SA1", "audit"):
        r = e.run(e.send(to, agent_id="C1", agent_type="coder"))
        assert r.decision == "deny" and "SendMessage policy" in r.reason, (to, r)
    # the caller type comes from the registry when the event lacks agent_type
    assert e.run(e.send("SA1", agent_id="C1")).decision == "deny"
    # its own parent may resume it; so may the main thread
    assert e.run(e.send("SA1", agent_id="O1", agent_type="orchestrator")).decision.startswith("allow")
    assert e.run(e.send("SA1")).decision.startswith("allow")
    # unknown targets and STACK_POLICY=off pass
    assert e.run(e.send("nobody", agent_id="C1", agent_type="coder")).decision.startswith("allow")
    assert e.run(e.send("SA1", agent_id="C1", agent_type="coder"),
                 extra={"STACK_POLICY": "off"}).decision.startswith("allow")


def test_l7_own_child_and_own_parent_may_be_resumed():
    e = Env()
    spawned(e, "main-coder", "SC1")
    spawned(e, "coder", "C2", caller="SC1", ctype="main-coder")
    e.run(e.stop("SC1", "main-coder"))
    assert e.run(e.send("SC1", agent_id="C2", agent_type="coder")).decision.startswith("allow")
    # a child whose type is outside the row (spawned while the policy was off) is still its own
    pre = e.pre_agent("writer", agent_id="C2", agent_type="coder")
    assert e.run(pre, extra={"STACK_POLICY": "off"}).decision.startswith("allow")
    e.run(e.start("W1", "writer"))
    e.run(e.post_agent(pre, "W1"))
    e.run(e.stop("W1", "writer"))
    assert e.run(e.send("W1", agent_id="C2", agent_type="coder")).decision.startswith("allow")
    # ...but not a finished writer someone else spawned
    spawned(e, "writer", "W2")
    e.run(e.stop("W2", "writer"))
    assert e.run(e.send("W2", agent_id="C2", agent_type="coder")).decision == "deny"


def test_r11_resuming_a_finished_child_counts_against_the_fanout_cap():
    e = Env(STACK_MAX_FANOUT=2, STACK_MAX_SELF_FANOUT=1)
    spawned(e, "main-coder", "SC")
    spawned(e, "coder", "C1", caller="SC", ctype="main-coder")
    spawned(e, "coder", "C2", caller="SC", ctype="main-coder")
    e.run(e.stop("C1", "coder"))
    spawned(e, "verifier", "V1", caller="SC", ctype="main-coder")     # SC: C2 + V1 running
    r = e.run(e.send("C1", agent_id="SC", agent_type="main-coder"))
    assert r.decision == "deny" and "Fan-out limit" in r.reason, r
    e.run(e.stop("V1", "verifier"))                                   # one slot free again
    assert e.run(e.send("C1", agent_id="SC", agent_type="main-coder")).decision.startswith("allow")
    # copies: a main-coder resuming a finished copy of itself while another copy runs
    spawned(e, "main-coder", "S2", caller="SC", ctype="main-coder")
    e.run(e.stop("S2", "main-coder"))
    e.run(e.stop("C2", "coder"))
    spawned(e, "main-coder", "S3", caller="SC", ctype="main-coder")
    r = e.run(e.send("S2", agent_id="SC", agent_type="main-coder"))
    assert r.decision == "deny" and "Copy limit" in r.reason, r
