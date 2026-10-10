"""Subprocess-driven tests for dot-config/dot-claude/hooks/agent_guard.py (stdlib hook).

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
GUARD = ROOT / "dot-config" / "dot-claude" / "hooks" / "agent_guard.py"
REPEATS = 20
FANOUT = 20

KNOBS = ("STACK_POLICY", "STACK_BLACKCAT_DELEGATE_ONLY", "BLACKCAT_MAX_STEPS", "SCREEN_LOCK_TTL_S",
         "STRIP_AGENT_MODEL",
         "STACK_GUARD_LOG", "STACK_MODE_PROBE", "CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH",
         "BLACKCAT_DISPATCH_WINDOW_S", "STACK_MAX_FANOUT",
         "STACK_FANOUT_IDLE_S", "STACK_MAX_FANOUT_BY_TYPE", "STACK_LEASE_TTL_S",
         "STACK_RESUME_TTL_S", "STACK_PROMPT_CTX_BUDGET", "STACK_SESSION_CTX_BUDGET",
         "STACK_MAX_MCP_CALLS", "BLACKCAT_BACKGROUND", "STACK_SOFT_LIMIT_SCALE", "BLACKCAT_MAX_OWN_STEPS", "BLACKCAT_MAX_READS",
         "BLACKCAT_BASH_TIMEOUT_MS", "BASH_DEFAULT_TIMEOUT_MS", "STACK_FANOUT_SESSION",
         "CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS",
         # the dynamic fan-out knobs (stack_fanout.KNOBS)
         "STACK_FANOUT_DYN", "STACK_FANOUT_DYN_ALPHA", "STACK_FANOUT_DYN_BETA_FAIL",
         "STACK_FANOUT_DYN_BETA_RL", "STACK_FANOUT_DYN_BREAKER", "STACK_FANOUT_DYN_DELAY_RATIO",
         "STACK_FANOUT_DYN_ENFORCE", "STACK_FANOUT_DYN_HOLD_S", "STACK_FANOUT_DYN_NODE_RUNS",
         "STACK_FANOUT_DYN_RESERVE_TOK", "STACK_FANOUT_DYN_SLACK", "STACK_FANOUT_DYN_TYPES",
         "STACK_FANOUT_DYN_W0", "STACK_FANOUT_DYN_WMIN")


# ---------------------------------------------------------------- harness
# The mechanics below were written against these caps; the shipped defaults (BlackCat 24 steps,
# dispatches included, the per-type fan-out table) are checked by test_shipped_spawn_defaults.
BASELINE = {"BLACKCAT_MAX_STEPS": "8",
            "STACK_MAX_FANOUT_BY_TYPE": "orchestrator=8,planner=8,plan-reviewer=8"}


@pytest.fixture
def bare_env(tmp_path):
    e = {k: v for k, v in os.environ.items() if k not in KNOBS}
    e["XDG_STATE_HOME"] = str(tmp_path / "state")
    e["STACK_USAGE_COLLECT"] = "0"     # SessionStart starts no usage collector in these tests
    return e


@pytest.fixture
def env(bare_env):
    return dict(bare_env, **BASELINE)


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
    # no permissionDecision: a label-only rewrite (STACK_AGENT_LABEL), which allows
    return json.loads(p.stdout)["hookSpecificOutput"].get("permissionDecision", "allow")


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
                   json.loads(stdout)["hookSpecificOutput"].get("permissionDecision", "allow"))
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
    assert list(d) == ["policy", "leaves", "agents", "builtins", "blackcat_tools", "installer_types", "eq_types"]
    assert len(d["agents"]) == 59 and len(set(d["agents"])) == 59
    assert d["installer_types"] == ["toolsmith"] and d["eq_types"] == ["equilibrium"]
    assert d["builtins"] == [] and "explore" in d["agents"] and "explore" in d["leaves"]
    assert set(d["policy"]) == set(d["agents"])
    assert sorted(d["leaves"]) == sorted(k for k, v in d["policy"].items() if not v)
    # only agents on BlackCat's row are reachable at any depth: it lists every specialist
    assert set(d["policy"]["blackcat"]) == set(d["agents"]) - {"blackcat"}
    assert set(d["policy"]["orchestrator"]) == set(d["policy"]["blackcat"]) - {"orchestrator"}
    assert {"ml-engineer", "dl-engineer", "llm-engineer", "ninja-coder"} <= set(
        d["policy"]["main-coder"])
    # escalation chain coder < main-coder < ninja-coder (the top tier); coder is a leaf
    assert d["policy"]["coder"] == [] and "coder" in d["leaves"]
    assert {"main-coder", "mathematician"} <= set(d["policy"]["ninja-coder"])
    assert sorted(a for a in d["agents"] if a.endswith("-coder")) == ["main-coder", "ninja-coder"]
    for eng in ("mlx-engineer", "cuda-engineer", "dl-engineer", "llm-engineer"):
        assert "ninja-coder" in d["policy"][eng]
    # T1: browser-operator (logged-in browser) is spawned only by blackcat and the orchestrator,
    # never by an agent that reads web pages (an injected page must not reach the user's sessions)
    assert {k for k, v in d["policy"].items() if "browser-operator" in v} == {
        "blackcat", "orchestrator"}
    assert d["policy"]["mlx-engineer"] == d["policy"]["cuda-engineer"]
    for new in ("plan-reviewer", "mlx-engineer", "cuda-engineer", "devops-engineer",
                "data-engineer", "frontend-engineer", "ml-engineer", "dl-engineer",
                "llm-engineer", "data-scientist", "browser-operator", "claude-code-engineer",
                "ninja-coder"):
        assert new in d["agents"]
    assert "senior-coder" not in d["agents"]
    for parent, row in d["policy"].items():
        assert parent not in row, parent                    # nobody spawns its own type
        assert not [c for c in row if c.endswith("-copy")], parent      # copy types retired
    assert d["policy"]["planner"]                           # planner keeps Agent
    assert {"plan-reviewer", "image-director", "coder"} <= set(d["leaves"])
    assert {"Agent", "SendMessage", "Workflow", "CronCreate", "Skill", "Read"} <= set(
        d["blackcat_tools"])
    # no web tool on BlackCat (T1), no work tool (it only delegates), no search tool
    assert not {"WebFetch", "WebSearch", "Monitor", "NotebookEdit", "Grep", "Glob", "Bash", "Write",
                "Edit"} & set(d["blackcat_tools"])


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
            if "equilibrium" in (parent, child):
                continue        # eq spawns need an eq header / a bound run: tests/test_eq_guard.py
            ev = (pre_agent(sid(), child, parent="blackcat") if parent == "blackcat" else
                  pre_agent(sid(), child, parent=parent, agent_id="id-" + parent))
            assert decision(run(ev, env)) == "allow", (parent, child)


@pytest.mark.parametrize("parent,child", [
    ("blackcat", "general-purpose"), ("blackcat", "fork"), ("explore", "scout"),
    ("blackcat", "statusline-setup"), ("blackcat", "claude"), ("blackcat", "plan"),
    ("blackcat", "blackcat"), ("orchestrator", "general-purpose"), ("orchestrator", "orchestrator"),
    ("main-coder", "general-purpose"), ("main-coder", "fork"),
    ("mlx-engineer", "mlx-engineer"), ("cuda-engineer", "cuda-engineer"),
    ("devops-engineer", "devops-engineer"), ("designer", "designer"),
    ("image-director", "image-director"), ("browser-operator", "scout"),
    ("claude-code-engineer", "claude-code-engineer"), ("data-scientist", "ninja-coder"),
    ("ml-engineer", "ninja-coder"), ("planner", "planner"), ("llm-engineer", "designer"),
    ("coder", "main-coder"), ("coder", "ninja-coder"), ("scout", "coder"),
    ("planner", "coder"), ("plan-reviewer", "coder"), ("researcher", "coder"),
    ("devops-engineer", "ninja-coder"), ("data-engineer", "designer"),
    ("frontend-engineer", "ninja-coder"), ("mlx-engineer", "main-coder"),
    ("claude-code-guide", "scout"), ("verifier", "coder"),
    # nobody spawns its own type; the retired copy types are unknown
    ("coder", "coder"), ("researcher", "researcher"), ("main-coder", "main-coder"),
    ("ninja-coder", "ninja-coder"), ("writer", "writer"), ("mathematician", "mathematician"),
    ("data-scientist", "data-scientist"), ("blackcat", "coder-copy"),
    ("orchestrator", "researcher-copy"), ("main-coder", "coder-copy"),
    ("writer", "researcher-copy"), ("researcher", "coder-copy"),
    # retired 2026-10-04: unknown types for every caller
    ("orchestrator", "supreme-coder"), ("main-coder", "supreme-coder"),
    ("blackcat", "supreme-coder"), ("blackcat", "db-engineer"), ("blackcat", "localizer"),
    ("data-engineer", "db-engineer"), ("writer", "localizer"),
    ("plan-reviewer", "scout"), ("image-director", "scout"),        # leaves
    ("coder", "explore"), ("coder", "scout"), ("coder", "test-engineer"), ("coder", "build-fixer"),
])
def test_denied_pairs(env, parent, child):
    ev = (pre_agent(sid(), child, parent="blackcat") if parent == "blackcat" else
          pre_agent(sid(), child, parent=parent, agent_id="id-" + parent))
    p = run(ev, env)
    assert decision(p) == "deny"
    assert "Spawn policy" in reason(p)


def test_coder_is_a_leaf(env):
    """coder (decided 2026-10-04): no Agent or SendMessage on its tools line, an empty POLICY row,
    and every spawn it attempts is refused."""
    text = (ROOT / "dot-config" / "dot-claude" / "agents" / "coder.md").read_text()
    tools = {t.strip() for t in re.search(r"(?m)^tools:(.*)$", text).group(1).split(",")}
    assert not {"Agent", "SendMessage"} & tools, tools
    assert "May spawn:" not in text
    pol = policy(env)
    assert pol["policy"]["coder"] == [] and "coder" in pol["leaves"]
    for child in sorted(set(pol["agents"]) - {"blackcat"}):
        p = run(pre_agent(sid(), child, parent="coder", agent_id="id-coder"), env)
        assert decision(p) == "deny" and "Spawn policy" in reason(p), child


def test_missing_subagent_type_is_general_purpose(env):
    ev = pre_agent(sid(), "", parent="blackcat")
    del ev["tool_input"]["subagent_type"]
    p = run(ev, env)
    assert decision(p) == "deny"
    assert "subagent_type is required" in reason(p) and "explore" in reason(p)


def test_normalization(env):
    assert decision(run(pre_agent(sid(), "Explore", parent="Main_Coder", agent_id="x"),
                        env)) == "allow"


GENERIC_SPELLINGS = [None, "", "  ", "general-purpose", "General-Purpose", "GENERAL_PURPOSE",
                     "claude", "fork", "Fork", "SubAgent", "subagent", "Sub Agent", "Task", "Plan",
                     "statusline-setup", "workflow-subagent", "Agent", "my-plugin:helper"]


@pytest.mark.parametrize("parent,agent_id", [
    ("blackcat", None), ("", None), ("my-custom-agent", None),           # main threads
    ("main-coder", "M1"), ("orchestrator", "O1"),                         # stack subagents
    ("general-purpose", "G1"), ("SubAgent", "S1"),                        # generic subagents
])
@pytest.mark.parametrize("tool", ["Agent", "Task", "SubAgent"])
def test_generic_types_denied_for_every_caller(env, parent, agent_id, tool):
    """The leak: a caller without a POLICY row (typeless main thread, a host's agent, a generic
    subagent) used to spawn anything, general-purpose and fork included."""
    for child in GENERIC_SPELLINGS:
        ev = pre_agent(sid(), child, parent=parent, agent_id=agent_id)
        ev["tool_name"] = tool
        if child is None:
            del ev["tool_input"]["subagent_type"]
        p = run(ev, env)
        assert decision(p) == "deny", (parent, tool, child)
        assert "Spawn policy" in reason(p), reason(p)


@pytest.mark.parametrize("parent,agent_id,child,want", [
    ("", None, "coder", "allow"), ("my-custom-agent", None, " Code Reviewer ", "allow"),
    ("", None, "ninja-coder", "allow"), ("claude", None, "orchestrator", "allow"),
    ("general-purpose", "G1", "coder", "deny"), ("SubAgent", "S1", "scout", "deny"),
    ("my-plugin:helper", "P1", "coder", "deny"),
])
def test_rowless_callers(env, parent, agent_id, child, want):
    """A caller without a row: every stack agent on a main thread, nothing as a subagent."""
    assert decision(run(pre_agent(sid(), child, parent=parent, agent_id=agent_id), env)) == want


def _guard_module():
    sys.path.insert(0, str(GUARD.parent))
    try:
        import agent_guard
    finally:
        sys.path.pop(0)
    return agent_guard


@pytest.mark.parametrize("parent", [None, "", "claude", "my-custom-agent"])
def test_rowless_main_thread_spawns_every_stack_agent(env, parent):
    """User decision 2026-10-04: only BlackCat is held to a spawn list. A main thread with no POLICY
    row (typeless, `claude --agent claude`, a foreign agent) may spawn every stack agent, the
    orchestrator included; generic and built-in types and blackcat stay refused."""
    g = _guard_module()
    for child in [a for a in g.AGENTS if a not in ("blackcat", "equilibrium")]:     # eq: test_eq_guard.py
        assert decision(run(pre_agent(sid(), child, parent=parent), env)) == "allow", child
    for child in ("blackcat", "general-purpose", "claude", "fork", "Plan", "statusline-setup",
                  "my-plugin:helper", "coder-copy"):
        assert decision(run(pre_agent(sid(), child, parent=parent), env)) == "deny", child
    s = sid()
    script = "await agent('x', {agentType: 'data-engineer'})"
    assert decision(run(workflow_ev(s, parent=parent, script=script), env)) == "allow"


def test_rows_unchanged_for_blackcat_typed_main_threads_and_subagents(env):
    """BlackCat keeps its own list (every specialist, generic types refused); a
    main thread with a POLICY row (claude --agent main-coder) keeps that row; subagents keep theirs,
    and an agent context of no known type keeps BlackCat's row."""
    g = _guard_module()
    for child in ("blackcat", "general-purpose", "coder-copy"):
        assert decision(run(pre_agent(sid(), child, parent="blackcat"), env)) == "deny", child
    outside = [a for a in g.AGENTS if a not in g.POLICY["main-coder"] and a != "blackcat"]
    assert "orchestrator" in outside
    for child in outside:
        assert decision(run(pre_agent(sid(), child, parent="main-coder"), env)) == "deny", child
    assert decision(run(pre_agent(sid(), "coder", parent="main-coder"), env)) == "allow"
    assert decision(run(pre_agent(sid(), "designer", parent="coder", agent_id="C1"), env)) == "deny"
    for parent in ("", "main-session"):
        assert decision(run(pre_agent(sid(), "blackcat", parent=parent, agent_id="X1"),
                            env)) == "deny", parent
        assert decision(run(pre_agent(sid(), "coder", parent=parent, agent_id="X1"),
                            env)) == "allow", parent
    for parent in ("general-purpose", "my-plugin:helper"):
        assert decision(run(pre_agent(sid(), "coder", parent=parent, agent_id="G1"), env)) == "deny"


def test_task_alias_reaches_the_spawn_gate(env):
    ev = pre_agent(sid(), "coder", parent="blackcat")
    ev["tool_name"] = "Task"
    assert decision(run(ev, env)) == "allow"
    ev = pre_agent(sid(), "scout", parent="main-coder", agent_id="C1")
    ev["tool_name"] = "SubAgent"
    assert decision(run(ev, env)) == "allow"


@pytest.mark.parametrize("atype", ["general-purpose", "SubAgent", "subagent", "fork", "claude",
                                   "workflow-subagent", "General Purpose"])
@pytest.mark.parametrize("tool,ti", [("Read", {"file_path": "x"}), ("Bash", {"command": "ls"}),
                                     ("mcp__exa__web_search_exa", {"query": "q"})])
def test_generic_subagent_runs_no_tools(env, atype, tool, ti):
    """A generic agent started outside the Agent tool (a forked skill without `agent:`, a workflow
    stage without agentType) is refused every tool call by the every-tool `budget` hook."""
    ev = {"session_id": sid(), "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": ti, "agent_id": "X1", "agent_type": atype}
    p = run(ev, env, args=["budget"])
    assert decision(p) == "deny" and "generic agent" in reason(p)
    assert decision(run(ev, env, args=["budget"], extra={"STACK_POLICY": "off"})) == "allow"


@pytest.mark.parametrize("atype", ["coder", "explore", "researcher", "claude-test:runner"])
def test_stack_and_namespaced_subagents_keep_tools(env, atype):
    ev = {"session_id": sid(), "hook_event_name": "PreToolUse", "tool_name": "Read",
          "tool_input": {"file_path": "x"}, "agent_id": "X1", "agent_type": atype}
    assert decision(run(ev, env, args=["budget"])) == "allow"
    del ev["agent_id"]                                   # the main thread is never refused here
    ev["agent_type"] = "general-purpose"
    assert decision(run(ev, env, args=["budget"])) == "allow"


def workflow_ev(s, parent="blackcat", agent_id=None, tool="Workflow", **ti):
    ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_input": ti, "cwd": str(ROOT)}
    if parent:
        ev["agent_type"] = parent
    if agent_id:
        ev["agent_id"] = agent_id
    return ev


TYPED = ("export const meta = {name: 'audit', description: 'd'}\n"
         "const files = await agent('list files', {agentType: 'explore', schema: S})\n"
         "return await pipeline(files.files, f => agent(`fix ${f}`, {agentType: 'coder', label: f}))\n")


@pytest.mark.parametrize("tool", ["Workflow", "RunWorkflow"])
def test_workflow_needs_typed_stages(env, tool):
    s = sid()
    assert decision(run(workflow_ev(s, tool=tool, script=TYPED), env)) == "allow"
    for bad, why in (("await agent('do it')", "generic default workflow subagent"),
                     ("await agent('x', {label: 'a'})", "has no agentType"),
                     ("await agent('x', {agentType: 'coder', ...o})", "spread or computed"),
                     ("await agent('x', {agentType: 'explore', effort: 'max'})", "above explore"),
                     ("await agent(`a ${await agent('i', {agentType: 'explore'})}`)",
                      "exactly two arguments"),
                     ("await agent('x', {agentType: 'general-purpose'})", "not an agent you may"),
                     ("await agent('x', {agentType: 'senior-coder'})", "not an agent you may"),
                     ("await agent('x', {agentType: 'coder', model: 'opus'})", "sets model"),
                     ("await workflow('other')", "nested workflow"),
                     ("await agent('x', {agentType: 'coder'", "not closed")):
        p = run(workflow_ev(s, tool=tool, script=bad), env)
        assert decision(p) == "deny" and why in reason(p), (bad, reason(p))
        assert "explore" in reason(p)                       # the valid types are named
    assert decision(run(workflow_ev(s, tool=tool, script="await agent('x')"), env,
                        extra={"STACK_POLICY": "off"})) == "allow"


def test_workflow_by_name_and_path(env, tmp_path):
    s = sid()
    p = run(workflow_ev(s, name="deep-research"), env)
    assert decision(p) == "deny" and "researcher" in reason(p)
    script = tmp_path / "w.js"
    script.write_text(TYPED)
    assert decision(run(workflow_ev(s, scriptPath=str(script)), env)) == "allow"
    script.write_text("await agent('x')")
    assert decision(run(workflow_ev(s, scriptPath=str(script)), env)) == "deny"
    assert decision(run(workflow_ev(s, scriptPath=str(tmp_path / "none.js")), env)) == "deny"
    # Claude Code runs scriptPath before script: every source present is checked
    p = run(workflow_ev(s, script=TYPED, scriptPath=str(script)), env)
    assert decision(p) == "deny" and "(in scriptPath)" in reason(p)
    # a saved workflow is found by its file stem under the project's .claude/workflows
    saved = tmp_path / "proj" / ".claude" / "workflows"
    saved.mkdir(parents=True)
    (saved / "audit.js").write_text(TYPED)
    ev = workflow_ev(s, name="audit")
    ev["cwd"] = str(tmp_path / "proj")
    assert decision(run(ev, env)) == "allow"
    (saved / "deep-research.js").write_text(TYPED)       # a bundled name is refused all the same
    ev = workflow_ev(s, name="deep-research")
    ev["cwd"] = str(tmp_path / "proj")
    assert decision(run(ev, env)) == "deny"
    # a main thread with a row of its own (claude-ninja) is held to that row
    ninja = "await agent('x', {agentType: 'designer'})"
    assert decision(run(workflow_ev(s, parent="ninja-coder", script=ninja), env)) == "deny"


# ---------------------------------------------------------------- depth
def test_depth_chain(env):
    """The registry records each child's depth (ledger, budgets, stack-who); the hook refuses no
    spawn by depth: Claude Code withholds the Agent tool at CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH
    (sub-agents.md), so a call that reaches the hook is within the native limit."""
    s = sid()
    assert decision(run(pre_agent(s, "orchestrator", parent="blackcat"), env)) == "allow"
    run(post_agent(s, "orchestrator", "A1"), env)
    run(post_agent(s, "main-coder", "A2", agent_id="A1", parent="orchestrator"), env)
    run(post_agent(s, "ninja-coder", "A3", agent_id="A2", parent="main-coder", as_string=True), env)
    reg = lambda a: json.loads((state(env, s) / "agents" / (a + ".json")).read_text())  # noqa
    assert [reg(a)["depth"] for a in ("A1", "A2", "A3")] == [1, 2, 3]
    assert reg("A3")["parent"] == "A2"
    # L2 and L3 may spawn (the hook's own depth limit, Claude Code's default 3, is gone)
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="A2"), env)) \
        == "allow"
    p = run(pre_agent(s, "scout", parent="ninja-coder", agent_id="A3"), env)
    assert decision(p) == "allow"
    # unknown provenance decides nothing any more: a main-coder never spawns a main-coder (policy,
    # whatever the registry knows); an allowed pair from a caller of unknown depth passes (Claude
    # Code's native depth limit stays authoritative)
    p = run(pre_agent(s, "main-coder", parent="main-coder", agent_id="ZZ"), env)
    assert decision(p) == "deny" and "Spawn policy" in reason(p)
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="ZZ"), env)) == "allow"
    # child of an unknown caller has null depth; it may use its own row
    run(post_agent(s, "main-coder", "A4", agent_id="ZZ", parent="ninja-coder"), env)
    assert reg("A4")["depth"] is None
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="A4"), env)) == "allow"
    p = run(pre_agent(s, "main-coder", parent="main-coder", agent_id="A4"), env)
    assert decision(p) == "deny" and "Spawn policy" in reason(p)
    # the native knob is not read by the hook: an L2 still spawns at a limit of 2
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="A2"), env,
            extra={"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "2"})
    assert decision(p) == "allow"
    # an explicit depth 4: L3 may spawn an L4, and the hook does not refuse the L4 either
    four = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "4"}
    assert decision(run(pre_agent(s, "main-coder", parent="ninja-coder", agent_id="A3"), env,
                        extra=four)) == "allow"
    run(post_agent(s, "scout", "A5", agent_id="A3", parent="ninja-coder"), env, extra=four)
    assert reg("A5")["depth"] == 4
    run(post_agent(s, "main-coder", "A6", agent_id="A3", parent="ninja-coder"), env, extra=four)
    p = run(pre_agent(s, "scout", parent="main-coder", agent_id="A6"), env, extra=four)
    assert decision(p) == "allow"
    # the stack's depth 8 (settings.json): the registry follows the chain down to an L8
    eight = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "8"}
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="A6"), env,
                        extra=eight)) == "allow"
    # main-coder and ninja-coder may spawn each other (coder is a leaf, the copies are retired)
    chain = [("A6", "main-coder"), ("A7", "ninja-coder"), ("A8", "main-coder"),
             ("A9", "ninja-coder"), ("A10", "main-coder")]
    for (pid, ptype), (cid, ctype) in zip(chain, chain[1:]):
        assert decision(run(pre_agent(s, ctype, parent=ptype, agent_id=pid), env,
                            extra=eight)) == "allow"
        run(post_agent(s, ctype, cid, agent_id=pid, parent=ptype), env, extra=eight)
    assert [reg(a)["depth"] for a, _ in chain] == [4, 5, 6, 7, 8]
    assert decision(run(pre_agent(s, "scout", parent="ninja-coder", agent_id="A9"), env,
                        extra=eight)) == "allow"
    p = run(pre_agent(s, "scout", parent="main-coder", agent_id="A10"), env, extra=eight)
    assert decision(p) == "allow"           # natively an L8 has no Agent tool at limit 8


def test_subagent_start_does_not_clobber_depth(env):
    s = sid()
    run(post_agent(s, "coder", "C1"), env)
    run(lifecycle(s, "SubagentStart", "C1", "coder"), env)
    reg = json.loads((state(env, s) / "agents" / "C1.json").read_text())
    assert reg["depth"] == 1 and reg["type"] == "coder" and "started" in reg


# ---------------------------------------------------------------- blackcat dispatch (M4)
def test_blackcat_dispatch_cap_is_the_step_cap_concurrent(env):
    """BLACKCAT_MAX_DISPATCH is retired (2026-10-04): BlackCat's dispatches are bounded by
    BLACKCAT_MAX_STEPS alone (8 here); a stale BLACKCAT_MAX_DISPATCH in the environment does
    nothing."""
    for _ in range(REPEATS):
        s = sid()
        res = run_many([pre_agent(s, "coder", parent="blackcat") for _ in range(FANOUT)], env,
                       extra={"BLACKCAT_MAX_DISPATCH": "1"})
        assert res.count("allow") == 8, res
        # losers left no fan-out leases, dispatch or step markers behind
        assert len(list((state(env, s) / "fanout" / "main").iterdir())) == 8
        names = sorted(p.name.split(".")[0] for p in (state(env, s) / "blackcat").iterdir())
        assert names == ["dispatch"] * 8 + ["step"] * 8
    p = run(pre_agent(s, "coder", parent="blackcat"), env)
    assert decision(p) == "deny" and "step limit (8 tool calls" in reason(p)
    assert "dispatch limit" not in reason(p)


def test_blackcat_step_knob_bounds_dispatches_concurrent(env):
    s = sid()
    res = run_many([pre_agent(s, "coder", parent="blackcat") for _ in range(FANOUT)], env,
                   extra={"BLACKCAT_MAX_STEPS": "3"})
    assert res.count("allow") == 3


def test_blackcat_new_prompt_and_rollback(env):
    env["BLACKCAT_MAX_STEPS"] = "1"
    s = sid()
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="p1"), env)) == "allow"
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="p1"), env)) == "deny"
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="p2"), env)) == "allow"
    # PermissionDenied for blackcat's p1 call frees its dispatch marker (the step stays spent)
    fail = pre_agent(s, "coder", parent="blackcat", prompt="p1")
    fail["hook_event_name"] = "PermissionDenied"
    assert run(fail, env).stdout == ""
    assert not (state(env, s) / "blackcat" / "dispatch.p1.0").exists()
    assert (state(env, s) / "blackcat" / "step.p1.0").exists()
    # a subagent's failure does not touch blackcat markers
    run(pre_agent(s, "coder", parent="blackcat", prompt="p3"), env)
    sub = pre_agent(s, "coder", parent="coder", agent_id="C9", prompt="p3")
    sub["hook_event_name"] = "PostToolUseFailure"
    run(sub, env)
    assert (state(env, s) / "blackcat" / "dispatch.p3.0").exists()


def test_user_prompt_prunes_other_prompts(env):
    env["BLACKCAT_MAX_STEPS"] = "1"
    s = sid()
    run(pre_agent(s, "coder", parent="blackcat", prompt="p1"), env)
    run({"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": "p2"}, env)
    assert not (state(env, s) / "blackcat" / "dispatch.p1.0").exists()
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="p1"), env)) == "allow"
    # prompt_id absent -> "noprompt" markers, cleared by the next UserPromptSubmit
    ev = pre_agent(s, "coder", parent="blackcat")
    del ev["prompt_id"]
    assert decision(run(ev, env)) == "allow"
    assert decision(run(ev, env)) == "deny"
    run({"session_id": s, "hook_event_name": "UserPromptSubmit"}, env)
    assert decision(run(ev, env)) == "allow"


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
    run(pre_agent(s, "coder", parent="blackcat"), env)        # a BlackCat dispatch marker
    run(pre_agent(s, "ninja-coder"), env)
    run(post_agent(s, "ninja-coder", "G1"), env)
    run(screen(s, agent_id="D1"), env)
    p = run({"session_id": s, "hook_event_name": "SessionStart", "source": source}, env)
    if source == "compact":       # the compaction digest (tests/test_compact_survival.py), only output
        out = json.loads(p.stdout)
        assert p.returncode == 0 and set(out) == {"hookSpecificOutput"}
        assert out["hookSpecificOutput"]["additionalContext"].startswith("Compaction survival")
    else:
        assert p.returncode == 0 and p.stdout == ""
    d = state(env, s)
    for f in ("screen.lock", "blackcat"):
        assert (d / f).exists() != cleared, (source, f)
    assert (d / "agents" / "G1.json").exists()  # registry kept


def test_session_start_prunes_old_dirs(env):
    root = Path(env["XDG_STATE_HOME"]) / "claude-agent-stack"
    old, fresh = root / "old-session", root / "fresh-session"
    for d in (old, fresh):
        (d / "agents").mkdir(parents=True)
        (d / "screen.lock").write_text("{}")
    t = time.time() - 4 * 86400
    for p in (old / "agents", old / "screen.lock", old):
        os.utime(p, (t, t))
    run({"session_id": "cur", "hook_event_name": "SessionStart", "source": "startup"}, env)
    assert not old.exists() and fresh.exists() and (root / "cur").exists()


# ---------------------------------------------------------------- fail-closed (L7)
def test_bad_tool_input_denied(env):
    ev = pre_agent(sid(), "coder", parent="blackcat")
    ev["tool_input"] = "not an object"
    p = run(ev, env)
    assert decision(p) == "deny" and "stack guard error" in reason(p)
    # the escape hatch goes to the user (systemMessage), never to the model (reason)
    assert "STACK_POLICY" not in reason(p)
    assert "STACK_POLICY" in json.loads(p.stdout)["systemMessage"]
    ev["tool_name"] = "SendMessage"
    assert decision(run(ev, env)) == "deny"


def test_policy_off_no_output(env):
    extra = {"STACK_POLICY": "off", "STACK_AGENT_LABEL": "off"}
    s = sid()
    for ev in (pre_agent(s, "general-purpose", parent="blackcat"),
               pre_agent(s, "coder", parent="blackcat"), pre_agent(s, "coder", parent="blackcat"),
               pre_agent(s, "ninja-coder", parent="scout", agent_id="x"),
               screen(s, agent_id="a"), screen(s, agent_id="b")):
        p = run(ev, env, extra=extra)
        assert p.returncode == 0 and p.stdout == ""
    assert not (state(env, s) / "screen.lock").exists()
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
    p = run(pre_agent("s", "coder", parent="blackcat"), env, extra=extra)
    assert decision(p) == "deny" and "stack guard error" in reason(p)


def test_unparseable_stdin(env):
    p = run("{not json", env)
    assert p.returncode == 0 and p.stdout == ""
    p = run("{not json", env, args=["blackcat-guard"])
    assert decision(p) == "deny"
    # STACK_POLICY=off does not lift delegate-only: BlackCat's own wiring still fails closed, the
    # settings wiring refuses only what names BlackCat; STACK_BLACKCAT_DELEGATE_ONLY=0 lifts both
    off = {"STACK_POLICY": "off"}
    p = run("{not json", env, args=["blackcat-guard"], extra=off)
    assert decision(p) == "deny" and "STACK_BLACKCAT_DELEGATE_ONLY" in json.loads(p.stdout)["systemMessage"]
    p = run("{not json", env, args=["blackcat-guard", "--settings"], extra=off)
    assert p.returncode == 0 and p.stdout == ""
    for spelling in ("blackcat", "BlackCat", "black-cat", "Black Cat"):   # as loose as norm()
        p = run('{"agent_type": "%s", "tool_name": "Bash"' % spelling, env,
                args=["blackcat-guard", "--settings"], extra=off)
        assert decision(p) == "deny", spelling
    p = run('{"agent_type": "blackcat-helper", "tool_name": "Bash"', env,
            args=["blackcat-guard", "--settings"], extra=off)
    assert p.returncode == 0 and p.stdout == ""
    for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
        p = run('{"agent_type": "blackcat"', env, args=args,
                extra=dict(off, STACK_BLACKCAT_DELEGATE_ONLY="0"))
        assert p.returncode == 0 and p.stdout == "", args


# ---------------------------------------------------------------- blackcat-guard mode
def rg(s, tool, prompt="p1", **extra):
    return dict({"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
                 "prompt_id": prompt,
                 "tool_input": {"command": "git status"} if tool == "Bash" else {}}, **extra)


def test_blackcat_guard_allowlist(env):
    s = sid()
    refused = ("WebSearch", "WebFetch", "mcp__exa__search", "mcp__claude-in-chrome__navigate",
               "mcp__conductor__AskUserQuestion", "TaskOutput", "NotebookEdit", "Monitor",
               "PowerShell", "LSP", "Grep", "Glob", "TodoWrite", "EnterPlanMode", "", None)
    for tool in refused:
        p = run(rg(s, tool), env, args=["blackcat-guard"])
        assert decision(p) == "deny" and "belongs to a specialist" in reason(p), tool
    # the allowlist (the user's, 2026-10-04): every tool on it passes through both wirings, with
    # the policy on and off; with the policy off the specialist tools are still refused
    for extra in ({}, {"STACK_POLICY": "off"}):
        for tool in ALLOWLIST:
            for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
                ev = rg(s, tool, prompt="p-%s-%d" % (tool, len(extra)), agent_type="blackcat")
                assert decision(run(ev, env, args=args, extra=extra)) == "allow", (tool, args, extra)
        for tool in refused:
            p = run(rg(s, tool, agent_type="blackcat"), env, args=["blackcat-guard", "--settings"],
                    extra=extra)
            assert decision(p) == "deny", (tool, extra)


ALLOWLIST = ("Agent", "Task", "SendMessage", "TaskStop", "ListAgents", "AskUserQuestion",
             "ExitPlanMode", "Read", "SendUserFile", "ToolSearch", "Skill", "Workflow", "CronCreate",
             "CronDelete", "CronList", "ScheduleWakeup", "RemoteTrigger", "PushNotification")


def test_blackcat_allowlist_is_the_users():
    """BLACKCAT_TOOLS is exactly the user's list (Task is the Agent tool's old name)."""
    g = _guard_types()
    assert g.BLACKCAT_TOOLS == set(ALLOWLIST) - {"Task"}
    assert g.canonical_tool("Task") == "Agent"


@pytest.mark.parametrize("tool", ["Bash", "Write", "Edit"])
def test_blackcat_does_no_work_itself(env, tool):
    """BLACKCAT_MAX_OWN_STEPS defaults to 0: every Bash/Write/Edit call of BlackCat is
    refused, through both wirings, with a reason that names whom to dispatch; it spends no step."""
    s = sid()
    ti = {"command": "git status"} if tool == "Bash" else {"file_path": "/x/a.md"}
    for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
        p = run(rg(s, tool, tool_input=ti, agent_type="blackcat", tool_use_id="t-" + args[-1]),
                env, args=args)
        assert decision(p) == "deny", args
        r = reason(p)
        assert "only delegates" in r and "main-coder" in r and "explore" in r and "coder" in r, r
    assert not list((state(env, s) / "blackcat").glob("step.*"))
    # a subagent's call is untouched, whatever the knobs
    for extra in ({}, {"STACK_POLICY": "off"}, {"BLACKCAT_MAX_OWN_STEPS": "5"}):
        for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
            assert decision(run(rg(s, tool, tool_input=ti, agent_id="A1", agent_type="coder"), env,
                                args=args, extra=extra)) == "allow", (args, extra)
    # STACK_POLICY=off and BLACKCAT_MAX_OWN_STEPS > 0 no longer lift delegate-only (default on)
    for n, extra in enumerate(({"STACK_POLICY": "off"}, {"BLACKCAT_MAX_OWN_STEPS": "5"},
                               {"STACK_POLICY": "off", "BLACKCAT_MAX_OWN_STEPS": "5"},
                               {"STACK_BLACKCAT_DELEGATE_ONLY": "1", "BLACKCAT_MAX_OWN_STEPS": "5"},
                               {"STACK_BLACKCAT_DELEGATE_ONLY": "no", "STACK_POLICY": "off"})):
        for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
            p = run(rg(s, tool, prompt="d1", tool_input=ti, agent_type="blackcat",
                       tool_use_id="d-%d-%s" % (n, args[-1])), env, args=args, extra=extra)
            assert decision(p) == "deny" and "only delegates" in reason(p), (args, extra)
            if extra.get("STACK_POLICY") == "off":    # the user is told what does lift it
                assert "STACK_BLACKCAT_DELEGATE_ONLY" in json.loads(p.stdout)["systemMessage"]
    # only STACK_BLACKCAT_DELEGATE_ONLY=0 hands the decision back: the policy off allows ...
    lift = {"STACK_BLACKCAT_DELEGATE_ONLY": "0"}
    assert decision(run(rg(s, tool, tool_input=ti), env, args=["blackcat-guard"],
                        extra=dict(lift, STACK_POLICY="off"))) == "allow"
    # ... and an explicit own-work override (where the tools line grants the tool) is counted
    res = [decision(run(rg(s, tool, prompt="o1", tool_input=ti), env, args=["blackcat-guard"],
                        extra=dict(lift, BLACKCAT_MAX_OWN_STEPS="2"))) for _ in range(3)]
    assert res == ["allow", "allow", "deny"]
    # without the override, knob 0 alone keeps the old default (own-work cap 0): refused
    assert decision(run(rg(s, tool, prompt="o2", tool_input=ti), env, args=["blackcat-guard"],
                        extra=lift)) == "deny"


def test_delegate_only_with_policy_off_keeps_the_read_cap_and_lifts_the_rest(env):
    """With STACK_POLICY=off, delegate-only keeps BLACKCAT_MAX_READS (reading is BlackCat's one
    work tool) but no step cap: 30 ToolSearch calls pass, the 4th Read is refused, no step marker."""
    s, off = sid(), {"STACK_POLICY": "off"}
    res = [decision(run(rg(s, "Read", prompt="r1", tool_use_id="r%d" % i), env, args=["blackcat-guard"],
                        extra=off)) for i in range(4)]
    assert res == ["allow"] * 3 + ["deny"]
    p = run(rg(s, "Read", prompt="r1", tool_use_id="r9"), env, args=["blackcat-guard"], extra=off)
    assert "read limit (3" in reason(p) and "STACK_BLACKCAT_DELEGATE_ONLY" in json.loads(p.stdout)["systemMessage"]
    assert all(decision(run(rg(s, "ToolSearch", prompt="r1"), env, args=["blackcat-guard"], extra=off))
               == "allow" for _ in range(30))
    assert not list((state(env, s) / "blackcat").glob("step.*"))
    # both wirings see the same Read once (tool_use_id), so it counts once
    s2 = sid()
    for i in range(3):
        for args in (["blackcat-guard"], ["blackcat-guard", "--settings"]):
            ev = rg(s2, "Read", prompt="r2", agent_type="blackcat", tool_use_id="w%d" % i)
            assert decision(run(ev, env, args=args, extra=off)) == "allow", (i, args)


def test_delegate_only_internal_error_fails_closed_with_policy_off(env, tmp_path):
    """An exception inside blackcat-guard (state dir unusable) denies BlackCat's Read with the
    policy off as well, naming the knob that lifts it."""
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    p = run(rg(sid(), "Read"), env, args=["blackcat-guard"],
            extra={"STACK_POLICY": "off", "XDG_STATE_HOME": str(blocker)})
    assert decision(p) == "deny" and "stack guard error" in reason(p)
    assert "STACK_BLACKCAT_DELEGATE_ONLY" in json.loads(p.stdout)["systemMessage"]


def stop_ev(s, msg, **extra):
    ev = {"session_id": s, "hook_event_name": "Stop", "prompt_id": "u1", "stop_hook_active": False,
          "background_tasks": [{"id": "t1", "type": "subagent"}], "session_crons": []}
    if msg is not None:
        ev["last_assistant_message"] = msg
    ev.update(extra)
    return ev


def test_blackcat_reply_stop_hook_only_logs(env):
    """The reply-to-user check (Stop, blackcat.md): never blocks (no output, exit 0, whatever the
    input), logs a turn that ends with no text, never a turn with text, never a subagent's stop,
    never any message text."""
    s = sid()
    log = state(env, s) / "reply-check.jsonl"
    for msg in ("Dispatched scout; I'll relay the answer.", "  ok  "):
        p = run(stop_ev(s, msg), env, args=["blackcat-reply"])
        assert p.returncode == 0 and p.stdout == "" and p.stderr == ""
    assert not log.exists()
    for ev in (stop_ev(s, ""), stop_ev(s, "  \n "), stop_ev(s, None), stop_ev(s, 7)):
        p = run(ev, env, args=["blackcat-reply"])
        assert p.returncode == 0 and p.stdout == ""
    rows = [json.loads(x) for x in log.read_text().splitlines()]
    assert len(rows) == 4 and [r["field"] for r in rows] == [True, True, False, True]
    assert all(r["prompt_id"] == "u1" and r["background_tasks"] == 1 for r in rows)
    assert oct(log.stat().st_mode & 0o777) == "0o600"
    # a subagent's stop, another event, and garbage: nothing logged, nothing printed, exit 0
    for raw in (stop_ev(s, "", agent_id="A1"), dict(stop_ev(s, ""), hook_event_name="SubagentStop"),
                "{not json", "[]", "", json.dumps({"hook_event_name": "Stop"}) * 2):
        p = run(raw, env, args=["blackcat-reply"])
        assert p.returncode == 0 and p.stdout == "", raw
    assert len(log.read_text().splitlines()) == 4
    # an unusable state dir: still exit 0, no output (warns on stderr only)
    blocker = Path(env["XDG_STATE_HOME"]).parent / "blocker"
    blocker.write_text("x")
    p = run(stop_ev(sid(), ""), env, args=["blackcat-reply"], extra={"XDG_STATE_HOME": str(blocker)})
    assert p.returncode == 0 and p.stdout == "" and "blackcat-reply" in p.stderr


def test_blackcat_reply_hook_is_wired_log_only():
    """blackcat.md wires the Stop hook without --fail-closed (a check that cannot start must not
    hold the turn); settings.json wires no Stop hook (BlackCat's own frontmatter only)."""
    text = (ROOT / "dot-config" / "dot-claude" / "agents" / "blackcat.md").read_text().split("\n---\n", 1)[0]
    stop = text.split("\n  Stop:\n", 1)[1]
    cmd = json.loads('"%s"' % re.search(r'(?m)^\s+command:\s*"(.*)"\s*$', stop).group(1))
    assert cmd == '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" agent_guard blackcat-reply'
    assert "Stop" not in json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())["hooks"]


def test_blackcat_reads_count_as_steps(env):
    """Read is BlackCat's one work tool: each call is a step and a read (BLACKCAT_MAX_READS 3);
    the 9th call of any kind in one prompt is refused."""
    s = sid()
    extra = {}
    calls = ["Read", "Read", "Agent", "Read", "ToolSearch", "Agent", "Skill", "AskUserQuestion"]
    for tool in calls:
        p = (run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env, extra=extra)
             if tool == "Agent" else run(rg(s, tool, prompt="q1"), env, args=["blackcat-guard"]))
        assert decision(p) == "allow", tool
    for tool in ("ToolSearch", "AskUserQuestion", "Skill"):
        p = run(rg(s, tool, prompt="q1"), env, args=["blackcat-guard"])
        assert decision(p) == "deny" and "step limit (8 tool calls" in reason(p), tool
    p = run(rg(s, "Read", prompt="q1"), env, args=["blackcat-guard"])   # read cap (3) first
    assert decision(p) == "deny" and "read limit (3" in reason(p) and "explore" in reason(p)
    for tool in ("Bash", "Write"):                     # never BlackCat's, whatever is left
        p = run(rg(s, tool, prompt="q1"), env, args=["blackcat-guard"])
        assert decision(p) == "deny" and "only delegates" in reason(p), tool
    p = run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env, extra=extra)
    assert decision(p) == "deny" and "step limit" in reason(p)
    # SendMessage, like Agent, is counted by the main hook (with its resume reservation)
    p = run(dict(send(s, "X1"), agent_type="blackcat", prompt_id="q1"), env)
    assert decision(p) == "deny" and "step limit (8 tool calls" in reason(p)
    # reads alone stop at the read cap; the knob moves it; specialist tools never pass
    s2 = sid()
    res = [decision(run(rg(s2, "Read", prompt="q1"), env, args=["blackcat-guard"]))
           for _ in range(5)]
    assert res == ["allow"] * 3 + ["deny"] * 2
    res = [decision(run(rg(s2, "Read", prompt="q2"), env, args=["blackcat-guard"],
                        extra={"BLACKCAT_MAX_READS": "1"})) for _ in range(2)]
    assert res == ["allow", "deny"]
    assert decision(run(rg(s2, "Read", prompt="q3"), env, args=["blackcat-guard"],
                        extra={"BLACKCAT_MAX_READS": "0"})) == "deny"
    for tool in ("WebFetch", "NotebookEdit", "Monitor"):
        p = run(rg(sid(), tool, prompt="q1"), env, args=["blackcat-guard"])
        assert decision(p) == "deny" and "belongs to a specialist" in reason(p), tool


def test_blackcat_guard_subagent_passes_and_no_substring_bypass(env):
    s = sid()
    assert decision(run(rg(s, "Bash", agent_id="A1", agent_type="coder"), env,
                        args=["blackcat-guard"])) == "allow"
    ev = rg(s, "WebFetch")
    ev["tool_input"] = {"url": "https://x", "agent_id": "fake", "note": '"agent_id"'}
    assert decision(run(ev, env, args=["blackcat-guard"])) == "deny"


def test_blackcat_guard_steps_and_agent_never_denied(env):
    s = sid()
    res = [decision(run(rg(s, "ToolSearch"), env, args=["blackcat-guard"])) for _ in range(9)]
    assert res == ["allow"] * 8 + ["deny"]
    assert decision(run(rg(s, "Agent"), env, args=["blackcat-guard"])) == "allow"
    assert decision(run(rg(s, "ToolSearch", prompt="p2"), env, args=["blackcat-guard"])) == "allow"
    assert decision(run(rg(s, "ToolSearch"), env, args=["blackcat-guard"],
                        extra={"BLACKCAT_MAX_STEPS": "20"})) == "allow"


def test_blackcat_read_cap_holds_through_the_settings_wiring(env):
    """settings.json's `blackcat-guard --settings` wiring alone (each call claimed by it first)
    still holds BlackCat to BLACKCAT_MAX_READS: the read cap is not the frontmatter wiring's."""
    s = sid()
    res = [decision(run(rg(s, "Read", prompt="sr", agent_type="blackcat", tool_use_id="sr%d" % i),
                        env, args=["blackcat-guard", "--settings"])) for i in range(4)]
    assert res == ["allow"] * 3 + ["deny"]


NOT_BLACKCAT = [None, "", "main-coder", "claude", "general-purpose", "coder", "unknown"]


@pytest.mark.parametrize("agent_type", NOT_BLACKCAT)
def test_other_main_thread_agents_are_untouched_by_the_settings_wiring(env, agent_type):
    """Only BlackCat is delegate-only. settings.json runs `blackcat-guard --settings` on every
    main-thread call of every session; for any other agent (claude --agent main-coder, --agent
    claude, a typeless main thread, a foreign name) it returns at once: no decision, no output,
    no step/read/own-work counter, no state file, whatever the tool and however many calls."""
    s = sid()
    for tool in ("Bash", "Write", "Edit", "Read"):
        ti = {"command": "git status"} if tool == "Bash" else {"file_path": "/x/a.md"}
        for i in range(10):
            ev = rg(s, tool, prompt="nb", tool_input=ti, tool_use_id="nb-%s-%d" % (tool, i))
            if agent_type is not None:
                ev["agent_type"] = agent_type
            p = run(ev, env, args=["blackcat-guard", "--settings"])
            assert p.returncode == 0 and p.stdout == "" and p.stderr == "", (tool, i, p)
    for tool in ("WebFetch", "Grep", "NotebookEdit", "Monitor"):   # not on BlackCat's allowlist
        ev = rg(s, tool, prompt="nb", tool_use_id="nb-" + tool)
        if agent_type is not None:
            ev["agent_type"] = agent_type
        p = run(ev, env, args=["blackcat-guard", "--settings"])
        assert p.returncode == 0 and p.stdout == "", (tool, p)
    root = Path(env["XDG_STATE_HOME"])
    assert not root.exists() or not [f for f in root.rglob("*") if f.is_file()]


def test_blackcat_stays_restricted_through_the_settings_wiring(env):
    """The same calls from BlackCat through the same wiring are refused or counted."""
    s = sid()
    for tool in ("Bash", "Write", "Edit", "WebFetch", "Grep"):
        ti = {"command": "git status"} if tool == "Bash" else {"file_path": "/x/a.md"}
        p = run(rg(s, tool, tool_input=ti, agent_type="blackcat", tool_use_id="bc-" + tool), env,
                args=["blackcat-guard", "--settings"])
        assert decision(p) == "deny", tool
    res = [decision(run(rg(s, "Read", prompt="bc", agent_type="blackcat", tool_use_id="bcr%d" % i),
                        env, args=["blackcat-guard", "--settings"])) for i in range(4)]
    assert res == ["allow"] * 3 + ["deny"]


def test_the_unconditional_wiring_is_blackcat_md_only():
    """blackcat-guard without --settings (which acts on every main-thread call it sees) is wired
    only in blackcat.md's frontmatter, whose hooks run only while BlackCat is the session's agent
    (sub-agents.md, "Hooks in subagent frontmatter"); settings.json wires only `--settings`."""
    agents = sorted(p.name for p in (ROOT / "dot-config" / "dot-claude" / "agents").glob("*.md")
                    if "blackcat-guard" in p.read_text())
    assert agents == ["blackcat.md"]
    settings = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())
    cmds = [h["command"] for ev in settings["hooks"].values() for g in ev for h in g["hooks"]
            if "blackcat-guard" in h.get("command", "")]
    assert cmds and all(c.rstrip().endswith("blackcat-guard --settings") for c in cmds), cmds


def test_blackcat_spawn_caps_and_foreground_drop_key_on_blackcat(env):
    """BlackCat's step cap (BLACKCAT_MAX_STEPS, 8 here, dispatches included) and the
    run_in_background drop bind BlackCat, not any main thread: main-coder on the main thread spawns
    8 at its own fan-out cap and keeps a foreground child."""
    s = sid()
    res = [decision(run(pre_agent(s, "coder", parent="main-coder", prompt="mc"), env,
                        extra={"STACK_MAX_FANOUT_BY_TYPE": "main-coder=20"})) for _ in range(8)]
    assert res == ["allow"] * 8
    p = run(pre_agent(sid(), "coder", parent="main-coder", run_in_background=False), env,
            extra={"STACK_AGENT_LABEL": "off"})
    assert decision(p) == "allow" and "run_in_background" not in p.stdout
    p = run(pre_agent(sid(), "coder", parent="blackcat", run_in_background=False), env,
            extra={"STACK_AGENT_LABEL": "off"})
    assert "run_in_background" not in json.loads(p.stdout)["hookSpecificOutput"]["updatedInput"]


def test_blackcat_guard_steps_concurrent(env):
    s = sid()
    res = run_many([rg(s, "ToolSearch") for _ in range(FANOUT)], env, args=["blackcat-guard"])
    assert res.count("allow") == 8


def test_blackcat_hook_command_as_rendered(env, tmp_path):
    """blackcat.md's frontmatter hook runs the guard through the launcher, fail-closed (S2): render
    its command the way install.sh does and run it through a shell."""
    text = (ROOT / "dot-config" / "dot-claude" / "agents" / "blackcat.md").read_text()
    m = re.search(r'(?m)^\s+command:\s*"(.*)"\s*$', text)
    assert m, "blackcat.md has no hook command"
    cmd = json.loads('"%s"' % m.group(1))
    assert cmd == '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" --fail-closed agent_guard blackcat-guard'
    cmd = cmd.replace("__CLAUDE_DIR__", str(ROOT / "dot-config" / "dot-claude"))
    e = dict(env, STACK_PYTHON=sys.executable)
    s = sid()
    p = run(rg(s, "WebFetch"), e, cmd=["sh", "-c", cmd])
    assert decision(p) == "deny"
    p = run(rg(s, "SendMessage"), e, cmd=["sh", "-c", cmd])
    assert decision(p) == "allow"


# ---------------------------------------------------------------- model strip, logging
def test_model_strip(env):
    p = run(pre_agent(sid(), "coder", parent="blackcat", model="opus"), env)
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "model" not in out["updatedInput"]
    assert out["updatedInput"]["subagent_type"] == "coder"
    p = run(pre_agent(sid(), "coder", parent="blackcat", model="opus"), env,
            extra={"STRIP_AGENT_MODEL": "0", "STACK_AGENT_LABEL": "off"})
    assert p.stdout == ""


@pytest.mark.parametrize("mode", ["bypassPermissions", "acceptEdits", "plan"])
def test_agent_mode_input_is_left_alone(env, mode):
    """The Agent tool's `mode` is deprecated and ignored by Claude Code (2.1.287 schema: subagents
    inherit the session's permission mode), so the guard no longer strips it: `mode` alone causes
    no rewrite, and a rewrite for another reason (the label) keeps it."""
    for parent, aid in (("blackcat", None), ("main-coder", "M1")):
        p = run(pre_agent(sid(), "coder", parent=parent, agent_id=aid, mode=mode), env,
                extra={"STACK_AGENT_LABEL": "off"})
        assert decision(p) == "allow" and p.stdout == ""
        p = run(pre_agent(sid(), "coder", parent=parent, agent_id=aid, mode=mode), env)
        out = json.loads(p.stdout)["hookSpecificOutput"]
        assert out["updatedInput"]["mode"] == mode and out["updatedInput"]["subagent_type"] == "coder"
        assert "mode removed" not in out.get("permissionDecisionReason", "")


def test_shipped_spawn_defaults(bare_env):
    """No knobs set: BlackCat 24 steps (dispatches included), 3 reads and no own Bash/Write/Edit
    call per prompt; the per-type
    fan-out table."""
    env = bare_env
    s = sid()
    res = [decision(run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env))
           for _ in range(25)]
    assert res == ["allow"] * 24 + ["deny"]     # no dispatch cap: the step cap alone
    assert "step limit (24" in reason(run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env))
    s = sid()
    res = [decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"]))
           for _ in range(25)]
    assert res == ["allow"] * 24 + ["deny"]
    s = sid()
    res = [decision(run(rg(s, "Read", prompt="q1"), env, args=["blackcat-guard"]))
           for _ in range(4)]
    assert res == ["allow"] * 3 + ["deny"]
    for tool in ("Bash", "Write", "Edit"):
        assert decision(run(rg(s, tool, prompt="q2"), env, args=["blackcat-guard"])) == "deny"
    for parent, cap in (("orchestrator", 32), ("main-coder", 6),
                        ("ninja-coder", 5), ("researcher", 4), ("devops-engineer", 3), ("designer", 3)):
        s, child = sid(), ("scout" if parent in ("researcher", "devops-engineer", "designer") else "coder")
        res = [decision(run(pre_agent(s, child, parent=parent, agent_id="P1"), env))
               for _ in range(cap + 1)]
        assert res == ["allow"] * cap + ["deny"], (parent, res)


def test_orchestrator_fanout_32_from_settings_and_env_lowers_it(bare_env):
    """settings.json's STACK_MAX_FANOUT_BY_TYPE carries orchestrator=32 (32 running children, the
    33rd refused, the knob named); a lower value in the env var still lowers it."""
    shipped = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())["env"]
    for value, cap in ((shipped["STACK_MAX_FANOUT_BY_TYPE"], 32), ("orchestrator=5", 5)):
        s, extra = sid(), {"STACK_MAX_FANOUT_BY_TYPE": value}
        res = [decision(run(pre_agent(s, "coder", parent="orchestrator", agent_id="O1"),
                            bare_env, extra=extra)) for _ in range(cap)]
        assert res == ["allow"] * cap, (value, res)
        p = run(pre_agent(s, "coder", parent="orchestrator", agent_id="O1"), bare_env, extra=extra)
        assert decision(p) == "deny" and "orchestrator=%d" % cap in reason(p), (value, reason(p))


def _guard_types():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "agent_guard_types", str(ROOT / "dot-config" / "dot-claude" / "hooks" / "agent_guard.py"))
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    return g


TOP_TIER_PHRASES = {
    "ninja-coder.md": ["You are the top of the coding chain"],
    "orchestrator.md": ["coder → main-coder → ninja-coder (the top tier"],
    "blackcat.md": ["a near-impossible problem → ninja-coder with a dossier"],
    "main-coder.md": ["ninja-coder failed too → STATUS: partial"],
}


@pytest.mark.parametrize("fname", sorted(TOP_TIER_PHRASES))
def test_ninja_coder_is_the_top_tier_in_prompts(fname):
    """ninja-coder tops the coding chain (2026-10-04): routing and escalation name it last, and
    no plan step or escalation goes past it."""
    text = re.sub(r"\s+", " ", (ROOT / "dot-config" / "dot-claude" / "agents" / fname).read_text())
    for phrase in TOP_TIER_PHRASES[fname]:
        assert phrase in text, (fname, phrase)


def test_blackcat_foreground_dropped(env):
    # Claude Desktop / Agent SDK: a foreground child blocks the BlackCat main thread for its whole
    # run, so the hook drops `run_in_background: false` (the child starts in the background)
    p = run(pre_agent(sid(), "coder", parent="blackcat", run_in_background=False), env)
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "allow"
    assert "run_in_background" not in out["updatedInput"]
    assert out["updatedInput"]["subagent_type"] == "coder"
    # both rewrites in one decision
    p = run(pre_agent(sid(), "coder", parent="blackcat", run_in_background=False, model="opus"), env)
    ui = json.loads(p.stdout)["hookSpecificOutput"]["updatedInput"]
    assert "run_in_background" not in ui and "model" not in ui
    # an explicit background request, a subagent's foreground call, a plain main thread and the
    # knob set to 0 are left alone (labels off: test_agent_label.py covers them)
    off = {"STACK_AGENT_LABEL": "off"}
    assert run(pre_agent(sid(), "coder", parent="blackcat", run_in_background=True), env,
               extra=off).stdout == ""
    assert run(pre_agent(sid(), "coder", parent="orchestrator", agent_id="O1",
                         run_in_background=False), env, extra=off).stdout == ""
    assert run(pre_agent(sid(), "coder", run_in_background=False), env, extra=off).stdout == ""
    assert run(pre_agent(sid(), "coder", parent="blackcat", run_in_background=False), env,
               extra=dict(off, BLACKCAT_BACKGROUND="0")).stdout == ""


def test_guard_log(env):
    s = sid()
    run(lifecycle(s, "SubagentStart", "A", "coder"), env, extra={"STACK_GUARD_LOG": "1"})
    run(lifecycle(s, "SubagentStart", "B", "coder"), env)
    lines = (state(env, s) / "guard.log").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["agent_id"] == "A"


def test_lifecycle_never_outputs_decision(env):
    s = sid()
    for ev in (lifecycle(s, "SubagentStart", "G", "ninja-coder"),
               lifecycle(s, "SubagentStop", "G", "ninja-coder"),
               {"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": "p"},
               post_agent(s, "coder", "C")):
        p = run(ev, env)
        assert p.returncode == 0 and "permissionDecision" not in p.stdout and "decision" not in p.stdout
        if ev["hook_event_name"] == "SubagentStart":    # its start time only (STACK_AGENT_STARTED)
            assert set(json.loads(p.stdout)["hookSpecificOutput"]) == {"hookEventName",
                                                                        "additionalContext"}
        else:
            assert p.stdout == ""


# ---------------------------------------------------------------- blackcat dispatch window
def test_blackcat_dispatch_window(env):
    s = sid()
    assert decision(run(pre_agent(s, "scout", parent="blackcat", prompt="w1"), env)) == "allow"
    assert decision(run(pre_agent(s, "oracle", parent="blackcat", prompt="w1"), env)) == "allow"
    # the burst is over once the first dispatch is older than the window
    m = state(env, s) / "blackcat" / "dispatch.w1.0"
    m.write_text(str(time.time() - 120))
    p = run(pre_agent(s, "coder", parent="blackcat", prompt="w1"), env)
    assert decision(p) == "deny" and "together in one message" in reason(p)
    # a longer window lets it through; a new prompt starts a new burst
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="w1"), env,
                        extra={"BLACKCAT_DISPATCH_WINDOW_S": "600"})) == "allow"
    assert decision(run(pre_agent(s, "coder", parent="blackcat", prompt="w2"), env)) == "allow"
    # a marker caught between O_EXCL create and its timestamp write counts as brand new
    m.write_text("")
    assert decision(run(pre_agent(s, "writer", parent="blackcat", prompt="w1"), env)) == "allow"


# ---------------------------------------------------------------- no self-spawn, no copies
def test_no_agent_spawns_its_own_type_and_copy_types_are_gone(env):
    """The copy types (researcher-copy, coder-copy) were retired 2026-10-04: no caller may spawn
    them, and no agent spawns its own type."""
    s = sid()
    run(post_agent(s, "researcher", "R1", agent_id="O1", parent="orchestrator"), env)
    p = run(pre_agent(s, "researcher", parent="researcher", agent_id="R1"), env)
    assert decision(p) == "deny" and "Spawn policy" in reason(p)
    for parent, aid in (("blackcat", None), ("orchestrator", "O1"), ("researcher", "R1"),
                        ("main-coder", "M1")):
        for child in ("researcher-copy", "coder-copy"):
            p = run(pre_agent(s, child, parent=parent, agent_id=aid), env)
            assert decision(p) == "deny", (parent, child)


# ---------------------------------------------------------------- fan-out caps
def test_fanout_cap_concurrent(env):
    for limit in ("3", "5"):
        s = sid()
        evs = [pre_agent(s, "coder", parent="main-coder", agent_id="SC") for _ in range(FANOUT)]
        res = run_many(evs, env, extra={} if limit == "3" else {"STACK_MAX_FANOUT": limit})
        assert res.count("allow") == int(limit), res


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
    # leases whose call never reported back end at the STACK_LEASE_TTL_S ceiling
    time.sleep(1.1)
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env,
                        extra=dict(extra, STACK_LEASE_TTL_S="1"))) == "allow"


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
        run(post_agent(s, "coder", "K%d" % i, agent_id="SC", parent="main-coder"), env)
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="SC"), env)
    assert decision(p) == "deny" and "Fan-out limit" in reason(p)
    run({"session_id": s, "hook_event_name": "SessionStart", "source": "resume"}, env)
    assert not (state(env, s) / "fanout").exists()
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="SC"), env)) == "allow"
    # a resumed child (SubagentStart of a stopped agent) runs in the background and counts again
    run(lifecycle(s, "SubagentStart", "K0", "coder"), env)
    reg = json.loads((state(env, s) / "agents" / "K0.json").read_text())
    assert "stopped" not in reg and reg["bg"] is True and reg["parent"] == "SC"


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
    (cfg / "hooks" / "stack_io.py").write_text((GUARD.parent / "stack_io.py").read_text())
    settings = (ROOT / "dot-config" / "dot-claude" / "settings.json").read_text()
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
    s = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())
    matchers = [g["matcher"] for g in s["hooks"]["PreToolUse"]]
    rx = next(re.compile("^(?:%s)$" % m) for m in matchers if "ctx_index" in m)
    for tool in ("mcp__context-mode__ctx_index", "mcp__markitdown__convert_to_markdown",
                 "mcp__magg__docling_convert_document_into_docling_document",
                 "mcp__playwright__browser_navigate", "mcp__magg__pw_browser_file_upload"):
        assert rx.match(tool), tool
    for tool in ("mcp__context-mode__ctx_search", "mcp__context-mode__ctx_fetch_and_index", "Read"):
        assert not rx.match(tool), tool


# ---------------------------------------------------------------- spawn leases (review #1 ii-iv)
def leases(env, s, caller):
    folder = state(env, s) / "fanout" / caller
    return sorted(p.stem for p in folder.iterdir()) if folder.exists() else []


def reg_of(env, s, aid):
    return json.loads((state(env, s) / "agents" / (aid + ".json")).read_text())


def age_leases(env, s, caller, seconds):
    for f in (state(env, s) / "fanout" / caller).iterdir():
        obj = json.loads(f.read_text())
        obj["ts"] = time.time() - seconds
        f.write_text(json.dumps(obj))


def test_resume_holds_a_reservation_until_it_starts(env):
    s = sid()
    extra = {"STACK_MAX_FANOUT_BY_TYPE": "orchestrator=2"}
    w = pre_agent(s, "writer", parent="orchestrator", agent_id="O1")          # O1's earlier child
    assert decision(run(w, env, extra=extra)) == "allow"
    run(lifecycle(s, "SubagentStart", "W1", "writer"), env)
    run(lifecycle(s, "SubagentStop", "W1", "writer"), env)
    run(post_agent(s, "writer", "W1", agent_id="O1", parent="orchestrator", status="completed",
                   tool_use_id=w["tool_use_id"]), env)
    fg = pre_agent(s, "coder", parent="orchestrator", agent_id="O1")         # foreground, in flight
    assert decision(run(fg, env, extra=extra)) == "allow"
    assert leases(env, s, "O1") == [fg["tool_use_id"]]
    # resuming W1 checks O1's cap and reserves the slot until W1 starts ...
    assert decision(run(send(s, "W1", agent_id="O1"), env, extra=extra)) == "allow"
    assert leases(env, s, "O1") == sorted([fg["tool_use_id"], "resume-W1"])
    res = json.loads((state(env, s) / "fanout" / "O1" / "resume-W1.json").read_text())
    assert res["type"] == "writer" and res["resume"] == "W1"
    p = run(pre_agent(s, "scout", parent="orchestrator", agent_id="O1"), env, extra=extra)
    assert decision(p) == "deny" and "orchestrator=2" in reason(p)
    # ... where the reservation becomes a live background child: counted once, never twice
    run(lifecycle(s, "SubagentStart", "W1", "writer"), env)
    assert leases(env, s, "O1") == [fg["tool_use_id"]]
    rec = reg_of(env, s, "W1")
    assert rec["parent"] == "O1" and rec["bg"] is True and "stopped" not in rec
    # O1 runs the leased coder and the resumed writer: at its cap of 2
    p = run(pre_agent(s, "scout", parent="orchestrator", agent_id="O1"), env, extra=extra)
    assert decision(p) == "deny" and "orchestrator=2" in reason(p)
    # the foreground call reports back: its lease goes, and a finished child never counts
    run(post_agent(s, "coder", "K1", agent_id="O1", parent="orchestrator", status="completed",
                   tool_use_id=fg["tool_use_id"]), env)
    assert leases(env, s, "O1") == [] and reg_of(env, s, "K1")["bg"] is False
    assert decision(run(pre_agent(s, "scout", parent="orchestrator", agent_id="O1"), env,
                        extra=extra)) == "allow"


def test_parents_never_swap(env):
    s = sid()
    for r in ("R1", "R2"):                         # two researchers at the same depth
        run(post_agent(s, "researcher", r, agent_id="O1", parent="orchestrator"), env)
    a = pre_agent(s, "scout", parent="researcher", agent_id="R1")
    b = pre_agent(s, "scout", parent="researcher", agent_id="R2")
    assert run_many([a, b], env) == ["allow", "allow"]
    # the children start in the other order; SubagentStart names no parent and links nothing
    run(lifecycle(s, "SubagentStart", "X2", "scout"), env)
    run(lifecycle(s, "SubagentStart", "X1", "scout"), env)
    assert "parent" not in reg_of(env, s, "X1") and "parent" not in reg_of(env, s, "X2")
    assert leases(env, s, "R1") == [a["tool_use_id"]] and leases(env, s, "R2") == [b["tool_use_id"]]
    # each parent's own PostToolUse records its own child
    run(post_agent(s, "scout", "X2", agent_id="R2", parent="researcher",
                   tool_use_id=b["tool_use_id"]), env)
    run(post_agent(s, "scout", "X1", agent_id="R1", parent="researcher",
                   status="completed", tool_use_id=a["tool_use_id"]), env)
    assert reg_of(env, s, "X1")["parent"] == "R1" and reg_of(env, s, "X2")["parent"] == "R2"
    assert leases(env, s, "R1") == [] and leases(env, s, "R2") == []
    # a stray event naming another caller never moves a child
    run(post_agent(s, "scout", "X1", agent_id="R2", parent="researcher"), env)
    assert reg_of(env, s, "X1")["parent"] == "R1"


def test_foreground_counts_hold_past_120s_without_subagent_start(env):
    s = sid()
    evs = [pre_agent(s, "coder", parent="main-coder", agent_id="SC") for _ in range(3)]
    for ev in evs:
        assert decision(run(ev, env)) == "allow"
    age_leases(env, s, "SC", 3600)     # an hour-long foreground run: no SubagentStart, no report
    p = run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env)
    assert decision(p) == "deny" and "3 children" in reason(p)
    # one call reports back: its slot frees
    run(post_agent(s, "coder", "K0", agent_id="SC", parent="main-coder", status="completed",
                   tool_use_id=evs[0]["tool_use_id"]), env)
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env)) == "allow"
    # the STACK_LEASE_TTL_S ceiling (6 h) voids leases whose call never reported back
    age_leases(env, s, "SC", 21601)
    assert len(leases(env, s, "SC")) == 3
    assert decision(run(pre_agent(s, "scout", parent="main-coder", agent_id="SC"), env)) == "allow"
    assert len(leases(env, s, "SC")) == 1


def test_stale_leases_voided_when_the_caller_stops(env):
    s = sid()
    run(post_agent(s, "main-coder", "SC3"), env)       # TaskStop resolves its target in the registry
    stops = {
        "SC1": lifecycle(s, "SubagentStop", "SC1", "main-coder"),
        "SC2": lifecycle(s, "StopFailure", "SC2", "main-coder", error="rate_limit"),
        "SC3": {"session_id": s, "hook_event_name": "PostToolUse", "tool_name": "TaskStop",
                "tool_input": {"task_id": "SC3"}, "tool_response": {"task_id": "SC3"}},
    }
    for caller in list(stops) + ["OTHER"]:
        for _ in range(2):
            assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id=caller),
                                env)) == "allow"
    for caller, ev in stops.items():
        assert len(leases(env, s, caller)) == 2
        run(ev, env)
        assert leases(env, s, caller) == [], caller
    assert len(leases(env, s, "OTHER")) == 2        # nobody else's leases go


@pytest.mark.parametrize("parent,child,cap", [
    ("main-coder", "coder", 3), ("orchestrator", "coder", 8), ("planner", "scout", 8),
    ("researcher", "scout", 3)])
def test_fanout_cap_per_type(env, parent, child, cap):
    s = sid()
    res = run_many([pre_agent(s, child, parent=parent, agent_id="P") for _ in range(12)], env)
    assert res.count("allow") == cap, res
    p = run(pre_agent(s, child, parent=parent, agent_id="P"), env)
    assert decision(p) == "deny" and "Fan-out limit" in reason(p)


def test_fanout_by_type_parsing(env):
    extra = {"STACK_MAX_FANOUT_BY_TYPE":
             " 'Orchestrator = 2 ; planner=1,\n bogus, x=-1, researcher=5,'"}
    s = sid()
    res = run_many([pre_agent(s, "coder", parent="orchestrator", agent_id="O") for _ in range(6)],
                   env, extra=extra)
    assert res.count("allow") == 2
    assert decision(run(pre_agent(s, "scout", parent="planner", agent_id="PL"), env,
                        extra=extra)) == "allow"
    p = run(pre_agent(s, "scout", parent="planner", agent_id="PL"), env, extra=extra)
    assert decision(p) == "deny" and "planner=1" in reason(p)
    res = run_many([pre_agent(s, "scout", parent="researcher", agent_id="RC")
                    for _ in range(8)], env, extra=extra)
    assert res.count("allow") == 5
    # malformed items are skipped with a warning; everything else keeps STACK_MAX_FANOUT
    p = run(pre_agent(sid(), "coder", parent="main-coder", agent_id="M"), env, extra=extra)
    assert decision(p) == "allow"
    assert "ignoring 'bogus'" in p.stderr and "ignoring 'x=-1'" in p.stderr
    # set but empty: no per-type overrides at all
    s2 = sid()
    res = run_many([pre_agent(s2, "coder", parent="orchestrator", agent_id="O") for _ in range(8)],
                   env, extra={"STACK_MAX_FANOUT_BY_TYPE": ""})
    assert res.count("allow") == 3


def test_resume_cap_uses_per_type_caps(env):
    s = sid()
    for i in range(8):                              # orchestrator O1 at its cap of 8 ...
        run(post_agent(s, "coder", "K%d" % i, agent_id="O1", parent="orchestrator"), env)
    run(post_agent(s, "writer", "W", agent_id="O1", parent="orchestrator", status="completed"),
        env)
    run(lifecycle(s, "SubagentStop", "W", "writer"), env)     # ... and a finished 9th child
    p = run(send(s, "W", agent_id="O1"), env)
    assert decision(p) == "deny" and "orchestrator=8" in reason(p)
    run(lifecycle(s, "SubagentStop", "K0", "coder"), env)
    assert decision(run(send(s, "W", agent_id="O1"), env)) == "allow"


def test_no_depth_check_from_spawn_meta_for_a_running_foreground_caller(env, tmp_path):
    """A caller whose depth only its meta.json knows (spawnDepth 4 at a limit of 4) is not refused,
    and PreToolUse(Agent) writes no depth from meta.json: Claude Code enforces the limit itself."""
    s = sid()
    sub = tmp_path / "p" / s / "subagents"
    sub.mkdir(parents=True)
    main = tmp_path / "p" / (s + ".jsonl")
    main.write_text("")
    (sub / "agent-F1.meta.json").write_text(json.dumps({"agentType": "main-coder", "spawnDepth": 4}))
    four = {"CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH": "4"}
    p = run(dict(pre_agent(s, "scout", parent="main-coder", agent_id="F1"), transcript_path=str(main)),
            env, extra=four)
    assert decision(p) == "allow"
    assert not (state(env, s) / "agents" / "F1.json").exists()


# ---------------------------------------------------------------- BlackCat: 8 steps, dispatches included
def test_blackcat_steps_count_dispatches(env):
    s = sid()
    for _ in range(4):        # 4 dispatches (counted by the main hook) + 4 other tools = 8
        assert decision(run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env)) == "allow"
        assert decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) \
            == "allow"
    p = run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])
    assert decision(p) == "deny" and "step limit (8 tool calls per prompt" in reason(p)
    # the 9th call as a dispatch is refused by the step limit as well
    p = run(pre_agent(s, "scout", parent="blackcat", prompt="q1"), env)
    assert decision(p) == "deny" and "step limit" in reason(p)
    assert len(leases(env, s, "main")) == 4           # a refused call leaves no lease
    # 8 dispatches alone use the whole allowance; a new prompt_id starts over
    s2, extra = sid(), {}
    res = [decision(run(pre_agent(s2, "scout", parent="blackcat", prompt="q1"), env, extra=extra))
           for _ in range(9)]
    assert res == ["allow"] * 8 + ["deny"]
    assert decision(run(rg(s2, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) == "deny"
    assert decision(run(pre_agent(s2, "scout", parent="blackcat", prompt="q2"), env,
                        extra=extra)) == "allow"
    assert decision(run(rg(s2, "ToolSearch", prompt="q2"), env, args=["blackcat-guard"])) == "allow"


def test_blackcat_steps_concurrent_dispatches(env):
    s = sid()
    res = run_many([pre_agent(s, "scout", parent="blackcat", prompt="q1") for _ in range(FANOUT)],
                   env)
    assert res.count("allow") == 8, res
    names = [p.name.split(".")[0] for p in (state(env, s) / "blackcat").iterdir()]
    assert names.count("step") == 8 and names.count("dispatch") == 8   # losers rolled back


def test_blackcat_refused_dispatch_spends_no_step(env):
    s = sid()
    p = run(pre_agent(s, "general-purpose", parent="blackcat", prompt="q1"), env)
    assert decision(p) == "deny" and "general-purpose" in reason(p)
    folder = state(env, s) / "blackcat"
    assert not folder.exists() or not list(folder.iterdir())


# ---------------------------------------------------------------- token budgets
BUDGET = {"STACK_PROMPT_CTX_BUDGET": "1000", "STACK_SESSION_CTX_BUDGET": "100000"}


@pytest.fixture
def sess(tmp_path):
    """A session's transcripts laid out like ~/.claude/projects/<project>/: the main transcript
    <session>.jsonl and the subagents' own <session>/subagents/agent-<id>.jsonl."""
    s = sid()
    proj = tmp_path / "projects" / "-tmp-proj"
    (proj / s / "subagents").mkdir(parents=True)
    main = proj / (s + ".jsonl")
    main.write_text(json.dumps({"type": "user", "message": {"role": "user", "content": "hi"}}) + "\n")
    return s, main, proj / s / "subagents"


def call_line(mid, tokens, end="\n"):
    """One transcript line of an API call whose context (input + cache_creation + cache_read) is
    `tokens`; output tokens never count."""
    return json.dumps({"type": "assistant", "requestId": "req_" + mid, "uuid": uuid.uuid4().hex,
                       "message": {"id": mid, "type": "message", "role": "assistant",
                                   "content": [{"type": "text", "text": "x"}],
                                   "usage": {"input_tokens": tokens // 4,
                                             "cache_creation_input_tokens": tokens // 4,
                                             "cache_read_input_tokens": tokens - 2 * (tokens // 4),
                                             "output_tokens": 999}}}) + end


def append(path, text):
    with open(path, "a") as f:
        f.write(text)


def tool_ev(s, main, tool, agent_id="A1", prompt="p1", **ti):
    ev = {"session_id": s, "hook_event_name": "PreToolUse", "tool_name": tool,
          "tool_use_id": "tu-" + uuid.uuid4().hex[:8], "prompt_id": prompt,
          "transcript_path": str(main), "cwd": str(main.parent), "tool_input": ti}
    if agent_id:
        ev["agent_id"], ev["agent_type"] = agent_id, "coder"
    return ev


def prompt_ev(s, main, pid):
    return {"session_id": s, "hook_event_name": "UserPromptSubmit", "prompt_id": pid,
            "prompt": "go", "transcript_path": str(main), "cwd": str(main.parent)}


def budget_run(ev, env, extra=None):
    """The settings.json wiring for every tool: `agent_guard.py budget`."""
    return run(ev, env, args=["budget"], extra=dict(BUDGET, **(extra or {})))


def test_budget_prompt_cap_denies_and_a_new_prompt_resets(env, sess):
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "allow"
    append(main, call_line("m1", 400))
    append(subs / "agent-a1.jsonl", call_line("m2", 500))
    assert decision(budget_run(tool_ev(s, main, "Bash", command="ls"), env)) == "allow"   # 900
    append(subs / "agent-a2.jsonl", call_line("m3", 200))                               # 1,100
    p = budget_run(tool_ev(s, main, "Bash", command="ls"), env)
    assert decision(p) == "deny"
    assert reason(p).startswith("Prompt token budget reached") and "1,100" in reason(p)
    assert "STACK_PROMPT_CTX_BUDGET=1000" in reason(p) and "STATUS: partial" in reason(p)
    msg = json.loads(p.stdout)["systemMessage"]
    # the limit comes from the session's limits snapshot (here the env override it recorded)
    assert "STACK_PROMPT_CTX_BUDGET" in msg and "stack_limits.py show" in msg
    assert "install.sh" not in msg
    p = budget_run(tool_ev(s, main, "Read", agent_id=None, file_path="x"), env)   # BlackCat
    assert decision(p) == "deny" and "answer the user now" in reason(p)
    # the main hook's own tools check it too, before any lease
    p = run(tool_ev(s, main, "Agent", subagent_type="scout", prompt="x", description="x"), env,
            extra=BUDGET)
    assert decision(p) == "deny" and "Prompt token budget" in reason(p)
    assert leases(env, s, "A1") == []
    # ... so `budget` mode leaves the main hook's tools alone
    assert decision(budget_run(tool_ev(s, main, "Agent", subagent_type="scout"), env)) == "allow"
    # a new human prompt starts a new prompt budget
    run(prompt_ev(s, main, "p2"), env, extra=BUDGET)
    assert decision(budget_run(tool_ev(s, main, "Bash", prompt="p2", command="ls"), env)) \
        == "allow"
    st = json.loads((state(env, s) / "budget.json").read_text())
    assert st["total"] == 1100 and st["prompt_base"] == 1100 and st["prompt_id"] == "p2"


def test_budget_session_cap_spans_prompts(env, sess):
    s, main, subs = sess
    extra = {"STACK_PROMPT_CTX_BUDGET": "0", "STACK_SESSION_CTX_BUDGET": "1000"}
    run(prompt_ev(s, main, "p1"), env, extra=extra)
    append(subs / "agent-a1.jsonl", call_line("m1", 600))
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env, extra=extra)) == "allow"
    run(prompt_ev(s, main, "p2"), env, extra=extra)
    append(main, call_line("m2", 600))
    p = budget_run(tool_ev(s, main, "Read", prompt="p2", file_path="x"), env, extra=extra)
    assert decision(p) == "deny" and reason(p).startswith("Session token budget reached")
    assert "STACK_SESSION_CTX_BUDGET=1000" in reason(p)
    msg = json.loads(p.stdout)["systemMessage"]
    assert "Start a new session" in msg and "stack_limits.py show" in msg


def test_budget_never_blocks_reporting(env, sess, tmp_path):
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    append(main, call_line("m1", 5000))
    scratch = tmp_path / "scratchpad"
    allowed = [("SubagentHandback", {"message": "done"}), ("TaskStop", {"task_id": "x"}),
               ("AskUserQuestion", {"questions": []}),
               ("ToolSearch", {"query": "select:SubagentHandback"}),
               ("ToolSearch", {"query": "select:TaskStop"}),
               ("Write", {"file_path": str(main.parent / ".claude-work" / "job" / "report.md")}),
               ("Edit", {"file_path": ".claude-work/job/plan.md"}),
               ("Write", {"file_path": str(scratch / "out.md")})]
    for tool, ti in allowed:
        ev = dict(tool_ev(s, main, tool, **ti), scratchpad_dir=str(scratch))
        assert decision(budget_run(ev, env)) == "allow", tool
    refused = [("Write", {"file_path": str(tmp_path / "elsewhere.md")}),
               ("Edit", {"file_path": str(main.parent / "src.py")}),
               ("Write", {"file_path": ".claude-work/../escape.md"}),
               ("ToolSearch", {"query": "select:WebSearch"}), ("Bash", {"command": "ls"}),
               ("WebSearch", {"query": "x"}), ("mcp__exa__web_search_exa", {"query": "x"}),
               ("mcp__conductor__AskUserQuestion", {}),      # Conductor dropped 2026-10-04
               ("Read", {"file_path": "x"})]
    for tool, ti in refused:
        ev = dict(tool_ev(s, main, tool, **ti), scratchpad_dir=str(scratch))
        assert decision(budget_run(ev, env)) == "deny", tool


def test_budget_counts_each_call_once_and_only_complete_lines(env, sess):
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    append(main, call_line("m1", 600) * 3)       # one API call written as three content blocks
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "allow"
    append(main, call_line("m2", 500, end=""))   # still being written
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "allow"
    append(main, "\n")
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "deny"
    st = json.loads((state(env, s) / "budget.json").read_text())
    assert st["total"] == 1100 and st["files"][str(main)]["off"] == main.stat().st_size


def test_budget_fails_open(env, sess):
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    # unreadable lines are skipped with a warning, never a denial
    append(main, '{"type": "assistant", "message": {broken\n')
    append(main, json.dumps({"type": "assistant", "requestId": "r", "message": {
        "id": "m", "usage": {"input_tokens": "lots"}}}) + "\n")
    p = budget_run(tool_ev(s, main, "Read", file_path="x"), env)
    assert decision(p) == "allow" and "could not be read" in p.stderr
    # no transcript_path: not checked
    ev = tool_ev(s, main, "Read", file_path="x")
    del ev["transcript_path"]
    p = budget_run(ev, env)
    assert decision(p) == "allow" and "transcript_path" in p.stderr
    # a transcript cut short or replaced goes on from its end: nothing is counted twice
    append(subs / "agent-a1.jsonl", call_line("m1", 600) + call_line("m2", 300))
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "allow"   # 900
    (subs / "agent-a1.jsonl").write_text(call_line("m1", 600))
    p = budget_run(tool_ev(s, main, "Read", file_path="x"), env)
    assert decision(p) == "allow" and "truncated" in p.stderr
    assert json.loads((state(env, s) / "budget.json").read_text())["total"] == 900
    append(main, call_line("m9", 5000))
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "deny"
    # STACK_POLICY=off, or both budgets 0: nothing is refused
    over = tool_ev(s, main, "Read", file_path="x")
    assert decision(budget_run(over, env, extra={"STACK_POLICY": "off"})) == "allow"
    # the budgets are fixed when the session's limits snapshot is written (its first event here):
    # 0 set now waits for the next session; a session started with both 0 refuses nothing
    off = {"STACK_PROMPT_CTX_BUDGET": "0", "STACK_SESSION_CTX_BUDGET": "0"}
    assert decision(budget_run(over, env, extra=off)) == "deny"
    s2 = sid()
    main2 = main.parent / (s2 + ".jsonl")
    main2.write_text(call_line("m1", 5000))
    assert decision(budget_run(tool_ev(s2, main2, "Read", file_path="x"), env, extra=off)) \
        == "allow"
    # unreadable hook input: allowed (the budget fails open; the main hook fails closed)
    p = run("{not json", env, args=["budget"])
    assert p.returncode == 0 and p.stdout == ""


def test_budget_main_thread_starts_a_prompt_the_hook_missed(env, sess):
    s, main, subs = sess
    append(subs / "agent-a1.jsonl", call_line("m1", 1200))      # no UserPromptSubmit recorded
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env)) == "deny"
    # BlackCat's own call carries the prompt being processed: its first sight starts the budget
    assert decision(budget_run(tool_ev(s, main, "Read", agent_id=None, prompt="p9",
                                       file_path="x"), env)) == "allow"
    assert decision(budget_run(tool_ev(s, main, "Read", prompt="p9", file_path="x"), env)) \
        == "allow"


def session_start(ev, env, extra=None):
    """SessionStart as Claude Code delivers it: to the settings.json groups whose matcher matches
    the event's source (hooks.md:1120-1122), and to no other. Returns how many runs it made."""
    s = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())
    n = 0
    for g in s["hooks"]["SessionStart"]:
        m = g.get("matcher") or "*"
        if m != "*" and not re.fullmatch(m, ev["source"]):
            continue
        for h in g["hooks"]:
            if h["command"].endswith('stack-hook" agent_guard'):
                assert run(ev, env, extra=extra).returncode == 0
                n += 1
    return n


def test_budget_catches_up_on_resume_and_forks_start_at_the_end(env, sess):
    s, main, subs = sess
    append(main, call_line("m1", 700))
    append(subs / "agent-a1.jsonl", call_line("m2", 700))
    extra = {"STACK_PROMPT_CTX_BUDGET": "0", "STACK_SESSION_CTX_BUDGET": "1000"}
    start = {"session_id": s, "hook_event_name": "SessionStart", "transcript_path": str(main),
             "cwd": str(main.parent)}
    assert session_start(dict(start, source="resume"), env, extra=extra) == 1
    assert json.loads((state(env, s) / "budget.json").read_text())["total"] == 1400
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env, extra=extra)) \
        == "deny"
    append(main, call_line("m4", 400))                # the main transcript alone: 1,100 > 1,000
    f = sid()                                         # a fork: the copied history is not its own
    fmain = main.parent / (f + ".jsonl")
    fmain.write_text(main.read_text())
    # delivered only if settings.json's SessionStart matcher lists fork
    session_start(dict(start, session_id=f, transcript_path=str(fmain), source="fork"), env,
                  extra=extra)
    ev = dict(tool_ev(f, fmain, "Read", file_path="x"))
    assert decision(budget_run(ev, env, extra=extra)) == "allow"
    append(fmain, call_line("m3", 1000))
    assert decision(budget_run(ev, env, extra=extra)) == "deny"


def test_budget_hook_wired_for_every_tool():
    s = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())
    groups = [g for g in s["hooks"]["PreToolUse"]
              if any(h["command"].endswith('--fail-closed agent_guard budget') for h in g["hooks"])]
    assert len(groups) == 1 and groups[0]["matcher"] == "*"
    assert all("if" not in h for h in groups[0]["hooks"])
    # SessionStart reaches the guard for startup and resume (locks, leases, registry) and for fork
    # (a fork counts only what it adds; without the event it inherits its parent's history)
    starts = [g.get("matcher") or "*" for g in s["hooks"]["SessionStart"]
              if any(h["command"].endswith('stack-hook" agent_guard') for h in g["hooks"])]
    for source in ("startup", "resume", "fork"):
        assert any(m == "*" or re.fullmatch(m, source) for m in starts), (source, starts)


def test_check_budget_cli(env, sess, tmp_path):
    s, main, subs = sess
    append(main, call_line("m1", 10) * 2)
    append(subs / "agent-a1.jsonl", call_line("m2", 20))
    p = run("", env, args=["--check-budget", str(main)])
    assert p.returncode == 0 and "ok (2 API calls, 30 context tokens" in p.stdout
    drift = tmp_path / "drift.jsonl"                  # usage renamed: the budgets would see nothing
    drift.write_text(json.dumps({"type": "assistant", "requestId": "r",
                                 "message": {"id": "m", "usage_v2": {"input_tokens": 5}}}) + "\n")
    p = run("", env, args=["--check-budget", str(drift)])
    assert p.returncode == 1 and "FAIL" in p.stdout
    p = run("", env, args=["--check-budget"], extra={"CLAUDE_CONFIG_DIR": str(tmp_path / "none")})
    assert p.returncode == 0 and "skipped" in p.stdout
    # a long transcript without a single assistant line: the message type was renamed, and the
    # budgets would count nothing (never "ok (0 API calls)")
    renamed = tmp_path / "renamed.jsonl"
    renamed.write_text("".join(
        json.dumps({"type": "user" if i % 2 else "model_turn", "requestId": "r%d" % i,
                    "message": {"id": "m%d" % i, "usage": {"input_tokens": 5}}}) + "\n"
        for i in range(60)))
    p = run("", env, args=["--check-budget", str(renamed)])
    assert p.returncode == 1 and "FAIL" in p.stdout and "no assistant lines" in p.stdout
    assert "ok (0 API calls" not in p.stdout
    # a session that has only just started: too early to tell, never "ok (0 API calls)"
    young = tmp_path / "young.jsonl"
    young.write_text(json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
    p = run("", env, args=["--check-budget", str(young)])
    assert p.returncode == 0 and "skipped" in p.stdout and "ok (0 API calls" not in p.stdout


def test_budget_log_keeps_no_tool_input(env, sess):
    """STACK_GUARD_LOG=1 in `budget` mode (every tool call) logs the tool name and ids only: a
    Bash command, a Write body or a pasted secret never lands in guard.log."""
    s, main, subs = sess
    ev = tool_ev(s, main, "Bash", command="curl -H 'Authorization: Bearer SECRET-123' x")
    assert decision(budget_run(ev, env, extra={"STACK_GUARD_LOG": "1"})) == "allow"
    ev2 = tool_ev(s, main, "Write", file_path="/tmp/x", content="SECRET-456")
    assert decision(budget_run(ev2, env, extra={"STACK_GUARD_LOG": "1"})) == "allow"
    text = (state(env, s) / "guard.log").read_text()
    assert "SECRET" not in text and "curl" not in text and "tool_input" not in text
    lines = [json.loads(x) for x in text.splitlines()]
    assert [x["tool_name"] for x in lines] == ["Bash", "Write"]
    assert lines[0]["tool_use_id"] == ev["tool_use_id"] and lines[0]["agent_id"] == "A1"


def test_budget_task_notification_turn_keeps_the_prompt_window(env, sess):
    """Task notifications carry prompt ids of their own and fire no UserPromptSubmit: once a human
    prompt is on record, BlackCat's call in a notification's turn stays in that prompt's budget."""
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    append(subs / "agent-a1.jsonl", call_line("m1", 1200))
    p = budget_run(tool_ev(s, main, "Read", agent_id=None, prompt="notif-1", file_path="x"), env)
    assert decision(p) == "deny" and "Prompt token budget" in reason(p)
    # a notification delivered as a prompt event does not start a budget either
    notif = dict(prompt_ev(s, main, "notif-2"), prompt="<task-notification>\n<task-id>x</task-id>")
    run(notif, env, extra=BUDGET)
    assert decision(budget_run(tool_ev(s, main, "Read", prompt="notif-2", file_path="x"), env)) \
        == "deny"
    run(prompt_ev(s, main, "p2"), env, extra=BUDGET)                  # the user's next prompt
    assert decision(budget_run(tool_ev(s, main, "Read", prompt="p2", file_path="x"), env)) \
        == "allow"



def test_budget_prompt_left_pending_starts_on_the_main_thread(env, sess):
    """UserPromptSubmit cannot take the budget lock (here held by the test): it leaves the prompt
    pending, and BlackCat's first call under that prompt_id starts the window; a notification's
    prompt_id (never pending) does not."""
    import fcntl
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    append(subs / "agent-a1.jsonl", call_line("m1", 1200))
    st_dir = state(env, s)
    fd = os.open(str(st_dir / "budget.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        run(prompt_ev(s, main, "p2"), env, extra=BUDGET)          # times out after 5 s
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    assert json.loads((st_dir / "prompt-pending.json").read_text())["prompt_id"] == "p2"
    p = budget_run(tool_ev(s, main, "Read", agent_id=None, prompt="notif-1", file_path="x"), env)
    assert decision(p) == "deny"                                   # still p1's window: 1,200
    assert decision(budget_run(tool_ev(s, main, "Read", agent_id=None, prompt="p2",
                                       file_path="x"), env)) == "allow"
    st = json.loads((st_dir / "budget.json").read_text())
    assert st["prompt_id"] == "p2" and st["prompt_base"] == 1200
    assert not (st_dir / "prompt-pending.json").exists()
    # a recorded prompt clears its own marker
    run(prompt_ev(s, main, "p3"), env, extra=BUDGET)
    assert not (st_dir / "prompt-pending.json").exists()


# ---------------------------------------------------------------- soft token limits
SHIPPED = {"STACK_PROMPT_CTX_BUDGET": "300000000", "STACK_SESSION_CTX_BUDGET": "1920000000"}


def soft_out(p):
    """(permissionDecision, additionalContext) of a hook run; ("allow", None) for no output."""
    assert p.returncode == 0, p.stderr
    if not p.stdout.strip():
        return "allow", None
    h = json.loads(p.stdout)["hookSpecificOutput"]
    return h.get("permissionDecision", "allow"), h.get("additionalContext")


def subagent_ev(s, main, aid, atype, tool="Read", **ti):
    return dict(tool_ev(s, main, tool, agent_id=aid, **(ti or {"file_path": "x"})),
                agent_type=atype)


def test_soft_agent_limit_warns_once_per_segment(env, sess):
    """scout's soft limit (390,000 context tokens) at STACK_SOFT_LIMIT_SCALE=0.001: 390. A warning
    rides on the first call past it, never a refusal; once per run; a resume starts over. With the
    hard budgets off the soft limits still count."""
    s, main, subs = sess
    extra = {"STACK_SOFT_LIMIT_SCALE": "0.001", "STACK_PROMPT_CTX_BUDGET": "0",
             "STACK_SESSION_CTX_BUDGET": "0"}
    run(prompt_ev(s, main, "p1"), env, extra=extra)
    run(lifecycle(s, "SubagentStart", "A1", "scout"), env)
    tf = subs / "agent-A1.jsonl"
    append(tf, call_line("m1", 300))
    ev = subagent_ev(s, main, "A1", "scout")
    assert soft_out(budget_run(ev, env, extra=extra)) == ("allow", None)        # 300: no hit
    append(tf, call_line("m2", 100))
    dec, ctx = soft_out(budget_run(ev, env, extra=extra))                        # 400: a hit
    assert dec == "allow" and ctx.startswith("Soft token limit reached for this run")
    assert "400 context tokens" in ctx and "soft limit for scout: 390" in ctx
    assert "STATUS: partial" in ctx and "ask your caller before continuing" in ctx
    append(tf, call_line("m3", 1000))
    assert soft_out(budget_run(ev, env, extra=extra)) == ("allow", None)        # warned once
    # another agent's tokens are not this one's
    run(lifecycle(s, "SubagentStart", "A2", "scout"), env)
    append(subs / "agent-A2.jsonl", call_line("m4", 100))
    assert soft_out(budget_run(subagent_ev(s, main, "A2", "scout"), env, extra=extra))[1] is None
    # a resume is a new segment: earlier calls (timestamped before it) do not count
    time.sleep(0.01)
    run(lifecycle(s, "SubagentStart", "A1", "scout"), env)
    assert soft_out(budget_run(ev, env, extra=extra))[1] is None
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.999Z", time.gmtime(time.time() + 2))
    line = json.loads(call_line("m5", 395))
    append(tf, json.dumps(dict(line, timestamp=stamp)) + "\n")
    assert "395 context tokens" in soft_out(budget_run(ev, env, extra=extra))[1]


def test_soft_agent_limit_scale_and_unlimited_types(env, sess):
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env)
    for aid, atype in (("S1", "scout"), ("S2", "scout"), ("O1", "orchestrator")):
        run(lifecycle(s, "SubagentStart", aid, atype), env)
        append(subs / ("agent-%s.jsonl" % aid), call_line("m-" + aid, 700000))
    # scale 1: 700,000 > 390,000 warns; scale 2 (780,000) does not; scale 0 turns them off
    assert soft_out(budget_run(subagent_ev(s, main, "S2", "scout"), env,
                               extra=dict(SHIPPED, STACK_SOFT_LIMIT_SCALE="2")))[1] is None
    assert soft_out(budget_run(subagent_ev(s, main, "S2", "scout"), env,
                               extra=dict(SHIPPED, STACK_SOFT_LIMIT_SCALE="0")))[1] is None
    assert "soft limit for scout: 390,000" in soft_out(
        budget_run(subagent_ev(s, main, "S1", "scout"), env, extra=SHIPPED))[1]
    # the orchestrator has no per-agent limit (the prompt limit, 80 at this scale, still applies)
    ctx = soft_out(budget_run(subagent_ev(s, main, "O1", "orchestrator"), env,
                              extra=dict(SHIPPED, STACK_SOFT_LIMIT_SCALE="0.000001")))[1]
    assert "for this prompt" in ctx and "for this run" not in ctx


def test_soft_prompt_limit_once_per_human_prompt(env, sess):
    """33,000,000 context tokens since the user's last prompt (here x 0.001 = 33,000): one warning
    per prompt, to whichever agent calls a tool next; task notifications do not reset it."""
    s, main, subs = sess
    extra = dict(SHIPPED, STACK_SOFT_LIMIT_SCALE="0.001")
    run(prompt_ev(s, main, "p1"), env, extra=extra)
    append(main, call_line("m1", 32999))
    main_ev = tool_ev(s, main, "Read", agent_id=None, file_path="x")
    assert soft_out(budget_run(main_ev, env, extra=extra)) == ("allow", None)
    append(main, call_line("m2", 1))
    dec, ctx = soft_out(budget_run(dict(main_ev, prompt_id="notif-1"), env, extra=extra))
    assert dec == "allow" and "Soft token limit reached for this prompt" in ctx
    assert "33,000 context tokens since the user's last prompt" in ctx and "ask them" in ctx
    assert soft_out(budget_run(main_ev, env, extra=extra))[1] is None              # once
    run(prompt_ev(s, main, "p2"), env, extra=extra)
    append(main, call_line("m3", 33000))
    dec, ctx = soft_out(budget_run(tool_ev(s, main, "Bash", prompt="p2", command="ls"), env,
                                   extra=extra))                  # a subagent (coder) this time
    assert dec == "allow" and "ask your caller" in ctx



def test_soft_prompt_limit_140m_while_an_orchestrator_runs(env, sess):
    """A running orchestrator raises the prompt limit from 33,000,000 to 140,000,000 (x 0.001:
    33,000 -> 140,000; 80,000,000 until 2026-10-08); once it stops, 33,000,000 applies again."""
    s, main, subs = sess
    extra = dict(SHIPPED, STACK_SOFT_LIMIT_SCALE="0.001")
    run(prompt_ev(s, main, "p1"), env, extra=extra)
    run(lifecycle(s, "SubagentStart", "O1", "orchestrator"), env)
    append(main, call_line("m1", 139999))
    main_ev = tool_ev(s, main, "Read", agent_id=None, file_path="x")
    assert soft_out(budget_run(main_ev, env, extra=extra)) == ("allow", None)
    append(main, call_line("m2", 1))
    ctx = soft_out(budget_run(main_ev, env, extra=extra))[1]
    assert "Soft token limit reached for this prompt" in ctx and "soft limit 140,000" in ctx
    run(prompt_ev(s, main, "p2"), env, extra=extra)
    run(lifecycle(s, "SubagentStop", "O1", "orchestrator"), env)
    append(main, call_line("m3", 33000))
    ctx = soft_out(budget_run(main_ev, env, extra=extra))[1]
    assert "Soft token limit reached for this prompt" in ctx and "soft limit 33,000" in ctx


def test_soft_limits_leave_the_hard_caps_alone(env, sess):
    """Hard budgets keep their values and wording; a hard refusal carries no soft note; another
    gate's output (the main hook's Agent label) carries a queued warning."""
    s, main, subs = sess
    run(prompt_ev(s, main, "p1"), env, extra=BUDGET)
    run(lifecycle(s, "SubagentStart", "A1", "scout"), env)
    append(subs / "agent-A1.jsonl", call_line("m1", 5000))
    p = budget_run(subagent_ev(s, main, "A1", "scout"), env,
                   extra={"STACK_SOFT_LIMIT_SCALE": "0.001"})
    assert decision(p) == "deny" and reason(p).startswith("Prompt token budget reached")
    assert "Soft token limit" not in p.stdout
    shipped = json.loads((ROOT / "dot-config" / "dot-claude" / "settings.json").read_text())["env"]
    # the hard budgets are learned limits (stack_limits.py seed: 300M / 1.92B), not shipped env knobs
    assert "STACK_PROMPT_CTX_BUDGET" not in shipped and "STACK_SESSION_CTX_BUDGET" not in shipped
    assert "STACK_SOFT_LIMIT_SCALE" not in shipped     # a process env value must reach the hooks
    # the main hook's own tools: the warning joins the handler's output
    s2 = sid()
    main2 = main.parent / (s2 + ".jsonl")
    main2.write_text("")
    (main.parent / s2 / "subagents").mkdir(parents=True)
    run(prompt_ev(s2, main2, "p1"), env)
    run(pre_agent(s2, "ninja-coder", parent="main-coder", agent_id="M1"), env)
    run(lifecycle(s2, "SubagentStart", "C1", "ninja-coder"), env)
    run(post_agent(s2, "ninja-coder", "C1", agent_id="M1", parent="main-coder"), env)
    append(main.parent / s2 / "subagents" / "agent-C1.jsonl", call_line("m1", 20000))
    ev = dict(pre_agent(s2, "explore", parent="ninja-coder", agent_id="C1"),
              transcript_path=str(main2), cwd=str(main.parent))
    dec, ctx = soft_out(run(ev, env, extra={"STACK_SOFT_LIMIT_SCALE": "0.001"}))
    assert dec == "allow" and "soft limit for ninja-coder: 19,000" in ctx


# ---------------------------------------------------------------- review 2026-09-28: resumes, leases
def finished_children(env, s, caller, ctype, child, ids):
    """`caller` spawns each of `ids` in the foreground; each runs, stops and reports back."""
    for x in ids:
        ev = pre_agent(s, child, parent=ctype, agent_id=caller)
        assert decision(run(ev, env)) == "allow", x
        run(lifecycle(s, "SubagentStart", x, child), env)
        run(lifecycle(s, "SubagentStop", x, child), env)
        run(post_agent(s, child, x, agent_id=caller, parent=ctype, status="completed",
                       tool_use_id=ev["tool_use_id"]), env)


def test_parallel_resumes_respect_the_fanout_cap(env):
    s = sid()
    kids = ["K%d" % i for i in range(6)]
    finished_children(env, s, "M1", "main-coder", "scout", kids)
    res = run_many([dict(send(s, k, agent_id="M1"), agent_type="main-coder") for k in kids], env)
    assert res.count("allow") == 3, res                           # STACK_MAX_FANOUT=3
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="M1"), env)
    assert decision(p) == "deny" and "Fan-out limit" in reason(p)
    # a resume that never starts stops counting after STACK_RESUME_TTL_S (120 s)
    age_leases(env, s, "M1", 121)
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="M1"), env)) == "allow"
    assert len(leases(env, s, "M1")) == 1


def test_two_messages_to_one_finished_agent_reserve_once(env):
    s = sid()
    env["STACK_MAX_FANOUT"] = "1"
    finished_children(env, s, "M1", "main-coder", "scout", ["K0"])
    res = run_many([dict(send(s, "K0", agent_id="M1"), agent_type="main-coder") for _ in range(2)],
                   env)
    assert res == ["allow", "allow"] and leases(env, s, "M1") == ["resume-K0"]


def test_a_starting_agent_voids_its_own_leases(env):
    s = sid()
    run(post_agent(s, "main-coder", "L1", status="async_launched"), env)
    run(lifecycle(s, "SubagentStart", "L1", "main-coder"), env)
    finished_children(env, s, "L1", "main-coder", "coder", ["W1"])
    # BlackCat resumes W1, L1's finished child: one of L1's 3 slots, reserved until W1 starts
    assert decision(run(dict(send(s, "W1"), agent_type="blackcat"), env)) == "allow"
    for _ in range(2):
        assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)) \
            == "allow"
    p = run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)
    assert decision(p) == "deny" and "Fan-out limit" in reason(p)
    # L1's two calls end without PostToolUse (a deny rule, another hook, a cancel) and L1 without
    # SubagentStop; later BlackCat resumes L1
    run(dict(send(s, "L1"), agent_type="blackcat"), env)
    run(lifecycle(s, "SubagentStart", "L1", "main-coder"), env)
    # a starting agent has no Agent call in flight: its leaked leases go, W1's reservation stays
    assert leases(env, s, "L1") == ["resume-W1"]
    for _ in range(2):
        assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)) \
            == "allow"
    assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)) == "deny"


def test_a_stopped_child_drops_the_lease_that_spawned_it(env, tmp_path):
    s = sid()
    env["STACK_MAX_FANOUT"] = "8"
    subs = tmp_path / "p" / s / "subagents"
    subs.mkdir(parents=True)
    main = tmp_path / "p" / (s + ".jsonl")
    main.write_text("")

    def spawn(cid, caller=None, meta=True):
        ev = (pre_agent(s, "coder", parent="main-coder", agent_id=caller) if caller else
              pre_agent(s, "coder", parent="blackcat"))
        assert decision(run(dict(ev, transcript_path=str(main)), env)) == "allow"
        if meta:     # Claude Code's own record of the spawn (subagents/agent-<id>.meta.json)
            m = {"agentType": "coder", "spawnDepth": 2 if caller else 1,
                 "toolUseId": ev["tool_use_id"], "requestShape": "foreground"}
            if caller:
                m["parentAgentId"] = caller
            (subs / ("agent-%s.meta.json" % cid)).write_text(json.dumps(m))
        run(dict(lifecycle(s, "SubagentStart", cid, "coder"), transcript_path=str(main)), env)
        return ev["tool_use_id"]

    for cid in ("K1", "K2", "K3"):
        spawn(cid, "SC")
    keep = spawn("K4", "SC", meta=False)
    b1 = spawn("B1")
    assert len(leases(env, s, "SC")) == 4 and leases(env, s, "main") == [b1]
    # the foreground calls never report back (cancelled); each child's own stop drops its lease
    run(dict(lifecycle(s, "SubagentStop", "K1", "coder"), transcript_path=str(main),
             agent_transcript_path=str(subs / "agent-K1.jsonl")), env)
    run(dict(lifecycle(s, "StopFailure", "K2", "coder", error="rate_limit"),
             transcript_path=str(main)), env)
    run({"session_id": s, "hook_event_name": "PostToolUse", "tool_name": "TaskStop",
         "agent_id": "SC", "agent_type": "main-coder", "transcript_path": str(main),
         "tool_input": {"task_id": "K3"}, "tool_response": {"task_id": "K3"}}, env)
    run(dict(lifecycle(s, "SubagentStop", "K4", "coder"), transcript_path=str(main),
             agent_transcript_path=str(subs / "agent-K4.jsonl")), env)
    run(dict(lifecycle(s, "SubagentStop", "B1", "coder"), transcript_path=str(main),
             agent_transcript_path=str(subs / "agent-B1.jsonl")), env)
    assert leases(env, s, "SC") == [keep]                 # no meta.json: nothing is guessed
    assert leases(env, s, "main") == []


def test_agent_done_drops_the_lease_even_when_the_lock_times_out(env):
    import fcntl
    s = sid()
    ev = pre_agent(s, "coder", parent="main-coder", agent_id="SC")
    assert decision(run(ev, env)) == "allow"
    assert leases(env, s, "SC") == [ev["tool_use_id"]]
    fd = os.open(str(state(env, s) / "fanout.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)              # someone holds the fan-out lock for > 5 s
        p = run(post_agent(s, "coder", "K1", agent_id="SC", parent="main-coder",
                           status="completed", tool_use_id=ev["tool_use_id"]), env)
        assert p.returncode == 0 and p.stdout == "" and "timed out" in p.stderr
    finally:
        os.close(fd)
    assert leases(env, s, "SC") == []


# ---------------------------------------------------------------- review 2026-09-28, round 2
def test_blackcat_step_limit_refuses_a_resume_and_holds_no_slot(env):
    """At BLACKCAT_MAX_STEPS a BlackCat SendMessage that would resume a finished agent is refused
    and reserves nothing: blackcat-guard and the main hook run in parallel for the same call, so
    the step and the resume reservation are one decision in the main hook (as for Agent)."""
    s = sid()
    run(post_agent(s, "main-coder", "L1", status="async_launched"), env)
    run(lifecycle(s, "SubagentStart", "L1", "main-coder"), env)
    finished_children(env, s, "L1", "main-coder", "coder", ["W1"])
    for _ in range(8):
        assert decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) == "allow"
    ev = dict(send(s, "W1"), agent_type="blackcat", prompt_id="q1")
    res = [decision(run(ev, env, args=a)) for a in (["blackcat-guard"], [])]
    assert "deny" in res, res
    assert leases(env, s, "L1") == []                 # L1 keeps all 3 of its slots
    for _ in range(3):
        assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)) \
            == "allow"


def test_blackcat_resume_is_one_step(env):
    s = sid()
    run(post_agent(s, "main-coder", "L1", status="async_launched"), env)
    run(lifecycle(s, "SubagentStart", "L1", "main-coder"), env)
    finished_children(env, s, "L1", "main-coder", "coder", ["W1"])
    folder = state(env, s) / "blackcat"
    steps = lambda: len([p for p in folder.iterdir() if p.name.startswith("step.")]) \
        if folder.exists() else 0
    for _ in range(7):
        assert decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) == "allow"
    assert steps() == 7 and leases(env, s, "L1") == []
    # the 8th step: both hooks run for the one call, one step is claimed, the resume reserved
    ev = dict(send(s, "W1"), agent_type="blackcat", prompt_id="q1")
    assert [decision(run(ev, env, args=a)) for a in (["blackcat-guard"], [])] == ["allow", "allow"]
    assert steps() == 8 and leases(env, s, "L1") == ["resume-W1"]
    p = run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])
    assert decision(p) == "deny" and "step limit" in reason(p)


def test_a_refused_blackcat_resume_spends_no_step(env):
    """A BlackCat resume refused at the fan-out limit claims no step and reserves nothing: the
    step is claimed only after resume_reserve succeeds (on_send)."""
    s = sid()
    run(post_agent(s, "main-coder", "L1", status="async_launched"), env)
    run(lifecycle(s, "SubagentStart", "L1", "main-coder"), env)
    finished_children(env, s, "L1", "main-coder", "coder", ["W1"])
    for _ in range(3):                                   # L1 fills STACK_MAX_FANOUT=3
        assert decision(run(pre_agent(s, "coder", parent="main-coder", agent_id="L1"), env)) \
            == "allow"
    folder = state(env, s) / "blackcat"
    steps = lambda: len([p for p in folder.iterdir() if p.name.startswith("step.")]) \
        if folder.exists() else 0
    for _ in range(7):
        assert decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) == "allow"
    before = leases(env, s, "L1")
    p = run(dict(send(s, "W1"), agent_type="blackcat", prompt_id="q1"), env)
    assert decision(p) == "deny" and "Fan-out limit" in reason(p)
    assert steps() == 7 and "resume-W1" not in leases(env, s, "L1")
    assert leases(env, s, "L1") == before
    # the step it did not spend is still there: the 8th call passes
    assert decision(run(rg(s, "ToolSearch", prompt="q1"), env, args=["blackcat-guard"])) == "allow"

def test_a_resume_starts_even_when_the_fanout_lock_times_out(env):
    """SubagentStart of a resumed agent while the fan-out lock is stuck (> 5 s): the start is
    still recorded (a live background child again) and its reservation dropped, outside the
    lock."""
    import fcntl
    s = sid()
    finished_children(env, s, "M1", "main-coder", "ninja-coder", ["G1"])
    assert decision(run(dict(send(s, "G1", agent_id="M1"), agent_type="main-coder"), env)) \
        == "allow"
    assert leases(env, s, "M1") == ["resume-G1"]
    fd = os.open(str(state(env, s) / "fanout.mutex"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)              # someone holds the fan-out lock for > 5 s
        p = run(lifecycle(s, "SubagentStart", "G1", "ninja-coder"), env)
        assert p.returncode == 0 and "Decision" not in p.stdout
    finally:
        os.close(fd)
    rec = reg_of(env, s, "G1")
    assert not rec.get("stopped") and rec.get("bg") is True and rec.get("resumed")
    assert leases(env, s, "M1") == []


# ---------------------------------------------------------------- MCP call cap
def mcp_ev(s, main, tool="mcp__exa__web_search_exa", agent_id="A1", agent_type="coder", **ti):
    ev = tool_ev(s, main, tool, agent_id=agent_id, **ti)
    if agent_id:
        ev["agent_type"] = agent_type
    return ev


def mcp_count(env, s, aid):
    f = state(env, s) / "mcp-calls" / (aid + ".json")
    return json.loads(f.read_text())["calls"] if f.exists() else 0


def seed_mcp(env, s, aid, n):
    folder = state(env, s) / "mcp-calls"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / (aid + ".json")).write_text(json.dumps({"calls": n}))


def test_mcp_cap_counts_per_agent_and_denies_only_mcp(env, sess):
    s, main, _ = sess
    cap = {"STACK_MAX_MCP_CALLS": "3"}
    for _ in range(3):
        assert decision(budget_run(mcp_ev(s, main), env, extra=cap)) == "allow"
    assert mcp_count(env, s, "A1") == 3
    p = budget_run(mcp_ev(s, main), env, extra=cap)
    assert decision(p) == "deny" and reason(p).startswith("MCP call limit reached")
    assert "STACK_MAX_MCP_CALLS=3" in reason(p) and "STATUS: partial" in reason(p)
    msg = json.loads(p.stdout)["systemMessage"]
    assert "STACK_MAX_MCP_CALLS" in msg and "until the next install.sh run" in msg
    assert mcp_count(env, s, "A1") == 3                     # a refused call is not counted
    # other tools, and reporting, still work
    assert decision(budget_run(tool_ev(s, main, "Read", file_path="x"), env, extra=cap)) == "allow"
    assert decision(budget_run(tool_ev(s, main, "SubagentHandback", message="x"), env,
                               extra=cap)) == "allow"
    # another agent of the same type has its own count; the main thread is never counted
    assert decision(budget_run(mcp_ev(s, main, agent_id="A2"), env, extra=cap)) == "allow"
    for _ in range(5):
        assert decision(budget_run(mcp_ev(s, main, agent_id=None), env, extra=cap)) == "allow"
    assert not (state(env, s) / "mcp-calls" / "none.json").exists()
    # 0 = off; STACK_POLICY=off too
    assert decision(budget_run(mcp_ev(s, main), env,
                               extra={"STACK_MAX_MCP_CALLS": "0"})) == "allow"
    assert decision(budget_run(mcp_ev(s, main), env,
                               extra=dict(cap, STACK_POLICY="off"))) == "allow"


def agent_turns(atype):
    """maxTurns in the repo's agents/<type>.md."""
    text = (ROOT / "dot-config" / "dot-claude" / "agents" / (atype + ".md")).read_text()
    return int(re.search(r"^maxTurns:\s*(\d+)\s*$", text, re.M).group(1))


def test_mcp_cap_is_min_of_knob_and_max_turns(env, sess):
    """Default 64, lowered by a smaller frontmatter maxTurns (scout, oracle, explore); a larger one
    (orchestrator, mcp-broker, coder) gets 64. The caps follow the agent files."""
    s, main, _ = sess
    for aid, atype in (("S1", "scout"), ("R1", "oracle"), ("B1", "mcp-broker"),
                       ("O1", "orchestrator"), ("C1", "coder"), ("E1", "explore")):
        cap = min(64, agent_turns(atype))
        seed_mcp(env, s, aid, cap - 1)
        assert decision(budget_run(mcp_ev(s, main, agent_id=aid, agent_type=atype), env)) == "allow"
        p = budget_run(mcp_ev(s, main, agent_id=aid, agent_type=atype), env)
        assert decision(p) == "deny", atype
        assert ("%d MCP tool calls" % cap) in reason(p), reason(p)
        assert (("its turn budget turns.%s=%d" % (atype, cap)) in reason(p)) \
            == (cap < 64), reason(p)


def test_mcp_cap_on_the_main_hooks_mcp_tools(env, sess):
    """computer-use and local-file MCP tools go through the main hook, which checks the cap
    before taking the screen lock."""
    s, main, _ = sess
    seed_mcp(env, s, "D1", 100)                              # designer: maxTurns 100 -> cap 64
    p = run(mcp_ev(s, main, "mcp__computer-use__screenshot", agent_id="D1", agent_type="designer"),
            env)
    assert decision(p) == "deny" and "MCP call limit" in reason(p)
    assert not (state(env, s) / "screen.lock").exists()
    assert decision(run(mcp_ev(s, main, "mcp__computer-use__screenshot", agent_id="D2",
                               agent_type="designer"), env)) == "allow"
    assert mcp_count(env, s, "D2") == 1


def test_mcp_cap_parallel_calls_count_exactly(env, sess):
    s, main, _ = sess
    res = run_many([mcp_ev(s, main) for _ in range(FANOUT)], env, args=["budget"],
                   extra={"STACK_MAX_MCP_CALLS": "5"})
    assert res.count("allow") == 5, res
    assert mcp_count(env, s, "A1") == 5


def test_mcp_cap_is_per_prompt_a_resume_starts_a_new_count(env, sess):
    """A subagent's prompt is one run: SubagentStart (spawn or resume) starts a new count. A
    message to the agent while it still runs is part of the same run."""
    s, main, _ = sess
    cap = {"STACK_MAX_MCP_CALLS": "3"}
    run(lifecycle(s, "SubagentStart", "A1", "coder"), env, extra=cap)          # first prompt
    for _ in range(3):
        assert decision(budget_run(mcp_ev(s, main), env, extra=cap)) == "allow"
    assert decision(budget_run(mcp_ev(s, main), env, extra=cap)) == "deny"
    # the parent messages it while it runs: no SubagentStart, no new allowance
    run(dict(send(s, "A1", agent_id="P1"), agent_type="main-coder"), env, extra=cap)
    assert decision(budget_run(mcp_ev(s, main), env, extra=cap)) == "deny"
    # it finishes and is resumed with a new prompt: a fresh count of 3
    run(lifecycle(s, "SubagentStop", "A1", "coder"), env, extra=cap)
    run(lifecycle(s, "SubagentStart", "A1", "coder"), env, extra=cap)
    for _ in range(3):
        assert decision(budget_run(mcp_ev(s, main), env, extra=cap)) == "allow"
    assert mcp_count(env, s, "A1") == 3
    p = budget_run(mcp_ev(s, main), env, extra=cap)
    assert decision(p) == "deny" and "for its current prompt" in reason(p)
    assert "per agent per prompt" in json.loads(p.stdout)["systemMessage"]


# ---------------------------------------------------------------- read-only: lake env
@pytest.mark.parametrize("command,ok", [
    ("lake env lean .claude-work/j/x.lean", True),
    ("cd /tmp && lake env lean .claude-work/j/x.lean", True),
    ("lake env", True),
    ("lake build", True),
    ("lake env rm -rf src", False),
    ("lake env sh -c 'echo x > src/a'", False),
    ("lake env python3 -c 'import os; os.remove(\"a\")'", False),
    ("lake env lean src/x.lean > src/out.txt", False),
])
def test_readonly_lake_env_checks_the_wrapped_command(command, ok):
    """`lake env <cmd>` runs <cmd>: a read-only agent's <cmd> is held to the same allowlist."""
    g = _guard_types()
    bad = g.readonly_violation(command, {"cwd": str(ROOT)})
    assert (bad is None) == ok, bad


def test_blackcat_reads_never_eat_the_dispatch_burst(env):
    """Shipped caps (24 steps, 3 reads, 0 own calls): reads first, against the rules, still leave
    room for a burst of 8 dispatches; the 4th read and every Bash/Write/Edit are refused (and spend
    no step), then 13 more calls fit and the 25th is refused."""
    s = sid()
    shipped = {"BLACKCAT_MAX_STEPS": "24"}
    for _ in range(3):
        assert decision(run(rg(s, "Read", prompt="w1"), env, args=["blackcat-guard"],
                            extra=shipped)) == "allow"
    p = run(rg(s, "Read", prompt="w1"), env, args=["blackcat-guard"], extra=shipped)
    assert decision(p) == "deny" and "read limit (3" in reason(p)
    for tool in ("Bash", "Edit", "Write"):
        p = run(rg(s, tool, prompt="w1"), env, args=["blackcat-guard"], extra=shipped)
        assert decision(p) == "deny" and "only delegates" in reason(p), tool
    for i in range(8):
        p = run(pre_agent(s, "scout", parent="blackcat", prompt="w1"), env, extra=shipped)
        assert decision(p) == "allow", i
    for i in range(13):
        p = run(rg(s, "ToolSearch", prompt="w1"), env, args=["blackcat-guard"], extra=shipped)
        assert decision(p) == "allow", i
    p = run(rg(s, "ToolSearch", prompt="w1"), env, args=["blackcat-guard"], extra=shipped)
    assert decision(p) == "deny" and "step limit (24" in reason(p)


OWN_ON = {"BLACKCAT_MAX_OWN_STEPS": "4", "STACK_BLACKCAT_DELEGATE_ONLY": "0"}


@pytest.mark.parametrize("ti,ok", [
    ({"command": "make test"}, True),                                     # harness default 120 s
    ({"command": "make test", "timeout": 120000}, True),
    ({"command": "make test", "timeout": 120001}, False),
    ({"command": "make test", "timeout": 600000}, False),
    ({"command": "make test", "timeout": 600000, "run_in_background": True}, True),
    ({"command": "make test", "run_in_background": "yes", "timeout": 600000}, False),
])
def test_blackcat_foreground_bash_is_bounded(env, ti, ok):
    """Only reachable with STACK_BLACKCAT_DELEGATE_ONLY=0 and an explicit BLACKCAT_MAX_OWN_STEPS
    override (the defaults refuse Bash)."""
    p = run(rg(sid(), "Bash", tool_input=ti), env, args=["blackcat-guard"], extra=OWN_ON)
    assert (decision(p) == "allow") == ok, ti
    if not ok:
        assert "foreground Bash is capped at 120 s" in reason(p)


def test_blackcat_foreground_cap_follows_a_raised_default(env):
    """BASH_DEFAULT_TIMEOUT_MS raised in settings env: a Bash call without a timeout would wait
    that long, so it must pass an explicit timeout within the cap."""
    s = sid()
    raised = dict(OWN_ON, BASH_DEFAULT_TIMEOUT_MS="300000")
    p = run(rg(s, "Bash", tool_input={"command": "ls"}), env, args=["blackcat-guard"], extra=raised)
    assert decision(p) == "deny" and "asks for 300 s" in reason(p)
    p = run(rg(s, "Bash", prompt="p2", tool_input={"command": "ls", "timeout": 60000}), env,
            args=["blackcat-guard"], extra=raised)
    assert decision(p) == "allow"
