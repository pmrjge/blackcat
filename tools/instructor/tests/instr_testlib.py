"""Helpers for the instructor tests: scratch repositories with worktrees, script runs, status lines."""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

BIN = Path(__file__).resolve().parents[1] / "bin"

STATUS_RE = re.compile(r"^(OK|FAIL|NOOP) ([a-z-]+)((?: [a-z_]+=\S+)*) log=(\S+)$")


def git(*args, cwd: Path) -> str:
    """git in a scratch repository: no hooks, no signing, fixed identity."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                         "-c", "init.defaultBranch=main", "-c", "user.name=t",
                         "-c", "user.email=t@example.invalid", *args],
                        cwd=cwd, env=env, capture_output=True, text=True, check=True,
                        stdin=subprocess.DEVNULL)
    return cp.stdout.strip()


def commit(repo: Path, name: str, text: str = "x\n") -> str:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    git("add", "--", name, cwd=repo)
    git("commit", "-q", "-m", f"add {name}", cwd=repo)
    return git("rev-parse", "HEAD", cwd=repo)


def scratch(tmp_path: Path, files: dict[str, str] | None = None) -> tuple[Path, Path]:
    """A repository `m` on main (with `files` committed) and a worktree `wt` on branch feat one
    commit ahead. Returns (main checkout, feat worktree)."""
    m, wt = tmp_path / "m", tmp_path / "wt"
    m.mkdir()
    git("init", "-q", cwd=m)
    commit(m, "a.txt", "a\n")
    for name, text in (files or {}).items():
        commit(m, name, text)
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=m)
    commit(wt, "b.txt", "b\n")
    return m, wt


def sha(repo: Path, ref: str) -> str:
    return git("rev-parse", "--verify", ref, cwd=repo)


def run_script(name: str, *args: str, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    return subprocess.run([sys.executable, str(BIN / name), *args], cwd=cwd, env=env, text=True,
                          capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL)


def status(stdout: str) -> tuple[str, str, dict[str, str], str]:
    """The single status line: (status, verb, keys, log). Fails unless stdout is exactly one line."""
    lines = stdout.splitlines()
    assert len(lines) == 1, stdout
    m = STATUS_RE.match(lines[0])
    assert m, lines[0]
    kv = dict(f.split("=", 1) for f in m.group(3).split())
    return m.group(1), m.group(2), kv, m.group(4)
