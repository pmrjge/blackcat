"""hooks/stack_io.py (the hooks' and installer's shared file helpers) and what a missing copy does.

Run: ~/.claude/venvs/tools/bin/python -m pytest -q -p no:cacheprovider tests/test_stack_io.py
"""
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
spec = importlib.util.spec_from_file_location("stack_io_t", HOOKS / "stack_io.py")
io_ = importlib.util.module_from_spec(spec)
spec.loader.exec_module(io_)


def test_read_json_returns_objects_only(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"x": 1}')
    assert io_.read_json(str(p)) == {"x": 1}
    for body in ("[1, 2]", "3", "not json", '{"x": '):
        p.write_text(body)
        assert io_.read_json(str(p)) is None
        assert io_.read_json(str(p), {}) == {}
    p.write_bytes(b'{"x": "\xff"}')                       # not UTF-8
    assert io_.read_json(str(p)) is None
    p.write_text("[" * 100000 + "]" * 100000)               # RecursionError, not a crash
    assert io_.read_json(str(p)) is None
    assert io_.read_json(str(tmp_path / "missing.json"), "d") == "d"
    assert io_.read_json(str(tmp_path)) is None              # a directory


def test_read_json_limit(tmp_path):
    p = tmp_path / "a.json"
    p.write_text('{"x": 1}')                                 # 8 bytes
    assert io_.read_json(str(p), limit=8) == {"x": 1}
    assert io_.read_json(str(p), limit=7) is None


def test_write_json_atomic(tmp_path):
    p = tmp_path / "new" / "dir" / "a.json"                  # parents are created
    io_.write_json_atomic(str(p), {"b": 1, "a": [1, 2]})
    assert p.read_text() == '{"b":1,"a":[1,2]}'
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    io_.write_json_atomic(str(p), {"b": 1, "a": 2}, indent=2, sort_keys=True)
    assert p.read_text() == '{\n  "a": 2,\n  "b": 1\n}\n'
    assert sorted(os.listdir(p.parent)) == ["a.json"]        # no temporary file left


def test_write_atomic_replaces_a_symlink_never_writes_through(tmp_path):
    victim = tmp_path / "victim"
    victim.write_text("keep")
    link = tmp_path / "out.json"
    link.symlink_to(victim)
    io_.write_atomic(str(link), b"{}", mode=0o644)
    assert victim.read_text() == "keep"
    assert not link.is_symlink() and link.read_bytes() == b"{}"
    assert stat.S_IMODE(link.stat().st_mode) == 0o644 & ~_umask()


def test_write_atomic_failure_leaves_target_and_no_temporary(tmp_path):
    p = tmp_path / "a.json"
    p.write_text("old")
    with pytest.raises(TypeError):
        io_.write_atomic(str(p), "text, not bytes")
    assert p.read_text() == "old"
    assert sorted(os.listdir(tmp_path)) == ["a.json"]
    with pytest.raises(TypeError):
        io_.write_json_atomic(str(p), {"x": object()})       # not serializable: nothing written
    assert p.read_text() == "old"


def test_write_atomic_fsync(tmp_path, monkeypatch):
    """fsync=True syncs the temporary file before the rename (stack_limits' live.json relies on it)."""
    calls = []
    real = os.fsync
    monkeypatch.setattr(io_.os, "fsync", lambda fd: (calls.append(fd), real(fd)))
    io_.write_atomic(str(tmp_path / "a"), b"x")
    assert calls == []
    io_.write_atomic(str(tmp_path / "b"), b"y", fsync=True)
    assert len(calls) == 1 and (tmp_path / "b").read_bytes() == b"y"


def test_now_iso():
    assert io_.now_iso(0) == "1970-01-01T00:00:00Z"
    assert len(io_.now_iso()) == 20


def _umask():
    m = os.umask(0)
    os.umask(m)
    return m


@pytest.mark.parametrize("broken", [None, "def read_json(:\n"])         # missing; present with a SyntaxError
def test_guard_without_stack_io_starts_and_fails_closed(tmp_path, broken):
    """A partial or damaged install (stack_io.py missing, or unparseable): the guard still starts; a
    subagent's spawn, which needs its state, is denied (guard_error), never let through by a crash;
    no-push still refuses a push; --self-test fails."""
    hooks = tmp_path / "cfg" / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy(HOOKS / "agent_guard.py", hooks / "agent_guard.py")
    if broken:
        (hooks / "stack_io.py").write_text(broken)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "BLACKCAT_"))}
    env.update(XDG_STATE_HOME=str(tmp_path / "state"), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"),
               STACK_USAGE_COLLECT="0", PYTHONDONTWRITEBYTECODE="1")
    ev = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Agent",       # a subagent's spawn
          "agent_type": "orchestrator", "agent_id": "a1", "tool_use_id": "tu-1",       # its fan-out lease is state
          "tool_input": {"subagent_type": "coder", "description": "x", "prompt": "do x"},
          "transcript_path": str(tmp_path / "t.jsonl"), "cwd": str(tmp_path)}
    p = subprocess.run([sys.executable, str(hooks / "agent_guard.py")], input=json.dumps(ev), env=env,
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    out = json.loads(p.stdout)["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny" and "stack_io.py unusable" in out["permissionDecisionReason"]
    ev = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash",
          "tool_input": {"command": "git push origin main"}, "cwd": str(tmp_path)}
    p = subprocess.run([sys.executable, str(hooks / "agent_guard.py"), "no-push"], input=json.dumps(ev),
                       env=env, capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0 and json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    p = subprocess.run([sys.executable, str(hooks / "agent_guard.py"), "--self-test"], env=env,
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 1 and "FAIL stack_io.py unusable" in p.stdout
