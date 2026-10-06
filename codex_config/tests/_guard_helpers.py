"""Shared helpers of the guard tests (test_guard*.py, test_stub.py): a scratch install of the guard
under tmp_path, events built from the hooks_schema.rs fixtures, and ways to run the guard in-process
(fast) or through the sh stub (real). Nothing here reads or writes the real ~/.codex, ~/.agents,
~/.claude or ~/.local/state: every path is under the test's tmp_path."""
from __future__ import annotations

import copy
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
CODEX_CONFIG = TESTS.parent
REPO = CODEX_CONFIG.parent
HOOKS_SRC = CODEX_CONFIG / "hooks"
DOT_HOOKS = REPO / "dot-claude" / "hooks"
FIXTURES = TESTS / "fixtures" / "guard"
VENDOR = TESTS / "fixtures" / "vendor"
GUARD_TEMPLATE = CODEX_CONFIG / "templates" / "guard.base.json"


def load_by_path(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def support_files():
    return [line.strip() for line in (HOOKS_SRC / "SUPPORT_FILES").read_text().splitlines()
            if line.strip()]


class Stack(object):
    """A staged CODEX_HOME under tmp_path: <home>/.codex/stack/{bin,hooks,policy}, a scratch
    project dir and a state dir, laid out as INTERFACES.md §2 describes."""

    def __init__(self, tmp_path, python=None, guard_overrides=None, agents=None, layout="stack"):
        self.root = Path(tmp_path)
        self.home = self.root / "home"
        self.codex_home = self.home / ".codex"
        self.stack = self.codex_home / "stack"
        self.state = self.home / ".local" / "state" / "codex-agent-stack"
        self.project = self.root / "proj"
        self.xdg = self.root / "xdg-state"
        for d in (self.stack / "bin", self.stack / "hooks", self.stack / "policy", self.project,
                  self.home / ".agents" / "skills", self.xdg):
            d.mkdir(parents=True, exist_ok=True)
        if layout == "flat":
            self.hooks_dir = self.root / "managed"
            self.bin_dir = self.hooks_dir
            self.policy_dir = self.hooks_dir
            self.hooks_dir.mkdir()
        else:
            self.hooks_dir = self.stack / "hooks"
            self.bin_dir = self.stack / "bin"
            self.policy_dir = self.stack / "policy"
        shutil.copy2(HOOKS_SRC / "codex_guard.py", self.hooks_dir / "codex_guard.py")
        for rel in support_files():
            shutil.copy2(REPO / rel, self.hooks_dir / Path(rel).name)
        shutil.copy2(HOOKS_SRC / "codex-hook", self.bin_dir / "codex-hook")
        os.chmod(self.bin_dir / "codex-hook", 0o755)
        if python:
            os.symlink(python, self.bin_dir / "stack-python")
        (self.codex_home / "auth.json").write_text('{"token": "secret"}')
        (self.codex_home / "stack.env").write_text("EXA_API_KEY=x\n")
        (self.codex_home / "config.toml").write_text("model = 'x'\n")
        self.guard = self.guard_json(guard_overrides or {})
        self.agents = agents if agents is not None else json.loads(
            (FIXTURES / "agents.json").read_text())
        self.write_policy()

    def guard_json(self, overrides):
        g = json.loads(GUARD_TEMPLATE.read_text())
        g.update({"codex_home": str(self.codex_home), "home": str(self.home),
                  "state_dir": str(self.state), "stack": str(self.stack),
                  "protected_roots": [str(self.codex_home), str(self.home / ".agents"),
                                      str(self.state)],
                  "credentials": {"paths": [str(self.home / ".ssh"), str(self.home / ".aws")],
                                  "globs": ["**/.env", "**/.env.*"]},
                  "toolsmith_wrapper": str(self.stack / "bin" / "stack-install")})
        g.update(overrides)
        return g

    def write_policy(self):
        (self.policy_dir / "guard.json").write_text(json.dumps(self.guard, indent=1))
        (self.policy_dir / "agents.json").write_text(json.dumps(self.agents, indent=1))

    @property
    def guard_py(self):
        return self.hooks_dir / "codex_guard.py"

    @property
    def stub(self):
        return self.bin_dir / "codex-hook"

    def env(self, **extra):
        env = {"PATH": "/usr/bin:/bin", "HOME": str(self.home), "XDG_STATE_HOME": str(self.xdg),
               "TMPDIR": str(self.root / "tmp"), "LANG": "C"}
        (self.root / "tmp").mkdir(exist_ok=True)
        env.update(extra)
        return env


def event(kind, **over):
    """An event from the hooks_schema.rs fixture `kind`; agent_type=None drops agent_id and
    agent_type (the main thread); other keys override."""
    ev = json.loads((FIXTURES / "events" / ("%s.json" % kind)).read_text())
    if "agent_type" in over and over["agent_type"] is None:
        over = dict(over)
        del over["agent_type"]
        ev.pop("agent_type", None)
        ev.pop("agent_id", None)
        over.pop("agent_id", None)
    ev.update(over)
    return ev


def pre(tool, tool_input, agent_type="coder", agent_id="agent-1", **over):
    ev = event("pre_tool_use", tool_name=tool, tool_input=tool_input, agent_type=agent_type,
               agent_id=agent_id, **over)
    return ev


def bash(command, agent_type="coder", agent_id="agent-1", **over):
    return pre("Bash", {"command": command}, agent_type, agent_id, **over)


class Guard(object):
    """The guard module loaded from a Stack's hooks dir (GUARD_DIR is the staged copy), run
    in-process through codex_guard.run with the given event on stdin."""

    def __init__(self, stack, monkeypatch):
        self.stack = stack
        for k, v in stack.env().items():       # HOME, XDG_STATE_HOME, TMPDIR: all under tmp_path
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("CODEX_HOME", raising=False)
        self.mod = load_by_path("codex_guard_under_test_%d" % id(self), stack.guard_py)

    def run(self, mode, ev, scope=None):
        argv = [mode] + (["--scope", "global"] if scope == "global" else [])
        out = io.StringIO()
        raw = ev if isinstance(ev, bytes) else json.dumps(ev).encode("utf-8")
        rc = self.mod.run(argv, io.BytesIO(raw), out)
        text = out.getvalue()
        return rc, (json.loads(text) if text.strip() else None)

    def pre(self, ev, scope=None):
        rc, out = self.run("pre_tool_use", self._cwd(ev), scope)
        assert rc == 0
        return out

    def perm(self, ev, scope=None):
        rc, out = self.run("permission_request", self._cwd(ev), scope)
        assert rc == 0
        return out

    def observe(self, mode, ev):
        rc, out = self.run(mode, self._cwd(ev))
        assert rc == 0 and out is None
        return out

    def _cwd(self, ev):
        if isinstance(ev, dict) and ev.get("cwd") == "/":
            ev = dict(ev, cwd=str(self.stack.project))
        return ev


def decision(out):
    """"deny", "allow" (with updatedInput) or None for a PreToolUse output."""
    return None if out is None else out["hookSpecificOutput"]["permissionDecision"]


def reason(out):
    return out["hookSpecificOutput"].get("permissionDecisionReason", "")


def perm_denied(out):
    return out is not None and out["hookSpecificOutput"]["decision"]["behavior"] == "deny"


def run_stub(stack, mode, ev, scope=None, env=None, stub=None, timeout=30):
    """Run the hook the way Codex does: /bin/sh '<stub>' <mode>, the event on stdin."""
    argv = ["/bin/sh", str(stub or stack.stub), mode] + (["--scope", "global"] if scope else [])
    if isinstance(ev, dict) and ev.get("cwd") == "/":
        ev = dict(ev, cwd=str(stack.project))
    data = ev if isinstance(ev, bytes) else json.dumps(ev).encode("utf-8")
    p = subprocess.run(argv, input=data, capture_output=True, timeout=timeout,
                       env=env or stack.env(), cwd=str(stack.project))
    out = p.stdout.decode().strip()
    return p.returncode, (json.loads(out) if out else None), p.stderr.decode()


def interpreter():
    """The real interpreter behind sys.executable (a uv venv's python is a link to it)."""
    return os.path.realpath(sys.executable)


def deepcopy(x):
    return copy.deepcopy(x)
