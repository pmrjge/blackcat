"""Regression tests for the 2026-09-26 hook review (liveness, id joins).
Run: uv run --python 3.13 --with pytest pytest -q tests/test_guard_regressions.py
GUARD=/path/to/agent_guard.py points them at another copy of the hook.
"""
import os
import time

from guard_harness import Env

def test_f4_no_double_count_while_post_tool_use_runs():
    e = Env(STACK_MAX_FANOUT=2)
    pre = e.pre_agent("coder", agent_id="SC", agent_type="main-coder")
    e.run(pre)
    p = e.spawn(e.post_agent(pre, "A1"), patch={"fanout_release": {"before": 1.0}})
    time.sleep(0.4)
    r = e.run(e.pre_agent("coder", agent_id="SC", agent_type="main-coder"))
    p.wait()
    assert r.decision.startswith("allow"), r


def test_f7_remote_isolation_denied():
    e = Env()
    assert e.run(e.pre_agent("coder", agent_type="blackcat", isolation="remote")).decision == "deny"
    assert e.run(e.pre_agent("coder", agent_type="blackcat", isolation="worktree", prompt="q2")).decision.startswith("allow")


def test_f8_internal_subagentstop_creates_no_registry_entry():
    e = Env()
    e.run(e.stop("int-1", "blackcat"))
    assert not os.path.isdir(os.path.join(e.sdir(), "agents")) or not os.listdir(os.path.join(e.sdir(), "agents"))


def test_f9_prefixed_hook_ids_join_with_tool_response_ids():
    e = Env()
    pre = e.pre_agent("coder", agent_type="blackcat")
    e.run(pre)
    e.run(e.post_agent(pre, "a4d2c8f1"))
    e.run(e.start("agent-a4d2c8f1", "coder"))
    e.run(e.stop("agent-a4d2c8f1", "coder"))
    assert e.reg("a4d2c8f1").get("stopped")


# ---------------------------------------------------------------- L7: SendMessage resumes
def spawned(e, child, cid, caller=None, ctype=None, name=None):
    ti = {"name": name} if name else {}
    pre = e.pre_agent(child, agent_id=caller, agent_type=ctype or ("blackcat" if not caller else None), **ti)
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
    # running sibling: no peer-to-peer messages (routing scope, tests/test_send_routing.py)
    assert e.run(e.send("SA1", agent_id="C1", agent_type="coder")).decision == "deny"
    e.run(e.stop("SA1", "security-auditor"))
    for to in ("SA1", "agent-SA1", "audit"):
        r = e.run(e.send(to, agent_id="C1", agent_type="coder"))
        assert r.decision == "deny" and "SendMessage policy" in r.reason, (to, r)
    # the caller type comes from the registry when the event lacks agent_type
    assert e.run(e.send("SA1", agent_id="C1")).decision == "deny"
    # its own parent may resume it; so may the main thread
    assert e.run(e.send("SA1", agent_id="O1", agent_type="orchestrator")).decision.startswith("allow")
    assert e.run(e.send("SA1")).decision.startswith("allow")
    # an unknown target is refused; STACK_POLICY=off passes
    assert e.run(e.send("nobody", agent_id="C1", agent_type="coder")).decision == "deny"
    assert e.run(e.send("nobody", agent_id="C1", agent_type="coder"),
                 extra={"STACK_POLICY": "off"}).decision.startswith("allow")
    assert e.run(e.send("SA1", agent_id="C1", agent_type="coder"),
                 extra={"STACK_POLICY": "off"}).decision.startswith("allow")


def test_l7_own_child_may_be_resumed_a_finished_parent_never():
    """guard-land finding 5 (decided 2026-10-04): a child messages its parent while the parent
    runs; resuming a FINISHED parent starts new work upward and is refused."""
    e = Env()
    spawned(e, "main-coder", "SC1")
    spawned(e, "coder", "C2", caller="SC1", ctype="main-coder")
    assert e.run(e.send("SC1", agent_id="C2", agent_type="coder")).decision.startswith("allow")
    e.run(e.stop("SC1", "main-coder"))
    r = e.run(e.send("SC1", agent_id="C2", agent_type="coder"))
    assert r.decision == "deny" and "may not resume its parent" in r.reason, r
    assert e.run(e.send("SC1")).decision.startswith("allow")        # the main thread may
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
    e = Env(STACK_MAX_FANOUT=2)
    spawned(e, "main-coder", "SC")
    spawned(e, "coder", "C1", caller="SC", ctype="main-coder")
    spawned(e, "coder", "C2", caller="SC", ctype="main-coder")
    e.run(e.stop("C1", "coder"))
    spawned(e, "verifier", "V1", caller="SC", ctype="main-coder")     # SC: C2 + V1 running
    r = e.run(e.send("C1", agent_id="SC", agent_type="main-coder"))
    assert r.decision == "deny" and "Fan-out limit" in r.reason, r
    e.run(e.stop("V1", "verifier"))                                   # one slot free again
    assert e.run(e.send("C1", agent_id="SC", agent_type="main-coder")).decision.startswith("allow")
    # the resume holds that slot from the SendMessage on, before C1 has even started
    r = e.run(e.pre_agent("scout", agent_id="SC", agent_type="main-coder"))
    assert r.decision == "deny" and "Fan-out limit" in r.reason, r
    e.run(e.start("C1", "coder"))                                     # reservation -> live child
    r = e.run(e.pre_agent("scout", agent_id="SC", agent_type="main-coder"))
    assert r.decision == "deny" and "Fan-out limit" in r.reason, r
    e.run(e.stop("C1", "coder"))


# ---------------------------------------------------------------- review 2026-09-28
def test_r12_parallel_resumes_reserve_their_slots():
    """Resumes sent in one message are counted one by one: each takes a reservation under the
    fan-out lock, so the cap holds across the burst (the check used to reserve nothing)."""
    e = Env(STACK_MAX_FANOUT=2)
    spawned(e, "main-coder", "SC")
    for c in ("C1", "C2", "C3", "C4"):
        spawned(e, "coder", c, caller="SC", ctype="main-coder")
        e.run(e.stop(c, "coder"))
    rs = e.run_many([e.send(c, agent_id="SC", agent_type="main-coder")
                     for c in ("C1", "C2", "C3", "C4")])
    assert sum(r.decision.startswith("allow") for r in rs) == 2, rs
    folder = os.path.join(e.sdir(), "fanout", "SC")
    held = os.listdir(folder) if os.path.isdir(folder) else []
    assert len([f for f in held if f.startswith("resume-")]) == 2, held


def test_r13_a_resume_that_never_starts_expires():
    e = Env(STACK_MAX_FANOUT=1, STACK_RESUME_TTL_S=1)
    spawned(e, "main-coder", "SC")
    spawned(e, "coder", "C1", caller="SC", ctype="main-coder")
    e.run(e.stop("C1", "coder"))
    assert e.run(e.send("C1", agent_id="SC", agent_type="main-coder")).decision.startswith("allow")
    assert e.run(e.pre_agent("scout", agent_id="SC", agent_type="main-coder")).decision == "deny"
    time.sleep(1.1)                     # the SendMessage was refused elsewhere: C1 never started
    assert e.run(e.pre_agent("scout", agent_id="SC", agent_type="main-coder")).decision.startswith(
        "allow")
