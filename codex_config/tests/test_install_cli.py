"""codex_config/install.sh (flags, usage, refusals, the steps before render) and lib/codex_diff.py.

Light CLI tests: every run uses a scratch git repository (copies of this checkout's codex_config, the
engine files and dot-claude, committed), a scratch HOME and CODEX_HOME, and the fake codex first on
PATH. render.py and doctor.py are replaced by recording stubs in that repository, so the argv the
installer builds for them is pinned here; the whole flow with the real render is smoke.sh's job.
Nothing here reads or writes the real ~/.codex, ~/.agents, ~/.claude or /etc.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

import pytest

from _foundation_helpers import git, write
from conftest import CODEX_CONFIG, FAKE_CODEX_DIR, REPO, load_lib

dg = load_lib("codex_diff")
INSTALL = "codex_config/install.sh"
ENGINE_FILES = ("lib/install_state.py", "lib/claude_md_block.py", "lib/stack.env.example")

STUB_RENDER = ("import json, os, sys\n"
               "json.dump(sys.argv[1:], open(os.environ['STUB_LOG'], 'w'))\n"
               "sys.exit(1)\n")
STUB_DOCTOR = ("import json, os, sys\n"
               "json.dump(sys.argv[1:], open(os.environ['STUB_LOG'], 'w'))\n"
               "print('doctor stub')\n"
               "sys.exit(1)\n")


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    """A committed scratch repository with the Codex installer, built once per module."""
    root = tmp_path_factory.mktemp("tpl") / "repo"
    root.mkdir()
    for rel in ENGINE_FILES:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO / rel, root / rel)
    ign = shutil.ignore_patterns("__pycache__", "build", ".pytest_cache")
    shutil.copytree(CODEX_CONFIG, root / "codex_config", ignore=ign)
    shutil.copytree(REPO / "dot-claude", root / "dot-claude", ignore=ign)
    (root / "codex_config" / "lib" / "render.py").write_text(STUB_RENDER)
    (root / "codex_config" / "lib" / "doctor.py").write_text(STUB_DOCTOR)
    git(root, "init", "-q", "-b", "main")
    git(root, "config", "gc.auto", "0")             # no background repack while the tests copy the objects
    git(root, "config", "maintenance.auto", "false")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    return root


@pytest.fixture
def env(template, tmp_path, scratch_home, monkeypatch):
    repo = tmp_path / "repo"
    shutil.copytree(template, repo, symlinks=True)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    log = tmp_path / "stub.json"
    monkeypatch.setenv("TMPDIR", str(tmp))
    monkeypatch.setenv("STACK_PYTHON", sys.executable)
    monkeypatch.setenv("STUB_LOG", str(log))
    monkeypatch.delenv("FAKE_CODEX_VERSION", raising=False)
    return dict(scratch_home, repo=repo, tmp=tmp, log=log)


def run(env, *args, path=None, extra=None, stdin=""):
    e = dict(os.environ, **(extra or {}))
    if path is not None:
        e["PATH"] = path
    return subprocess.run(["bash", str(env["repo"] / INSTALL), *map(str, args)], capture_output=True, text=True,
                          env=e, input=stdin, cwd=str(env["tmp"]))


def argv_of(env):
    return json.loads(env["log"].read_text())


def codex_home_state(env):
    ch = env["codex_home"]
    return sorted(str(p.relative_to(ch)) for p in ch.rglob("*"))


# ---- usage and refusals ------------------------------------------------------------------------
def test_help_lists_every_flag(env):
    r = run(env, "--help")
    assert r.returncode == 0 and r.stderr == ""
    for flag in ("--dry-run", "--diff", "--restore", "--force-config", "--yes", "--no-prompt", "--codex-home",
                 "--skills-root", "--profile-name", "--no-agents-md", "--no-mcp", "--legacy-sandbox",
                 "--git-allow-rules", "--no-escalation", "--with-rollout-budget", "--print-requirements",
                 "--doctor", "--ide-default", "--no-ide-default", "--no-astra-profile", "--force"):
        assert flag in r.stdout, flag
    assert run(env, "-h").stdout == r.stdout


@pytest.mark.parametrize("args", [
    ["--bogus"], ["--ide-default", "--no-ide-default"], ["--force-config"], ["--skills-root", "rel/path"],
    ["--profile-name", "bad name"], ["--profile-name", "-x"], ["--codex-home"], ["--codex-home="],
    ["--diff", "--restore"], ["--doctor", "--print-requirements"], ["--restore", "--doctor"],
    ["--no-ide-default", "--ide-default"], ["--profile-name"]])
def test_bad_usage_exits_2_with_usage(env, args):
    before = codex_home_state(env)
    r = run(env, *args)
    assert r.returncode == 2, r.stderr
    assert "usage: codex_config/install.sh" in r.stderr
    assert codex_home_state(env) == before and not env["log"].exists()


def test_never_passes_allow_dirty(env):
    code = [ln for ln in (CODEX_CONFIG / "install.sh").read_text().splitlines() if not ln.lstrip().startswith("#")]
    assert not [ln for ln in code if "--allow-dirty" in ln]


def test_python_below_3_11_or_missing_is_a_clear_error(env, tmp_path):
    fake = write(tmp_path / "py", "#!/bin/sh\nexit 1\n", 0o755)
    r = run(env, "--dry-run", extra={"STACK_PYTHON": str(fake)})
    assert r.returncode == 1 and "Python >= 3.11" in r.stderr
    r = run(env, "--dry-run", extra={"STACK_PYTHON": "/nonexistent/python"})
    assert r.returncode == 1 and "Python >= 3.11" in r.stderr


def test_dirty_repository_stops_at_the_snapshot(env):
    with open(env["repo"] / "codex_config" / "models.toml", "a") as f:
        f.write("# edited, not committed\n")
    before = codex_home_state(env)
    r = run(env, "--dry-run")
    assert r.returncode == 1 and "uncommitted changes" in r.stderr and "Nothing was changed" in r.stderr
    assert codex_home_state(env) == before and not env["log"].exists()


def test_refused_codex_homes_exit_2(env, tmp_path):
    home = env["home"]
    (home / ".claude").mkdir()
    for args, extra in ((["--codex-home", str(home)], None), (["--codex-home", str(home / ".claude")], None),
                        (["--codex-home", str(env["repo"] / "codex_config")], None),
                        (["--codex-home", str(tmp_path / "missing")], None), ([], {"CODEX_HOME": "/"}),
                        (["--codex-home", "/etc"], None)):
        r = run(env, "--dry-run", *args, extra=extra)
        assert r.returncode == 2, (args, r.stderr)
        assert "Nothing was changed" in r.stderr, (args, r.stderr)
    assert not env["log"].exists()


# ---- requirements, doctor, restore ---------------------------------------------------------------
def test_print_requirements_writes_only_the_build_dir_and_prints_root_steps(env):
    r = run(env, "--print-requirements")
    assert r.returncode == 0, r.stderr
    build = env["repo"] / "codex_config" / "build"
    assert (build / "requirements.toml").is_file() and (build / "managed-hooks" / "codex-hook").is_file()
    steps = [ln.strip() for ln in r.stdout.splitlines() if ln.strip().startswith("sudo ")]
    assert any("/usr/bin/python3 -I -c" in s and "CHECKED_HASH" in s for s in steps)
    assert any(s.endswith("/etc/codex/requirements.toml") for s in steps) or "NEVER replaced" in r.stdout
    assert not env["log"].exists() and codex_home_state(env) == []


def test_doctor_passes_the_paths_and_the_exit_status(env):
    r = run(env, "--doctor")
    assert r.returncode == 1 and "doctor stub" in r.stdout
    assert argv_of(env) == ["--codex-home", str(env["codex_home"]), "--home", str(env["home"])]


def test_restore_without_a_backup_refuses(env):
    r = run(env, "--restore", "--yes")
    assert r.returncode == 1 and "no install backup" in r.stderr
    r = run(env, "--restore", "--dry-run")
    assert r.returncode == 1 and "no install backup" in r.stderr


# ---- the argv handed to render ---------------------------------------------------------------------
def test_render_gets_the_mapped_flags(env):
    r = run(env, "--dry-run", "--profile-name", "mine", "--skills-root", "none", "--no-agents-md", "--no-mcp",
            "--legacy-sandbox", "--git-allow-rules", "--no-escalation", "--with-rollout-budget",
            "--ide-default", "--no-astra-profile", "--force")
    assert r.returncode == 1 and "render failed" in r.stderr and "Nothing was changed" in r.stderr
    a = argv_of(env)
    for flag in ("--no-agents-md", "--no-mcp", "--legacy-sandbox", "--git-allow-rules", "--no-escalation",
                 "--with-rollout-budget", "--ide-default", "--no-astra-profile", "--force"):
        assert flag in a, flag
    assert "--no-ide-default" not in a and "--with-wandb" not in a
    assert a[a.index("--profile-name") + 1] == "mine" and a[a.index("--skills-root") + 1] == "none"
    assert a[a.index("--codex-home") + 1] == str(env["codex_home"]) and a[a.index("--home") + 1] == str(env["home"])
    assert a[a.index("--codex") + 1] == str(FAKE_CODEX_DIR / "codex")
    src = a[a.index("--src") + 1]
    assert a[a.index("--stage") + 1] != src and "/src" in src          # the snapshot, never the repository
    assert str(env["repo"]) not in src
    assert codex_home_state(env) == []


def test_render_defaults_and_no_ide_default(env):
    run(env, "--dry-run", "--no-ide-default")
    a = argv_of(env)
    assert "--no-ide-default" in a and "--ide-default" not in a and "--skills-root" not in a
    assert a[a.index("--profile-name") + 1] == "codex"


def test_without_codex_render_gets_none(env):
    run(env, "--dry-run", path="/usr/bin:/bin")
    a = argv_of(env)
    assert a[a.index("--codex") + 1] == "none"


def test_old_codex_stops_before_render(env):
    r = run(env, "--dry-run", extra={"FAKE_CODEX_VERSION": "0.159.9"})
    assert r.returncode == 1 and "older than 0.160.1" in r.stderr
    assert not env["log"].exists()
    r = run(env, "--dry-run", extra={"FAKE_CODEX_VERSION": "0.160.1"})
    assert env["log"].exists()


@pytest.mark.parametrize("line,expected", [
    ("WANDB_API_KEY=sekrit-123", True), ("export WANDB_API_KEY='sekrit-123'", True),
    ('  WANDB_API_KEY="sekrit-123"  # mine', True), ("WANDB_API_KEY=", False), ('WANDB_API_KEY=""', False),
    ("# WANDB_API_KEY=sekrit-123", False), ("OTHER_WANDB_API_KEY=sekrit-123", False)])
def test_wandb_is_a_presence_check_and_never_printed(env, line, expected):
    write(env["codex_home"] / "stack.env", line + "\n", 0o600)
    r = run(env, "--dry-run")
    assert ("--with-wandb" in argv_of(env)) is expected
    assert "sekrit-123" not in r.stdout + r.stderr + env["log"].read_text()


# ---- codex_diff ------------------------------------------------------------------------------------
def test_codex_diff_reports_by_area(tmp_path):
    live, stage = tmp_path / "live", tmp_path / "stage"
    write(live / "codex.config.toml", "model = 'old'\n")
    write(stage / "codex.config.toml", "model = 'new'\n")
    write(live / "stack/agents/gone.toml", "x = 1\n")
    write(stage / "stack/agents/new.toml", "x = 2\n")
    write(stage / "stack/policy/guard.json", '{"a": 1}\n')
    os.symlink("/somewhere/python3.13", (live / "stack/bin").mkdir(parents=True) or live / "stack/bin/stack-python")
    write(live / "rules/claude-agent-stack.rules", "same\n")
    write(stage / "rules/claude-agent-stack.rules", "same\n")
    write(tmp_path / "links.json", json.dumps({"root": "/r", "links": {"a": "/t/a", "b": "/t/b"}}))
    write(live / ".stack-manifest.json", json.dumps({"links": {"links": {"b": "/old/b", "c": "/t/c"}}}))
    out = "\n".join(dg.report(str(live), str(stage), str(tmp_path / "links.json")))
    assert "profiles:\n    ~ codex.config.toml" in out and "-model = 'old'" in out and "+model = 'new'" in out
    assert "rules: no changes" in out and "AGENTS.md block: no changes" in out
    assert "- stack/agents/gone.toml" in out and "+ stack/agents/new.toml" in out
    assert "+ stack/policy/guard.json" in out
    assert "stack-python" not in out                  # made after the apply, not part of the render
    assert "1 added, 1 removed, 1 retargeted" in out and "+ a" in out and "- c" in out and "~ b" in out


def test_codex_diff_regions_and_agents_block(tmp_path):
    reg = load_lib("config_region")
    cmb = load_lib("claude_md_block", REPO / "lib" / "claude_md_block.py")
    live, stage = tmp_path / "live", tmp_path / "stage"
    user = b"[projects.x]\ntrust = 1\n"
    write(live / "config.toml", user.decode())
    (stage / "config.toml").parent.mkdir(parents=True)
    (stage / "config.toml").write_bytes(reg.splice(user, 'model = "m"\n', "[features]\nhooks = true\n"))
    out = "\n".join(dg.report(str(live), str(stage)))
    assert "+ region A (new" in out and "+ region B (new" in out
    # unchanged regions with a different user part: no difference reported
    (live / "config.toml").write_bytes(reg.splice(user, 'model = "m"\n', "[features]\nhooks = true\n"))
    (stage / "config.toml").write_bytes(reg.splice(user + b"[extra]\n", 'model = "m"\n', "[features]\nhooks = true\n"))
    assert "config.toml regions: no changes" in "\n".join(dg.report(str(live), str(stage)))
    # a changed region body
    (stage / "config.toml").write_bytes(reg.splice(user, 'model = "n"\n', "[features]\nhooks = true\n"))
    out = "\n".join(dg.report(str(live), str(stage)))
    assert "~ region A" in out and "region B" not in out
    write(live / "AGENTS.md", "mine\n")
    (stage / "AGENTS.md").write_bytes(cmb.splice(b"mine\n", cmb.render_block("block v1\n")))
    assert "AGENTS.md block:\n    + stack block" in "\n".join(dg.report(str(live), str(stage)))
    (live / "AGENTS.md").write_bytes(cmb.splice(b"other\n", cmb.render_block("block v1\n")))
    assert "AGENTS.md block: no changes" in "\n".join(dg.report(str(live), str(stage)))


def test_codex_diff_never_reads_through_a_symlink(tmp_path):
    live, stage = tmp_path / "live", tmp_path / "stage"
    secret = write(tmp_path / "secret.txt", "TOPSECRET\n")
    live.mkdir()
    os.symlink(secret, live / "rules_link")
    (live / "rules").mkdir()
    os.symlink(secret, live / "rules" / "claude-agent-stack.rules")
    write(stage / "rules/claude-agent-stack.rules", "new\n")
    (live / "stack" / "policy").mkdir(parents=True)
    os.symlink(secret, live / "stack" / "policy" / "guard.json")      # inside a directory area, whose diffs print
    write(stage / "stack/policy/guard.json", "{}\n")
    out = "\n".join(dg.report(str(live), str(stage)))
    assert "TOPSECRET" not in out and "symlink" in out


def test_codex_diff_cli_is_read_only(tmp_path):
    live, stage = tmp_path / "live", tmp_path / "stage"
    write(live / "codex.config.toml", "a\n")
    write(stage / "codex.config.toml", "b\n")
    before = sorted(str(p) for p in tmp_path.rglob("*"))
    r = subprocess.run([sys.executable, str(CODEX_CONFIG / "lib" / "codex_diff.py"), str(live), str(stage)],
                       capture_output=True, text=True)
    assert r.returncode == 0 and "~ codex.config.toml" in r.stdout
    assert sorted(str(p) for p in tmp_path.rglob("*")) == before
    assert subprocess.run([sys.executable, str(CODEX_CONFIG / "lib" / "codex_diff.py")],
                          capture_output=True, text=True).returncode == 1
