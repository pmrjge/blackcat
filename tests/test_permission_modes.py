"""Permission modes: sessions start in Plan (settings.json permissions.defaultMode), builders carry
`permissionMode: acceptEdits` for their subagent runs, read-only agents never do, and no agent
file declares any other mode (tests/lint_agents.py permission_mode_problem), and the MCP servers
allowed without a prompt are exactly the decided set.

Run: uv run --with pytest pytest -q tests/test_permission_modes.py
"""
import json
import os
import stat
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
import lint_agents  # noqa: E402

AGENTS = ROOT / "dot-claude" / "agents"
SETTINGS = ROOT / "dot-claude" / "settings.json"
BUILDER_TOOLS = "Read, Write, Edit, Bash, ToolSearch, Skill"
READONLY_TOOLS = "Read, Bash, WebFetch, ToolSearch, Skill"


def fixture(tmp_path, tools, mode=None, name="fixture-agent"):
    lines = ["---", f"name: {name}", 'description: "A fixture agent for the permissionMode rule."',
             "model: sonnet", "maxTurns: 10", f"tools: {tools}", "color: red"]
    if mode is not None:
        lines.append(f"permissionMode: {mode}")
    p = tmp_path / f"{name}.md"
    p.write_text("\n".join(lines + ["---", "You are a fixture. May spawn: nothing.", ""]))
    return p


def mode_errors(path, monkeypatch):
    monkeypatch.setattr(lint_agents, "errors", [])
    lint_agents.check_agent_file(path, {}, set(), set())
    return [e for e in lint_agents.errors if "permissionMode" in e]


def test_settings_start_every_session_in_plan():
    assert json.loads(SETTINGS.read_text())["permissions"]["defaultMode"] == "plan"


@pytest.mark.parametrize("tools,mode", [
    (BUILDER_TOOLS, "acceptEdits"),
    (BUILDER_TOOLS, None),
    (READONLY_TOOLS, "plan"),
    (READONLY_TOOLS, '"plan"'),
    (READONLY_TOOLS, None),
])
def test_allowed_modes_pass(tmp_path, monkeypatch, tools, mode):
    assert mode_errors(fixture(tmp_path, tools, mode), monkeypatch) == []


@pytest.mark.parametrize("mode", ["default", "auto", "dontAsk", "bypassPermissions", "Plan", ""])
def test_other_modes_fail_with_the_docs_rule(tmp_path, monkeypatch, mode):
    errs = mode_errors(fixture(tmp_path, BUILDER_TOOLS, mode), monkeypatch)
    assert len(errs) == 1, errs
    assert "only acceptEdits" in errs[0] and "plan, default or dontAsk" in errs[0], errs


def test_read_only_agent_with_accept_edits_fails(tmp_path, monkeypatch):
    errs = mode_errors(fixture(tmp_path, READONLY_TOOLS, "acceptEdits"), monkeypatch)
    assert len(errs) == 1 and "read-only agent declares no acceptEdits" in errs[0], errs


def test_builder_with_plan_fails(tmp_path, monkeypatch):
    errs = mode_errors(fixture(tmp_path, BUILDER_TOOLS, "plan"), monkeypatch)
    assert len(errs) == 1 and "could never edit" in errs[0], errs


def test_notebook_edit_counts_as_editing(tmp_path, monkeypatch):
    assert mode_errors(fixture(tmp_path, "Read, NotebookEdit, Skill", "acceptEdits"), monkeypatch) == []


def test_installer_type_carries_accept_edits_without_edit_tools(tmp_path, monkeypatch):
    """toolsmith installs through Bash alone (bin/stack-install): acceptEdits keeps it working under a
    Plan parent; plan would make it read-only; another Bash-only agent still may not carry it."""
    ok = fixture(tmp_path, "Read, Bash, Skill", "acceptEdits", name="toolsmith")
    assert mode_errors(ok, monkeypatch) == []
    assert mode_errors(fixture(tmp_path, "Read, Bash, Skill", "plan", name="toolsmith"), monkeypatch)
    assert mode_errors(fixture(tmp_path, "Read, Skill", "acceptEdits", name="toolsmith"), monkeypatch)
    assert mode_errors(fixture(tmp_path, "Read, Bash, Skill", "acceptEdits", name="bash-only"), monkeypatch)


def test_shipped_agents_follow_the_rule():
    """Every agent that can write files carries acceptEdits for its subagent runs (45, plus toolsmith and
    equilibrium, which run their executors through Bash: 47); BlackCat, the main thread, follows the session's mode
    (Plan) and the read-only agents carry none."""
    modes, writers = {}, set()
    for f in sorted(AGENTS.glob("*.md")):
        data, _ = lint_agents.parse_frontmatter(f.read_text())
        assert lint_agents.permission_mode_problem(data) is None, f.name
        if lint_agents.EDIT_TOOLS & set(lint_agents.get_tools(data)[0]) or f.stem in lint_agents.INSTALLER_TYPES | lint_agents.EQ_TYPES:
            writers.add(f.stem)
        if "permissionMode" in data:
            modes[f.stem] = lint_agents.get_inline(data, "permissionMode")
    assert set(modes.values()) == {"acceptEdits"}
    assert set(modes) == writers - {"blackcat"} and len(modes) == 47
    assert {f.stem for f in AGENTS.glob("*.md")} - set(modes) == {
        "blackcat", "claude-code-guide", "code-reviewer", "explore", "oracle", "plan-reviewer", "planner",
        "proof-checker", "scout", "security-auditor", "verifier"}


# ---------------------------------------------------------------- MCP allow rules
# Under Plan and acceptEdits an MCP tool without an allow rule prompts (bypassPermissions ran it
# silently). The user's decision, "All except DB and Chrome": every MCP server an agent names is
# allowed whole, except mongodb and postgres (database writes) and claude-in-chrome (the user's
# logged-in browser), which keep prompting and are denied in headless runs. magg and context-mode
# are allowed or asked tool by tool (test_no_duplicates). No agent names conductor since BlackCat
# dropped Conductor's AskUserQuestion (2026-10-04).
ALLOWED_MCP_SERVERS = {
    "exa", "jina", "libdocs", "wolfram", "huggingface", "wandb", "spider", "image-studio", "huetension",
    "markitdown", "illustrator", "after-effects", "premiere", "blender", "playwright", "neural-memory",
    "computer-use", "lean", "mobilebuild"}
PROMPTING_MCP_SERVERS = {"mongodb", "postgres", "claude-in-chrome"}
PER_TOOL_MCP_SERVERS = {"magg", "context-mode"}


def mcp_rules(kind):
    """(server, tool or None) for each mcp__ rule of permissions.<kind>; `mcp__s` and `mcp__s__*`
    both name the whole server (docs: permissions, "MCP")."""
    out = []
    for rule in json.loads(SETTINGS.read_text())["permissions"].get(kind, []):
        parts = rule.split("__", 2)
        if parts[0] == "mcp" and len(parts) > 1:
            tool = parts[2] if len(parts) == 3 else None
            out.append((parts[1], None if tool == "*" else tool))
    return out


def test_whole_server_mcp_allow_rules_are_exactly_the_decided_set():
    whole = [s for s, tool in mcp_rules("allow") if tool is None]
    assert len(whole) == len(set(whole)), whole
    assert set(whole) == ALLOWED_MCP_SERVERS


def test_database_and_chrome_servers_keep_prompting():
    """No allow rule (it would run them unprompted) and no deny rule (data-engineer and
    browser-operator need them) names mongodb, postgres or claude-in-chrome, in any form."""
    named = {s for kind in ("allow", "deny") for s, _ in mcp_rules(kind)}
    assert not named & PROMPTING_MCP_SERVERS, named & PROMPTING_MCP_SERVERS
    assert not {"mcp__mongodb", "mcp__postgres", "mcp__claude-in-chrome"} & set(
        json.loads(SETTINGS.read_text())["permissions"]["allow"])


def test_allowed_mcp_servers_meet_no_ask_or_deny_rule():
    """Deny, then ask, then allow: the first match wins, so a shipped ask or deny rule on an
    allowed server would silently cancel its allow rule."""
    hit = {s for kind in ("ask", "deny") for s, _ in mcp_rules(kind)} & ALLOWED_MCP_SERVERS
    assert not hit, hit


def test_every_mcp_server_an_agent_names_has_a_decision():
    """A new MCP server in an agent's tools line fails here until someone allows it or lists it as
    prompting; a server no agent names any more fails until it leaves the lists."""
    named = set()
    for f in sorted(AGENTS.glob("*.md")):
        data, _ = lint_agents.parse_frontmatter(f.read_text())
        for t in lint_agents.get_tools(data)[0]:
            if t.startswith("mcp__"):
                named.add(t.split("__")[1])
    assert named == ALLOWED_MCP_SERVERS | PROMPTING_MCP_SERVERS | PER_TOOL_MCP_SERVERS, (
        sorted(named ^ (ALLOWED_MCP_SERVERS | PROMPTING_MCP_SERVERS | PER_TOOL_MCP_SERVERS)))


# ---------------------------------------------------------------- STACK_MODE_PROBE (diagnostic)
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"


def guard(ev, tmp_path, args=(), probe="1", **extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("STACK_MODE_PROBE", "STACK_POLICY", "STACK_GUARD_LOG", "XDG_STATE_HOME")}
    env.update(XDG_STATE_HOME=str(tmp_path / "state"), STACK_USAGE_COLLECT="0", STACK_MODE_PROBE=probe, **extra)
    return subprocess.run([sys.executable, str(GUARD), *args], input=json.dumps(ev), capture_output=True,
                          text=True, env=env, timeout=60)


def probe_lines(tmp_path):
    p = tmp_path / "state" / "claude-agent-stack" / "mode-probe.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def pre(session, tool, agent=None, mode="plan", **ti):
    ev = {"hook_event_name": "PreToolUse", "session_id": session, "tool_name": tool,
          "tool_use_id": "toolu_" + uuid.uuid4().hex[:8], "tool_input": ti, "permission_mode": mode,
          "transcript_path": "/nonexistent.jsonl"}
    if agent:
        ev.update(agent_id=agent[1], agent_type=agent[0])
    return ev


def test_probe_logs_pre_tool_use_without_the_input(tmp_path):
    p = guard(pre("s1", "Bash", command="curl -H 'Authorization: Bearer SECRET-1' x"), tmp_path, ["budget"])
    assert p.returncode == 0 and p.stdout == "", p.stderr
    p = guard(pre("s1", "Write", agent=("coder", "agent-c1"), mode="acceptEdits", file_path="/x",
                  content="SECRET-2"), tmp_path, ["budget"])
    assert p.returncode == 0, p.stderr
    rows = probe_lines(tmp_path)
    assert [(r["event"], r["tool"], r["agent_type"], r["agent_id"], r["depth"], r["permission_mode"])
            for r in rows] == [("PreToolUse", "Bash", None, None, 0, "plan"),
                               ("PreToolUse", "Write", "coder", "c1", None, "acceptEdits")]
    text = (tmp_path / "state" / "claude-agent-stack" / "mode-probe.jsonl").read_text()
    assert "SECRET" not in text and "curl" not in text and "tool_input" not in text and "/x" not in text
    assert stat.S_IMODE((tmp_path / "state" / "claude-agent-stack" / "mode-probe.jsonl").stat().st_mode) == 0o600


def test_probe_logs_subagent_start_and_permission_request_and_decides_nothing(tmp_path):
    p = guard({"hook_event_name": "SubagentStart", "session_id": "s2", "agent_id": "agent-a7",
               "agent_type": "planner"}, tmp_path)
    assert p.returncode == 0, p.stderr
    p = guard({"hook_event_name": "PermissionRequest", "session_id": "s2", "tool_name": "Edit",
               "tool_input": {"file_path": "/y", "old_string": "a", "new_string": "SECRET-3"},
               "permission_mode": "default"}, tmp_path)
    assert p.returncode == 0 and p.stdout == "", (p.stdout, p.stderr)     # no decision: the dialog proceeds
    rows = probe_lines(tmp_path)
    assert [(r["event"], r["agent_type"], r.get("permission_mode", "absent")) for r in rows] == [
        ("SubagentStart", "planner", "absent"), ("PermissionRequest", None, "default")]
    assert "SECRET" not in json.dumps(rows)


def test_probe_off_by_default_and_with_zero(tmp_path):
    guard(pre("s3", "Read", file_path="/z"), tmp_path, ["budget"], probe="0")
    guard({"hook_event_name": "PermissionRequest", "session_id": "s3", "tool_name": "Edit"}, tmp_path, probe="0")
    assert probe_lines(tmp_path) == []


def test_probe_runs_with_policy_off_and_stops_at_one_megabyte(tmp_path):
    log = tmp_path / "state" / "claude-agent-stack" / "mode-probe.jsonl"
    guard(pre("s4", "Read", file_path="/z"), tmp_path, ["budget"], STACK_POLICY="off")
    assert len(probe_lines(tmp_path)) == 1
    with open(log, "a") as f:
        f.write("x" * ((1 << 20) - log.stat().st_size - 10) + "\n")
    size = log.stat().st_size
    assert guard(pre("s4", "Read", file_path="/z"), tmp_path, ["budget"]).returncode == 0
    assert log.stat().st_size == size                   # capped: no line past 1 MB


def test_probe_never_follows_a_symlink(tmp_path):
    root = tmp_path / "state" / "claude-agent-stack"
    root.mkdir(parents=True)
    target = tmp_path / "elsewhere.txt"
    target.write_text("")
    (root / "mode-probe.jsonl").symlink_to(target)
    p = guard(pre("s5", "Read", file_path="/z"), tmp_path, ["budget"])
    assert p.returncode == 0 and target.read_text() == ""
    assert "mode probe" in p.stderr                     # warned, the call itself allowed


def test_probe_never_hangs_on_a_fifo(tmp_path):
    root = tmp_path / "state" / "claude-agent-stack"
    root.mkdir(parents=True)
    os.mkfifo(root / "mode-probe.jsonl")
    p = guard(pre("s6", "Read", file_path="/z"), tmp_path, ["budget"])      # timeout=60 would raise
    assert p.returncode == 0 and "mode probe" in p.stderr
