"""Bayes scheduler estimates in stack_sched_refresh.py (WP4, docs/BAYES.md 2.2, B, A.9): load_bayes_sched and the
`bayes` argument of combine().

Run: uv run --python 3.13 --with pytest --with pandas --with numpy pytest -q tests/test_stack_sched_bayes.py
Tests B1-T13 (a valid sched block gives a model stack_sched.load_model accepts, method bayes; without one the output
is byte-equal to main's) and B1-T20 (hostile sched blocks: combine() and refresh() output equal to main's), the
promotion gate (SCHED_BAYES_LIVE, STACK_BAYES), and the mutants of the plan's WP4 row (each named in the test that
kills it). "main" is MAIN_REV's stack_sched_refresh.py (git show), run on the same inputs. Every test uses its own
XDG_STATE_HOME under tmp_path, never the stack's.
"""
import copy
import csv
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
pytest.importorskip("numpy")

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
AGENTS = ROOT / "dot-config" / "dot-claude" / "agents"
MAIN_REV = "47dce9f4"            # main before WP4
EID = "e" * 64
FIT = "0123456789abcdef"
NOW = "2026-10-08T12:00:00Z"
T0 = 1790000000


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load("stack_sched_refresh_wp4", HOOKS / "stack_sched_refresh.py")
L, U, D = R.L, R.U, R.D
S = _load("stack_sched_wp4", HOOKS / "stack_sched.py")
SHIPPED = json.loads((HOOKS / "sched_model.json").read_text())


@pytest.fixture(scope="module")
def M(tmp_path_factory):
    """stack_sched_refresh.py of main MAIN_REV, loaded on the same stack_limits, stack_usage and
    derive_sched_model modules as R."""
    p = subprocess.run(["git", "-C", str(ROOT), "show", f"{MAIN_REV}:dot-config/dot-claude/hooks/stack_sched_refresh.py"],
                       capture_output=True, check=False)
    if p.returncode != 0:
        pytest.skip(f"main {MAIN_REV} not in this checkout")
    d = tmp_path_factory.mktemp("main_hooks")
    (d / "stack_sched_refresh.py").write_bytes(p.stdout)
    saved_path, saved = list(sys.path), {k: sys.modules.get(k) for k in ("stack_limits", "stack_usage",
                                                                          "derive_sched_model")}
    sys.modules.update(stack_limits=L, stack_usage=U, derive_sched_model=D)
    try:
        mod = _load("stack_sched_refresh_main_" + MAIN_REV, d / "stack_sched_refresh.py")
    finally:
        sys.path[:] = saved_path
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
    assert not hasattr(mod, "load_bayes_sched")
    return mod


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith("STACK_") or k == "CLAUDE_SESSION_ID"]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    root = tmp_path / "st" / "claude-agent-stack"
    (root / "limits").mkdir(parents=True)
    return root


# ---------------------------------------------------------------- inputs
def entry(m, typed=True):
    """A valid sched-block entry (docs/BAYES.md 2.2) around turns median m."""
    e = {"turns": {"S": 0.6 * m, "M": m, "L": 3.0 * m}, "sec_per_call": {"p50": 12.0, "p90": 30.0},
         "ctx": {"a": 50000.0, "b": 1500.0}, "static_cc": 20000.0,
         "band": {"level": 0.9, "method": "bayes", "n_ref": m, "turns": {"lo": 0.75 * m, "med": m, "hi": 1.4 * m},
                  "sec_per_call": {"lo": 10.0, "med": 12.0, "hi": 15.0}, "ctx": {"lo": 0.85, "med": 1.0, "hi": 1.2}},
         "n_seg": 12, "n_agents": 5, "n_first": 6}
    if typed:
        e["status"] = "supported"
    return e


def bayes_doc(seed):
    """A bayes.json whose sched block is valid for `seed` and EID."""
    return {"schema_version": 1, "code": "stack_bayes/1", "generated": NOW, "evidence_id": EID,
            "seed_sha": seed["sha"], "fit_id": FIT, "models": {}, "vars": {},
            "sched": {"model_gate": {g: True for g in R.SCHED_GATES},
                      "types": {"scout": entry(7.0), "coder": entry(30.0), "rigger-animator": entry(25.0)},
                      "pools": {"lookup": entry(7.0, typed=False)},
                      "resume_ctx": {"alpha": 2000.0, "gamma": 300.0, "lo": [1000.0, 100.0], "hi": [4000.0, 600.0]},
                      "fixer": {"reread": 200000.0, "lo": 150000.0, "hi": 260000.0, "level": 0.95, "n": 9}}}


def new_fit():
    """A stand-in for fit() on collected rows: scout with 6 new segments, a new-only type."""
    sc = copy.deepcopy(SHIPPED["types"]["scout"])
    sc.update(n_seg=6, n_agents=3, n_first=3, turns={"S": 5.0, "M": 6.0, "L": 9.0}, maxTurns=40)
    sc["band"]["turns"] = {"lo": 5.0, "med": 6.0, "hi": 7.5}
    return {"types": {"scout": sc, "newbie": copy.deepcopy(sc)}, "pools": {}, "stack_hash": "sha256:" + "ab" * 32,
            "data_until": "2026-10-08T00:00:00Z"}


def dumps(J):
    return json.dumps(J, indent=1)


def write_bayes(st, doc, text=None):
    p = st / "limits" / "bayes.json"
    p.write_text(text if text is not None else json.dumps(doc))
    return str(p)


def write_inputs(st):
    """runs2.csv rows (scout and coder segments over two sessions) and proposals.json with EID."""
    usage = st / "usage"
    usage.mkdir(exist_ok=True)
    with open(usage / "runs2.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=U.COLUMNS)
        w.writeheader()
        for i in range(12):
            t, n = ("scout", 5 + i % 3) if i < 7 else ("coder", 20 + 3 * i)
            f0 = T0 + 1000 * i
            w.writerow(dict(U.EMPTY_ROW, schema_version="2", session=f"sess-{i % 2}", id=f"a{i:02d}", type=t,
                            seg="0", status="complete", api_calls=str(n), ctx=str(30000 * n), first_cc="18000",
                            first_ts=str(f0), last_ts=str(f0 + 9 * n), wall_s=str(9 * n), src="measured"))
    (st / "limits" / "proposals.json").write_text(json.dumps({"schema_version": 1, "evidence_id": EID,
                                                              "vars": {}, "pools": {}}))
    return str(usage)


def run_refresh(mod, st, monkeypatch, name):
    monkeypatch.setattr(mod, "now_iso", lambda: NOW)
    out = st / (name + ".json")
    mod.refresh(str(st / "usage"), str(out), str(HOOKS / "sched_model.json"), str(AGENTS),
                str(HOOKS / "agent_guard.py"), B=20)
    return out.read_bytes()


def seed_with(tmp_path, *types):
    """A seed file with extra types (each with turns, soft.agent and hard.agent variables), loaded."""
    doc = json.loads(Path(L.SEED_PATH).read_text())
    for t in types:
        doc["vars"]["turns." + t] = {"ceiling": 11, "floor": 5, "kind": "hard", "seed": 11, "unit": "turns"}
        doc["vars"]["soft.agent." + t] = dict(doc["vars"]["soft.agent.scout"])
        doc["vars"]["hard.agent." + t] = dict(doc["vars"]["hard.agent.scout"])
    p = tmp_path / "seed.json"
    p.write_text(json.dumps(doc))
    return str(p), L.load_seed(str(p))


# ---------------------------------------------------------------- hostile blocks (B1-T20)
def _set(path, value):
    def f(d):
        x = d
        for k in path[:-1]:
            x = x[k]
        x[path[-1]] = value
    return f


def _del(path):
    def f(d):
        x = d
        for k in path[:-1]:
            x = x[k]
        del x[path[-1]]
    return f


SC = ("sched",)
SCOUT = SC + ("types", "scout")
HOSTILE = {
    # the five of B1-T20
    "nan_ctx_a": _set(SCOUT + ("ctx", "a"), float("nan")),          # kills M2 (doc path; the file path is below)
    "nan_static_cc": _set(SCOUT + ("static_cc",), float("nan")),
    "lo_gt_med": _set(SCOUT + ("band", "turns", "lo"), 7.7),         # kills M1: med 7.0, hi 9.8
    "lo_gt_med_ctx": _set(SC + ("pools", "lookup", "band", "ctx", "lo"), 1.05),
    "S_gt_L": _set(SCOUT + ("turns", "S"), 22.0),
    "unknown_type": _set(SC + ("types", "no-such-agent"), entry(9.0)),
    "fixed_guard_type": _set(SC + ("types", "STACK_MAX_FANOUT"), entry(9.0)),
    "fixed_guard_pool": _set(SC + ("pools", "BLACKCAT_MAX_STEPS"), entry(9.0, typed=False)),
    "fixed_guard_key": _set(SCOUT + ("STACK_BAYES",), "on"),
    # the rest of the whole-block validation
    "inf_static_cc": _set(SCOUT + ("static_cc",), float("inf")),
    "zero_turns": _set(SCOUT + ("turns", "S"), 0.0),
    "negative_ctx_b": _set(SCOUT + ("ctx", "b"), -1.0),
    "bool_number": _set(SCOUT + ("static_cc",), True),
    "string_number": _set(SCOUT + ("turns", "M"), "7"),
    "p50_gt_p90": _set(SCOUT + ("sec_per_call", "p50"), 31.0),
    "hi_lt_med": _set(SCOUT + ("band", "sec_per_call", "hi"), 11.0),
    "band_method": _set(SCOUT + ("band", "method"), "combined"),
    "band_level": _set(SCOUT + ("band", "level"), 1.0),
    "band_missing_qty": _del(SCOUT + ("band", "ctx")),
    "float_count": _set(SCOUT + ("n_seg",), 12.0),
    "negative_count": _set(SCOUT + ("n_agents",), -1),
    "status": _set(SCOUT + ("status",), "pooled"),
    "pool_status": _set(SC + ("pools", "lookup", "status"), "supported"),
    "missing_key": _del(SCOUT + ("static_cc",)),
    "unknown_pool": _set(SC + ("pools", "no-such-pool"), entry(9.0, typed=False)),
    "gate_false": _set(SC + ("model_gate", "spc"), False),
    "gate_truthy": _set(SC + ("model_gate", "turns"), 1),
    "gate_missing": _del(SC + ("model_gate", "ctx_ab")),
    "sched_extra_key": _set(SC + ("extra",), {}),
    "sched_not_object": _set(SC, [1, 2]),
    "types_not_object": _set(SC + ("types",), []),
    "empty": lambda d: d["sched"].update(types={}, pools={}),
    "resume_lo_gt_hi": _set(SC + ("resume_ctx", "lo"), [5000.0, 100.0]),
    "fixer_outside": _set(SC + ("fixer", "reread"), 300000.0),
    "fixer_nan": _set(SC + ("fixer", "lo"), float("nan")),
    "other_evidence": _set(("evidence_id",), "f" * 64),
    "other_seed": _set(("seed_sha",), "sha256:" + "0" * 64),
    "schema_version": _set(("schema_version",), 2),
    "code": _set(("code",), "other/1"),
    "fit_id": _set(("fit_id",), "XYZ"),
}


def test_valid_block_is_accepted():
    """Positive control: the block every hostile case starts from validates, with its fit_id."""
    seed = L.load_seed()
    blk = R.load_bayes_sched("/nonexistent", EID, seed["sha"], seed=seed, doc=bayes_doc(seed))
    assert blk is not None and blk["fit_id"] == FIT
    assert sorted(blk["types"]) == ["coder", "rigger-animator", "scout"] and sorted(blk["pools"]) == ["lookup"]
    assert blk["types"]["scout"] == entry(7.0) and blk["fixer"]["n"] == 9


@pytest.mark.parametrize("case", sorted(HOSTILE))
def test_B1_T20_hostile_sched_block_combine_equals_main(case, M, st):
    """B1-T20: a hostile sched block -> load_bayes_sched None, combine() output equal to main's (byte for byte),
    no exception. Kills M1 (lo_gt_med*), M2 (nan_*), M3 (fixed_guard_*; see also the seed-type test)."""
    seed = L.load_seed()
    doc = bayes_doc(seed)
    HOSTILE[case](doc)
    blk = R.load_bayes_sched("/nonexistent", EID, seed["sha"], seed=seed, doc=doc)
    assert blk is None, case
    new = new_fit()
    today = dumps(M.combine(SHIPPED, new, ["s1"], 7))
    assert dumps(R.combine(SHIPPED, new, ["s1"], 7, blk)) == today
    assert dumps(R.combine(SHIPPED, new, ["s1"], 7)) == today
    assert "bayes.json ignored (sched)" in (st / "limits" / "limits.log").read_text()


def test_B1_T20_fixed_guard_name_that_is_a_seed_type(M, st, tmp_path):
    """A fixed-guard name that the seed does list as a type ("maxturns" -> MAXTURNS) is still refused: the
    fixed-guard check, not the seed-type check, drops it. Kills M3 (fixed-guard name accepted)."""
    _, seed = seed_with(tmp_path, "maxturns")
    assert "maxturns" in L._types(seed) and L.is_fixed_guard("maxturns")
    doc = bayes_doc(seed)
    doc["sched"]["types"]["maxturns"] = entry(9.0)
    blk = R.load_bayes_sched("/nonexistent", EID, seed["sha"], seed=seed, doc=doc)
    assert blk is None
    new = new_fit()
    assert dumps(R.combine(SHIPPED, new, [], 0, blk)) == dumps(M.combine(SHIPPED, new, [], 0))
    del doc["sched"]["types"]["maxturns"]                     # positive control on the same seed
    assert R.load_bayes_sched("/nonexistent", EID, seed["sha"], seed=seed, doc=doc) is not None


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_B1_T20_non_finite_in_the_file(token, st):
    """Through the file: NaN/Infinity tokens are refused at parse (stack_limits' parser), 1e999 parses to inf and
    is refused by the block check (kills M2b: the finite check removed)."""
    seed = L.load_seed()
    doc = bayes_doc(seed)
    doc["sched"]["types"]["scout"]["static_cc"] = 4242.25
    text = json.dumps(doc).replace("4242.25", token)
    assert token in text
    path = write_bayes(st, None, text)
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is None
    write_bayes(st, doc)
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is not None


def test_absent_unreadable_and_oversized_files(st):
    seed = L.load_seed()
    assert R.load_bayes_sched(str(st / "limits" / "none.json"), EID, seed["sha"], seed=seed) is None
    path = write_bayes(st, None, "{not json")
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is None
    path = write_bayes(st, None, " " * (L.BAYES_MAX_BYTES + 1))
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is None
    path = write_bayes(st, None, "[" * 100000 + "]" * 100000)
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is None
    doc = bayes_doc(seed)
    doc["sched"] = None                                      # no block: None, nothing logged
    path = write_bayes(st, doc)
    assert R.load_bayes_sched(path, EID, seed["sha"], seed=seed) is None
    assert R.load_bayes_sched(path, EID, None, seed=seed) is None


# ---------------------------------------------------------------- refresh() end to end (B1-T13, B1-T20)
def on(monkeypatch, live=True):
    monkeypatch.setenv("STACK_BAYES", "on")
    monkeypatch.setattr(R, "SCHED_BAYES_LIVE", live)


def test_B1_T13_no_block_refresh_byte_equal_to_main(M, st, monkeypatch):
    """B1-T13, second half: without a bayes.json (and with one but not promoted, or STACK_BAYES other than on)
    refresh() writes exactly main's bytes on a fixed input."""
    write_inputs(st)
    today = run_refresh(M, st, monkeypatch, "main")
    assert json.loads(today)["refresh"]["rows"] == 12
    assert run_refresh(R, st, monkeypatch, "absent") == today
    on(monkeypatch)
    assert run_refresh(R, st, monkeypatch, "absent_on") == today
    write_bayes(st, bayes_doc(L.load_seed()))
    monkeypatch.setattr(R, "SCHED_BAYES_LIVE", False)        # the shipped value: not promoted
    assert R.SCHED_BAYES_LIVE is False and run_refresh(R, st, monkeypatch, "not_live") == today
    monkeypatch.setattr(R, "SCHED_BAYES_LIVE", True)
    for mode in ("off", "shadow", "bogus"):
        monkeypatch.setenv("STACK_BAYES", mode)
        assert run_refresh(R, st, monkeypatch, "mode_" + mode) == today, mode


def test_shipped_promotion_gate_is_off():
    """BAYES.md 3.3: the scheduler's bayes method is promoted by a reviewed commit with the user's yes (WP6)."""
    src = (HOOKS / "stack_sched_refresh.py").read_text()
    assert "\nSCHED_BAYES_LIVE = False\n" in src


def test_B1_T13_valid_block_model_accepted_method_bayes(M, st, monkeypatch):
    """B1-T13, first half: a valid sched block, promoted and on -> refresh writes a model stack_sched.load_model
    accepts, with method bayes and the fit_id recorded, values bounded (x step) and rounded as today."""
    write_inputs(st)
    today = json.loads(run_refresh(M, st, monkeypatch, "main"))
    write_bayes(st, bayes_doc(L.load_seed()))
    on(monkeypatch)
    raw = run_refresh(R, st, monkeypatch, "with_bayes")
    J = json.loads(raw)
    assert J["refresh"]["bayes"] == {"method": "bayes", "fit_id": FIT, "types": ["coder", "rigger-animator", "scout"],
                                     "pools": ["lookup"]}
    m = S.load_model(str(st / "with_bayes.json"))
    assert m["file"] == str(st / "with_bayes.json")
    for grp, t in (("types", "scout"), ("types", "coder"), ("types", "rigger-animator"), ("pools", "lookup")):
        v = m[grp][t]
        assert v["band"]["method"] == "bayes" and v["band"]["fit_id"] == FIT, t
        assert v["turns"]["S"] <= v["turns"]["M"] <= v["turns"]["L"], t
        for q in ("turns", "sec_per_call", "ctx"):
            assert v["band"][q]["lo"] <= v["band"][q]["med"] <= v["band"][q]["hi"], (t, q)
        assert v["band"]["n_ref"] == v["turns"]["M"]
    # bounded(): the shipped scout M 5.0 cannot jump to the posterior's 7.0 (x 1.5 at most), then rounded()
    sc, sc0 = J["types"]["scout"], SHIPPED["types"]["scout"]
    assert sc["turns"]["M"] == round(min(7.0, 1.5 * sc0["turns"]["M"]), 1) == 7.0
    assert sc["turns"]["L"] == round(1.5 * sc0["turns"]["L"], 1)            # 21.0 wanted, x 1.5 allowed
    assert sc["n_seg"] == 12 and sc["n_agents"] == 5 and sc["status"] == "supported"
    assert J["types"]["rigger-animator"]["turns"] == {"S": 15.0, "M": 25.0, "L": 75.0}   # no previous value
    assert J["types"]["rigger-animator"]["status"] == "supported"
    # types the block does not name are main's
    for t in J["types"]:
        if t not in ("scout", "coder", "rigger-animator"):
            assert J["types"][t] == today["types"][t], t
    assert {k: v for k, v in J["refresh"].items() if k != "bayes"} == today["refresh"]
    assert S.tinfo(m, "scout")["turns"] == J["types"]["scout"]["turns"]


@pytest.mark.parametrize("case", ["nan_token", "lo_gt_med", "S_gt_L", "unknown_type", "fixed_guard_type",
                                  "fixed_guard_seed_type", "other_evidence"])
def test_B1_T20_hostile_refresh_byte_equal_to_main(case, M, st, monkeypatch, tmp_path):
    """B1-T20 through refresh() with the gate open: a hostile file -> main's bytes."""
    write_inputs(st)
    if case == "fixed_guard_seed_type":
        path, seed = seed_with(tmp_path, "maxturns")
        monkeypatch.setattr(L, "SEED_PATH", path)
    seed = L.load_seed()
    today = run_refresh(M, st, monkeypatch, "main")
    doc = bayes_doc(seed)
    text = None
    if case == "nan_token":
        doc["sched"]["types"]["scout"]["ctx"]["a"] = float("nan")
        text = json.dumps(doc)
        assert "NaN" in text
    elif case == "fixed_guard_seed_type":
        doc["sched"]["types"]["maxturns"] = entry(9.0)
    else:
        HOSTILE[case](doc)
    write_bayes(st, doc, text)
    on(monkeypatch)
    assert run_refresh(R, st, monkeypatch, "hostile") == today
    assert "bayes.json ignored (sched)" in (st / "limits" / "limits.log").read_text()


def test_bayes_sched_never_raises(st, monkeypatch):
    on(monkeypatch)
    write_bayes(st, bayes_doc(L.load_seed()))
    assert R.bayes_sched() is None                          # no proposals.json: no evidence id
    (st / "limits" / "proposals.json").write_text(json.dumps({"schema_version": 1, "evidence_id": EID,
                                                              "vars": {}, "pools": {}}))
    assert R.bayes_sched()["fit_id"] == FIT
    monkeypatch.setattr(L, "SEED_PATH", "/nonexistent/seed.json")
    assert R.bayes_sched() is None                          # SeedError: today's path


def test_stdlib_only_reader():
    """The new reader adds no import: stack_sched_refresh.py's imports are main's."""
    import ast
    src = (HOOKS / "stack_sched_refresh.py").read_text()
    mods = sorted({a.name for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Import) for a in n.names}
                  | {n.module for n in ast.walk(ast.parse(src)) if isinstance(n, ast.ImportFrom)})
    assert mods == ["argparse", "copy", "derive_sched_model", "json", "math", "os", "pandas", "stack_io",
                    "stack_limits", "stack_usage", "sys"]
