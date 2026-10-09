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
    for k in ("evidence_id", "seed_sha", "fit_id", "risk", "sampler", "versions", "data", "hyper", "drift"):
        if k != "hyper":
            assert a[k] == b[k], k
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
