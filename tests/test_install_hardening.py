"""Installer hardening (B8, 2026-10-04): the security audit's findings at 90398f3 and the code
review's defects, each proven end to end on a scratch install (fresh HOME, fake `claude`, the
real install.sh in a subprocess) or on doctor.sh run as /stack-doctor runs it.

Threat model (audit): a prompt-injected sandboxed agent can write the stack repo checkout and any
project directory; the user runs ./install.sh and /stack-doctor outside the sandbox."""
import glob
import importlib.util
import json
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
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


def _git(repo, *args, check=True):
    """git in a scratch repo, as an agent would run it there (hooks off, no signing, no prompt)."""
    return subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-c", "user.name=t",
                           "-c", "user.email=t@example.invalid", "-C", repo, *args], stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=check)


def _marker_script(path, marker):
    """An executable that leaves `marker` behind when anything runs it (fsmonitor, a filter driver)."""
    Path(path).write_text("#!/bin/sh\necho \"$0 $*\" >>%s\ncat >/dev/null 2>&1\nexit 1\n" % shlex.quote(str(marker)))
    os.chmod(path, 0o755)


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
    # install_state.py loads stack_io.py by file path: the repo's dot-claude/hooks (agent-writable,
    # ignored *.pyc there never shown) is never put on sys.path, where it would shadow later imports
    p = subprocess.run([shutil.which("python3"), "-I", "-B", "-c",
                        "import importlib.util, sys; s = importlib.util.spec_from_file_location('install_state', sys.argv[1]); "
                        "m = importlib.util.module_from_spec(s); s.loader.exec_module(m); "
                        "print(m.load_json is not None, [p for p in sys.path if 'dot-claude' in p])",
                        os.path.join(repo, "lib", "install_state.py")], capture_output=True, text=True, cwd=str(tmp_path))
    assert p.stdout.strip() == "True []", (p.stdout, p.stderr[-800:])


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


# ---------------------------------------------------------------- MEDIUM: sandbox cache variables
@needs_git
def test_install_drops_the_sandbox_cache_variables(tmp_path):
    """install.sh run from a sandboxed shell drops every exported variable naming
    ~/.cache/claude-sandbox before any tool starts: the uv it runs sees none of them."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    real_uv = shutil.which("uv")
    if not real_uv:
        pytest.skip("needs uv")
    wrap = tmp_path / "wrap"
    wrap.mkdir()
    log = tmp_path / "uv-env.log"
    (wrap / "uv").write_text('#!/bin/sh\necho "UV_CACHE_DIR=${UV_CACHE_DIR-unset} CARGO_HOME=${CARGO_HOME-unset}" '
                             '>>"%s"\nexec "%s" "$@"\n' % (log, real_uv))
    (wrap / "uv").chmod(0o755)
    sb = home / ".cache" / "claude-sandbox"
    path = os.pathsep.join((str(wrap), os.path.join(repo, "tests", "fake-claude"), str(home / "shim"),
                            os.environ.get("PATH", "")))
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--dry-run",
                            env_extra={"PATH": path, "UV_CACHE_DIR": str(sb / "uv"), "CARGO_HOME": str(sb / "cargo")})
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert "ignoring the sandbox cache variables of this shell: UV_CACHE_DIR CARGO_HOME" in out.stderr or \
        "ignoring the sandbox cache variables of this shell: CARGO_HOME UV_CACHE_DIR" in out.stderr, out.stderr[-800:]
    seen = log.read_text()
    assert seen and "claude-sandbox" not in seen, seen


# ---------------------------------------------------------------- MEDIUM: CWE-494 unpinned scripts
def test_every_shipped_pep723_script_has_a_dependency_cutoff():
    """The stack's own PEP 723 scripts (MCP servers holding API keys, the model refit, the SDK helper)
    resolve their dependency ranges as of a fixed date: `[tool.uv] exclude-newer` in the header, which
    `uv run --script` (the agents' mcpServers, the prefetch, the refit) honours."""
    import re
    found = {}
    for sub in ("mcp", "hooks", "bin"):
        for p in sorted(Path(ROOT, "dot-claude", sub).glob("*.py")):
            m = re.search(r"(?m)^# /// script\n((?:#.*\n)*?)# ///$", p.read_text(encoding="utf-8"))
            if m and re.search(r'dependencies = \[\s*"', m.group(1)):
                found[p.name] = re.search(r'(?m)^# exclude-newer = "\d{4}-\d\d-\d\dT00:00:00Z"$', m.group(1)) is not None
    assert {"image_studio_mcp.py", "libdocs_mcp.py", "neural_memory_mcp.py"} <= set(found)
    assert [n for n, ok in found.items() if not ok] == []


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


# ================================================================ security re-check (2026-10-04)
# Same threat model, the checkout's .git included: an agent can write the index, .git/config,
# .git/info/{exclude,attributes} and any ignored file. Each test below fails on b8-land-2 (4286278).
PY3 = shutil.which("python3")


def _plant_pyc(repo, marker):
    """Two payloads in the repo's dot-claude/hooks that git status never shows: a sourceless
    json.pyc for the python3 on PATH (`*.py[cod]` is ignored; it runs when the guard starts
    without -I, its dir then sys.path[0]) and a stack_io/ package (hidden by .git/info/exclude; a
    package dir beats stack_io.py, which the guard imports after putting its own dir first on
    sys.path, so it runs even under -I)."""
    hooks = Path(repo, "dot-claude", "hooks")
    src = hooks / "payload_src.py"
    _marker_module(src, marker)
    subprocess.run([PY3, "-c", "import py_compile, sys; py_compile.compile(sys.argv[1], cfile=sys.argv[2], doraise=True)",
                    str(src), str(hooks / "json.pyc")], check=True)
    src.unlink()
    (hooks / "stack_io").mkdir()
    _marker_module(hooks / "stack_io" / "__init__.py", marker)
    with open(os.path.join(repo, ".git", "info", "exclude"), "a") as f:
        f.write("dot-claude/hooks/stack_io/\n")


# ---------------------------------------------------------------- 1. CRITICAL CWE-427: the lint step
@needs_git
def test_lint_agents_never_imports_bytecode_planted_in_repo_hooks(tmp_path):
    """tests/lint_agents.py run as the installer ran it (isolated python3, no arguments) used to run
    the repo's agent_guard.py, which puts its own dir first on sys.path: an ignored json.pyc there
    ran as the user. It now refuses that dir instead of importing from it."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    mark = tmp_path / "pwned"
    _plant_pyc(repo, mark)
    assert _git(repo, "status", "--porcelain").stdout == ""          # the review shows nothing
    p = subprocess.run([PY3, "-I", "-B", os.path.join(repo, "tests", "lint_agents.py")], cwd=str(tmp_path),
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    assert not mark.exists(), "lint_agents.py ran bytecode planted (ignored) in dot-claude/hooks"
    assert p.returncode == 1 and "json.pyc" in p.stderr, p.stderr[-800:]


def _lint_block():
    """install.sh's step-7 lint block, verbatim (the `if [ "$NO_DEPS" = 0 ] && [ "$DRY_RUN" = 0 ]` one)."""
    text = Path(ROOT, "install.sh").read_text()
    m = re.search(r'(?ms)^if \[ "\$NO_DEPS" = 0 \] && \[ "\$DRY_RUN" = 0 \]; then\n(?:(?!^fi$).)*?lint_agents\.py.*?^fi$', text)
    assert m, "the lint block moved"
    return m.group(0)


@needs_git
def test_install_lint_step_runs_nothing_from_the_repo_hooks(tmp_path):
    """The step-7 block, run as install.sh runs it, takes the policy from the STAGED guard ($S/hooks,
    private) and passes it with --policy-json: the json.pyc planted in the repo's dot-claude/hooks
    never runs, even with the same interpreter, and the lint passes."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    mark = tmp_path / "pwned"
    _plant_pyc(repo, mark)
    stage, work = tmp_path / "stage", tmp_path / "work"
    work.mkdir()
    shutil.copytree(os.path.join(ROOT, "dot-claude", "hooks"), stage / "hooks",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    script = "\n".join([
        "set -euo pipefail",
        "note(){ printf '  %s\\n' \"$*\"; }",
        'PY_ISOLATE="-I -B -X pycache_prefix=/dev/null/claude-agent-stack-no-bytecode"',
        'python3(){ command python3 $PY_ISOLATE "$@"; }',
        "NO_DEPS=0 DRY_RUN=0 RUN_PY=%s HERE=%s S=%s WORK=%s" % tuple(map(shlex.quote, (PY3, repo, str(stage), str(work)))),
        _lint_block(), ""])
    p = subprocess.run(["/bin/bash", "-c", script], cwd=str(work), capture_output=True, text=True, timeout=180,
                       stdin=subprocess.DEVNULL)
    assert not mark.exists(), "the lint step ran bytecode planted in the repo's dot-claude/hooks"
    assert "lint: tests/lint_agents.py ok" in p.stdout, (p.stdout[-1500:], p.stderr[-800:])


# ---------------------------------------------------------------- 3a. HIGH CWE-345: the main-branch rule
@needs_git
@pytest.mark.parametrize("plant", ["fsmonitor", "filter"])
def test_main_branch_rule_never_runs_a_program_the_repo_config_names(tmp_path, plant):
    """Run from another branch, the main-branch rule runs `git status`, `switch` and `merge`: a
    core.fsmonitor program never runs (off for every call); a clean/smudge filter driver (with
    `* filter=x` in .git/info/attributes) stops the run before git could start it."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    _git(repo, "switch", "-q", "-c", "feat")
    mark = tmp_path / "pwned"
    _marker_script(tmp_path / "prog.sh", mark)
    if plant == "fsmonitor":
        _git(repo, "config", "core.fsmonitor", str(tmp_path / "prog.sh"))
    else:
        _git(repo, "config", "filter.x.clean", str(tmp_path / "prog.sh"))
        _git(repo, "config", "filter.x.smudge", str(tmp_path / "prog.sh"))
        Path(repo, ".git", "info", "attributes").write_text("* filter=x\n")

    def stat_dirty():                                         # status re-hashes it: the clean filter runs
        p = os.path.join(repo, "install.sh")
        t = os.stat(p).st_mtime + 7
        os.utime(p, (t, t))
    stat_dirty()
    _git(repo, "status", "--porcelain", check=False)
    assert mark.exists(), "git status did not run %s: the probe proves nothing" % plant
    mark.unlink()
    stat_dirty()                                              # the probe refreshed the index
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert not mark.exists(), (mark.read_text(), out.stdout[-1500:], out.stderr[-1500:])
    if plant == "filter":
        assert out.returncode == 1 and "filter.x.clean" in out.stderr, out.stderr[-1500:]


# ---------------------------------------------------------------- 2. HIGH CWE-829: ignored files shipped
@needs_git
def test_install_never_ships_a_plugin_hooks_file_a_gitignore_hides(tmp_path):
    """A self-ignoring .gitignore (`*`) hides stack-plugins/plugins/lean-lsp/hooks/hooks.json from
    every git listing; `cp -R stack-plugins` installed it anyway (Claude Code loads it as plugin hooks)."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    hooks = Path(repo, "dot-claude", "stack-plugins", "plugins", "lean-lsp", "hooks")
    hooks.mkdir()
    (hooks / ".gitignore").write_text("*\n")
    (hooks / "hooks.json").write_text(json.dumps({"hooks": {"SessionStart": [{"hooks": [
        {"type": "command", "command": "echo PLANTED-9b2c"}]}]}}))
    assert _git(repo, "status", "--porcelain", "--untracked-files=all").stdout == ""
    out = _tis._run_install(repo, str(home), str(home / ".claude"),
                            argv=["--no-mcp", "--no-deps", "--no-profile", "--yes"])
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert (home / ".claude" / "stack-plugins" / "plugins" / "lean-lsp").is_dir()     # plugins were installed
    assert _grep_tree(str(home / ".claude"), b"PLANTED-9b2c") == []


@needs_git
@pytest.mark.parametrize("hide", ["info/exclude", "status.showUntrackedFiles=no", "core.excludesFile"])
def test_install_never_ships_an_agent_the_repo_hides(tmp_path, hide):
    """An agent file kept out of `git status` (.git/info/exclude, status.showUntrackedFiles=no, or a
    core.excludesFile set in .git/config) was installed by the agents/*.md glob. Only files HEAD
    tracks ship now; an untracked one that is not ignored is listed as not installed."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    agents = Path(repo, "dot-claude", "agents")
    text = (agents / "browser-operator.md").read_text().replace("name: browser-operator", "name: zz-hidden", 1)
    (agents / "zz-hidden.md").write_text(text)
    if hide == "info/exclude":
        with open(os.path.join(repo, ".git", "info", "exclude"), "a") as f:
            f.write("dot-claude/agents/zz-hidden.md\n")
    elif hide == "core.excludesFile":
        Path(tmp_path, "ignore").write_text("zz-hidden.md\n")
        _git(repo, "config", "core.excludesFile", str(tmp_path / "ignore"))
    else:
        _git(repo, "config", "status.showUntrackedFiles", "no")
    assert "zz-hidden" not in _git(repo, "status", "--porcelain").stdout
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert not (home / ".claude" / "agents" / "zz-hidden.md").exists()
    if hide != "info/exclude":          # your global excludes file and status.* never hide a file from the review
        assert "?? dot-claude/agents/zz-hidden.md  (untracked: not installed)" in out.stdout, out.stdout[-2000:]


@needs_git
def test_install_copies_only_the_skill_files_head_tracks(tmp_path):
    """An ignored file planted in a skill (notes.log: `*.log` is ignored, so the supply review never
    shows it) is not copied; an untracked, unignored one is listed as not installed and not copied
    either (re-check 2026-10-04: only files HEAD tracks ship); a committed new file and an edit of a
    tracked one are."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    sk = Path(repo, "dot-claude", "skills", "web-research")
    (sk / "committed.md").write_text("a committed note\n")
    _git(repo, "add", "dot-claude/skills/web-research/committed.md")
    _git(repo, "commit", "-q", "-m", "note")
    (sk / "notes.log").write_text("SECRET-7f3a9c\n")
    (sk / "extra.md").write_text("an untracked note\n")
    with open(sk / "SKILL.md", "a") as f:
        f.write("\nEDITED-4d1e\n")
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert "?? dot-claude/skills/web-research/extra.md  (untracked: not installed)" in out.stdout
    assert " M dot-claude/skills/web-research/SKILL.md" in out.stdout
    skill = home / ".claude" / "skills" / "web-research"
    assert b"EDITED-4d1e" in (skill / "SKILL.md").read_bytes() and (skill / "committed.md").is_file()
    assert not (skill / "extra.md").exists()
    assert not (skill / "notes.log").exists() and _grep_tree(str(home / ".claude"), b"SECRET-7f3a9c") == []


# ---------------------------------------------------------------- 3. HIGH CWE-345: a blind review
@needs_git
@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_install_refuses_an_index_flag_that_hides_an_edit(tmp_path, flag):
    """git status never shows an edit of a file the index marks assume-unchanged or skip-worktree:
    the run stops, naming the file and how to clear the mark; nothing is installed."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    rel = "dot-claude/skills/web-research/SKILL.md"
    _git(repo, "update-index", flag, rel)
    with open(os.path.join(repo, rel), "a") as f:
        f.write("\nINJECTED-7f3a9c\n")
    assert _git(repo, "status", "--porcelain").stdout == ""
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 1, (out.stdout[-1500:], out.stderr[-1500:])
    assert rel in out.stderr and "update-index --no-assume-unchanged --no-skip-worktree" in out.stderr, out.stderr[-1500:]
    assert _grep_tree(str(home / ".claude"), b"INJECTED-7f3a9c") == []


@needs_git
def test_install_review_compares_bytes_not_the_stat_cache(tmp_path):
    """core.checkStat=minimal and core.trustctime=false in .git/config, an edit of the same size and
    the old mtime put back: git status trusts its stat cache and shows nothing. The review hashes
    the bytes against HEAD, so the edit is listed and --no-prompt stops."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    rel = "dot-claude/agents/browser-operator.md"
    p = Path(repo, rel)
    st = p.stat()
    time.sleep(1.1)                                          # the index is now newer than the file: not racy
    _git(repo, "update-index", "--refresh")
    _git(repo, "config", "core.checkStat", "minimal")
    _git(repo, "config", "core.trustctime", "false")
    data = p.read_bytes()
    p.write_bytes(data[:-12] + b"INJECTED-7f3")              # same size
    os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert _git(repo, "status", "--porcelain").stdout == ""
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--no-prompt")
    log = out.stdout + out.stderr
    assert " M " + rel in log and out.returncode == 1 and "--no-prompt forbids asking" in log, log[-2000:]


@needs_git
def test_install_never_runs_the_repo_core_fsmonitor(tmp_path):
    """core.fsmonitor in .git/config names a program git status runs: the review (on main, even under
    --dry-run) never starts it."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    mark = tmp_path / "pwned"
    _marker_script(tmp_path / "fsmonitor.sh", mark)
    _git(repo, "config", "core.fsmonitor", str(tmp_path / "fsmonitor.sh"))
    _git(repo, "status", "--porcelain")
    assert mark.exists(), "git status did not run the fsmonitor hook: the probe proves nothing"
    mark.unlink()
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--dry-run")
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert not mark.exists(), mark.read_text()


@needs_git
@pytest.mark.parametrize("how", ["tree rewritten in place", "fsck.skipList"])
def test_install_refuses_an_object_store_rewritten_in_place(tmp_path, how):
    """Delta re-check HIGH (CWE-345): git never re-hashes an object it reads. An agent writes a
    malicious skill file, its blob, and rewrites the parent tree object in place (HEAD unchanged):
    ls-tree, status and prev..HEAD then all agree with the tampered working tree, so the byte review
    sees nothing. git fsck catches the hash mismatch and the run stops; fsck.* keys in the repo's own
    config (which could tell fsck to skip that object) are refused outright."""
    import zlib
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    rel = "dot-claude/skills/web-research/SKILL.md"
    if how == "fsck.skipList":
        Path(tmp_path, "skip").write_text("")
        _git(repo, "config", "fsck.skipList", str(tmp_path / "skip"))
    else:
        tree = _git(repo, "rev-parse", "HEAD:dot-claude/skills/web-research").stdout.strip()
        with open(os.path.join(repo, rel), "a") as f:
            f.write("\nINJECTED-7f3a9c\n")
        blob = _git(repo, "hash-object", "-w", rel).stdout.strip()
        listing = _git(repo, "ls-tree", tree).stdout.replace(
            _git(repo, "rev-parse", "HEAD:" + rel).stdout.strip(), blob)
        new = subprocess.run(["git", "-C", repo, "mktree"], input=listing, capture_output=True, text=True,
                             check=True).stdout.strip()
        raw = subprocess.run(["git", "-C", repo, "cat-file", "tree", new], capture_output=True, check=True).stdout
        obj = os.path.join(repo, ".git", "objects", tree[:2], tree[2:])
        os.chmod(obj, 0o644)
        Path(obj).write_bytes(zlib.compress(b"tree %d\0" % len(raw) + raw))
        assert blob in _git(repo, "ls-tree", "-r", "HEAD").stdout             # HEAD's tree now names the new blob
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 1, (out.stdout[-1500:], out.stderr[-1500:])
    assert ("git fsck finds a damaged or altered object" if how != "fsck.skipList" else "fsck.skiplist") \
        in out.stderr, out.stderr[-1500:]
    assert _grep_tree(str(home / ".claude"), b"INJECTED-7f3a9c") == []


def test_every_python_git_call_in_install_sh_turns_hooks_and_replace_refs_off():
    """Each git argv install.sh's python steps build (["git", ...]) turns hooks off and ignores replace
    refs (refs/replace, agent-writable, would let another object stand in for the one named)."""
    calls = re.findall(r'\["git", [^\]]*\]', Path(ROOT, "install.sh").read_text())
    assert len(calls) >= 2, calls
    bad = [c for c in calls if '"core.hooksPath=/dev/null"' not in c or '"--no-replace-objects"' not in c]
    assert bad == [], bad


# ---------------------------------------------------------------- 4. MEDIUM CWE-367: check, then copy
@needs_git
def test_skill_copy_reads_only_the_bytes_the_review_saw(tmp_path):
    """An agent swaps a skill file for a link to a secret the moment staging starts (after the
    review and the symlink check). The installer copies from its private snapshot, read once
    before the review: the secret never reaches the config dir."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    secret = _secret_tree(tmp_path)
    skills = sorted(d for d in os.listdir(os.path.join(repo, "dot-claude", "skills"))
                    if os.path.isdir(os.path.join(repo, "dot-claude", "skills", d)))
    target = Path(repo, "dot-claude", "skills", "typography", "references", "web-fonts.md")
    assert target.is_file()
    pat = str(home / ".local" / "state" / "claude-agent-stack-backups" / ".work.*" / "stage" / "skills" / skills[0])
    swapped, stop = [], threading.Event()

    def attacker():                     # a concurrently running agent, with perfect timing
        while not stop.is_set():
            if glob.glob(pat):
                tmp = target.with_name("web-fonts.md.lnk")
                os.symlink(str(secret), str(tmp))
                os.replace(str(tmp), str(target))
                swapped.append(time.time())
                return
            time.sleep(0.0005)

    t = threading.Thread(target=attacker)
    t.start()
    try:
        out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    finally:
        stop.set()
        t.join()
    assert swapped, "the attacker never saw the staged skills"
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    assert _grep_tree(str(home / ".claude"), b"SECRET-7f3a9c") == []
    assert (home / ".claude" / "skills" / "typography" / "references" / "web-fonts.md").is_file()


@needs_git
def test_snapshot_refuses_a_link_on_a_directory_component(tmp_path):
    """A skill's references/ dir swapped for a link to a dir of the agent's choosing: the run stops
    (the link sweep; the snapshot's per-component O_NOFOLLOW covers a swap after the sweep)."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    refs = Path(repo, "dot-claude", "skills", "typography", "references")
    elsewhere = tmp_path / "elsewhere"
    shutil.copytree(refs, elsewhere)
    (elsewhere / "web-fonts.md").write_text("SECRET-7f3a9c\n")
    shutil.rmtree(refs)
    os.symlink(str(elsewhere), str(refs))
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 1 and "is a symlink; the stack ships none" in out.stderr, out.stderr[-1500:]
    assert _grep_tree(str(home / ".claude"), b"SECRET-7f3a9c") == []


@needs_git
@pytest.mark.parametrize("link", ["tests/derive_thresholds.py", "requirements"])
def test_snapshot_follows_no_link_on_any_component(tmp_path, link):
    """Outside dot-claude/ (no sweep there) the snapshot's O_NOFOLLOW open, component by component,
    refuses a tracked file or a directory on its path that is now a link."""
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    p = Path(repo, link)
    moved = tmp_path / "moved"
    shutil.move(str(p), str(moved))
    os.symlink(str(moved), str(p))
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--yes")
    assert out.returncode == 1 and "nothing in" in out.stderr and link + "/" * (link == "requirements") in out.stderr, \
        out.stderr[-1500:]
    assert not (home / ".claude" / "agents").exists()


# ---------------------------------------------------------------- 6. CWE-377: an agent-writable TMPDIR
@needs_git
def test_install_moves_a_sandbox_tmpdir_to_its_private_work_dir(tmp_path):
    """Run from a Claude Code shell, TMPDIR is the sandbox's /tmp/claude-<uid>, which agents write:
    the run's here-document files (bash 4+), mktemp files and tools' temp files go to $WORK/tmp
    instead. The scratch install's TMPDIR lies under the sandbox's when this suite runs sandboxed."""
    if not os.path.realpath(str(tmp_path)).startswith(("/private/tmp/claude", "/tmp/claude")):
        pytest.skip("needs a TMPDIR under /tmp/claude* (a sandboxed run)")
    repo = _tis._scratch_repo(str(tmp_path / "repo"))
    home = tmp_path / "home"
    home.mkdir()
    real_uv = shutil.which("uv")
    if not real_uv:
        pytest.skip("needs uv")
    wrap = tmp_path / "wrap"
    wrap.mkdir()
    log = tmp_path / "uv-env.log"
    (wrap / "uv").write_text('#!/bin/sh\necho "TMPDIR=${TMPDIR-unset}" >>"%s"\nexec "%s" "$@"\n' % (log, real_uv))
    (wrap / "uv").chmod(0o755)
    path = os.pathsep.join((str(wrap), os.path.join(repo, "tests", "fake-claude"), str(home / "shim"),
                            os.environ.get("PATH", "")))
    out = _tis._run_install(repo, str(home), str(home / ".claude"), "--dry-run", env_extra={"PATH": path})
    assert out.returncode == 0, (out.stdout[-1500:], out.stderr[-1500:])
    seen = set(log.read_text().split())
    work = os.path.join(str(home), ".local", "state", "claude-agent-stack-backups", ".work.")
    assert seen and all(s.startswith("TMPDIR=" + work) and s.endswith("/tmp") for s in seen), seen


# ---------------------------------------------------------------- 5. stack-update-tools: gone
def test_stack_update_tools_is_not_shipped():
    """The audit's MEDIUM on bin/stack-update-tools is moot: the script is deleted and nothing names it."""
    assert not os.path.exists(os.path.join(ROOT, "dot-claude", "bin", "stack-update-tools"))
    assert "stack-update-tools" not in Path(ROOT, "install.sh").read_text()
