"""check-suite: plan, result parsing (pytest summary, install_smoke known failures), status line.

Run: uv run --with pytest pytest -q tools/instructor/tests/"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import check_suite
from instr_testlib import commit, git, run_script, status

FAKE = {
    "dot-config/dot-claude/hooks/agent_guard.py": "import sys\nsys.exit(0)\n",
    "tests/lint_agents.py": "print('lint ok')\n",
    "tests/prompt_budget.py": "import sys\nassert sys.argv[1:] == ['--check']\n",
    "tests/install_smoke.sh": "echo '  PASS  one'\necho '== Summary: 1 passed, 0 failed'\n",
    "tests/test_fake.py": "def test_ok():\n    assert True\n",
    "lib/x.sh": "echo ok\n",
}
SMOKE_KNOWN = ("echo '  PASS  one'\necho '  FAIL  supply-chain confirmation (rc=1/1, unchanged: 1): x'\n"
               "echo '  FAIL  controlling-terminal supply confirmation (rc=1, unchanged: 1): y'\n"
               "echo '== Summary: 1 passed, 2 failed'\nexit 1\n")


def fake_repo(tmp_path: Path, **override: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)
    for name, text in {**FAKE, **override}.items():
        commit(repo, name, text)
    return repo


@pytest.fixture
def py(monkeypatch):
    monkeypatch.setattr(check_suite, "PYTHON", Path(sys.executable))


def suite(repo: Path, capsys, *args: str):
    rc = check_suite.main(["--repo", str(repo), *args])
    return rc, status(capsys.readouterr().out)


def test_all_steps_pass(tmp_path, py, capsys):
    repo = fake_repo(tmp_path)
    rc, (st, verb, kv, log) = suite(repo, capsys)
    assert (rc, st, verb, kv["failed"], kv["steps"]) == (0, "OK", "check-suite", "none", "7")
    assert (kv["pytest_passed"], kv["pytest_failed"], kv["smoke_passed"], kv["smoke_new_fail"]) == ("1", "0", "1", "0")
    text = Path(log).read_text()
    assert "## pytest: exit 0" in text and "-m pytest -q tests/" in text


@pytest.mark.parametrize("override,failed", [
    ({"lib/x.sh": "if then fi\n"}, "bash-n"),
    ({"tests/test_fake.py": "def test_bad():\n    assert False\n"}, "pytest"),
    ({"tests/lint_agents.py": "raise SystemExit(1)\n"}, "lint-agents"),
    ({"tests/install_smoke.sh": SMOKE_KNOWN.replace("supply-chain", "doctor")}, "smoke"),
    ({"tests/install_smoke.sh": "echo '  FAIL  x'\necho '== Summary: 0 passed, 1 failed'\n"}, "smoke"),
    ({"tests/install_smoke.sh": "echo crashed early\nexit 0\n"}, "smoke"),
])
def test_a_failing_step_is_named(tmp_path, py, capsys, override, failed):
    repo = fake_repo(tmp_path, **override)
    rc, (st, _, kv, _) = suite(repo, capsys)
    assert (rc, st, kv["failed"]) == (1, "FAIL", failed)


def test_pytest_runs_each_test_dir_with_its_own_conftest(tmp_path, py, capsys):
    """tests/ and tools/instructor/tests/ each have a conftest.py and tests/ imports its own by name:
    one pytest run per directory (in one process the last conftest loaded wins), counts summed."""
    repo = fake_repo(tmp_path, **{
        "tests/conftest.py": "MARK = 'stack'\n",
        "tests/test_fake.py": "from conftest import MARK\n\ndef test_ok():\n    assert MARK == 'stack'\n",
        "tools/instructor/tests/conftest.py": "import sys\n",
        "tools/instructor/tests/test_i.py": "def test_i():\n    assert True\n\ndef test_j():\n    assert True\n"})
    rc, (st, _, kv, log) = suite(repo, capsys, "--only", "pytest")
    assert (rc, st, kv["steps"], kv["pytest_passed"], kv["pytest_failed"]) == (0, "OK", "2", "3", "0")
    text = Path(log).read_text()
    assert "-m pytest -q tests/\n" in text.replace("   (cwd", "\n") and "-m pytest -q tools/instructor/tests/" in text


def test_known_openpty_smoke_failures_pass(tmp_path, py, capsys):
    repo = fake_repo(tmp_path, **{"tests/install_smoke.sh": SMOKE_KNOWN})
    rc, (st, _, kv, _) = suite(repo, capsys, "--only", "smoke")
    assert (rc, st, kv["smoke_known_fail"], kv["smoke_new_fail"]) == (0, "OK", "2", "0")


def test_only_skip_fail_fast_and_dry_run(tmp_path, py, capsys):
    repo = fake_repo(tmp_path, **{"lib/x.sh": "if then fi\n"})
    rc, (st, _, kv, log) = suite(repo, capsys, "--skip", "pytest", "--skip", "smoke", "--dry-run")
    assert (rc, st, kv["dry_run"], kv["steps"]) == (0, "OK", "1", "5")
    assert "## " not in Path(log).read_text()                  # nothing ran
    rc, (st, _, kv, log) = suite(repo, capsys, "--fail-fast")
    assert (st, kv["failed"]) == ("FAIL", "bash-n") and "## guard-self-test" not in Path(log).read_text()


def test_pytest_summary_parsing():
    kv: dict = {}
    out = "....F\n=== short test summary info ===\nFAILED t.py::x - 1 passed in a string\n" \
          "1 failed, 4 passed, 2 skipped, 1 error in 3.21s\n"
    assert not check_suite.judge("pytest", 1, out, kv)
    assert (kv["pytest_passed"], kv["pytest_failed"], kv["pytest_skipped"], kv["pytest_errors"]) == (4, 1, 2, 1)
    assert not check_suite.judge("pytest", 0, "no summary\n", {})


def test_env_drops_session_variables(tmp_path, py, capsys, monkeypatch):
    monkeypatch.setenv("STACK_LIMITS_SNAPSHOT", "x")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "y")
    monkeypatch.setenv("GIT_DIR", "/nonexistent")
    probe = ("import os, sys\n"
             "sys.exit(any(k in os.environ for k in ('STACK_LIMITS_SNAPSHOT', 'CLAUDE_SESSION_ID', 'GIT_DIR')))\n")
    repo = fake_repo(tmp_path, **{"tests/lint_agents.py": probe})
    rc, (st, _, kv, _) = suite(repo, capsys, "--only", "lint-agents")
    assert (rc, st) == (0, "OK")


def test_missing_tools_python_fails(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(check_suite, "PYTHON", tmp_path / "no-python")
    repo = fake_repo(tmp_path)
    rc, (st, _, kv, _) = suite(repo, capsys)
    assert (rc, st, kv["reason"]) == (1, "FAIL", "no-tools-python")


def test_cli_contract(tmp_path):
    cp = run_script("check_suite.py", "--only", "everything", cwd=tmp_path)
    assert cp.returncode == 2 and status(cp.stdout)[2]["reason"] == "bad-arg"
    cp = run_script("check_suite.py", "--dry-run", cwd=tmp_path)               # not a checkout
    assert cp.returncode == 1 and status(cp.stdout)[2]["reason"] == "not-a-checkout"
