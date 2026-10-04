"""bin/stack-hook (sh launcher) and hooks/stack_hook.py (entry stub with cached bytecode).

Run: uv run --no-project --python 3.13 --with-requirements requirements/tools.txt pytest -q tests/test_stack_hook.py
Every test works on a copy of dot-claude/hooks and dot-claude/bin/stack-hook under tmp_path, with its
own XDG_STATE_HOME, HOME and CLAUDE_CONFIG_DIR; nothing in the repository or ~ is written.
STACK_HOOK_BENCH_N (default 20) sets the rounds of the timing test; `-s` shows its numbers.
"""
import ast
import json
import marshal
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS_SRC = ROOT / "dot-claude" / "hooks"
LAUNCHER_SRC = ROOT / "dot-claude" / "bin" / "stack-hook"
PY = sys.executable
TAG = sys.implementation.cache_tag            # cpython-313
SID = "s-parity0000a1"

pytestmark = pytest.mark.skipif(sys.version_info < (3, 13), reason="the hook floor is Python 3.13")


def uv_python(ver):
    uv = shutil.which("uv")
    if not uv:
        return None
    p = subprocess.run([uv, "python", "find", "--system", "--no-project", "--no-config", ver],
                       capture_output=True, text=True, check=False)
    return p.stdout.strip() if p.returncode == 0 and p.stdout.strip() else None


# ---------------------------------------------------------------- tree, env, runners
@pytest.fixture(scope="session")
def golden(tmp_path_factory):
    """hooks/ and bin/stack-hook copied once, every module precompiled (timestamp pyc), as S2 installs."""
    c = tmp_path_factory.mktemp("golden") / "C"
    shutil.copytree(HOOKS_SRC, c / "hooks", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (c / "bin").mkdir()
    shutil.copy2(LAUNCHER_SRC, c / "bin" / "stack-hook")
    env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
    subprocess.run([PY, "-m", "compileall", "-q", str(c / "hooks")], env=env, check=True)
    return c


class Tree:
    def __init__(self, c):
        self.c, self.hooks = c, c / "hooks"
        self.stub, self.launcher = self.hooks / "stack_hook.py", c / "bin" / "stack-hook"

    def src(self, mod):
        return self.hooks / (mod + ".py")

    def pyc(self, mod):
        return self.hooks / "__pycache__" / ("%s.%s.pyc" % (mod, TAG))

    def direct(self, mod, args=()):
        return [PY, str(self.src(mod)), *args]

    def via_stub(self, mod, args=(), closed=False):
        return [PY, str(self.stub), *(["--fail-closed"] if closed else []), mod, *args]

    def via_launcher(self, mod, args=(), closed=False, sh="/bin/sh"):
        return [*sh.split(), str(self.launcher), *(["--fail-closed"] if closed else []), mod, *args]


@pytest.fixture
def tree(golden, tmp_path):
    c = tmp_path / "C"
    shutil.copytree(golden, c, symlinks=True)       # copy2 keeps the mtimes: the pycs stay valid
    yield Tree(c)
    for d, dirs, _ in os.walk(c):                   # undo the permission tests' chmods for cleanup
        for x in dirs:
            os.chmod(os.path.join(d, x), 0o755)


def base_env(root):
    """A hook's environment: no stack knobs, its own state, home and config dirs, no bytecode writes
    (the hook env may carry PYTHONDONTWRITEBYTECODE=1)."""
    e = {k: v for k, v in os.environ.items()
         if not k.startswith(("STACK_", "BLACKCAT_", "SUPREME_", "SCREEN_", "CLAUDE_CODE_MAX", "PYTHON",
                              "STRIP_AGENT_MODEL", "UV_", "CLAUDE_ENV_FILE", "CLAUDE_CONFIG_DIR",
                              "VIRTUAL_ENV", "CONDA_"))}
    for d in ("xdg", "home", "cfg"):
        (root / d).mkdir(parents=True, exist_ok=True)
    (root / "stack.env").touch()
    e.update(XDG_STATE_HOME=str(root / "xdg"), HOME=str(root / "home"), CLAUDE_CONFIG_DIR=str(root / "cfg"),
             STACK_ENV_FILE=str(root / "stack.env"), CLAUDE_ENV_FILE=str(root / "envfile"),
             STACK_USAGE_COLLECT="0", PYTHONDONTWRITEBYTECODE="1", PATH="/usr/bin:/bin")
    return e


@pytest.fixture
def env(tmp_path):
    return base_env(tmp_path / "run")


def run(cmd, stdin="", env=None, **kw):
    data = stdin if isinstance(stdin, str) else json.dumps(stdin)
    p = subprocess.run(cmd, input=data, capture_output=True, text=True, env=env, timeout=60, check=False, **kw)
    return p.returncode, p.stdout, p.stderr


def decision(out):
    rc, stdout, _ = out
    if rc != 0 or not stdout.strip():
        return "allow" if rc == 0 else "rc%d" % rc
    return json.loads(stdout).get("hookSpecificOutput", {}).get("permissionDecision", "allow")


def pyc_loads(p):
    marshal.loads(Path(p).read_bytes()[16:])
    return True


PUSH = {"session_id": SID, "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": "/",
        "tool_use_id": "tu-p", "tool_input": {"command": "git push origin main"}}
READ = {"session_id": SID, "hook_event_name": "PreToolUse", "tool_name": "Read", "cwd": "/",
        "tool_use_id": "tu-r", "tool_input": {"file_path": "/etc/hosts"}}
BROKEN_PRE = '{"hook_event_name": "PreToolUse", "tool_name": "Agent", oops'


# ---------------------------------------------------------------- parity: stub and launcher vs direct
def session_events(root):
    """>= 15 hook calls of one session, in order: (module, args, fail_closed (a PreToolUse entry), stdin)."""
    proj, tr = root / "proj", root / "projects" / "p"
    (proj / "node_modules" / "pkg").mkdir(parents=True)
    (proj / "node_modules" / "pkg" / "index.js").write_text("x")
    (proj / "src").mkdir()
    (proj / "src" / "a.py").write_text("x = 1\n")
    (tr / SID / "subagents").mkdir(parents=True)
    main = tr / (SID + ".jsonl")
    lines = [{"type": "user", "message": {"content": "hi"}}]
    lines += [{"type": "assistant", "requestId": "r%d" % i, "message": {"id": "m%d" % i,
               "usage": {"input_tokens": 1000}}} for i in range(5)]
    main.write_text("".join(json.dumps(x) + "\n" for x in lines))
    (tr / SID / "subagents" / "agent-A1.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines[1:]))
    (tr / SID / "subagents" / "agent-A1.meta.json").write_text(json.dumps({"agentType": "coder"}))

    def ev(event, **kw):
        return dict({"session_id": SID, "hook_event_name": event, "transcript_path": str(main),
                     "cwd": str(proj)}, **kw)

    def pre(tool, ti, tu, **kw):
        return ev("PreToolUse", tool_name=tool, tool_input=ti, tool_use_id=tu, **kw)

    sub = {"agent_id": "A1", "agent_type": "coder"}
    coder = {"subagent_type": "coder", "prompt": "x", "description": "x"}
    return [
        ("agent_guard", [], False, ev("SessionStart", source="startup")),
        ("agent_guard", ["session-env"], False, ev("SessionStart", source="startup")),
        ("agent_guard", [], False, ev("UserPromptSubmit", prompt_id="p1", prompt="go")),
        ("agent_guard", [], True, pre("Agent", coder, "tu-a1", prompt_id="p1")),
        ("agent_guard", [], True, pre("Agent", dict(coder, subagent_type="general-purpose"), "tu-a2",
                                      prompt_id="p1")),
        ("agent_guard", [], True, pre("Agent", dict(coder, subagent_type="no-such-agent"), "tu-a3",
                                      prompt_id="p1")),
        ("agent_guard", [], False, ev("PostToolUse", tool_name="Agent", tool_use_id="tu-a1", tool_input=coder,
                                      tool_response={"agentId": "A1", "status": "async_launched"})),
        ("agent_guard", [], False, ev("SubagentStart", **sub)),
        ("agent_guard", ["budget"], True, pre("Read", {"file_path": str(proj / "src" / "a.py")}, "tu-r1", **sub)),
        ("agent_guard", ["no-push"], True, pre("Bash", {"command": "git push origin main"}, "tu-b1", **sub)),
        ("agent_guard", ["no-push"], True, pre("Bash", {"command": "git status"}, "tu-b2", **sub)),
        ("agent_guard", ["blackcat-guard", "--settings"], True, pre("Read", {"file_path": "/x"}, "tu-r2")),
        ("agent_guard", ["image-limit"], True, pre("mcp__image-studio__edit", {"prompt": "p"}, "tu-m1", **sub)),
        ("agent_guard", [], True, BROKEN_PRE),
        ("read_gate", [], False, pre("Read", {"file_path": str(proj / "node_modules/pkg/index.js")}, "tu-g1",
                                     **sub)),
        ("read_gate", [], False, pre("Read", {"file_path": str(proj / "node_modules/pkg/index.js")}, "tu-g2",
                                     **sub)),
        ("web_caps", [], False, pre("mcp__exa__web_search_exa", {"query": "q", "numResults": 100}, "tu-w1")),
        ("agent_guard", [], False, ev("SubagentStop", **sub)),
        ("stack_usage", ["start"], False, ev("SubagentStart", agent_id="A2", agent_type="coder")),
        ("stack_usage", ["end"], False, ev("SessionEnd", reason="exit")),
        ("agent_guard", ["--print-policy"], False, ""),
        ("agent_guard", ["no-such-mode"], False, ""),
        ("read_gate", ["--print"], False, ""),
        ("web_caps", ["--print"], False, ""),
    ]


STARTED = re.compile(r"Started \d{4}-\d\d-\d\d \d\d:\d\d \(local\)\.")


def scrub(res):
    """SubagentStart's `Started <local time>` line: runs seconds apart may straddle a minute."""
    rc, out, err = res
    return rc, STARTED.sub("Started <T> (local).", out), err


def run_session(tree, tmp_path, how):
    root = tmp_path / "session"              # the same paths for every runner: outputs must match exactly
    shutil.rmtree(root, ignore_errors=True)
    e = base_env(root)
    e["STACK_PYTHON"] = PY
    out = []
    for mod, args, closed, stdin in session_events(root):
        if how == "direct":
            cmd = tree.direct(mod, args)
        elif how == "stub":
            cmd = tree.via_stub(mod, args)
        else:                                 # as S2 wires it: --fail-closed on the PreToolUse entries
            cmd = tree.via_launcher(mod, args, closed=closed)
        out.append(((mod, args), scrub(run(cmd, stdin, e))))
    return out


def test_parity_stub_and_launcher_match_direct_script(tree, tmp_path):
    direct = run_session(tree, tmp_path, "direct")
    assert len(direct) >= 15
    # the events exercise real decisions, not no-ops
    d = {i: decision(direct[i][1]) for i in (3, 4, 5, 8, 9, 10, 13, 14, 15)}
    assert d[4] == d[5] == d[9] == d[13] == d[14] == "deny", d
    assert d[3] == d[8] == d[10] == d[15] == "allow", d
    assert direct[21][1][0] == 2 and "updatedInput" in direct[16][1][1], direct[16]
    assert "Started <T> (local)." in direct[7][1][1], direct[7]
    for how in ("stub", "launcher"):
        got = run_session(tree, tmp_path, how)
        for (call, want), (_, have) in zip(direct, got, strict=True):
            assert have == want, (how, call, want, have)


def test_parity_through_symlinked_config_dir(tree, env, tmp_path):
    """~/.claude may be a symlink: the stub keeps the invoked paths (__file__, argv[0]) as a direct run."""
    link = tmp_path / "link"
    link.symlink_to(tree.c)
    lt = Tree(link)
    e = dict(env, STACK_PYTHON=PY)
    for mod, args, stdin in (("agent_guard", ["no-push"], PUSH), ("agent_guard", [], BROKEN_PRE),
                             ("agent_guard", ["--print-policy"], ""), ("read_gate", ["--print"], "")):
        want = run(lt.direct(mod, args), stdin, e)
        assert run(lt.via_stub(mod, args), stdin, e) == want
        assert run(lt.via_launcher(mod, args, closed=True), stdin, e) == want


def test_cached_pyc_is_used_not_rewritten(tree, env):
    before = tree.pyc("agent_guard").stat().st_mtime_ns
    rc, out, err = run([PY, "-v", *tree.via_stub("agent_guard", ["no-push"])[1:]], PUSH, env)
    assert decision((rc, out, err)) == "deny"
    assert "code object from '%s'" % tree.pyc("agent_guard") in err      # loaded from the pyc, not compiled
    assert tree.pyc("agent_guard").stat().st_mtime_ns == before


# ---------------------------------------------------------------- bytecode failure modes
def test_pycache_prefix_env_ignored(tree, env, tmp_path):
    """PYTHONPYCACHEPREFIX in the hook's environment: bytecode still comes from (and goes to) the
    protected hooks/__pycache__, never the prefix dir (stack_hook.py sets sys.pycache_prefix = None)."""
    pfx = tmp_path / "pfx"
    rc, out, err = run([PY, "-v", *tree.via_stub("agent_guard", ["no-push"])[1:]], PUSH,
                       dict(env, PYTHONPYCACHEPREFIX=str(pfx)))
    assert decision((rc, out, err)) == "deny"
    assert "code object from '%s'" % tree.pyc("agent_guard") in err
    assert not pfx.exists() or not list(pfx.rglob("agent_guard*.pyc"))


def test_corrupt_pyc_body_falls_back_and_heals(tree, env):
    want = run(tree.direct("agent_guard", ["no-push"]), PUSH, env)
    b = bytearray(tree.pyc("agent_guard").read_bytes())
    b[20:60] = b"\x00" * 40                  # valid header, bad marshal data: import raises ValueError
    tree.pyc("agent_guard").write_bytes(bytes(b))
    assert run(tree.via_stub("agent_guard", ["no-push"]), PUSH, env) == want
    assert run(tree.via_stub("agent_guard", ["no-push"]), PUSH, env) == want
    assert pyc_loads(tree.pyc("agent_guard"))   # dropped by the fallback, rewritten by the next import


def test_truncated_pyc_recompiles(tree, env):
    want = run(tree.direct("agent_guard", ["no-push"]), PUSH, env)
    tree.pyc("agent_guard").write_bytes(b"garbage")
    assert run(tree.via_stub("agent_guard", ["no-push"]), PUSH, env) == want
    assert pyc_loads(tree.pyc("agent_guard"))


def test_stale_pyc_runs_new_code(tree, env):
    with open(tree.src("agent_guard"), "a") as f:    # size changes, so timestamp mode sees it at once
        f.write('\nBYPASS_HINT = "EDITED-SINCE-COMPILE"\n')
    rc, out, _ = run(tree.via_stub("agent_guard"), BROKEN_PRE, env)
    assert rc == 0 and json.loads(out)["systemMessage"].startswith("EDITED-SINCE-COMPILE")
    assert b"EDITED-SINCE-COMPILE" in tree.pyc("agent_guard").read_bytes()


@pytest.mark.parametrize("case", ["readonly-pycache", "unreadable-pycache", "readonly-hooks-no-pycache"])
def test_unwritable_or_unreadable_cache_still_works(tree, env, case):
    want = run(tree.direct("agent_guard", ["no-push"]), PUSH, env)
    cache = tree.hooks / "__pycache__"
    if case == "readonly-hooks-no-pycache":
        shutil.rmtree(cache)
        os.chmod(tree.hooks, 0o555)
    else:
        os.chmod(cache, 0o555 if case == "readonly-pycache" else 0o000)
    try:
        assert run(tree.via_stub("agent_guard", ["no-push"]), PUSH, env) == want
    finally:
        os.chmod(tree.hooks, 0o755)
        if cache.exists():
            os.chmod(cache, 0o755)


def test_concurrent_cold_start(tree, env):
    shutil.rmtree(tree.hooks / "__pycache__")
    want = run(tree.direct("agent_guard", ["no-push"]), PUSH, env)
    procs = [subprocess.Popen(tree.via_stub("agent_guard", ["no-push"]), stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
             for _ in range(8)]
    outs = [p.communicate(json.dumps(PUSH), timeout=60) for p in procs]
    assert [(p.returncode, o, e) for p, (o, e) in zip(procs, outs, strict=True)] == [want] * 8
    assert want[0] == 0 and decision(want) == "deny"
    assert pyc_loads(tree.pyc("agent_guard"))
    assert all(n.endswith(".pyc") for n in os.listdir(tree.hooks / "__pycache__"))   # no temp leftovers


# ---------------------------------------------------------------- stub: rejection and fail-closed
@pytest.mark.parametrize("name", ["../hooks/agent_guard", "agent_guard.py", "/abs/agent_guard", "hooks/read_gate",
                                  "os", "stack_hook", "stack_limits", "AGENT_GUARD", ""])
def test_unknown_module_rejected(tree, env, name):
    rc, out, err = run(tree.via_stub(name, ["no-push"]), PUSH, env)
    assert (rc, out) == (0, "") and "unknown hook module" in err
    rc, out, _ = run(tree.via_stub(name, ["no-push"], closed=True), PUSH, env)
    hso = json.loads(out)["hookSpecificOutput"]
    assert rc == 0 and hso["permissionDecision"] == "deny"
    assert hso["permissionDecisionReason"].startswith("stack guard error: unknown hook module")


@pytest.mark.parametrize("breakage", ["syntax", "missing"])
def test_import_failure_fails_closed_on_pretooluse_only(tree, env, breakage):
    if breakage == "syntax":
        with open(tree.src("agent_guard"), "a") as f:
            f.write("\ndef broken(:\n")
    else:
        tree.src("agent_guard").unlink()
    rc, out, err = run(tree.via_stub("agent_guard", ["no-push"], closed=True), PUSH, env)
    hso = json.loads(out)["hookSpecificOutput"]
    assert rc == 0 and hso["permissionDecision"] == "deny" and "failed to start" in hso["permissionDecisionReason"]
    stop = {"session_id": SID, "hook_event_name": "SubagentStop", "agent_id": "A1"}
    rc, out, err = run(tree.via_stub("agent_guard"), stop, env)               # other events: no flag
    assert (rc, out) == (0, "") and "stack_hook: hook agent_guard failed to start" in err
    rc, out, err = run(tree.via_stub("agent_guard", ["budget"], closed=True), READ,
                       dict(env, STACK_POLICY="off"))                         # the bypass still works
    assert (rc, out) == (0, "") and "failed to start" in err


def test_fail_closed_deny_has_guard_error_shape(tree, env):
    """The stub's deny is agent_guard.guard_error's: same keys, same reason frame."""
    _, guard_out, _ = run(tree.direct("agent_guard"), BROKEN_PRE, env)
    _, stub_out, _ = run(tree.via_stub("nope", closed=True), PUSH, env)
    g, s = json.loads(guard_out), json.loads(stub_out)
    assert set(g) == set(s) and set(g["hookSpecificOutput"]) == set(s["hookSpecificOutput"])
    frame = re.compile(r"^stack guard error: .+\. Report STATUS: blocked with this message; do not retry\.$", re.S)
    for x in (g, s):
        assert frame.match(x["hookSpecificOutput"]["permissionDecisionReason"])
        assert x["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        assert "STACK_POLICY" in x["systemMessage"]


def test_module_shadowing_on_pythonpath_ignored(tree, env, tmp_path):
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "agent_guard.py").write_text("import sys\nprint('EVIL')\ndef main(a):\n    return 7\n")
    want = run(tree.direct("agent_guard", ["no-push"]), PUSH, env)
    for extra in ({"PYTHONPATH": str(evil)}, {"PYTHONPATH": str(evil), "PYTHONSAFEPATH": "1"}):
        assert run(tree.via_stub("agent_guard", ["no-push"]), PUSH, dict(env, **extra)) == want


@pytest.mark.parametrize("ver", ["3.12", "3.9"])
def test_old_interpreter_refused_by_stub(tree, env, ver):
    py = uv_python(ver) if ver != "3.9" else "/usr/bin/python3"
    if not py or not os.access(py, os.X_OK) or run([py, "-c", "pass"])[0] != 0:
        pytest.skip("no Python %s here" % ver)
    rc, out, _ = run([py, str(tree.stub), "--fail-closed", "agent_guard", "no-push"], PUSH, env)
    hso = json.loads(out)["hookSpecificOutput"]
    assert rc == 0 and hso["permissionDecision"] == "deny" and "needs Python >= 3.13" in hso["permissionDecisionReason"]
    rc, out, err = run([py, str(tree.stub), "agent_guard"], {"hook_event_name": "Stop"}, env)
    assert (rc, out) == (0, "") and "needs Python >= 3.13" in err


def test_stub_static_contract():
    src = (HOOKS_SRC / "stack_hook.py").read_text()
    ast.parse(src, feature_version=(3, 13))
    ast.parse(src, feature_version=(3, 8))           # old interpreters reach the version check
    ns = {}
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == "MODULES":
            ns = ast.literal_eval(node.value)
    # each module's own `if __name__ == "__main__"` decides main(sys.argv) vs main(sys.argv[1:])
    for mod, full in ns.items():
        m = ast.parse((HOOKS_SRC / (mod + ".py")).read_text())
        guard = [n for n in m.body if isinstance(n, ast.If) and "__main__" in ast.unparse(n.test)]
        call = ast.unparse(guard[-1].body[0])
        assert call == ("sys.exit(main(sys.argv))" if full else "sys.exit(main(sys.argv[1:]))"), (mod, call)


# ---------------------------------------------------------------- launcher
SHELLS = [s for s in ("/bin/sh", "/bin/bash", "/bin/dash", "/bin/zsh --emulate sh")
          if os.access(s.split()[0], os.X_OK)]


def wrapper(path, real, tag):
    """A fake interpreter: says it was picked, then runs the real one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\necho "picked:%s" >&2\nexec "%s" "$@"\n' % (tag, real))
    path.chmod(0o755)
    return path


def fake_uv(bindir, prints, log):
    bindir.mkdir(parents=True, exist_ok=True)
    (bindir / "uv").write_text('#!/bin/sh\necho "$@" > "%s"\necho "%s"\n' % (log, prints))
    (bindir / "uv").chmod(0o755)


@pytest.fixture(params=SHELLS)
def sh(request):
    return request.param


def launch(tree, env, sh, closed=True, stdin=PUSH):
    return run(tree.via_launcher("agent_guard", ["no-push"], closed=closed, sh=sh), stdin, env)


def test_launcher_stack_python_found(tree, env, sh, tmp_path):
    (tree.c / "bin" / "stack-python").symlink_to(wrapper(tmp_path / "real" / "py", PY, "stack-python"))
    rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c)), sh)
    assert rc == 0 and decision((rc, out, err)) == "deny" and "picked:stack-python" in err


def test_launcher_stack_python_override_wins(tree, env, sh, tmp_path):
    (tree.c / "bin" / "stack-python").symlink_to(wrapper(tmp_path / "a" / "py", PY, "stack-python"))
    e = dict(env, CLAUDE_CONFIG_DIR=str(tree.c), STACK_PYTHON=str(wrapper(tmp_path / "b" / "py", PY, "override")))
    rc, out, err = launch(tree, e, sh)
    assert decision((rc, out, err)) == "deny" and "picked:override" in err and "stack-python" not in err


def test_launcher_sibling_stack_python(tree, env, sh, tmp_path):
    """A config dir installed while CLAUDE_CONFIG_DIR pointed elsewhere (or was unset): the
    stack-python beside the launcher is found before uv; the config dir's own one still wins."""
    (tree.c / "bin" / "stack-python").symlink_to(wrapper(tmp_path / "sib" / "py", PY, "sibling"))
    log = tmp_path / "uv.args"
    fake_uv(tmp_path / "fakebin", wrapper(tmp_path / "uvpy" / "python3.13", PY, "uv"), log)
    e = dict(env, PATH="%s:/usr/bin:/bin" % (tmp_path / "fakebin"))   # CLAUDE_CONFIG_DIR: an empty dir
    rc, out, err = launch(tree, e, sh)
    assert decision((rc, out, err)) == "deny" and "picked:sibling" in err and not log.exists()
    cfg_bin = Path(e["CLAUDE_CONFIG_DIR"]) / "bin"
    cfg_bin.mkdir()
    (cfg_bin / "stack-python").symlink_to(wrapper(tmp_path / "cfg" / "py", PY, "config"))
    rc, out, err = launch(tree, e, sh)
    assert decision((rc, out, err)) == "deny" and "picked:config" in err and "sibling" not in err


def test_launcher_uv_fallback(tree, env, sh, tmp_path):
    log = tmp_path / "uv.args"
    fake_uv(tmp_path / "fakebin", wrapper(tmp_path / "uvpy" / "bin" / "python3.13", PY, "uv"), log)
    e = dict(env, PATH="%s:/usr/bin:/bin" % (tmp_path / "fakebin"),
             STACK_PYTHON=str(tmp_path / "missing"), CLAUDE_CONFIG_DIR=str(tree.c))
    rc, out, err = launch(tree, e, sh)
    assert decision((rc, out, err)) == "deny" and "picked:uv" in err
    # uv-managed only: a .venv or uv.toml in the hook's cwd (the user's project) is never used
    assert log.read_text().split() == ["python", "find", "--system", "--managed-python", "--no-project",
                                       "--no-config", "3.13"]


def test_launcher_uv_flags_ignore_project_venv_and_config(tree, env, tmp_path):
    """Real uv: a .venv in the hook's cwd (the user's project) or an active VIRTUAL_ENV is never the hook
    interpreter (its .pth files would run first), and a uv.toml there cannot hide the managed 3.13."""
    uv, py313 = shutil.which("uv"), uv_python("3.13")
    if not uv or not py313:
        pytest.skip("uv or a uv-managed 3.13 absent")
    e = dict(env, PATH="%s:/usr/bin:/bin" % os.path.dirname(uv), HOME=os.environ.get("HOME", ""),
             CLAUDE_CONFIG_DIR=str(tree.c))
    cmd = tree.via_launcher("agent_guard", ["no-push"], closed=True)
    venv_proj = tmp_path / "venv-proj"
    venv = venv_proj / ".venv"
    subprocess.run([uv, "venv", "-q", "--python", py313, str(venv)], check=True, capture_output=True)
    (venv / "lib" / "python3.13" / "site-packages" / "marker.pth").write_text(
        "import sys; sys.stderr.write('picked:VENV\\n')\n")
    rc, out, err = run(cmd, PUSH, dict(e, VIRTUAL_ENV=str(venv)), cwd=venv_proj)
    assert decision((rc, out, err)) == "deny" and "VENV" not in err, err
    cfg_proj = tmp_path / "cfg-proj"
    cfg_proj.mkdir()
    (cfg_proj / "uv.toml").write_text('python-preference = "only-system"\n')
    rc, out, err = run(cmd, PUSH, e, cwd=cfg_proj)
    assert decision((rc, out, err)) == "deny", err


@pytest.mark.parametrize("closed,want_rc", [(True, 2), (False, 0)])
def test_launcher_nothing_found(tree, env, sh, closed, want_rc):
    rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c)), sh, closed=closed)
    assert (rc, out) == (want_rc, "") and "./install.sh" in err and "no Python >= 3.13" in err


@pytest.mark.parametrize("closed", [True, False])
def test_launcher_missing_stub_never_reaches_python(tree, env, sh, closed):
    """No hooks/stack_hook.py (a partial install): python's own exit 2 would block every event, also
    the non-fail-closed ones; the launcher takes the nothing-found path instead."""
    tree.stub.unlink()
    rc, out, err = launch(tree, dict(env, STACK_PYTHON=PY), sh, closed=closed)
    assert (rc, out) == ((2 if closed else 0), "") and "./install.sh" in err and "can't open" not in err
    rc, out, err = run(tree.via_launcher("agent_guard", ["budget"], closed=closed, sh=sh), READ,
                       dict(env, STACK_PYTHON=PY, STACK_POLICY="off"))
    assert (rc, out) == (0, "")


@pytest.mark.parametrize("policy", ["off", "OFF"])
def test_launcher_policy_off(tree, env, sh, policy, tmp_path):
    # nothing found: never blocks (but no-push, see test_no_push_start_failure_not_lifted_by_policy_off)
    rc, out, err = run(tree.via_launcher("agent_guard", ["budget"], closed=True, sh=sh), READ,
                       dict(env, CLAUDE_CONFIG_DIR=str(tree.c), STACK_POLICY=policy))
    assert (rc, out) == (0, "") and "./install.sh" in err
    # an interpreter found: the hook still runs (usage accounting and logs do not stop under off)
    e = dict(env, STACK_POLICY=policy, STACK_PYTHON=PY)
    assert run(tree.via_launcher("agent_guard", ["no-push"], closed=True, sh=sh), PUSH, e) == \
        run(tree.direct("agent_guard", ["no-push"]), PUSH, e)


def test_no_push_start_failure_not_lifted_by_policy_off(tree, env, sh):
    """no-push is absolute (agent_guard.py: not switched off by STACK_POLICY=off): a hook that cannot
    start still blocks a push under STACK_POLICY=off, in the launcher and in the stub."""
    e = dict(env, STACK_POLICY="off")                    # CLAUDE_CONFIG_DIR: an empty dir, no interpreter
    rc, out, err = launch(tree, e, sh)
    assert (rc, out) == (2, "") and "./install.sh" in err
    tree.src("agent_guard").unlink()
    rc, out, err = run(tree.via_stub("agent_guard", ["no-push"], closed=True), PUSH, e)
    assert rc == 0 and decision((rc, out, err)) == "deny"
    assert "STACK_POLICY=off never lifts no-push" in json.loads(out)["systemMessage"]


def test_launcher_dangling_symlink_skipped(tree, env, sh, tmp_path):
    (tree.c / "bin" / "stack-python").symlink_to(tmp_path / "gone" / "python3.13")
    e = dict(env, CLAUDE_CONFIG_DIR=str(tree.c))
    rc, out, err = launch(tree, e, sh)
    assert (rc, out) == (2, "") and "./install.sh" in err
    log = tmp_path / "uv.args"
    fake_uv(tmp_path / "fakebin", wrapper(tmp_path / "uvpy" / "python3.13", PY, "uv"), log)
    rc, out, err = launch(tree, dict(e, PATH="%s:/usr/bin:/bin" % (tmp_path / "fakebin")), sh)
    assert decision((rc, out, err)) == "deny" and "picked:uv" in err


def test_launcher_non_executable_skipped(tree, env, sh, tmp_path):
    p = wrapper(tmp_path / "x" / "py", PY, "noexec")
    p.chmod(0o644)
    rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c), STACK_PYTHON=str(p)), sh)
    assert (rc, out) == (2, "") and "picked" not in err


def test_launcher_old_version_by_name_skipped(tree, env, sh, tmp_path):
    for name in ("python3.12", "python3.9", "python2.7", "python3.12t"):
        old = wrapper(tmp_path / name / name, PY, "old")
        rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c), STACK_PYTHON=str(old)), sh)
        assert (rc, out) == (2, "") and "picked" not in err, name
    log = tmp_path / "uv.args"
    fake_uv(tmp_path / "fakebin", wrapper(tmp_path / "uvold" / "python3.12", PY, "old"), log)
    rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c),
                                     PATH="%s:/usr/bin:/bin" % (tmp_path / "fakebin")), sh)
    assert (rc, out) == (2, "") and "picked" not in err
    ok = wrapper(tmp_path / "new" / "python3.14", PY, "new")       # 3.13+ by name passes
    rc, out, err = launch(tree, dict(env, CLAUDE_CONFIG_DIR=str(tree.c), STACK_PYTHON=str(ok)), sh)
    assert decision((rc, out, err)) == "deny" and "picked:new" in err


def test_launcher_old_version_behind_symlink_refused_by_stub(tree, env, sh):
    """stack-python -> a 3.12 the launcher cannot see by name: the stub's own check denies."""
    py312 = uv_python("3.12")
    if not py312:
        pytest.skip("no uv-managed 3.12")
    (tree.c / "bin" / "stack-python").symlink_to(py312)
    e = dict(env, CLAUDE_CONFIG_DIR=str(tree.c))
    rc, out, _ = launch(tree, e, sh)
    assert rc == 0 and "needs Python >= 3.13" in json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    rc, out, err = launch(tree, e, sh, closed=False, stdin={"hook_event_name": "Stop"})
    assert (rc, out) == (0, "") and "needs Python >= 3.13" in err


def test_launcher_shellcheck():
    sc = shutil.which("shellcheck")
    if not sc:
        pytest.skip("shellcheck not installed")
    p = subprocess.run([sc, "-s", "sh", str(LAUNCHER_SRC)], capture_output=True, text=True, check=False)
    assert p.returncode == 0, p.stdout


# ---------------------------------------------------------------- timing (loose, never flaky)
def test_stub_faster_than_direct_script(tree, tmp_path):
    """Warm per-call wall time of a PreToolUse Read (`budget`), direct vs stub vs sh+stub; only asserts
    the stub path beats recompiling the 579 KB script each call."""
    cache = tree.hooks / "__pycache__"
    if not os.access(cache, os.W_OK) or not tree.pyc("agent_guard").exists():
        pytest.skip("pycache not writable here")
    root = tmp_path / "bench"
    events = session_events(root)
    e = dict(base_env(root), STACK_PYTHON=PY)
    for mod, args, _, stdin in events[:8]:                       # session, prompt, subagent A1 started
        run(tree.direct(mod, args), stdin, e)
    read = events[8][3]
    cmds = {"direct": tree.direct("agent_guard", ["budget"]), "stub": tree.via_stub("agent_guard", ["budget"]),
            "sh+stub": tree.via_launcher("agent_guard", ["budget"], closed=True)}
    n = int(os.environ.get("STACK_HOOK_BENCH_N", "20"))
    times = {k: [] for k in cmds}
    for _ in range(2):                                           # warm-up
        for c in cmds.values():
            run(c, read, e)
    for _ in range(n):
        for k, c in cmds.items():                                # interleaved: drift hits all alike
            t = time.perf_counter()
            rc, out, err = run(c, read, e)
            times[k].append((time.perf_counter() - t) * 1000.0)
            assert rc == 0 and decision((rc, out, err)) == "allow", (k, err)
    med = {k: round(statistics.median(v), 1) for k, v in times.items()}
    print(json.dumps({"python": "%d.%d.%d" % sys.version_info[:3], "n": n, "median_ms": med,
                      "p90_ms": {k: round(sorted(v)[int(0.9 * (len(v) - 1))], 1) for k, v in times.items()}}))
    assert med["stub"] < med["direct"] and med["sh+stub"] < med["direct"], med
