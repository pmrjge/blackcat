"""bin/claude-ultracode (claude-ninja, claude-supreme, claude-ultracode <agent>): the main thread
starts in Plan unless you pass a mode yourself. The builders' agent files carry
`permissionMode: acceptEdits` for their subagent runs; the launcher passes `--permission-mode plan`
so a main-thread builder follows the stack's default whatever Claude Code does with that line.

The launcher execs `claude`: tests/fake-claude/claude stands in for it and logs its argv.

Run: uv run --with pytest pytest -q tests/test_ultracode_launcher.py
"""
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "dot-claude" / "bin" / "claude-ultracode"
FAKE_CLAUDE = ROOT / "tests" / "fake-claude"
SETTINGS = '{"permissions":{"allow":["Workflow"]}}'


def launch(tmp_path, name, *args):
    """Run the launcher under `name` (a symlink, as install.sh links it); the argv claude got."""
    link = tmp_path / name
    if not link.exists():
        link.symlink_to(LAUNCHER)
    log = tmp_path / "claude.log"
    log.unlink(missing_ok=True)
    env = {"PATH": "%s:/usr/bin:/bin" % FAKE_CLAUDE, "HOME": str(tmp_path), "FAKE_CLAUDE_LOG": str(log),
           "GITHUB_TOKEN": "gh_x"}
    p = subprocess.run([str(link), *args], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(log.read_text().splitlines()[-1])


@pytest.mark.parametrize("name,agent", [("claude-ninja", "ninja-coder"), ("claude-supreme", "supreme-coder")])
def test_default_adds_plan_once(tmp_path, name, agent):
    argv = launch(tmp_path, name, "-p", "hello")
    assert argv == ["--agent", agent, "--effort", "ultracode", "--settings", SETTINGS,
                    "--permission-mode", "plan", "-p", "hello"]
    assert argv.count("--permission-mode") == 1


def test_claude_ultracode_takes_the_agent_and_adds_plan(tmp_path):
    argv = launch(tmp_path, "claude-ultracode", "main-coder", "--resume", "abc")
    assert argv == ["--agent", "main-coder", "--effort", "ultracode", "--settings", SETTINGS,
                    "--permission-mode", "plan", "--resume", "abc"]


@pytest.mark.parametrize("user", [
    ["--permission-mode", "acceptEdits"],
    ["--permission-mode=bypassPermissions"],
    ["--dangerously-skip-permissions"],
    ["-p", "hi", "--permission-mode", "plan"],          # already plan: still one flag
])
def test_a_mode_you_pass_wins_and_is_not_doubled(tmp_path, user):
    argv = launch(tmp_path, "claude-ninja", *user)
    assert argv[:6] == ["--agent", "ninja-coder", "--effort", "ultracode", "--settings", SETTINGS]
    assert argv[6:] == user                              # passed through as given, nothing added
    assert sum(a == "--permission-mode" or a.startswith("--permission-mode=") for a in argv) \
        == sum(a == "--permission-mode" or a.startswith("--permission-mode=") for a in user)


def test_text_after_double_dash_is_not_a_mode(tmp_path):
    """After `--` everything is a positional argument (the prompt), not a flag of yours."""
    argv = launch(tmp_path, "claude-supreme", "-p", "--", "--permission-mode")
    assert argv[6:] == ["--permission-mode", "plan", "-p", "--", "--permission-mode"]


def test_forge_tokens_stay_out(tmp_path):
    link = tmp_path / "claude-ninja"
    link.symlink_to(LAUNCHER)
    probe = tmp_path / "bin"
    probe.mkdir()
    (probe / "claude").write_text('#!/bin/sh\nprintf "%s" "${GITHUB_TOKEN:-unset}"\n')
    (probe / "claude").chmod(0o755)
    env = {"PATH": "%s:/usr/bin:/bin" % probe, "HOME": str(tmp_path), "GITHUB_TOKEN": "gh_x"}
    p = subprocess.run([str(link)], env=env, capture_output=True, text=True, timeout=30)
    assert p.returncode == 0 and p.stdout == "unset"


def test_usage_without_an_agent(tmp_path):
    link = tmp_path / "claude-ultracode"
    link.symlink_to(LAUNCHER)
    p = subprocess.run([str(link)], env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True,
                       timeout=30)
    assert p.returncode == 2 and "usage: claude-ultracode <agent>" in p.stderr
    assert os.access(LAUNCHER, os.X_OK)
