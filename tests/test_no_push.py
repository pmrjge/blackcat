"""Tests for agent_guard.py no-push mode: the stack's Git rule says agents never push.

Run: uv run --with pytest pytest -q tests/test_no_push.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "dot-claude" / "hooks" / "agent_guard.py"
sys.path.insert(0, str(GUARD.parent))
import agent_guard as G  # noqa: E402

PUSHES = [
    "git push", "git push origin main", "git push --force-with-lease", "git -C /x push",
    "git -c a=b push origin", "git 'push' origin", "cd x && git push", "cd x; git push", "cd x\ngit push",
    "/usr/bin/git push", "echo $(git push)", 'echo "$(git push origin)"', "echo `git push`",
    "git --git-dir=/r/.git push", "git --git-dir /r/.git push", "git --no-pager push",
    "git lfs push origin main", "git subtree push --prefix=d r main", "git send-pack r", "(git push)",
    "git -C x push 2>&1 | tail", "FOO=1 git push", "git status && git push -u origin HEAD",
    "git -C 'dir with space' push",
    "git commit -m \"$(cat <<'EOF'\nmsg\nEOF\n)\" && git push",
    "cat <<EOF > f\nx\nEOF\ngit push",
]
NOT_PUSHES = [
    "git status", 'git commit -m "document the git push rule"', "git log --grep push", "git help push",
    "grep -rn 'git push' .", "git merge --ff-only feat", "git -C /x merge --ff-only push",
    "git config push.default current", "ls", "gitk --all", "git branch push-fix", "git switch -c push",
    "git log -- push.py", "python3 x.py push", 'git commit -m "x',
    "git commit -m \"$(cat <<'EOF'\nAgents never git push.\ngit push is the user's step\nEOF\n)\"",
    "git commit -F - <<EOF\nno git push here\nEOF",
]


@pytest.mark.parametrize("command", PUSHES)
def test_push_detected(command):
    assert G.git_push_in(command)


@pytest.mark.parametrize("command", NOT_PUSHES)
def test_non_push_allowed(command):
    assert not G.git_push_in(command)


def run_hook(command, **env):
    ev = {"session_id": "t", "hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": command}}
    return subprocess.run([sys.executable, str(GUARD), "no-push"], input=json.dumps(ev),
                          capture_output=True, text=True, timeout=30, env=dict(os.environ, **env))


def test_hook_denies_push_even_with_policy_off():
    for policy in ("on", "off"):
        p = run_hook("git -C . push origin main", STACK_POLICY=policy)
        assert p.returncode == 0
        out = json.loads(p.stdout)["hookSpecificOutput"]
        assert out["permissionDecision"] == "deny" and "never push" in out["permissionDecisionReason"]


def test_hook_allows_other_git():
    p = run_hook("git merge --ff-only feature")
    assert p.returncode == 0 and p.stdout == ""


def test_settings_wire_no_push():
    s = json.loads((ROOT / "dot-claude" / "settings.json").read_text())
    assert "Bash(git push *)" in s["permissions"]["deny"]
    hooks = [h for g in s["hooks"]["PreToolUse"] if g.get("matcher") == "Bash" for h in g["hooks"]]
    assert any(h.get("if") == "Bash(git *)" and h["command"].endswith("agent_guard.py\" no-push") for h in hooks)
    assert s["worktree"]["baseRef"] == "head"
