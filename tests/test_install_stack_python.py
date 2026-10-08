"""install.sh and the hooks' interpreter (Python migration S2): bin/stack-python, the smoke test
before settings.json changes, timestamp bytecode, the launcher hook commands.

Run: uv run --no-project --python 3.13 --with-requirements requirements/tools.txt pytest -q tests/test_install_stack_python.py
Each install runs from a scratch copy of the working tree into a scratch HOME and config dir (the
helpers of tests/test_install_state.py). The interpreter is a logging shim in front of uv's managed
3.13 (given as STACK_PYTHON), so every call the installer makes through stack-python is recorded with
the state of the config dir's settings.json at that moment: the ordering proof.
"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_install_state import ROOT, _run_install, _scratch_repo  # noqa: E402

sys.path.insert(0, os.path.join(ROOT, "lib"))
import install_state as st  # noqa: E402

needs_git = pytest.mark.skipif(not os.path.exists(os.path.join(ROOT, ".git")), reason="needs the stack's git checkout")
SETTINGS = os.path.join(ROOT, "dot-config", "dot-claude", "settings.json")
BLACKCAT = os.path.join(ROOT, "dot-config", "dot-claude", "agents", "blackcat.md")
LAUNCH = '/bin/sh "__CLAUDE_DIR__/bin/stack-hook" '


def real313():
    uv = shutil.which("uv")
    p = subprocess.run([uv, "python", "find", "--system", "--managed-python", "--no-project", "--no-config",
                        "3.13"], capture_output=True, text=True, check=False) if uv else None
    if not p or p.returncode or not p.stdout.strip():
        pytest.skip("needs uv's managed Python 3.13")
    return p.stdout.strip()


def shim(tmp_path, conf):
    """A python3.13 that logs `<settings state>\\t<argv>` per call and runs the real 3.13; while the
    file `fail` exists, the hook stub (the smoke test) exits 1 instead."""
    d = tmp_path / "py" / "bin"
    d.mkdir(parents=True)
    log, fail = tmp_path / "py.log", tmp_path / "fail"
    p = d / "python3.13"
    p.write_text("""#!/bin/sh
s=none
[ -f '{conf}/settings.json' ] && s=old
grep -q 'bin/stack-hook' '{conf}/settings.json' 2>/dev/null && s=new
printf '%s\\t%s\\n' "$s" "$*" >> '{log}'
case "$*" in *stack_hook.py*) [ -f '{fail}' ] && exit 1 ;; esac
exec '{real}' "$@"
""".format(conf=conf, log=log, fail=fail, real=real313()))
    p.chmod(0o755)
    return str(p), log, fail


def calls(log):
    return [ln.split("\t", 1) for ln in log.read_text().splitlines()] if log.exists() else []


@pytest.fixture
def scratch(tmp_path):
    home = str(tmp_path / "home")
    os.makedirs(home)
    return _scratch_repo(str(tmp_path / "repo")), home, os.path.join(home, ".claude")


# ---------------------------------------------------------------- templates
def hook_cmds():
    s = json.load(open(SETTINGS, encoding="utf-8"))
    return [(ev, g.get("matcher"), x["command"]) for ev, gs in s["hooks"].items() for g in gs for x in g["hooks"]]


def test_hook_commands_use_the_launcher_and_fail_closed_only_on_guard_pretooluse():
    py_hooks = [(ev, m, c) for ev, m, c in hook_cmds() if re.search(r"agent_guard|stack_usage|read_gate|web_caps", c)]
    assert len(py_hooks) >= 22
    for ev, m, c in py_hooks:
        assert c.startswith(LAUNCH), c
        mod = c[len(LAUNCH):].replace("--fail-closed ", "").split()[0]
        assert mod in ("agent_guard", "stack_usage", "read_gate", "web_caps"), c
        closed = " --fail-closed " in " %s " % c[len(LAUNCH) - 1:]
        # exit 2 blocks the tool on PreToolUse; on Stop, UserPromptSubmit, PermissionRequest ... it
        # has side effects: only the guard's PreToolUse entries fail closed (read_gate, web_caps open)
        assert closed == (ev == "PreToolUse" and mod == "agent_guard"), (ev, m, c)
    assert not [c for _, _, c in hook_cmds() if "__PYTHON3__" in c and ".py" in c and "/hooks/" in c]
    fm = open(BLACKCAT, encoding="utf-8").read().split("\n---", 1)[0]
    assert 'command: "/bin/sh \\"__CLAUDE_DIR__/bin/stack-hook\\" --fail-closed agent_guard blackcat-guard"' in fm


def test_stack_hook_re_matches_new_and_old_commands():
    src = open(os.path.join(ROOT, "install.sh"), encoding="utf-8").read()
    rx = re.compile(re.search(r'^STACK_HOOK_RE = re\.compile\(r"([^"]+)"\)$', src, re.M).group(1))
    old = ['"/usr/bin/python3" "/u/.claude/hooks/agent_guard.py" no-push',
           '"/opt/homebrew/bin/python3" "/u/.claude/hooks/read_gate.py"',
           '"/usr/bin/python3" "/u/.claude/hooks/stack_usage.py" end']
    new = ['/bin/sh "/u/.claude/bin/stack-hook" --fail-closed agent_guard budget',
           '/bin/sh "/u/.claude/bin/stack-hook" web_caps']
    assert all(rx.search(json.dumps({"type": "command", "command": c})) for c in old + new)
    assert not rx.search(json.dumps({"command": '/bin/sh "/u/bin/stack-hooks-mine"'}))


def test_excluded_covers_bytecode_and_the_link():
    for rel in ("hooks/__pycache__/agent_guard.cpython-313.pyc", "bin/__pycache__/x.pyc",
                "mcp/__pycache__/y.pyc", "bin/stack-python"):
        assert st.excluded(rel) and not st.in_scope(rel), rel
    assert not st.excluded("bin/stack-hook") and not st.excluded("hooks/stack_hook.py")


def test_excluded_paths_are_never_planned(tmp_path):
    c, s = tmp_path / "c", tmp_path / "s"
    for d in (c, s):
        (d / "hooks").mkdir(parents=True)
        (d / "hooks" / "agent_guard.py").write_text("x\n")
    (c / "hooks" / "__pycache__").mkdir()
    (c / "hooks" / "__pycache__" / "agent_guard.cpython-313.pyc").write_bytes(b"\0" * 16)
    (c / "bin").mkdir()
    (c / "bin" / "stack-python").symlink_to("/nonexistent/python3.13")
    st.stage(str(c), str(s / "x"))
    assert not (s / "x" / "bin" / "stack-python").exists() and not (s / "x" / "hooks" / "__pycache__").exists()
    plan = st.make_plan(str(c), str(s), str(tmp_path / "r.json"))
    assert not plan["removed"] and not plan["added"], plan


# ---------------------------------------------------------------- installer runs
@needs_git
def test_dry_run_prints_stack_python_and_smoke_before_settings(scratch, tmp_path):
    repo, home, conf = scratch
    py, log, _ = shim(tmp_path, conf)
    p = _run_install(repo, home, conf, "--dry-run", env_extra={"STACK_PYTHON": py})
    out = p.stdout + p.stderr
    assert p.returncode == 0, out[-3000:]
    i_link = out.index("Hook interpreter: %s/bin/stack-python" % conf)
    i_smoke = out.index("smoke test passed on %s" % py)
    i_settings = out.index("7/11 Merge settings.json")
    assert i_link < i_smoke < i_settings
    assert "would: ln -sfn %s %s/bin/stack-python" % (py, conf) in out
    assert not os.path.lexists(os.path.join(conf, "bin", "stack-python"))


@needs_git
def test_dry_run_creates_nothing(scratch, tmp_path):
    """--dry-run writes nothing outside its own working dir (removed at exit): no config dir, no
    stack-python, no state, backup or cache dir under XDG_STATE_HOME (here HOME/.local/state)."""
    repo, home, conf = scratch
    py, _, _ = shim(tmp_path, conf)
    p = _run_install(repo, home, conf, "--dry-run", env_extra={"STACK_PYTHON": py})
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    left = sorted(os.path.relpath(os.path.join(d, x), home) for d, ds, fs in os.walk(home) for x in ds + fs)
    # the stack's paths only: the test helper's scratch dirs (tmp, shim) are its own, and brew's
    # ~/Library/Caches/Homebrew comes from lib/devtools.sh's report (not checked here)
    ours = [x for x in left if x.startswith((".local", ".claude", ".cache"))]
    assert ours == [], " ".join(x for x in ours if x.count("/") < 3)


@needs_git
def test_dry_run_without_313_says_what_it_would_do(scratch, tmp_path):
    repo, home, conf = scratch
    empty = tmp_path / "no-pythons"
    empty.mkdir()
    p = _run_install(repo, home, conf, "--dry-run", env_extra={"UV_PYTHON_INSTALL_DIR": str(empty)})
    out = p.stdout + p.stderr
    assert p.returncode == 0, out[-3000:]
    assert out.index("no uv-managed Python 3.13") < out.index("would: smoke-test the staged hooks") \
        < out.index("7/11 Merge settings.json")


@needs_git
def test_no_313_stops_before_settings(scratch, tmp_path):
    repo, home, conf = scratch
    empty = tmp_path / "no-pythons"
    empty.mkdir()
    p = _run_install(repo, home, conf, env_extra={"UV_PYTHON_INSTALL_DIR": str(empty)})
    out = p.stdout + p.stderr
    assert p.returncode == 1 and "no Python 3.13 for the hooks" in out and "uv python install 3.13" in out, out[-2000:]
    assert "7/11" not in out and not os.path.exists(os.path.join(conf, "settings.json"))


@needs_git
def test_old_interpreter_in_stack_python_env_refused(scratch, tmp_path):
    repo, home, conf = scratch
    old = shutil.which("python3.12") or (real313().replace("3.13", "3.12") if os.path.exists(
        real313().replace("3.13", "3.12")) else None)
    if not old or not os.path.exists(old):
        pytest.skip("no Python 3.12 to play the old interpreter")
    p = _run_install(repo, home, conf, env_extra={"STACK_PYTHON": old})
    assert p.returncode == 1 and "not a working Python >= 3.13" in p.stdout + p.stderr
    assert not os.path.exists(os.path.join(conf, "settings.json"))


@needs_git
def test_install_links_and_smoke_tests_before_settings_then_compiles(scratch, tmp_path):
    repo, home, conf = scratch
    py, log, _ = shim(tmp_path, conf)
    p = _run_install(repo, home, conf, env_extra={"STACK_PYTHON": py})
    out = p.stdout + p.stderr
    assert p.returncode == 0, out[-3000:]
    link = os.path.join(conf, "bin", "stack-python")
    assert os.readlink(link) == py
    rows = calls(log)
    smoke = [i for i, (s, a) in enumerate(rows) if "stack_hook.py --fail-closed agent_guard" in a]
    comp = [i for i, (s, a) in enumerate(rows) if "-m compileall" in a]
    assert len(smoke) == 2 and len(comp) == 1, rows
    # the smoke test (budget Read, then no-push) ran on the staged stub before any settings.json existed
    assert all(rows[i][0] == "none" for i in smoke), rows
    assert "agent_guard budget" in rows[smoke[0]][1] and "agent_guard no-push" in rows[smoke[1]][1]
    assert all(re.search(r"/stage/(bin/\.\./)?hooks/stack_hook\.py ", rows[i][1]) for i in smoke), rows
    # compiled after the settings with the launcher commands were applied, by stack-python, timestamp
    s_c, a_c = rows[comp[0]]
    assert smoke[-1] < comp[0] and s_c == "new", rows
    assert "--invalidation-mode timestamp" in a_c and " -f " in " %s " % a_c
    for m in ("agent_guard", "stack_usage", "stack_limits", "stack_bayes_grid", "stack_report", "stack_fanout",
              "stack_fanout_wire", "read_gate", "web_caps", "stack_hook"):
        assert "%s/hooks/%s.py" % (conf, m) in a_c, m
        pyc = os.path.join(conf, "hooks", "__pycache__", "%s.cpython-313.pyc" % m)
        flags = int.from_bytes(open(pyc, "rb").read()[4:8], "little")
        assert flags == 0, (m, flags)                       # 0: timestamp-checked (not a hash pyc)
    # the installed stack_limits.py finds its grid tier beside it (_grid_mod loads it by path from there)
    grid = ("import sys; sys.path.insert(0, sys.argv[1]); import stack_limits as L; m = L._grid_mod(); "
            "print(m.__file__ if m else 'missing')")
    r = subprocess.run([sys.executable, "-B", "-c", grid, os.path.join(conf, "hooks")], capture_output=True, text=True,
                       env=dict(os.environ, XDG_STATE_HOME=str(tmp_path / "xdg-grid")), timeout=60)
    assert r.stdout.strip() == os.path.join(conf, "hooks", "stack_bayes_grid.py"), (r.stdout, r.stderr)
    # the installed hooks run through the launcher on the link
    s = json.load(open(os.path.join(conf, "settings.json")))
    cmd = [x["command"] for g in s["hooks"]["PreToolUse"] for x in g["hooks"] if x["command"].endswith(" no-push")][0]
    assert cmd == '/bin/sh "%s/bin/stack-hook" --fail-closed agent_guard no-push' % conf
    assert s["statusLine"]["command"].startswith('"%s"' % link)
    ev = {"session_id": "s1", "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/",
          "tool_use_id": "t", "tool_input": {"command": "git push origin main"}}
    env = {k: v for k, v in os.environ.items() if not k.startswith(("STACK_", "PYTHON"))}
    env.update(HOME=home, CLAUDE_CONFIG_DIR=conf, XDG_STATE_HOME=str(tmp_path / "xdg"), STACK_USAGE_COLLECT="0")
    r = subprocess.run(["/bin/sh", "-c", cmd], input=json.dumps(ev), capture_output=True, text=True, env=env)
    assert r.returncode == 0 and json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
    # the doctor: stack-python, launcher smoke test, fresh bytecode, and its probes find the launcher commands
    # without uv on PATH: the doctor's image-model check (a network lookup) is skipped
    path = [p for p in env["PATH"].split(os.pathsep) if p and not os.path.exists(os.path.join(p, "uv"))]
    env.update(TMPDIR=str(tmp_path), PATH=os.pathsep.join([os.path.join(repo, "tests", "fake-claude")] + path))
    d = subprocess.run(["bash", os.path.join(conf, "bin", "doctor.sh")], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL, timeout=600).stdout
    for want in ("ok    bin/stack-python -> %s (Python 3.13." % py,
                 "ok    bin/stack-hook and hooks/stack_hook.py",
                 "ok    hook launcher smoke test: a Read through stack-hook --fail-closed agent_guard budget is allowed",
                 "ok    hook bytecode fresh (timestamp pycs, cpython-313)",
                 'ok    token budgets wired: PreToolUse "*" runs agent_guard.py budget',
                 "ok    settings.json PreToolUse(Bash) no-push enforces the policy",
                 "ok    blackcat.md blackcat-guard enforces the policy",
                 "ok    guard hooks wired for all 10 events",
                 "ok    sandboxed Bash env: session-env SessionStart hook wired"):
        assert want in d, (want, d[-4000:])
    assert "no agent_guard hook command found" not in d and "did not deny" not in d, d[-4000:]
    # source newer than its pyc, in a cache dir nobody can rewrite (the doctor's own hook probes would
    # otherwise heal it before the check): reported stale
    os.utime(os.path.join(conf, "hooks", "agent_guard.py"))
    cache = os.path.join(conf, "hooks", "__pycache__")
    os.chmod(cache, 0o555)
    try:
        d = subprocess.run(["bash", os.path.join(conf, "bin", "doctor.sh")], capture_output=True, text=True, env=env,
                           stdin=subprocess.DEVNULL, timeout=600).stdout
    finally:
        os.chmod(cache, 0o755)
    assert "WARN  hook bytecode missing or stale for agent_guard (cpython-313)" in d, d[-3000:]


@needs_git
def test_failed_smoke_keeps_the_previous_install(scratch, tmp_path):
    """An install from before S2 (direct `<python> .../agent_guard.py` commands): a re-run whose smoke
    test fails changes nothing (settings.json byte-identical, the earlier stack-python link back);
    once it passes, the old commands are replaced, none kept as the user's or duplicated."""
    repo, home, conf = scratch
    py, log, fail = shim(tmp_path, conf)
    p = _run_install(repo, home, conf, env_extra={"STACK_PYTHON": py})
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    sp = os.path.join(conf, "settings.json")
    s = json.load(open(sp))
    n_cmds = sum(len(g["hooks"]) for gs in s["hooks"].values() for g in gs)
    for gs in s["hooks"].values():                     # rewrite them the way an earlier install did
        for g in gs:
            for x in g["hooks"]:
                m = re.fullmatch(r'/bin/sh "([^"]+)/bin/stack-hook" (?:--fail-closed )?(\w+)(.*)', x["command"])
                if m:
                    x["command"] = '"/usr/bin/python3" "%s/hooks/%s.py"%s' % (m.group(1), m.group(2), m.group(3))
    json.dump(s, open(sp, "w"), indent=2)
    before = open(sp, "rb").read()
    link = os.path.join(conf, "bin", "stack-python")
    os.unlink(link)
    os.symlink("/earlier/python3.13", link)
    fail.write_text("1")
    p = _run_install(repo, home, conf, env_extra={"STACK_PYTHON": py})
    out = p.stdout + p.stderr
    assert p.returncode == 1 and "hook smoke test failed" in out and "uv python install 3.13" in out, out[-3000:]
    assert "7/11" not in out
    assert open(sp, "rb").read() == before and os.readlink(link) == "/earlier/python3.13"
    fail.unlink()
    p = _run_install(repo, home, conf, env_extra={"STACK_PYTHON": py})
    assert p.returncode == 0, (p.stdout + p.stderr)[-3000:]
    s = json.load(open(sp))
    cmds = [x["command"] for gs in s["hooks"].values() for g in gs for x in g["hooks"]]
    assert len(cmds) == n_cmds and not [c for c in cmds if "/usr/bin/python3" in c], cmds
    assert os.readlink(link) == py
