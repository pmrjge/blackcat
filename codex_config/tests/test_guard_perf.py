"""p95 of one hook call < 100 ms (DESIGN.md §9 guard list), measured the way Codex runs it:
/bin/sh '<stub>' <mode>, a fresh interpreter per call, a realistic mix of events, the guard's
bytecode precompiled the way the installer does after apply (`<python> -I` py_compile, checked-hash
pycs in <guard dir>/__pycache__, one per target interpreter). The numbers are printed (pytest -s
shows them) and written to <tmp>/p95.json, with the interpreter's own start-up (`<python> -I -c
pass`) beside them.

Decision (2026-10-06, macOS 27 arm64, inside the Claude sandbox, n=96 per run): the 100 ms target
stays, end to end, for a real interpreter linked as stack-python, with the installer's precompiled
bytecode; it is not relaxed. Measured p95 (interpreter start-up `-I -c pass` p95 in brackets):
uv CPython 3.13.16 38-41 ms [15-16]; Apple's 3.9.6 framework binary (CLT or Xcode, what
`uv --python 3.9` resolves to) 82-87 ms [30-32] with precompiled bytecode, 97-106 ms without (the
earlier 105.7 ms failure). Apple's 3.9 under `-I` never writes bytecode and ships no stdlib pycs,
so every call compiles the stdlib it imports (re, json, shlex: ~30 ms); the guard and the stub keep
that set small (SourceFileLoader, not importlib.util, which pulls in typing: ~15 ms per call on 3.9). The
/usr/bin/python3 xcrun shim (the stub's fallback and the managed tier's interpreter) cannot be timed
here: in the sandbox xcrun cannot write its cache db, so `-c pass` alone takes 484-500 ms and a hook
call 566-617 ms (90 ms above that start-up). Its test runs only with CODEX_GUARD_PERF_SHIM=1,
outside the sandbox (the user-run command in test_p95_usr_bin_python3_fallback's skip reason).
stack-python must never link to /usr/bin/python3: the shim dispatches on its argv[0] and fails as
`stack-python` (exit 72, so every gated call would be denied).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from _guard_helpers import Stack, bash, event, interpreter, pre, precompile, run_stub

P95_LIMIT_MS = 100.0
ROUNDS = 12


def mix(stack):
    patch = "*** Begin Patch\n*** Update File: src/app.py\n@@\n-a\n+b\n*** End Patch\n"
    return [
        ("pre_tool_use", bash("git status && rg -n TODO src | head", agent_type="python-engineer")),
        ("pre_tool_use", bash("bash -c \"git -C repo push origin main\"", agent_type="coder")),
        ("pre_tool_use", bash("uv run --no-project --with pytest pytest -q tests",
                              agent_type="code-reviewer")),
        ("pre_tool_use", pre("apply_patch", {"command": patch}, agent_type="python-engineer")),
        ("pre_tool_use", pre("spawn_agent", {"agent_type": "coder", "message": "m", "model": "x"},
                             agent_type=None)),
        ("pre_tool_use", pre("mcp__libdocs__get_docs", {"id": "x"}, agent_type="python-engineer")),
        ("permission_request", event("permission_request", tool_input={"command": "git commit -m x"})),
        ("post_tool_use", event("post_tool_use")),
    ]


def percentiles(times):
    times = sorted(times)
    return times[len(times) // 2], times[int(len(times) * 0.95) - 1], times[-1]


def startup(python, env, n):
    """`<python> -I -c pass`: the interpreter's own start-up, the floor under every hook call."""
    times = []
    for i in range(n + 3):
        t = time.perf_counter()
        subprocess.run([python, "-I", "-c", "pass"], env=env, capture_output=True, check=True)
        if i >= 3:
            times.append((time.perf_counter() - t) * 1000.0)
    return percentiles(times)


def measure(tmp_path, python, link):
    """(report, p95): the mix through the stub, `link` = python is linked as stack-python (else the
    stub falls back to /usr/bin/python3)."""
    stack = Stack(tmp_path, python=python if link else None)
    stack.guard["caps"] = {"mcp_calls_per_agent": 0, "mcp_calls_per_session": 0}   # 0 = no cap
    stack.write_policy()
    pycs = precompile(stack, python)
    for mode, ev in mix(stack):                # warm-up: the state dir, the OS file cache
        run_stub(stack, mode, ev, timeout=60)
    times = []
    for _ in range(ROUNDS):
        for mode, ev in mix(stack):
            t = time.perf_counter()
            rc, _, err = run_stub(stack, mode, ev, timeout=60)
            times.append((time.perf_counter() - t) * 1000.0)
            assert rc == 0, err
    p50, p95, top = percentiles(times)
    s50, s95, _ = startup(python, stack.env(), len(times))
    report = {"python": python, "version": subprocess.check_output(
                  [python, "-I", "-c", "import sys; print(sys.version.split()[0])"],
                  env=stack.env(), text=True).strip(),
              "n": len(times), "p50_ms": round(p50, 1), "p95_ms": round(p95, 1),
              "max_ms": round(top, 1), "startup_p50_ms": round(s50, 1),
              "startup_p95_ms": round(s95, 1), "guard_own_p95_ms": round(p95 - s95, 1),
              "pycs": sorted(os.path.basename(p) for p in pycs)}
    (tmp_path / "p95.json").write_text(json.dumps(report))
    print("\nguard hook timing: %s" % json.dumps(report))
    return report, p95


def test_p95_under_100ms(tmp_path):
    report, p95 = measure(tmp_path, interpreter(), link=True)
    tag = "codex_guard.%s.pyc" % sys.implementation.cache_tag
    assert tag in report["pycs"], report
    assert p95 < P95_LIMIT_MS, report


@pytest.mark.skipif(os.environ.get("CODEX_GUARD_PERF_SHIM") != "1",
                    reason="user-run, outside the sandbox: CODEX_GUARD_PERF_SHIM=1 uv run --no-project "
                           "--python 3.13 --with pytest python -m pytest -q -s -p no:cacheprovider "
                           "codex_config/tests/test_guard_perf.py")
def test_p95_usr_bin_python3_fallback(tmp_path):
    """The stub's fallback and the managed tier's interpreter: /usr/bin/python3 (on macOS the xcrun
    shim), with its own cpython-39 pyc precompiled."""
    if not os.access("/usr/bin/python3", os.X_OK):
        pytest.skip("no /usr/bin/python3 on this machine")
    report, p95 = measure(tmp_path, "/usr/bin/python3", link=False)
    assert p95 < P95_LIMIT_MS, report
