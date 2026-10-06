"""p95 of one hook call < 100 ms (DESIGN.md §9 guard list), measured the way Codex runs it:
/bin/sh '<stub>' <mode>, a fresh interpreter per call (the one running the tests, linked as
stack-python), a realistic mix of events. The numbers are printed (pytest -s shows them) and
written to <tmp>/p95.json."""
from __future__ import annotations

import json
import sys
import time

from _guard_helpers import Stack, bash, event, interpreter, pre, run_stub

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


def test_p95_under_100ms(tmp_path):
    stack = Stack(tmp_path, python=interpreter())
    stack.guard["caps"] = {"mcp_calls_per_agent": 0, "mcp_calls_per_session": 0}   # 0 = no cap
    stack.write_policy()
    for mode, ev in mix(stack):                # warm-up: the pyc cache, the state dir
        run_stub(stack, mode, ev)
    times = []
    for _ in range(ROUNDS):
        for mode, ev in mix(stack):
            t = time.perf_counter()
            rc, _, err = run_stub(stack, mode, ev)
            times.append((time.perf_counter() - t) * 1000.0)
            assert rc == 0, err
    times.sort()
    p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95) - 1]
    report = {"python": sys.version.split()[0], "n": len(times), "p50_ms": round(p50, 1),
              "p95_ms": round(p95, 1), "max_ms": round(times[-1], 1)}
    (tmp_path / "p95.json").write_text(json.dumps(report))
    print("\nguard hook timing: %s" % json.dumps(report))
    assert p95 < P95_LIMIT_MS, report
