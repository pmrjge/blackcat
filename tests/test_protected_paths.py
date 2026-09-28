"""Tests for agent_guard.py's "protect" scan kind: a Bash-level write (redirection, cp/mv/
install/rsync, tee, dd, sed/perl -i) is denied when it targets a path already denied to the
Read/Edit/Write tools (hooks/, bin/, settings.json, .git/, .claude/settings*.json). Claude Code's
own protected-path check applies to the Edit/Write tools, not to raw Bash, and bypassPermissions
mode (the stack's default) skips even that — this hook is the replacement, and it must not block
ordinary Bash writes elsewhere.

Run: uv run --with pytest pytest -q tests/test_protected_paths.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC_HOOK = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
SRC_SETTINGS = ROOT / "dot-claude" / "settings.json"


@pytest.fixture
def installed(tmp_path):
    """A rendered, installed-looking config dir (__CLAUDE_DIR__ substituted for real) plus a
    project directory with its own .claude/, so the deny rules the hook reads actually resolve to
    real paths instead of the literal template placeholder."""
    cfg = tmp_path / "claude"
    (cfg / "hooks").mkdir(parents=True)
    shutil.copy(SRC_HOOK, cfg / "hooks" / "agent_guard.py")
    settings = SRC_SETTINGS.read_text().replace("__CLAUDE_DIR__", str(cfg))
    (cfg / "settings.json").write_text(settings)
    proj = tmp_path / "proj"
    (proj / ".claude" / "agents").mkdir(parents=True)
    (proj / ".git").mkdir()
    sys.path.insert(0, str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)
    import agent_guard as g
    yield g, cfg, proj
    sys.path.remove(str(cfg / "hooks"))
    sys.modules.pop("agent_guard", None)


def test_redirect_into_hooks_or_settings_or_bin_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for target, op in [(cfg / "hooks" / "agent_guard.py", ">"), (cfg / "settings.json", ">>"),
                       (cfg / "bin" / "mcp-headers", ">")]:
        got = g.protected_write_in("echo x %s %s" % (op, target), ev)
        assert got and got[0] == "protect", target


def test_write_commands_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    target = str(cfg / "hooks" / "agent_guard.py")
    cases = [
        "cp new.py %s" % target,
        "mv new.py %s" % target,
        "sed -i s/x/y/ %s" % target,
        "sed -i.bak s/x/y/ %s" % target,
        "tee %s <<< x" % target,
        "dd if=/dev/zero of=%s" % target,
        "cp -t %s new.py" % (cfg / "hooks"),
        "install -m 0644 new.py %s" % target,
    ]
    for cmd in cases:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_nested_shells_still_caught(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    target = str(cfg / "hooks" / "agent_guard.py")
    for cmd in ["bash -c 'echo x > %s'" % target, "eval \"echo x > %s\"" % target,
               "sh -c \"sed -i s/x/y/ %s\"" % target]:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_project_git_and_claude_settings_denied(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for cmd in ["echo x > .git/config", "echo x > .claude/settings.json",
               "echo x > .claude/settings.local.json", "echo x > .claude/hooks/x.py"]:
        got = g.protected_write_in(cmd, ev)
        assert got and got[0] == "protect", cmd


def test_ordinary_writes_allowed(installed):
    g, cfg, proj = installed
    ev = {"cwd": str(proj)}
    for cmd in ["echo x > /tmp/whatever.txt", "cp foo.txt bar.txt", "echo hi",
               "echo x > .claude/agents/coder.md", "sed -i s/x/y/ README.md",
               "cp a.py b.py", "tee out.log <<< x", "git commit -am 'x'"]:
        got = g.protected_write_in(cmd, ev)
        assert got is None, (cmd, got)


def run_hook(installed_hook_path, command, **env):
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": command}, "cwd": env.pop("cwd", None)}
    return subprocess.run([sys.executable, str(installed_hook_path), "no-push"],
                          input=json.dumps(ev), capture_output=True, text=True, timeout=30,
                          env=dict(os.environ, **env))


def test_hook_denies_protected_write_end_to_end(installed):
    g, cfg, proj = installed
    hook_path = cfg / "hooks" / "agent_guard.py"
    target = str(cfg / "settings.json")
    p = run_hook(hook_path, "echo x > %s" % target, cwd=str(proj), STACK_POLICY="off")
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "protected-path rule" in out["permissionDecisionReason"]


def test_hook_allows_ordinary_write_end_to_end(installed):
    g, cfg, proj = installed
    hook_path = cfg / "hooks" / "agent_guard.py"
    p = run_hook(hook_path, "echo x > /tmp/whatever.txt", cwd=str(proj))
    assert p.returncode == 0 and p.stdout == "", p.stderr


def test_settings_wire_ask_rules_and_protected_paths():
    s = json.loads(SRC_SETTINGS.read_text())
    ask = set(s["permissions"].get("ask") or [])
    assert {"mcp__magg__magg_add_server", "mcp__magg__magg_load_kit",
            "mcp__magg__proxy"} <= ask
    deny = set(s["permissions"]["deny"])
    assert {"Edit(.git/**)", "Edit(.claude/settings.json)",
            "Edit(.claude/settings.local.json)", "Edit(.claude/hooks/**)"} <= deny
    # agents/, skills/ etc. in a project's .claude/ stay editable: only the settings/hooks are
    # locked down, matching the global config's own scope
    assert "Edit(.claude/**)" not in deny
