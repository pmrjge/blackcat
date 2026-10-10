"""WP5 5b (docs/BAYES.md A.11): the fold driver tests/b1_folds.py and the informative B1-T14 of
tests/b1_backtest.py.

Run: uv run --no-project --python 3.13 --with-requirements requirements/tools.txt pytest -q tests/test_b1_folds.py
The fits are a FAKE fitter (a stub stack_bayes.py, as tests/test_stack_bayes_fit.py's fake venv): it records its
argv, environment, the sessions and snapshots of its state directory and whether the live accel.lock is held, and
writes a bayes.json the reader accepts whose hyperparameters come from the rows it was given (and from the regime it
treats as current). No NUTS fit runs here. Every test uses its own XDG_STATE_HOME and HOME under tmp_path, never the
stack's.
"""
import csv
import fcntl
import importlib.util
import json
import math
import os
import random
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
AGENTS = ROOT / "dot-config" / "dot-claude" / "agents"
TESTS = ROOT / "tests"
T0 = 1790000000.0
R0 = "00aa11bb22cc33dd"            # a regime whose fake offset is 0 (the calibrated sets)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
_B1_REPO = os.environ.pop("B1_REPO", None)       # the scripts under test use this checkout's hooks
try:
    BT = _load("b1_backtest", TESTS / "b1_backtest.py")
    F = _load("b1_folds", TESTS / "b1_folds.py")
finally:
    if _B1_REPO is not None:
        os.environ["B1_REPO"] = _B1_REPO
L = BT.L
V2_COLUMNS = ["schema_version", "session", "id", "type", "seg", "status", "api_calls", "ctx", "first_ts", "last_ts",
              "compacted", "turn_limited", "after_limit", "is_main", "window", "status_code", "hit_soft", "hit_turn",
              "hit_hard_agent", "hit_hard_prompt", "hit_hard_session", "regime", "src"]

FAKE_FIT = r'''#!/usr/bin/env python3
import fcntl, hashlib, json, math, os, sys
here = os.path.dirname(os.path.abspath(__file__))
ctl = json.load(open(os.path.join(here, "fake.json")))
args = sys.argv[1:]
if "--help" in args:
    print("usage: stack_bayes.py {fit,check} [--out OUT] [--no-sched]" + ("" if ctl.get("no_regime") else
                                                                         " [--regime REGIME]"))
    sys.exit(0)
sys.path.insert(0, ctl["hooks"])
import stack_limits as L
out = args[args.index("--out") + 1]
regime = args[args.index("--regime") + 1] if "--regime" in args else L.current_regime()
rows, _ = L.read_rows(L.csv_paths(), models=L.agent_models(ctl["agents"]))
sessions = sorted({r["session"] for r in rows})
held = None
if ctl.get("lock"):
    try:
        fd = os.open(ctl["lock"], os.O_RDWR)
    except OSError:
        held = "absent"
    else:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = False
            fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError:
            held = True
        os.close(fd)
snaps = os.path.join(L.limits_dir(), "snapshots")
rec = {"argv": args, "xdg": os.environ.get("XDG_STATE_HOME"), "cwd": os.getcwd(), "sessions": sessions,
       "eid": L.evidence_id(rows), "regime": regime, "accel_held": held,
       "snapshots": sorted(os.listdir(snaps)) if os.path.isdir(snaps) else [],
       "scale": os.environ.get("STACK_SOFT_LIMIT_SCALE")}
with open(os.path.join(here, "calls.jsonl"), "a") as fh:
    fh.write(json.dumps(rec) + "\n")
mode = ctl.get("modes", {}).get(str(len(sessions)), "ok")
if mode == "exit1":
    print("bayes: failed: boom")
    sys.exit(1)
if mode == "garbage":
    open(out, "w").write("{")
    print("bayes: fit garbage")
    sys.exit(0)
seed = L.load_seed()
off = int(regime[:2], 16) / 256.0 + ctl.get("mu_shift", 0.0)
def hyper(q, default, scale):
    by = {}
    for r in rows:
        if r["scope"] == "agent" and r[q]:
            by.setdefault(r["type"], []).append(math.log(r[q]))
    return {"tau_t": 0.3, "tau_new": ctl.get("tau_new", 0.2), "rho": 0.1, "p_resume": 0.2,
            "types": {t: {"mu": round(sum(v) / len(v) + off, 9), "scale": scale} for t, v in sorted(by.items())}}
good = {"gate": True, "diag": {"rhat_max": 1.003, "ess_bulk_min": 1841, "ess_tail_min": 1680, "divergences": 0,
                               "ebfmi_min": 0.76, "constant": ["z_s"], "nan": []}}
bad = {"gate": True, "diag": dict(good["diag"], divergences=3)}
eid = L.evidence_id(rows)
doc = {"schema_version": 1, "code": "stack_bayes/1", "generated": "2026-10-10T00:00:00Z", "evidence_id": eid,
       "seed_sha": seed["sha"], "fit_id": hashlib.sha256((eid + regime).encode()).hexdigest()[:16],
       "risk": dict(L.RISK), "sampler": {"seed": 20261003, "chains": 8, "draws": 4000, "tune": 2000,
                                          "target_accept": 0.98},
       "versions": {}, "data": {"rows": len(rows), "regime_current": "seen" if regime in {r["regime"] for r in rows}
                                else "new"},
       "models": {"turns-nb2s-h4": good, "ctx-ln-h4": bad if mode == "badgate" else good},
       "hyper": {"turns": hyper("api_calls", 30, 20.0), "ctx": hyper("ctx", 5e6, 0.4)},
       "drift": {}, "vars": {}, "sched": None}
open(out, "w").write(json.dumps(doc))
print("bayes: fit %s ok" % doc["fit_id"])
'''


# ---------------------------------------------------------------- fixtures and builders
@pytest.fixture
def env(tmp_path, monkeypatch):
    """A live state under tmp_path (XDG_STATE_HOME and HOME), no STACK_* knob."""
    for k in [k for k in os.environ if k.startswith(("STACK_", "PYTENSOR", "NUMBA_"))]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "live"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    live = tmp_path / "live" / "claude-agent-stack"
    live.mkdir(parents=True)
    return live


class Fake:
    def __init__(self, tmp_path, **ctl):
        self.dir = tmp_path / "fake"
        self.dir.mkdir()
        self.py = self.dir / "stack_bayes.py"
        self.py.write_text(FAKE_FIT)
        self.set(**ctl)

    def set(self, **ctl):
        (self.dir / "fake.json").write_text(json.dumps(dict(ctl, hooks=str(HOOKS), agents=str(AGENTS))))

    def calls(self):
        p = self.dir / "calls.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def agent_row(sess, aid, ts, regime, ctx, api, cens=False):
    """A coder row: observed (schema 2, status_code 0, every hit_* measured 0) or censored (A.3 row 9: a schema-3
    complete row with status_code empty, still in the support sample)."""
    return {"schema_version": 3 if cens else 2, "session": sess, "id": aid, "type": "coder", "seg": 0,
            "status": "complete", "api_calls": api, "ctx": ctx, "first_ts": ts - 100, "last_ts": ts, "compacted": 0,
            "turn_limited": 0, "after_limit": 0, "is_main": 0, "window": "", "status_code": "" if cens else 0,
            "hit_soft": 0, "hit_turn": 0, "hit_hard_agent": 0, "hit_hard_prompt": 0, "hit_hard_session": 0,
            "regime": regime, "src": "measured"}


def make_data(root, sessions, seed=7, ctx_scale=1.0):
    """root/usage/runs3.csv and root/limits/snapshots/<s>.json for sessions [(sid, regime, n rows, censored)];
    observed ctx log-normal (median 5e6, sd 0.4 on the log scale), api_calls about 30; censored rows at
    ctx 1e5 x ctx_scale and api_calls 3 (far below any T)."""
    rnd = random.Random(seed)
    rows = []
    for i, (sid, regime, n, cens) in enumerate(sessions):
        for a in range(n):
            ts = T0 + 10000 * i + a + 1
            if cens:
                rows.append(agent_row(sid, f"a{a}", ts, regime, int(1e5 * ctx_scale), 3, cens=True))
            else:
                rows.append(agent_row(sid, f"a{a}", ts, regime, int(5e6 * math.exp(0.4 * rnd.gauss(0, 1))),
                                      max(2, round(30 * math.exp(0.3 * rnd.gauss(0, 1))))))
    usage = root / "usage"
    usage.mkdir(parents=True, exist_ok=True)
    with open(usage / "runs3.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=V2_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    snaps = root / "limits" / "snapshots"
    snaps.mkdir(parents=True, exist_ok=True)
    for sid, *_ in sessions:
        (snaps / f"{sid}.json").write_text(json.dumps({"session_id": sid}))
    return usage


def folds(tmp_path, fake, data, *extra, out="hyper"):
    """Run the driver in-process with the fake fitter; (rc, out dir)."""
    od = tmp_path / out
    rc = F.main(["--data", str(data), "--out-dir", str(od), "--python", sys.executable, "--fitter", str(fake.py),
                 *extra])
    return rc, od


def backtest(tmp_path, data, hyper, *extra, name="bt.json"):
    out = tmp_path / name
    rc = BT.main(["--data", str(data), "--hyper-dir", str(hyper), "--sims", "400", "--out", str(out), *extra])
    return rc, (json.loads(out.read_text()) if out.exists() else None)


def order_of(data):
    return BT.read_data(str(data))[1]


SIX = [(f"s{i}", R0, 16, False) for i in range(6)]


# ---------------------------------------------------------------- the driver: folds, regime, files
def test_each_fold_fits_once_on_the_earlier_sessions_only(env, tmp_path):
    """Kills "fold k trains on session k (leak)" and "one hyperparameter set reused across folds": one fit per
    fold, whose state holds exactly the sessions before k (rows and snapshots), at the test session's regime,
    with the shipped sampler; each fold's files come from its own fit."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 0
    order = order_of(data)
    calls = fake.calls()
    assert [len(c["sessions"]) for c in calls] == [2, 3, 4, 5]
    ctx_docs = set()
    for k, c in zip((2, 3, 4, 5), calls):
        assert c["sessions"] == sorted(order[:k]) and order[k] not in c["sessions"]
        assert c["snapshots"] == sorted(f"{s}.json" for s in order[:k])
        argv = c["argv"]
        assert argv[:2] == ["fit", "--no-sched"] and argv[argv.index("--regime") + 1] == R0
        assert not {"--chains", "--draws", "--tune", "--timeout", "--seed"} & set(argv)
        assert c["cwd"] == "/" and not c["xdg"].startswith(str(env.parent))
        g = json.loads((od / f"fold{k}_gate.json").read_text())
        assert g["test_session"] == order[k] and g["train_sessions"] == order[:k] and g["ok"] is True
        assert g["evidence_id"] == c["eid"] == L.evidence_id([r for r in BT.read_data(str(data))[0]
                                                              if r["session"] in order[:k]])
        assert g["regime"] == R0 and g["data"]["regime_current"] == "seen"
        assert g["models"]["ctx-ln-h4"]["ok"] and g["models"]["turns-nb2s-h4"]["ok"]
        ctx = json.loads((od / f"fold{k}_ctx.json").read_text())
        assert ctx == json.loads((od / f"fold{k}_bayes.json").read_text())["hyper"]["ctx"]
        ctx_docs.add(json.dumps(ctx, sort_keys=True))
        assert BT.load_hyper_file(str(od / f"fold{k}_turns.json"), 0.0)["types"]["coder"]["scale"] == 20.0
    assert len(ctx_docs) == 4                                   # four fits, four hyperparameter sets
    assert not [p for p in od.iterdir() if p.name.startswith(".b1-folds-")]    # the work state is removed


def test_a_kept_work_dir_is_never_reused(env, tmp_path, capsys):
    """--keep-work leaves each fold's state (only its training sessions); a second run into the same --work-dir
    stops (exit 2) instead of mixing an earlier run's files into a fold."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    work = tmp_path / "work"
    rc, _od = folds(tmp_path, fake, data, "--no-accel-lock", "--work-dir", str(work), "--keep-work")
    assert rc == 0
    usage = work / "fold3" / "state" / "claude-agent-stack" / "usage" / "runs3.csv"
    with open(usage, newline="") as fh:
        assert {r["session"] for r in csv.DictReader(fh)} == set(order_of(data)[:3])
    rc, _od = folds(tmp_path, fake, data, "--no-accel-lock", "--work-dir", str(work), out="h2")
    assert rc == 2 and "FileExistsError" in capsys.readouterr().err and len(fake.calls()) == 4


def test_the_soft_limit_scale_changes_no_fold(env, tmp_path, monkeypatch):
    """A.11.3 proof: two runs that differ only in STACK_SOFT_LIMIT_SCALE give equal fold<k>_ctx.json and the same
    regime and data.regime_current (the driver passes --regime; without it the fake, like the fitter, would
    fold the scale's regime in)."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    regs = []
    for scale in ("1", "0.5"):
        monkeypatch.setenv("STACK_SOFT_LIMIT_SCALE", scale)
        regs.append(L.current_regime())
    assert regs[0] != regs[1]                                   # the scale moves the machine's regime
    outs = []
    for scale, name in (("1", "h1"), ("0.5", "h2")):
        monkeypatch.setenv("STACK_SOFT_LIMIT_SCALE", scale)
        rc, od = folds(tmp_path, fake, data, "--no-accel-lock", out=name)
        assert rc == 0
        outs.append(od)
    assert {c["scale"] for c in fake.calls()} == {"1", "0.5"}
    for k in (2, 3, 4, 5):
        a, b = (json.loads((od / f"fold{k}_ctx.json").read_text()) for od in outs)
        assert a == b
        ga, gb = (json.loads((od / f"fold{k}_gate.json").read_text()) for od in outs)
        assert (ga["regime"], ga["data"]) == (gb["regime"], gb["data"]) == (R0, {"regime_current": "seen"})


def test_a_failed_gate_or_invalid_output_is_recorded_never_dropped(env, tmp_path):
    """Kills "failed fold gate ignored" (driver side): a failing model gate, a failed fit and an unreadable
    bayes.json each give an ok false gate file with the reason (no hyper files without a valid fit), exit 1;
    a test session without a regime is never fitted at another regime."""
    fake = Fake(tmp_path, modes={"3": "badgate", "4": "exit1", "5": "garbage"})
    data = make_data(tmp_path / "copy", SIX[:5] + [("s5", "", 16, False)])
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 1
    gate = {k: json.loads((od / f"fold{k}_gate.json").read_text()) for k in (2, 3, 4, 5)}
    assert gate[2]["ok"] is True
    assert gate[3]["ok"] is False and gate[3]["models"]["ctx-ln-h4"]["ok"] is False
    assert gate[3]["models"]["turns-nb2s-h4"]["ok"] is True and "ctx-ln-h4" in gate[3]["reason"]
    assert (od / "fold3_ctx.json").exists()                     # a valid fit whose gate failed: kept, reported
    assert gate[4]["ok"] is False and gate[4]["reason"] == "fit failed: exit 1"
    assert not (od / "fold4_ctx.json").exists() and not (od / "fold4_turns.json").exists()
    assert gate[5]["ok"] is False and "no regime" in gate[5]["reason"] and gate[5]["regime"] is None
    assert len(fake.calls()) == 3                               # folds 2-4 fitted; fold 5 has no regime
    fake.set(modes={"5": "garbage"})
    data2 = make_data(tmp_path / "copy2", SIX)
    rc, od2 = folds(tmp_path, fake, data2, "--no-accel-lock", out="h2")
    g5 = json.loads((od2 / "fold5_gate.json").read_text())
    assert rc == 1 and g5["ok"] is False and g5["reason"].startswith("bayes.json invalid")


@pytest.mark.parametrize("where", ["xdg", "home", "symlink", "work"])
def test_a_target_in_the_live_state_is_refused(env, tmp_path, monkeypatch, capsys, where):
    """Kills "live state dir accepted as target": an --out-dir or --work-dir resolving into
    $XDG_STATE_HOME/claude-agent-stack or ~/.local/state/claude-agent-stack is refused before any fit."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    home_live = tmp_path / "home" / ".local" / "state" / "claude-agent-stack"
    home_live.mkdir(parents=True)
    extra = []
    if where == "xdg":
        od = env / "folds"
    elif where == "home":
        monkeypatch.delenv("XDG_STATE_HOME")
        od = home_live / "folds"
    elif where == "symlink":
        (tmp_path / "link").symlink_to(env)
        od = tmp_path / "link" / "folds"
    else:
        od = tmp_path / "hyper"
        extra = ["--work-dir", str(env / "work")]
    rc = F.main(["--data", str(data), "--out-dir", str(od), "--python", sys.executable, "--fitter", str(fake.py),
                 "--no-accel-lock", *extra])
    assert rc == 2 and "live state directory" in capsys.readouterr().err
    assert fake.calls() == [] and not od.exists() and not (env / "work").exists()


def test_the_live_accel_lock_is_held_during_every_fit(env, tmp_path):
    """Kills "accel.lock not taken": each fit runs while the live <state>/accel.lock is held (the fd is passed
    to it), and the lock is free again after the run; --no-accel-lock runs without it."""
    lock = env / "accel.lock"
    fake = Fake(tmp_path, lock=str(lock))
    data = make_data(tmp_path / "copy", SIX)
    rc, _od = folds(tmp_path, fake, data)
    assert rc == 0
    assert [c["accel_held"] for c in fake.calls()] == [True] * 4
    fd = os.open(lock, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)            # released at the end
    finally:
        os.close(fd)
    rc, _od = folds(tmp_path, fake, data, "--no-accel-lock", out="h2")
    assert rc == 0 and [c["accel_held"] for c in fake.calls()[4:]] == [False] * 4


def test_a_held_accel_lock_refuses_without_fitting(env, tmp_path, capsys):
    import stack_usage
    lock = env / "accel.lock"
    fake = Fake(tmp_path, lock=str(lock))
    data = make_data(tmp_path / "copy", SIX)
    fd = stack_usage.accel_acquire("another-job")
    assert fd is not None
    try:
        rc, _od = folds(tmp_path, fake, data)
    finally:
        os.close(fd)
    assert rc == 2 and "accel.lock" in capsys.readouterr().err and fake.calls() == []


def test_a_fitter_without_regime_is_refused(env, tmp_path, capsys):
    """--regime is WP5 5c's: until the fitter offers it, the driver refuses (never the live or checkout
    regime)."""
    fake = Fake(tmp_path, no_regime=True)
    data = make_data(tmp_path / "copy", SIX)
    rc, _od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 2 and "--regime" in capsys.readouterr().err and fake.calls() == []


def test_an_interpreter_that_cannot_run_the_fitter_is_named_in_the_refusal(env, tmp_path, capsys):
    """A --python that does not run (or a --help that fails) is refused with a message that says so, not only
    "has no --regime option" (code review L2)."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    rc = F.main(["--data", str(data), "--out-dir", str(tmp_path / "hyper"), "--python", "/nonexistent/python",
                 "--fitter", str(fake.py), "--no-accel-lock"])
    err = capsys.readouterr().err
    assert rc == 2 and "--help` did not run" in err and "/nonexistent/python" in err and fake.calls() == []


def test_the_shipped_fitter_is_feature_detected():
    """Regression guard: the real stack_bayes.py is offered --regime exactly when its parser has it."""
    has = "--regime" in (HOOKS / "stack_bayes.py").read_text()
    assert F.has_regime_option(sys.executable, str(HOOKS / "stack_bayes.py")) is has


# ---------------------------------------------------------------- the backtest: verdicts
def test_an_all_censored_set_is_not_informative(env, tmp_path):
    """Kills "informativeness removed": every test row censored below T (u = n) gives informative false, I1, I2
    and I3 failed, REJECT (informative), exit 1."""
    fake = Fake(tmp_path, mu_shift=3.0)
    data = make_data(tmp_path / "copy", [(f"s{i}", R0, 16, True) for i in range(6)])
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 0
    rc, doc = backtest(tmp_path, data, od)
    sa = doc["families"]["soft.agent"]
    i = sa["informative"]
    assert (i["n"], i["u"], i["m"]) == (64, 64, 0) and i["folds_production"] == 4 and i["folds_any"] == 4
    assert i["ok"] is False and set(i["failed"]) == {"I1", "I2", "I3"}
    assert (sa["verdict"], sa["reason"]) == ("REJECT", "informative") and rc == 1
    assert sa["strata"]["production"]["supported"]["hits_T"] == [0, 64]


def test_an_informative_calibrated_set_accepts_and_low_power_keeps_the_exit_code(env, tmp_path, monkeypatch):
    """Positive control of the informativeness rule (an uncensored set calibrated by construction ACCEPTs), and
    kills "power gate removed": power_ok is power_2.5r >= B1_MIN_POWER and does not change the exit code."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 0
    rc, doc = backtest(tmp_path, data, od)
    sa = doc["families"]["soft.agent"]
    assert (sa["verdict"], rc) == ("ACCEPT", 0), sa
    i = sa["informative"]
    assert i["ok"] and i["u"] == 0 and i["m"] == 64 and i["q05"] > 0
    assert sa["power_2.5r"] >= BT.B1_MIN_POWER and sa["power_ok"] is True
    monkeypatch.setattr(BT, "B1_MIN_POWER", 1.01)                 # every run is now under-powered
    rc, doc = backtest(tmp_path, data, od, name="bt2.json")
    sa = doc["families"]["soft.agent"]
    assert (sa["verdict"], sa["power_ok"], rc) == ("ACCEPT", False, 0)


def test_an_ineligible_scored_fold_never_accepts(env, tmp_path):
    """Code review L1, A.11.3: with --min-train-sessions 1 the fold that trains on one session is scored; its
    rows must not help a verdict to ACCEPT, though the 3 eligible folds have production rows."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX[:5])
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock", "--min-train-sessions", "1")
    assert rc == 0
    rc, doc = backtest(tmp_path, data, od, "--min-train-sessions", "1")
    sa = doc["families"]["soft.agent"]
    assert sa["informative"]["folds_production"] == 3
    assert (sa["verdict"], rc) != ("ACCEPT", 0)
    assert (sa["verdict"], sa["reason"], sa["checks"]["folds"]) == ("REJECT", "folds", False)


def test_five_eligible_folds_with_one_production_fold_reject_on_folds(env, tmp_path):
    """A.11.4 proof, kills "fold-count rule": 5 eligible folds, only the last test session shares a regime with
    its training rows (60 scorable rows, production-supported): REJECT (folds), though any-regime has 5."""
    fake = Fake(tmp_path)
    regs = ["10" * 8, "10" * 8, "20" * 8, "30" * 8, "40" * 8, "50" * 8, "10" * 8]
    data = make_data(tmp_path / "copy", [(f"s{i}", regs[i], 60 if i == 6 else (16 if i < 2 else 8), False)
                                         for i in range(7)])
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 0
    rc, doc = backtest(tmp_path, data, od)
    sa = doc["families"]["soft.agent"]
    i = sa["informative"]
    assert (i["folds_production"], i["folds_any"]) == (1, 5)
    assert sa["strata"]["production"]["supported"]["n"] == 60 and i["m"] == 60
    assert (sa["verdict"], sa["reason"], sa["checks"]["folds"], rc) == ("REJECT", "folds", False, 1)
    rc, doc = backtest(tmp_path, data, od, "--support", "any", name="bt_any.json")
    assert doc["families"]["soft.agent"]["reason"] != "folds" and doc["support"] == "any"


def test_a_failed_fold_gate_blocks_the_family(env, tmp_path):
    """Kills "failed fold gate ignored" (backtest side): one fold whose ctx gate failed makes soft.agent and
    hard.agent blocked:gate (exit 1) while turns, whose model passed, is not blocked; a fold whose fit wrote
    nothing blocks as well."""
    fake = Fake(tmp_path, modes={"3": "badgate"})
    data = make_data(tmp_path / "copy", SIX)
    rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    assert rc == 1
    rc, doc = backtest(tmp_path, data, od, "--families", "soft.agent,turns")
    fam = doc["families"]
    assert (fam["soft.agent"]["verdict"], fam["hard.agent"]["verdict"]) == ("blocked:gate", "blocked:gate")
    assert fam["soft.agent"]["blocked_folds"] == [3] and fam["turns"]["blocked_folds"] == []
    assert fam["turns"]["verdict"] != "blocked:gate" and rc == 1
    fake.set(modes={"4": "exit1"})
    rc, od2 = folds(tmp_path, fake, data, "--no-accel-lock", out="h2")
    rc, doc = backtest(tmp_path, data, od2, name="bt2.json")
    assert doc["families"]["turns"]["verdict"] == "blocked:gate" and doc["families"]["turns"]["blocked_folds"] == [4]
    assert doc["families"]["soft.agent"]["verdict"] == "blocked:gate" and rc == 1


def test_another_folds_hyperparameters_are_an_error(env, tmp_path, capsys):
    """A gate file whose evidence id is not the fold's training rows' (one fit's files copied to another fold)
    stops the backtest with exit 2."""
    fake = Fake(tmp_path)
    data = make_data(tmp_path / "copy", SIX)
    _rc, od = folds(tmp_path, fake, data, "--no-accel-lock")
    for suffix in ("_ctx.json", "_turns.json", "_gate.json"):
        g = (od / f"fold5{suffix}").read_text()
        if suffix == "_gate.json":
            g = json.dumps(dict(json.loads(g), fold=4))
        (od / f"fold4{suffix}").write_text(g)
    rc, _doc = backtest(tmp_path, data, od)
    assert rc == 2 and "evidence_id" in capsys.readouterr().err


# ---------------------------------------------------------------- the backtest: rules in isolation
def test_I3_q05_is_the_empirical_cdf_convention():
    """Kills "I3 quantile convention": with exactly 5 % of null draws at 0, q05 = 0 and u = 0 fails I3
    (an index K0[int(0.05 sims)] would give 1 and let a vacuous ACCEPT through)."""
    k0 = [0] * 100 + [1] * 1900
    random.Random(3).shuffle(k0)
    assert BT.q05_of(k0) == 0
    info = BT.informativeness("soft.agent", 100, 30, 30, k0)
    assert info["u"] == 0 and info["q05"] == 0 and info["failed"] == ["I3"] and info["ok"] is False
    assert BT.q05_of([0] * 99 + [1] * 1901) == 1
    assert BT.informativeness("soft.agent", 100, 30, 30, [0] * 99 + [1] * 1901)["ok"] is True
    assert BT.q05_of([]) is None and BT.q05_of([4]) == 4


def test_I1_I2_bounds_and_deny_types_skip_I3():
    k0 = [9] * 200                                                                  # q05 9
    assert BT.informativeness("soft.agent", 40, 2, 2, k0)["ok"] is True              # m 40
    assert BT.informativeness("soft.agent", 40, 2, 3, k0)["failed"] == ["I1"]        # m 39
    assert BT.informativeness("soft.agent", 50, 2, 7, k0)["ok"] is True               # u / n = 0.10
    assert BT.informativeness("soft.agent", 49, 2, 7, k0)["failed"] == ["I2"]         # u / n > 0.10
    assert BT.informativeness("turns", 60, 0, 0, [0] * 200)["ok"] is True             # no I3 for deny types
    assert BT.informativeness("soft.agent", 60, 0, 0, [0] * 200)["failed"] == ["I3"]
    assert BT.informativeness("hard.agent", 0, 0, 0, [])["failed"] == ["I1", "I2"]


def test_verdict_precedence():
    assert BT.verdict_of(False, True, False, False) == ("REJECT", "folds")
    assert BT.verdict_of(True, True, False, False) == ("blocked:gate", "gate")
    assert BT.verdict_of(True, False, False, False) == ("REJECT", "informative")
    assert BT.verdict_of(True, False, True, False) == ("REJECT", "check")
    assert BT.verdict_of(True, False, True, True) == ("ACCEPT", None)
    assert (BT.power_ok_of(0.4999), BT.power_ok_of(0.5), BT.power_ok_of(None)) == (False, True, False)


class _Zero:
    """An RNG whose uniform draw is 0: the randomized PIT returns its lower end."""

    @staticmethod
    def random():
        return 0.0


class _CdfPred:
    def __init__(self, fam, cdf):
        self.fam, self._cdf = fam, cdf

    def cdf(self, y):
        return self._cdf[y]


def test_censored_pit_starts_at_F_of_y_minus():
    """Kills "NB PIT at U(F(y), 1)": a censored NB row's PIT is U(F(y - 1), 1), a log-normal one U(F(y), 1)."""
    nb = _CdfPred("turns", {9: 0.2, 10: 0.6})
    assert BT.pit(nb, 10, 1, _Zero) == 0.2
    assert BT.pit(nb, 10, 0, _Zero) == 0.2                       # uncensored NB: U(F(y - 1), F(y))
    ln = _CdfPred("soft.agent", {5e6: 0.7, 5e6 - 1: 0.69})
    assert BT.pit(ln, 5e6, 1, _Zero) == 0.7 and BT.pit(ln, 5e6, 0, _Zero) == 0.7


class _NormPred:
    """log Y = 3 w + 0.1 e (a dominant session effect): the marginal quantile integrates w."""

    fam = "soft.agent"

    def quantile(self, p):
        return math.exp(math.sqrt(9.01) * BT.G.nppf(p))

    def draw(self, rnd, w):
        return math.exp(3.0 * w + 0.1 * rnd.gauss(0, 1))


def test_power_uses_the_marginal_quantile_with_clustered_hits():
    """Kills "T_alt conditional instead of marginal": 3 folds x 20 scorable rows, a dominant session effect.
    Marginal T_alt (hit iff about w > 0.674): a fold is all hits with probability 0.25 and the too-many side
    rejects when 2 or 3 folds are (P0(K >= 40) ~ 0.028 < 0.05 <= P0(K >= 20) ~ 0.27): power 3 (0.25^2) 0.75 +
    0.25^3 = 0.156. A per-replicate (conditional on w) T_alt makes hits Bin(60, 0.25): power ~ 0.06."""
    pred = _NormPred()
    T = pred.quantile(0.9)
    rows = [(1.0, 0)] * 20                                       # observed, below T: scorable
    items = [[(pred, T, rows)] for _ in range(3)]
    rnd = random.Random(11)
    k0 = BT.simulate_null(items, 4000, rnd)
    assert 0.015 < sum(1 for k in k0 if k >= 40) / 4000 < 0.045
    many, few = BT.simulate_power(items, k0, 4000, rnd, 0.1)
    assert 0.12 < many < 0.20, many
    assert 0 <= few <= 1


def test_power_counts_unknown_rows_only_in_hi():
    """Rows unknown in the data (censored below T) add to hi_sim, never to lo_sim: with every row unknown the
    too-many side never rejects (lo_sim = 0)."""
    pred = _NormPred()
    T = pred.quantile(0.9)
    items = [[(pred, T, [(T / 10, 1)] * 20)] for _ in range(3)]
    rnd = random.Random(5)
    k0 = BT.simulate_null(items, 500, rnd)
    many, _few = BT.simulate_power(items, k0, 500, rnd, 0.1)
    assert many == 0.0


class _IidPred:
    """log Y ~ N(0, 1), no session effect: K0 is about Bin(n, 0.1)."""

    fam = "soft.agent"

    def quantile(self, p):
        return math.exp(BT.G.nppf(p))

    def draw(self, rnd, w):
        return math.exp(rnd.gauss(0, 1))


def test_power_r5_adds_the_unknown_rows_to_hi():
    """Pins power_r/5 (the too-few side, P0(K <= hi_sim) < 0.05, hi_sim = lo_sim + u): 3 folds x 40 rows, K0 about
    Bin(120, 0.1) (P0(K <= 6) about 0.04). All rows scorable: lo_sim about Bin(120, 0.02) <= 6 almost always, so
    power about 1. Half of them unknown: hi_sim >= 60, never rejected, power 0 (kills "hi_sim without + u")."""
    pred = _IidPred()
    T = pred.quantile(0.9)
    rnd = random.Random(17)
    scorable = [[(pred, T, [(1.0, 0)] * 40)] for _ in range(3)]
    k0 = BT.simulate_null(scorable, 2000, rnd)
    _many, few = BT.simulate_power(scorable, k0, 2000, rnd, 0.1)
    assert few > 0.9, few
    half = [[(pred, T, [(1.0, 0)] * 20 + [(T / 10, 1)] * 20)] for _ in range(3)]
    _many, few = BT.simulate_power(half, k0, 2000, rnd, 0.1)
    assert few == 0.0
