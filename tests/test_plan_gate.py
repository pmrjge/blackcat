"""The plan gate (agent_guard.py plan_gate_violation, plan_resume_violation; SDK-3 decision (c)) and the
host-stop release (reap_host_stopped; SDK-3, probe PR5b).

Plan gate: a subagent runs in its own frontmatter permissionMode (probe PR3: a coder dispatched by a
plan-mode BlackCat ran in acceptEdits), so a caller whose PreToolUse event says permission_mode "plan"
dispatches only PLAN_SAFE_TYPES, runs no Workflow and resumes no finished builder; a project
.claude/agents folder (it may redefine a safe name) closes the gate. Every caller; STACK_POLICY=off lifts it.

Host-stop release: an Agent SDK host's stop_task() fires no hook (PR5b), but Claude Code writes
"stoppedByUser": true into the child's meta.json; the guard then marks the child stopped before it
counts running children.

Run: uv run --with pytest pytest -q tests/test_plan_gate.py
GUARD=/path/to/agent_guard.py points them at another copy of the hook (mutation runs)."""
import importlib.util
import json
import os
import time
from pathlib import Path

import pytest

from guard_harness import GUARD, Env

ROOT = Path(__file__).resolve().parents[1]
CONF = ROOT / "dot-config" / "dot-claude"
SAFE = ["claude-code-guide", "code-reviewer", "explore", "oracle", "plan-reviewer", "planner", "proof-checker",
        "scout", "security-auditor", "verifier"]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def env(**knobs):
    e = Env(STACK_USAGE_COLLECT="0", **knobs)
    os.mkdir(os.path.join(e.tmp, ".git"))          # cwd is a repository root with no project agents
    return e


def ok(r):
    assert r.rc == 0, r.stderr
    return r.decision.startswith("allow")


def refused(r, what="Plan mode"):
    assert r.rc == 0, r.stderr
    return r.decision == "deny" and what in r.reason


def agent(e, child, mode="plan", caller=None, ctype="blackcat"):
    return e.run(dict(e.pre_agent(child, agent_id=caller, agent_type=ctype), permission_mode=mode))


def workflow(e, mode):
    script = ("export const meta = {name: 'w', description: 'd'}\n"
              "return await agent('look', {agentType: 'explore'})\n")
    ev = e.base("PreToolUse", tool_name="Workflow", agent_type="blackcat", permission_mode=mode,
                tool_use_id="toolu_wf1", tool_input={"script": script})
    return e.run(ev)


def bg_child(e, cid, child, caller=None, ctype="blackcat", mode="default"):
    pre = dict(e.pre_agent(child, agent_id=caller, agent_type=ctype), permission_mode=mode)
    assert ok(e.run(pre))
    assert e.run(e.start(cid, child)).rc == 0
    assert e.run(e.post_agent(pre, cid)).rc == 0
    return pre


# ---------------------------------------------------------------- the plan gate: Agent
@pytest.mark.parametrize("child", ["coder", "main-coder", "orchestrator", "python-engineer", "equilibrium",
                                   "toolsmith", "researcher"])
def test_plan_mode_refuses_every_builder(child):
    e = env()
    r = agent(e, child)
    assert refused(r) and "'%s'" % child in r.reason and "ExitPlanMode" in r.reason, r
    assert set(r.reason.split("dispatch: ")[-1].rstrip(".").split(", ")) == set(SAFE), r


@pytest.mark.parametrize("child", SAFE)
def test_plan_mode_dispatches_the_agents_that_inherit_plan(child):
    assert ok(agent(env(), child))


@pytest.mark.parametrize("mode", ["default", "acceptEdits", "auto", None, ""])
def test_other_modes_and_no_reported_mode_dispatch_builders(mode):
    e = env()
    pre = e.pre_agent("coder", agent_type="blackcat")
    if mode is not None:
        pre["permission_mode"] = mode
    assert ok(e.run(pre))


def test_the_gate_binds_every_caller_in_plan_mode():
    e = env()
    assert refused(agent(e, "coder", ctype=None))                        # a main thread without --agent
    bg_child(e, "P1", "planner")
    assert ok(agent(e, "scout", caller="P1", ctype="planner"))           # an inherit-mode subagent's own row
    bg_child(e, "O1", "orchestrator")
    assert refused(agent(e, "coder", caller="O1", ctype="orchestrator"))
    assert ok(agent(e, "coder", mode="acceptEdits", caller="O1", ctype="orchestrator"))


def test_policy_off_lifts_the_plan_gate():
    assert ok(agent(env(STACK_POLICY="off"), "coder"))


def test_a_project_agents_folder_closes_the_gate():
    e = env()
    os.makedirs(os.path.join(e.tmp, ".claude", "agents"))
    r = agent(e, "explore")
    assert refused(r) and "project agents folder" in r.reason and "dispatch: none" in r.reason, r
    assert ok(agent(e, "explore", mode="default"))


def test_a_spawn_type_error_keeps_its_own_reason():
    r = agent(env(), "general-purpose")
    assert refused(r, "Spawn policy") and "Plan mode" not in r.reason, r


# ---------------------------------------------------------------- the plan gate: Workflow
def test_no_workflow_runs_in_plan_mode():
    e = env()
    assert refused(workflow(e, "plan"))
    assert ok(workflow(e, "default"))


# ---------------------------------------------------------------- the plan gate: SendMessage resumes
def msg(e, to, mode="plan"):
    return e.run(dict(e.send(to, agent_type="blackcat"), permission_mode=mode))


def test_resuming_a_finished_builder_is_refused_in_plan_mode():
    e = env()
    bg_child(e, "C1", "coder")
    bg_child(e, "X1", "explore")
    assert ok(msg(e, "C1"))                                  # running: coordination, not a spawn
    e.run(e.stop("C1", "coder"))
    e.run(e.stop("X1", "explore"))
    r = msg(e, "C1")
    assert refused(r) and "resuming 'C1', a finished coder" in r.reason, r
    assert ok(msg(e, "X1"))                                  # a finished safe agent resumes
    assert ok(msg(e, "C1", mode="default"))


def test_a_finished_record_of_unknown_type_is_refused_in_plan_mode():
    e = env()
    bg_child(e, "C2", "coder")
    e.run(e.stop("C2", "coder"))
    p = os.path.join(e.sdir(), "agents", "C2.json")
    rec = json.load(open(p))
    rec.pop("type", None)
    json.dump(rec, open(p, "w"))
    assert refused(msg(e, "C2"))


# ---------------------------------------------------------------- the lists agree with the files
def test_plan_safe_types_are_the_agents_without_a_mode():
    g = load("agent_guard_plan", GUARD)
    sdk = load("stack_sdk_plan", CONF / "bin" / "stack_sdk.py")
    inherit = {n for n, m in sdk.stack_agents(str(CONF)).items() if m in (None, "plan", "default")} - {"blackcat"}
    assert set(g.PLAN_SAFE_TYPES) == inherit == set(SAFE)


def test_project_agent_dirs_walk_like_stack_sdk(tmp_path):
    g = load("agent_guard_walk", GUARD)
    sdk = load("stack_sdk_walk", CONF / "bin" / "stack_sdk.py")
    conf = tmp_path / "home" / ".claude"
    (conf / "agents").mkdir(parents=True)
    main = tmp_path / "home" / "main"
    (main / ".git" / "worktrees" / "w1").mkdir(parents=True)
    (main / ".git" / "worktrees" / "w1" / "commondir").write_text("../..\n")
    wt = tmp_path / "home" / "wt"
    (wt / "sub" / "deeper").mkdir(parents=True)
    (wt / ".git").write_text("gitdir: %s\n" % (main / ".git" / "worktrees" / "w1"))
    cases = []
    for setup in ((), (wt / ".claude" / "agents",), (wt / "sub" / ".claude" / "agents", main / ".claude" / "agents")):
        for p in setup:
            p.mkdir(parents=True, exist_ok=True)
        for cwd in (wt, wt / "sub" / "deeper", tmp_path / "home"):
            got, want = g.project_agent_dirs(str(cwd), str(conf)), sdk.project_agent_files(str(cwd), str(conf))
            cases.append((str(cwd), got))
            assert got == want, (cwd, got, want)
    assert any(got for _, got in cases) and g.project_agent_dirs(str(tmp_path / "home"), str(conf)) == []


# ---------------------------------------------------------------- host-stop release (PR5b)
def stopped_meta(e, cid, flag=True, age_meta=0.0, age_tr=None):
    sub = os.path.join(e.proj, e.sid, "subagents")
    tr, meta = os.path.join(sub, "agent-%s.jsonl" % cid), os.path.join(sub, "agent-%s.meta.json" % cid)
    with open(tr, "w") as f:
        f.write('{"type": "user"}\n')
    with open(meta, "w") as f:
        json.dump({"agentType": "coder", "toolUseId": "toolu_x", "spawnDepth": 2, "stoppedByUser": flag}, f)
    now = time.time()
    os.utime(meta, (now - age_meta, now - age_meta))
    t = now - age_meta - 1 if age_tr is None else now - age_tr
    os.utime(tr, (t, t))


def capped():
    """main-coder M1 (STACK_MAX_FANOUT=1) with one running background coder C1: its next spawn is refused."""
    e = env(STACK_MAX_FANOUT="1")
    bg_child(e, "M1", "main-coder")
    bg_child(e, "C1", "coder", caller="M1", ctype="main-coder")
    e.age_reg("C1", 30)                            # started 30 s ago
    assert refused(agent(e, "coder", mode="acceptEdits", caller="M1", ctype="main-coder"), "Fan-out limit")
    return e


def test_a_child_its_host_stopped_is_released_before_the_count():
    e = capped()
    stopped_meta(e, "C1")
    assert ok(agent(e, "coder", mode="acceptEdits", caller="M1", ctype="main-coder"))
    assert e.reg("C1").get("stopped")


def test_a_host_stop_also_frees_the_slot_for_a_resume():
    e = capped()
    e.run(e.stop("C1", "coder"))                   # a finished coder M1 resumes ...
    bg_child(e, "C3", "coder", caller="M1", ctype="main-coder", mode="acceptEdits")
    e.age_reg("C3", 30)
    r = e.run(dict(e.send("C1", agent_id="M1", agent_type="main-coder"), permission_mode="acceptEdits"))
    assert refused(r, "Fan-out limit"), r          # ... once C3 no longer holds the one slot
    stopped_meta(e, "C3")
    assert ok(e.run(dict(e.send("C1", agent_id="M1", agent_type="main-coder"), permission_mode="acceptEdits")))
    assert e.reg("C3").get("stopped")


@pytest.mark.parametrize("flag", [False, "true", 1, None])
def test_only_a_true_stopped_by_user_flag_releases(flag):
    e = capped()
    stopped_meta(e, "C1", flag=flag)
    assert refused(agent(e, "coder", mode="acceptEdits", caller="M1", ctype="main-coder"), "Fan-out limit")
    assert not e.reg("C1").get("stopped")


def test_a_child_resumed_after_the_stop_is_not_released():
    e = capped()
    stopped_meta(e, "C1", age_meta=60)             # the flag predates the record's latest start (30 s ago)
    assert refused(agent(e, "coder", mode="acceptEdits", caller="M1", ctype="main-coder"), "Fan-out limit")
    assert not e.reg("C1").get("stopped")


def test_a_child_still_writing_after_the_flag_is_not_released():
    e = capped()
    stopped_meta(e, "C1", age_meta=20, age_tr=5)   # transcript lines 15 s after the meta
    assert refused(agent(e, "coder", mode="acceptEdits", caller="M1", ctype="main-coder"), "Fan-out limit")
    assert not e.reg("C1").get("stopped")
