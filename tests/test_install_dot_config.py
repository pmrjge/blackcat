"""install.sh after the dot-config/ move (2026-10-07): dot-claude/, codex_config/ and equilibrium/ live
under dot-config/ as dot-claude, dot-codex_config and dot-equilibrium.

- `./install.sh --codex [ARGS]` is the Codex installer's only entry point: taken before anything
  Claude-side, the flag stripped, every other argument passed on as given, STACK_CODEX_VIA_TOP=1 set.
- An install whose manifest records a commit from before the move still reads that commit's shipped
  settings.json (at dot-claude/settings.json) and reviews prev..HEAD over the old path too, with each
  moved file paired to its new path."""
import importlib.util
import json
import os
import shutil
import subprocess

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INSTALL = os.path.join(ROOT, "install.sh")
CODEX_INSTALL = os.path.join(ROOT, "dot-config", "dot-codex_config", "install.sh")
BASH = shutil.which("bash", path="/bin:/usr/bin") or "/bin/bash"   # macOS: bash 3.2, the oldest supported

needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")

FAKE_CODEX = """#!/bin/sh
printf 'via=%s\\n' "${STACK_CODEX_VIA_TOP-unset}"
printf 'uv=%s\\n' "${UV_CACHE_DIR-unset}"
printf 'argc=%d\\n' "$#"
for a in "$@"; do printf 'arg=[%s]\\n' "$a"; done
"""


def _env(tmp_path, **extra):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {"PATH": "/usr/bin:/bin", "HOME": str(home), "CLAUDE_CONFIG_DIR": str(home / ".claude"),
           "TMPDIR": str(tmp_path)}
    env.update(extra)
    return env, home


def _top_with_fake_codex(tmp_path):
    """A copy of install.sh beside a fake dot-config/dot-codex_config/install.sh that prints what it got."""
    top = tmp_path / "top"
    (top / "dot-config" / "dot-codex_config").mkdir(parents=True)
    shutil.copy2(INSTALL, top / "install.sh")
    (top / "dot-config" / "dot-codex_config" / "install.sh").write_text(FAKE_CODEX)
    return top


def _run(argv, env, cwd=None):
    return subprocess.run(argv, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60,
                          check=False, cwd=cwd)


def _got(out):
    lines = out.stdout.splitlines()
    return (next(x for x in lines if x.startswith("via="))[4:], next(x for x in lines if x.startswith("uv="))[3:],
            [x[5:-1] for x in lines if x.startswith("arg=[")])


# ---------------------------------------------------------------- --codex: the only Codex entry point
@pytest.mark.parametrize("args, want", [
    (["--codex"], []),
    (["--dry-run", "--codex", "a b", "", "--help"], ["--dry-run", "a b", "", "--help"]),
    (["--codex", "--codex", "--yes"], ["--yes"]),
    (["--with-ml", "--codex", "--config-dir", "x"], ["--with-ml", "--config-dir", "x"]),
])
def test_codex_flag_anywhere_execs_the_codex_installer_with_the_rest(tmp_path, args, want):
    """--codex anywhere: stripped, the rest passed on unchanged and in order (an empty argument and one
    with a space included; none at all under bash 3.2's set -u), STACK_CODEX_VIA_TOP=1 exported. Claude
    options are not checked here: the Codex installer rejects what it doesn't know."""
    top = _top_with_fake_codex(tmp_path)
    env, home = _env(tmp_path)
    out = _run([BASH, str(top / "install.sh"), *args], env)
    assert out.returncode == 0, (out.stdout, out.stderr)
    via, _uv, got = _got(out)
    assert (via, got) == ("1", want), out.stdout
    assert out.stderr == "" and not any(home.iterdir())


def test_codex_is_taken_before_the_macos_check_and_through_a_link(tmp_path):
    """Nothing Claude-side runs first: on a system the Claude installer refuses (uname is not Darwin,
    no STACK_ALLOW_NON_MACOS) --codex still reaches the Codex installer, found beside the real script
    when install.sh is started through a symlink elsewhere."""
    top = _top_with_fake_codex(tmp_path)
    fake = tmp_path / "fakebin"
    fake.mkdir()
    (fake / "uname").write_text("#!/bin/sh\necho Linux\n")
    (fake / "uname").chmod(0o755)
    link = tmp_path / "elsewhere" / "inst"
    link.parent.mkdir()
    os.symlink(top / "install.sh", link)
    env, home = _env(tmp_path, PATH="%s:/usr/bin:/bin" % fake)
    ctl = _run([BASH, str(link), "--dry-run"], env)
    assert ctl.returncode == 1 and "installs on macOS only (this is Linux)" in ctl.stdout, (ctl.stdout, ctl.stderr)
    out = _run([BASH, str(link), "--codex", "--dry-run"], env)
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert _got(out)[0::2] == ("1", ["--dry-run"]) and "macOS" not in out.stdout + out.stderr
    assert not any(home.iterdir())


def test_codex_path_drops_the_sandbox_cache_variables_first(tmp_path):
    """The one step before the dispatch: a variable naming ~/.cache/claude-sandbox (agent-writable,
    CWE-427) never reaches the Codex installer, which runs uv."""
    top = _top_with_fake_codex(tmp_path)
    env, home = _env(tmp_path)
    env["UV_CACHE_DIR"] = str(home / ".cache" / "claude-sandbox" / "uv")
    out = _run([BASH, str(top / "install.sh"), "--codex"], env)
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert _got(out)[1] == "unset"
    assert "ignoring the sandbox cache variables of this shell: UV_CACHE_DIR" in out.stderr


def test_codex_missing_installer_is_a_usage_error(tmp_path):
    top = _top_with_fake_codex(tmp_path)
    os.unlink(top / "dot-config" / "dot-codex_config" / "install.sh")
    env, home = _env(tmp_path)
    out = _run([BASH, str(top / "install.sh"), "--codex"], env)
    assert out.returncode == 2 and "dot-config/dot-codex_config/install.sh is missing" in out.stderr, out.stderr
    assert not any(home.iterdir())


def test_codex_help_is_the_codex_installers_and_the_top_help_names_it(tmp_path):
    """`./install.sh --codex --help` prints the Codex installer's options (the real one), writes
    nothing; `./install.sh --help` documents --codex and where its arguments go."""
    env, home = _env(tmp_path)
    out = _run([INSTALL, "--codex", "--help"], env)
    assert out.returncode == 0, (out.stdout, out.stderr)
    assert "--codex-home PATH" in out.stdout and "--skills-root" in out.stdout, out.stdout
    assert "--with-eq-container" not in out.stdout                     # not the Claude installer's help
    assert not any(home.iterdir())
    top = _run([INSTALL, "--help"], env)
    assert top.returncode == 0
    assert "./install.sh --codex [ARGS]" in top.stdout and "./install.sh --codex --help" in top.stdout
    assert "every other argument goes to the Codex installer" in " ".join(
        x.lstrip("#").strip() for x in top.stdout.splitlines())


# The inner script's own refusal is group B2's change (dot-config/dot-codex_config/install.sh); until it
# lands here this test skips. Integrator: once B2 is in, drop the skipif.
@pytest.mark.skipif("STACK_CODEX_VIA_TOP" not in open(CODEX_INSTALL, encoding="utf-8").read(),
                    reason="dot-config/dot-codex_config/install.sh does not check STACK_CODEX_VIA_TOP yet "
                           "(group B2's change): integrator, remove this skipif after merging B2")
def test_codex_installer_run_directly_names_the_entry_point(tmp_path):
    env, home = _env(tmp_path)
    out = _run([BASH, CODEX_INSTALL, "--help"], env)
    assert out.returncode == 2, (out.returncode, out.stdout, out.stderr)
    assert "use ./install.sh --codex" in out.stderr, out.stderr
    assert not any(home.iterdir())
    ok = _run([BASH, CODEX_INSTALL, "--help"], dict(env, STACK_CODEX_VIA_TOP="1"))
    assert ok.returncode == 0 and "--codex-home" in ok.stdout, (ok.stdout, ok.stderr)


# ---------------------------------------------------------------- a manifest commit from before the move
def _tis():
    spec = importlib.util.spec_from_file_location("_tis", os.path.join(HERE, "test_install_state.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(repo, *args, env=None, inp=None):
    p = subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
                        "-c", "user.email=t@example.invalid", "-C", repo, *args],
                       env=dict(os.environ, **(env or {})), input=inp, capture_output=True, text=True, check=True)
    return p.stdout.strip()


def _pre_move_commit(repo, tmp_path, settings_text):
    """A commit (off every branch, as the smoke test's N-SUPPLY one) with the pre-move layout: the
    shipped tree at dot-claude/ instead of dot-config/dot-claude/, its settings.json = settings_text."""
    idx = {"GIT_INDEX_FILE": str(tmp_path / "pre-move.idx")}
    _git(repo, "read-tree", "HEAD", env=idx)
    _git(repo, "rm", "--cached", "-r", "-q", "dot-config/dot-claude", env=idx)
    _git(repo, "read-tree", "--prefix=dot-claude/", "HEAD:dot-config/dot-claude", env=idx)
    blob = _git(repo, "hash-object", "-w", "--stdin", inp=settings_text)
    _git(repo, "update-index", "--cacheinfo", "100644,%s,dot-claude/settings.json" % blob, env=idx)
    tree = _git(repo, "write-tree", env=idx)
    return _git(repo, "commit-tree", tree, "-p", "HEAD", "-m", "pre-move layout")


@needs_git
def test_pre_move_manifest_commit_settings_and_supply_review_use_the_old_path(tmp_path):
    """The first install after the move, over one whose manifest (older than settings_permission_scalars)
    records a pre-move commit that shipped defaultMode bypassPermissions: the shipped mode still comes
    from <commit>:dot-claude/settings.json (else: "can't tell", and the old default would stay), and the
    supply review over <commit>..HEAD covers dot-claude/ too, -M pairing each moved file with its new
    path, so only the real edit counts (1 line), not the whole tree as new."""
    tis = _tis()
    repo = tis._scratch_repo(str(tmp_path / "repo"))
    shipped_text = open(os.path.join(repo, "dot-config", "dot-claude", "settings.json"), encoding="utf-8").read()
    shipped_mode = json.loads(shipped_text)["permissions"]["defaultMode"]
    assert shipped_mode != "bypassPermissions" and shipped_text.count('"defaultMode": "%s"' % shipped_mode) == 1
    pre = _pre_move_commit(repo, tmp_path, shipped_text.replace('"defaultMode": "%s"' % shipped_mode,
                                                                '"defaultMode": "bypassPermissions"'))
    with pytest.raises(subprocess.CalledProcessError):
        _git(repo, "cat-file", "-e", pre + ":dot-config/dot-claude")
    home = str(tmp_path / "home")
    os.makedirs(home)
    conf = os.path.join(home, ".claude")
    tis._install(repo, home, conf)
    mp = os.path.join(conf, ".stack-manifest.json")
    m = json.load(open(mp))
    m["commit"] = pre
    for k in ("settings_permission_scalars", "settings_permission_scalars_commit"):
        m.pop(k, None)
    json.dump(m, open(mp, "w"), indent=2)
    sp = os.path.join(conf, "settings.json")
    s = json.load(open(sp))
    s["permissions"]["defaultMode"] = "bypassPermissions"           # what that install left in place
    json.dump(s, open(sp, "w"), indent=2)

    out = tis._run_install(repo, home, conf, "--yes")
    log = out.stdout + out.stderr
    assert out.returncode == 0, (out.stdout[-3000:], out.stderr[-3000:])
    assert json.load(open(sp))["permissions"]["defaultMode"] == shipped_mode, log[-3000:]
    assert ('set permissions.defaultMode="%s" (was "bypassPermissions", the stack\'s earlier default)'
            % shipped_mode) in log, log[-3000:]
    assert "can't tell the stack's earlier default" not in log
    assert "changes to the stack's shipped files and installer since the last install (%s" % pre[:12] in log
    assert "{dot-claude => dot-config/dot-claude}/" in log, log[-3000:]
    assert " 1 insertion(+), 1 deletion(-)" in log, log[-3000:]
    assert ("diff -M %s HEAD -- dot-config/dot-claude install.sh lib requirements tests/lint_agents.py "
            "tests/derive_sched_model.py tests/derive_thresholds.py dot-claude\n" % pre[:12]) in log, log[-3000:]
