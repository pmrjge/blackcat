"""Helpers for the part-A foundation tests (codex_home, codex_state, source_snapshot, skill_links).

Everything works under a scratch directory: a temporary git repository built from copies of this
repository's files, scratch HOME/CODEX_HOME trees, subprocesses of the current interpreter.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from conftest import CODEX_CONFIG, REPO

# the files a snapshot needs to run codex_state.py (the engine loads dot-claude/hooks/stack_io.py)
MINI_REPO_FILES = ("lib/install_state.py", "lib/claude_md_block.py", "lib/stack.env.example",
                   "dot-claude/hooks/stack_io.py")


def git_env(extra=None):
    """An environment for test-side git commands: no user or system config, fixed identity."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t",
               GIT_AUTHOR_EMAIL="t@example.invalid", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@example.invalid", GIT_TERMINAL_PROMPT="0")
    env.update(extra or {})
    return env


def git(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), "-c", "commit.gpgsign=false", *args], env=git_env(),
                          capture_output=True, text=True, check=check)


def make_repo(root: Path) -> Path:
    """A git repository at root holding codex_config/lib (this checkout's) and the engine files, with
    one commit."""
    root.mkdir(parents=True)
    for rel in MINI_REPO_FILES:
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, dst)
    shutil.copytree(CODEX_CONFIG / "lib", root / "codex_config" / "lib",
                    ignore=shutil.ignore_patterns("__pycache__"))
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


def run_py(script, *args, env=None, cwd=None):
    """Run a Python script with this interpreter; returns the CompletedProcess (text)."""
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True,
                          env=env if env is not None else dict(os.environ), cwd=cwd)


def write_json(path, obj):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj))
    return Path(path)


def write(path, text, mode=None):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    if mode is not None:
        p.chmod(mode)
    return p
