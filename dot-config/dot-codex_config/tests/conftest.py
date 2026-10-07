"""Shared fixtures for dot-config/dot-codex_config/tests. Owned by the build lead: children add helpers in their own
test modules (or tests/_<area>_helpers.py), never here.

Every test runs against a scratch HOME and a scratch CODEX_HOME under tmp_path: nothing here may
read or write the real ~/.codex, ~/.agents, ~/.claude or /etc, and no test may run a real `codex`
(the fake CLI in tests/fake-codex/ is first on PATH and exits 97 on any unsupported subcommand).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
CODEX_CONFIG = TESTS.parent
REPO = CODEX_CONFIG.parent.parent   # <repo>/dot-config/dot-codex_config
LIB = CODEX_CONFIG / "lib"
FAKE_CODEX_DIR = TESTS / "fake-codex"
VENDOR = TESTS / "fixtures" / "vendor"

sys.path.insert(0, str(TESTS))   # test helper modules (tests/_*_helpers.py)


def load_lib(name: str, path: Path | None = None):
    """Import dot-config/dot-codex_config/lib/<name>.py (or `path`) by file path, the way the installer does."""
    p = Path(path) if path else LIB / ("%s.py" % name)
    spec = importlib.util.spec_from_file_location("codex_config_" + name, p)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def scratch_home(tmp_path, monkeypatch):
    """A scratch HOME with an empty CODEX_HOME (~/.codex, 0700) and ~/.agents/skills; env points at them;
    the fake codex is first on PATH. Returns a dict of Paths: home, codex_home, skills_root, state."""
    home = tmp_path / "home"
    codex_home = home / ".codex"
    skills_root = home / ".agents" / "skills"
    state = home / ".local" / "state"
    for d in (codex_home, skills_root, state):
        d.mkdir(parents=True)
    codex_home.chmod(0o700)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("PATH", str(FAKE_CODEX_DIR) + os.pathsep + os.environ.get("PATH", ""))
    return {"home": home, "codex_home": codex_home, "skills_root": skills_root, "state": state}
