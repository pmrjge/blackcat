"""Installer hardening (B8, 2026-10-04): the security audit's findings at 90398f3 and the code
review's defects, each proven end to end on a scratch install (fresh HOME, fake `claude`, the
real install.sh in a subprocess) or on doctor.sh run as /stack-doctor runs it.

Threat model (audit): a prompt-injected sandboxed agent can write the stack repo checkout and any
project directory; the user runs ./install.sh and /stack-doctor outside the sandbox."""
import importlib.util
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
_spec = importlib.util.spec_from_file_location("_tis", os.path.join(HERE, "test_install_state.py"))
_tis = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_tis)

needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")


def _marker_module(path, marker):
    """A module that, when imported, leaves `marker` behind (the planted payload)."""
    Path(path).write_text("open(%r, 'w').close()\n" % str(marker))


# ---------------------------------------------------------------- CRITICAL: CWE-427 planted modules
@needs_git
def test_install_never_imports_a_module_planted_in_the_repo_or_cwd(tmp_path):
    """lib/datetime.py (install_state.py's sys.path[0] before the fix), re.py in the repo root (the
    caller's cwd for `python3 -`/`-c`) and lib/__pycache__ bytecode for install_state (the render
    step's import) must never run, even under --dry-run, which runs every python step."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    marks = [tmp_path / ("pwned-%d" % i) for i in range(3)]
    _marker_module(os.path.join(repo, "lib", "datetime.py"), marks[0])
    _marker_module(os.path.join(repo, "re.py"), marks[1])
    _marker_module(os.path.join(repo, "json.py"), marks[2])
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--dry-run", cwd=repo)
    assert out.returncode == 0, (out.stdout[-2000:], out.stderr[-2000:])
    assert [m.name for m in marks if m.exists()] == [], out.stdout[-2000:]


@needs_git
def test_diff_never_imports_a_module_planted_in_lib(tmp_path):
    """--diff (lib/stack_diff.py) loads install_state.py by file path: a lib/datetime.py beside it
    never shadows the stdlib module install_state imports."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    mark = tmp_path / "pwned"
    _marker_module(os.path.join(repo, "lib", "datetime.py"), mark)
    out = _tis._run_install(repo, str(home), str(home / ".claude"), cwd=repo, argv=["--diff"])
    assert out.returncode == 0 and "stack diff (read-only)" in out.stdout, (out.stdout[-1500:], out.stderr[-1500:])
    assert not mark.exists()


@needs_git
def test_install_lists_a_new_file_in_lib_and_lint_agents_in_the_supply_review(tmp_path):
    """A module added to lib/ (not only the three files the old SUPPLY_PATHS named) and an edit of
    tests/lint_agents.py (run by step 7) are listed before the question."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    Path(repo, "lib", "helper_planted.py").write_text("X = 1\n")
    with open(os.path.join(repo, "tests", "lint_agents.py"), "a") as f:
        f.write("\n# planted edit\n")
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--no-prompt")
    log = out.stdout + out.stderr
    assert "lib/helper_planted.py" in log and "tests/lint_agents.py" in log, log[-3000:]
    assert out.returncode == 1 and "--no-prompt forbids asking" in log


# ---------------------------------------------------------------- HIGH: CWE-59 symlinks, ignored files
def _secret_tree(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("SECRET-7f3a9c\n")
    return secret


def _grep_tree(root, needle):
    hits = []
    for r, _ds, fs in os.walk(root):
        for n in fs:
            p = os.path.join(r, n)
            try:
                if needle in open(p, "rb").read():
                    hits.append(p)
            except OSError:
                pass
    return hits


@needs_git
@pytest.mark.parametrize("where", ["dot-claude/skills/web-research/notes.log", "dot-claude/agents/zz-link.md"])
def test_install_refuses_a_symlink_under_dot_claude(tmp_path, where):
    """A link planted in the repo (a name .gitignore hides from the review, or any untracked one)
    stops the install before anything is copied: the secret it points at never reaches the config
    dir, where agents could read it."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    os.symlink(str(_secret_tree(tmp_path)), os.path.join(repo, where))
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 1 and "is a symlink; the stack ships none" in out.stderr, (out.stdout[-1500:], out.stderr[-1500:])
    assert _grep_tree(str(home / ".claude"), b"SECRET-7f3a9c") == []


@needs_git
def test_install_copies_only_the_skill_files_git_lists(tmp_path):
    """An ignored file planted in a skill (notes.log: `*.log` is ignored, so the supply review never
    shows it) is not copied; an untracked, unignored one is (the review lists it)."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    Path(repo, "dot-claude", "skills", "web-research", "notes.log").write_text("SECRET-7f3a9c\n")
    Path(repo, "dot-claude", "skills", "web-research", "extra.md").write_text("an untracked note\n")
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    skill = home / ".claude" / "skills" / "web-research"
    assert (skill / "SKILL.md").is_file() and (skill / "extra.md").is_file()
    assert not (skill / "notes.log").exists() and _grep_tree(str(home / ".claude"), b"SECRET-7f3a9c") == []


def _doctor_copy(tmp_path, with_guard_section=False):
    c = tmp_path / "conf"
    (c / "bin").mkdir(parents=True)
    shutil.copy(os.path.join(ROOT, "dot-claude", "bin", "doctor.sh"), c / "bin" / "doctor.sh")
    if with_guard_section:          # the guard-probe section runs only when both exist
        (c / "settings.json").write_text(json.dumps({"hooks": {}}))
        (c / "hooks").mkdir()
        (c / "hooks" / "agent_guard.py").write_text("")
    return c


def test_doctor_never_imports_a_module_planted_in_the_session_cwd(tmp_path):
    """/stack-doctor runs doctor.sh as a hook in the session's directory, outside the sandbox: a
    json.py there (python's sys.path[0] for `python3 -`) must not run."""
    c = _doctor_copy(tmp_path)
    proj = tmp_path / "proj"
    proj.mkdir()
    mark = tmp_path / "pwned"
    for mod in ("json", "glob", "re", "sys_planted"):
        _marker_module(proj / ("%s.py" % mod), mark)
    p = subprocess.run(["/bin/bash", str(c / "bin" / "doctor.sh")], cwd=str(proj), capture_output=True,
                       text=True, timeout=300, stdin=subprocess.DEVNULL)
    assert "done." in p.stdout, p.stdout[-2000:]
    assert not mark.exists(), "doctor.sh imported a module planted in its working directory"


def test_doctor_leaves_no_temp_dir_behind(tmp_path):
    """The guard probes' scratch state dir (tempfile.mkdtemp) is removed when the check ends."""
    c = _doctor_copy(tmp_path, with_guard_section=True)
    tmp = tmp_path / "tmp"
    tmp.mkdir()
    env = dict(os.environ, TMPDIR=str(tmp))
    p = subprocess.run(["/bin/bash", str(c / "bin" / "doctor.sh")], capture_output=True, text=True,
                       timeout=300, env=env, stdin=subprocess.DEVNULL)
    assert "agent_guard hook command found" in p.stdout, p.stdout[-2000:]   # the section ran
    assert sorted(x.name for x in tmp.iterdir()) == []
