# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""check-suite: the stack's C10 check suite in one checkout, one status line.

Steps, in order: bash -n on every tracked *.sh, agent_guard --self-test, lint_agents,
prompt_budget --check, pytest (tests/ and tools/instructor/tests/, one run each), install_smoke (FAIL lines
other than the two known openpty cases count). The interpreter is fixed (the stack's tools venv),
not an argument: a recipe argument must never choose what runs."""
from __future__ import annotations

import re
import sys
from pathlib import Path

from instr_common import Parser, Run, abort, abs_path, bounded_int, clean_env, git_out, toplevel

STEPS = ("bash-n", "guard-self-test", "lint-agents", "prompt-budget", "pytest", "smoke")
PYTHON = Path.home() / ".claude" / "venvs" / "tools" / "bin" / "python"
DROP_ENV = ("STACK_LIMITS_SNAPSHOT", "CLAUDE_SESSION_ID")
# install_smoke cases that fail where os.openpty() is denied (sandboxed Bash); pass in a terminal
KNOWN_SMOKE = (re.compile(r"supply-chain confirmation \("),
               re.compile(r"controlling-terminal supply confirmation \("))
_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed)")


def build_plan(repo: Path, steps: tuple[str, ...]) -> list[tuple[str, list[str], Path]]:
    """(step, argv, cwd) for each selected step; list form only, no shell."""
    py = str(PYTHON)
    plan: list[tuple[str, list[str], Path]] = []
    for step in steps:
        if step == "bash-n":
            rc, out = git_out(["ls-files", "-z", "--", "*.sh"], repo)
            for f in sorted(filter(None, out.split("\0"))) if rc == 0 else []:
                plan.append((step, ["/bin/bash", "-n", "--", "./" + f], repo))
        elif step == "guard-self-test":
            plan.append((step, [py, "dot-claude/hooks/agent_guard.py", "--self-test"], repo))
        elif step == "lint-agents":
            plan.append((step, [py, "tests/lint_agents.py"], repo))
        elif step == "prompt-budget":
            plan.append((step, [py, "tests/prompt_budget.py", "--check"], repo))
        elif step == "pytest":  # one run per directory: each has its own conftest.py, imported by name
            for d in ("tests/", "tools/instructor/tests/"):
                if (repo / d).is_dir():
                    plan.append((step, [py, "-m", "pytest", "-q", d], repo))
        elif step == "smoke":
            plan.append((step, ["/bin/bash", "tests/install_smoke.sh"], repo))
    return plan


def judge(step: str, rc: int, out: str, kv: dict) -> bool:
    """Whether a finished step passed; adds its counts to kv (summed over the pytest runs)."""
    if step == "pytest":
        tail = [ln for ln in out.splitlines() if _COUNT.search(ln) and " in " in ln]
        counts = {k.rstrip("s") if k.startswith("error") else k: int(n)
                  for n, k in _COUNT.findall(tail[-1] if tail else "")}
        for k in ("passed", "failed", "error", "skipped"):
            name = "pytest_" + ("errors" if k == "error" else k)
            kv[name] = kv.get(name, 0) + counts.get(k, 0)
        return rc == 0 and bool(tail)
    if step == "smoke":
        m = re.search(r"^== Summary: (\d+) passed, (\d+) failed", out, re.M)
        fails = re.findall(r"^  FAIL  (.*)$", out, re.M)
        new = [f for f in fails if not any(k.match(f) for k in KNOWN_SMOKE)]
        kv.update(smoke_passed=m.group(1) if m else 0, smoke_known_fail=len(fails) - len(new),
                  smoke_new_fail=len(new))
        return bool(m) and not new and int(m.group(2)) == len(fails)
    return rc == 0


def run_suite(run: Run, repo: Path, steps: tuple[str, ...], fail_fast: bool, timeout: int,
              dry_run: bool) -> tuple[bool, dict]:
    """Build the plan, then log it (dry run) or execute it. Returns (passed, status keys)."""
    plan = build_plan(repo, steps)
    run.plan(plan)
    kv: dict = {"steps": len(plan)}
    if not plan:
        return False, {**kv, "reason": "empty-plan"}
    if dry_run:
        return True, {**kv, "dry_run": 1}
    if not PYTHON.is_file():
        return False, {**kv, "reason": "no-tools-python"}
    failed: list[str] = []
    env = clean_env(DROP_ENV)
    for step, argv, cwd in plan:
        if failed and fail_fast:
            break
        rc, out = run.step(step, argv, cwd, env=env, timeout=timeout)
        if not judge(step, rc, out, kv) and step not in failed:
            failed.append(step)
    kv["failed"] = ",".join(failed) or "none"
    return not failed, kv


def main(argv: list[str] | None = None) -> int:
    ap = Parser("check-suite", description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=abs_path, help="checkout to check (default: the current one)")
    ap.add_argument("--only", action="append", choices=STEPS, help="run only these steps")
    ap.add_argument("--skip", action="append", choices=STEPS, default=[], help="leave these out")
    ap.add_argument("--fail-fast", action="store_true", help="stop after the first failed step")
    ap.add_argument("--timeout", type=bounded_int(1, 7200), default=3600, help="seconds per step")
    ap.add_argument("--dry-run", action="store_true", help="log the command plan, run nothing")
    a = ap.parse_args(argv)
    repo = toplevel(a.repo) or abort("check-suite", "not-a-checkout")
    steps = tuple(s for s in STEPS if (not a.only or s in a.only) and s not in a.skip)
    run = Run("check-suite", repo)
    ok, kv = run_suite(run, repo, steps, a.fail_fast, a.timeout, a.dry_run)
    return run.finish("OK" if ok else "FAIL", repo=repo.name, **kv)


if __name__ == "__main__":
    sys.exit(main())
