"""hooks/codex-hook, the POSIX sh stub (INTERFACES.md §3-C; DESIGN.md §4.5 item 4): Python lookup,
both layouts, fail closed (exit 2) for the gating modes when Python or the guard is missing or the
guard dies, never blocking (exit 0) for the observe-only modes, and `python -I` isolation."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

import pytest

from _guard_helpers import (HOOKS_SRC, Stack, bash, decision, event, interpreter, precompile,
                            reason, run_stub)

STUB = HOOKS_SRC / "codex-hook"


@pytest.mark.parametrize("shell", ["sh", "bash"])
def test_stub_parses(shell):
    assert subprocess.run([shell, "-n", str(STUB)]).returncode == 0


def test_stub_runs_the_guard_in_the_stack_layout(tmp_path):
    stack = Stack(tmp_path, python=interpreter())
    rc, out, err = run_stub(stack, "pre_tool_use", bash("git push origin main"))
    assert rc == 0 and decision(out) == "deny" and "never push" in reason(out), err
    rc, out, err = run_stub(stack, "pre_tool_use", bash("ls"))
    assert rc == 0 and out is None, err
    rc, out, err = run_stub(stack, "post_tool_use", event("post_tool_use"))
    assert rc == 0 and out is None, err


def test_stub_runs_the_guard_in_the_flat_managed_layout(tmp_path):
    stack = Stack(tmp_path, python=interpreter(), layout="flat")
    rc, out, err = run_stub(stack, "pre_tool_use", bash("bash -c 'git push'", agent_type="default"),
                            scope="global")
    assert rc == 0 and decision(out) == "deny", err
    rc, out, err = run_stub(stack, "pre_tool_use", bash("ls", agent_type="default"), scope="global")
    assert rc == 0 and out is None, err


def no_python_copy(tmp_path, dangling=False):
    """A stub copy whose only fallback interpreter path does not exist."""
    d = tmp_path / "nopy"
    d.mkdir()
    text = STUB.read_text()
    assert text.count("/usr/bin/python3") >= 2
    (d / "codex-hook").write_text(text.replace("/usr/bin/python3", str(tmp_path / "missing-python3")))
    shutil.copy2(HOOKS_SRC / "codex_guard.py", d / "codex_guard.py")
    if dangling:
        os.symlink(str(tmp_path / "gone"), d / "stack-python")
    return d / "codex-hook"


@pytest.mark.parametrize("dangling", [False, True])
def test_no_python_exits_2_for_gating_modes(tmp_path, dangling):
    stub = no_python_copy(tmp_path, dangling)
    for mode in ("pre_tool_use", "permission_request"):
        p = subprocess.run(["/bin/sh", str(stub), mode], input=b"{}", capture_output=True)
        assert p.returncode == 2 and b"no Python" in p.stderr


def test_no_python_never_blocks_observe_modes(tmp_path):
    stub = no_python_copy(tmp_path)
    for mode in ("post_tool_use", "subagent_stop", "user_prompt_submit", "session_end"):
        p = subprocess.run(["/bin/sh", str(stub), mode], input=b"{}", capture_output=True)
        assert p.returncode == 0 and b"no Python" in p.stderr


def test_missing_guard_exits_2(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    shutil.copy2(STUB, d / "codex-hook")
    os.symlink(interpreter(), d / "stack-python")
    p = subprocess.run(["/bin/sh", str(d / "codex-hook"), "pre_tool_use"], input=b"{}",
                       capture_output=True)
    assert p.returncode == 2 and b"not found" in p.stderr


@pytest.mark.parametrize("body", ["raise SystemExit(3)\n", "def broken(:\n", "import os\nos._exit(1)\n"])
def test_a_dying_guard_is_a_deny_for_gating_modes_only(tmp_path, body):
    d = tmp_path / "flat"
    d.mkdir()
    shutil.copy2(STUB, d / "codex-hook")
    os.symlink(interpreter(), d / "stack-python")
    (d / "codex_guard.py").write_text(body)
    p = subprocess.run(["/bin/sh", str(d / "codex-hook"), "pre_tool_use"], input=b"{}",
                       capture_output=True)
    assert p.returncode == 2
    p = subprocess.run(["/bin/sh", str(d / "codex-hook"), "subagent_stop"], input=b"{}",
                       capture_output=True)
    assert p.returncode == 0


def test_python_environment_variables_are_ignored(tmp_path):
    """`python -I`: PYTHONPATH/PYTHONSTARTUP from the environment never run code in the hook."""
    stack = Stack(tmp_path, python=interpreter())
    evil = tmp_path / "evil"
    evil.mkdir()
    marker = tmp_path / "ran"
    (evil / "sitecustomize.py").write_text("open(%r, 'w').write('x')\n" % str(marker))
    (evil / "json.py").write_text("open(%r, 'w').write('x')\n" % str(marker))
    env = stack.env(PYTHONPATH=str(evil), PYTHONSTARTUP=str(evil / "json.py"))
    rc, out, err = run_stub(stack, "pre_tool_use", bash("git push"), env=env)
    assert rc == 0 and decision(out) == "deny", err
    assert not marker.exists()


def test_stub_loads_the_bytecode_beside_the_guard(tmp_path):
    """The stub's `python -I` loader reads <guard dir>/__pycache__ (sys.pycache_prefix unset), where
    the installer precompiles: an unchecked-hash pyc of a variant guard is what runs."""
    stack = Stack(tmp_path, python=interpreter())
    variant = tmp_path / "variant" / "codex_guard.py"
    variant.parent.mkdir()
    head = "def run(argv, stdin, stdout):\n"
    src = stack.guard_py.read_text()
    assert src.count(head) == 1
    variant.write_text(src.replace(head, head + "    stdout.write('{\"from\": \"pyc\"}\\n')\n"
                                                "    return 0\n"))
    cfile = stack.hooks_dir / "__pycache__" / ("codex_guard.%s.pyc" % sys.implementation.cache_tag)
    subprocess.run([interpreter(), "-I", "-c", "import py_compile, sys; py_compile.compile("
                    "sys.argv[1], cfile=sys.argv[2], doraise=True, invalidation_mode="
                    "py_compile.PycInvalidationMode.UNCHECKED_HASH)", str(variant), str(cfile)],
                   check=True)
    rc, out, err = run_stub(stack, "pre_tool_use", bash("git push"))
    assert rc == 0 and out == {"from": "pyc"}, err


def test_precompiled_guard_runs_unchanged(tmp_path):
    """The installer's precompile step (checked-hash pycs) leaves the verdicts as they are."""
    stack = Stack(tmp_path, python=interpreter())
    pycs = precompile(stack, interpreter())
    assert len(pycs) == len(list(stack.hooks_dir.glob("*.py")))
    rc, out, err = run_stub(stack, "pre_tool_use", bash("git push origin main"))
    assert rc == 0 and decision(out) == "deny", err
    rc, out, err = run_stub(stack, "pre_tool_use", bash("ls"))
    assert rc == 0 and out is None, err


def test_stub_falls_back_to_usr_bin_python3(tmp_path):
    if not os.access("/usr/bin/python3", os.X_OK):
        pytest.skip("no /usr/bin/python3 on this machine")
    stack = Stack(tmp_path)                    # no stack-python link
    rc, out, err = run_stub(stack, "pre_tool_use", bash("git push"), timeout=60)
    assert rc == 0 and decision(out) == "deny", err
