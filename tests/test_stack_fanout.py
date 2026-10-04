"""stack_fanout.py: the dynamic fan-out decision core (dynamic fan-out plan, step 4 / D1-D3).

Run: uv run --no-project --python 3.13 --with pytest pytest -q tests/test_stack_fanout.py
The module's own invariants only; the property and simulation tests (step 5a) live elsewhere.
"""
import importlib.util
import json
import random
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOD = ROOT / "dot-claude" / "hooks" / "stack_fanout.py"
spec = importlib.util.spec_from_file_location("stack_fanout", MOD)
F = importlib.util.module_from_spec(spec)
sys.modules["stack_fanout"] = F
spec.loader.exec_module(F)

ORCH_ROW = ["coder", "main-coder", "ninja-coder", "verifier", "python-engineer",
            "code-reviewer", "designer"]


def knobs(mode="enforce", **env):
    e = {"STACK_FANOUT_DYN": mode}
    e.update(env)
    k, warnings = F.parse_knobs(e)
    assert not warnings, warnings
    return k


def plan_of(nodes, **top):
    return F.parse_plan(json.dumps(dict({"job": "j1", "nodes": nodes}, **top)), ORCH_ROW)


def decide(k, plan, nodes, node_id, child="coder", n=0, c_ceil=32, **kw):
    return F.dyn_decision(k, "spawn", "orch1", "orchestrator", c_ceil, n, child, plan=plan,
                          nodes=nodes, node_id=node_id, **kw)


# ---------------------------------------------------------------- D1: chain walk, aborted runs
def test_chain_walk_allows_exactly_six_runs_then_runs_used():
    k = knobs(STACK_FANOUT_DYN_ENFORCE="node,deps,conflict,budget,aimd")
    plan = plan_of([{"id": "T1", "a": "coder", "w": ["src/**"]}])
    st = F.nodes_new("j1")
    walk = ["coder", "coder", "main-coder", "main-coder", "ninja-coder", "ninja-coder"]
    for i, child in enumerate(walk):
        nid, why = F.node_of(plan, "T1 build parser", child)
        assert (nid, why) == ("T1", "planned")
        r = decide(k, plan, st, nid, child, live_tids=set(), live_children=set())
        assert r["allow"] and r["would_allow"] and r["planned"], (i, r)
        st = F.record_spawn(st, nid, "tu%d" % i, child, 100.0 + i)
        # while the lease is live the node is running
        r2 = decide(k, plan, st, nid, child, live_tids={"tu%d" % i})
        assert not r2["allow"] and r2["code"] == "running"
        st, ok = F.bind_child(st, "tu%d" % i, "c%d" % i)
        assert ok
        st, ok = F.end_run(st, "c%d" % i, 150.0 + i, "failed")
        assert ok
    r = decide(k, plan, st, "T1", "ninja-coder")
    assert not r["allow"] and r["code"] == "runs_used"
    assert "6 runs" in r["reason"] and "STACK_FANOUT_DYN_NODE_RUNS" in r["reason"]


def test_chain_types_and_unplanned_labels():
    plan = plan_of([{"id": "T1", "a": "main-coder"}, {"id": "T2", "a": "python-engineer",
                                                      "alt": "coder"},
                    {"id": "T3", "a": "verifier"}])
    assert F.chain_types(plan["nodes"][0]) == ("main-coder", "ninja-coder")
    assert F.node_of(plan, "T1: fix", "coder") == (None, "type_mismatch")   # not later on the chain
    assert F.node_of(plan, "T2 port", "main-coder") == ("T2", "planned")     # after its alt coder
    assert F.node_of(plan, "T3 verify", "main-coder") == (None, "type_mismatch")
    assert F.node_of(plan, "T9 x", "coder") == (None, "unknown_node")
    assert F.node_of(plan, "", "coder") == (None, "no_label")
    assert F.node_of(None, "T1", "main-coder") == (None, "no_plan")


def test_aborted_runs_are_not_live_and_not_counted():
    k = knobs()
    plan = plan_of([{"id": "T1", "a": "coder"}])
    st = F.nodes_new("j1")
    for i in range(12):                   # 12 spawns whose lease vanished before a child bound
        st = F.record_spawn(st, "T1", "tu%d" % i, "coder", float(i))
    runs = st["runs"]["T1"]
    assert all(F.run_status(r, set(), set()) == "aborted" for r in runs)
    assert F.node_block(plan, "T1", st, set(), set(), k) is None
    r = decide(k, plan, st, "T1")
    assert r["allow"] and r["would_allow"]
    # the same run is live while its lease exists, or while its bound child is not stopped
    assert F.run_status(runs[0], {"tu0"}, set()) == "live"
    st2, _ = F.bind_child(st, "tu0", "c0")
    assert F.run_status(st2["runs"]["T1"][0], set(), {"c0"}) == "live"
    assert F.run_status(st2["runs"]["T1"][0], set(), set()) == "ended"
    assert F.compact(st, set(), set())["runs"] == {}


def test_remove_run_frees_the_node():
    k = knobs()
    plan = plan_of([{"id": "T1", "a": "ninja-coder"}])
    st = F.record_spawn(F.nodes_new("j1"), "T1", "tu1", "ninja-coder", 1.0)
    assert decide(k, plan, st, "T1", "ninja-coder", live_tids={"tu1"})["code"] == "running"
    st, found = F.remove_run(st, "tu1")       # a later gate (a taint mark it could not record) denied it
    assert found and st["runs"] == {}
    assert decide(k, plan, st, "T1", "ninja-coder", live_tids={"tu1"})["allow"]


def test_dependencies_conflicts_and_exclusive_tags():
    k = knobs(STACK_FANOUT_DYN_ENFORCE="node,deps,conflict")
    plan = plan_of([{"id": "A", "a": "coder", "w": ["src/a/**"]},
                    {"id": "B", "a": "coder", "dep": ["A"]},
                    {"id": "C", "a": "coder", "w": ["src/a/x.py"]},
                    {"id": "D", "a": "designer", "r": ["gui"]},
                    {"id": "E", "a": "coder", "r": ["gui"]}])
    st = F.nodes_new("j1")
    r = decide(k, plan, st, "B")
    assert not r["allow"] and r["code"] == "deps" and "waits on A" in r["reason"]
    st = F.record_spawn(st, "A", "ta", "coder", 1.0)
    st = F.record_spawn(st, "D", "td", "designer", 1.0)
    live = {"ta", "td"}
    assert decide(k, plan, st, "C", live_tids=live)["code"] == "conflict"
    assert decide(k, plan, st, "C", live_tids=live, isolation="worktree")["allow"]
    assert decide(k, plan, st, "E", live_tids=live)["code"] == "exclusive"
    assert decide(k, plan, st, "B", live_tids=live)["code"] == "deps"     # A still live
    st, _ = F.bind_child(st, "ta", "ca")
    st, _ = F.end_run(st, "ca", 5.0)
    assert decide(k, plan, st, "B", live_tids={"td"})["allow"]
    elig, blocked = F.ready_eligible(plan, st, {"td"}, set(), k)
    assert elig == ["A", "B", "C"] and blocked["E"][0] == "exclusive" and blocked["D"][0] == "running"


def test_unplanned_spawns_and_understated_switch_off():
    k = knobs()
    plan = plan_of([{"id": "T1", "a": "coder"}], slack=1)
    st = F.record_spawn(F.nodes_new("j1"), None, "u1", "verifier", 1.0)
    r = decide(k, plan, st, None, "verifier", live_tids=set())
    assert r["allow"] and not r["understated"]
    r = decide(k, plan, st, None, "verifier", live_tids={"u1"})
    assert r["allow"] and r["understated"]                  # past the slack: allowed, flagged
    for _ in range(F.UNDERSTATED_MAX):
        st = F.note_understated(st)
    assert st["plan_off"]
    st = F.record_spawn(st, "T1", "t1", "coder", 2.0)
    assert decide(k, plan, st, "T1", live_tids={"t1"})["allow"]   # plan terms are off now


# ---------------------------------------------------------------- D2: budget
def test_budget_worked_case_k_b_at_least_one():
    b_rem = F.budget_remaining(100000000, 1920000000, 1850000000, 10000000)
    assert b_rem == 70000000
    assert F.k_budget(b_rem, 0, F.RESERVE_TOK, [1000000]) == 62
    model = {"types": {"coder": {"turns": {"M": 10}, "ctx": {"a": 100000, "b": 0}}}}
    assert F.c_med(model, "coder") == 1000000
    plan = plan_of([{"id": "T1", "a": "coder"}])
    r = decide(knobs(STACK_FANOUT_DYN_ENFORCE="budget"), plan, F.nodes_new("j1"), "T1", n=0,
               b_rem=b_rem, model=model)
    assert r["allow"] and r["terms"]["kb"] == 62


def test_budget_denies_only_when_enforced_and_fails_open_when_unknown():
    model = {"types": {"coder": {"turns": {"M": 10}, "ctx": {"a": 100000, "b": 0}}}}
    commit = F.commit_tokens([("coder", 200000)], model)
    assert commit == 800000
    assert F.k_budget(8500000, 0, F.RESERVE_TOK, [1000000]) == 0
    r = decide(knobs(STACK_FANOUT_DYN_ENFORCE="budget"), None, None, None, n=1, b_rem=8500000,
               model=model)
    assert not r["allow"] and r["code"] == "budget"
    r = decide(knobs(), None, None, None, n=1, b_rem=8500000, model=model)
    assert r["allow"] and not r["would_allow"]              # budget not in the enforce list
    assert F.budget_remaining(0, 0, 5, 5) is None
    assert F.k_budget(None, 0, 0, [1.0]) is None
    bad = {"types": {"coder": {"turns": {"M": "many"}}}}
    r = decide(knobs(STACK_FANOUT_DYN_ENFORCE="budget"), None, None, None, n=1, b_rem=1, model=bad)
    assert r["allow"] and "kb" not in r["terms"]             # malformed model: K_B = infinity


# ---------------------------------------------------------------- R1, R3, R4
def test_r1_dynamic_cap_never_above_static_and_off_shadow_always_allow():
    rnd = random.Random(7)
    plan = plan_of([{"id": "T%d" % i, "a": "coder", "dep": ["T%d" % (i - 1)] if i % 3 != 1 else []}
                    for i in range(1, 10)])
    for _ in range(400):
        mode = rnd.choice(F.MODES)
        k = knobs(mode, STACK_FANOUT_DYN_ENFORCE="node,deps,conflict,budget,aimd",
                  STACK_FANOUT_DYN_W0=str(rnd.randint(1, 40)))
        c_ceil, n = rnd.randint(1, 40), rnd.randint(0, 45)
        st = F.nodes_new("j1")
        tids = set()
        for i in range(rnd.randint(0, 6)):
            nid = "T%d" % rnd.randint(1, 9)
            st = F.record_spawn(st, nid, "t%d" % i, "coder", 0.0)
            if rnd.random() < 0.5:
                tids.add("t%d" % i)
        r = decide(k, plan, st, rnd.choice(["T1", "T4", "T7", None]), n=n, c_ceil=c_ceil,
                   live_tids=tids, b_rem=rnd.choice([None, 0, 9e6, 7e7]),
                   aimd={"w": rnd.randint(-3, 50)}, k_sess=rnd.choice([None, -2, 0, 5, 40]))
        assert r["cap"] <= c_ceil
        if mode != "enforce":
            assert r["allow"]
        if r["allow"] and mode == "enforce":
            assert n < c_ceil


@pytest.mark.parametrize("kw", [
    {"n": "x"}, {"n": -1}, {"plan": {"nodes": "bad"}}, {"plan": {"nodes": [{"id": "T1"}]}},
    {"nodes": {"runs": {"T1": "zz"}}, "plan": "PLAN"}, {"aimd": {"w": object()}},
    {"live_tids": 5}, {"kind": "fork"},
])
def test_r3_bad_input_falls_back_to_static(kw):
    plan = plan_of([{"id": "T1", "a": "coder"}])
    if kw.get("plan") == "PLAN":
        kw["plan"] = plan
    kind = kw.pop("kind", "spawn")
    args = dict(plan=plan, nodes=None, node_id="T1")
    args.update(kw)
    n = args.pop("n", 0)
    r = F.dyn_decision(knobs(), kind, "orch1", "orchestrator", 32, n, "coder", **args)
    assert r["allow"] and r["cap"] <= 32
    assert r["fallback"] or r["would_allow"], r


def test_r3_exception_is_static_and_scope_is_orchestrator_only():
    r = F.dyn_decision(knobs(), "spawn", "orch1", "orchestrator", 32, 0, "coder", plan=object(),
                       node_id="T1")
    assert r["allow"] and r["fallback"] and r["binding"] == "error"
    k = knobs(STACK_FANOUT_DYN_TYPES="orchestrator,blackcat,main-coder")
    for caller, ctype in (("main", "blackcat"), ("main", None), ("a1", "blackcat")):
        assert not F.in_scope(caller, ctype, 32, k)
    assert F.in_scope("a1", "main-coder", 6, k) and not F.in_scope("a1", "main-coder", 0, k)
    r = F.dyn_decision(knobs(), "spawn", "a1", "main-coder", 6, 99, "coder")
    assert r["allow"] and r["binding"] == "scope"
    assert F.dyn_decision(knobs("off"), "spawn", "o", "orchestrator", 32, 99, "coder")["binding"] == "off"
    assert F.parse_knobs({"STACK_FANOUT_DYN": "enforce", "STACK_POLICY": "off"})[0]["mode"] == "off"


def test_r4_window_ignored_with_no_child_and_shadow_logs_would_deny():
    k = knobs(STACK_FANOUT_DYN_ENFORCE="aimd")
    assert decide(k, None, None, None, n=0, aimd={"w": 1})["allow"]
    r = decide(k, None, None, None, n=1, aimd={"w": 1})
    assert not r["allow"] and r["code"] == "window"
    r = decide(knobs("shadow", STACK_FANOUT_DYN_ENFORCE="aimd"), None, None, None, n=1,
               aimd={"w": 1})
    assert r["allow"] and not r["would_allow"] and r["code"] == "window"
    rec = F.log_fields(r)
    assert json.loads(json.dumps(rec)) == rec and rec["would_allow"] is False


def test_breaker_trips_after_denials_without_a_new_child():
    k = knobs(STACK_FANOUT_DYN_BREAKER="3/600")
    st = F.nodes_new("j1")
    st = F.breaker_note_denial(st, 0.0, k)
    st = F.breaker_note_denial(st, 10.0, k)
    st = F.breaker_note_child(st)
    st = F.breaker_note_denial(st, 20.0, k)
    st = F.breaker_note_denial(st, 700.0, k)       # the one at 20 s is out of the window
    assert not st["breaker"]["tripped"]
    st = F.breaker_note_denial(st, 710.0, k)
    st = F.breaker_note_denial(st, 720.0, k)
    assert st["breaker"]["tripped"]
    r = decide(knobs(STACK_FANOUT_DYN_ENFORCE="aimd"), None, st, None, n=5, aimd={"w": 1})
    assert r["allow"] and r["binding"] == "breaker"


# ---------------------------------------------------------------- D3: AIMD
def test_aimd_updates():
    k = knobs()
    st = F.aimd_new(32, k)
    assert st["w"] == 8
    st, act = F.aimd_update(st, "stop_failure", 100.0, 32, k, error="rate_limit")
    assert (st["w"], act) == (4, "cut")
    st, act = F.aimd_update(st, "stop_failure", 130.0, 32, k, error="overloaded")
    assert (st["w"], act) == (4, "hold")                   # within HOLD_S of the last cut
    st, act = F.aimd_update(st, "stop_failure", 200.0, 32, k, error="server_error")
    assert (st["w"], act) == (3, "cut")
    for err in ("billing_error", "authentication_failed", "max_output_tokens", "invalid_request"):
        assert F.aimd_update(st, "stop_failure", 999.0, 32, k, error=err)[1] == "none"
    st, act = F.aimd_update(st, "finish", 300.0, 32, k, healthy=True)
    assert (st["w"], act) == (4, "increase")
    assert F.aimd_update(st, "finish", 300.0, 32, k, healthy=False)[1] == "none"
    assert F.aimd_update(st, "delay", 300.0, 32, k) == (st, "shadow_cut")
    low = {"w": 1, "last_dec": None}
    assert F.aimd_update(low, "refusal", 0.0, 32, k)[0]["w"] == 1       # W_min floor
    assert F.aimd_update({"w": 4}, "finish", 0.0, 4, k, healthy=True)[0]["w"] == 4   # capped at C_ceil
    assert F.aimd_window({"w": 50}, 32, k) == 32


def test_healthy_finish_and_delay_ratio():
    assert F.finish_healthy(True, 100, 200, False, 30e6, 100e6)
    assert not F.finish_healthy(True, 100, 200, False, 20e6, 100e6)   # B_rem < 0.25 x hard.prompt
    assert not F.finish_healthy(True, 300, 200, False, None, 100e6)
    assert not F.finish_healthy(True, 100, 200, True, None, 0)
    model = {"types": {"coder": {"sec_per_call": {"p50": 5, "p90": 10}}}}
    r = F.delay_ratio([("coder", 0.0, 10), ("coder", 0.0, 2)], 300.0, model)
    assert r == pytest.approx(3.0)
    assert F.delay_ratio([], 1.0, None) is None


# ---------------------------------------------------------------- plan validation and CLI
def test_parse_plan_accepts_and_rejects_with_safe_text():
    plan = plan_of([{"id": "T1", "a": "coder", "s": "M", "w": ["src/**"]},
                    {"id": "T2", "a": "coder", "dep": ["T1"]},
                    {"id": "T3", "a": "verifier", "dep": ["T1"]}])
    assert F.plan_accept_text(plan) == "plan accepted: 3 nodes, max width 2"
    cases = [
        ({"job": "j", "nodes": [{"id": "T3", "a": "coder", "dep": ["T5"]},
                                {"id": "T5", "a": "coder", "dep": ["T3"]}]}, "cycle T3→T5→T3"),
        ({"job": "j", "nodes": [{"id": "<script>", "a": "coder"}]}, "node 0: id must match"),
        ({"job": "j", "nodes": [{"id": "T1", "a": "blackcat"}]}, "not an agent type this caller"),
        ({"job": "j", "nodes": [{"id": "T1", "a": "coder", "dep": ["$(rm)"]}]}, "unknown node"),
        ({"job": "j", "nodes": [{"id": "T1", "a": "coder", "r": ["root"]}]}, "subset of"),
        ({"job": "j", "slack": 5, "nodes": [{"id": "T1", "a": "coder"}]}, "slack"),
        ({"job": "j", "nodes": [{"id": "T%d" % i, "a": "coder"} for i in range(33)]}, "more than 32"),
        ({"job": "j", "nodes": [{"id": "T1", "a": "coder", "w": ["a\x00b"]}]}, "glob"),
        ({"job": "j", "nodes": [{"id": "T1", "a": "coder", "w": ["x"] * 17}]}, "at most 16"),
    ]
    for data, want in cases:
        with pytest.raises(F.PlanError) as ei:
            F.parse_plan(json.dumps(data), ORCH_ROW)
        assert want in str(ei.value)
        assert "<script>" not in str(ei.value) and "$(rm)" not in str(ei.value)
    for blob in ("[" * 5000 + "]" * 5000, "{" + '"a":' * 10, "x" * (F.PLAN_MAX_BYTES + 1),
                 json.dumps({"job": "j", "nodes": [{"id": "T1", "a": "coder", "x": [[[[[1]]]]]}]})):
        with pytest.raises(F.PlanError):
            F.parse_plan(blob, ORCH_ROW)
    assert F.plan_reject_text(F.PlanError("cycle T3→T5"), 32) == \
        "plan rejected: cycle T3→T5; static cap 32 applies"


def test_new_job_resets_node_runs_but_keeps_the_breaker():
    st = F.record_spawn(F.nodes_new("j1"), "T1", "t1", "coder", 0.0)
    st["breaker"]["tripped"] = True
    plan2 = F.parse_plan({"job": "j2", "nodes": [{"id": "T1", "a": "coder"}]})
    st2 = F.nodes_for_plan(st, plan2)
    assert st2["runs"] == {} and st2["job"] == "j2" and st2["breaker"]["tripped"]
    assert F.nodes_for_plan(st, F.parse_plan({"job": "j1", "nodes": [{"id": "T1", "a": "coder"}]}))[
        "runs"] == st["runs"]


def test_knob_names_are_fixed_guards():
    assert all(n.startswith("STACK_FANOUT_DYN") for n in F.KNOBS) and len(F.KNOBS) == 14
    assert F.DEFAULT_KNOBS["node_runs"] == F._NODE_RUNS == 6
    assert F.DEFAULT_KNOBS["reserve_tok"] == F.RESERVE_TOK == 8000000
    assert F.DEFAULT_KNOBS["mode"] == "shadow" and F.DEFAULT_KNOBS["enforce"] == ("node", "deps")
    k, warnings = F.parse_knobs({"STACK_FANOUT_DYN_ENFORCE": "node,learn", "STACK_FANOUT_DYN_BETA_RL": "0"})
    assert len(warnings) == 2 and k["enforce"] == ("node", "deps") and k["beta_rl"] == 0.5
    assert all("learn" not in w for w in warnings)


@pytest.mark.parametrize("py", ["/usr/bin/python3", sys.executable])
def test_cli_check_and_import_under_system_python(py, tmp_path):
    if not Path(py).exists():
        pytest.skip("no %s" % py)
    good = tmp_path / "plan.dag.json"
    good.write_text(json.dumps({"job": "j", "nodes": [{"id": "T1", "a": "coder"},
                                                      {"id": "T2", "a": "coder"}]}))
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"job": "j", "nodes": [{"id": "T1", "a": "coder", "dep": ["T1"]}]}))
    r = subprocess.run([py, str(MOD), "check", str(good)], capture_output=True, text=True)
    assert r.returncode == 0 and r.stdout.strip() == "plan accepted: 2 nodes, max width 2"
    r = subprocess.run([py, str(MOD), "check", str(bad), "--cap", "32"], capture_output=True, text=True)
    assert r.returncode == 1 and "depends on itself; static cap 32 applies" in r.stdout
    r = subprocess.run([py, str(MOD), "report", "--session", "../x"], capture_output=True, text=True)
    assert r.returncode == 2


# ---------------------------------------------------------------- review fixes (glob ranges, regex anchors)
def test_wide_class_globs_overlap_fast():
    """A class spanning all of Unicode is an interval, never expanded into a set of characters."""
    import time
    a, b = "[\x01-\U0010ffff]a*", "[\x01-\U0010ffff]b*"
    t0 = time.perf_counter()
    assert F.glob_overlap(a, b) is True
    assert time.perf_counter() - t0 < 0.02


def _first_chars_set(seg):
    """The old set semantics of _first_chars: the oracle (small classes only)."""
    if not seg or seg[0] in "*?":
        return None
    if seg[0] != "[":
        return {seg[0]}
    end = seg.find("]", 2)
    if end < 0:
        return None
    body, out, i = seg[1:end], set(), 0
    if body[:1] in "!^":
        return None
    while i < len(body):
        if i + 2 < len(body) and body[i + 1] == "-":
            out |= {chr(c) for c in range(ord(body[i]), ord(body[i + 2]) + 1)}
            i += 3
        else:
            out.add(body[i])
            i += 1
    return out


def test_first_char_ranges_meet_exactly_when_the_sets_intersect():
    rng = random.Random(20261004)
    alphabet = "abcdefghij-*?!^]"
    for _ in range(4000):
        segs = []
        for _ in range(2):
            body = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6)))
            segs.append(rng.choice(["[" + body + "]x", "[" + body, body + "*", "*" + body]))
        sx, sy = (_first_chars_set(s) for s in segs)
        rx, ry = (F._first_chars(s) for s in segs)
        assert (sx is None) == (rx is None) and (sy is None) == (ry is None), segs
        if sx is not None and sy is not None:
            assert bool(sx & sy) == F._ranges_meet(rx, ry), segs


@pytest.mark.parametrize("name", ["NODE_ID_RE", "TYPE_RE", "JOB_RE", "OUTCOME_RE", "SID_RE"])
def test_id_patterns_refuse_a_trailing_newline(name):
    rx = getattr(F, name)
    assert rx.match("abc") and not rx.match("abc\n")


def test_a_node_id_with_a_trailing_newline_is_rejected():
    with pytest.raises(F.PlanError):
        plan_of([{"id": "A\n", "a": "coder"}])


# ---------------------------------------------------------------- parity with stack_sched (copied code)
def _sched():
    hooks = str(ROOT / "dot-claude" / "hooks")
    if hooks not in sys.path:
        sys.path.insert(0, hooks)
    sp = importlib.util.spec_from_file_location("stack_sched_parity",
                                                ROOT / "dot-claude" / "hooks" / "stack_sched.py")
    mod = importlib.util.module_from_spec(sp)
    sys.modules["stack_sched_parity"] = mod
    sp.loader.exec_module(mod)
    return mod


def test_glob_overlap_parity_with_stack_sched():
    S = _sched()
    rng = random.Random(7)
    parts = ["*", "?", "[a-m]", "[n-z]", "[!x]", "a", "b", "src", "x.py", "**", "[ab]c", "a*"]
    for _ in range(3000):
        a, b = ("/".join(rng.choice(parts) for _ in range(rng.randint(1, 4))) for _ in range(2))
        assert F.glob_overlap(a, b) == S._glob_overlap(a, b), (a, b)


def test_cost_model_parity_with_stack_sched():
    """c_med and wall_hi equal stack_sched._est_for on an empty model (its built-ins), for every
    built-in type and for pool-only types."""
    S = _sched()
    for t in list(S._TURNS) + ["rust-engineer", "security-auditor", "scout", "designer"]:
        e = S._est_for({}, t, None, None)
        assert F.c_med(None, t) == pytest.approx(e.ctx_p50), t
        assert F.cost_model(None, t)["wall_hi"] == pytest.approx(e.wall_hi), t
