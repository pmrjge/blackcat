"""Permission modes: sessions start in Plan (settings.json permissions.defaultMode), builders carry
`permissionMode: acceptEdits` for their subagent runs, read-only agents never do, and no agent
file declares any other mode (tests/lint_agents.py permission_mode_problem).

Run: uv run --with pytest pytest -q tests/test_permission_modes.py
"""
import json
import sys
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


def test_shipped_agents_follow_the_rule():
    """Every builder file that declares a mode declares acceptEdits; no read-only agent carries one."""
    modes = {}
    for f in sorted(AGENTS.glob("*.md")):
        data, _ = lint_agents.parse_frontmatter(f.read_text())
        assert lint_agents.permission_mode_problem(data) is None, f.name
        if "permissionMode" in data:
            modes[f.stem] = lint_agents.get_inline(data, "permissionMode")
    assert set(modes.values()) <= {"acceptEdits", "plan"}
    assert {"coder", "main-coder", "ninja-coder", "supreme-coder", "test-engineer"} <= set(modes)
    assert "blackcat" not in modes          # the main thread follows the session's mode (Plan)
    for ro in ("code-reviewer", "security-auditor", "verifier", "planner", "plan-reviewer", "scout"):
        assert modes.get(ro) != "acceptEdits", ro
