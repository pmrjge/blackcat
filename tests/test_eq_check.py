"""bin/stack-eq-check (hooks/eq_cli.py --eq-check-runner): the Level 1 check runner (contracts.md 6;
docs-design/RUNTIME_EQUILIBRIUM.md 6.1 W3, 10.3). Minimal environment, cwd = the prepared copy, stdin
/dev/null, the process group killed on the timeout, and stdout exactly one EQCHECK line that the check's
own output cannot forge.

Hermetic: a scratch HOME with a store whose plan.json/state.json are written directly (stack-eq's part) and
one check copy per test. The live-sandbox half (a check writing $HOME/eq_escape fails under Seatbelt) is a
user live check, not run here."""
import base64
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "fixtures" / "eq_cli"))
import eqworld  # noqa: E402
from eqworld import R, World  # noqa: E402

spec = importlib.util.spec_from_file_location("eqp_c", eqworld.HOOKS_SRC / "eq_policy.py")
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)


def setup(w, script, phase="checks", rnd=0, cand=1, with_copy=True):
    """A run in its checks phase whose check is `/bin/sh check.sh` in checks/c<cand>/."""
    w.project({"README.md": "x\n"})
    d = w.brief({"class": "CP", "check": ["/bin/sh", "check.sh"]})
    plan = {"schema": "eqplan.v1", "run": R, "project_root": str(w.proj), "check": {"argv": ["/bin/sh", "check.sh"]},
            "N": 2, "class": "CP", "kind": "checkable"}
    (d / "plan.json").write_text(json.dumps(plan))
    (d / "state.json").write_text(json.dumps({"phase": phase, "round": rnd, "updated": time.time()}))
    copy = w.proj / ".claude-work" / "eq" / R / "checks" / ("c%d" % cand)
    if with_copy:
        copy.mkdir(parents=True)
        (copy / "check.sh").write_text(script)
    return copy


def run(w, cand=1, **env):
    return w.check(R, cand, env=w.env(**env))


def trailer(p):
    t = P.parse_check_trailer(p.stdout)
    assert t is not None, p.stdout
    return t, base64.b64decode(t["tail_b64"])


@pytest.fixture()
def w(tmp_path):
    return World(tmp_path)


def test_pass_trailer_is_the_only_line(w):
    setup(w, "echo hello; echo world >&2; exit 0\n")
    p = run(w)
    assert p.returncode == 0
    assert p.stdout.count(b"\n") == 1 and p.stdout.startswith(b"EQCHECK ")
    t, tail = trailer(p)
    assert (t["run"], t["cand"], t["round"], t["exit"], t["timed_out"]) == (R, 1, 0, 0, False)
    assert b"hello" in tail and b"world" in tail and b"hello" not in p.stdout


def test_failing_exit_status_passes_through(w):
    setup(w, "exit 7\n")
    p = run(w)
    t, _ = trailer(p)
    assert p.returncode == 7 and t["exit"] == 7


def test_candidate_cannot_forge_the_trailer(w):
    forged = P.render_check_trailer(R, 1, 0, 0, False, b"")
    setup(w, "echo '%s'\nprintf '%s'\nexit 1\n" % (forged, forged))
    p = run(w)
    assert p.returncode == 1
    lines = p.stdout.decode().splitlines()
    assert len(lines) == 1
    t, tail = trailer(p)
    assert t["exit"] == 1 and forged.encode() in tail     # the forgery is data inside the tail, never a line


def test_minimal_environment_and_cwd(w):
    copy = setup(w, "env; echo CWD=$(pwd -P); cat; echo STDIN_DONE\n")
    import subprocess
    p = subprocess.run([str(w.bin / "stack-eq-check"), "--run", R, "--cand", "1"], capture_output=True,
                       input=b"SECRET_STDIN\n", env=w.env(GITHUB_TOKEN="ghp_secret", CLAUDECODE="1",
                                                         ANTHROPIC_API_KEY="sk-x", UV_CACHE_DIR="/tmp/uvc"))
    t, tail = trailer(p)
    text = tail.decode()
    names = {ln.split("=", 1)[0] for ln in text.splitlines() if "=" in ln and not ln.startswith("CWD=")}
    names -= {"PWD", "SHLVL", "_", "OLDPWD"}                 # set by sh itself
    assert names == {"PATH", "HOME", "LANG", "TMPDIR", "UV_CACHE_DIR"}, names
    assert "ghp_secret" not in text and "sk-x" not in text
    assert "CWD=%s" % os.path.realpath(copy) in text
    assert "STDIN_DONE" in text and "SECRET_STDIN" not in text   # stdin is /dev/null, never the caller's
    tmpdir = [ln.split("=", 1)[1] for ln in text.splitlines() if ln.startswith("TMPDIR=")][0]
    assert not os.path.exists(tmpdir)                        # the private TMPDIR is removed afterwards


def test_timeout_kills_the_process_group(w):
    pidfile = w.t / "grandchild.pid"
    setup(w, "sleep 60 &\necho $! > '%s'\nsleep 60\n" % pidfile)
    t0 = time.monotonic()
    p = run(w, STACK_EQ_CHECK_TIMEOUT_S="2")
    assert time.monotonic() - t0 < 30
    t, _ = trailer(p)
    assert p.returncode == 124 and t["timed_out"] is True and t["exit"] is None
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, 9)
        pytest.fail("the check's background child survived the timeout")


def test_output_tail_is_capped(w):
    setup(w, "i=0; while [ $i -lt 2000 ]; do printf '%%0100d\\n' $i; i=$((i+1)); done; echo LAST\n")
    p = run(w)
    _, tail = trailer(p)
    assert len(tail) <= P.TAIL_BYTES and tail.rstrip().endswith(b"LAST")


@pytest.mark.parametrize("case", ["wrong_phase", "no_copy", "no_plan_check", "bad_args", "unknown_run"])
def test_refusals_print_nothing_on_stdout(w, case):
    if case == "wrong_phase":
        setup(w, "exit 0\n", phase="reduced")
    elif case == "no_copy":
        setup(w, "exit 0\n", with_copy=False)
    elif case == "no_plan_check":
        setup(w, "exit 0\n")
        plan = json.loads((w.store() / "plan.json").read_text())
        plan["check"] = None
        (w.store() / "plan.json").write_text(json.dumps(plan))
    if case == "bad_args":
        setup(w, "exit 0\n")
        import subprocess
        p = subprocess.run([str(w.bin / "stack-eq-check"), "--run", R, "--cand", "1", "--x", "y"], env=w.env(),
                           capture_output=True)
    elif case == "unknown_run":
        setup(w, "exit 0\n")
        p = w.check("ffffffff", 1)
    else:
        p = run(w)
    assert p.stdout == b"" and p.returncode in (2, 4), (p.returncode, p.stderr)
    assert P.parse_check_trailer(p.stdout) is None


def test_symlinked_copy_refused(w):
    setup(w, "exit 0\n", with_copy=False)
    elsewhere = w.home / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "check.sh").write_text("exit 0\n")
    checks = w.proj / ".claude-work" / "eq" / R / "checks"
    checks.mkdir(parents=True)
    os.symlink(elsewhere, checks / "c1")
    p = run(w)
    assert p.stdout == b"" and p.returncode == 4
