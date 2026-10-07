"""Helpers for the installer end-to-end tests (test_installer_e2e.py, test_installer_ide.py).

`Sandbox` owns one fixed scratch tree per test module:

    <root>/repo   a committed git copy of the tree this test file lives in (dot-config/dot-codex_config,
                  dot-config/dot-claude,
                  the engine files of lib/), so the tests work from mutate.py's temporary copy too
    <root>/home   scratch HOME (with ~/.codex, ~/.agents/skills, ~/.local/state)
    <root>/tmp    scratch TMPDIR

install.sh really runs (real render, fake codex first on PATH, STACK_PYTHON given) so each run costs
seconds. To keep the suite sane the tree is archived once in its two states ("fresh" and "installed")
and every test restores the archive over the SAME absolute path (the manifest and the skill links hold
absolute paths, so a copy elsewhere would not be equivalent).

Nothing here touches the real ~/.codex, ~/.agents, ~/.claude or /etc. install.sh runs in a new session
(no controlling terminal), so a prompt can never reach a real tty.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

from _foundation_helpers import git
from conftest import CODEX_CONFIG, FAKE_CODEX_DIR, REPO

ENGINE_FILES = ("lib/install_state.py", "lib/claude_md_block.py", "lib/stack.env.example")
INSTALL = "dot-config/dot-codex_config/install.sh"
BEGIN_A = "# >>> claude-agent-stack: begin A"
BEGIN_B = "# >>> claude-agent-stack: begin B"
END_A = "# <<< claude-agent-stack: end A <<<"
END_B = "# <<< claude-agent-stack: end B <<<"
EXCLUDED_SKILLS = ("claude-code-extensions", "override-agent", "stack-doctor", "stack-tree")


def installer_python() -> str:
    """The interpreter handed to install.sh: a real binary >= 3.11 (the one running pytest)."""
    return os.path.realpath(sys.executable)


def tree_hash(*paths, skip_pycache=True) -> str:
    """sha256 over the sorted listing (type, relative path, mode, content hash | link target) of each path."""
    h = hashlib.sha256()
    for base in paths:
        base = Path(base)
        h.update(("== %s\n" % base).encode())
        if not (base.exists() or base.is_symlink()):
            h.update(b"absent\n")
            continue
        for p in sorted([base, *base.rglob("*")], key=lambda q: str(q)):
            rel = str(p.relative_to(base))
            if skip_pycache and "__pycache__" in p.parts:
                continue
            if p.is_symlink():
                h.update(("L %s -> %s\n" % (rel, os.readlink(p))).encode())
            elif p.is_file():
                h.update(("F %s %o %s\n" % (rel, p.stat().st_mode & 0o777,
                                            hashlib.sha256(p.read_bytes()).hexdigest())).encode())
            else:
                h.update(("D %s %o\n" % (rel, p.stat().st_mode & 0o777)).encode())
    return h.hexdigest()


class Sandbox:
    def __init__(self, root: Path):
        self.root = root
        self.repo = root / "repo"
        self.home = root / "home"
        self.ch = self.home / ".codex"
        self.skills = self.home / ".agents" / "skills"
        self.state = self.home / ".local" / "state"
        self.tmp = root / "tmp"
        self.archives = root.parent / (root.name + "-archives")
        self.archives.mkdir(parents=True, exist_ok=True)

    # ---- building ----------------------------------------------------------------------------------
    def build_repo(self):
        for rel in ENGINE_FILES:
            (self.repo / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, self.repo / rel)
        ign = shutil.ignore_patterns("__pycache__", "build", ".pytest_cache")
        shutil.copytree(CODEX_CONFIG, self.repo / "dot-config" / "dot-codex_config", ignore=ign)
        shutil.copytree(REPO / "dot-config" / "dot-claude", self.repo / "dot-config" / "dot-claude", ignore=ign)
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "gc.auto", "0")
        git(self.repo, "config", "maintenance.auto", "false")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "init")

    def fresh_dirs(self):
        for d in (self.ch, self.skills, self.state, self.tmp):
            d.mkdir(parents=True, exist_ok=True)
        self.ch.chmod(0o700)

    def archive(self, name: str):
        with tarfile.open(self.archives / (name + ".tar"), "w") as t:
            for d in (self.repo, self.home):
                t.add(d, arcname=d.name)

    def restore(self, name: str):
        for d in (self.repo, self.home, self.tmp):
            shutil.rmtree(d, ignore_errors=True)
        self.tmp.mkdir(parents=True)
        with tarfile.open(self.archives / (name + ".tar")) as t:
            t.extractall(self.root, filter="tar")

    # ---- running -----------------------------------------------------------------------------------
    def env(self, extra=None):
        e = {k: v for k, v in os.environ.items()
             if not k.startswith(("CLAUDE", "CODEX", "STACK_", "GIT_", "FAKE_CODEX"))}
        e.update(HOME=str(self.home), CODEX_HOME=str(self.ch), XDG_STATE_HOME=str(self.state),
                 TMPDIR=str(self.tmp), STACK_PYTHON=installer_python(), STACK_CODEX_VIA_TOP="1",
                 PATH=str(FAKE_CODEX_DIR) + os.pathsep + os.environ.get("PATH", ""))
        e.update(extra or {})
        return e

    def run(self, *args, extra=None, stdin="", ch_flag=True, check=None):
        """install.sh in the scratch tree. `--codex-home` is passed unless ch_flag is False."""
        cmd = ["bash", str(self.repo / INSTALL)]
        if ch_flag:
            cmd += ["--codex-home", str(self.ch)]
        cmd += [str(a) for a in args]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.env(extra), input=stdin,
                           cwd=str(self.tmp), start_new_session=True, timeout=600)
        if check is not None:
            assert r.returncode == check, "exit %s (wanted %s)\n--- stdout\n%s\n--- stderr\n%s" % (
                r.returncode, check, r.stdout[-3000:], r.stderr[-3000:])
        return r

    def commit(self, msg="edit"):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)
        return git(self.repo, "rev-parse", "HEAD").stdout.strip()

    def edit_repo(self, rel, old, new):
        p = self.repo / rel
        text = p.read_text()
        assert text.count(old) == 1, (rel, old)
        p.write_text(text.replace(old, new))
        return self.commit("edit " + rel)

    def hook_env(self, cmd: str, name="hook") -> dict:
        """Extra env putting a `codex` wrapper first on PATH: on the first `execpolicy` call (render, after the
        live CODEX_HOME was staged and before the plan) it runs the shell command `cmd`, then the fake codex."""
        d = self.root / ("bin-" + name)
        d.mkdir(exist_ok=True)
        (self.root / ("done-" + name)).unlink(missing_ok=True)
        script = d / "codex"
        script.write_text('#!/bin/sh\nif [ "$1" = execpolicy ] && [ ! -e "$CODEX_HOOK_DONE" ]; then\n'
                          '  : > "$CODEX_HOOK_DONE"; sh -c "$CODEX_HOOK_CMD" >&2\nfi\nexec "%s/codex" "$@"\n'
                          % FAKE_CODEX_DIR)
        script.chmod(0o755)
        return {"PATH": str(d) + os.pathsep + str(FAKE_CODEX_DIR) + os.pathsep + os.environ.get("PATH", ""),
                "CODEX_HOOK_CMD": cmd, "CODEX_HOOK_DONE": str(self.root / ("done-" + name))}

    # ---- observing ---------------------------------------------------------------------------------
    def fingerprint(self) -> str:
        """CODEX_HOME, ~/.agents, the state folders, and every other file of the scratch HOME."""
        return tree_hash(self.home)

    def config(self) -> bytes:
        return (self.ch / "config.toml").read_bytes()

    def backups(self):
        root = self.state / "codex-agent-stack-backups"
        return sorted(p for p in root.iterdir()) if root.is_dir() else []

    def manifest(self) -> dict:
        return json.loads((self.ch / ".stack-manifest.json").read_text())


def out(r) -> str:
    return r.stdout + r.stderr


def build_sandbox(tmp_path_factory, name="sbx") -> Sandbox:
    sbx = Sandbox(tmp_path_factory.mktemp(name))
    sbx.root.joinpath("tmp").mkdir(exist_ok=True)
    sbx.build_repo()
    sbx.fresh_dirs()
    sbx.archive("fresh")
    r = sbx.run("--yes", check=0)
    assert "Backup:" in r.stdout or "Plan:" in r.stdout
    sbx.archive("installed")
    return sbx


@pytest.fixture(scope="module")
def _sandbox(tmp_path_factory):
    return build_sandbox(tmp_path_factory)


@pytest.fixture
def fresh(_sandbox):
    """The scratch tree before any install."""
    _sandbox.restore("fresh")
    return _sandbox


@pytest.fixture
def installed(_sandbox):
    """The scratch tree after one `install.sh --yes`."""
    _sandbox.restore("installed")
    return _sandbox
