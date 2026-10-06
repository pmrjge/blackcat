"""lib/codex_home.py: CODEX_HOME resolution and the refusal list (DESIGN.md §7.2)."""
from __future__ import annotations

import os
import stat

import pytest

from conftest import load_lib

ch = load_lib("codex_home")


def env_of(sh, **kw):
    e = {"HOME": str(sh["home"]), "XDG_STATE_HOME": str(sh["state"])}
    e.update(kw)
    return e


def res(sh, flag=None, repos=(), **env):
    return ch.resolve(flag, env_of(sh, **env), str(sh["home"]), str(sh["home"]), list(repos))


def test_default_created_0700(scratch_home):
    sh = scratch_home
    sh["codex_home"].rmdir()
    old = os.umask(0o022)
    try:
        r = res(sh)
    finally:
        os.umask(old)
    assert r["source"] == "default" and r["created"] is True
    assert r["path"] == str(sh["codex_home"])
    assert stat.S_IMODE(os.stat(r["path"]).st_mode) == 0o700


def test_default_existing_not_created(scratch_home):
    r = res(scratch_home)
    assert r["created"] is False and r["warn"] == []


def test_env_then_flag_precedence_and_warning(scratch_home, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir(mode=0o700)
    b.mkdir(mode=0o700)
    r = res(scratch_home, CODEX_HOME=str(a))
    assert (r["source"], r["path"]) == ("env", str(a))
    r = res(scratch_home, flag=str(b), CODEX_HOME=str(a))
    assert (r["source"], r["path"]) == ("flag", str(b))
    assert any("points elsewhere" in w for w in r["warn"])
    r = res(scratch_home, flag=str(b))
    assert any("export CODEX_HOME=" in w for w in r["warn"])


def test_tilde_and_relative_flag(scratch_home):
    (scratch_home["home"] / "cx").mkdir(mode=0o700)
    assert res(scratch_home, flag="~/cx")["path"] == str(scratch_home["home"] / "cx")
    assert res(scratch_home, flag="cx")["path"] == str(scratch_home["home"] / "cx")


@pytest.mark.parametrize("source", ["flag", "env"])
def test_explicit_path_must_exist(scratch_home, tmp_path, source):
    missing = tmp_path / "nope"
    kw = {"flag": str(missing)} if source == "flag" else {"CODEX_HOME": str(missing)}
    with pytest.raises(ch.CodexHomeError, match="does not exist"):
        res(scratch_home, **kw)
    assert not missing.exists()


def test_empty_flag_refused(scratch_home):
    with pytest.raises(ch.CodexHomeError, match="needs a path"):
        res(scratch_home, flag="")


def test_existing_file_refused(scratch_home, tmp_path):
    f = tmp_path / "file"
    f.write_text("x")
    with pytest.raises(ch.CodexHomeError, match="not a directory"):
        res(scratch_home, flag=str(f))


REFUSED = {
    "root": lambda sh, t: "/",
    "home": lambda sh, t: str(sh["home"]),
    "home-parent": lambda sh, t: str(sh["home"].parent),
    "documents": lambda sh, t: str(sh["home"] / "Documents"),
    "inside-claude": lambda sh, t: str(sh["home"] / ".claude" / "codex"),
    "claude-itself": lambda sh, t: str(sh["home"] / ".claude"),
    "ssh": lambda sh, t: str(sh["home"] / ".ssh" / "x"),
    "etc": lambda sh, t: "/etc/codex",
    "usr": lambda sh, t: "/usr/local/codex",
    "backups": lambda sh, t: str(sh["state"] / "codex-agent-stack-backups" / "x"),
    "claude-backups": lambda sh, t: str(sh["state"] / "claude-agent-stack-backups"),
    "guard-state": lambda sh, t: str(sh["state"] / "codex-agent-stack"),
    "repo": lambda sh, t: str(t / "repo" / "sub"),
    "quote": lambda sh, t: str(t / "it's"),
    "dollar": lambda sh, t: str(t / "a$b"),
    "newline": lambda sh, t: str(t / "a\nb"),
}


@pytest.mark.parametrize("case", sorted(REFUSED))
def test_refusal_list(scratch_home, tmp_path, case):
    path = REFUSED[case](scratch_home, tmp_path)
    if not path.startswith(("/etc", "/usr")) and path != "/" and "\n" not in path:
        os.makedirs(path, exist_ok=True)
    with pytest.raises(ch.CodexHomeError):
        res(scratch_home, flag=path, repos=[str(tmp_path / "repo")])


def test_claude_config_dir_env_refused(scratch_home, tmp_path):
    out = tmp_path / "outside"
    cfg = out / "cfg"
    (cfg / "codex").mkdir(parents=True)
    with pytest.raises(ch.CodexHomeError, match="Claude config"):
        res(scratch_home, flag=str(cfg / "codex"), CLAUDE_CONFIG_DIR=str(cfg))
    with pytest.raises(ch.CodexHomeError, match="contains the Claude config"):
        res(scratch_home, flag=str(out), CLAUDE_CONFIG_DIR=str(cfg))


def test_home_with_quote_refused_for_default(tmp_path):
    home = tmp_path / "o'neil"
    home.mkdir()
    with pytest.raises(ch.CodexHomeError):
        ch.resolve(None, {}, str(home), str(home), [])
    assert not (home / ".codex").exists()


def test_refusal_creates_nothing(scratch_home):
    sh = scratch_home
    target = sh["home"] / ".claude" / "codex"
    with pytest.raises(ch.CodexHomeError):
        res(sh, flag=str(target))
    assert not target.exists()


def test_symlinked_and_open_mode_warn(scratch_home, tmp_path):
    real = tmp_path / "real"
    real.mkdir(mode=0o755)
    real.chmod(0o755)
    link = tmp_path / "link"
    link.symlink_to(real)
    r = res(scratch_home, flag=str(link))
    assert r["real"] == os.path.realpath(real)
    assert any("symlink" in w for w in r["warn"]) and any("mode 755" in w for w in r["warn"])


def test_backup_root_paths(scratch_home):
    e = env_of(scratch_home)
    assert ch.default_backup_root(e, str(scratch_home["home"])) == str(
        scratch_home["state"] / "codex-agent-stack-backups")
    assert ch.default_backup_root({}, "/h") == "/h/.local/state/codex-agent-stack-backups"
    assert ch.default_state_dir({}, "/h") == "/h/.local/state/codex-agent-stack"
