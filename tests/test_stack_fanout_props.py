"""stack_fanout.py: independent unit, property, fuzz and simulation tests (dynamic fan-out plan, step 5a).

Written from the plan (rules R1-R9, D0-D4), not from tests/test_stack_fanout.py. Stdlib `random` with
fixed seeds, no sleeps, no wall clocks (the one timing test takes the best of three runs).

Run: uv run --no-project --python 3.13 --with-requirements requirements/tools.txt \
         pytest -q tests/test_stack_fanout_props.py tests/test_stack_fanout.py

STACK_FANOUT_UNDER_TEST=<path> points the suite at a mutated copy of the module (mutation proofs).
"""
import copy
import heapq
import importlib.util
import itertools
import json
import math
import os
import random
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = Path(os.environ.get("STACK_FANOUT_UNDER_TEST") or ROOT / "dot-claude" / "hooks" / "stack_fanout.py")
_spec = importlib.util.spec_from_file_location("stack_fanout_props_target", MOD)
F = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(F)

ROW = ["coder", "main-coder", "ninja-coder", "verifier", "code-reviewer", "python-engineer"]
ALL_TERMS = "node,deps,conflict,budget,aimd"
GARBAGE = [None, float("nan"), float("inf"), -float("inf"), -1, 0, 1, 2 ** 70, -2 ** 70, 1.5, "x", "",
           [], {}, True, False, b"b", (1,), object(), [[]], {"a": 1}]
M = 1_000_000


# ------------------------------------------------------------------ helpers
def kn(mode="enforce", terms=ALL_TERMS, **env):
    e = {"STACK_FANOUT_DYN": mode, "STACK_FANOUT_DYN_ENFORCE": terms}
    e.update({("STACK_FANOUT_DYN_" + k.upper()): str(v) for k, v in env.items()})
    k, warnings = F.parse_knobs(e)
    assert warnings == [], warnings
    return k


def mkplan(nodes, **top):
    return F.parse_plan(dict({"job": "J1", "nodes": nodes}, **top), ROW)


def dec(k, plan=None, nodes=None, node_id=None, child="coder", n=0, c_ceil=32, kind="spawn",
        caller="o1", ctype="orchestrator", **kw):
    return F.dyn_decision(k, kind, caller, ctype, c_ceil, n, child, plan=plan, nodes=nodes,
                          node_id=node_id, **kw)


def model_1m(t="coder"):
    """A sched model whose c_med(t) is exactly 1,000,000 context tokens."""
    return {"types": {t: {"turns": {"M": 10}, "ctx": {"a": 100000, "b": 0}}}}


def rand_dag(rng, shape, n_nodes=None):
    n = n_nodes or rng.randint(1, 32)
    ids = ["T%d" % i for i in range(n)]
    nodes = []
    for i, nid in enumerate(ids):
        if shape == "chain":
            dep = [ids[i - 1]] if i else []
        elif shape == "wide":
            dep = []
        elif shape == "diamond":
            dep = [] if i == 0 else ([ids[0]] if i < n - 1 else ids[1:i])
        else:
            dep = rng.sample(ids[:i], rng.randint(0, min(3, i)))
        nd = {"id": nid, "a": rng.choice(["coder", "main-coder", "verifier"]), "dep": dep}
        if rng.random() < 0.5:
            nd["w"] = ["src/g%d/*" % rng.randint(0, 3)]
        if rng.random() < 0.15:
            nd["r"] = ["accel"]
        nodes.append(nd)
    return {"job": "J1", "nodes": nodes}


def rand_plan(rng, max_nodes=10):
    top = rand_dag(rng, rng.choice(["chain", "wide", "diamond", "layered"]), rng.randint(1, max_nodes))
    if rng.random() < 0.5:
        top["slack"] = rng.randint(0, 4)
    return F.parse_plan(top, ROW)


def rand_state(rng, plan):
    """A node state built only through the public API, plus the live lease and child id sets."""
    st, lt, lc, i = F.nodes_new(plan["job"]), set(), set(), 0
    for nd in plan["nodes"] + [None] * rng.randint(0, 4):
        for _ in range(rng.choice([0, 0, 1, 1, 2, 8]) if nd else 1):
            i += 1
            tid = "t%d" % i
            st = F.record_spawn(st, nd["id"] if nd else None, tid, "coder", float(i), iso=rng.random() < 0.3)
            kind = rng.choice(["abort", "lease", "child", "ended"])
            if kind == "lease":
                lt.add(tid)
            elif kind in ("child", "ended"):
                cid = "c%d" % i
                st, _ = F.bind_child(st, tid, cid)
                if kind == "child":
                    lc.add(cid)
                else:
                    st, _ = F.end_run(st, cid, float(i) + 1, "ok")
    return st, lt, lc


def rand_env(rng, mode=None):
    terms = [t for t in F.ENFORCE_TERMS if rng.random() < 0.6] or ["node"]
    env = {"STACK_FANOUT_DYN": mode or rng.choice(["off", "shadow", "enforce"]),
           "STACK_FANOUT_DYN_ENFORCE": ",".join(terms),
           "STACK_FANOUT_DYN_W0": str(rng.randint(1, 40)), "STACK_FANOUT_DYN_WMIN": str(rng.randint(1, 4)),
           "STACK_FANOUT_DYN_SLACK": str(rng.randint(0, 5)),
           "STACK_FANOUT_DYN_RESERVE_TOK": str(rng.choice([0, 8 * M, 30 * M])),
           "STACK_FANOUT_DYN_NODE_RUNS": str(rng.randint(1, 9))}
    return env


def rand_call(rng, mode=None):
    plan = rand_plan(rng) if rng.random() < 0.85 else None
    st, lt, lc = rand_state(rng, plan) if plan else (F.nodes_new(), set(), set())
    node_id = None
    if plan and rng.random() < 0.8:
        node_id = rng.choice(plan["nodes"])["id"]
    return {"env": rand_env(rng, mode), "kind": rng.choice(["spawn", "spawn", "resume"]),
            "caller": "o1", "caller_type": "orchestrator",
            "c_ceil": rng.choice([0, 1, 2, 3, 8, 32]), "n": rng.randint(0, 40),
            "child_type": rng.choice(["coder", "main-coder", "verifier", "weird-type"]),
            "plan": plan, "nodes": st, "node_id": node_id, "isolation": rng.choice([None, "worktree"]),
            "live_tids": lt, "live_children": lc,
            "b_rem": rng.choice([None, -5 * M, 0, 5 * M, 30 * M, 70 * M, 10 ** 9]),
            "commit": rng.choice([0.0, 2.0 * M, 40.0 * M]),
            "model": None, "aimd": rng.choice([None, {"w": rng.randint(-2, 40), "last_dec": None}]),
            "k_sess": rng.choice([None, rng.randint(-3, 40)])}


def run_call(c, env=None):
    k = F.parse_knobs(env or c["env"])[0]
    return F.dyn_decision(k, c["kind"], c["caller"], c["caller_type"], c["c_ceil"], c["n"], c["child_type"],
                          plan=c["plan"], nodes=c["nodes"], node_id=c["node_id"], isolation=c["isolation"],
                          live_tids=c["live_tids"], live_children=c["live_children"], b_rem=c["b_rem"],
                          commit=c["commit"], model=c["model"], aimd=c["aimd"], k_sess=c["k_sess"])


def with_mode(env, mode, terms=None):
    e = dict(env, STACK_FANOUT_DYN=mode)
    if terms:
        e["STACK_FANOUT_DYN_ENFORCE"] = terms
    return e


# ------------------------------------------------------------------ knobs (R9)
def test_knob_names_and_plan_defaults():
    assert len(F.KNOBS) == 14 and len(set(F.KNOBS)) == 14
    assert all(n.startswith("STACK_FANOUT_DYN") for n in F.KNOBS)
    k, w = F.parse_knobs({})
    assert w == []
    assert (k["mode"], k["enforce"], k["types"]) == ("shadow", ("node", "deps"), ("orchestrator",))
    assert (k["w0"], k["wmin"], k["alpha"]) == (8, 1, 1)
    assert (k["beta_rl"], k["beta_fail"], k["hold_s"]) == (0.5, 0.75, 60)
    assert (k["reserve_tok"], k["slack"], k["node_runs"]) == (8_000_000, 2, 6)
    assert (k["delay_ratio"], k["breaker"]) == (1.5, (5, 600))


@pytest.mark.parametrize("name", sorted(F.KNOB_DEFAULTS))
def test_invalid_knob_value_takes_default_and_is_never_echoed(name):
    k0 = F.parse_knobs({})[0]
    k, w = F.parse_knobs({name: "zz-secret-9!"})
    assert k == k0
    assert len(w) == 1 and name in w[0] and "zz-secret-9" not in w[0]


@pytest.mark.parametrize("env,key,want", [
    ({"STACK_FANOUT_DYN_BETA_RL": "0"}, "beta_rl", 0.5), ({"STACK_FANOUT_DYN_BETA_RL": "1.5"}, "beta_rl", 0.5),
    ({"STACK_FANOUT_DYN_BETA_RL": "1"}, "beta_rl", 1.0), ({"STACK_FANOUT_DYN_BETA_FAIL": "nan"}, "beta_fail", 0.75),
    ({"STACK_FANOUT_DYN_W0": "0"}, "w0", 8), ({"STACK_FANOUT_DYN_W0": "1025"}, "w0", 8),
    ({"STACK_FANOUT_DYN_W0": "8.0"}, "w0", 8), ({"STACK_FANOUT_DYN_W0": "12"}, "w0", 12),
    ({"STACK_FANOUT_DYN_NODE_RUNS": "0"}, "node_runs", 6), ({"STACK_FANOUT_DYN_NODE_RUNS": "33"}, "node_runs", 6),
    ({"STACK_FANOUT_DYN_NODE_RUNS": "32"}, "node_runs", 32),
    ({"STACK_FANOUT_DYN_ENFORCE": "node,bogus"}, "enforce", ("node", "deps")),
    ({"STACK_FANOUT_DYN_ENFORCE": "budget, aimd"}, "enforce", ("budget", "aimd")),
    ({"STACK_FANOUT_DYN": "enforce,shadow"}, "mode", "shadow"), ({"STACK_FANOUT_DYN": "bogus"}, "mode", "shadow"),
    ({"STACK_FANOUT_DYN": "off"}, "mode", "off"), ({"STACK_FANOUT_DYN": ""}, "mode", "shadow"), ({"STACK_FANOUT_DYN": "ENFORCE"}, "mode", "enforce"),
    ({"STACK_FANOUT_DYN_DELAY_RATIO": "1.0"}, "delay_ratio", 1.5),
    ({"STACK_FANOUT_DYN_HOLD_S": "inf"}, "hold_s", 60), ({"STACK_FANOUT_DYN_HOLD_S": "0"}, "hold_s", 0.0),
    ({"STACK_FANOUT_DYN_BREAKER": "0/600"}, "breaker", (0, 600)), ({"STACK_FANOUT_DYN_BREAKER": "3/90s"}, "breaker", (3, 90)),
    ({"STACK_FANOUT_DYN_BREAKER": "x"}, "breaker", (5, 600)),
    ({"STACK_FANOUT_DYN_TYPES": "Orchestrator, main-coder"}, "types", ("orchestrator", "main-coder")),
    ({"STACK_FANOUT_DYN_TYPES": "bad type!"}, "types", ("orchestrator",)),
    ({"STACK_FANOUT_DYN_SLACK": "-1"}, "slack", 2), ({"STACK_FANOUT_DYN_ALPHA": "0"}, "alpha", 0),
    ({"STACK_FANOUT_DYN_RESERVE_TOK": "-5"}, "reserve_tok", 8_000_000),
    ({"STACK_FANOUT_DYN_W0": ""}, "w0", 8), ({"STACK_FANOUT_DYN_W0": "   "}, "w0", 8),
])
def test_knob_ranges(env, key, want):
    assert F.parse_knobs(env)[0][key] == want


@pytest.mark.parametrize("val", ["off", "OFF", " off "])
def test_stack_policy_off_forces_mode_off(val):
    assert F.parse_knobs({"STACK_FANOUT_DYN": "enforce", "STACK_POLICY": val})[0]["mode"] == "off"
    assert F.parse_knobs({"STACK_FANOUT_DYN": "enforce", "STACK_POLICY": "on"})[0]["mode"] == "enforce"


def test_parse_knobs_fuzz_never_raises_and_stays_in_range():
    rng = random.Random(101)
    strs = ["", " ", "nan", "inf", "-inf", "-1", "0", "1", "2", "1e999", "0x10", "9" * 40, "a/b", "5/600",
            "enforce", "shadow", "off", "node,deps", "coder", "\x00", "ü", "1.5"]
    for _ in range(500):
        env = {name: rng.choice(strs + GARBAGE) for name in F.KNOBS if rng.random() < 0.7}
        if rng.random() < 0.3:
            env["STACK_POLICY"] = rng.choice(strs + GARBAGE)
        snapshot = copy.copy(env)
        k, w = F.parse_knobs(env)
        assert env == snapshot or any(isinstance(v, float) and v != v for v in env.values())
        assert k["mode"] in F.MODES and 1 <= k["w0"] <= 1024 and 1 <= k["wmin"] <= 1024
        assert 0 <= k["alpha"] <= 64 and 0 < k["beta_rl"] <= 1 and 0 < k["beta_fail"] <= 1
        assert math.isfinite(k["hold_s"]) and 0 <= k["slack"] <= 32 and 1 <= k["node_runs"] <= 32
        assert 1 < k["delay_ratio"] <= 1000 and k["reserve_tok"] >= 0 and set(k["enforce"]) <= set(F.ENFORCE_TERMS)
        assert len(w) <= len(F.KNOBS)
    for junk in GARBAGE:
        assert F.parse_knobs(junk)[0]["mode"] in F.MODES


# ------------------------------------------------------------------ scope (R2)
@pytest.mark.parametrize("caller,ctype", [("main", "orchestrator"), ("", "orchestrator"), (None, "orchestrator"),
                                          ("o1", "blackcat"), ("o1", "main"), ("o1", ""), ("o1", None),
                                          ("o1", "coder"), ("o1", "main-coder")])
def test_only_orchestrator_in_scope_even_when_types_lists_everyone(caller, ctype):
    wide = kn(terms=ALL_TERMS, types="orchestrator,blackcat,main,coder,main-coder")
    narrow = kn()
    assert not F.in_scope(caller, ctype, 32, narrow)
    if ctype not in ("blackcat", "main", "", None) and caller:
        assert F.in_scope(caller, ctype, 32, wide) == (ctype in ("coder", "main-coder"))
    else:
        assert not F.in_scope(caller, ctype, 32, wide)


def test_in_scope_positive_and_negative_cases():
    k = kn()
    assert F.in_scope("o1", "orchestrator", 32, k)
    assert not F.in_scope("o1", "orchestrator", 0, k)            # no static cap: dyn off
    assert not F.in_scope("o1", "orchestrator", -3, k)
    assert not F.in_scope("o1", "orchestrator", 32, kn("off"))
    assert not F.in_scope("o1", "orchestrator", 32, None)
    assert not F.in_scope("o1", "orchestrator", 32.0, k)


def test_main_thread_and_blackcat_get_the_static_decision_whatever_the_plan_says():
    plan = mkplan([{"id": "A", "a": "coder"}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "t1", "coder", 1.0)     # A already has a live run
    for caller, ctype in [("main", "orchestrator"), ("", None), ("bc", "blackcat"), ("c1", "coder")]:
        d = dec(kn(), plan, st, "A", n=1, caller=caller, ctype=ctype, live_tids={"t1"}, b_rem=-1.0,
                aimd={"w": 1})
        assert d["allow"] and d["binding"] == "scope" and d["fallback"] and d["code"] is None
        assert d["cap"] == 32 and d["terms"] == {"ceil": 32}
    d = dec(kn(), plan, st, "A", n=1, live_tids={"t1"})
    assert not d["allow"] and d["code"] == "running"


# ------------------------------------------------------------------ plan parsing (D1)
def test_parse_plan_accepts_and_normalizes():
    p = F.parse_plan(json.dumps({"job": "j-1.x", "slack": 3, "nodes": [
        {"id": "A", "a": "coder", "alt": "main-coder", "dep": ["B", "B"], "w": ["src/*"], "r": ["gui", "accel", "gui"]},
        {"id": "B", "a": "verifier", "s": "L", "n": 4}]}), ROW)
    assert p["job"] == "j-1.x" and p["slack"] == 3 and len(p["nodes"]) == 2
    a, b = p["nodes"]
    assert a["dep"] == ["B"] and a["r"] == ["accel", "gui"] and a["w"] == ["src/*"] and a["rd"] == []
    assert a["alt"] == "main-coder" and b["alt"] is None and b["dep"] == []
    assert p["width"] == 1


def test_parse_plan_width_diamond_and_wide():
    d = F.parse_plan({"job": "d", "nodes": [{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]},
                                            {"id": "C", "a": "coder", "dep": ["A"]},
                                            {"id": "D", "a": "coder", "dep": ["B", "C"]}]})
    assert d["width"] == 2
    w = F.parse_plan(rand_dag(random.Random(1), "wide", 32))
    assert w["width"] == 32


def test_parse_plan_accepts_str_bytes_and_dict_and_does_not_alias_or_mutate_input():
    raw = {"job": "j", "nodes": [{"id": "A", "a": "coder", "dep": [], "w": ["a/*"]},
                                 {"id": "B", "a": "coder", "dep": ["A"]}]}
    snap = copy.deepcopy(raw)
    p1 = F.parse_plan(raw)
    p1["nodes"][1]["dep"].append("ZZ")
    p1["nodes"][0]["w"].append("zz")
    assert raw == snap
    assert F.parse_plan(json.dumps(raw)) == F.parse_plan(json.dumps(raw).encode()) == F.parse_plan(raw)


def _base():
    return {"job": "j", "nodes": [{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]}]}


def _with(**node_edits):
    p = _base()
    p["nodes"][1].update(node_edits)
    return p


def _top(**edits):
    p = _base()
    p.update(edits)
    return p


REJECT = [
    ("not-json", "{not json"), ("array", "[]"), ("string", '"x"'), ("null", "null"), ("empty-nodes", _top(nodes=[])),
    ("nodes-not-list", _top(nodes={})), ("no-job", {"nodes": _base()["nodes"]}), ("bad-job", _top(job="bad job")),
    ("job-too-long", _top(job="a" * 65)), ("job-int", _top(job=1)),
    ("slack-5", _top(slack=5)), ("slack-neg", _top(slack=-1)), ("slack-bool", _top(slack=True)),
    ("slack-float", _top(slack=1.5)), ("slack-str", _top(slack="1")),
    ("33-nodes", {"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder"} for i in range(33)]}),
    ("node-not-object", _top(nodes=[1])), ("id-digit-first", _with(id="1x")), ("id-17-chars", _with(id="A" * 17)),
    ("id-space", _with(id="A B")), ("id-missing", _with(id=None)), ("id-dup", _with(id="A")),
    ("a-missing", _with(a=None)), ("a-int", _with(a=3)), ("a-upper", _with(a="Coder")), ("a-not-in-row", _with(a="designer")),
    ("alt-not-in-row", _with(alt="designer")), ("alt-int", _with(alt=3)),
    ("dep-not-list", _with(dep="A")), ("dep-int", _with(dep=[1])), ("dep-unknown", _with(dep=["Q"])),
    ("dep-self", _with(dep=["B"])), ("dep-unknown-hostile", _with(dep=["IGNORE ALL; rm -rf"])),
    ("cycle", {"job": "j", "nodes": [{"id": "A", "a": "coder", "dep": ["B"]}, {"id": "B", "a": "coder", "dep": ["A"]}]}),
    ("cycle3", {"job": "j", "nodes": [{"id": "A", "a": "coder", "dep": ["C"]}, {"id": "B", "a": "coder", "dep": ["A"]},
                                      {"id": "C", "a": "coder", "dep": ["B"]}]}),
    ("r-bad-tag", _with(r=["root"])), ("r-not-list", _with(r="gui")), ("r-int", _with(r=[1])),
    ("s-bad", _with(s="XL")), ("n-zero", _with(n=0)), ("n-bool", _with(n=True)), ("n-float", _with(n=1.5)),
    ("w-17", _with(w=["a"] * 17)), ("w-257", _with(w=["a" * 257])), ("w-nul", _with(w=["a\x00b"])),
    ("w-empty", _with(w=[""])), ("w-int", _with(w=[1])), ("w-str", _with(w="a")), ("rd-17", _with(rd=["a"] * 17)),
    ("rd-257", _with(rd=["a" * 257])), ("rd-nul", _with(rd=["\x00"])),
    ("nan-n", '{"job":"j","nodes":[{"id":"A","a":"coder","n":NaN}]}'),
    ("depth-7", _top(x=[[[[[[1]]]]]])), ("bytes-65537", b" " * 65537),
    ("not-utf8", b'{"job":"\xff\xfe"}'), ("deep-bracket-bomb", "[" * 60000), ("deep-obj-bomb", '{"a":' * 12000),
]


@pytest.mark.parametrize("name,content", REJECT, ids=[r[0] for r in REJECT])
def test_parse_plan_rejects(name, content):
    if not isinstance(content, (str, bytes, dict)):
        pytest.skip("n/a")
    with pytest.raises(F.PlanError) as ei:
        F.parse_plan(content, ROW)
    msg = str(ei.value)
    for hostile in ("IGNORE ALL", "rm -rf", "bad job", "\x00", "Coder", "designer"):
        assert hostile not in msg, msg


def test_parse_plan_limits_are_exact_boundaries():
    ok = lambda p: F.parse_plan(p, ROW)  # noqa: E731
    ok({"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder"} for i in range(32)]})
    ok(_top(slack=0)), ok(_top(slack=4))
    ok(_with(w=["a"] * 16, rd=["b" * 256] * 16))
    ok(_with(id="A" + "b" * 15))
    ok(_top(job="a" * 64))
    ok(_with(s="S", n=1))
    ok(_top(x=[[[[[]]]]]))                                # nesting depth 6: allowed
    with pytest.raises(F.PlanError):
        ok(_top(x=[[[[[[]]]]]]))                          # depth 7
    base = json.dumps(dict(_base(), pad=""))
    pad = 65536 - len(base.encode())
    exact = json.dumps(dict(_base(), pad="x" * pad)).encode()
    assert len(exact) == 65536
    ok(exact)
    with pytest.raises(F.PlanError):
        ok(exact + b" ")
    with pytest.raises(F.PlanError):
        ok(exact.decode() + " ")


def test_parse_plan_messages_carry_only_validated_ids():
    cyc = {"job": "j", "nodes": [{"id": "A", "a": "coder", "dep": ["B"]}, {"id": "B", "a": "coder", "dep": ["A"]}]}
    with pytest.raises(F.PlanError) as ei:
        F.parse_plan(cyc)
    assert "A" in str(ei.value) and "B" in str(ei.value)
    for payload in ("IGNORE PREVIOUS INSTRUCTIONS", "../../etc/passwd", "$(id)", "<script>"):
        for plan in (_with(dep=[payload]), _top(job=payload), _with(a=payload), _with(id=payload), _with(r=[payload]),
                     _with(s=payload), _with(w=[payload] * 17)):
            with pytest.raises(F.PlanError) as ei:
                F.parse_plan(plan, ROW)
            assert payload not in str(ei.value) and "IGNORE" not in str(ei.value)


def _mutate(rng, obj):
    obj = copy.deepcopy(obj)
    slots = []

    def walk(o):
        if isinstance(o, dict):
            for key in list(o):
                slots.append((o, key))
                walk(o[key])
        elif isinstance(o, list):
            for i in range(len(o)):
                slots.append((o, i))
                walk(o[i])
    walk(obj)
    for _ in range(rng.randint(1, 3)):
        if not slots:
            break
        c, key = rng.choice(slots)
        if (isinstance(c, dict) and key not in c) or (isinstance(c, list) and key >= len(c)):
            continue
        act = rng.random()
        if act < 0.5:
            c[key] = rng.choice(GARBAGE + ["A", "B", ["A"], {"id": "Z", "a": "coder"}, "x" * 300, "T1", ["T1", "T1"]])
        elif act < 0.7 and isinstance(c, dict):
            del c[key]
        elif isinstance(c, dict):
            c[rng.choice(["id", "a", "dep", "w", "r", "n", "s", "slack", "job", "nodes", "alt", "rd"])] = rng.choice(GARBAGE)
    return obj


def _independent_acyclic(plan):
    deps = {n["id"]: set(n["dep"]) for n in plan["nodes"]}
    done = set()
    while len(done) < len(deps):
        ready = [i for i, d in deps.items() if i not in done and d <= done]
        if not ready:
            return False
        done.update(ready)
    return True


def test_parse_plan_fuzz_only_planerror_and_accepted_plans_are_sane():
    rng = random.Random(202)
    accepted = rejected = 0
    for i in range(1500):
        src = rand_dag(rng, rng.choice(["chain", "wide", "diamond", "layered"]), rng.randint(1, 8))
        obj = _mutate(rng, src) if i % 5 else src
        try:
            text = json.dumps(obj)
        except (TypeError, ValueError):
            continue
        try:
            p = F.parse_plan(text, ROW if i % 2 else None)
        except F.PlanError:
            rejected += 1
            continue
        accepted += 1
        ids = [n["id"] for n in p["nodes"]]
        assert 1 <= len(ids) <= 32 and len(set(ids)) == len(ids)
        assert all(F.NODE_ID_RE.match(x) for x in ids)
        assert all(d in ids and d != n["id"] for n in p["nodes"] for d in n["dep"])
        assert _independent_acyclic(p)
        assert all(len(n["w"]) <= 16 and len(n["rd"]) <= 16 for n in p["nodes"])
        assert set(sum((n["r"] for n in p["nodes"]), [])) <= set(F.RISK_TAGS)
        assert p["slack"] is None or 0 <= p["slack"] <= 4
    assert accepted > 100 and rejected > 100
    for _ in range(300):
        blob = bytes(rng.randrange(256) for _ in range(rng.randint(0, 200)))
        for c in (blob, blob.decode("latin-1")):
            with pytest.raises(F.PlanError):
                F.parse_plan(c)
    for junk in GARBAGE:
        try:
            F.parse_plan(junk, ROW)
        except F.PlanError:
            pass


def _best_of(fn, runs=3):
    best = 9.9
    for _ in range(runs):
        t0 = time.perf_counter()
        try:
            fn()
        except F.PlanError:
            pass
        best = min(best, time.perf_counter() - t0)
    return best


def test_hostile_plans_are_parsed_or_rejected_under_50ms():
    n = 32
    dense = {"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder", "dep": ["N%d" % j for j in range(i)],
                                    "w": ["src/%d/**/*.py" % k for k in range(16)],
                                    "rd": ["docs/%d/*" % k for k in range(16)]} for i in range(n)]}
    cycle = {"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder", "dep": ["N%d" % ((i + 1) % n)]} for i in range(n)]}
    chains = {"job": "j", "nodes": [{"id": "N%d" % i, "a": "coder", "dep": ["N%d" % (i - 1)] if i else []}
                                    for i in range(n)]}
    texts = [json.dumps(dense), json.dumps(cycle), json.dumps(chains), "[" * 65000, '{"a":' * 12000,
             '{"job":"j","nodes":[' + ",".join(['{"id":"A","a":"coder"}'] * 2500) + "]}",
             json.dumps({"job": "j", "nodes": [{"id": "A", "a": "coder", "w": ["a" * 256] * 16}] * 30})]
    for t in texts:
        assert _best_of(lambda t=t: F.parse_plan(t, ROW)) < 0.05, t[:40]


# ------------------------------------------------------------------ node_of and chain_types
def test_chain_types_and_node_of():
    assert F.chain_types({"a": "coder", "alt": None}) == ("coder", "main-coder", "ninja-coder")
    assert F.chain_types({"a": "main-coder", "alt": None}) == ("main-coder", "ninja-coder")
    assert F.chain_types({"a": "ninja-coder", "alt": None}) == ("ninja-coder",)
    assert F.chain_types({"a": "verifier", "alt": None}) == ("verifier",)
    assert F.chain_types({"a": "verifier", "alt": "main-coder"}) == ("verifier", "main-coder", "ninja-coder")
    assert F.chain_types({"a": "ninja-coder", "alt": "coder"})[:2] == ("ninja-coder", "coder")
    p = mkplan([{"id": "T1", "a": "coder"}, {"id": "T2", "a": "verifier"}])
    assert F.node_of(p, "T1 build parser", "coder") == ("T1", "planned")
    assert F.node_of(p, "T1: build parser", "main-coder") == ("T1", "planned")
    assert F.node_of(p, "T1, x", "ninja-coder") == ("T1", "planned")
    assert F.node_of(p, "T2 verify", "coder") == (None, "type_mismatch")
    assert F.node_of(p, "T1 x", "verifier") == (None, "type_mismatch")
    assert F.node_of(p, "T9 x", "coder") == (None, "unknown_node")
    assert F.node_of(p, "t1 x", "coder") == (None, "unknown_node")
    assert F.node_of(p, "build T1", "coder") == (None, "unknown_node")
    assert F.node_of(p, "", "coder") == (None, "no_label")
    assert F.node_of(p, "   ", "coder") == (None, "no_label")
    assert F.node_of(p, None, "coder") == (None, "no_label")
    assert F.node_of(None, "T1 x", "coder") == (None, "no_plan")


# ------------------------------------------------------------------ R5: chain walk, aborted runs
def _walk(k, plan, types, node="T1", now0=100.0):
    """Spawn, bind, end one run per type in `types` (each a failure); the decision of each spawn."""
    st, out = F.nodes_new(plan["job"]), []
    for i, t in enumerate(types):
        d = dec(k, plan, st, node, child=t)
        out.append(d)
        if not d["allow"]:
            break
        tid, cid = "tid%d" % i, "cid%d" % i
        st = F.record_spawn(st, node, tid, t, now0 + i)
        st, found = F.bind_child(st, tid, cid)
        assert found
        st, found = F.end_run(st, cid, now0 + i + 0.5, "failed")
        assert found
    return out, st


def test_chain_walk_six_allowed_runs_then_denial():
    plan = mkplan([{"id": "T1", "a": "coder"}])
    types = ["coder", "coder", "main-coder", "main-coder", "ninja-coder", "ninja-coder", "ninja-coder"]
    out, st = _walk(kn(), plan, types)
    assert [d["allow"] for d in out] == [True] * 6 + [False]
    assert out[6]["code"] == "runs_used" and "6" in out[6]["reason"] and "T1" in out[6]["reason"]
    assert all(F.node_of(plan, "T1 x", t) == ("T1", "planned") for t in types)
    assert len(st["runs"]["T1"]) == 6


def test_chain_walk_honours_node_runs_knob_and_default_enforce_terms():
    plan = mkplan([{"id": "T1", "a": "coder"}])
    for nr in (1, 2, 5):
        out, _ = _walk(kn(node_runs=nr), plan, ["coder"] * (nr + 1))
        assert [d["allow"] for d in out] == [True] * nr + [False]
    # default enforce set is node,deps: the node term is on
    out, _ = _walk(kn(terms="node,deps"), plan, ["coder"] * 8)
    assert out[-1]["allow"] is False
    # without the node term the denial is only reported
    out, _ = _walk(kn(terms="deps"), plan, ["coder"] * 8)
    assert out[-1]["allow"] is True and out[-1]["would_allow"] is False and "runs_used" in out[-1]["fails"]


def test_aborted_runs_do_not_count_toward_node_runs_or_block():
    plan = mkplan([{"id": "T1", "a": "coder"}, {"id": "T2", "a": "coder", "dep": ["T1"]}])
    k = kn()
    st = F.nodes_new("J1")
    for i in range(30):                                   # lease gone, child never bound: aborted
        st = F.record_spawn(st, "T1", "ab%d" % i, "coder", float(i))
    assert F.run_status(st["runs"]["T1"][0], set(), set()) == "aborted"
    d = dec(k, plan, st, "T1")
    assert d["allow"] and d["code"] is None
    elig, blocked = F.ready_eligible(plan, st, set(), set(), k)
    assert elig == ["T1"] and blocked["T2"][0] == "deps"     # an aborted run is not an ended dependency
    out, _ = _walk(k, plan, ["coder"] * 7)               # a fresh node: still 6
    assert sum(d["allow"] for d in out) == 6
    # 6 ended runs plus 30 aborted: runs used up, not blocked earlier
    st2 = st
    for i in range(6):
        st2 = F.record_spawn(st2, "T1", "r%d" % i, "coder", 50.0 + i)
        st2, _ = F.bind_child(st2, "r%d" % i, "c%d" % i)
        assert dec(k, plan, st2, "T1", live_tids=set(), live_children={"c%d" % i})["code"] == "running"
    assert dec(k, plan, st2, "T1")["code"] == "runs_used"
    assert F.node_block(plan, "T1", st2, set(), set(), k) == ("runs_used", 6)


def test_run_status_live_aborted_ended():
    r = {"tid": "t1", "child_id": None}
    assert F.run_status(r, {"t1"}, set()) == "live"
    assert F.run_status(r, set(), set()) == "aborted"
    assert F.run_status(r, {"other"}, {"c1"}) == "aborted"
    r["child_id"] = "c1"
    assert F.run_status(r, set(), {"c1"}) == "live"
    assert F.run_status(r, {"t1"}, set()) == "live"
    assert F.run_status(r, set(), set()) == "ended"
    assert F.run_status({"tid": None, "child_id": None}, {None}, {None}) == "aborted"


def test_dependencies_unblock_on_any_ended_run_and_name_the_dependency():
    plan = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]}])
    k = kn()
    st = F.nodes_new("J1")
    d = dec(k, plan, st, "B")
    assert not d["allow"] and d["code"] == "deps" and "A" in d["reason"] and d["eligible"] == ["A"]
    st = F.record_spawn(st, "A", "ta", "coder", 1.0)
    assert dec(k, plan, st, "B", live_tids={"ta"})["code"] == "deps"          # lease live
    st, _ = F.bind_child(st, "ta", "ca")
    assert dec(k, plan, st, "B", live_children={"ca"})["code"] == "deps"      # child live
    for outcome in ("ok", "failed", "stop_failure"):
        s2, _ = F.end_run(st, "ca", 5.0, outcome)
        d = dec(k, plan, s2, "B", live_children=set())
        assert d["allow"] and d["planned"] and d["node"] == "B"


def test_dependency_term_can_be_reported_without_enforcing():
    plan = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]}])
    d = dec(kn(terms="node"), plan, F.nodes_new("J1"), "B")
    assert d["allow"] and not d["would_allow"] and d["code"] == "deps"


def test_exclusive_tags_and_write_conflicts_and_isolation():
    plan = mkplan([{"id": "A", "a": "coder", "w": ["src/*"], "r": ["accel"]},
                   {"id": "B", "a": "coder", "r": ["accel"]},
                   {"id": "C", "a": "coder", "w": ["src/*.py"]},
                   {"id": "D", "a": "coder", "rd": ["src/x.py"]},
                   {"id": "E", "a": "coder", "w": ["docs/*"]},
                   {"id": "G", "a": "coder", "r": ["gui"]}, {"id": "H", "a": "coder", "r": ["gui"]}])
    k = kn()
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    live = {"live_tids": {"ta"}}
    assert dec(k, plan, st, "B", n=1, **live)["code"] == "exclusive"
    assert dec(k, plan, st, "C", n=1, **live)["code"] == "conflict"
    assert dec(k, plan, st, "D", n=1, **live)["code"] == "conflict"           # rd against a live w
    assert dec(k, plan, st, "E", n=1, **live)["allow"]                       # disjoint
    assert dec(k, plan, st, "C", n=1, isolation="worktree", **live)["allow"]
    st_iso = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0, iso=True)
    assert dec(k, plan, st_iso, "C", n=1, **live)["allow"]                   # the live node is isolated
    assert dec(k, plan, st_iso, "B", n=1, **live)["code"] == "exclusive"     # exclusivity ignores isolation
    st_g = F.record_spawn(F.nodes_new("J1"), "G", "tg", "coder", 1.0)
    assert dec(k, plan, st_g, "H", n=1, live_tids={"tg"})["code"] == "exclusive"
    assert dec(k, plan, F.nodes_new("J1"), "C")["allow"]                     # nothing live: no conflict
    # w and rd of two nodes never conflict (read/read)
    p2 = mkplan([{"id": "A", "a": "coder", "rd": ["src/*"]}, {"id": "B", "a": "coder", "rd": ["src/*"]}])
    s2 = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    assert dec(k, p2, s2, "B", n=1, live_tids={"ta"})["allow"]


def test_conflict_term_falls_back_to_static_past_its_deadline():
    plan = mkplan([{"id": "A", "a": "coder", "w": ["src/*"]}, {"id": "B", "a": "coder", "w": ["src/*"]}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    base = dict(plan=plan, nodes=st, node_id="B", n=1, live_tids={"ta"})
    assert dec(kn(), **base)["code"] == "conflict"
    ticks = iter(range(10 ** 6))
    d = dec(kn(), clock=lambda: float(next(ticks)), **base)                  # each clock read: +1 s
    assert d["allow"] and d["code"] is None


def test_node_block_precedence_and_details():
    plan = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]}])
    k = kn()
    st = F.record_spawn(F.nodes_new("J1"), "B", "tb", "coder", 1.0)
    assert F.node_block(plan, "B", st, {"tb"}, set(), k) == ("running", None)
    assert F.node_block(plan, "B", st, set(), set(), k) == ("deps", ["A"])
    assert F.node_block(plan, "A", st, set(), set(), k) is None


# ------------------------------------------------------------------ unplanned spawns, slack, plan_off
def test_unplanned_spawns_use_slack_then_fall_back_without_plan_terms():
    plan = mkplan([{"id": "A", "a": "coder"}], slack=1)
    k = kn()
    st = F.nodes_new("J1")
    d = dec(k, plan, st, None, n=0)
    assert d["allow"] and not d["planned"] and not d["understated"]
    st = F.record_spawn(st, None, "u1", "verifier", 1.0)
    d = dec(k, plan, st, None, n=1, live_tids={"u1"})
    assert d["allow"] and d["understated"] and d["fallback"] is False       # slack used up: allowed, flagged
    d = dec(k, plan, st, None, n=32, live_tids={"u1"})
    assert not d["allow"] and d["code"] == "ceil"                            # static cap still binds
    # unplanned spawn is never blocked by node terms
    st2 = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    assert dec(k, plan, st2, None, n=1, live_tids={"ta"})["allow"]


def test_understated_three_times_switches_plan_terms_off():
    plan = mkplan([{"id": "A", "a": "coder"}])
    k = kn()
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    assert dec(k, plan, st, "A", n=1, live_tids={"ta"})["code"] == "running"
    for i in range(3):
        assert not st["plan_off"]
        st = F.note_understated(st)
    assert st["understated"] == 3 and st["plan_off"] is True
    d = dec(k, plan, st, "A", n=1, live_tids={"ta"})
    assert d["allow"] and not d["planned"] and d["code"] is None
    assert dec(k, plan, st, "A", n=32, live_tids={"ta"})["code"] == "ceil"   # the static cap remains


def test_resume_has_no_plan_terms_but_keeps_cap_window_budget():
    plan = mkplan([{"id": "A", "a": "coder"}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    k = kn()
    d = dec(k, plan, st, "A", n=1, kind="resume", live_tids={"ta"})
    assert d["allow"] and not d["planned"] and d["kind"] == "resume"
    assert dec(k, plan, st, "A", n=32, kind="resume")["code"] == "ceil"
    assert dec(k, plan, st, None, n=3, kind="resume", aimd={"w": 3})["code"] == "window"
    assert dec(k, None, None, None, n=0, kind="resume", aimd={"w": 1})["allow"]
    assert dec(k, None, None, None, n=0, kind="resume", b_rem=0.0)["code"] == "budget"
    assert dec(k, None, None, None, n=1, kind="resume", b_rem=100 * M, aimd={"w": 9})["allow"]


# ------------------------------------------------------------------ budget (D2): K_B
def test_worked_case_total_185b_gives_kb_62():
    b_rem = F.budget_remaining(100 * M, 1_920 * M, 1_850 * M, 10 * M)
    assert b_rem == 70 * M
    mdl = model_1m()
    assert F.c_med(mdl, "coder") == 1 * M
    assert F.k_budget(b_rem, 0.0, 8 * M, [1.0 * M]) == 62
    plan = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder"}, {"id": "C", "a": "coder"}])
    d = dec(kn(), plan, F.nodes_new("J1"), "A", b_rem=b_rem, model=mdl)
    assert d["allow"] and d["terms"]["kb"] == 62 >= 1
    d = dec(kn(), None, None, None, b_rem=b_rem, model=mdl)
    assert d["allow"] and d["terms"]["kb"] == 62
    d = dec(kn(), None, None, None, n=5, b_rem=b_rem, model=mdl)
    assert d["terms"]["kb"] == 5 + 62
    # the same case at the exact edge
    assert F.k_budget(9 * M, 0, 8 * M, [1.0 * M]) == 1
    assert F.k_budget(9 * M - 1, 0, 8 * M, [1.0 * M]) == 0
    assert F.k_budget(8 * M, 0, 8 * M, [1.0 * M]) == 0


def test_budget_remaining_unit():
    assert F.budget_remaining(100, 1000, 500, 10) == 90
    assert F.budget_remaining(100, 1000, 950, 10) == 50
    assert F.budget_remaining(0, 1000, 500, 10) == 500            # caps <= 0 are off
    assert F.budget_remaining(100, 0, 500, 10) == 90
    assert F.budget_remaining(0, 0, 5, 5) is None and F.budget_remaining(None, None, 1, 1) is None
    assert F.budget_remaining(100, 1000, None, None) == 100
    assert F.budget_remaining(100, 1000, 2000, 10) == -1000       # overspent: negative, not clamped
    for bad in ("abc", [1], object()):
        assert F.budget_remaining(bad, 10, 1, 1) is None
        assert F.budget_remaining(10, bad, 1, 1) is None
    for bad in ("abc", float("nan"), [1], object()):
        assert F.budget_remaining(10, 10, bad, 1) is None
        assert F.budget_remaining(10, 10, 1, bad) is None
    assert F.budget_remaining(float("inf"), 10, 1, 1) is None


def _brute_kb(b_rem, commit, reserve, costs):
    if b_rem is None or not costs:
        return None
    room, k, i = b_rem - commit - reserve, 0, 0
    while True:
        c = costs[i] if i < len(costs) else costs[0]
        if c <= 0 and i >= len(costs):
            return None                                   # further spawns cost nothing: unlimited
        if c > room:
            return k
        room -= c
        k += 1
        if k > 10 ** 5:
            return None
        i += 1


def test_k_budget_matches_brute_force_and_is_monotone():
    rng = random.Random(303)
    for _ in range(3000):
        costs = [float(rng.choice([0, 1, 2, 5, 17, 100])) * rng.choice([1, 1000]) for _ in range(rng.randint(0, 5))]
        if costs and rng.random() < 0.9:
            costs[0] = max(costs[0], 1.0)
        b = rng.choice([None, float(rng.randint(-50, 5000))])
        commit, reserve = float(rng.randint(0, 300)), float(rng.randint(0, 300))
        want = _brute_kb(b, commit, reserve, costs)
        got = F.k_budget(b, commit, reserve, costs)
        assert got == want, (b, commit, reserve, costs)
        if got is not None:
            assert got >= 0
    for _ in range(2000):
        costs = [float(rng.randint(1, 50)) for _ in range(rng.randint(1, 6))]
        commit, reserve = float(rng.randint(0, 200)), float(rng.randint(0, 200))
        b1 = float(rng.randint(-100, 2000))
        b2 = b1 + rng.randint(0, 1000)
        k1, k2 = F.k_budget(b1, commit, reserve, costs), F.k_budget(b2, commit, reserve, costs)
        assert k1 <= k2                                   # more remaining budget never lowers K_B
        assert F.k_budget(b1, commit + 5, reserve, costs) <= k1      # more commit or reserve never raises it
        assert F.k_budget(b1, commit, reserve + 5, costs) <= k1


def test_kb_monotone_in_remaining_budget_through_dyn_decision():
    rng = random.Random(304)
    for _ in range(300):
        c = rand_call(rng, "enforce")
        c["c_ceil"] = max(c["c_ceil"], 1)
        last = None
        for b in (-10 * M, 0, 5 * M, 9 * M, 20 * M, 70 * M, 500 * M, 10 ** 10):
            c["b_rem"] = b
            d = run_call(c)
            kb = d["terms"].get("kb", 10 ** 9) if not d["fallback"] else 10 ** 9
            if last is not None:
                assert kb >= last
                assert last >= 0
            last = kb


def test_budget_denies_when_exhausted_and_is_reported_when_not_enforced():
    mdl = model_1m()
    d = dec(kn(), None, None, None, n=0, b_rem=8 * M + 999_999, model=mdl)
    assert not d["allow"] and d["code"] == "budget" and "budget" in d["fails"]
    d = dec(kn(terms="node,deps"), None, None, None, n=0, b_rem=0.0, model=mdl)
    assert d["allow"] and not d["would_allow"] and d["binding"] == "budget"
    d = dec(kn(), None, None, None, n=0, b_rem=None, model=mdl)
    assert d["allow"] and "kb" not in d["terms"]               # unknown budget: infinity, fail open
    d = dec(kn(reserve_tok=0), None, None, None, n=0, b_rem=1 * M, model=mdl)
    assert d["allow"] and d["terms"]["kb"] == 1
    d = dec(kn(), None, None, None, n=0, b_rem=70 * M, commit=62.0 * M, model=mdl)
    assert d["code"] == "budget"
    d = dec(kn(), None, None, None, n=0, b_rem=70 * M, commit=61.0 * M, model=mdl)
    assert d["allow"] and d["terms"]["kb"] == 1


def test_unknown_or_malformed_model_fails_open():
    for bad in ({"types": {"coder": {"turns": {"M": "x"}}}}, {"types": {"coder": {"ctx": {"a": float("nan")}}}},
                {"types": {"coder": {"ctx": {"a": -5}}}}, {"types": {"coder": {"sec_per_call": {"p50": "z"}}}}):
        with pytest.raises(ValueError):
            F.cost_model(bad, "coder")
        d = dec(kn(), None, None, None, b_rem=0.0, model=bad)
        assert d["allow"] and "kb" not in d["terms"]
    for ok in (None, {}, [], "x", {"types": []}, {"types": {"coder": None}}):
        assert F.c_med(ok, "coder") == 31603 * 18 + 1297 * 18 * 18


def test_cost_model_formula_and_builtin_fallbacks():
    mdl = {"types": {"coder": {"turns": {"M": 7}, "ctx": {"a": 1000, "b": 10}}}}
    assert F.c_med(mdl, "coder") == 1000 * 7 + 10 * 49
    assert F.c_med(None, "main-coder") == 95000 * 44 + 1300 * 44 * 44
    assert F.c_med(None, "never-heard-of-it") == F.c_med(None, "claude-code-engineer")
    assert F.c_med(None, "researcher") == 82033 * 32 + 887 * 32 * 32
    cm = F.cost_model(None, "coder")
    assert cm["spc_p90"] == 22 and cm["wall_hi"] > 18 * 7 and cm["c_med"] > 0
    for t in ("coder", "verifier", "planner", "unknown-x", "writer", "orchestrator"):
        c = F.cost_model(mdl, t)
        assert all(math.isfinite(v) and v >= 0 for v in c.values())


def test_commit_tokens():
    mdl = model_1m()
    assert F.commit_tokens([], mdl) == 0
    assert F.commit_tokens([("coder", 0)], mdl) == 1 * M
    assert F.commit_tokens([("coder", 400_000), ("coder", 5 * M), ("coder", None)], mdl) == 600_000 + 0 + 1 * M
    assert F.commit_tokens([("coder", 1 * M)], mdl) == 0


def test_load_model_reads_caches_and_rejects(tmp_path):
    p = tmp_path / "m.json"
    assert F.load_model(str(p)) is None
    p.write_text("[1]")
    assert F.load_model(str(p)) is None
    p.write_text("{not json")
    assert F.load_model(str(p)) is None
    p.write_text(json.dumps(model_1m()))
    assert F.load_model(str(p)) == model_1m()
    p.write_text(json.dumps({"types": {}, "x": 1}))
    assert F.load_model(str(p)) == {"types": {}, "x": 1}


def test_finish_healthy_and_healthy_budget_and_delay_ratio():
    f = F.finish_healthy
    assert f(True, 10, 20, False, 50 * M, 100 * M)
    assert f(True, 20, 20, False, 25 * M, 100 * M)                      # boundaries are inclusive
    assert not f(True, 20.01, 20, False, 50 * M, 100 * M)
    assert not f(False, 10, 20, False, 50 * M, 100 * M)
    assert not f(True, 10, 20, True, 50 * M, 100 * M)
    assert not f(True, 10, 20, False, 25 * M - 1, 100 * M)
    assert not f(True, None, 20, False, 50 * M, 100 * M) and not f(True, 10, None, False, 50 * M, 100 * M)
    assert not f(True, "x", 20, False, 50 * M, 100 * M)
    assert f(True, 10, 20, False, None, 100 * M) and f(True, 10, 20, False, -1, 0)
    assert F.delay_ratio([], 100.0, None) is None
    assert F.delay_ratio([("coder", 0.0, 2)], 100.0, None) is None       # fewer than 3 calls
    assert F.delay_ratio([("coder", 0.0, 10)], 220.0, None) == pytest.approx(1.0)   # (220/10)/22
    assert F.delay_ratio([("coder", 0.0, 10), ("coder", 0.0, 10)], 440.0, None) == pytest.approx(2.0)
    r = F.delay_ratio([("coder", 0.0, 10), ("coder", 0.0, 10), ("coder", 0.0, 5)], 220.0, None)
    assert r == pytest.approx(1.0)                                       # median of 1, 1, 2
    assert F.delay_ratio([("coder", "bad", 10), ("coder", 0.0, "x"), ("coder", 0.0, 10)], 220.0, None) == pytest.approx(1.0)


# ------------------------------------------------------------------ modes
def test_off_mode_is_the_static_decision_whatever_the_inputs():
    rng = random.Random(505)
    for _ in range(400):
        c = rand_call(rng, "off")
        d = run_call(c)
        assert d["allow"] is True and d["fallback"] is True and d["mode"] == "off" and d["binding"] == "off"
        assert d["cap"] == c["c_ceil"] and d["terms"] == {"ceil": c["c_ceil"]} and d["code"] is None
        c2 = dict(c, plan=None, nodes=None, node_id=None, aimd=None, b_rem=None, k_sess=None)
        assert run_call(c2) == d
    env = {"STACK_FANOUT_DYN": "enforce", "STACK_POLICY": "off"}
    c = rand_call(rng)
    assert run_call(c, dict(c["env"], **env))["binding"] == "off"
    off = dict(F.DEFAULT_KNOBS, mode="off")
    assert F.dyn_decision(off, "spawn", "o1", "orchestrator", 8, 3, "coder")["binding"] == "off"
    assert F.dyn_decision(None, "spawn", "o1", "orchestrator", 8, 3, "coder")["mode"] == "shadow"


def test_shadow_never_denies_while_enforce_does_and_would_allow_matches():
    rng = random.Random(606)
    enforce_denied = 0
    for _ in range(1200):
        c = rand_call(rng, "enforce")
        env_all = with_mode(c["env"], "enforce", ALL_TERMS)
        enf = run_call(c, env_all)
        sh = run_call(c, with_mode(c["env"], "shadow", ALL_TERMS))
        assert sh["allow"] is True and sh["mode"] == "shadow"
        assert sh["would_allow"] == enf["allow"] == (enf["allow"] and enf["would_allow"])
        assert sh["cap"] == enf["cap"] and sh["code"] == enf["code"] and sh["fails"] == enf["fails"]
        enforce_denied += not enf["allow"]
        if not enf["allow"]:
            assert enf["code"] in F.CODE_TERM and enf["reason"].startswith("Dynamic fan-out (%s)" % enf["code"])
    assert enforce_denied > 150
    # enforce with a subset: denies only the enforced terms
    plan = mkplan([{"id": "A", "a": "coder"}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    base = dict(plan=plan, nodes=st, node_id="A", n=1, live_tids={"ta"}, aimd={"w": 1})
    assert dec(kn(terms="node"), **base)["code"] == "running"
    d = dec(kn(terms="deps"), **base)                     # running and window are reported only
    assert d["allow"] and not d["would_allow"] and set(d["fails"]) >= {"running", "window"}
    d = dec(kn(terms="aimd"), **base)
    assert not d["allow"] and d["code"] == "window"


def test_static_ceiling_denies_in_enforce_whatever_terms_are_enabled():
    d = dec(kn(terms="aimd"), None, None, None, n=32, c_ceil=32)
    assert not d["allow"] and d["code"] == "ceil"
    d = dec(kn("shadow"), None, None, None, n=32, c_ceil=32)
    assert d["allow"] and not d["would_allow"]


# ------------------------------------------------------------------ R1 property and garbage inputs (R3)
def test_r1_dynamic_cap_never_exceeds_static_cap_random_property():
    rng = random.Random(707)
    allowed = 0
    for _ in range(3000):
        c = rand_call(rng)
        d = run_call(c)
        assert isinstance(d["cap"], int) and 0 <= d["cap"] <= max(0, c["c_ceil"])
        assert d["terms"].get("ceil", c["c_ceil"]) == c["c_ceil"] or d["fallback"]
        mode = F.parse_knobs(c["env"])[0]["mode"]
        if not d["fallback"] and c["k_sess"] is not None:
            assert d["cap"] <= max(0, c["n"] + c["k_sess"])          # K_sess bounds the reported cap
        if mode != "enforce":
            assert d["allow"] is True
        elif d["allow"]:
            allowed += 1
            if not d["fallback"]:
                assert c["n"] < c["c_ceil"]                     # an allowed spawn leaves room under C_static
        if d["allow"] and mode == "enforce" and c["c_ceil"] > 0 and c["n"] >= c["c_ceil"]:
            assert d["fallback"] is True                      # only out-of-scope or error paths bypass it
    assert allowed > 150


def test_cap_is_the_minimum_of_the_d2_terms_and_names_the_binding_one():
    mdl = model_1m()
    three = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder"}, {"id": "C", "a": "coder"}], slack=2)
    one = mkplan([{"id": "A", "a": "coder"}], slack=0)
    st = F.nodes_new("J1")

    def go(plan, **kw):
        args = dict(plan=plan, nodes=st, node_id="A", n=1, model=mdl, aimd={"w": 20, "last_dec": None}, c_ceil=32)
        args.update(kw)
        return dec(kn(), **args)
    d = go(three)
    assert d["cap"] == 6 and d["terms"]["elig"] == 1 + 3 + 2 and d["binding"] == "elig" and d["allow"]
    d = go(three, aimd={"w": 5})
    assert d["cap"] == 5 and d["terms"]["w"] == 5 and d["binding"] == "w"
    d = go(three, aimd={"w": 5}, k_sess=2)
    assert d["cap"] == 3 and d["terms"]["sess"] == 3 and d["binding"] == "sess"
    d = go(three, aimd={"w": 5}, k_sess=2, b_rem=9.5 * M)
    assert d["cap"] == 2 and d["terms"]["kb"] == 2 and d["binding"] == "kb"
    d = go(one)
    assert d["cap"] == 2 and d["terms"]["elig"] == 2 and d["binding"] == "elig"
    d = go(three, c_ceil=4, aimd={"w": 20}, k_sess=50)
    assert d["cap"] == 4 and d["terms"]["ceil"] == 4 and d["binding"] == "ceil"
    d = go(three, k_sess=-9)
    assert d["cap"] == 0 and d["terms"]["sess"] == -8                      # never negative
    d = go(three, node_id=None, k_sess=0)
    assert d["terms"]["sess"] == 1 and d["cap"] <= 1


def test_r1_with_c_ceil_one_the_second_spawn_is_always_denied():
    rng = random.Random(708)
    for _ in range(300):
        c = rand_call(rng, "enforce")
        c["c_ceil"], c["n"] = 1, 1
        d = run_call(c)
        assert not d["allow"] and "ceil" in d["fails"] and d["cap"] <= 1


def test_r4_with_no_running_child_a_ready_planned_node_is_always_spawned():
    rng = random.Random(709)
    seen = 0
    for _ in range(1500):
        plan = rand_plan(rng)
        k = F.parse_knobs(dict(rand_env(rng, "enforce"), STACK_FANOUT_DYN_RESERVE_TOK="8000000"))[0]
        st = F.nodes_new("J1")
        elig, _ = F.ready_eligible(plan, st, set(), set(), k)
        nid = rng.choice(elig)
        c_ceil = rng.randint(1, 32)
        aimd = {"w": rng.randint(-3, 40), "last_dec": None}
        d = F.dyn_decision(k, "spawn", "o1", "orchestrator", c_ceil, 0, "coder", plan=plan, nodes=st, node_id=nid,
                           b_rem=rng.choice([None, 500 * M, 10 ** 10]), commit=0.0, aimd=aimd,
                           k_sess=rng.choice([None, 1, 5]))
        if d["code"] is None:
            seen += 1
        assert d["allow"], (d["code"], d["reason"])
    assert seen > 1000


def test_garbage_and_missing_inputs_fall_back_to_the_static_decision():
    rng = random.Random(808)
    plan = mkplan([{"id": "A", "a": "coder"}, {"id": "B", "a": "coder", "dep": ["A"]}])
    good = dict(kind="spawn", caller="o1", caller_type="orchestrator", c_ceil=8, n=2, child_type="coder",
                plan=plan, nodes=F.nodes_new("J1"), node_id="A", isolation=None, live_tids=set(),
                live_children=set(), b_rem=70 * M, commit=0.0, model=None, aimd={"w": 4, "last_dec": None},
                k_sess=10)
    fb = errs = 0
    for i in range(2500):
        args = dict(good)
        for key in rng.sample(sorted(good), rng.randint(1, 4)):
            args[key] = rng.choice(GARBAGE)
        k = F.parse_knobs({"STACK_FANOUT_DYN": rng.choice(["enforce", "shadow"]),
                           "STACK_FANOUT_DYN_ENFORCE": ALL_TERMS})[0]
        if i % 7 == 0:
            k = rng.choice(GARBAGE + [dict(k, mode=rng.choice(GARBAGE)), dict(k, types=rng.choice(GARBAGE)),
                                      dict(k, breaker=rng.choice(GARBAGE)), dict(k, enforce=rng.choice(GARBAGE))])
        try:
            d = F.dyn_decision(k, args.pop("kind"), args.pop("caller"), args.pop("caller_type"),
                               args.pop("c_ceil"), args.pop("n"), args.pop("child_type"), **args)
        except Exception as exc:                                 # noqa: BLE001
            pytest.fail("dyn_decision raised %r for %r" % (exc, args))
        assert isinstance(d, dict) and isinstance(d["cap"], int)
        if d["fallback"]:
            fb += 1
            assert d["allow"] is True and d["code"] is None and d["reason"] is None
            assert d["binding"] in ("off", "scope", "error", "breaker")
            errs += d["binding"] == "error"
        if not d["allow"]:
            assert d["mode"] == "enforce" and d["fallback"] is False and d["reason"]
    assert fb > 500 and errs > 50


def test_exception_in_a_term_is_the_static_decision_not_a_refusal():
    class Boom(dict):
        def get(self, *a, **kw):
            raise RuntimeError("x")

    class BadPlan(dict):
        def __getitem__(self, key):
            raise RuntimeError("x")
    k = kn()
    d = F.dyn_decision(k, "spawn", "o1", "orchestrator", 8, 0, "coder", plan=BadPlan(nodes=[]), nodes=F.nodes_new("J"))
    assert d["allow"] and d["fallback"] and d["binding"] == "error" and d["cap"] == 8
    d = F.dyn_decision(k, "spawn", "o1", "orchestrator", 8, 0, "coder", nodes=Boom())
    assert d["allow"] and d["fallback"]
    d = F.dyn_decision(k, "bogus-kind", "o1", "orchestrator", 8, 0, "coder")
    assert d["allow"] and d["fallback"] and d["binding"] == "error"
    d = F.dyn_decision(k, "spawn", "o1", "orchestrator", 8, -1, "coder")
    assert d["allow"] and d["fallback"]
    for nan_inf in (float("nan"), float("inf"), -float("inf")):
        for key in ("b_rem", "commit", "k_sess", "aimd", "model"):
            d = dec(k, None, None, None, n=0, **{key: nan_inf})
            assert d["allow"] or d["code"] in F.CODE_TERM


def test_malformed_node_state_is_repaired_not_fatal():
    plan = mkplan([{"id": "A", "a": "coder"}])
    for bad in (None, 5, "x", [], {"runs": 5, "unplanned": "x", "breaker": []}, {"runs": {"A": "zz"}}):
        d = dec(kn(), plan, bad, "A")
        assert isinstance(d["cap"], int)
        if not d["fallback"]:
            assert d["allow"]


# ------------------------------------------------------------------ AIMD (D3)
def test_aimd_cut_table_and_hold():
    k = kn(hold_s=60)
    a, act = F.aimd_update({"w": 8, "last_dec": None}, "stop_failure", 1000.0, 32, k, error="rate_limit")
    assert (a["w"], act, a["last_dec"]) == (4, "cut", 1000.0)
    b, act = F.aimd_update(a, "stop_failure", 1059.0, 32, k, error="rate_limit")
    assert (b["w"], act, b["last_dec"]) == (4, "hold", 1000.0)
    c, act = F.aimd_update(b, "stop_failure", 1060.0, 32, k, error="overloaded")
    assert (c["w"], act) == (2, "cut")
    for err, want in (("rate_limit", 4), ("overloaded", 4), ("server_error", 6), ("unknown", 6)):
        assert F.aimd_update({"w": 8, "last_dec": None}, "stop_failure", 5.0, 32, k, error=err)[0]["w"] == want
    assert F.aimd_update({"w": 8, "last_dec": None}, "refusal", 5.0, 32, k)[0]["w"] == 4
    assert F.aimd_update({"w": 5, "last_dec": None}, "refusal", 5.0, 32, k)[0]["w"] == 2        # floor(2.5)
    assert F.aimd_update({"w": 1, "last_dec": None}, "refusal", 5.0, 32, k)[0]["w"] == 1        # W_min
    assert F.aimd_update({"w": 8, "last_dec": None}, "refusal", 5.0, 32, kn(wmin=6))[0]["w"] == 6


@pytest.mark.parametrize("err", ["billing_error", "authentication_failed", "invalid_request", "max_output_tokens",
                                 None, "", "RATE_LIMIT", "other", 5, ["rate_limit"]])
def test_aimd_other_stop_failures_change_nothing(err):
    st = {"w": 8, "last_dec": None}
    new, act = F.aimd_update(st, "stop_failure", 5.0, 32, kn(), error=err)
    assert new == {"v": st.get("v", new.get("v")), "w": 8, "last_dec": None} or new["w"] == 8
    assert new["w"] == 8 and new["last_dec"] is None and act == "none"


def test_aimd_finish_increase_delay_and_unknown_events():
    k = kn()
    st = {"w": 8, "last_dec": None}
    assert F.aimd_update(st, "finish", 1.0, 32, k, healthy=True)[0]["w"] == 9
    assert F.aimd_update(st, "finish", 1.0, 32, k, healthy=True)[1] == "increase"
    assert F.aimd_update(st, "finish", 1.0, 32, k, healthy=False) == ({"w": 8, "last_dec": None}, "none")
    assert F.aimd_update({"w": 32, "last_dec": None}, "finish", 1.0, 32, k, healthy=True)[0]["w"] == 32
    assert F.aimd_update(st, "finish", 1.0, 32, kn(alpha=3), healthy=True)[0]["w"] == 11
    assert F.aimd_update(st, "finish", 1.0, 32, kn(alpha=0), healthy=True)[1] == "none"
    assert F.aimd_update({"w": 31, "last_dec": None}, "finish", 1.0, 32, kn(alpha=5), healthy=True)[0]["w"] == 32
    new, act = F.aimd_update(st, "delay", 1.0, 32, k)
    assert new["w"] == 8 and act == "shadow_cut" and new["last_dec"] is None
    for ev in ("stop", "taskstop", "idle", "", None, 5):
        assert F.aimd_update(st, ev, 1.0, 32, k, error="rate_limit")[0]["w"] == 8


def test_aimd_window_clamps_garbage_state():
    k = kn(w0=8, wmin=2)
    assert F.aimd_window(None, 32, k) == 8
    assert F.aimd_window({}, 4, k) == 4                              # min(C_ceil, W0)
    assert F.aimd_window({"w": "x"}, 32, k) == 8
    assert F.aimd_window({"w": 10 ** 9}, 32, k) == 32
    assert F.aimd_window({"w": -5}, 32, k) == 2
    assert F.aimd_window({"w": 0}, 1, k) == 1                        # W_min cannot exceed C_ceil
    assert F.aimd_window({"w": 7}, 3, k) == 3
    assert F.aimd_new(32, k) == {"v": 1, "w": 8, "last_dec": None} and F.aimd_new(3, k)["w"] == 3


def test_aimd_window_stays_within_bounds_under_random_events_and_recovers():
    rng = random.Random(909)
    errors = ["rate_limit", "overloaded", "server_error", "unknown", "billing_error", None, "x"]
    events = ["finish", "stop_failure", "refusal", "delay", "other"]
    for _ in range(300):
        c_ceil = rng.randint(1, 32)
        k = F.parse_knobs({"STACK_FANOUT_DYN_W0": str(rng.randint(1, 40)), "STACK_FANOUT_DYN_WMIN": str(rng.randint(1, 5)),
                           "STACK_FANOUT_DYN_ALPHA": str(rng.randint(0, 4)),
                           "STACK_FANOUT_DYN_BETA_RL": str(rng.choice([0.1, 0.5, 0.99, 1])),
                           "STACK_FANOUT_DYN_BETA_FAIL": str(rng.choice([0.2, 0.75, 1])),
                           "STACK_FANOUT_DYN_HOLD_S": str(rng.choice([0, 1, 60]))})[0]
        lo = min(k["wmin"], c_ceil)
        st, now, last_cut = F.aimd_new(c_ceil, k), 0.0, None
        if rng.random() < 0.3:
            st = {"w": rng.randint(-10, 100), "last_dec": rng.choice([None, 0.0])}
        for _ in range(rng.randint(1, 60)):
            now += rng.choice([0.0, 0.5, 5.0, 61.0])
            before = copy.deepcopy(st)
            w0 = F.aimd_window(st, c_ceil, k)
            ev = rng.choice(events)
            st, act = F.aimd_update(before, ev, now, c_ceil, k, healthy=rng.random() < 0.6, error=rng.choice(errors))
            assert lo <= st["w"] <= c_ceil and lo <= F.aimd_window(st, c_ceil, k) <= c_ceil
            assert act in ("increase", "cut", "hold", "shadow_cut", "none")
            if act == "cut":
                assert st["w"] <= w0 and st["last_dec"] == now
                if last_cut is not None:
                    assert now - last_cut >= k["hold_s"]           # at most one decrease per HOLD
                last_cut = now
            elif act == "increase":
                assert st["w"] == min(c_ceil, w0 + k["alpha"]) and st["w"] > w0
            else:
                assert st["w"] == w0
        # recovery: enough healthy finishes restore the window to C_ceil (when alpha > 0)
        if k["alpha"] > 0:
            for _ in range(c_ceil + 1):
                st, _ = F.aimd_update(st, "finish", now, c_ceil, k, healthy=True)
            assert st["w"] == c_ceil


def test_aimd_recovers_after_stop_failure_and_refusal_sequences_and_n0_still_spawns():
    k = kn(w0=8, hold_s=60)
    st, now = F.aimd_new(32, k), 0.0
    for ev, err in [("stop_failure", "rate_limit"), ("refusal", None), ("stop_failure", "server_error"),
                    ("stop_failure", "overloaded"), ("refusal", None)]:
        now += 61.0
        st, act = F.aimd_update(st, ev, now, 32, k, error=err)
        assert act == "cut"
    assert st["w"] == 1
    d = dec(k, None, None, None, n=0, aimd=st)
    assert d["allow"]                                              # R4: W is ignored with nothing running
    assert not dec(k, None, None, None, n=1, aimd=st)["allow"] and dec(k, None, None, None, n=1, aimd=st)["code"] == "window"
    for i in range(1, 32):
        st, act = F.aimd_update(st, "finish", now, 32, k, healthy=True)
        assert (st["w"], act) == (min(32, 1 + i), "increase")
    assert st["w"] == 32
    assert dec(k, None, None, None, n=31, aimd=st)["allow"]
    assert F.aimd_update(st, "finish", now, 32, k, healthy=True)[0]["w"] == 32


# ------------------------------------------------------------------ breaker, nodes_for_plan
def test_breaker_trips_after_count_denials_in_window_and_resets_on_new_child():
    k = kn(breaker="5/600")
    plan = mkplan([{"id": "A", "a": "coder"}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "ta", "coder", 1.0)
    base = dict(plan=plan, node_id="A", n=1, live_tids={"ta"})
    for i in range(4):
        st = F.breaker_note_denial(st, 100.0 + i, k)
        assert not st["breaker"]["tripped"]
        assert dec(k, nodes=st, **base)["code"] == "running"
    st_ok = F.breaker_note_child(st)
    assert st_ok["breaker"]["denials"] == [] and not st_ok["breaker"]["tripped"]
    st = F.breaker_note_denial(st, 104.0, k)
    assert st["breaker"]["tripped"] is True
    d = dec(k, nodes=st, **base)
    assert d["allow"] and d["fallback"] and d["binding"] == "breaker"       # back to static
    assert dec(k, nodes=st, **dict(base, n=32))["allow"]                    # (the guard's own static cap applies)
    assert F.breaker_note_child(st)["breaker"]["tripped"] is True            # tripped for good


def test_breaker_window_expiry_and_disabled_and_denial_cap():
    k = kn(breaker="3/100")
    st = F.nodes_new("J1")
    for t in (0.0, 60.0, 151.0):                                   # the first denial is 151 s old at the third
        st = F.breaker_note_denial(st, t, k)
    assert not st["breaker"]["tripped"] and len(st["breaker"]["denials"]) == 2
    for t in (152.0, 153.0):
        st = F.breaker_note_denial(st, t, k)
    assert st["breaker"]["tripped"]
    off = kn(breaker="0/600")
    st = F.nodes_new("J1")
    for t in range(500):
        st = F.breaker_note_denial(st, float(t), off)
    assert not st["breaker"]["tripped"] and len(st["breaker"]["denials"]) <= 64
    st = F.nodes_new("J1")
    for t in range(0, 100000, 1000):
        st = F.breaker_note_denial(st, float(t), k)
    assert not st["breaker"]["tripped"]                              # spaced out: never trips


def test_nodes_for_plan_new_job_resets_runs_and_keeps_the_breaker():
    plan1, plan2 = mkplan([{"id": "A", "a": "coder"}]), F.parse_plan({"job": "J2", "nodes": [{"id": "A", "a": "coder"}]})
    st = F.record_spawn(F.nodes_new(plan1["job"]), "A", "ta", "coder", 1.0)
    st = F.breaker_note_denial(st, 10.0, kn())
    same = F.nodes_for_plan(st, plan1)
    assert same == st and same is not st and same["runs"] is not st["runs"]
    new = F.nodes_for_plan(st, plan2)
    assert new["job"] == "J2" and new["runs"] == {} and new["breaker"] == st["breaker"]
    assert F.nodes_for_plan(st, None) == st
    assert F.nodes_for_plan(None, plan2)["job"] == "J2"


# ------------------------------------------------------------------ node state functions
def test_state_lifecycle_unit():
    st = F.nodes_new("J1")
    st = F.record_spawn(st, "A", "t1", "coder", 5.0, iso=True)
    r = st["runs"]["A"][0]
    assert r == {"tid": "t1", "child_id": None, "type": "coder", "t_spawn": 5.0, "t_end": None, "outcome": None,
                 "iso": True}
    st, found = F.bind_child(st, "t1", "c1")
    assert found and st["runs"]["A"][0]["child_id"] == "c1"
    assert F.bind_child(st, "nope", "c9")[1] is False and F.bind_child(st, None, "c9")[1] is False
    st, found = F.end_run(st, "c1", 9.0, "failed")
    assert found and st["runs"]["A"][0]["t_end"] == 9.0 and st["runs"]["A"][0]["outcome"] == "failed"
    st, found = F.end_run(st, "c1", 99.0, "ok")                      # the first end wins
    assert found and st["runs"]["A"][0]["t_end"] == 9.0 and st["runs"]["A"][0]["outcome"] == "failed"
    assert F.end_run(st, "zz", 1.0)[1] is False and F.end_run(st, None, 1.0)[1] is False
    st2, _ = F.end_run(F.bind_child(F.record_spawn(F.nodes_new("J"), None, "u", "coder", 1.0), "u", "cu")[0], "cu", 2.0, "Bad Outcome!")
    assert st2["unplanned"][0]["outcome"] == "other"
    st, found = F.remove_run(st, "t1")
    assert found and "A" not in st["runs"]
    assert F.remove_run(st, "t1")[1] is False and F.remove_run(st, None)[1] is False
    st = F.record_spawn(st, None, "u1", "verifier", 1.0)
    assert F.remove_run(st, "u1")[1] is True


def test_compact_drops_aborted_and_ended_unplanned_only():
    st = F.nodes_new("J1")
    st = F.record_spawn(st, "A", "ab", "coder", 1.0)                                  # aborted
    st = F.record_spawn(st, "A", "ok", "coder", 2.0)
    st, _ = F.bind_child(st, "ok", "c_ok")
    st, _ = F.end_run(st, "c_ok", 3.0)                                                # ended
    st = F.record_spawn(st, "B", "lv", "coder", 4.0)                                   # live lease
    st = F.record_spawn(st, None, "u_end", "coder", 5.0)
    st, _ = F.bind_child(st, "u_end", "cu_end")                                       # ended unplanned
    st = F.record_spawn(st, None, "u_live", "coder", 6.0)
    st, _ = F.bind_child(st, "u_live", "cu_live")
    out = F.compact(st, {"lv"}, {"cu_live"})
    assert [r["tid"] for r in out["runs"]["A"]] == ["ok"] and [r["tid"] for r in out["runs"]["B"]] == ["lv"]
    assert [r["tid"] for r in out["unplanned"]] == ["u_live"]
    assert F.compact(F.record_spawn(F.nodes_new("J"), "A", "x", "coder", 1.0), set(), set())["runs"] == {}


def test_record_spawn_bounds_the_state_and_keeps_the_new_run():
    st = F.nodes_new("J1")
    for i in range(200):
        st = F.record_spawn(st, "A", "t%d" % i, "coder", float(i))
        assert st["runs"]["A"][-1]["tid"] == "t%d" % i
        st = F.record_spawn(st, None, "u%d" % i, "coder", float(i))
    assert len(st["runs"]["A"]) == F.RUNS_KEPT and len(st["unplanned"]) == F.UNPLANNED_KEPT


def test_mark_ready_and_unplanned_live():
    st = F.nodes_new("J1")
    st = F.mark_ready(st, ["A", "B"], 10.0)
    st = F.mark_ready(st, ["A", "C"], 20.0)
    assert st["ready_ts"] == {"A": 10.0, "B": 10.0, "C": 20.0}
    st = F.record_spawn(st, None, "u1", "coder", 1.0)
    st = F.record_spawn(st, None, "u2", "coder", 1.0)
    st, _ = F.bind_child(st, "u2", "cu2")
    assert F.unplanned_live(st, {"u1"}, set()) == 1
    assert F.unplanned_live(st, {"u1"}, {"cu2"}) == 2
    assert F.unplanned_live(st, set(), set()) == 0


def _snapshot_state_funcs():
    st = F.nodes_new("J1")
    st = F.record_spawn(st, "A", "t1", "coder", 1.0)
    st, _ = F.bind_child(st, "t1", "c1")
    st = F.record_spawn(st, "B", "t2", "coder", 2.0)
    st = F.record_spawn(st, None, "t3", "coder", 3.0)
    st = F.breaker_note_denial(st, 4.0, kn())
    return st


@pytest.mark.parametrize("name,call", [
    ("record_spawn", lambda s: F.record_spawn(s, "A", "tx", "coder", 9.0)),
    ("record_spawn_unplanned", lambda s: F.record_spawn(s, None, "tx", "coder", 9.0)),
    ("bind_child", lambda s: F.bind_child(s, "t2", "c2")[0]),
    ("end_run", lambda s: F.end_run(s, "c1", 9.0, "ok")[0]),
    ("remove_run", lambda s: F.remove_run(s, "t2")[0]),
    ("remove_run_unplanned", lambda s: F.remove_run(s, "t3")[0]),
    ("compact", lambda s: F.compact(s, set(), set())),
    ("mark_ready", lambda s: F.mark_ready(s, ["A"], 9.0)),
    ("note_understated", F.note_understated),
    ("breaker_note_denial", lambda s: F.breaker_note_denial(s, 9.0, kn())),
    ("breaker_note_child", F.breaker_note_child),
    ("nodes_for_plan_same", lambda s: F.nodes_for_plan(s, {"job": "J1", "nodes": []})),
    ("nodes_for_plan_new", lambda s: F.nodes_for_plan(s, {"job": "J2", "nodes": []})),
])
def test_state_functions_return_new_copies_and_never_mutate_inputs(name, call):
    st = _snapshot_state_funcs()
    snap = copy.deepcopy(st)
    out = call(st)
    assert st == snap, "%s mutated its input" % name
    assert out is not st
    # the result shares no container with the input: scribble over it, the input stays intact
    for key in ("runs", "unplanned", "ready_ts", "breaker"):
        assert out[key] is not st[key], "%s aliases %s" % (name, key)
    for runs in list(out["runs"].values()) + [out["unplanned"]]:
        for r in runs:
            r["tid"] = "SCRIBBLE"
        runs.append({"tid": "SCRIBBLE"})
    out["breaker"]["denials"].append(-1.0)
    out["ready_ts"]["ZZ"] = 1.0
    out["runs"]["ZZ"] = []
    assert st == snap
    json.dumps(out)                                                 # JSON-serializable state


def test_pure_functions_never_mutate_inputs_and_are_deterministic():
    rng = random.Random(1001)
    for _ in range(200):
        c = rand_call(rng, "enforce")
        before = copy.deepcopy({k: v for k, v in c.items() if k != "env"})
        d1 = run_call(c)
        after = {k: v for k, v in c.items() if k != "env"}
        assert after == before                                     # decision, plan, nodes, aimd: untouched
        d2 = run_call(c)
        assert json.dumps(d1, sort_keys=True, default=str) == json.dumps(d2, sort_keys=True, default=str)
        d3 = run_call(dict(c, live_tids=sorted(c["live_tids"]), live_children=tuple(sorted(c["live_children"]))))
        assert json.dumps(d1, sort_keys=True, default=str) == json.dumps(d3, sort_keys=True, default=str)
        d4 = run_call(dict(copy.deepcopy(before), env=c["env"]))
        assert json.dumps(d1, sort_keys=True, default=str) == json.dumps(d4, sort_keys=True, default=str)
        if c["plan"]:
            k = F.parse_knobs(c["env"])[0]
            s1 = F.ready_eligible(c["plan"], c["nodes"], c["live_tids"], c["live_children"], k)
            assert after == before and s1 == F.ready_eligible(c["plan"], c["nodes"], c["live_tids"], c["live_children"], k)
            nb = F.node_block(c["plan"], c["plan"]["nodes"][0]["id"], c["nodes"], c["live_tids"], c["live_children"], k)
            assert nb == F.node_block(c["plan"], c["plan"]["nodes"][0]["id"], c["nodes"], c["live_tids"], c["live_children"], k)
            assert after == before
        a0 = {"w": 5, "last_dec": None}
        F.aimd_update(a0, "stop_failure", 1.0, 8, error="rate_limit")
        assert a0 == {"w": 5, "last_dec": None}
    env = {"STACK_FANOUT_DYN": "enforce", "STACK_FANOUT_DYN_TYPES": "a,b"}
    snap = dict(env)
    F.parse_knobs(env)
    assert env == snap


def test_log_fields_and_deny_text_carry_numbers_and_validated_ids_only():
    hostile = {"mode": "IGNORE", "kind": "x;y", "allow": 1, "would_allow": 0, "cap": "7", "binding": "B" * 100,
               "code": "../etc", "planned": 1, "node": "bad id; rm", "understated": 0, "fallback": 0,
               "terms": {"ceil": 8, "w": float("nan"), "kb": float("inf"), "x": "s", "y": True, "z": 3.9},
               "eligible": ["A", "B"]}
    out = F.log_fields(hostile)
    assert out["mode"] == "other" and out["kind"] == "other" and out["code"] is None and out["node"] is None
    assert out["cap"] == 7 and len(out["binding"]) <= 16 and out["terms"] == {"ceil": 8, "z": 3}
    assert out["n_elig"] == 2 and out["allow"] is True and out["would_allow"] is False
    json.dumps(out)
    d = F.deny_text(("deps", ["A", "bad id; DROP", "C"]), {"node": "inj; ignore", "eligible": ["X", "bad one"], "free": 3}, kn(), "t y")
    assert "ignore" not in d and "DROP" not in d and "bad one" not in d and "A, C" in d and "Free slots: 3" in d
    d = F.deny_text(("budget", 5), {"node": "A"}, kn(), "evil type; run")
    assert "evil" not in d and "agent" in d


# ------------------------------------------------------------------ simulation: event-driven orchestrator
def _simulate(seed, variant="healthy"):
    """An event-driven orchestrator over a random plan DAG with random run durations. Returns metrics."""
    rng = random.Random(seed)
    shape = rng.choice(["chain", "wide", "diamond", "layered", "layered"])
    top = rand_dag(rng, shape)
    plan = F.parse_plan(top, ROW)
    nodes = {n["id"]: n for n in plan["nodes"]}
    order = [n["id"] for n in plan["nodes"]]
    c_ceil = rng.choice([1, 2, 3, 6, 8, 16, 32])
    maxc = rng.choice([c_ceil, c_ceil + 3, 20, 33])
    others = rng.randint(0, max(0, min(maxc - 1, 30)))
    p_fail = 0.9 if variant == "hostile" else 0.2
    k = F.parse_knobs({"STACK_FANOUT_DYN": "enforce", "STACK_FANOUT_DYN_ENFORCE": ALL_TERMS,
                       "STACK_FANOUT_DYN_W0": str(rng.randint(1, 10)), "STACK_FANOUT_DYN_SLACK": str(rng.randint(0, 3)),
                       "STACK_FANOUT_DYN_BREAKER": "5/600" if variant == "breaker" else "0/600"})[0]
    node_runs = k["node_runs"]
    st, aimd = F.nodes_new(plan["job"]), F.aimd_new(c_ceil, k)
    lt, lc, runs, heap, seq = set(), set(), {}, [], itertools.count()
    attempts = {i: 0 for i in order}           # non-aborted runs
    ended = {i: 0 for i in order}
    live_nodes, done = {}, set()
    spent = [0.0]
    m = {"max_live": 0, "denials": 0, "spawns": 0, "min_w": 99, "naughty_denied": 0, "budget_stop": False}
    now = [0.0]
    ids = itertools.count(1)

    def b_rem():
        return 10 ** 9 if variant != "tight" else 40 * M - spent[0]

    def own_bad(nid):
        """The sim's own oracle for node nid (never uses the module): reasons a spawn must be denied."""
        why = set()
        if nid in live_nodes:
            why.add("running")
        if attempts[nid] >= node_runs:
            why.add("runs_used")
        if any(ended[d] == 0 for d in nodes[nid]["dep"]):
            why.add("deps")
        for u in live_nodes:
            if u == nid:
                continue
            if "accel" in nodes[nid].get("r", []) and "accel" in nodes[u].get("r", []):
                why.add("exclusive")
            if set(nodes[nid].get("w", [])) & set(nodes[u].get("w", [])):
                why.add("conflict")
        return why

    def attempt(nid):
        n = len(lt) + len(lc)
        ladder = F.chain_types(nodes[nid]) if nid else ("verifier",)
        ctype = ladder[min(attempts[nid] // 2, len(ladder) - 1)] if nid else "verifier"
        k_sess = maxc - others - n
        bad = own_bad(nid) if nid else set()
        d = F.dyn_decision(k, "spawn", "o1", "orchestrator", c_ceil, n, ctype, plan=plan, nodes=st, node_id=nid,
                           live_tids=lt, live_children=lc, b_rem=b_rem(), commit=0.0, aimd=aimd, k_sess=k_sess)
        allowed = d["allow"] and k_sess >= 1 and n < c_ceil      # the guard's own static checks
        tripped = st["breaker"]["tripped"] or st["plan_off"]
        assert d["cap"] <= c_ceil
        if bad and not tripped:
            assert not d["allow"] and d["code"] in bad, (nid, bad, d["code"], d["reason"])
            m["naughty_denied"] += 1
        if not allowed:
            m["denials"] += 1
            if n == 0 and not bad:
                if variant == "tight":
                    assert d["code"] == "budget"                       # liveness holds while K_B >= 1
                    m["budget_stop"] = True
                else:
                    pytest.fail("liveness (R4): n=0, node %s ready, denied %r %r" % (nid, d["code"], d["reason"]))
            elif n < c_ceil and k_sess >= 1 and not bad and d["code"] != "budget":
                pass
            if n < c_ceil and not bad:
                nonlocal_st(F.breaker_note_denial(st, now[0], k))
            return False
        # allowed: invariants
        assert n + 1 <= c_ceil and others + n + 1 <= maxc
        if not tripped and nid:
            assert not bad
        tid = "tid%d" % next(ids)
        nonlocal_st(F.breaker_note_child(F.record_spawn(st, nid, tid, ctype, now[0])))
        if nid and d["understated"]:
            nonlocal_st(F.note_understated(st))
        if not nid and d["understated"]:
            nonlocal_st(F.note_understated(st))
        lt.add(tid)
        runs[tid] = {"nid": nid, "type": ctype}
        if nid:
            live_nodes[nid] = live_nodes.get(nid, 0) + 1
            attempts[nid] += 1
        spent[0] += F.c_med(None, ctype)
        m["spawns"] += 1
        m["max_live"] = max(m["max_live"], len(lt) + len(lc))
        assert m["max_live"] <= c_ceil and others + len(lt) + len(lc) <= maxc
        r = rng.random()
        if r < 0.06:
            heapq.heappush(heap, (now[0] + 0.1, next(seq), "abort_remove", tid))
        elif r < 0.12:
            heapq.heappush(heap, (now[0] + 0.1, next(seq), "abort_drop", tid))
        else:
            heapq.heappush(heap, (now[0] + rng.uniform(0.1, 2.0), next(seq), "start", tid))
        return True

    def nonlocal_st(new):
        nonlocal st
        st = new

    def pump():
        ready = [i for i in order if i not in done and i not in live_nodes and all(d in done for d in nodes[i]["dep"])]
        rng.shuffle(ready)
        undone = [i for i in order if i not in done]
        cands, gave_up = list(ready), False
        if undone and rng.random() < 0.3:
            cands.append(rng.choice(undone))                           # a possibly premature or duplicate spawn
        for nid in cands:
            if attempts[nid] >= node_runs and nid in ready:
                done.add(nid)                                           # runs used up: the orchestrator does it itself
                gave_up = True
                continue
            if m["budget_stop"]:
                return False
            attempt(nid)
        if rng.random() < 0.1 and not m["budget_stop"]:
            attempt(None)
        return gave_up                                                  # dependents may now be ready

    guard = 0
    while True:
        guard += 1
        assert guard < 20000, "no progress"
        while pump():
            pass
        m["min_w"] = min(m["min_w"], F.aimd_window(aimd, c_ceil, k))
        if m["budget_stop"]:
            break
        if not heap:
            assert len(done) == len(order), "deadlock: %d of %d nodes done, nothing running" % (len(done), len(order))
            break
        t, _, kind, key = heapq.heappop(heap)
        now[0] = t
        if kind in ("abort_remove", "abort_drop"):
            lt.discard(key)
            info = runs.pop(key)
            if kind == "abort_remove":
                nst, found = F.remove_run(st, key)
                assert found
                st = nst
            if info["nid"]:
                live_nodes[info["nid"]] -= 1
                if not live_nodes[info["nid"]]:
                    del live_nodes[info["nid"]]
                attempts[info["nid"]] -= 1                              # aborted runs do not count
        elif kind == "start":
            cid = "child-" + key
            st, found = F.bind_child(st, key, cid)
            assert found
            lt.discard(key)
            lc.add(cid)
            runs[cid] = runs.pop(key)
            heapq.heappush(heap, (t + rng.lognormvariate(3, 1), next(seq), "end", cid))
        else:
            info = runs.pop(key)
            lc.discard(key)
            ok = rng.random() >= p_fail
            st, found = F.end_run(st, key, t, "ok" if ok else "failed")
            assert found
            if info["nid"]:
                live_nodes[info["nid"]] -= 1
                if not live_nodes[info["nid"]]:
                    del live_nodes[info["nid"]]
                ended[info["nid"]] += 1
                if ok:
                    done.add(info["nid"])
            if ok:
                aimd, _ = F.aimd_update(aimd, "finish", t, c_ceil, k, healthy=True)
            else:
                err = rng.choice(["rate_limit", "overloaded", "server_error", "unknown", "billing_error", None])
                aimd, _ = F.aimd_update(aimd, "stop_failure", t, c_ceil, k, error=err)
                if rng.random() < 0.1:
                    aimd, _ = F.aimd_update(aimd, "refusal", t, c_ceil, k)
            assert 1 <= aimd["w"] <= c_ceil and 1 <= F.aimd_window(aimd, c_ceil, k) <= c_ceil
    if variant != "tight":
        assert len(done) == len(order) and not lt and not lc and not heap
    return m


@pytest.mark.parametrize("seed", range(80))
def test_simulation_healthy_budget_never_exceeds_caps_and_always_finishes(seed):
    m = _simulate(seed, "healthy")
    assert m["spawns"] >= 1 and m["min_w"] >= 1


@pytest.mark.parametrize("seed", range(30))
def test_simulation_hostile_failures_still_finish_within_caps(seed):
    _simulate(1000 + seed, "hostile")


@pytest.mark.parametrize("seed", range(30))
def test_simulation_with_the_breaker_enabled_never_exceeds_caps_and_finishes(seed):
    _simulate(2000 + seed, "breaker")


@pytest.mark.parametrize("seed", range(30))
def test_simulation_tight_budget_only_ever_refuses_on_budget_when_idle(seed):
    _simulate(3000 + seed, "tight")


def test_simulation_exercises_the_interesting_paths():
    tot = {"denials": 0, "naughty_denied": 0, "spawns": 0}
    widest = 0
    for s in range(60):
        m = _simulate(4000 + s, "healthy")
        for key in tot:
            tot[key] += m[key]
        widest = max(widest, m["max_live"])
    assert tot["denials"] > 100 and tot["naughty_denied"] > 50 and widest >= 4


def test_simulation_is_deterministic():
    assert _simulate(77, "healthy") == _simulate(77, "healthy")


def test_one_glob_pair_cannot_outrun_the_conflict_deadline():
    """A class over all of Unicode once took seconds per glob pair (ranges were expanded into sets
    and the deadline was checked only between pairs); now each pair is cheap."""
    wide = "[" + "\x01-\U0010ffff" * 8 + "]"           # one class, 8 ranges over all of Unicode
    plan = mkplan([{"id": "A", "a": "coder", "w": [wide + "a/b"]},
                   {"id": "B", "a": "coder", "w": [wide + "b/c"]}])
    st = F.record_spawn(F.nodes_new("J1"), "A", "tuA", "coder", 1.0)
    t0 = time.perf_counter()
    dec(kn(), plan, st, "B", live_tids={"tuA"}, live_children=set())
    assert time.perf_counter() - t0 < 1.0
