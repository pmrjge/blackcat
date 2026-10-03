"""stack-budget security review (F1-F6, L1, L2): each test failed on 44c9fd5 and passes after its fix.

Run: uv run --python 3.12 --with pytest pytest -q tests/test_stack_budget_security.py
Reuses test_stack_budget's env fixture (temp XDG_STATE_HOME), snapshot(), run() and _load().
"""
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_stack_budget as T  # noqa: E402  (env fixture, snapshot(), run(), _load())

env = T.env
SID = T.SID
OTHER = "44444444-4444-4444-8444-444444444444"


def rows(env, cells):
    U = sys.modules.get("stack_usage") or T._load("stack_usage")
    d = env / "usage"
    d.mkdir(exist_ok=True)
    with open(d / "runs2.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=U.COLUMNS)
        w.writeheader()
        for i, extra in enumerate(cells):
            r = dict(U.EMPTY_ROW, schema_version="2", session=SID, id="a%d" % i, type="scout", seg="0",
                     status="complete", api_calls="5", first_ts=str(1000 + i), last_ts=str(1100 + i), src="measured")
            r.update(extra)
            w.writerow(r)


def graph(tmp_path, doc):
    g = tmp_path / "g.json"
    g.write_text(json.dumps(doc))
    return str(g)


# F1: the installed copy runs <dirname(config dir)>/tests/prompt_budget.py
def test_f1_static_never_runs_a_file_outside_the_repo(tmp_path):
    b = tmp_path / "cfg" / ".claude" / "bin"
    b.mkdir(parents=True)
    shutil.copy(T.CLI, b / "stack-budget")
    (tmp_path / "cfg" / "tests").mkdir()
    marker = tmp_path / "ran"
    (tmp_path / "cfg" / "tests" / "prompt_budget.py").write_text("open(%r, 'w').write('x')\n" % str(marker))
    subprocess.run([T.PY, str(b / "stack-budget"), "static"], capture_output=True, text=True, check=False)
    assert not marker.exists()


# F2: graph strings and row cells reach the terminal raw
def test_f2_no_terminal_escapes_from_a_graph(env, tmp_path):
    T.snapshot()
    g = graph(tmp_path, {"job": "j\x1b[1A\x1b[2K", "nodes": [{"id": "A\x1b[2K\rverdict: fits", "a": "scout", "n": 5}]})
    p = T.run("plan", g, "--session", SID)
    assert p.returncode == 0 and "\x1b" not in p.stdout and "\r" not in p.stdout


def test_f2_no_terminal_escapes_from_a_row(env):
    T.snapshot()
    rows(env, [{"ctx": "\x1b]0;pwned\x07\x1b[2K100000"}] + [{"ctx": "100000"}] * 3)
    p = T.run("agent", "scout")
    assert p.returncode == 0 and "\x1b" not in p.stdout


# F3: the rows are not held to the learner's hostile-CSV filter (stack_limits.parse_row)
def test_f3_finite_out_of_range_values_do_not_crash(env):
    T.snapshot()
    rows(env, [{"ctx": "-1e308"}] * 10 + [{"ctx": "1e308"}])
    p = T.run("--session", SID)
    assert p.returncode == 0, p.stderr[-300:]


def test_f3_a_twice_compacted_segment_is_not_healthy(env):
    T.snapshot()
    rows(env, [{"ctx": "100000"}] * 5 + [{"ctx": "900000", "compacted": "2"}])
    assert T.js("agent", "scout")["ctx"]["n"] == 5


# F4: plan borrows the ambient session's snapshot when --session's is not ok
def test_f4_plan_does_not_borrow_the_ambient_session(env, tmp_path):
    T.snapshot()
    g = graph(tmp_path, {"job": "j", "nodes": [{"id": "A", "a": "scout", "n": 5}]})
    p = T.run("plan", g, "--session", OTHER, extra={"CLAUDE_SESSION_ID": SID})
    assert p.returncode == 0 and SID not in p.stdout, p.stdout.splitlines()[:1]


# F5: stack_sched.session_snapshot -> session_limits can write when the snapshot vanishes between two reads
def test_f5_model_load_never_writes_if_the_snapshot_vanishes(env, monkeypatch):
    T.snapshot()
    L = sys.modules["stack_limits"]
    S = T._load("stack_sched")
    snap = Path(L.snapshot_path(SID))
    real, calls = L.read_snapshot, []

    def racing(sid):
        calls.append(sid)
        if len(calls) == 2 and snap.exists():
            snap.unlink()                     # _prune_snapshots (or rm) between the check and session_limits' read
        return real(sid)
    monkeypatch.setattr(L, "read_snapshot", racing)
    monkeypatch.setattr(L, "_create_excl", lambda *a, **k: pytest.fail("a snapshot file was written"))
    monkeypatch.setattr(L, "log", lambda *a, **k: pytest.fail("limits.log was written"))
    S._SESSION_OVERRIDE = SID
    S.load_model(None)


# F6: malformed state files crash or refuse instead of degrading
@pytest.mark.parametrize("body", ["[1]", "[" * 100000], ids=["list", "deep"])
def test_f6_malformed_budget_json_degrades(env, body):
    T.snapshot()
    (env / SID).mkdir()
    (env / SID / "budget.json").write_text(body)
    p = T.run("--session", SID)
    assert p.returncode == 0, p.stderr[-300:]


def test_f6_deep_live_json_degrades(env):
    T.snapshot()
    (env / "limits" / "live.json").write_text("[" * 100000)
    p = T.run("--session", SID)
    assert p.returncode == 0, p.stderr[-300:]


def test_f6_odd_snapshot_name_does_not_hide_the_newest(env):
    T.snapshot()
    (env / "limits" / "snapshots" / "x y.json").write_text("{}")
    p = T.run()
    assert p.returncode == 0, p.stderr[-300:]


# L1: an unknown type that is a known type plus five characters is accepted
def test_l1_unknown_agent_type_is_refused(env):
    T.snapshot()
    assert T.run("agent", "scout12345").returncode == 1


# L2: a non-Apple interpreter caches the hooks' bytecode beside them (<config>/hooks/__pycache__)
def test_l2_no_bytecode_beside_the_hooks(env, tmp_path, monkeypatch):
    h = tmp_path / "hooks"
    shutil.copytree(T.HOOKS, h, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    T.run("--all", extra={"STACK_HOOKS_DIR": str(h)}, py=sys.executable)
    assert not (h / "__pycache__").exists()


# Cases the review named without a proof (F2 on fields parse_row keeps raw, F6 NaN snapshot, non-numeric snapshot
# values, huge n, malformed model rows)
def _resnap(mutate):
    """SID's snapshot with mutate(doc) applied and its hash recomputed: a hand-made snapshot that verifies."""
    L = sys.modules["stack_limits"]
    p = Path(L.snapshot_path(SID))
    doc = json.loads(p.read_text())
    mutate(doc)
    doc["hash"] = L.snap_hash(doc)
    p.chmod(0o600)                                                    # snapshots are written read-only
    p.write_text(json.dumps(doc))


def test_f2_no_control_characters_from_a_numeric_cell_parse_row_keeps(env):
    T.snapshot()
    rows(env, [{"ctx": "100000\x0c", "api_calls": "5\x0b\x1c"}] * 4)    # str.strip() whitespace: parse_row keeps it
    p = T.run("agent", "scout")
    assert p.returncode == 0 and not {"\x0b", "\x0c", "\x1c"} & set(p.stdout), p.stdout[-300:]


def test_f6_nan_in_a_snapshot_is_tamper(env):
    T.snapshot()
    p = Path(sys.modules["stack_limits"].snapshot_path(SID))
    doc = json.loads(p.read_text())
    doc["values"]["soft.agent.scout"] = float("nan")                  # no hash verifies it (allow_nan=False)
    p.chmod(0o600)
    p.write_text(json.dumps(doc))
    d = T.js("--session", SID)
    assert d["session"]["snapshot"] == "tamper" and d["session"]["values_from"] == "seed"


def test_f6_non_numeric_snapshot_values_and_origins_degrade(env):
    T.snapshot()
    _resnap(lambda d: (d["values"].update({"soft.agent.scout": "x", "turns.scout": [1], "hard.agent.scout": True}),
                       d["origin"].update({"soft.agent.scout": "\x1b[2Kenv", "turns.scout": 7}),
                       d.update(sched_policy="\x1b[2Kreport", live_version="\x1b[1A")))
    for args in (("--session", SID, "--all"), ("agent", "scout", "--session", SID)):
        p = T.run(*args)
        assert p.returncode == 0 and "\x1b" not in p.stdout, (args, p.stderr[-300:])
    a = T.js("agent", "scout", "--session", SID)
    assert a["soft"]["value"] is None and a["turns"]["value"] is None and a["hard"]["value"] is None


def test_f6_a_huge_node_size_is_refused_not_a_traceback(env, tmp_path):
    T.snapshot()
    g = graph(tmp_path, {"job": "j", "nodes": [{"id": "A", "a": "scout", "n": 10 ** 400}]})
    p = T.run("plan", g, "--session", SID)
    assert p.returncode == 1 and "Traceback" not in p.stderr, p.stderr[-300:]


@pytest.mark.parametrize("ctx", [{"a": [1], "b": [2]}, "abc"], ids=["list", "str"])
def test_f6_malformed_model_rows_are_refused_not_a_traceback(env, tmp_path, ctx):
    T.snapshot()
    t = json.loads((T.HOOKS / "sched_model.json").read_text())["types"]["scout"]
    t["ctx"] = ctx
    m = tmp_path / "m.json"
    m.write_text(json.dumps({"types": {"scout": t}}))
    g = graph(tmp_path, {"job": "j", "nodes": [{"id": "A", "a": "scout", "s": "M"}]})
    p = T.run("plan", g, "--session", SID, extra={"STACK_SCHED_MODEL": str(m)})
    assert p.returncode == 1 and "Traceback" not in p.stderr, p.stderr[-300:]


def test_f2_no_terminal_escapes_from_a_session_id(env, tmp_path):
    T.snapshot()
    g = graph(tmp_path, {"job": "j", "nodes": [{"id": "A", "a": "scout", "n": 5}]})
    for args in ((), ("agent", "scout"), ("plan", g)):
        p = T.run(*args, "--session", "\x1b[2K\rx")                  # fails ID_RE: "bad session id", still shown
        assert p.returncode == 0 and "\x1b" not in p.stdout and "\r" not in p.stdout, (args, p.stderr[-300:])
