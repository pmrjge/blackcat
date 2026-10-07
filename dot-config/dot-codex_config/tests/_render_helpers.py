"""Shared helpers for the wave-2 render and doctor tests (lib/render.py, lib/doctor.py).

Every run is in-process against a scratch HOME/CODEX_HOME under pytest's tmp dirs: the "live"
CODEX_HOME is staged with codex_state.stage(), render.main() writes the stage and a work dir, and
the fake codex (tests/fake-codex) answers `execpolicy check`. Nothing here reads or writes the real
~/.codex, ~/.agents or ~/.claude, and no real codex runs.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import weakref
from pathlib import Path

from conftest import FAKE_CODEX_DIR, REPO, load_lib

render = load_lib("render")
codex_state = load_lib("codex_state")
config_region = load_lib("config_region")
doctor = load_lib("doctor")
hook_defs = load_lib("hook_defs")
FAKE_CODEX = FAKE_CODEX_DIR / "codex"
EXAMPLE_ENV = REPO / "lib" / "stack.env.example"
GUARD_BASE = REPO / "dot-config" / "dot-codex_config" / "templates" / "guard.base.json"
USER_SCOPE = ("exa", "jina", "wolfram", "huggingface")


class Env:
    """One scratch machine: home, live CODEX_HOME, XDG state, a stage and a work dir per run.

    The machine lives in a SHORT directory under $TMPDIR (removed when the object goes), not in
    pytest's tmp_path: the skills listing budget counts each skill's path (convert_skills), and
    pytest's long per-test paths alone push the 128 listed skills past skills.max_context_tokens."""

    def __init__(self, _tmp_path=None):
        self.root = Path(tempfile.mkdtemp(prefix="cr-"))
        weakref.finalize(self, shutil.rmtree, str(self.root), True)
        self.home = self.root / "home"
        self.ch = self.home / ".codex"
        self.state = self.home / ".local" / "state"
        self.skills_root = self.home / ".agents" / "skills"
        for d in (self.ch, self.state, self.skills_root):
            d.mkdir(parents=True, exist_ok=True)
        self.ch.chmod(0o700)
        self.stage = self.root / "stage"
        self.work = self.root / "work"
        self.runs = 0

    def new_stage(self) -> Path:
        """A fresh stage of the live CODEX_HOME (codex_state.py stage)."""
        if self.stage.exists():
            shutil.rmtree(self.stage)
        self.stage.mkdir()
        codex_state.stage(str(self.ch), str(self.stage))
        return self.stage

    def argv(self, *flags, stage=None, work=None, codex="none"):
        a = ["--src", str(REPO), "--stage", str(stage or self.stage), "--work", str(work or self.work),
             "--codex-home", str(self.ch), "--home", str(self.home)]
        if codex is not None and "--codex" not in flags:
            a += ["--codex", str(codex)]
        return a + list(flags)

    def run(self, *flags, stage=None, work=None, codex="none", env=None):
        """(rc, stdout, stderr) of render.main() on the stage."""
        out, err = io.StringIO(), io.StringIO()
        with patched_env(dict({"XDG_STATE_HOME": str(self.state), "FAKE_CODEX_PYTHON": sys.executable},
                              **(env or {}))):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = render.main(self.argv(*flags, stage=stage, work=work, codex=codex))
        self.runs += 1
        return rc, out.getvalue(), err.getvalue()

    def ok(self, *flags, **kw):
        rc, out, err = self.run(*flags, **kw)
        assert rc == 0, err
        return out

    def manifest(self, stage=None, work=None) -> dict:
        """Write the stage's manifest (codex_state.py manifest): the stage then stands for the live
        CODEX_HOME after an apply, and the next render sees it as the old manifest."""
        return codex_state.write_manifest(str(stage or self.stage), "c0ffee" * 6 + "0000", str(work or self.work))

    def work_json(self, name, work=None):
        return json.loads(((work or self.work) / name).read_text())


@contextlib.contextmanager
def patched_env(values):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def snapshot(root: Path) -> dict:
    """{rel: bytes | ("link", target)} of every file and link below root."""
    out = {}
    root = Path(root)
    for d, dirs, files in os.walk(root):
        for name in sorted(files) + [x for x in dirs if os.path.islink(os.path.join(d, x))]:
            p = Path(d) / name
            rel = str(p.relative_to(root))
            out[rel] = ("link", os.readlink(p)) if p.is_symlink() else p.read_bytes()
    return out


def changed(a: dict, b: dict) -> set:
    return {k for k in set(a) | set(b) if a.get(k) != b.get(k)}


def toml(path: Path) -> dict:
    import tomllib
    return tomllib.loads(Path(path).read_text())


def region_docs(data: bytes) -> tuple:
    """(A doc, B doc) parsed from config.toml's two regions."""
    import tomllib
    spans = config_region.find(data)
    return tuple(tomllib.loads(data[s[0]:s[1]].decode()) if s else None for s in (spans["A"], spans["B"]))
