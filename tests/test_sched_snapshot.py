"""S6 step 4: stack_sched and the refresh read only the session-start limits snapshot (U4).

Run: uv run --python 3.12 --with pytest --with pandas --with numpy pytest -q tests/test_sched_snapshot.py
Every test uses a temp XDG_STATE_HOME; nothing touches the real state folder.
"""
import ast
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-claude" / "hooks"
sys.path[:0] = [str(HOOKS), str(ROOT / "tests")]


def _load(name, path, register=False):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    if register:
        sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = sys.modules.get("stack_limits") or _load("stack_limits", HOOKS / "stack_limits.py", register=True)
S = _load("stack_sched_snapshot_test", HOOKS / "stack_sched.py", register=True)
SID1, SID2 = "11111111-1111-4111-8111-111111111111", "22222222-2222-4222-8222-222222222222"


def model_doc(m):
    return {"version": 1, "generated": "2026-10-03T00:00:00Z", "stack_hash": "sha256:" + "ab" * 32,
            "types": {"scout": {"turns": {"S": m, "M": m + 1, "L": m + 2}, "soft_limit": None}}}


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith("STACK_") or k == "CLAUDE_SESSION_ID"]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    L._ENV_WARNED.clear()
    S._LIMITS_MOD = L
    S._SESSION_OVERRIDE = None
    root = tmp_path / "st" / "claude-agent-stack"
    root.mkdir(parents=True)
    return root


def report(sid_env):
    os.environ["CLAUDE_SESSION_ID"] = sid_env
    m = S.load_model()
    return {"path": str(S.default_model_path()), "file": m["file"], "scout": S.tinfo(m, "scout"),
            "soft": dict(m["soft_values"]), "src": m["soft_source"], "policy": m["sched_policy"],
            "prompt": S.prompt_limit(m, ["orchestrator"]), "model_sha": hashlib.sha256(Path(m["file"]).read_bytes()).hexdigest()}


def test_T21_single_swap_stack_sched_reads_only_the_session_snapshot(st, tmp_path, monkeypatch):
    import pandas  # noqa: F401  (the refresh needs it)
    R = _load("stack_sched_refresh_t21", HOOKS / "stack_sched_refresh.py")
    cand = st / "sched_model.json"
    cand.write_text(json.dumps(model_doc(3)))
    path1, _ = L.apply_and_snapshot({"session_id": SID1, "source": "startup"}, spawn=False)
    assert path1 and os.path.exists(path1)
    before = report(SID1)
    assert before["src"] == "snapshot" and before["path"].endswith(SID1 + ".sched_model.json")
    assert before["scout"]["turns"] == {"S": 3, "M": 4, "L": 5} and before["policy"] == "fresh_fixer"
    snap_before = Path(path1).read_bytes()

    # mid-session: live.json, proposals.json, the candidate model, new rows, propose, the refresh
    seed = L.load_seed()
    live = L.live_from_seed(seed)
    live["vars"]["soft.agent.scout"]["value"] = 777000
    live["version"] = 99
    (st / "limits" / "live.json").write_text(json.dumps(live))
    (st / "limits" / "proposals.json").write_text(json.dumps({"schema_version": 1, "vars": {"soft.agent.scout": {}}}))
    cand.write_text(json.dumps(model_doc(9)))
    import stack_usage as U
    usage = st / "usage"
    usage.mkdir()
    row = dict(U.EMPTY_ROW, schema_version="2", session=SID1, id="a1", type="scout", seg="0", status="complete",
               api_calls="6", ctx="300000", first_ts="1000", last_ts="1100", wall_s="100", src="measured")
    import csv
    with open(usage / "runs2.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=U.COLUMNS)
        w.writeheader()
        w.writerow(row)
    L.propose()
    R.refresh(str(usage), str(cand), str(HOOKS / "sched_model.json"), str(ROOT / "dot-claude" / "agents"),
              str(HOOKS / "agent_guard.py"), B=20, sid=SID1)
    refreshed = json.loads(cand.read_text())
    assert refreshed["refresh"]["rows"] == 1                    # the refresh read the runs2.csv row
    assert report(SID1) == before                                # nothing stack_sched reports moved
    assert Path(path1).read_bytes() == snap_before

    # a new session's snapshot is the swap
    monkeypatch.setenv("STACK_SOFTCTX_SCOUT", "123000")
    path2, _ = L.apply_and_snapshot({"session_id": SID2, "source": "startup"}, spawn=False)
    after = report(SID2)
    assert path2 != path1 and after["path"].endswith(SID2 + ".sched_model.json")
    assert after["file"] != before["file"] and after["model_sha"] != before["model_sha"]
    assert after["scout"]["soft_limit"] == 123000 and before["scout"]["soft_limit"] != 123000
    assert report(SID1) == before                                # and the first session still reads its own


def test_model_resolution_order(st, monkeypatch, tmp_path):
    cand = st / "sched_model.json"
    cand.write_text(json.dumps(model_doc(3)))
    shipped = (HOOKS / "sched_model.json").resolve()
    monkeypatch.setenv("CLAUDE_SESSION_ID", SID1)
    assert S.default_model_path() == shipped                     # no snapshot yet: shipped, never the candidate
    L.apply_and_snapshot({"session_id": SID1, "source": "startup"}, spawn=False)
    snap_model = Path(L.snapshot_path(SID1)).with_name(SID1 + ".sched_model.json")
    assert S.default_model_path() == snap_model
    monkeypatch.delenv("CLAUDE_SESSION_ID")
    monkeypatch.setenv("STACK_LIMITS_SNAPSHOT", L.snapshot_path(SID1))
    assert S.default_model_path() == snap_model                  # sid from the exported snapshot path
    other = tmp_path / "m.json"
    other.write_text(json.dumps(model_doc(1)))
    monkeypatch.setenv("STACK_SCHED_MODEL", str(other))
    assert S.default_model_path() == other                       # the explicit override wins
    monkeypatch.delenv("STACK_SCHED_MODEL")
    Path(L.snapshot_path(SID1)).chmod(0o644)
    Path(L.snapshot_path(SID1)).write_text("{}")                 # tampered snapshot: shipped, no candidate
    assert S.default_model_path() == shipped


def test_soft_limits_source_snapshot_then_seed_then_constants(st, monkeypatch):
    seed = L.load_seed()
    assert S.soft_values()["source"] == "seed"
    assert S.soft_values()["values"]["soft.agent.scout"] == seed["vars"]["soft.agent.scout"]["seed"]
    monkeypatch.setenv("STACK_SOFTCTX_SCOUT", "250000")
    L.apply_and_snapshot({"session_id": SID1, "source": "startup"}, spawn=False)
    monkeypatch.delenv("STACK_SOFTCTX_SCOUT")
    monkeypatch.setenv("CLAUDE_SESSION_ID", SID1)
    sv = S.soft_values()
    assert sv["source"] == "snapshot" and sv["values"]["soft.agent.scout"] == 250000
    # no snapshot, no seed: the constants
    monkeypatch.setenv("CLAUDE_SESSION_ID", SID2)
    monkeypatch.setattr(L, "SEED_PATH", str(st / "nope.json"))
    sv = S.soft_values()
    assert sv["source"] == "constants" and sv["values"]["soft.agent.scout"] == S.SOFT_LIMITS["scout"]
    m = S.load_model("/nonexistent")
    assert S.tinfo(m, "build-fixer")["soft_limit"] == S.SOFT_POOLS["builder"]      # constants keep the pool rule


def test_constants_match_the_seed():
    """The fallback constants are the seed's values (which equal agent_guard.py's, test_stack_limits)."""
    seed = L.load_seed()
    for t, v in S.SOFT_LIMITS.items():
        assert seed["vars"]["soft.agent." + t]["seed"] == v, t
    assert seed["vars"]["soft.prompt"]["seed"] == S.SOFT_PROMPT_CTX
    for t, v in S.SOFT_PROMPT_CTX_BY_TYPE.items():
        assert seed["vars"]["soft.prompt." + t]["seed"] == v


def test_orchestrator_prompt_limit_follows_the_snapshot(st, monkeypatch):
    monkeypatch.setenv("STACK_SOFT_PROMPT_CTX", "40000000")
    L.apply_and_snapshot({"session_id": SID1, "source": "startup"}, spawn=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", SID1)
    m = S.load_model()
    assert S.prompt_limit(m, ["coder"]) == 40000000
    assert S.prompt_limit(m, ["coder", "orchestrator"]) == 80000000


GRAPH = {"nodes": [{"id": "A", "a": "coder", "n": 5}, {"id": "B", "a": "coder", "n": 5, "dep": ["A"], "resume": "A"}]}


def _advice(policy, gap, tmp_path):
    g = S.load_graph(GRAPH)
    m = S.load_model(str(HOOKS / "sched_model.json"))
    m["sched_policy"] = policy
    state = {"nodes": {"A": {"status": "done", "end": 1000.0}}, "now": 1000.0 + gap}
    sched = S.schedule(g, m)
    ready = S.next_ready(g, state, sched)
    return ready, S.next_advice(g, state, sched, m, ready), m


def test_next_advises_a_fresh_fixer_for_a_cold_resume(tmp_path):
    ready, adv, m = _advice("fresh_fixer", S.RESUME_WARM_S + 30, tmp_path)
    assert ready == ["B"] and len(adv) == 1 and adv[0]["action"] == "fresh_fixer" and adv[0]["resume"] == "A"
    kw, _ = S.kappas(m, "coder")
    assert adv[0]["cost"] == pytest.approx(kw * (S.tinfo(m, "coder")["static_cc"] + m["fixer"]["reread"]))
    assert adv[0]["reread"] == m["fixer"]["reread"]
    assert _advice("fresh_fixer", S.RESUME_WARM_S - 30, tmp_path)[1] == []     # warm: no advice
    assert _advice("report", S.RESUME_WARM_S + 30, tmp_path)[1] == []          # report policy: advice only off


def test_next_cli_keeps_stdout_and_advises_on_stderr(st, tmp_path):
    import subprocess
    (tmp_path / "g.json").write_text(json.dumps(GRAPH))
    (tmp_path / "s.json").write_text(json.dumps({"nodes": {"A": {"status": "done", "end": 1000.0}}, "now": 1500.0}))
    env = dict(os.environ, XDG_STATE_HOME=str(tmp_path / "st"))
    for k in [k for k in env if k.startswith("STACK_")]:
        env.pop(k)
    cmd = [sys.executable, str(HOOKS / "stack_sched.py"), "next", str(tmp_path / "g.json"), str(tmp_path / "s.json")]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    assert p.returncode == 0 and json.loads(p.stdout) == ["B"] and "fresh fixer" in p.stderr
    env["STACK_SCHED_POLICY"] = "report"
    # report is read from the snapshot in a session; outside one the env knob applies
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)
    assert json.loads(p.stdout) == ["B"] and p.stderr == ""


def test_refresh_frame_skips_main_rows_and_empty_cells():
    import stack_usage as U
    R = _load("stack_sched_refresh_frame", HOOKS / "stack_sched_refresh.py")
    base = dict(U.EMPTY_ROW, schema_version="2", session=SID1, status="complete", api_calls="5", ctx="1000",
                first_ts="10", last_ts="20", src="measured", stack_commit="abcdef1")
    rows = {(SID1, "a", 0): dict(base, id="a", type="scout", seg="0"),
            (SID1, "main", 0): dict(base, id="main", type="blackcat", seg="0", is_main="1"),
            (SID1, "b", 0): dict(base, id="b", type="scout", seg="0", api_calls=""),
            (SID1, "c", 0): dict(base, id="c", type="scout", seg="0", first_cc="")}
    df = R.frame(rows)
    assert sorted(df.id) == ["a", "c"] and set(df.src) == {"measured"} and df.stack_commit.iloc[0] == "abcdef1"
    assert df[df.id == "c"].first_cc.isna().all()                  # an empty cell stays NaN, never imputed


def test_derive_helpers_are_the_shared_core():
    import derive_thresholds as DT
    assert DT.q is L.q and DT.ceil2 is L.ceil2
    d = DT.derive([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], list("abcdef"))
    e = L.derive([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], list("abcdef"))
    assert {k: v for k, v in d.items() if k != "ci"} == {k: v for k, v in e.items() if k != "ci"}
    assert DT.derive([1.0, 2.0], ["a", "b"])["ci"][0] != DT.derive([1.0, 2.0], ["a", "b"])["ci"][0]   # NaN pair


def test_derive_sched_model_reads_the_seed_json(tmp_path):
    import derive_sched_model as D
    guard = HOOKS / "agent_guard.py"
    assert D.soft_limits_auto(str(guard)) == {t: v for t, v in D.soft_limits(str(guard)).items() if t != "blackcat"}
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"vars": {"soft.agent.scout": {"seed": 5}, "turns.scout": {"seed": 1}}}))
    assert D.soft_limits_auto(str(guard), str(seed)) == {"scout": 5}
    seed.write_text("not json")                                     # unreadable: the AST read of the guard
    assert D.soft_limits_auto(str(guard), str(seed)) == D.soft_limits(str(guard))


def test_hooks_only_import_the_stdlib():
    for f in ("stack_sched.py",):
        tree = ast.parse((HOOKS / f).read_text())
        mods = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        mods |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert not mods & {"pandas", "numpy", "scipy"}, mods
