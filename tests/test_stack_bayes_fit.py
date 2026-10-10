"""The detached Bayes fitter (WP3b; docs/BAYES.md 2, 2.1, 2.2, A.4, A.9 B1-T11): hooks/stack_bayes.py and
stack_usage.bayes_fit, which runs it at a collector's exit.

Run: ~/.claude/venvs/tools/bin/python -m pytest -q tests/test_stack_bayes_fit.py
The fit itself needs pymc (the opt-in Bayes lock): here a fake tools venv (a stub `python` that records its argv,
cwd, environment, niceness and process group, then behaves as told) stands in for it. stack_bayes.py's numeric core
(numpy only) is tested directly: the MCSE estimator, the delta-method MCSE of a predictive quantile (calibrated by
replication), the turns sweep against direct summation, the clamp at the cap, the sched entries. B1-T11 (determinism
of two real fits) runs only with STACK_BAYES_FIT_PYTHON=<an interpreter with the Bayes lock>.
Every test uses its own XDG_STATE_HOME under tmp_path, never the stack's.
"""
import importlib.util
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
FIX = ROOT / "tests" / "fixtures" / "bayes" / "b1v2"
SYS_PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
EID = "a" * 64
EID2 = "b" * 64
FIT = "0123456789abcdef"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if str(HOOKS) not in sys.path:
    sys.path.insert(0, str(HOOKS))
L = sys.modules.get("stack_limits") or _load("stack_limits", HOOKS / "stack_limits.py")
U = _load("stack_usage_bayes", HOOKS / "stack_usage.py")
B = _load("stack_bayes", HOOKS / "stack_bayes.py")
SEED = L.load_seed()
GOOD_MODEL = {"gate": True, "diag": {"rhat_max": 1.003, "ess_bulk_min": 1841, "ess_tail_min": 1680, "divergences": 0,
                                     "ebfmi_min": 0.76, "constant": ["z_s"], "nan": []}}
BAD_MODEL = {"gate": True, "diag": dict(GOOD_MODEL["diag"], divergences=2)}
PASS_MODEL = {"gate": True, "diag": dict(GOOD_MODEL["diag"], constant=[])}

FAKE_PY = r'''#!/usr/bin/python3
import json, os, subprocess, sys, time
here = os.path.dirname(os.path.abspath(__file__))
ctl = json.load(open(os.path.join(here, "fake.json")))
rec = {"argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(), "pgid": os.getpgrp(), "sid": os.getsid(0),
       "nice": os.getpriority(os.PRIO_PROCESS, 0), "env": dict(os.environ)}
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps(rec) + "\n")
mode = ctl["mode"]
if mode == "real":
    os.execv(ctl["python"], [ctl["python"]] + sys.argv[1:])
if mode == "sleep":
    child = subprocess.Popen(["/bin/sleep", "30"])
    with open(os.path.join(here, "pids.json"), "w") as f:
        json.dump([os.getpid(), child.pid], f)
    time.sleep(ctl.get("secs", 20))
    print("bayes: slept")
    sys.exit(0)
if mode == "ok":
    d = os.path.join(os.environ["XDG_STATE_HOME"], "claude-agent-stack", "limits")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "bayes.json"), "w") as f:
        f.write(open(ctl["doc"]).read())
    for line in ctl.get("lines", ["bayes: fit %s ok" % ("0123456789abcdef")]):
        print(line)
    sys.exit(0)
if mode == "hang":                  # the real stack_bayes.main (its own deadline) around a fit that never ends
    import importlib.util
    sys.path.insert(0, os.path.dirname(sys.argv[3]))
    spec = importlib.util.spec_from_file_location("stack_bayes", sys.argv[3])
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    def fit(cfg, out, log=print):
        with open(os.path.join(here, "pids.json"), "w") as f:
            json.dump([os.getpid()], f)
        time.sleep(ctl.get("secs", 60))
        return 0, "bayes: woke"
    B.missing_deps = lambda: []
    B.fit = fit
    sys.exit(B.main(sys.argv[4:] + ctl.get("args", [])))
if mode.startswith("exit"):
    print("bayes: exit")
    sys.exit(int(mode[4:]))
sys.exit(99)
'''


# ---------------------------------------------------------------- fixtures
@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith(("STACK_", "PYTENSOR", "NUMBA_"))]:
        monkeypatch.delenv(k)
    root = tmp_path / "st" / "claude-agent-stack"
    (root / "limits").mkdir(parents=True)
    (root / "usage").mkdir(parents=True)
    return root


def write_props(st, eid=EID):
    (st / "limits" / "proposals.json").write_text(json.dumps({"schema_version": 1, "evidence_id": eid, "vars": {}}))


def bayes_doc(models=None):
    return {"schema_version": 1, "code": "stack_bayes/1", "generated": "2026-10-09T00:00:00Z", "evidence_id": EID,
            "seed_sha": SEED["sha"], "fit_id": FIT, "risk": dict(L.RISK),
            "models": models if models is not None else {"ctx-ln-h4": GOOD_MODEL, "turns-nb2s-h4": BAD_MODEL},
            "hyper": {}, "drift": {}, "vars": {}, "sched": None}


class Fake:
    """A fake tools venv: <tmp>/cfg/venvs/tools/bin/python, wired in through stack_usage.bayes_python."""

    def __init__(self, tmp_path, monkeypatch):
        self.bin = tmp_path / "cfg" / "venvs" / "tools" / "bin"
        self.bin.mkdir(parents=True)
        self.py = self.bin / "python"
        self.py.write_text(FAKE_PY)
        self.py.chmod(0o755)
        self.doc = tmp_path / "doc.json"
        self.doc.write_text(json.dumps(bayes_doc()))
        self.mode("ok")
        monkeypatch.setattr(U, "bayes_python", lambda: str(self.py))

    def mode(self, mode, **kw):
        (self.bin / "fake.json").write_text(json.dumps(dict(kw, mode=mode, doc=str(self.doc))))

    def calls(self):
        p = self.bin / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


@pytest.fixture
def fake(st, tmp_path, monkeypatch):
    write_props(st)
    return Fake(tmp_path, monkeypatch)


def recs(st):
    p = st / "usage" / "bayes.json.rec"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def can_renice():
    p = subprocess.run([SYS_PY, "-c", "import os\ntry:\n os.nice(10); print(1)\nexcept OSError:\n print(0)"],
                       capture_output=True, text=True)
    return p.stdout.strip() == "1"


# ---------------------------------------------------------------- bayes_fit: how the fitter runs
def test_runs_the_venv_python_isolated_niced_in_its_own_group_and_records_the_fit(st, fake):
    r = U.bayes_fit("session end", now=1e9)
    assert r["status"] == "ok" and r["rc"] == 0 and r["evidence_id"] == EID
    (c,) = fake.calls()
    assert c["argv"] == ["-I", "-B", str(HOOKS / "stack_bayes.py"), "fit"]          # -B: no pycs in hooks/
    assert c["cwd"] == "/" and c["pgid"] == c["pid"] and c["sid"] == c["pid"]      # its own session and group
    if can_renice():
        assert c["nice"] >= os.getpriority(os.PRIO_PROCESS, 0) + U.BAYES_NICE
    assert r["fit_id"] == FIT and r["gates"] == {"ctx-ln-h4": True, "turns-nb2s-h4": False}
    assert r["summary"] == "bayes: fit 0123456789abcdef ok"
    (rec,) = recs(st)
    assert rec == json.loads(json.dumps(r))
    assert U.bayes_python() == str(fake.py)


def test_bayes_python_is_the_tools_venv_under_the_config_dir():
    mod = _load("stack_usage_paths", HOOKS / "stack_usage.py")
    assert mod.bayes_python() == os.path.join(str(HOOKS.parent), "venvs", "tools", "bin", "python")
    assert mod.accel_lock_path().endswith(os.path.join("claude-agent-stack", "accel.lock"))


def test_compile_caches_live_in_the_state_dir_and_the_sessions_knobs_are_dropped(st, fake, monkeypatch):
    """Mutant "PYTENSOR/NUMBA cache path outside the state dir": the child's PYTENSOR_FLAGS base_compiledir and
    NUMBA_CACHE_DIR are under <state>, whatever the session set; stack_bayes.cache_env agrees."""
    monkeypatch.setenv("PYTENSOR_FLAGS", "base_compiledir=/tmp/elsewhere,cxx=/usr/bin/evilcc")
    monkeypatch.setenv("NUMBA_CACHE_DIR", "/tmp/elsewhere")
    monkeypatch.setenv("NUMBA_DISABLE_JIT", "1")
    monkeypatch.setenv("PYTHONPATH", "/tmp/elsewhere")
    assert U.bayes_fit("idle", now=1e9)["status"] == "ok"
    env = fake.calls()[0]["env"]
    root = str(st)
    flags = dict(kv.split("=", 1) for kv in env["PYTENSOR_FLAGS"].split(","))
    assert flags["base_compiledir"].startswith(root + os.sep) and flags["cxx"] == "" and flags["mode"] == "NUMBA"
    assert env["NUMBA_CACHE_DIR"].startswith(root + os.sep)
    assert "NUMBA_DISABLE_JIT" not in env and "PYTHONPATH" not in env and env["PATH"] == U.REFRESH_PATH
    assert B.cache_env(root) == {"PYTENSOR_FLAGS": env["PYTENSOR_FLAGS"], "NUMBA_CACHE_DIR": env["NUMBA_CACHE_DIR"]}
    for d in B.cache_dirs(root):
        assert d.startswith(root + os.sep)


def test_the_timeout_kills_the_whole_fit_group(st, fake, monkeypatch):
    """Mutant "timeout removed": a fit past BAYES_TIMEOUT_S is killed with its process group (a grandchild too),
    recorded failed:timeout, and the collector goes on."""
    monkeypatch.setattr(U, "BAYES_TIMEOUT_S", 1.0)
    fake.mode("sleep", secs=20)
    t = time.monotonic()
    r = U.bayes_fit("idle", now=1e9)
    assert r["status"] == "failed:timeout" and r["rc"] is None and time.monotonic() - t < 10
    pids = json.loads((fake.bin / "pids.json").read_text())
    for pid in pids:
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("pid %d survived the timeout" % pid)
    assert recs(st)[-1]["status"] == "failed:timeout"


def test_default_timeout_is_900_s_and_reaches_the_child(st, fake, monkeypatch):
    assert U.BAYES_TIMEOUT_S == 900.0
    seen = []
    real = U._bayes_child
    monkeypatch.setattr(U, "_bayes_child",
                        lambda cmd, env, timeout, **kw: seen.append(timeout) or real(cmd, env, timeout, **kw))
    U.bayes_fit("idle", now=1e9)
    assert seen == [900.0]


def test_a_held_bayes_lock_skips_without_running(st, fake):
    """Mutant "lock removed": while another fit holds usage/bayes.lock nothing runs and nothing is recorded."""
    with U.Locked(str(st / "usage" / "bayes.lock"), nb=True) as lk:
        assert lk.ok
        assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:locked"
    assert fake.calls() == [] and recs(st) == []
    assert U.bayes_fit("idle", now=1e9)["status"] == "ok"


COLLECTOR = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("stack_usage_collector", sys.argv[1])
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
m.bayes_python = lambda: sys.argv[2]
m.bayes_fit("idle", now=1e9)
'''


def _wait_pids(fake, secs=20.0):
    pj, end = fake.bin / "pids.json", time.monotonic() + secs
    while time.monotonic() < end:
        try:
            return json.loads(pj.read_text())
        except (OSError, ValueError):
            time.sleep(0.05)
    pytest.fail("the fake fitter never started")


def _reap(pids):
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _gone(pid, secs=5.0):
    end = time.monotonic() + secs
    while time.monotonic() < end:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_the_fitter_keeps_the_bayes_lock_when_the_collector_dies(st, fake, tmp_path):
    """Security review F2: the fitter inherits the usage/bayes.lock fd, so a SIGKILLed collector's orphaned fit
    still holds the lock and the next collector's exit skips (skipped:locked) instead of starting a second fit."""
    fake.mode("sleep", secs=20)
    script = tmp_path / "collector.py"
    script.write_text(COLLECTOR)
    col = subprocess.Popen([sys.executable, str(script), str(HOOKS / "stack_usage.py"), str(fake.py)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids = []
    try:
        pids = _wait_pids(fake)
        col.kill()
        col.wait(10)
        assert _gone(pids[0], 0.3) is False                           # the orphaned fit is still running
        with U.Locked(str(st / "usage" / "bayes.lock"), nb=True) as lk:
            assert not lk.ok
        write_props(st, EID2)
        assert U.bayes_fit("session end", now=1e9 + 1, force=True)["status"] == "skipped:locked"
    finally:
        col.kill()
        _reap(pids)
    assert _gone(pids[0])
    with U.Locked(str(st / "usage" / "bayes.lock"), nb=True) as lk:      # freed once the fit is gone
        assert lk.ok


def test_a_sigterm_during_the_fit_kills_its_group_and_reaches_the_collectors_handler(st, fake):
    """A SIGTERM to the collector while the fit runs kills the fit's whole group (recorded failed:signal) and
    calls the collector's own handler (stop); the handler is restored afterwards."""
    import threading
    fake.mode("sleep", secs=20)
    seen = []

    def handler(*_):
        seen.append(1)
    old = signal.signal(signal.SIGTERM, handler)
    box = {}

    def term_when_started():
        box["pids"] = _wait_pids(fake)
        os.kill(os.getpid(), signal.SIGTERM)
    th = threading.Thread(target=term_when_started, daemon=True)
    try:
        th.start()
        t = time.monotonic()
        r = U.bayes_fit("idle", now=1e9)
        th.join(5)
        assert r["status"] == "failed:signal" and r["rc"] is None and time.monotonic() - t < 15, r
        assert seen == [1] and signal.getsignal(signal.SIGTERM) is handler
        assert all(_gone(pid) for pid in box["pids"])
        assert recs(st)[-1]["status"] == "failed:signal"
    finally:
        signal.signal(signal.SIGTERM, old)
        _reap(box.get("pids", []))


def test_no_pymc_is_a_clean_skip_through_the_real_fitter(st, fake):
    """Mutant "the no-pymc path raises": the real stack_bayes.py on an interpreter without the Bayes stack exits 3
    with its one line, writes nothing, and the record says skipped:no-pymc (not an attempt: the next exit tries
    again)."""
    fake.mode("real", python=SYS_PY)
    if subprocess.run([SYS_PY, "-c", "import pymc"], capture_output=True).returncode == 0:
        pytest.skip("%s has pymc" % SYS_PY)
    r = U.bayes_fit("idle", now=1e9)
    assert r["status"] == "skipped:no-pymc" and r["rc"] == 3, r
    assert r["summary"].startswith("bayes: skipped:no-pymc (missing: ")
    assert not (st / "limits" / "bayes.json").exists()
    assert not U._is_attempt(recs(st)[-1])
    fake.mode("ok")
    assert U.bayes_fit("idle", now=1e9 + 1)["status"] == "ok"             # no rate limit after a skip


def test_no_venv_python_is_skipped_no_pymc_without_a_spawn(st, fake, monkeypatch):
    monkeypatch.setattr(U, "bayes_python", lambda: str(fake.bin / "absent"))
    assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:no-pymc"
    assert fake.calls() == []


def test_fitter_main_without_the_stack_exits_3_with_one_line(monkeypatch, capsys, st):
    monkeypatch.setattr(B, "missing_deps", lambda: ["pymc", "nutpie"])
    for cmd in ("fit", "check"):
        assert B.main([cmd]) == B.EXIT_NO_PYMC
        out = capsys.readouterr().out.strip().splitlines()
        assert out == ["bayes: skipped:no-pymc (missing: pymc, nutpie)"]
    assert not (st / "limits" / "bayes.json").exists()


def test_missing_deps_resolves_without_importing(monkeypatch):
    monkeypatch.setattr(B, "DEPS", ("json", "stack_bayes_no_such_module", "stack_bayes_no_such.sub"))
    assert B.missing_deps() == ["stack_bayes_no_such_module", "stack_bayes_no_such.sub"]
    assert "stack_bayes_no_such_module" not in sys.modules


# ---------------------------------------------------------------- bayes_fit: when it runs
def test_once_per_evidence_and_once_per_6h(st, fake):
    t0 = 1e9
    assert U.bayes_fit("idle", now=t0)["status"] == "ok"
    assert U.bayes_fit("idle", now=t0 + 7 * 3600)["status"] == "skipped:same-evidence"
    write_props(st, EID2)
    assert U.bayes_fit("idle", now=t0 + 3600)["status"] == "skipped:rate"
    assert U.bayes_fit("idle", now=t0 + 3600, force=True)["status"] == "ok"            # manual --force
    write_props(st, EID)
    assert U.bayes_fit("idle", now=t0 + 3600 + U.BAYES_MIN_GAP_S - 1)["status"] == "skipped:rate"
    assert U.bayes_fit("idle", now=t0 + 3600 + U.BAYES_MIN_GAP_S + 1)["status"] == "ok"
    assert len(fake.calls()) == 3
    # a failed attempt counts too: the same evidence is not retried
    write_props(st, "c" * 64)
    fake.mode("exit7")
    t1 = t0 + 10 * U.BAYES_MIN_GAP_S
    assert U.bayes_fit("idle", now=t1)["status"] == "failed:exit 7"
    assert U.bayes_fit("idle", now=t1 + U.BAYES_MIN_GAP_S + 1)["status"] == "skipped:same-evidence"


def test_no_proposals_or_off_mode(st, fake, monkeypatch):
    (st / "limits" / "proposals.json").unlink()
    assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:no-proposals"
    (st / "limits" / "proposals.json").write_text('{"evidence_id": "../x"}')
    assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:no-proposals"
    n = len(recs(st))
    write_props(st)
    monkeypatch.setenv("STACK_BAYES", "Off ")
    assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:off"
    assert len(recs(st)) == n and fake.calls() == []


def _eq_run(st, sid="sess1", run="abcdef01", ended=False, phase=None, age=0.0):
    rd = st / sid / "eq" / run
    rd.mkdir(parents=True)
    (rd / "brief.json").write_text("{}")
    if phase:
        (rd / "state.json").write_text(json.dumps({"phase": phase}))
    if ended:
        (rd / "ended.json").write_text("{}")
    t = time.time() - age
    for p in list(rd.iterdir()) + [rd]:
        os.utime(p, (t, t))
    return rd


def test_skipped_while_an_eq_run_is_live(st, fake):
    rd = _eq_run(st)
    assert U.eq_run_live() and U.bayes_fit("idle")["status"] == "skipped:eq-run"
    shutil.rmtree(rd)
    _eq_run(st, ended=True)
    _eq_run(st, run="abcdef02", phase="result")
    _eq_run(st, run="abcdef03", age=U.EQ_LIVE_S + 60)
    _eq_run(st, run="not-a-run")
    assert not U.eq_run_live()
    assert U.bayes_fit("idle")["status"] == "ok"


def test_skipped_while_the_accelerator_lock_is_held(st, fake):
    lock = Path(U.accel_lock_path())
    assert not U.flock_held(str(lock)) and not lock.exists()        # probing never creates it
    with U.Locked(str(lock), nb=True) as lk:
        assert lk.ok and U.flock_held(str(lock))
        assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:accel-lock"
    assert not U.flock_held(str(lock))
    assert U.bayes_fit("idle", now=1e9)["status"] == "ok"


# ---------------------------------------------------------------- the accel.lock holder (work order step 9)
def test_accel_acquire_takes_a_private_regular_file_and_fails_closed(st, tmp_path, monkeypatch):
    """Mutants "accel_acquire ignores a held lock" and "no regular-file check": a second taker gets None
    while the first holds it, the fd again once it is closed; the file is 0600 and carries the holder's
    record; a symlink, a hardlink to another file, a FIFO (without blocking, even where flock works on one) or
    a directory at the path is never taken (mutant "no st_nlink check")."""
    lock = Path(U.accel_lock_path())
    fd = U.accel_acquire("job-a")
    assert fd is not None and U.flock_held(str(lock))
    try:
        assert (lock.stat().st_mode & 0o777) == 0o600
        rec = json.loads(lock.read_text())
        assert rec["holder"] == "job-a" and rec["pid"] == os.getpid() and abs(rec["since"] - time.time()) < 60
        assert U.accel_acquire("job-b") is None
    finally:
        os.close(fd)
    assert not U.flock_held(str(lock))
    fd = U.accel_acquire("job-b")
    assert fd is not None
    os.close(fd)
    lock.unlink()
    target = tmp_path / "elsewhere.lock"
    target.write_text("")
    lock.symlink_to(target)
    assert U.accel_acquire("x") is None and target.read_text() == ""
    lock.unlink()
    os.mkfifo(str(lock))
    t = time.monotonic()
    assert U.accel_acquire("x") is None and time.monotonic() - t < 2
    with monkeypatch.context() as m:            # macOS refuses flock on a FIFO; Linux allows it: the type check
        m.setattr(U.fcntl, "flock", lambda *a: None)
        assert U.accel_acquire("x") is None
    lock.unlink()
    lock.mkdir()
    assert U.accel_acquire("x") is None
    lock.rmdir()
    victim = tmp_path / "victim.txt"            # CWE-62: a hardlink to another file is never truncated
    victim.write_text("keep me\n")
    os.link(str(victim), str(lock))
    assert U.accel_acquire("x") is None and victim.read_text() == "keep me\n"


def test_the_fit_holds_the_accel_lock_and_an_orphan_keeps_it(st, fake, tmp_path):
    """Mutants "probe only" (the fit tests accel.lock but does not hold it), "accel fd not passed to the
    child" and "no holder record": while a fit runs no other accelerator job can take the lock, which names
    the fit; a SIGKILLed collector's orphaned fit keeps it; it is free once the fit is gone."""
    fake.mode("sleep", secs=20)
    script = tmp_path / "collector.py"
    script.write_text(COLLECTOR)
    col = subprocess.Popen([sys.executable, str(script), str(HOOKS / "stack_usage.py"), str(fake.py)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    lock, pids = Path(U.accel_lock_path()), []
    try:
        pids = _wait_pids(fake)
        assert U.accel_acquire("other") is None
        rec = json.loads(lock.read_text())
        assert rec["holder"] == U.ACCEL_HOLDER == "bayes-fit" and rec["pid"] == col.pid
        col.kill()
        col.wait(10)
        assert _gone(pids[0], 0.3) is False                           # the orphaned fit is still running
        assert U.flock_held(str(lock)) and U.accel_acquire("other") is None
        write_props(st, EID2)
        assert U.bayes_fit("session end", now=1e9 + 1, force=True)["status"] == "skipped:locked"
    finally:
        col.kill()
        _reap(pids)
    assert _gone(pids[0])
    fd = U.accel_acquire("other")
    assert fd is not None
    os.close(fd)


def test_a_skip_after_the_accel_lock_was_taken_releases_it(st, fake, monkeypatch):
    """Mutant "the collector's accel fd is never closed": a fit that does not start (no venv python, no
    fitter) or that ends leaves accel.lock free."""
    monkeypatch.setattr(U, "bayes_python", lambda: str(fake.bin / "absent"))
    assert U.bayes_fit("idle", now=1e9)["status"] == "skipped:no-pymc"
    assert not U.flock_held(U.accel_lock_path())
    monkeypatch.setattr(U, "bayes_python", lambda: str(fake.py))
    assert U.bayes_fit("idle", now=1e9)["status"] == "ok"
    assert not U.flock_held(U.accel_lock_path())


# ---------------------------------------------------------------- the fit's own deadline (work order step 10)
def test_the_fits_own_cap_comes_30_s_after_the_collectors():
    """Mutant "cap at or below the collector's": while the collector lives its kill (failed:timeout) must come
    first; the fit's own cap is near it."""
    assert B.FIT_TIMEOUT_S == U.BAYES_TIMEOUT_S + 30


def test_main_arms_the_deadline_around_fit_only(st, monkeypatch, capsys):
    """Mutants "deadline never armed", "a Python SIGALRM handler" and "alarm left armed": during fit() a real
    timer runs with SIGALRM at its default action; afterwards the timer is off and the old disposition back;
    `check` arms nothing; an out-of-range --timeout fails before the fit."""
    seen = []

    def fake_fit(cfg, out, log=print):
        seen.append((signal.getitimer(signal.ITIMER_REAL)[0], signal.getsignal(signal.SIGALRM)))
        return B.EXIT_OK, "bayes: fake"
    monkeypatch.setattr(B, "missing_deps", lambda: [])
    monkeypatch.setattr(B, "fit", fake_fit)
    old = signal.signal(signal.SIGALRM, signal.SIG_IGN)
    try:
        assert B.main(["fit", "--out", str(st / "x.json"), "--timeout", "50"]) == B.EXIT_OK
        assert B.main(["fit", "--out", str(st / "x.json")]) == B.EXIT_OK
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0 and signal.getsignal(signal.SIGALRM) == signal.SIG_IGN
        assert B.main(["check"]) == B.EXIT_OK and signal.getitimer(signal.ITIMER_REAL)[0] == 0
        for bad in ("0", "86401"):
            assert B.main(["fit", "--timeout", bad]) == B.EXIT_FAIL
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert len(seen) == 2
    assert 49 < seen[0][0] <= 50 and seen[0][1] == signal.SIG_DFL
    assert B.FIT_TIMEOUT_S - 1 < seen[1][0] <= B.FIT_TIMEOUT_S and seen[1][1] == signal.SIG_DFL
    assert "bayes: failed: timeout out of range" in capsys.readouterr().out


def test_an_orphaned_fit_ends_itself_at_its_cap_and_frees_both_locks(st, fake, tmp_path):
    """Work order step 10 (mutant "no cap in stack_bayes.py"): the real stack_bayes.main around a fit that never
    ends, under a collector that is SIGKILLed; the orphan keeps usage/bayes.lock and accel.lock, then ends
    itself (SIGALRM) at its --timeout, and both locks are free."""
    cap = 5
    fake.mode("hang", secs=120, args=["--timeout", str(cap)])
    script = tmp_path / "collector.py"
    script.write_text(COLLECTOR)
    col = subprocess.Popen([sys.executable, str(script), str(HOOKS / "stack_usage.py"), str(fake.py)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids = []
    try:
        pids = _wait_pids(fake)
        t0 = time.monotonic()
        col.kill()
        col.wait(10)
        assert _gone(pids[0], 0.3) is False
        with U.Locked(str(st / "usage" / "bayes.lock"), nb=True) as lk:
            assert not lk.ok
        assert U.flock_held(U.accel_lock_path())
        assert _gone(pids[0], cap + 10), "the orphaned fit outlived its own cap"
        assert time.monotonic() - t0 < cap + 10
    finally:
        col.kill()
        _reap(pids)
    with U.Locked(str(st / "usage" / "bayes.lock"), nb=True) as lk:
        assert lk.ok
    assert not U.flock_held(U.accel_lock_path())


def test_only_the_fitters_summary_line_is_kept(st, fake):
    fake.mode("ok", lines=["row data: session abc task secret", "bayes: fit " + "x" * 400, "bayes: fit good 1",
                           "trailing \x1b[31m noise"])
    r = U.bayes_fit("idle", now=1e9)
    assert r["summary"] == "bayes: fit good 1"
    fake.mode("ok", lines=["no summary"])
    write_props(st, EID2)
    assert U.bayes_fit("idle", now=1e9, force=True)["summary"] is None


def test_the_record_is_capped_and_bad_lines_are_dropped(st, fake, monkeypatch):
    lines = [json.dumps({"ts": i, "status": "skipped:rate", "evidence_id": EID2}) for i in range(450)]
    (st / "usage" / "bayes.json.rec").write_text("\n".join(lines[:200] + ["{not json", "[1]"] + lines[200:]) + "\n")
    U.bayes_fit("idle", now=1e9)
    rs = recs(st)
    assert len(rs) == U.BAYES_REC_MAX and rs[-1]["status"] == "ok" and all(isinstance(r, dict) for r in rs)
    monkeypatch.setattr(U, "BAYES_REC_BYTES", 300)
    assert all(isinstance(r, dict) for r in U.read_bayes_recs())


def test_never_raises(st, fake, monkeypatch):
    monkeypatch.setattr(U, "_bayes_run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    assert U.bayes_fit("idle")["status"] == "failed:RuntimeError"


def test_status_line_names_the_last_fit(st, fake):
    U.bayes_fit("idle", now=1e9)
    assert U.status_line().endswith("last bayes fit: ok")


def test_collector_exit_order_propose_bayes_refresh(st, tmp_path, monkeypatch):
    order = []
    sid = "s-order"
    sub = tmp_path / "proj" / sid / "subagents"
    sub.mkdir(parents=True)
    Path(U.session_dir(sid), "end").write_text("1\n")
    monkeypatch.setattr(U, "scan_once", lambda *a, **k: order.append("scan") or ([], False))
    monkeypatch.setattr(U, "propose_limits", lambda: order.append("propose"))
    monkeypatch.setattr(U, "bayes_fit", lambda **k: order.append(("bayes", k)))
    monkeypatch.setattr(U, "refresh", lambda **k: order.append("refresh"))
    old = signal.getsignal(signal.SIGTERM)
    try:
        assert U.run(sid, str(sub), poll=0.01) == "session end"
    finally:
        signal.signal(signal.SIGTERM, old)
    assert order == ["scan", "propose", ("bayes", {"trigger": "session end"}), "refresh"]


def test_install_stages_stack_bayes():
    """install.sh stages hooks/stack_bayes.py (644, beside stack_limits.py, which it imports) and tracks it in the
    manifest (STACK_SCRIPTS); bayes_fit runs it by path from the hooks folder."""
    inst = (ROOT / "install.sh").read_text(encoding="utf-8")
    loops = [ln for ln in inst.splitlines() if ln.startswith("for f in ") and 'stage_script 644 "hooks/$f"' in ln]
    assert any(" stack_bayes.py " in " %s " % ln.split(";", 1)[0] for ln in loops), loops
    assert '"hooks/stack_bayes.py"' in inst.split("STACK_SCRIPTS = [", 1)[1].split("]", 1)[0]


def test_the_bayes_lock_covers_the_fitters_imports():
    """requirements/tools-bayes.in (the opt-in lock's input, `-r tools.in`) names every third-party import of
    stack_bayes.py; tools.in itself stays free of them (requirements/README.md: extras get their own lock)."""
    import ast
    req = ROOT / "requirements"
    names = lambda t: {ln.split("=")[0].split("<")[0].split(">")[0].strip().lower()  # noqa: E731
                       for ln in t.splitlines() if ln.strip() and not ln.lstrip().startswith(("#", "-"))}
    extra, base = names((req / "tools-bayes.in").read_text()), names((req / "tools.in").read_text())
    assert "-r tools.in" in (req / "tools-bayes.in").read_text()
    need = set()
    for n in ast.walk(ast.parse((HOOKS / "stack_bayes.py").read_text())):
        mods = [a.name for a in n.names] if isinstance(n, ast.Import) else \
            [n.module] if isinstance(n, ast.ImportFrom) and n.level == 0 and n.module else []
        need |= {m.split(".")[0] for m in mods}
    local = {p.stem for p in HOOKS.glob("*.py")}
    third = {m for m in need if m not in sys.stdlib_module_names and m not in local}
    assert third <= extra | base, third - extra - base
    assert set(B.DEPS) <= extra | base and {"pymc", "nutpie", "arviz", "pytensor", "scipy"} <= extra - base


# ---------------------------------------------------------------- the fitter's numeric core (numpy only)
def ar1(rng, chains, draws, phi, size=None):
    """(chains, draws) AR(1) chains with stationary N(0, 1) marginals."""
    shp = (chains,) if size is None else (chains, size)
    x = np.empty((draws,) + shp)
    x[0] = rng.standard_normal(shp)
    s = math.sqrt(1 - phi * phi)
    for i in range(1, draws):
        x[i] = phi * x[i - 1] + s * rng.standard_normal(shp)
    return np.moveaxis(x, 0, 1)


def test_ess_and_mcse_of_the_mean():
    rng = np.random.default_rng(1)
    x = rng.standard_normal((4, 4000))
    assert abs(B.ess_of(B.split_chains(x)) / x.size - 1) < 0.1
    assert abs(B.mcse_mean(x) / (np.std(x, ddof=1) / math.sqrt(x.size)) - 1) < 0.06
    phi = 0.9
    y = ar1(rng, 4, 8000, phi)
    assert abs(B.ess_of(B.split_chains(y)) / (y.size * (1 - phi) / (1 + phi)) - 1) < 0.2
    assert B.mcse_mean(np.full((4, 100), 3.0)) == 0.0


def test_ess_matches_arviz_when_present():
    az = pytest.importorskip("arviz")
    rng = np.random.default_rng(2)
    for x in (rng.standard_normal((4, 1000)), ar1(rng, 8, 1500, 0.7)):
        assert B.ess_of(B.split_chains(x)) == pytest.approx(float(az.ess(x, method="mean")), rel=1e-9)
        assert B.mcse_mean(x) == pytest.approx(float(az.mcse(x, method="mean")), rel=1e-9)


def _nb_posterior(rng, chains, draws, phi):
    """A fake turns posterior with autocorrelated draws: eta ~ log 12 + 0.3 z, alpha ~ exp(0.5 + 0.2 z)."""
    e = math.log(12.0) + 0.3 * ar1(rng, chains, draws, phi)
    a = np.exp(0.5 + 0.2 * ar1(rng, chains, draws, phi))
    return e, a


def test_delta_mcse_of_a_turns_quantile_is_calibrated_by_replication():
    """The MCSE estimator (WP2 finding b): over R independent replicate posteriors with autocorrelated chains, the
    spread of T_raw (the 0.98 quantile) matches the mean predicted MCSE. An iid formula (no ESS) would predict about
    (1 - phi) / (1 + phi) of the variance; batch means over 20 batches move by ~16 % between two runs."""
    rng = np.random.default_rng(3)
    p, phi, R = 0.98, 0.8, 120
    Ts, ses = [], []
    for _ in range(R):
        e, a = _nb_posterior(rng, 4, 600, phi)
        P = B.PredNB(e, a, np.full(e.shape, 0.2), np.full(e.shape, -0.3), 0.3, e.shape)
        sw = P.sweep((p,), (p,), 2000)
        _q, t_raw, _pmf = B.PredNB.quantile_of(sw["mix"][p], p)
        Ts.append(t_raw)
        ses.append(P.mcse_rel(sw["mix"][p], p) * t_raw)
    ratio = float(np.std(Ts, ddof=1) / np.mean(ses))
    assert 0.75 < ratio < 1.33, ratio


def test_delta_mcse_of_a_ctx_quantile_is_calibrated_by_replication():
    rng = np.random.default_rng(4)
    p, phi, R = 0.9, 0.8, 60
    Ts, ses = [], []
    for _ in range(R):
        e = math.log(2e6) + 0.6 * ar1(rng, 4, 400, phi)
        sd = np.exp(0.2 + 0.1 * ar1(rng, 4, 400, phi))
        P = B.PredLN(e, sd, np.full(e.shape, -0.2), 0.3, e.shape)
        (T,) = P.quantiles((p,))
        Ts.append(math.log(T))
        ses.append(P.mcse_rel(T))
    ratio = float(np.std(Ts, ddof=1) / np.mean(ses))
    assert 0.75 < ratio < 1.33, ratio


def _nb_cdf_direct(k, mu, a):
    """P(Y - 1 <= k) of NB2(mu, a) by direct summation with lgamma (an independent route)."""
    s = 0.0
    for j in range(k + 1):
        s += math.exp(math.lgamma(j + a) - math.lgamma(a) - math.lgamma(j + 1) + a * math.log(a / (a + mu))
                      + j * math.log(mu / (a + mu)))
    return s


def test_turns_sweep_equals_direct_summation_with_retirement():
    from stack_bayes_grid import GH_W, GH_X
    rng = np.random.default_rng(5)
    e = np.concatenate([np.log([0.05, 0.2]), np.log(rng.uniform(3, 40, 10))])   # two draws retire at once
    a = rng.uniform(0.6, 5.0, e.size)
    tn, rr, pr = rng.uniform(0.0, 0.5, e.size), rng.uniform(-0.5, 0.5, e.size), 0.25
    P = B.PredNB(e, a, tn, rr, pr, (2, e.size // 2))

    def Fd(d, k):
        tot = 0.0
        for r_, w_r in ((0.0, 1 - pr), (rr[d], pr)):
            for x, w in zip(GH_X, GH_W):
                tot += w_r * w * _nb_cdf_direct(k, math.exp(e[d] + r_ + tn[d] * x), a[d])
        return tot
    ps = (0.25, 0.5, 0.9, 0.98)
    sw = P.sweep(ps, (0.5, 0.98), 400)
    for p in ps:
        k = sw["mix"][p][0]
        assert sum(Fd(d, k) for d in range(e.size)) / e.size >= p - 1e-12
        assert k == 0 or sum(Fd(d, k - 1) for d in range(e.size)) / e.size < p + 1e-12
        assert sw["mix"][p][2] == pytest.approx(sum(Fd(d, k) for d in range(e.size)) / e.size, abs=1e-9)
    for p in (0.5, 0.98):
        for d in range(e.size):
            k = int(sw["draw"][p][d])
            assert Fd(d, k) >= p - 1e-12 and (k == 0 or Fd(d, k - 1) < p + 1e-12)
    # beyond the sweep's end: not found, reported as kcap + 1
    sw = P.sweep((0.999,), (0.999,), 3)
    assert sw["mix"][0.999] is None and (sw["draw"][0.999] == 4).any()


def test_ln_quantiles_invert_the_mixture_cdf():
    rng = np.random.default_rng(6)
    e, sd = rng.normal(14, 1, 50), rng.uniform(0.5, 1.5, 50)
    P = B.PredLN(e, sd, np.full(50, -0.4), 0.3, (5, 10))
    ps = (0.5, 0.9, 0.99)
    for p, q in zip(ps, P.quantiles(ps)):
        assert float(P.Fd(math.log(q)).mean()) == pytest.approx(p, abs=1e-9)
    qd = P.draw_quantile(0.9).ravel()
    assert np.allclose(P.Fd(np.log(qd)), 0.9, atol=1e-9)


# ---------------------------------------------------------------- blocks: the clamp at the cap (WP2 finding a)
def _block(**kw):
    qd = {"rhat": 1.002, "ess_bulk": 1800.0, "ess_tail": 1500.0}
    args = dict(fam="soft.agent", model_id="ctx-ln-h4", T=3.4e8, T_raw=3.3e8, pi90=[5e7, 1.7e10],
                qx=[7e6, 8e7, 3.3e8, 1e9, 2.7e9, 8.9e9, 2.4e10, 9.9e10], at_bound=False,
                counts={"n": 10, "n_cens": 3, "agents": 6, "sessions": 3}, shrink=0.2, status="pooled", qd_diag=qd,
                mcse_rel=0.01, cap=L.CTX_MAX)
    args.update(kw)
    return B.make_block(**args)


def _doc_with(blk, var="soft.agent.coder"):
    d = bayes_doc({"ctx-ln-h4": GOOD_MODEL})
    d["vars"] = {var: blk}
    return d


def test_values_past_the_cap_are_clamped_with_at_bound_and_the_reader_takes_them():
    blk = _block()
    assert blk["at_bound"] is True and max(blk["pi90"] + blk["qtab"]["x"] + [blk["T"], blk["T_raw"]]) == L.CTX_MAX
    assert blk["qtab"]["x"] == sorted(blk["qtab"]["x"]) and min(blk["qtab"]["x"]) > 0
    L._bayes_doc_checked(_doc_with(blk), SEED)
    assert B.self_check(_doc_with(blk), SEED, EID) is None
    acc = L.load_bayes(SEED, EID, _doc_with(blk))
    assert set(acc) == {"soft.agent.coder"} and acc["soft.agent.coder"]["at_bound"] is True
    # within the cap: nothing clamped, at_bound as given
    ok = _block(pi90=[5e7, 9e8], qx=[7e6, 8e7, 3.3e8, 1e9, 2.7e9, 4e9, 5e9, 6e9])
    assert ok["at_bound"] is False and ok["pi90"] == [5e7, 9e8]


def test_the_reader_refuses_a_value_at_the_cap_without_at_bound():
    """The validator half of the rule (docs/BAYES.md 2.1 rule 4): a block value at CTX_MAX / TURNS_MAX with
    at_bound false drops the whole file."""
    blk = _block()
    blk["at_bound"] = False
    with pytest.raises(L._BayesInvalid):
        L._bayes_doc_checked(_doc_with(blk), SEED)
    assert L.load_bayes(SEED, EID, _doc_with(blk)) is None
    assert B.self_check(_doc_with(blk), SEED, EID) is not None
    t = _block(fam="turns", model_id="turns-nb2s-h4", T=40, T_raw=39.2, pi90=[30.0, L.TURNS_MAX],
               qx=[10, 20, 30, 35, 39, 45, 50, 60], cap=L.TURNS_MAX)
    assert t["at_bound"] is True                               # reaching the cap is enough (the reader's rule)
    L._bayes_doc_checked(_doc_with(t, "turns.coder"), SEED)
    t["at_bound"] = False
    with pytest.raises(L._BayesInvalid):
        L._bayes_doc_checked(_doc_with(t, "turns.coder"), SEED)


def test_a_soft_T_rounded_up_to_the_cap_is_flagged_and_the_fit_is_written():
    """Reviews (code item 3, security F1): soft T = ceil2(T_raw) rounds T_raw in (9.9e9, 1e10) up to exactly
    CTX_MAX; the writer must flag it, or self_check refuses the whole document (and that evidence is never
    retried)."""
    blk = _block(T=L.ceil2(9.95e9), T_raw=9.95e9, pi90=[5e7, 9e9],
                 qx=[7e6, 8e7, 3.3e8, 1e9, 2.7e9, 4e9, 5e9, 9.95e9])
    assert blk["T"] == L.CTX_MAX and blk["at_bound"] is True
    assert B.self_check(_doc_with(blk), SEED, EID) is None


class _FakeGrid:
    @staticmethod
    def lognormal_post(obs, cens, mu, tau, sig, oo, oc):
        return [0.0], [1.0], {"edge_mass": 0.0}

    @staticmethod
    def lognormal_quantile(etas, w, p, sig, tnew, rho, pres):
        return (math.log(9.95e9) if p >= 0.9 else math.log(1e9)), (math.log(1e9), math.log(9.95e9))


def test_a_grid_block_rounded_up_to_the_cap_is_kept_and_flagged(monkeypatch):
    """The stdlib grid tier (stack_limits.bayes_grid_block) has the same rounding: its T at CTX_MAX is kept with
    at_bound true, not dropped by _valid_block."""
    monkeypatch.setattr(L, "_grid_mod", lambda: _FakeGrid)
    hyper = {"ctx": {"types": {"coder": {"mu": 20.0, "scale": 1.0}}, "rho": 0.0, "tau_t": 1.0, "tau_new": 0.5,
                     "p_resume": 0.0}, "breach": []}
    entry = {"b": {"y": [1e9], "cens": [0], "resume": [0], "sess": ["s1"]}, "n": 1, "agents": 1, "ci": [1e9, 1e9],
             "x": [1e9], "sessions": 1}
    blk = L.bayes_grid_block(entry, hyper, "soft.agent.coder", SEED["vars"]["soft.agent.coder"])
    assert blk is not None and blk["T"] == L.CTX_MAX and blk["at_bound"] is True
    entry["b"]["y"] = [1e6]                              # well inside the cap: not flagged
    monkeypatch.setattr(_FakeGrid, "lognormal_quantile",
                        staticmethod(lambda *a: (math.log(2e6), (math.log(1e6), math.log(3e6)))))
    blk = L.bayes_grid_block(entry, hyper, "soft.agent.coder", SEED["vars"]["soft.agent.coder"])
    assert blk is not None and blk["at_bound"] is False


def test_a_turns_block_past_its_sweep_has_no_mcse_and_fails_the_quantity_gate():
    blk = _block(fam="turns", model_id="turns-nb2s-h4", T=681, T_raw=681.0, pi90=[400.0, 681.0],
                 qx=[85, 342, 677, 681, 681, 681, 681, 681], at_bound=True, mcse_rel=None, cap=681.0)
    assert blk["diag"]["mcse_rel"] is None and blk["at_bound"] is True
    assert not L.quantity_gate(blk["diag"])
    d = bayes_doc({"turns-nb2s-h4": GOOD_MODEL})
    d["vars"] = {"turns.coder": blk}
    assert L.load_bayes(SEED, EID, d) == {}


# ---------------------------------------------------------------- the sched block (docs/BAYES.md 2.2)
def _sched_entry(typed=True):
    rng = np.random.default_rng(7)
    shp = (4, 300)
    e, a = math.log(15.0) + 0.2 * rng.standard_normal(shp), np.exp(0.6 + 0.1 * rng.standard_normal(shp))
    sw = B.PredNB(e, a, np.full(shp, 0.2), np.full(shp, -0.2), 0.3, shp).sweep((0.25, 0.5, 0.9), (0.5,), 600)
    spc = B.PredLN(math.log(12) + 0.1 * rng.standard_normal(shp), np.full(shp, 0.5), None, 0.0, shp)
    stc = B.PredLN(math.log(2e4) + 0.1 * rng.standard_normal(shp), np.full(shp, 0.3), None, 0.0, shp)
    ab = B._ab_draws(math.log(3e4) + 0.1 * rng.standard_normal(shp), -2 + 0.2 * rng.standard_normal(shp), 20.0)
    return B.sched_entry(sw, spc, stc, ab, {"n_seg": 12, "n_agents": 5, "n_first": 9}, typed)


def test_sched_entries_are_valid_and_hostile_ones_are_refused():
    e = _sched_entry()
    assert e is not None and B.sched_entry_ok(e, True) and e["status"] == "supported"
    assert e["turns"]["S"] <= e["turns"]["M"] <= e["turns"]["L"] and e["band"]["n_ref"] == e["turns"]["M"]
    assert e["band"]["ctx"]["med"] == 1.0 and e["band"]["method"] == "bayes"
    p = _sched_entry(typed=False)
    assert "status" not in p and B.sched_entry_ok(p, False)
    for path, val in ((("turns", "S"), 10 ** 6), (("band", "turns", "lo"), 10 ** 6), (("ctx", "a"), float("nan")),
                      (("static_cc",), 0), (("band", "method"), "combined"), (("n_seg",), 1.5),
                      (("sec_per_call", "p50"), 10 ** 6), (("status",), "pooled")):
        bad = json.loads(json.dumps(e))
        d = bad
        for k in path[:-1]:
            d = d[k]
        d[path[-1]] = val
        assert not B.sched_entry_ok(bad, True), path


def test_the_sched_block_passes_the_schedulers_reader_when_it_has_one(tmp_path):
    """WP4's stack_sched_refresh.load_bayes_sched (bayes/4) reads what this file writes; skipped on a tree without
    it (the two branches merge separately)."""
    pytest.importorskip("pandas")
    SR = _load("stack_sched_refresh_wp3b", HOOKS / "stack_sched_refresh.py")
    if not hasattr(SR, "_sched_checked"):
        pytest.skip("stack_sched_refresh has no load_bayes_sched (WP4 not merged)")
    t = sorted(L._types(SEED))[0]
    pool = sorted(SEED["pools"])[0]
    # passing diag for the four source models: WP4 recomputes the sched model gate from models.<id>.diag
    doc = bayes_doc({m: PASS_MODEL for m in ("turns-nb2s-h4", "spc-ln-h4", "ctx_ab-kq-h2", "static_cc-ln-h2")})
    doc["sched"] ={"model_gate": {"turns": True, "spc": True, "ctx_ab": True, "static_cc": True},
                    "types": {t: _sched_entry()}, "pools": {pool: _sched_entry(False)}}
    out = SR._sched_checked(json.loads(json.dumps(doc)), EID, SEED["sha"], SEED)
    assert out and t in out["types"] and pool in out["pools"]


def test_self_check_refuses_what_the_reader_would_drop():
    d = bayes_doc()
    assert B.self_check(d, SEED, EID) is None
    assert B.self_check(d, SEED, EID2) == "evidence_id"
    bad = dict(d, vars={"STACK_MAX_FANOUT": {}})
    assert B.self_check(bad, SEED, EID)
    bad = dict(d, vars={"soft.agent.no-such-type-xyz": {}})
    assert "unknown variable" in B.self_check(bad, SEED, EID)
    e = _sched_entry()
    e["turns"]["S"] = e["turns"]["L"] + 1
    bad = dict(d, sched={"model_gate": {}, "types": {sorted(L._types(SEED))[0]: e}, "pools": {}})
    assert B.self_check(bad, SEED, EID).startswith("sched types")


def test_sampler_defaults():
    """docs/BAYES.md 1.3: nutpie, 8 chains x 4000 draws after 2000 tuning, target_accept 0.98, seed 20261003."""
    assert (B.CHAINS, B.DRAWS, B.TUNE, B.TARGET_ACCEPT, B.SEED) == (8, 4000, 2000, 0.98, 20261003)


# ---------------------------------------------------------------- assemble(): the post-sampling part of fit()
class _A:
    """A posterior variable as fit() sees it in an xarray Dataset: `.values` shaped (chain, draw[, k])."""

    def __init__(self, v):
        self.values = np.asarray(v, float)
        self.shape = self.values.shape


def _hier_post(rng, ix, shp, eta, log_scale, kind, sess=True, rho=True, regime=False):
    nt = len(ix.types)
    z = lambda *k: 0.05 * rng.standard_normal(shp + k)  # noqa: E731
    p = {"a0": float(np.mean(eta)) + z(), "b_fam": z(len(ix.fams)), "g": 0.5 + z(), "u_p": z(len(ix.peff)),
         "tau_t": 0.5 + np.abs(z()), "eta_type": eta + z(nt)}
    ls = "log_alpha" if kind == "nb" else "log_sigma"
    p[ls + "_t"] = log_scale + z(nt)
    p[ls] = float(np.mean(log_scale)) + z(len(ix.pools))
    if sess:
        p["tau_s"], p["tau_ts"] = 0.1 + np.abs(z()), 0.1 + np.abs(z())
    if rho:
        p["rho"] = -0.2 + z()
    if regime:
        p["tau_g"], p["z_g"] = 0.2 + np.abs(z()), z(len(ix.regimes))
    return {k: _A(v) for k, v in p.items()}


def _synthetic_fit(rng):
    ix = B.Index(SEED, {}, ["s1", "s2"], ["r1", "r2"])
    nt, shp = len(ix.types), (2, 50)
    t_eta = np.full(nt, math.log(8.0))
    t_eta[0] = math.log(1e4)                         # type 0: turns beyond its sweep -> at_bound, mcse null
    c_eta = np.full(nt, math.log(1e6))
    c_eta[0] = math.log(5e9)                         # type 0: ctx predictive past CTX_MAX -> clamped
    c_ls = np.where(np.arange(nt) % 2 == 0, math.log(0.3), math.log(1.3))   # narrow: 2 x soft T binds hard.agent
    posts = {"turns": _hier_post(rng, ix, shp, t_eta, np.full(nt, math.log(2.0)), "nb", regime=True),
             "ctx": _hier_post(rng, ix, shp, c_eta, c_ls, "ln"),
             "spc": _hier_post(rng, ix, shp, np.full(nt, math.log(12.0)), np.full(nt, math.log(0.5)), "ln"),
             "static_cc": _hier_post(rng, ix, shp, np.full(nt, math.log(2e4)), np.full(nt, math.log(0.3)), "ln",
                                     sess=False, rho=False)}
    z = lambda *k: 0.05 * rng.standard_normal(shp + k)  # noqa: E731
    posts["ctx_ab"] = {k: _A(v) for k, v in {
        "k_t": math.log(3e4) + z(nt), "q_t": -2.0 + z(nt), "u_pk": z(len(ix.peff)), "u_pq": z(len(ix.peff)),
        "K0": math.log(3e4) + z(), "Q0": -2.0 + z(), "tau_tk": 0.1 + np.abs(z()), "tau_tq": 0.1 + np.abs(z())}.items()}
    posts["resume_ctx"] = {"alpha": _A(2.0 + np.abs(z())), "gamma": _A(0.1 + np.abs(z()))}
    builders = [t for t in ix.types if ix.pool_of[t] == "builder"][:3]
    recs = []
    for t in list(ix.types[1:6]) + builders:
        for i in range(6):
            recs.append({"session": "s%d" % (1 + i % 2), "id": "%s-%d" % (t, i), "seg": int(i == 5), "type": t,
                         "status": "complete", "cens_turns": False, "cens_ctx": False, "cens": False,
                         "api_calls": 10.0, "ctx": 1e6, "ctx_at_first_write": 3e5, "first_ctx": 1e5})
    frames = {"turns": recs, "ctx": recs}
    gates = {B.MODEL_ID[k]: True for k in ("turns", "ctx", "spc", "static_cc", "ctx_ab", "resume_ctx")}
    qd = lambda q: {"rhat": 1.0, "ess_bulk": float(np.size(q)), "ess_tail": float(np.size(q))}  # noqa: E731
    out = B.assemble(posts, frames, ix, SEED, "r1", 0.2, rng, {"vars": {}, "pools": {}}, 20.0, gates, recs, True,
                     qd_fn=qd)
    return ix, gates, out


def test_assemble_builds_blocks_hyper_and_sched_the_reader_takes():
    """Code review item 2: fit()'s post-sampling (blocks, the hard.agent 2 x soft binding, the turns sweep and
    its at_bound, hyper_of, regime_terms, type and pool sched entries) on synthetic posteriors, numpy only."""
    ix, gates, (hyper, vars_, sched, notes) = _synthetic_fit(np.random.default_rng(11))
    assert notes == {"turns": "seen", "ctx": "only"}
    assert set(hyper) == {"turns", "ctx"} and set(hyper["ctx"]["types"]) == set(ix.types)
    doc = json.loads(json.dumps(dict(bayes_doc({m: PASS_MODEL for m in gates}), hyper=hyper, vars=vars_,
                                     sched=sched)))
    for v, blk in doc["vars"].items():
        L._norm_block(blk, SEED["vars"][v]["unit"])
    assert B.self_check(doc, SEED, EID) is None
    binding = free = 0
    for t in ix.types:
        soft, hard = doc["vars"].get("soft.agent." + t), doc["vars"].get("hard.agent." + t)
        if not soft or not hard or soft["at_bound"]:
            continue
        q99 = hard["qtab"]["x"][list(L.QTAB_P).index(0.99)]
        assert hard["T"] == L.hard_agent_T(q99, soft["T"])[0], t
        if L.HARD_OVER_SOFT * soft["T"] > q99:
            binding += 1
            assert hard["T_raw"] == L.HARD_OVER_SOFT * soft["T"]
            assert hard["diag"]["mcse_rel"] == soft["diag"]["mcse_rel"]
        else:
            free += 1
            assert hard["T_raw"] == pytest.approx(q99)
    assert binding and free
    t0 = ix.types[0]
    s0 = doc["vars"]["soft.agent." + t0]                 # its upper predictive quantiles pass CTX_MAX
    assert s0["at_bound"] is True and s0["qtab"]["x"][-1] == L.CTX_MAX and s0["T"] < L.CTX_MAX
    tb = doc["vars"]["turns." + t0]
    assert tb["at_bound"] is True and tb["diag"]["mcse_rel"] is None and not L.quantity_gate(tb["diag"])
    ok = doc["vars"]["turns." + ix.types[1]]
    assert ok["at_bound"] is False and ok["diag"]["mcse_rel"] is not None and ok["qtab"]["x"] == sorted(ok["qtab"]["x"])
    assert sched["types"] and sched["pools"] and "fixer" in sched and "resume_ctx" in sched
    assert sched["model_gate"] == {"turns": True, "spc": True, "ctx_ab": True, "static_cc": True}
    assert all(B.sched_entry_ok(e, True) for e in sched["types"].values())
    assert all(B.sched_entry_ok(e, False) for e in sched["pools"].values())


# ---------------------------------------------------------------- B1-T11: two real fits (opt-in)
FIT_PY = os.environ.get("STACK_BAYES_FIT_PYTHON")


@pytest.mark.skipif(not FIT_PY, reason="set STACK_BAYES_FIT_PYTHON to an interpreter with the Bayes lock")
def test_B1_T11_same_data_and_seed_give_the_same_fit(tmp_path):
    """B1-T11: two fits of the frozen fixture with one seed, in two processes. Identical apart from `generated`
    for the scheduler models (spc, static_cc, ctx_ab: their diagnostics and the sched block); turns and ctx are
    not bit-reproducible across processes in v2 (section 2): each block's T within 5 combined MCSEs, the model
    gates equal. On 2026-10-09 (WP2's environment, one machine) the two files were identical apart from
    `generated` (worst 0.00 MCSEs); the tolerance stays for other machines and builds (docs/BAYES.md H). The
    gate never relies on bit reproducibility."""
    docs = []
    for i in range(2):
        root = tmp_path / ("x%d" % i) / "claude-agent-stack"
        (root / "usage").mkdir(parents=True)
        (root / "limits").mkdir(parents=True)
        for n in ("runs.csv", "runs3.csv"):
            shutil.copy(FIX / n, root / "usage" / n)
        for n in ("live.json", "proposals.json"):
            shutil.copy(FIX / "state" / n, root / "limits" / n)
        env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / ("x%d" % i)))
        out = tmp_path / ("b%d.json" % i)
        p = subprocess.run([FIT_PY, "-I", str(HOOKS / "stack_bayes.py"), "fit", "--out", str(out),
                            "--chains", "4", "--draws", "1000", "--tune", "1000"], env=env, capture_output=True,
                           text=True, timeout=1800)
        assert p.returncode == 0, p.stdout[-2000:] + p.stderr[-2000:]
        docs.append(json.loads(out.read_text()))
    a, b = docs
    for k in ("evidence_id", "seed_sha", "fit_id", "risk", "sampler", "versions", "data"):
        assert a[k] == b[k], k
    # drift (A.12) comes from the turns/ctx posteriors, which need not be bit-reproducible: same entries and
    # sessions, ks_p within 0.05, the same breach unless a p lies within 0.005 of the 0.01 threshold
    assert set(a["drift"]) == set(b["drift"])
    for f, x in a["drift"].items():
        y = b["drift"][f]
        assert x["sessions"] == y["sessions"] and abs(x["ks_p"] - y["ks_p"]) <= 0.05, (f, x, y)
        if min(abs(x["ks_p"] - B.DRIFT_ALPHA), abs(y["ks_p"] - B.DRIFT_ALPHA)) > 0.005:
            assert x["breach"] == y["breach"], (f, x, y)
    for m in ("spc-ln-h4", "static_cc-ln-h2", "ctx_ab-kq-h2"):
        assert a["models"][m] == b["models"][m], m
    assert a["sched"] == b["sched"]
    assert {k: v["gate"] for k, v in a["models"].items()} == {k: v["gate"] for k, v in b["models"].items()}
    worst = 0.0
    for v, x in a["vars"].items():
        y = b["vars"][v]
        if x["at_bound"] or y["at_bound"] or x["diag"]["mcse_rel"] is None or y["diag"]["mcse_rel"] is None:
            continue
        z = abs(math.log(x["T_raw"] / y["T_raw"])) / math.hypot(x["diag"]["mcse_rel"], y["diag"]["mcse_rel"])
        worst = max(worst, z)
        assert z <= 5.0, (v, x["T_raw"], y["T_raw"])
    print("B1-T11 worst |log T1/T2| / combined MCSE: %.2f" % worst)


# ---------------------------------------------------------------- the drift check (WP5 5c; BAYES.md 2.1 rule 7, A.12)
DTYPES = 3                                   # synthetic rows use the first three seed types


def _drift_post(ix, kind, eta, log_scale, tau_s, tau_ts, rho=-0.2, shp=(2, 60), jitter=0.02, seed=0):
    """A synthetic turns ("nb") or ctx ("ln") posterior around known values (no NUTS): eta and log scale per
    type, the session and session x type effects' scales, the resume offset rho."""
    rng = np.random.default_rng(seed)
    nt = len(ix.types)
    def z(*k):
        return jitter * rng.standard_normal(shp + k)
    p = {"a0": np.full(shp, float(np.mean(eta))) + z(), "eta_type": np.asarray(eta, float) + z(nt),
         ("log_alpha_t" if kind == "nb" else "log_sigma_t"): np.asarray(log_scale, float) + z(nt),
         "tau_s": np.full(shp, tau_s), "tau_ts": np.full(shp, tau_ts), "rho": np.full(shp, rho) + z()}
    return {k: _A(v) for k, v in p.items()}


def _drift_world(kind, n_sess=5, rows_per=14, shift=0.0, shifted=None, tau_s=0.3, tau_ts=0.15, sigma=0.6,
                 alpha=3.0, cens_rate=0.25, seed=0, censor=True):
    """(ix, posterior, frame): sessions s00.. drawn from the model the posterior describes; the sessions in
    `shifted` (default: all) have their log location moved by `shift` (drift). Censoring is random: a limit
    drawn independently of y, a row at or past it is censored at the limit (A.3's shape)."""
    rng = np.random.default_rng(seed)
    sess = [f"s{i:02d}" for i in range(n_sess)]
    ix = B.Index(SEED, {}, sess, ["none"])
    nt = len(ix.types)
    base = np.log(np.linspace(8.0, 20.0, DTYPES)) if kind == "nb" else np.log(np.linspace(4e5, 2e6, DTYPES))
    eta = np.full(nt, float(base.mean()))
    eta[:DTYPES] = base
    log_scale = np.full(nt, math.log(alpha if kind == "nb" else sigma))
    post = _drift_post(ix, kind, eta, log_scale, tau_s, tau_ts, seed=seed + 1)
    shifted = set(range(n_sess)) if shifted is None else set(shifted)
    frame = []
    for si, s in enumerate(sess):
        u = tau_s * rng.standard_normal()
        v = tau_ts * rng.standard_normal(DTYPES)
        for i in range(rows_per):
            j = rng.integers(0, DTYPES)
            res = int(rng.random() < 0.2)
            loc = eta[j] - 0.2 * res + u + v[j] + (shift if si in shifted else 0.0)
            if kind == "nb":
                y = 1 + int(rng.poisson(rng.gamma(alpha, math.exp(loc) / alpha)))
                lim = math.ceil(math.exp(eta[j] + 0.9 + 0.5 * rng.standard_normal()))
                cens = censor and rng.random() < cens_rate * 3 and y >= lim
            else:
                y = math.exp(loc + sigma * rng.standard_normal())
                lim = math.exp(eta[j] + 0.6 + 0.5 * rng.standard_normal())
                cens = censor and rng.random() < cens_rate * 3 and y >= lim
            rec = {"session": s, "id": f"{s}-a{i}", "seg": res, "type": ix.types[j], "ts": 1e9 + 1e4 * si + i,
                   "resume": res, "regime": "none", "cens": bool(cens)}
            q = (lim if cens else y)
            rec["api_calls" if kind == "nb" else "ctx"] = float(q)
            frame.append(rec)
    return ix, post, frame


def _drift(kind, seed=0, **kw):
    ix, post, frame = _drift_world(kind, seed=seed, **kw)
    return B.drift_check(post, kind, ix, frame, (B.SEED, B.DRIFT_STREAM, seed))


@pytest.mark.parametrize("kind", ["ln", "nb"])
def test_stationary_sessions_do_not_breach(kind):
    """A.12: rows drawn from the posterior's own predictive (session effects included) give breach false in
    every seed, with an entry of exactly {ks_p, sessions, breach} over the last 5 sessions."""
    for seed in range(4):
        e, st = _drift(kind, seed=seed)
        assert e is not None and set(e) == {"ks_p", "sessions", "breach"}, st
        assert e["breach"] is False and e["ks_p"] >= B.DRIFT_ALPHA and e["sessions"] == 5, (seed, e, st)
        assert 1 / (B.DRIFT_B + 1) <= e["ks_p"] <= 1 and st["n"] == 70 and 0 < st["n_cens"] < 35


@pytest.mark.parametrize("kind,shift", [("ln", 2.0), ("ln", -2.0), ("nb", 1.5), ("nb", -1.5)])
def test_drifted_sessions_breach(kind, shift):
    """Mutants "breach never set" and "KS direction flipped": the last sessions' location moved up or down
    (drift in either tail) against the posterior give ks_p < 0.01 and breach true."""
    for seed in range(2):
        e, st = _drift(kind, seed=seed, shift=shift)
        assert e is not None and e["breach"] is True and e["ks_p"] < B.DRIFT_ALPHA, (seed, e, st)
        assert e["ks_p"] == pytest.approx(1 / (B.DRIFT_B + 1)), st     # far out: no replicate reaches D


def test_drift_before_the_last_5_sessions_is_outside_the_window():
    """Mutant "window = all sessions": 8 sessions whose first 3 drifted; the check reads the last 5 (by first
    row, not by name), which are stationary."""
    ix, post, frame = _drift_world("ln", n_sess=8, shift=3.0, shifted=(0, 1, 2), seed=3)
    rows, sess = B.drift_rows(frame)
    assert sess == ["s03", "s04", "s05", "s06", "s07"] and {r["session"] for r in rows} == set(sess)
    e, st = B.drift_check(post, "ln", ix, frame, (B.SEED, B.DRIFT_STREAM, 1))
    assert e == dict(e, sessions=5, breach=False) and st["n"] == 5 * 14
    for r in frame:                              # session order is by the first row, not by the session name
        if r["session"] == "s00":
            r["ts"] += 1e6
    _rows, sess = B.drift_rows(frame)
    assert sess == ["s04", "s05", "s06", "s07", "s00"]


def _kolmogorov_p(D, n):
    """The iid (asymptotic) KS p, for comparison only."""
    x = math.sqrt(n) * D
    return min(1.0, max(0.0, 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * x * x) for k in range(1, 101))))


def test_the_p_value_is_session_clustered_not_iid():
    """Mutant "iid KS p": with strong session effects (latent correlation 0.69, above WP2's 0.61) stationary
    sessions do not breach under the clustered p, while the iid p of the same D would flag most of them."""
    breaches, iid = 0, 0
    for seed in range(6):
        e, st = _drift("ln", seed=seed, tau_s=1.2, tau_ts=0.0, sigma=0.8, rows_per=16)
        breaches += e["breach"]
        iid += _kolmogorov_p(st["D"], st["n"]) < B.DRIFT_ALPHA
    assert breaches <= 1 and iid >= 3, (breaches, iid)


def test_under_the_minimum_there_is_no_entry():
    """A.12's minimum (>= 20 rows, >= 10 uncensored, >= 3 sessions): just below each bound, no entry and no
    check; at the bounds, an entry."""
    ix, post, frame = _drift_world("ln", n_sess=5, rows_per=4, seed=5, censor=False)
    def chk(fr):
        return B.drift_check(post, "ln", ix, fr, (B.SEED, B.DRIFT_STREAM, 1))
    e, st = chk(frame)
    assert e is not None and st["n"] == 20                        # 20 rows, 20 uncensored, 5 sessions
    e, st = chk(frame[:19])
    assert e is None and st["D"] is None and st["n"] == 19
    fr = [dict(r, cens=i < 10) for i, r in enumerate(frame)]
    assert chk(fr)[0] is not None                                 # 10 uncensored: enough
    fr = [dict(r, cens=i < 11) for i, r in enumerate(frame)]
    assert chk(fr)[0] is None                                     # 9 uncensored
    three = [r for r in frame if r["session"] in ("s02", "s03", "s04")]
    ix3, post3, fr3 = _drift_world("ln", n_sess=3, rows_per=7, seed=6, censor=False)
    assert B.drift_check(post3, "ln", ix3, fr3, (B.SEED, B.DRIFT_STREAM, 1))[0] is not None   # 21 rows, 3 sessions
    ix2, post2, fr2 = _drift_world("ln", n_sess=2, rows_per=15, seed=6, censor=False)
    assert B.drift_check(post2, "ln", ix2, fr2, (B.SEED, B.DRIFT_STREAM, 1))[0] is None       # 30 rows, 2 sessions
    assert len(three) < 20 and chk(three)[0] is None


def _one_draw_post(ix, kind, eta, log_scale):
    """A posterior of identical draws and no session effect: the predictive F is the closed form."""
    shp = (1, 4)
    nt = len(ix.types)
    p = {"a0": np.zeros(shp), "eta_type": np.broadcast_to(np.full(nt, eta), shp + (nt,)).copy(),
         ("log_alpha_t" if kind == "nb" else "log_sigma_t"): np.broadcast_to(np.full(nt, log_scale),
                                                                              shp + (nt,)).copy()}
    return {k: _A(v) for k, v in p.items()}


def _frame_of(ix, ys, cens, kind, per_sess=10):
    return [{"session": f"s{i // per_sess}", "id": f"a{i}", "seg": 0, "type": ix.types[0], "ts": 1e9 + i,
             "resume": 0, "regime": "none", "cens": bool(c), ("api_calls" if kind == "nb" else "ctx"): float(y)}
            for i, (y, c) in enumerate(zip(ys, cens))]


def test_censored_ln_pits_are_randomized_over_F_y_to_1():
    """Mutant "censored PIT not randomized": a censored log-normal row's PIT is U(F(y), 1) (spread over the
    whole interval), an exact row's is F(y); F in closed form from a one-point posterior."""
    ix = B.Index(SEED, {}, ["s0", "s1", "s2"], ["none"])
    mu, sig = math.log(1e6), 0.5
    post = _one_draw_post(ix, "ln", mu, math.log(sig))
    rng = np.random.default_rng(8)
    ys = np.exp(mu + sig * rng.standard_normal(30))
    cens = np.arange(30) % 2 == 0
    _e, st = B.drift_check(post, "ln", ix, _frame_of(ix, ys, cens, "ln"), (1, 2, 3))
    rows, _ = B.drift_rows(_frame_of(ix, ys, cens, "ln"))
    F = np.array([0.5 * math.erfc(-(math.log(r["ctx"]) - mu) / sig / math.sqrt(2)) for r in rows])
    c = np.array([r["cens"] for r in rows])
    pit = st["pit"]
    assert np.allclose(pit[~c], F[~c], atol=1e-4)
    assert (pit[c] >= F[c] - 1e-4).all() and (pit[c] <= 1).all()
    gap = (pit[c] - F[c]) / (1 - F[c])                  # U(0, 1) when randomized over [F(y), 1]
    assert gap.std() > 0.15 and 0.25 < gap.mean() < 0.75


def test_censored_nb_pits_keep_the_atom_at_y():
    """Mutants "censored NB PIT at U(F(y), 1)" and "not randomized": a censored turns row at y has PIT
    U(F(y - 1), 1), F(y - 1) = P(Y < y) (the fitter's censored term is P(Y >= y)); an exact one U(F(y - 1), F(y)).
    F in closed form (NB2 by direct summation) from a one-point posterior without session effects."""
    ix = B.Index(SEED, {}, ["s0", "s1", "s2"], ["none"])
    mu1, a = 6.0, 2.0                             # Y - 1 ~ NB(mu 6, alpha 2)
    post = _one_draw_post(ix, "nb", math.log(mu1), math.log(a))
    ys = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12] * 3
    cens = [i % 3 == 0 for i in range(30)]
    frame = _frame_of(ix, ys, cens, "nb")
    Fx = B.nb_table(np.full(4, math.log(mu1)), np.full(4, a), np.zeros(4), 20)
    for k in range(20):
        assert Fx[k] == pytest.approx(_nb_cdf_direct(k, mu1, a), abs=1e-12)
    lo, hi = B.nb_bounds(Fx, np.array([1, 5, 5]), np.array([False, False, True]))
    assert lo.tolist() == [0.0, Fx[3], Fx[3]] and hi.tolist() == [Fx[0], Fx[4], 1.0]
    lo_seen = []
    for k in range(6):
        _e, st = B.drift_check(post, "nb", ix, frame, (1, 2, k))
        rows, _ = B.drift_rows(frame)
        for r, u in zip(rows, st["pit"]):
            y = int(r["api_calls"])
            Fy1, Fy = _nb_cdf_direct(y - 2, mu1, a) if y >= 2 else 0.0, _nb_cdf_direct(y - 1, mu1, a)
            assert Fy1 - 1e-9 <= u <= (1.0 if r["cens"] else Fy + 1e-9)
            if r["cens"]:
                lo_seen.append(u < Fy)              # inside the atom [F(y - 1), F(y)): only U(F(y - 1), 1) gets there
    assert sum(lo_seen) >= 5 and not all(lo_seen)


DRIFT_OK = {"ks_p": 0.4, "sessions": 5, "breach": False}
DRIFT_BAD = {"ks_p": 0.002, "sessions": 5, "breach": True}
DRIFT_OLD = {"ks_p": 0.001, "sessions": 4, "breach": True}


@pytest.mark.parametrize("check,gate,prev,want", [
    (DRIFT_OK, True, None, DRIFT_OK),             # check runs, gate passes: its entry
    (DRIFT_BAD, True, None, DRIFT_BAD),
    (DRIFT_OK, True, DRIFT_OLD, DRIFT_OK),        # only a gated, passing check clears a breach
    (DRIFT_BAD, True, DRIFT_OLD, DRIFT_BAD),
    (None, True, None, None),                     # under the minimum: no entry
    (None, True, DRIFT_OLD, DRIFT_OLD),           # ... or the previous breach, unchanged
    (None, False, DRIFT_OLD, DRIFT_OLD),
    (DRIFT_OK, False, DRIFT_OLD, DRIFT_OLD),      # gate fails: never clears, carries the breach
    (DRIFT_OK, False, None, None),                # ... and writes no passing entry
    (DRIFT_BAD, False, None, DRIFT_BAD),          # ... but its own breach is written
    (DRIFT_BAD, False, DRIFT_OLD, DRIFT_BAD),
    (None, True, DRIFT_OK, None),                 # a previous non-breach is not carried
])
def test_the_sticky_breach(check, gate, prev, want):
    """A.12 breach semantics (user decision 2026-10-09). Mutants "breach cleared by an under-minimum fit" and
    "breach cleared by a gate-failing fit"."""
    assert B.drift_entry(check, gate, prev) == want
    out = B.drift_block({"ctx": check}, {"ctx-ln-h4": gate, "turns-nb2s-h4": True},
                        {"soft.agent": prev, "hard.agent": prev} if prev else {})
    assert out == ({} if want is None else {"soft.agent": want, "hard.agent": want})


# ---------------------------------------------------------------- fit() end to end with a fake sampler (no NUTS)
class _NS:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class FakeSampler:
    """fit()'s sampling replaced: fit_hier returns a synthetic posterior centred on the rows it is given (per
    type: mean log value, sd), shifted by `shift[kind]` on the log scale; diagnostics report GOOD_MODEL's diag, or
    BAD_MODEL's (2 divergences: the model gate fails) for the kinds in `bad`; the Bayes stack's imports are stubbed
    where absent. Everything after sampling (assemble, the drift check, self_check, the write) is the real code."""

    def __init__(self, monkeypatch):
        self.shift, self.bad, self.cur_reg = {"nb": 0.0, "ln": 0.0}, set(), []
        for name in ("pymc", "arviz", "pytensor", "nutpie", "scipy"):
            if importlib.util.find_spec(name) is None:
                mod = type(sys)(name)
                mod.__version__ = "0-fake"
                monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.setattr(B, "fit_hier", self.fit_hier)
        monkeypatch.setattr(B, "diagnostics", lambda dt, free, dropped=(): dict(
            (BAD_MODEL if dt["kind"] in self.bad else GOOD_MODEL)["diag"], constant=[]))
        monkeypatch.setattr(B, "qdiag", lambda qd: {"rhat": 1.0, "ess_bulk": 4000.0, "ess_tail": 4000.0})
        real = B.assemble

        def spy(posts, frames, ix, seed, cur_reg, *a, **k):
            self.cur_reg.append(cur_reg)
            return real(posts, frames, ix, seed, cur_reg, *a, **k)
        monkeypatch.setattr(B, "assemble", spy)

    def fit_hier(self, recs, ycol, kind, ix, center, cfg, seed, **kw):
        rng = np.random.default_rng(seed)
        y = np.array([r[ycol] for r in recs], float)
        ly = np.log(np.maximum(y - 1, 0.5)) if kind == "nb" else np.log(y)
        nt = len(ix.types)
        eta, sd = np.full(nt, ly.mean()), np.full(nt, max(ly.std(), 0.3))
        t_i = ix.ti(recs)
        for j in range(nt):
            if (t_i == j).sum() >= 3:
                eta[j], sd[j] = ly[t_i == j].mean(), max(ly[t_i == j].std(), 0.3)
        eta = eta + self.shift[kind]
        shp = (2, 50)
        def z(*k):
            return 0.01 * rng.standard_normal(shp + k)
        p = {"a0": float(eta.mean()) + z(), "b_fam": z(len(ix.fams)), "g": 0.5 + z(), "u_p": z(len(ix.peff)),
             "tau_t": 0.5 + np.abs(z()), "eta_type": eta + z(nt), "tau_s": 0.2 + np.abs(z()),
             "tau_ts": 0.1 + np.abs(z()), "rho": z()}
        if kind == "nb":
            p["log_alpha_t"], p["log_alpha"] = np.log(1.0 / sd ** 2 + 0.5) + z(nt), 0.5 + z(len(ix.pools))
        else:
            p["log_sigma_t"], p["log_sigma"] = np.log(sd) + z(nt), z(len(ix.pools))
        if len(ix.regimes) >= 2:
            p["tau_g"], p["z_g"] = 0.2 + np.abs(z()), z(len(ix.regimes))
        post = {k: _A(v) for k, v in p.items()}
        return {"posterior": _NS(dataset=post), "kind": kind}, list(p), 0.0, []


def _fixture_state(st):
    for n in ("runs.csv", "runs3.csv"):
        shutil.copy(FIX / n, st / "usage" / n)
    for n in ("live.json", "proposals.json"):
        shutil.copy(FIX / "state" / n, st / "limits" / n)


@pytest.fixture
def sampler(st, monkeypatch):
    _fixture_state(st)
    return FakeSampler(monkeypatch)


def _fit(st, regime=None):
    out = st / "limits" / "bayes.json"
    cfg = {"chains": 2, "draws": 50, "tune": 10, "seed": B.SEED, "no_sched": True, "regime": regime}
    rc, line = B.fit(cfg, str(out), log=lambda s: None)
    return rc, line, (json.loads(out.read_text()) if out.exists() else None)


def test_a_fit_writes_its_drift_entries_and_the_reader_drops_a_breached_family(st, sampler):
    """End to end on the frozen fixture (281 agent rows, 4 sessions): a posterior that fits the rows writes
    drift entries with breach false for turns, soft.agent and hard.agent; a ctx posterior moved by e^3 breaches
    soft.agent and hard.agent (one PIT set, equal entries) but not turns. stack_limits' existing reader then drops
    those families' nuts blocks (load_bayes), lists them as breached (load_hyper) and builds no grid block for
    them, while turns blocks stay. The file is written atomically, 0600, the summary line within its cap."""
    rc, line, doc = _fit(st)
    assert rc == B.EXIT_OK, line
    assert set(doc["drift"]) == {"turns", "soft.agent", "hard.agent"}
    assert all(set(e) == {"ks_p", "sessions", "breach"} and e["breach"] is False for e in doc["drift"].values()), \
        doc["drift"]
    assert doc["drift"]["soft.agent"] == doc["drift"]["hard.agent"] and doc["drift"]["turns"]["sessions"] == 4
    assert " drift turns D " in line and " breach none " in line and len(line) <= B.SUMMARY_MAX
    assert re.match(r"^bayes: [ -~]{0,280}\Z", line)                       # stack_usage.SUMMARY_RE keeps it
    sampler.shift["ln"] = 3.0
    rc, line, doc = _fit(st)
    assert rc == B.EXIT_OK and doc["drift"]["soft.agent"]["breach"] is True, doc["drift"]
    assert doc["drift"]["soft.agent"] == doc["drift"]["hard.agent"] and doc["drift"]["turns"]["breach"] is False
    assert " breach hard.agent,soft.agent " in line
    path = st / "limits" / "bayes.json"
    assert (path.stat().st_mode & 0o777) == 0o600 and [p.name for p in path.parent.iterdir()
                                                         if p.name.startswith(".tmp")] == []
    eid = doc["evidence_id"]
    accepted = L.load_bayes(SEED, eid)
    fams = {L.split_var(v)[0] for v in doc["vars"]}
    assert {"turns", "soft.agent", "hard.agent"} <= fams
    assert accepted and {L.split_var(v)[0] for v in accepted} == {"turns"}, sorted(accepted or ())
    undrifted = json.loads(path.read_text())
    undrifted["drift"] = {}
    assert {L.split_var(v)[0] for v in L.load_bayes(SEED, eid, undrifted)} >= {"soft.agent", "hard.agent"}
    hy, src = L.load_hyper(SEED)
    assert src == "fit:" + doc["fit_id"] and hy["breach"] == ["hard.agent", "soft.agent"]
    t = next(v.split(".", 2)[2] for v in doc["vars"] if v.startswith("soft.agent."))
    entry = {"b": {"y": [1e6, 2e6], "cens": [0, 0], "resume": [0, 0], "sess": ["s1", "s2"]}, "n": 2, "agents": 2,
             "ci": [1e6, 2e6], "x": [1e6, 2e6], "sessions": 2}
    assert L.bayes_grid_block(entry, hy, "soft.agent." + t, SEED["vars"]["soft.agent." + t]) is None


def test_the_breach_is_sticky_through_the_file_on_disk(st, sampler, monkeypatch):
    """A.12 through fit() and the bayes.json on disk: a gated breaching fit; then an under-minimum fit carries it
    (mutant "cleared by an under-minimum fit"); then a fit whose ctx gate fails while its own check passes
    carries it (mutant "cleared by a gate-failing fit"); then a gated passing fit clears it. A previous file the
    reader refuses carries nothing; a gate-failing fit with no breach before it writes no ctx entry."""
    sampler.shift["ln"] = 3.0
    rc, _line, doc = _fit(st)
    first = doc["drift"]["soft.agent"]
    assert rc == B.EXIT_OK and first["breach"] is True
    sampler.shift["ln"] = 0.0
    with monkeypatch.context() as m:
        m.setattr(B, "DRIFT_MIN_ROWS", 10 ** 6)
        rc, line, doc = _fit(st)
    assert rc == B.EXIT_OK and doc["drift"] == {"soft.agent": first, "hard.agent": first}, doc["drift"]
    assert "turns n " in line and " min" in line
    sampler.bad = {"ln"}
    rc, _line, doc = _fit(st)
    assert doc["drift"]["soft.agent"] == first and doc["drift"]["hard.agent"] == first
    assert doc["drift"]["turns"]["breach"] is False
    assert L.load_bayes(SEED, doc["evidence_id"]) is not None
    sampler.bad = set()
    rc, _line, doc = _fit(st)
    assert doc["drift"]["soft.agent"]["breach"] is False and doc["drift"]["soft.agent"]["ks_p"] >= B.DRIFT_ALPHA
    # a gate-failing fit without a previous breach: no ctx entry; with its own breach: breach true
    sampler.bad = {"ln"}
    rc, _line, doc = _fit(st)
    assert set(doc["drift"]) == {"turns"}
    sampler.shift["ln"] = 3.0
    rc, _line, doc = _fit(st)
    assert doc["drift"]["soft.agent"]["breach"] is True
    # a previous file the reader refuses (rules 1, 3, 4) carries nothing
    path = st / "limits" / "bayes.json"
    bad = json.loads(path.read_text())
    bad["vars"]["STACK_MAX_FANOUT"] = {}
    path.write_text(json.dumps(bad))
    assert B.previous_breaches(str(path), SEED) == {}
    sampler.shift["ln"], sampler.bad = 0.0, set()
    with monkeypatch.context() as m:
        m.setattr(B, "DRIFT_MIN_ROWS", 10 ** 6)
        rc, _line, doc = _fit(st)
    assert rc == B.EXIT_OK and doc["drift"] == {}
    path.write_text("{not json")
    assert B.previous_breaches(str(path), SEED) == {}


def test_regime_option_replaces_the_lookup(st, sampler, monkeypatch, capsys):
    """A.11.3: `stack_bayes.py fit --regime R` makes the fit use R as the current regime, whatever
    STACK_SOFT_LIMIT_SCALE (which moves stack_limits.current_regime) and proposals.regime are (mutant "--regime
    ignored", through main -> fit -> load_inputs -> assemble); data.regime_current is the fitter's note for R. A
    regime that is not 16 lowercase hex digits fails before the fit."""
    R = "0123456789abcdef"
    props = json.loads((st / "limits" / "proposals.json").read_text())
    assert props["regime"] and props["regime"] != R
    monkeypatch.setenv("STACK_SOFT_LIMIT_SCALE", "0.5")
    live = L.current_regime()
    assert live not in (R, props["regime"])
    for k in ("PYTENSOR_FLAGS", "NUMBA_CACHE_DIR"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr(B, "missing_deps", list)
    out = st / "limits" / "bayes.json"
    assert B.main(["fit", "--no-sched", "--out", str(out), "--chains", "2", "--draws", "100", "--tune", "100",
                   "--regime", R]) == B.EXIT_OK, capsys.readouterr().out
    assert sampler.cur_reg == [R]
    doc = json.loads(out.read_text())
    assert doc["data"]["regime_current"] in ("new", "new-prior")       # R has no rows: a new regime
    assert B.load_inputs(SEED, R)[5] == R and B.load_inputs(SEED)[5] == props["regime"]
    (st / "limits" / "proposals.json").unlink()
    assert B.load_inputs(SEED)[5] == live and B.load_inputs(SEED, R)[5] == R
    rc, _line, _doc = _fit(st, regime=props["regime"])                   # a seen regime: its own offset
    assert rc == B.EXIT_OK and sampler.cur_reg[-1] == props["regime"] and _doc["data"]["regime_current"] == "seen"
    called, real_fit = [], B.fit
    monkeypatch.setattr(B, "fit", lambda cfg, out, log=print: called.append(cfg) or (0, "bayes: x"))
    capsys.readouterr()
    for bad in ("0123456789ABCDEF", "0123456789abcde", "0123456789abcdef0", "../../etc/passwd", ""):
        assert B.main(["fit", "--regime", bad]) == B.EXIT_FAIL
        assert capsys.readouterr().out.strip() == "bayes: failed: --regime is not 16 lowercase hex digits"
    assert called == []
    assert B.main(["fit", "--regime", R]) == B.EXIT_OK and called[0]["regime"] == R
    assert B.main(["fit"]) == B.EXIT_OK and called[1]["regime"] is None
    assert real_fit({"regime": "zz"}, str(out))[0] == B.EXIT_FAIL


def test_the_pit_uses_the_rows_own_regime_offset():
    """A.12 (review F2): a row's F carries its own regime's offset tau_g z_g[g] (mutants "offset dropped" and
    "another regime's offset"): rows of regime rb, z_g = (-1, +1), drawn at mu + 1, have PIT F(y) at mu + 1."""
    ix = B.Index(SEED, {}, ["s0", "s1", "s2"], ["ra", "rb"])
    mu, sig = math.log(1e6), 0.5
    post = _one_draw_post(ix, "ln", mu, math.log(sig))
    post["tau_g"] = _A(np.ones((1, 4)))
    post["z_g"] = _A(np.broadcast_to(np.array([-1.0, 1.0]), (1, 4, 2)).copy())
    ys = np.exp(mu + 1.0 + sig * np.random.default_rng(9).standard_normal(30))
    frame = [dict(r, regime="rb") for r in _frame_of(ix, ys, np.zeros(30, bool), "ln")]
    _e, st = B.drift_check(post, "ln", ix, frame, (1, 2, 3))
    rows, _ = B.drift_rows(frame)
    F = [0.5 * math.erfc(-(math.log(r["ctx"]) - mu - 1.0) / sig / math.sqrt(2)) for r in rows]
    assert np.allclose(st["pit"], F, atol=1e-4)


def test_a_new_seed_keeps_the_breach_but_rule_3_still_refuses(st, sampler):
    """A.12 (review F1): the previous file is checked by rules 1, 3 and 4 only. A seed whose sha changed still
    carries the breach (rule 2's seed_sha is waived); a seed without a variable the file names refuses it."""
    sampler.shift["ln"] = 3.0
    rc, _line, doc = _fit(st)
    assert rc == B.EXIT_OK and doc["drift"]["soft.agent"]["breach"] is True
    path = str(st / "limits" / "bayes.json")
    got = B.previous_breaches(path, dict(SEED, sha="sha256:" + "f" * 64))
    assert set(got) == {"soft.agent", "hard.agent"} and got["soft.agent"] == doc["drift"]["soft.agent"]
    assert set(B.previous_breaches(path, SEED)) == {"soft.agent", "hard.agent"}
    victim = min(doc["vars"])
    fewer = dict(SEED, sha="sha256:" + "f" * 64, vars={k: v for k, v in SEED["vars"].items() if k != victim})
    assert B.previous_breaches(path, fewer) == {}
