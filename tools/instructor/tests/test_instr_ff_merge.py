"""ff-merge on scratch repositories: CAS ref move, checkout sync, refusals, lock, rollback, suite.

Run: uv run --with pytest pytest -q tools/instructor/tests/"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

import check_suite
import ff_merge
from instr_common import Run
from instr_testlib import commit, git, run_script, scratch, sha, status


def ff(m: Path, *args: str):
    cp = run_script("ff_merge.py", "--repo", str(m), *args, cwd=m)
    return cp, status(cp.stdout)


def test_dry_run_changes_nothing(tmp_path):
    m, wt = scratch(tmp_path)
    before = sha(m, "main")
    cp, (st, verb, kv, log) = ff(m, "--branch", "feat", "--suite", "none", "--dry-run")
    assert (cp.returncode, st, verb, kv["dry_run"]) == (0, "OK", "ff-merge", "1")
    assert sha(m, "main") == before and not (m / "b.txt").exists()
    assert "update-ref" in Path(log).read_text() and Path(log).parent == m / ".claude-work" / "instr"


def test_fast_forward_moves_ref_and_checkout_then_noop(tmp_path):
    m, wt = scratch(tmp_path)
    cp, (st, _, kv, _) = ff(m, "--branch", "feat", "--suite", "none")
    assert (cp.returncode, st, kv["merged"], kv["suite"]) == (0, "OK", "1", "skipped")
    assert sha(m, "main") == sha(m, "feat") and (m / "b.txt").read_text() == "b\n"
    assert git("status", "--porcelain", "--untracked-files=no", cwd=m) == ""
    assert "instr ff-merge: feat" in git("reflog", "-1", "--format=%gs", "refs/heads/main", cwd=m)
    cp, (st, _, kv, _) = ff(m, "--branch", "feat", "--suite", "none")
    assert (cp.returncode, st, kv["reason"]) == (3, "NOOP", "already-merged")


def test_from_the_branch_worktree(tmp_path):
    m, wt = scratch(tmp_path)
    cp = run_script("ff_merge.py", "--branch", "feat", "--suite", "none", cwd=wt)
    assert status(cp.stdout)[0] == "OK" and (m / "b.txt").exists()


@pytest.mark.parametrize("setup,reason", [
    ("diverged", "not-fast-forward"), ("dirty", "main-dirty"), ("untracked", "main-would-overwrite"),
    ("busy", "main-busy"), ("nobranch", "no-branch"),
])
def test_refusals_change_nothing(tmp_path, setup, reason):
    m, wt = scratch(tmp_path)
    branch = "feat"
    if setup == "diverged":
        commit(m, "c.txt")
    elif setup == "dirty":
        (m / "a.txt").write_text("someone's work\n")
    elif setup == "untracked":
        (m / "b.txt").write_text("untracked, not mine\n")
    elif setup == "busy":
        Path(git("rev-parse", "--path-format=absolute", "--git-path", "MERGE_HEAD", cwd=m)).write_text(sha(m, "feat"))
    else:
        branch = "nope"
    before = sha(m, "main")
    cp, (st, _, kv, _) = ff(m, "--branch", branch, "--suite", "none")
    assert (cp.returncode, st, kv["reason"]) == (1, "FAIL", reason)
    assert sha(m, "main") == before
    if setup == "dirty":
        assert (m / "a.txt").read_text() == "someone's work\n"
    if setup == "untracked":
        assert (m / "b.txt").read_text() == "untracked, not mine\n"


@pytest.mark.parametrize("bad", ["-x", "--upload-pack=x", "a..b", "x;rm -rf y", "$(id)", "a b", "x.lock",
                                 "HEAD", "../main", "a//b", "é", "x/", ".hidden", "a@{1}", "", "x" * 101])
def test_branch_allowlist(tmp_path, bad):
    m, _ = scratch(tmp_path)
    cp, (st, _, kv, log) = ff(m, "--branch", bad, "--suite", "none")
    assert (cp.returncode, st, kv["reason"], log) == (2, "FAIL", "bad-arg", "none")
    assert not (m / ".claude-work").exists()


@pytest.mark.parametrize("args", [["--suite", "all"], ["--wait", "-1"], ["--wait", "601"], ["--timeout", "1e3"],
                                  ["--repo", "relative/path"], ["--repo", "/a/../b"], ["--repo", "/a b"],
                                  ["--brnch", "feat"], ["--branch", "feat", "extra"]])
def test_other_bad_args(tmp_path, args):
    m, _ = scratch(tmp_path)
    cp = run_script("ff_merge.py", *(args if "--branch" in args else ["--branch", "feat", *args]), cwd=m)
    assert cp.returncode == 2 and status(cp.stdout)[2]["reason"] == "bad-arg"


def test_lock_busy_and_forged_locked_flag(tmp_path):
    m, _ = scratch(tmp_path)
    lock = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=m)) / "instr-ff-merge.lock"
    holder = subprocess.Popen(["/usr/bin/lockf", "-k", str(lock), "sleep", "30"])
    try:
        for _ in range(100):
            if lock.exists() and ff_merge.lock_held(lock):
                break
            time.sleep(0.05)
        cp, (st, _, kv, _) = ff(m, "--branch", "feat", "--suite", "none", "--wait", "0")
        assert (cp.returncode, st, kv["reason"]) == (1, "FAIL", "locked")
    finally:
        holder.kill()
        holder.wait()
    cp, (st, _, kv, _) = ff(m, "--branch", "feat", "--suite", "none", "--locked")
    assert (st, kv["reason"]) == ("FAIL", "lock-not-held") and not (m / "b.txt").exists()


def _ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**{"branch": "feat", "suite": "none", "timeout": 60, "dry_run": False, **kw})


def test_cas_loses_to_a_concurrent_move(tmp_path, monkeypatch, capsys):
    m, wt = scratch(tmp_path)
    git("switch", "-q", "-c", "elsewhere", cwd=m)          # main checked out nowhere
    other = commit(m, "c.txt")                             # a commit main is about to move to
    real = ff_merge.main_checkout

    def racing(cwd):                                       # another writer moves main after the checks
        git("update-ref", "refs/heads/main", other, cwd=m)
        return real(cwd)
    monkeypatch.setattr(ff_merge, "main_checkout", racing)
    rc = ff_merge.merge(_ns(), Run("ff-merge", m), m)
    st, _, kv, _ = status(capsys.readouterr().out)
    assert (rc, st, kv["reason"]) == (1, "FAIL", "main-moved") and sha(m, "main") == other


def test_checkout_update_failure_rolls_back(tmp_path, monkeypatch, capsys):
    m, wt = scratch(tmp_path)
    old, real = sha(m, "main"), Run.step

    def failing(self, label, argv, cwd, **kw):
        return (1, "") if label == "read-tree" else real(self, label, argv, cwd, **kw)
    monkeypatch.setattr(Run, "step", failing)
    rc = ff_merge.merge(_ns(), Run("ff-merge", m), m)
    st, _, kv, _ = status(capsys.readouterr().out)
    assert (rc, st, kv["reason"], kv["rollback"]) == (1, "FAIL", "checkout-update", "ok")
    assert sha(m, "main") == old


FAKE_C10 = {
    "dot-claude/hooks/agent_guard.py": "import sys\nsys.exit(0)\n",
    "tests/lint_agents.py": "print('lint ok')\n",
    "tests/prompt_budget.py": "print('budget ok')\n",
    "tests/install_smoke.sh": "echo '  PASS  one'\necho '== Summary: 1 passed, 0 failed'\n",
    "tests/test_fake.py": "def test_ok():\n    assert True\n",
    "tools/x.sh": "echo ok\n",
}


@pytest.mark.parametrize("broken,result", [(None, "passed"), ("tests/test_fake.py", "failed")])
def test_suite_runs_on_main_after_the_move(tmp_path, monkeypatch, capsys, broken, result):
    m, wt = scratch(tmp_path, FAKE_C10)
    if broken:
        commit(wt, broken, "def test_bad():\n    assert False\n")
    monkeypatch.setattr(check_suite, "PYTHON", Path(sys.executable))
    rc = ff_merge.merge(_ns(suite="c10"), Run("ff-merge", m), m)
    st, _, kv, log = status(capsys.readouterr().out)
    assert (kv["merged"], kv["suite"]) == ("1", result) and sha(m, "main") == sha(m, "feat")
    assert (rc, st) == ((0, "OK") if result == "passed" else (1, "FAIL"))
    assert kv["pytest_passed"] == ("1" if result == "passed" else "0")


def test_suite_needs_a_main_checkout(tmp_path):
    m, _ = scratch(tmp_path)
    git("switch", "-q", "-c", "elsewhere", cwd=m)
    cp, (st, _, kv, _) = ff(m, "--branch", "feat")
    assert (st, kv["reason"]) == ("FAIL", "main-not-checked-out") and sha(m, "main") != sha(m, "feat")
    cp, (st, _, kv, _) = ff(m, "--branch", "feat", "--suite", "none")
    assert st == "OK" and sha(m, "main") == sha(m, "feat") and kv["main"] == "-"


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not on PATH")
def test_runs_as_a_pep723_script_under_uv(tmp_path):
    m, _ = scratch(tmp_path)
    cp = subprocess.run(["uv", "run", "--quiet", "--script", str(Path(ff_merge.__file__)), "--branch", "feat",
                         "--suite", "none", "--dry-run"], cwd=m, capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0 and status(cp.stdout)[0] == "OK", cp.stderr
