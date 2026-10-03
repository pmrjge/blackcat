"""dot-claude/hooks/stack_limits.py (S6 W1): learned limits, proposals and per-session snapshots.

Run: uv run --python 3.12 --with pytest pytest -q tests/test_stack_limits.py
Tests T1-T7, T12-T17, T19 and T20 of the S6 design (section 4), plus the seed's parity with the
agents' frontmatter and agent_guard.py, the stdlib-only import rule and the hook interpreter
(/usr/bin/python3). Every test uses its own XDG_STATE_HOME under tmp_path, never the stack's.
"""
import ast
import csv
import importlib.util
import json
import math
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-claude" / "hooks"
LIMITS_PY = HOOKS / "stack_limits.py"
SEED_JSON = HOOKS / "stack_limits_seed.json"
GUARD = HOOKS / "agent_guard.py"
AGENTS_DIR = ROOT / "dot-claude" / "agents"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("stack_limits", LIMITS_PY)
T0 = 1790000000.0
# Model IDs as the API reports them (synthetic transcripts, the matcher's vectors): only on module-level
# constant lines like these, which tests/lint_agents.py allows (MODEL_ID_LINES)
HAIKU, SONNET, OPUS = "claude-haiku-4-5-20251001", "claude-sonnet-5-5", "claude-opus-5-5"
HAIKU_SHORT, BEDROCK_SONNET, OPUS_1M = "claude-haiku-4-5", "us.anthropic.claude-sonnet-4-5-20250929-v1:0", "claude-opus-4-6[1m]"

V1_COLUMNS = ["schema_version", "session", "id", "type", "seg", "status", "api_calls", "ctx", "input", "output",
              "cache_creation", "cache_read", "first_cc", "first_cr", "peak", "prev_peak", "gap_s", "first_ts",
              "last_ts", "wall_s", "compacted", "turn_limited", "after_limit"]
V2_COLUMNS = V1_COLUMNS + ["n_read", "n_write", "n_edit", "n_notebook", "n_bash", "n_grep", "n_glob", "n_agent", "n_send", "n_skill", "n_toolsearch", "n_webfetch", "n_websearch", "n_lsp", "n_mcp", "n_other", "tool_calls", "files_written", "files_written_repo", "git_commits", "ro_write", "first_ctx", "first_write_call", "ctx_at_first_write", "resume", "cold", "parent", "depth", "node", "window", "status_code", "hit_soft", "hit_turn", "hit_hard_agent", "hit_hard_prompt", "hit_hard_session", "hit_mcp", "sess_src", "snap", "regime", "is_main", "window_ctx", "task", "stack_commit", "src"]


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))     # no install manifest
    L._ENV_WARNED.clear()
    return tmp_path / "st" / "claude-agent-stack"


def lim(st, *parts):
    return st.joinpath("limits", *parts)


def write_csv(path, rows, columns=V2_COLUMNS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)


_REGIME = []


def regime():
    """The current regime of a test state folder (no candidate model, default policy and scale)."""
    if not _REGIME:
        _REGIME.append(L.current_regime())
    return _REGIME[0]


def row(session, aid, typ="coder", seg=0, ctx=1000000, api=10, ts=T0, status="complete", **kw):
    r = {"schema_version": 2, "session": session, "id": aid, "type": typ, "seg": seg, "status": status, "api_calls": api, "ctx": ctx,
             "first_ts": ts - 100, "last_ts": ts, "compacted": 0, "turn_limited": 0, "after_limit": 0, "is_main": 0,
             "regime": regime(), "src": "measured", "status_code": 0}
    r.update(kw)
    return r


def coder_rows(sessions=3, agents=4, ctx=40000000, api=30, t0=T0, typ="coder"):
    out = []
    for s in range(sessions):
        for a in range(agents):
            out.append(row(f"sess-{s}", f"a{s}{a}", typ, ctx=ctx + 100000 * (s * agents + a),
                           api=api + (s + a) % 3, ts=t0 + 1000 * s + a))
    return out


def entry(x, unit="ctx", ci="boot", agents=None, sessions=None, tight=0, n_new=None, upto=T0, regime_ok=True,
          top=None):
    xs = sorted(x)
    if ci == "boot":
        lo, hi = L.boot_ci(xs, B=200, seed=1)
        ci = [lo, hi]
    e = {"x": xs, "ci": ci, "agents": len(xs) if agents is None else agents, "sessions": sessions or min(len(xs), 5),
             "tight": tight, "n_new": len(xs) if n_new is None else n_new, "upto": upto,
             "top": sorted(xs, reverse=True)[:50] if top is None else top, "regime_ok": regime_ok}
    out = L._valid_entry(e, unit)
    assert out is not None, e
    return out


def mini_seed(types=("coder", "scout", "verifier", "orchestrator")):
    s = L.load_seed()
    V = {v: dict(x) for v, x in s["vars"].items() if L.split_var(v)[1] in types or L.split_var(v)[1] is None}
    pools = {"builder": ["coder"], "lookup": ["scout"], "verifier": ["verifier"], "coordinator": ["orchestrator"]}
    return {"schema_version": 1, "measured_on": s["measured_on"], "pools": pools, "vars": V, "sha": s["sha"]}


def props(vars_=None, pools=None, eid=None):
    return {"schema_version": 1, "evidence_id": eid or os.urandom(32).hex(), "vars": vars_ or {}, "pools": pools or {}}


def invariants_ok(seed, live):
    for sv, hv, ratio in L._pairs(seed):
        a, b = L._eff(live["vars"][sv]), L._eff(live["vars"][hv])
        if a is not None and b is not None and a > ratio * b + 1e-6:
            return False, (sv, a, hv, b)
    return True, None


def ast_assign(path, name):
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not in {path}")


def frontmatter_max_turns():
    out = {}
    for f in sorted(AGENTS_DIR.glob("*.md")):
        m = re.match(r"---\n(.*?)\n---", f.read_text(encoding="utf-8"), re.DOTALL)
        head = m.group(1) if m else ""
        name = re.search(r"^name:\s*(\S+)", head, re.MULTILINE)
        mt = re.search(r"^maxTurns:\s*(\d+)", head, re.MULTILINE)
        out[name.group(1) if name else f.stem] = int(mt.group(1)) if mt else None
    return out


def derive_sched_soft_limits():
    """tests/derive_sched_model.py's soft_limits(), compiled from its source (the module itself
    needs pandas/numpy)."""
    src = (ROOT / "tests" / "derive_sched_model.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "soft_limits")
    ns = {"ast": ast}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "derive_sched_model.py", "exec"), ns)  # noqa: S102
    return ns["soft_limits"](str(GUARD))


# ---------------------------------------------------------------- seed, imports, shared statistics
def test_seed_parity_with_frontmatter_and_guard():
    s = L.load_seed()
    fm = frontmatter_max_turns()
    agents = ast_assign(GUARD, "AGENTS")
    soft = derive_sched_soft_limits()
    for t in agents:
        if t == "blackcat":
            assert not any(v.endswith("." + t) for v in s["vars"]) and soft[t] is None
            continue
        mt = fm[t]
        assert mt, t
        assert s["vars"]["turns." + t] == {"seed": mt, "floor": max(5, math.ceil(mt / 4)), "ceiling": mt,
                                           "unit": "turns", "kind": "hard"}
        assert s["vars"]["soft.agent." + t] == {"seed": soft[t], "floor": 100000, "ceiling": 100000000,
                                                "unit": "ctx", "kind": "soft"}
        assert s["vars"]["hard.agent." + t] == {"seed": None, "floor": 2000000, "ceiling": 200000000,
                                                "unit": "ctx", "kind": "hard"}
    for t, mt in fm.items():
        assert (mt is None) == (t == "blackcat") and (mt is None or "turns." + t in s["vars"]), t
    assert set(soft) == set(agents)
    assert s["vars"]["soft.prompt"]["seed"] == ast_assign(GUARD, "SOFT_PROMPT_CTX")
    by_type = ast_assign(GUARD, "SOFT_PROMPT_CTX_BY_TYPE")        # user-set: the seed is the floor
    assert by_type and {v: x for v, x in s["vars"].items() if v.startswith("soft.prompt.")} == {
        "soft.prompt." + t: {"seed": val, "floor": val, "ceiling": max(100000000, val), "unit": "ctx", "kind": "soft"}
        for t, val in by_type.items()}
    scope = {k: (v["seed"], v["floor"], v["ceiling"], v["kind"]) for k, v in s["vars"].items() if "." not in k[5:]}
    assert scope == {"soft.prompt": (33000000, 5000000, 100000000, "soft"),
                     "hard.prompt": (100000000, 50000000, 250000000, "hard"),
                     "soft.session": (None, 100000000, 1500000000, "soft"),
                     "hard.session": (1920000000, 300000000, 2500000000, "hard")}
    tier = ast_assign(ROOT / "tests" / "derive_thresholds.py", "TIER")
    assert s["pools"] == {k: sorted(v.split()) for k, v in tier.items()}
    assert sorted(t for m in s["pools"].values() for t in m) == sorted(a for a in agents if a != "blackcat")
    live = L.live_from_seed(s)                       # the seed itself satisfies every invariant
    assert invariants_ok(s, live) == (True, None)
    assert json.loads(SEED_JSON.read_text())["schema_version"] == 1


def test_stdlib_only_imports():
    tree = ast.parse(LIMITS_PY.read_text(encoding="utf-8"))
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            mods.add(node.module.split(".")[0])
    std = getattr(sys, "stdlib_module_names", None)
    if std is None:
        pytest.skip("needs Python >= 3.10 for sys.stdlib_module_names")
    assert mods and mods <= set(std), sorted(mods - set(std))


def test_imports_on_hook_interpreter():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([PY, "-c", 'import sys; sys.path.insert(0, "dot-claude/hooks"); import stack_limits'],
                       cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr


def test_shared_statistics():
    assert L.q([1, 2, 3, 4], 0.9) == pytest.approx(3.7)              # numpy's linear quantile
    assert L.q([5], 0.5) == 5 and math.isnan(L.q([], 0.5))
    assert L.ceil2(123456) == 130000 and L.ceil2(19000000) == 19000000 and L.ceil2(0) == 0
    x = [10, 12, 14, 16, 18, 20, 22, 24, 26, 100]
    d = L.derive(x)
    assert d["n"] == 10 and d["p90"] == pytest.approx(L.q(x, 0.9))
    assert d["soft"] == L.ceil2(max(d["p90"] * d["m"], 2 * d["median"]))
    assert d["m"] == 1.25 and d["ft"] == 0.1 and d["tripped"] == [None]   # no m reaches 5 %: the lowest FT
    y = list(range(1, 41))
    d = L.derive(y, names=[f"n{v}" for v in y])
    assert d["m"] == 1.25 and d["ft"] == 0 and d["soft"] == L.ceil2(max(L.q(y, 0.9) * 1.25, 2 * L.q(y, 0.5)))
    assert L.derive(y, hard=True)["soft"] == math.ceil(max(L.q(y, 0.9) * 1.5, 2 * L.q(y, 0.5)))
    assert L.boot_ci(x, seed="a") == L.boot_ci(x, seed="a") and L.boot_ci([1, 2]) == (None, None)
    lo, hi = L.boot_ci(x, seed=3)
    assert lo <= hi
    assert L.env_name("code-reviewer") == "CODE_REVIEWER"
    assert L.env_name("code-reviewer", "turns") == "STACK_MAXTURNS_CODE_REVIEWER"
    assert L.env_var("soft.agent.claude-code-guide") == "STACK_SOFTCTX_CLAUDE_CODE_GUIDE"
    assert L.env_var("hard.agent.coder") == "STACK_HARDCTX_CODER"
    assert L.env_var("hard.prompt") == "STACK_PROMPT_CTX_BUDGET" and L.env_var("hard.session") == \
        "STACK_SESSION_CTX_BUDGET"
    assert L.lookup({"turns.coder": 99}, "turns", "coder-copy") == 99
    assert L.env_var("soft.prompt.orchestrator") == "STACK_SOFT_PROMPT_CTX_ORCHESTRATOR"
    assert L.split_var("soft.prompt.orchestrator") == ("soft.prompt", "orchestrator")
    vals = {"soft.prompt": 33000000, "soft.prompt.orchestrator": 80000000}
    assert L.prompt_soft_limit(vals) == 33000000 and L.prompt_soft_limit(vals, ["coder", "scout"]) == 33000000
    assert L.prompt_soft_limit(vals, ["coder", "orchestrator"]) == 80000000
    assert L.prompt_soft_limit(dict(vals, **{"soft.prompt": None}), ["orchestrator"]) is None   # prompt limit off


# ---------------------------------------------------------------- T1 fixed guards
def test_T1_fixed_guards_are_never_variables(st):
    s = L.load_seed()
    for v in s["vars"]:
        assert not L.is_fixed_guard(v) and not L.is_fixed_guard(L.env_var(v)), v
    for name in sorted(L.FIXED_GUARDS) + ["SUPREME_ONCE_PER_SESSION", "STACK_IMAGE_MAX_PX", "READ_GATE_DATA_BYTES",
                                          "STACK_FANOUT_SESSION",
                                          "STACK_FANOUT_DYN", "STACK_FANOUT_DYN_ALPHA",
                                          "STACK_FANOUT_DYN_BETA_FAIL", "STACK_FANOUT_DYN_BETA_RL",
                                          "STACK_FANOUT_DYN_BREAKER", "STACK_FANOUT_DYN_DELAY_RATIO",
                                          "STACK_FANOUT_DYN_ENFORCE", "STACK_FANOUT_DYN_HOLD_S",
                                          "STACK_FANOUT_DYN_NODE_RUNS", "STACK_FANOUT_DYN_RESERVE_TOK",
                                          "STACK_FANOUT_DYN_SLACK", "STACK_FANOUT_DYN_TYPES",
                                          "STACK_FANOUT_DYN_W0", "STACK_FANOUT_DYN_WMIN",
                                          "stack-max-depth", "blackcat.max.dispatch"]:
        assert L.is_fixed_guard(name), name
        assert not L.VAR_RE.match(name) and name not in s["vars"]
    bad = json.loads(SEED_JSON.read_text())
    bad["vars"]["STACK_MAX_DEPTH"] = {"seed": 3, "floor": 1, "ceiling": 5, "unit": "ctx", "kind": "hard"}
    with pytest.raises(L.SeedError):
        L._validate_seed(bad)

    # a fixed-guard name in live.json invalidates the file: set aside, reseeded, logged
    L.seed()
    live = json.loads(lim(st, "live.json").read_text())
    live["vars"]["STACK_MAX_DEPTH"] = {"value": 9}
    lim(st, "live.json").write_text(json.dumps(live))
    _path, notice = L.apply_and_snapshot({"session_id": "s-t1a", "source": "startup"}, spawn=False)
    assert notice and "reseeded" in notice
    assert len(list(lim(st).glob("live.invalid-*.json"))) == 1
    assert "STACK_MAX_DEPTH" not in json.loads(lim(st, "live.json").read_text())["vars"]
    assert "fixed guard STACK_MAX_DEPTH" in lim(st, "limits.log").read_text()

    # ... and in proposals.json: the whole file is ignored
    ok = {"soft.agent.coder": {"x": [5e7] * 6, "ci": [5e7, 5e7], "agents": 6, "sessions": 3, "tight": 0, "n_new": 6,
                                   "upto": T0, "top": [5e7], "regime_ok": True}}
    doc = dict(props(ok), vars=dict(ok, BLACKCAT_MAX_DISPATCH=ok["soft.agent.coder"]))
    assert L.validate_proposals(doc, s) == (None, "fixed guard BLACKCAT_MAX_DISPATCH")
    doc2 = dict(props(ok), pools={"SUPREME_SPAWNERS": ok["soft.agent.coder"]})
    assert L.validate_proposals(doc2, s)[0] is None
    assert L.validate_proposals(props(ok), s)[0]["vars"]["soft.agent.coder"]["n"] == 6
    lim(st, "proposals.json").write_text(json.dumps(doc))
    before = lim(st, "live.json").read_bytes()
    L.apply_and_snapshot({"session_id": "s-t1b", "source": "startup"}, spawn=False)
    assert lim(st, "live.json").read_bytes() == before
    assert "proposals.json ignored: fixed guard BLACKCAT_MAX_DISPATCH" in lim(st, "limits.log").read_text()


def test_T1b_mcp_caps_stay_fixed_guards(st):
    """A6: STACK_MAX_MCP_CALLS and the per-server web caps (web_caps.py KNOBS) are never learned: no
    seed variable, rejected in live.json and proposals.json, never a snapshot value; the effective
    MCP cap only follows the turn budget (min(knob, turns.<type>), test_limits_guard T11)."""
    s = L.load_seed()
    W = _load_web_caps()
    names = ["STACK_MAX_MCP_CALLS"] + sorted(k for k in W.KNOBS if "_MAX_" in k)
    for name in names:
        assert L.is_fixed_guard(name), name
    for name in ["STACK_MAX_MCP_CALLS"] + sorted(W.KNOBS):          # every web cap: never a variable
        assert not L.VAR_RE.match(name) and name not in s["vars"] and name.lower() not in s["vars"], name
        assert name not in {L.env_var(v) for v in s["vars"]}, name
    ok = {"soft.agent.coder": {"x": [5e7] * 6, "ci": [5e7, 5e7], "agents": 6, "sessions": 3, "tight": 0, "n_new": 6,
                               "upto": T0, "top": [5e7], "regime_ok": True}}
    for name in ("STACK_MAX_MCP_CALLS", "stack.max.mcp.calls", "EXA_MAX_RESULTS", "SPIDER_MAX_PAGES"):
        doc = dict(props(ok), vars=dict(ok, **{name: {"x": [9] * 6, "ci": [9, 9], "agents": 6}}))
        assert L.validate_proposals(doc, s) == (None, f"fixed guard {name}"), name
        with pytest.raises(L.LiveInvalid, match="fixed guard"):
            L.validate_live(dict(L.live_from_seed(s), vars={name: {"value": 999}}), s)
    # a proposed MCP cap never reaches live.json or a snapshot
    L.seed()
    doc = dict(props(ok), vars=dict(ok, STACK_MAX_MCP_CALLS={"x": [999] * 6, "ci": [999, 999], "agents": 6}))
    lim(st, "proposals.json").write_text(json.dumps(doc))
    path, _ = L.apply_and_snapshot({"session_id": "s-t1mcp", "source": "startup"}, spawn=False)
    snap = json.loads(open(path).read())
    assert set(snap["values"]) <= set(s["vars"]) and not [k for k in snap["values"] if L.is_fixed_guard(k)]
    assert "STACK_MAX_MCP_CALLS" not in json.dumps(snap)
    assert "STACK_MAX_MCP_CALLS" not in json.dumps(json.loads(lim(st, "live.json").read_text()))
    assert "proposals.json ignored: fixed guard STACK_MAX_MCP_CALLS" in lim(st, "limits.log").read_text()


def _load_web_caps():
    import importlib.util
    spec = importlib.util.spec_from_file_location("web_caps_t1b", HOOKS / "web_caps.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------- T2, T3 random proposals
def _rand_entry(rng, spec, upto):
    turns = spec["unit"] == "turns"
    cap = 1e4 if turns else 1e10
    n = rng.choice([1, 2, 3, 4, 5, 8, 20, 60])
    base = (spec["seed"] or spec["floor"] * rng.choice([1, 5, 50])) * rng.choice([0.01, 0.3, 1, 1, 3, 30])
    sig = rng.choice([0.05, 0.4, 1.5])
    x = [min(cap, max(0.0, rng.lognormvariate(math.log(max(base, 1)), sig))) for _ in range(n)]
    if turns:
        x = [float(round(v)) for v in x]
    p = L._qs(sorted(x), 0.9)
    ci = [None, None] if n < 3 else sorted([p * rng.uniform(0.5, 1.0), min(cap, p * rng.uniform(1.0, 1.8))])
    e = {"x": x, "ci": ci, "agents": rng.randint(1, n), "sessions": rng.randint(1, n), "tight": rng.choice([0, 0, 0, 1, 3]),
             "n_new": rng.choice([0, 1, n, n]), "upto": upto, "top": sorted(x, reverse=True)[:50],
             "regime_ok": rng.random() < 0.7}
    return L._valid_entry(e, spec["unit"])


def _rand_live(rng, seed):
    live = L.live_from_seed(seed)
    for v, s in live["vars"].items():
        spec = seed["vars"][v]
        r = rng.random()
        if r < 0.6:
            s["value"] = rng.randint(spec["floor"], spec["ceiling"])
        elif r < 0.75 and spec["seed"] is None:
            s["value"] = None
        s["d"] = rng.choice(L.D_LEVELS)
        s["hold"] = rng.choice([0] * 12 + [1, -1])
        s["streak"] = rng.randint(0, 2)
        s["recent"] = [{"dec": rng.choice(["step", "dead", "hold"]), "sign": rng.choice([-1, 0, 1]), "rel": 0.1}
                       for _ in range(rng.randint(0, 5))]
    return live


def test_T2_T3_random_proposals_stay_in_bounds_and_steps_are_bounded():
    rng = random.Random(20261003)
    seed = mini_seed()
    names = sorted(seed["vars"])
    fams = list(L.TYPE_FAMILIES)                          # the families with pools
    steps = 0
    for it in range(10000):
        live = _rand_live(rng, seed)
        vs = {}
        for v in rng.sample(names, rng.randint(1, 12)):
            e = _rand_entry(rng, seed["vars"][v], T0 + it)
            if e:
                vs[v] = e
        pools = {}
        for fam in rng.sample(fams, rng.randint(0, len(fams))):
            pool = rng.choice(sorted(seed["pools"]))
            spec = seed["vars"]["{}.{}".format(fam, seed["pools"][pool][0])]
            e = _rand_entry(rng, spec, T0 + it)
            if e:
                pools[f"{fam}:{pool}"] = e
        new, recs, _ = L.apply_proposals(seed, live, props(vs, pools), now=T0 + it)
        for v, s in new["vars"].items():
            spec = seed["vars"][v]
            assert s["value"] is None or spec["floor"] <= s["value"] <= spec["ceiling"], (it, v, s["value"])
            assert s["d"] in L.D_LEVELS
        assert invariants_ok(seed, new) == (True, None), it
        for r in recs:
            if r["decision"] in ("step", "clamp") and r.get("stepped") is not None and r["old"] is not None:
                steps += 1
                c = r["old"]
                assert abs(r["stepped"] - c) <= L.STEP_MAX * r["d"] * c + 1e-9, (it, r)    # T3
    assert steps > 500                    # the sample exercised the step rule


def test_user_set_prompt_limit_is_never_lowered_by_proposals():
    rng = random.Random(80000000)
    seed = mini_seed()
    v, floor = "soft.prompt.orchestrator", L.load_seed()["vars"]["soft.prompt.orchestrator"]["seed"]
    assert seed["vars"][v]["floor"] == floor == 80000000
    raised = 0
    for it in range(1000):
        live = _rand_live(rng, seed)
        live["vars"]["hard.prompt"]["status"] = rng.choice(["supported", "provisional", "unset"])
        vs = {}
        for name in (v, "hard.prompt", "soft.prompt"):
            e = _rand_entry(rng, seed["vars"][name], T0 + it)
            if e:
                vs[name] = dict(e, x=[x * rng.choice([0.001, 0.1, 1, 3]) for x in e["x"]])  # mostly far below
        new, recs, _ = L.apply_proposals(seed, live, props(vs), now=T0 + it)
        o, h = new["vars"][v], new["vars"]["hard.prompt"]
        assert o["value"] >= floor and (o["frozen"] is None or o["frozen"] >= floor), it
        if h["status"] == "supported" and L._eff(h) is not None:
            assert L._eff(o) <= 0.67 * L._eff(h) or h["frozen"] is not None, (it, o["value"], h)
            raised += any(r["var"] == "hard.prompt" and r.get("why") == "invariant" for r in recs)
    assert raised > 10
    # the seed itself: hard.prompt 100M < 80M / 0.67 is allowed until hard.prompt is supported
    live = L.live_from_seed(L.load_seed())
    assert L.enforce_invariants(L.load_seed(), live) == [] and live["vars"]["hard.prompt"]["value"] == 100000000
    live["vars"]["hard.prompt"]["status"] = "supported"
    recs = L.enforce_invariants(L.load_seed(), live)
    assert live["vars"]["hard.prompt"]["value"] == 119402986 and live["vars"][v]["value"] == 80000000, recs
    live["vars"]["hard.prompt"]["frozen"] = 100000000
    recs = L.enforce_invariants(L.load_seed(), live)
    assert [r["decision"] for r in recs] == ["hold"] and live["vars"][v]["value"] == 80000000


def test_T3_step_function():
    assert L.step(100, 1000, 1) == 125 and L.step(100, 10, 1) == 75
    assert L.step(100, 10, 0.5) == 87.5 and L.step(100, 101, 0.125) == 101
    assert L._round_toward(23750000.0, 19000000, "ctx") == 23700000
    assert L._round_toward(127.5, 170, "turns") == 128 and L._round_toward(212.5, 170, "turns") == 212


# ---------------------------------------------------------------- T4 dead band, T5 damping, T6 support
SPEC_SOFT = {"seed": 19000000, "floor": 100000, "ceiling": 100000000, "unit": "ctx", "kind": "soft"}


def _state(value, **kw):
    s = L._var_state(value)
    s.update(kw)
    return s


def test_T4_dead_band():
    x = [float(v) for v in range(30000000, 40000000, 1000000)]          # 10 values, narrow
    e = entry(x)
    T = L.target("soft", "ctx", e["x"], L._qs(e["x"], 0.9))
    for c in (T, int(T * 1.05), int(T * 0.95)):
        s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(c), e)
        assert rec["decision"] == "dead" and s["value"] == c and rec["new"] == c, (c, T)
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(int(T / 1.6)), e)   # outside the band, no
    assert rec["decision"] == "hold" and s["value"] == int(T / 1.6)            # false trips at c: hold
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(25000000), e)      # FT(c) = 100 %: loosen
    assert rec["decision"] == "step" and s["value"] == 31200000 and rec["ft"] == 1.0


def _loosen(up):
    return entry([5e7 + 1e5 * i for i in range(10)], upto=up)


def _tighten(up):
    return entry([1e6 + 1e4 * i for i in range(10)], upto=up)


def test_T5_damping():
    c = 19000000
    # a reversal within the last 3 changes halves d before the step
    s0 = _state(c, recent=[{"dec": "step", "sign": 1, "rel": 0.25}], upto=0)
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s0, _tighten(T0))
    assert rec["decision"] == "step" and s["d"] == 0.5 and rec["d"] == 0.5
    assert c * (1 - 0.125) <= s["value"] < c
    # an opposite change older than the last 3 changes is no reversal
    old = [{"dec": "step", "sign": 1, "rel": 0.2}] + [{"dec": "step", "sign": -1, "rel": -0.2}] * 3
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(c, recent=old), _tighten(T0))
    assert s["d"] == 1.0 and s["value"] == 14300000          # c x 0.75, 3 significant figures toward c
    # three dead-band decisions in a row double d (cap 1)
    x = [float(v) for v in range(30000000, 40000000, 1000000)]
    T = L.target("soft", "ctx", sorted(x), L._qs(sorted(x), 0.9))
    s = _state(T, d=0.25)
    ds = []
    for k in range(9):
        s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s, entry(x, upto=T0 + k))
        assert rec["decision"] == "dead"
        ds.append(s["d"])
    assert ds == [0.25, 0.25, 0.5, 0.5, 0.5, 1.0, 1.0, 1.0, 1.0]
    # three same-sign steps double d
    s = _state(5000000, d=0.5)
    for k in range(3):
        s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s, _loosen(T0 + k))
        assert rec["decision"] == "step" and rec["d"] == 0.5
    assert s["d"] == 1.0
    # alternating directions keep halving down to 1/8
    s = _state(19000000)
    for k in range(8):
        s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s, (_loosen if k % 2 else _tighten)(T0 + k))
    assert s["d"] == 0.125


def test_T6b_support_rule_boundaries():
    """A5 (s6-design-v2 section 4): (n >= 5 and agents >= 3) or (n >= 3 and agents >= 2 and
    w <= 0.35), w = (hi - lo) / p90; prompt scope n >= 30 windows from >= 3 sessions; session
    scope >= 5 sessions. Every bound inclusive, each side of the "or" sufficient on its own."""
    sup = L.support
    wide, at, over = (0, 100), (65, 100), (64.9, 100)              # w = 1.0, 0.35, 0.351 at p90 = 100
    # first clause alone (CI irrelevant, even missing or infinitely wide)
    for ci in (None, (None, None), wide):
        assert sup(5, 3, ci, 100) and sup(500, 3, ci, 100)
        assert not sup(4, 3, ci, 100) and not sup(5, 2, ci, 100)
    # second clause alone: the width bound is inclusive
    assert sup(3, 2, at, 100) and sup(4, 2, at, 100) and sup(5, 2, at, 100)
    assert not sup(3, 2, over, 100) and not sup(2, 2, at, 100) and not sup(3, 1, at, 100)
    assert not sup(3, 2, (100, 100), 0) and not sup(3, 2, (None, 100), 100)   # p90 0 or open CI: w = inf
    assert sup(3, 2, (100, 100), 100)                                        # w = 0
    # scopes: agents and CI play no part
    assert sup(30, 0, None, 0, "prompt", sessions=3) and not sup(29, 99, at, 100, "prompt", sessions=99)
    assert not sup(999, 99, at, 100, "prompt", sessions=2)
    assert sup(1, 0, None, 0, "session", sessions=5) and not sup(99, 99, at, 100, "session", sessions=4)
    # classify uses the regime-filtered own sample first, then the pool (type scope), then provisional
    e = entry([5e7 + 1e5 * i for i in range(5)], agents=3, ci=list(wide))
    assert L.classify("soft.agent", e, None)[0] == "supported"
    e = entry([5e7 + 1e5 * i for i in range(5)], agents=2, ci=[4.9e7, 4.9e7 + 0.34 * L._qs(e["x"], 0.9)])
    assert L.classify("soft.agent", e, None)[0] == "supported"
    e = entry([5e7 + 1e5 * i for i in range(5)], agents=2, ci=[4.9e7, 4.9e7 + 0.36 * L._qs(e["x"], 0.9)])
    assert L.classify("soft.agent", e, None)[0] == "provisional"


def test_T6_support_provisional_and_hard_caps():
    sup = L.support
    assert sup(5, 3, None, 1) and not sup(4, 2, (10, 90), 100) and not sup(4, 3, None, 100)
    assert sup(3, 2, (90, 100), 100) and not sup(3, 2, (50, 100), 100) and not sup(3, 1, (99, 100), 100)
    assert sup(30, 0, None, 0, "prompt", sessions=3) and not sup(29, 0, None, 0, "prompt", sessions=3)
    assert not sup(30, 0, None, 0, "prompt", sessions=2)
    assert sup(5, 0, None, 0, "session", sessions=5) and not sup(9, 0, None, 0, "session", sessions=4)

    # provisional (n >= 3, not supported): T from the CI's upper end; the orchestrator gets it
    x = [2e6, 3e6, 4e6, 5e6]
    e = entry(x, agents=1, ci=[3e6, 9e6])
    status, _use, p90e = L.classify("soft.agent", e, None)
    assert status == "provisional" and p90e == 9e6
    spec = {"seed": None, "floor": 100000, "ceiling": 100000000, "unit": "ctx", "kind": "soft"}
    s, rec = L.decide("soft.agent.orchestrator", spec, _state(None), e)
    assert s["value"] == L.target("soft", "ctx", e["x"], 9e6) and s["status"] == "provisional"
    assert s["value"] > L.target("soft", "ctx", e["x"], L._qs(e["x"], 0.9))
    # current regime missing: supported data still only provisional
    e2 = entry([5e7 + 1e5 * i for i in range(10)], regime_ok=False)
    assert L.classify("soft.agent", e2, None)[0] == "provisional"
    # n < 3 holds
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(19000000), entry([9e7, 9.5e7], ci=[None, None]))
    assert rec["decision"] == "hold" and s["value"] == 19000000
    # pooled: own sample too small, the pool's supports (T from the pool's upper end)
    pool = entry([5e7 + 1e5 * i for i in range(10)])
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, _state(19000000), entry([4e7], ci=[None, None]), pool)
    assert s["status"] == "pooled" and rec["decision"] == "step" and s["value"] == int(19000000 * 1.25 // 1e5 * 1e5)

    # hard caps move only when supported
    hp = {"seed": 100000000, "floor": 50000000, "ceiling": 250000000, "unit": "ctx", "kind": "hard"}
    big = [3e8 + 1e6 * i for i in range(30)]
    s, rec = L.decide("hard.prompt", hp, _state(100000000), entry(big, sessions=2))
    assert rec["decision"] == "hold" and s["value"] == 100000000 and s["status"] == "provisional"
    s, rec = L.decide("hard.prompt", hp, _state(100000000), entry(big, sessions=3))
    assert rec["decision"] == "step" and s["value"] == 125000000 and s["status"] == "supported"
    ha = {"seed": None, "floor": 2000000, "ceiling": 200000000, "unit": "ctx", "kind": "hard"}
    s, rec = L.decide("hard.agent.coder", ha, _state(None), entry([4e7] * 4, agents=1, ci=[4e7, 4e7]))
    assert s["value"] is None and rec["decision"] == "hold"
    s, rec = L.decide("hard.agent.coder", ha, _state(None), entry([4e7 + 1e5 * i for i in range(6)]),
                      soft_ref=19000000)
    assert s["value"] == L.ceil2(max(1.5 * L.q([4e7 + 1e5 * i for i in range(6)], 0.9), 1.1 * 4.05e7, 3.8e7))
    tspec = {"seed": 170, "floor": 43, "ceiling": 170, "unit": "turns", "kind": "hard"}
    s, rec = L.decide("turns.coder", tspec, _state(170), entry([20.0, 22, 25, 30], "turns", agents=1))
    assert rec["decision"] == "hold" and s["value"] == 170
    s, rec = L.decide("turns.coder", tspec, _state(170), entry([20.0, 22, 25, 30, 31, 32], "turns"))
    assert rec["decision"] == "step" and s["value"] == 128          # ceil(170 x 0.75)
    # soft.session stays unset until supported
    ss = {"seed": None, "floor": 100000000, "ceiling": 1500000000, "unit": "ctx", "kind": "soft"}
    s, _ = L.decide("soft.session", ss, _state(None), entry([3e8, 4e8, 5e8, 6e8], sessions=4))
    assert s["value"] is None
    s, _ = L.decide("soft.session", ss, _state(None), entry([3e8, 4e8, 5e8, 6e8, 7e8], sessions=5))
    assert s["value"] is not None and 1e8 <= s["value"] <= 1.5e9


# ---------------------------------------------------------------- T7, T12, T13 through the state files
def _setup_rows(st, rows, name="runs2.csv"):
    write_csv(st / "usage" / name, rows)


def test_T7_same_evidence_twice_and_no_new_rows(st):
    _setup_rows(st, coder_rows())
    L.seed()
    assert L.propose() is not None
    _p1, n1 = L.apply_and_snapshot({"session_id": "s-t7a", "source": "startup"}, spawn=False)
    assert n1 and n1.startswith("limits v2: coder.hard off→") and "coder.soft 19M→23.7M" in n1
    live1 = lim(st, "live.json").read_bytes()
    hist1 = lim(st, "history.jsonl").read_bytes()
    _p2, n2 = L.apply_and_snapshot({"session_id": "s-t7b", "source": "startup"}, spawn=False)
    assert n2 is None and lim(st, "live.json").read_bytes() == live1 and lim(st, "history.jsonl").read_bytes() == hist1
    assert L.read_snapshot("s-t7b")[0]["values"] == L.read_snapshot("s-t7a")[0]["values"]
    # a new evidence id whose entries carry no new rows moves nothing
    doc = json.loads(lim(st, "proposals.json").read_text())
    doc["evidence_id"] = "f" * 64
    for e in list(doc["vars"].values()) + list(doc["pools"].values()):
        e["n_new"] = 0
    lim(st, "proposals.json").write_text(json.dumps(doc))
    before = json.loads(live1)
    L.apply_and_snapshot({"session_id": "s-t7c", "source": "startup"}, spawn=False)
    after = json.loads(lim(st, "live.json").read_text())
    assert after["version"] == before["version"] + 1 and after["evidence_id"] == "f" * 64
    assert {v: s["value"] for v, s in after["vars"].items()} == {v: s["value"] for v, s in before["vars"].items()}
    # rows not newer than the variable's `upto` move nothing either
    doc["evidence_id"] = "e" * 64
    for e in doc["vars"].values():
        e["n_new"] = 5
    lim(st, "proposals.json").write_text(json.dumps(doc))
    L.apply_and_snapshot({"session_id": "s-t7d", "source": "startup"}, spawn=False)
    again = json.loads(lim(st, "live.json").read_text())
    assert {v: s["value"] for v, s in again["vars"].items()} == {v: s["value"] for v, s in before["vars"].items()}


def test_T7_new_rows_only_count_in_the_sample_the_rules_use():
    own = entry([1e6 + 1e4 * i for i in range(10)], n_new=0, upto=T0)       # supported, nothing new
    pool = entry([1e6 + 1e4 * i for i in range(12)], upto=T0 + 50)          # other types' new rows
    s0 = _state(19000000, upto=T0)
    assert L.decide("soft.agent.coder", SPEC_SOFT, s0, own, pool) == (s0, None)
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s0, dict(own, n_new=2, upto=T0 + 60), pool)
    assert rec["decision"] == "step" and s["upto"] == T0 + 60
    weak = entry([4e7], ci=[None, None], upto=T0)                           # pooled: the pool's rows count
    s, rec = L.decide("soft.agent.coder", SPEC_SOFT, s0, weak, entry([5e7 + 1e5 * i for i in range(10)],
                                                                     upto=T0 + 50))
    assert rec["status"] == "pooled" and s["upto"] == T0 + 50


def test_T12_T13_propose_changes_nothing_new_sid_gets_next_version(st):
    pa, na = L.apply_and_snapshot({"session_id": "s-a", "source": "startup"}, spawn=False)
    assert na is None and os.stat(pa).st_mode & 0o777 == 0o444
    snap_a = Path(pa).read_bytes()
    live0 = lim(st, "live.json").read_bytes()
    _setup_rows(st, coder_rows())
    doc = L.propose()
    assert doc and "soft.agent.coder" in doc["vars"] and lim(st, "proposals.json").exists()
    assert lim(st, "live.json").read_bytes() == live0 and Path(pa).read_bytes() == snap_a      # T12
    # the same session again (resume, compact, clear): the same snapshot, nothing applied
    for src in ("resume", "compact", "clear"):
        assert L.apply_and_snapshot({"session_id": "s-a", "source": src}, spawn=False) == (pa, None)
    assert lim(st, "live.json").read_bytes() == live0
    _pb, nb = L.apply_and_snapshot({"session_id": "s-b", "source": "startup"}, spawn=False)
    a, b = L.read_snapshot("s-a")[0], L.read_snapshot("s-b")[0]
    live = json.loads(lim(st, "live.json").read_text())
    assert b["live_version"] == a["live_version"] + 1 == live["version"]                        # T13
    assert Path(pa).read_bytes() == snap_a and L.read_snapshot("s-a")[1] == "ok"
    assert b["values"] == {v: s["value"] for v, s in live["vars"].items()}
    assert a["values"]["soft.agent.coder"] == 19000000 and b["values"]["soft.agent.coder"] == 23700000
    assert b["values"]["turns.coder"] == 128 and a["values"]["turns.coder"] == 170
    assert b["values"]["hard.agent.coder"] is not None and a["values"]["hard.agent.coder"] is None
    assert b["origin"]["soft.agent.coder"] == "live" and b["regime"] == L.current_regime()
    assert nb.startswith("limits v2: ") and len(nb) <= L.NOTICE_MAX and "stack_limits.py show" in nb
    model = L.snapshots_dir() + "/s-b.sched_model.json"
    assert b["sched_model"]["file"] == "s-b.sched_model.json" and os.stat(model).st_mode & 0o777 == 0o444
    assert L.session_limits("s-b")["sched_model"] == model
    hist = [json.loads(x) for x in lim(st, "history.jsonl").read_text().splitlines()]
    steps = [h for h in hist if h["decision"] == "step"]
    assert {h["var"] for h in steps} >= {"soft.agent.coder", "turns.coder", "hard.agent.coder"}
    assert all(h["session"] == "s-b" and h["live_version"] == 2 for h in steps)


# ---------------------------------------------------------------- T14 commands
def run_cli(*argv):
    return L.main(list(argv))


def test_T14_hold_release_freeze_unfreeze_rollback(st, capsys):
    L.seed()
    v0 = json.loads(lim(st, "live.json").read_text())["version"]
    assert run_cli("hold", "soft.agent.coder", "--sessions", "2") == 0
    live = json.loads(lim(st, "live.json").read_text())
    assert live["vars"]["soft.agent.coder"]["hold"] == 2 and live["version"] == v0 + 1
    _setup_rows(st, coder_rows())
    L.propose()
    L.apply_and_snapshot({"session_id": "s-h1", "source": "startup"}, spawn=False)
    live = json.loads(lim(st, "live.json").read_text())
    assert live["vars"]["soft.agent.coder"]["value"] == 19000000 and live["vars"]["soft.agent.coder"]["hold"] == 1
    assert live["vars"]["turns.coder"]["value"] == 128                       # the others still learn
    assert run_cli("release", "soft.agent.coder") == 0
    assert json.loads(lim(st, "live.json").read_text())["vars"]["soft.agent.coder"]["hold"] == 0

    assert run_cli("freeze", "soft.agent.coder", "--value", "20000000") == 0
    L.apply_and_snapshot({"session_id": "s-f1", "source": "startup"}, spawn=False)
    snap = L.read_snapshot("s-f1")[0]
    assert snap["values"]["soft.agent.coder"] == 20000000 and snap["origin"]["soft.agent.coder"] == "frozen"
    assert run_cli("freeze", "soft.agent.coder", "--value", "1") == 2                      # below the floor
    assert run_cli("freeze", "hard.agent.scout") == 2                                       # unset, no value
    assert run_cli("unfreeze", "soft.agent.coder") == 0
    L.apply_and_snapshot({"session_id": "s-f2", "source": "startup"}, spawn=False)
    assert L.read_snapshot("s-f2")[0]["origin"]["soft.agent.coder"] == "live"

    assert run_cli("rollback", "turns.coder", "--to", "prev") == 0
    t = json.loads(lim(st, "live.json").read_text())["vars"]["turns.coder"]
    assert t["value"] == 170 and t["prev"] == 128 and t["hold"] == 1 and t["d"] == 0.5
    assert run_cli("rollback", "hard.agent.*", "--to", "seed") == 0
    live = json.loads(lim(st, "live.json").read_text())
    assert all(s["value"] is None and s["hold"] == 1 and s["d"] == 0.5
               for v, s in live["vars"].items() if v.startswith("hard.agent."))
    assert invariants_ok(L.load_seed(), L.validate_live(live, L.load_seed())) == (True, None)
    hist = [json.loads(x) for x in lim(st, "history.jsonl").read_text().splitlines()]
    assert {"hold", "frozen", "rollback"} <= {h["decision"] for h in hist}
    assert {h.get("cmd") for h in hist} >= {"hold", "release", "freeze", "unfreeze"}

    capsys.readouterr()
    assert run_cli("apply") == 2
    for argv in (["apply", "--dry-run"], ["show"], ["show", "soft.agent.*", "--json"], ["status"],
                 ["history", "turns.coder"], ["stability"]):
        assert run_cli(*argv) == 0, argv
    out = capsys.readouterr().out
    assert "limits: live v" in out and '"soft.agent.coder"' in out


# ---------------------------------------------------------------- T15, T16 schema and invalid files
def test_T15_older_schema_migrated_newer_left_untouched(st):
    lim(st).mkdir(parents=True)
    old = {"version": 7, "values": {"soft.agent.coder": 25000000, "turns.scout": 99999, "hard.prompt": None}}
    raw = json.dumps(old).encode()
    lim(st, "live.json").write_bytes(raw)
    assert L.seed() == "migrated"
    assert lim(st, "live.v0.json").read_bytes() == raw
    live = json.loads(lim(st, "live.json").read_text())
    assert live["schema_version"] == 1 and live["version"] == 7
    assert live["vars"]["soft.agent.coder"]["value"] == 25000000
    assert live["vars"]["turns.scout"]["value"] == L.load_seed()["vars"]["turns.scout"]["ceiling"]    # clamped
    assert live["vars"]["hard.prompt"]["value"] is None
    assert L.seed() == "present" and lim(st, "live.json").read_text() == json.dumps(live, sort_keys=True,
                                                                                     separators=(",", ":"))
    newer = json.dumps({"schema_version": 2, "version": 40, "vars": {}}).encode()
    lim(st, "live.json").write_bytes(newer)
    lim(st, "limits.log").unlink()
    _path, notice = L.apply_and_snapshot({"session_id": "s-new", "source": "startup"}, spawn=False)
    assert lim(st, "live.json").read_bytes() == newer and "newer schema" in notice
    snap = L.read_snapshot("s-new")[0]
    s = L.load_seed()
    assert snap["values"] == {v: x["seed"] for v, x in s["vars"].items()}
    assert set(snap["origin"].values()) == {"fallback"} and snap["live_version"] is None
    assert len(lim(st, "limits.log").read_text().splitlines()) == 1


def test_T15b_seed_change_reaches_only_pristine_variables(st, capsys):
    """`seed` (install.sh) moves a variable still at an older seed (unset, n = 0, never frozen,
    held or rolled back) to the shipped seed; a learned, frozen or held value is kept."""
    s = L.load_seed()
    lim(st).mkdir(parents=True)
    old = L.live_from_seed(s)
    V = old["vars"]
    V["hard.session"]["value"] = 666000000                       # an older stack's seed, untouched
    V["hard.prompt"].update(value=90000000, frozen=120000000)    # frozen: kept
    V["soft.agent.coder"].update(value=25000000, status="supported", n=7, agents=3, changed=1.0e9,
                                 prev=19000000, recent=[{"dec": "step", "sign": 1, "rel": 0.3}])
    V["turns.scout"].update(value=10, hold=2)                    # held by the user: kept
    V["soft.agent.scout"].update(value=2000000, status="provisional", n=2,
                                 recent=[{"dec": "hold", "sign": 0, "rel": None}])   # evidence, unmoved
    old["version"] = 5
    lim(st, "live.json").write_text(json.dumps(old))
    out = L.seed()
    assert out.startswith("reseeded from the new seed: hard.session 666M -> 1.92B") and out.endswith("live v6")
    live = json.loads(lim(st, "live.json").read_text())
    hs = live["vars"]["hard.session"]
    assert hs["value"] == s["vars"]["hard.session"]["seed"] == 1920000000
    assert hs["status"] == "unset" and hs["frozen"] is None and hs["changed"] is None and L.pristine(hs)
    assert (live["vars"]["hard.prompt"]["value"], live["vars"]["hard.prompt"]["frozen"]) == (90000000, 120000000)
    assert live["vars"]["soft.agent.coder"]["value"] == 25000000
    assert (live["vars"]["turns.scout"]["value"], live["vars"]["turns.scout"]["hold"]) == (10, 2)
    assert live["vars"]["soft.agent.scout"]["value"] == 2000000
    changed = {v for v in s["vars"] if live["vars"][v]["value"] != V[v]["value"]}
    assert changed == {"hard.session"} and live["version"] == 6
    hist = [json.loads(x) for x in lim(st, "history.jsonl").read_text().splitlines()]
    assert [(h["var"], h["decision"], h["old"], h["new"]) for h in hist] == [
        ("hard.session", "reseeded", 666000000, 1920000000)]
    assert L.seed() == "present"                                 # idempotent
    L.apply_and_snapshot({"session_id": "s-reseed", "source": "startup"}, spawn=False)
    snap = L.read_snapshot("s-reseed")[0]
    assert snap["values"]["hard.session"] == 1920000000 and snap["origin"]["hard.session"] == "live"
    capsys.readouterr()
    assert run_cli("show", "hard.session*") == 0
    row = [x for x in capsys.readouterr().out.splitlines() if x.startswith("hard.session ")][0].split()
    assert row[1:3] == ["1.92B", "1.92B"] and "live" in row


def test_T15d_reseed_never_moves_a_learned_partner_or_a_rolled_back_value(st):
    """A re-seed that would break soft <= ratio x hard against a learned partner is skipped (the
    invariant would move the learned value); a rolled-back variable (d = 1/2) is not pristine."""
    s = L.load_seed()
    assert s["vars"]["soft.agent.coder"]["seed"] == 19000000
    lim(st).mkdir(parents=True)
    old = L.live_from_seed(s)
    V = old["vars"]
    V["soft.agent.coder"]["value"] = 15000000                    # pristine at an older seed
    V["hard.agent.coder"].update(value=20000000, status="supported", n=9, agents=3, changed=1.0e9,
                                 recent=[{"dec": "step", "sign": 1, "rel": None}])
    V["soft.agent.scout"]["value"] = 2000000                     # pristine, partner unset: re-seeded
    lim(st, "live.json").write_text(json.dumps(old))
    L.seed()
    W = json.loads(lim(st, "live.json").read_text())["vars"]
    assert W["hard.agent.coder"]["value"] == 20000000 and W["soft.agent.coder"]["value"] == 15000000
    assert W["soft.agent.scout"]["value"] == s["vars"]["soft.agent.scout"]["seed"]
    seed_turns = s["vars"]["turns.coder"]["seed"]
    W["turns.coder"]["value"] = seed_turns - 1
    lim(st, "live.json").write_text(json.dumps(dict(json.loads(lim(st, "live.json").read_text()), vars=W)))
    L.cmd_rollback("turns.coder", to="prev")                     # value unchanged, hold 1, d 1/2
    L.cmd_hold("turns.coder", sessions=0)                        # released: still d 1/2
    assert L.seed() == "present"
    assert json.loads(lim(st, "live.json").read_text())["vars"]["turns.coder"]["value"] == seed_turns - 1


def test_T15c_schema0_values_are_not_pristine(st):
    """Values imported from schema 0 that differ from the seed carry a `migrated` decision, so a
    later `seed` never takes them for an untouched seed value."""
    lim(st).mkdir(parents=True)
    lim(st, "live.json").write_text(json.dumps({"version": 3, "values": {"hard.session": 700000000}}))
    assert L.seed() == "migrated"
    live = json.loads(lim(st, "live.json").read_text())
    assert live["vars"]["hard.session"]["value"] == 700000000
    assert not L.pristine(live["vars"]["hard.session"]) and L.pristine(live["vars"]["hard.prompt"])
    assert L.seed() == "present"


def test_T16_invalid_live_set_aside_and_reseeded(st):
    lim(st).mkdir(parents=True)
    lim(st, "live.json").write_bytes(b"{not json")
    _path, notice = L.apply_and_snapshot({"session_id": "s-inv", "source": "startup"}, spawn=False)
    aside = list(lim(st).glob("live.invalid-*.json"))
    assert len(aside) == 1 and aside[0].read_bytes() == b"{not json"
    live = json.loads(lim(st, "live.json").read_text())
    assert live["version"] == 1 and live["vars"]["turns.coder"]["value"] == 170
    assert "live.json invalid (not JSON)" in lim(st, "limits.log").read_text() and "reseeded" in notice
    assert L.read_snapshot("s-inv")[0]["origin"]["turns.coder"] == "live"
    # a structurally broken variable is invalid too
    bad = dict(live)
    bad["vars"] = dict(live["vars"], **{"turns.coder": {"value": "170"}})
    lim(st, "live.json").write_text(json.dumps(bad))
    L.apply_and_snapshot({"session_id": "s-inv2", "source": "startup"}, spawn=False)
    assert len(list(lim(st).glob("live.invalid-*.json"))) == 2


# ---------------------------------------------------------------- T17 hostile CSV
def test_T17_hostile_csv_moves_at_most_one_bounded_step(st):
    good = coder_rows(sessions=3, agents=4, ctx=12000000, api=30, t0=T0 + 5000)
    hostile = [
        row("sess-0", "nan1", ctx="nan"), row("sess-0", "inf1", ctx="inf"), row("sess-1", "neg1", ctx=-5),
        row("sess-1", "huge1", ctx=2e10), row("sess-2", "turn1", api=20000), row("sess-2", "bad id!", ctx=5e7),
        row("sess-2", "badts", last_ts="nan"), row("sess-2", "badtype", typ="(unknown)"),
        row("../../etc", "x1"), row("sess-2", "flag1", compacted=-1), dict(row("sess-2", "sv"), schema_version=9),
    ]
    flood = [row("evil", f"e{i}", ctx=9.9e9, api=9999, ts=T0 + i * 0.01, hit_soft=1, status_code=1)
             for i in range(60000)]
    _setup_rows(st, good + hostile + flood)
    L.seed()
    before = json.loads(lim(st, "live.json").read_text())
    doc = L.propose()
    assert doc["rows"] == 50000 and doc["truncated"] and doc["dropped"] >= len(hostile) - 1
    entries = list(doc["vars"].items()) + list(doc["pools"].items())
    assert any(len(e["x"]) == 24 for _, e in entries)
    for k, e in entries:
        evil = 9999 if k.startswith("turns") else 9.9e9
        assert len([x for x in e["x"] if x >= evil]) <= len(e["x"]) / 2, k     # <= 50 % from one session
        assert all(math.isfinite(x) and x >= 0 for x in e["x"])
    L.apply_and_snapshot({"session_id": "s-hostile", "source": "startup"}, spawn=False)
    after = json.loads(lim(st, "live.json").read_text())
    s = L.load_seed()
    moved = 0
    for v, spec in s["vars"].items():
        old, new = before["vars"][v]["value"], after["vars"][v]["value"]
        assert new is None or spec["floor"] <= new <= spec["ceiling"], v
        if old is not None and new is not None:
            assert abs(new - old) <= 0.25 * old + 1, (v, old, new)
            moved += new != old
    assert moved >= 1


# ---------------------------------------------------------------- T19 concurrency
CHILD = r"""
import json, sys, time
sys.path.insert(0, sys.argv[3])
import stack_limits as L
t = float(sys.argv[2])
while time.time() < t:
    time.sleep(0.001)
print(json.dumps(L.apply_and_snapshot({"session_id": sys.argv[1], "source": "startup"}, spawn=False)))
"""


def test_T19_concurrent_apply_one_version_bump(st, tmp_path):
    _setup_rows(st, coder_rows())
    L.seed()
    L.propose()
    v0 = json.loads(lim(st, "live.json").read_text())["version"]
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env.update(XDG_STATE_HOME=str(tmp_path / "st"), PYTHONDONTWRITEBYTECODE="1", CLAUDE_CONFIG_DIR=str(tmp_path / "c"))
    start = time.time() + 1.0
    ps = [subprocess.Popen([PY, "-c", CHILD, sid, repr(start), str(HOOKS)], env=env, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, text=True) for sid in ("s-c1", "s-c2")]
    outs = [p.communicate(timeout=60) for p in ps]
    assert all(p.returncode == 0 for p in ps), outs
    live = json.loads(lim(st, "live.json").read_text())
    assert live["version"] == v0 + 1
    docs = [L.read_snapshot(s) for s in ("s-c1", "s-c2")]
    assert all(state == "ok" for _, state in docs)
    assert {d["live_version"] for d, _ in docs} == {v0 + 1}
    batches = {(h["session"], h["live_version"]) for h in map(json.loads, lim(st, "history.jsonl").read_text()
                                                               .splitlines()) if h["decision"] != "seeded"}
    assert len(batches) == 1


# ---------------------------------------------------------------- T20 latency
def _full_proposals(seed, rng):
    vs, pools = {}, {}
    for v, spec in seed["vars"].items():
        base = spec["seed"] or spec["floor"] * 3
        x = sorted(min(spec["ceiling"] * 3, max(1, rng.lognormvariate(math.log(base), 0.6))) for _ in range(400))
        if spec["unit"] == "turns":
            x = [float(round(v)) for v in x]
        vs[v] = {"x": x, "prob": [0.5] * 400, "ci": [L._qs(x, 0.85), L._qs(x, 0.95)], "agents": 60, "sessions": 12, "tight": 1,
                     "n_new": 400, "upto": T0, "top": x[::-1][:50], "regime_ok": True, "n": 400}
    for fam in L.TYPE_FAMILIES:
        for pool in seed["pools"]:
            pools[f"{fam}:{pool}"] = vs["{}.{}".format(fam, seed["pools"][pool][0])]
    return props(vs, pools, eid="a" * 64)


def test_T20_latency(st):
    rng = random.Random(7)
    s = L.load_seed()
    L.seed()
    base = lim(st, "live.json").read_bytes()
    lim(st, "proposals.json").write_text(json.dumps(_full_proposals(s, rng)))
    times = []
    for k in range(50):
        lim(st, "live.json").write_bytes(base)
        t = time.perf_counter()
        path, _ = L.apply_and_snapshot({"session_id": f"s-perf-{k}", "source": "startup"}, spawn=False)
        times.append(time.perf_counter() - t)
        assert L.read_snapshot(f"s-perf-{k}")[0]["live_version"] == 2
    times.sort()
    assert times[int(0.95 * len(times)) - 1] <= 0.300, times[-5:]
    resume = []
    for _ in range(50):
        t = time.perf_counter()
        assert L.apply_and_snapshot({"session_id": "s-perf-0", "source": "resume"}, spawn=False) == (path.replace(
            "s-perf-49", "s-perf-0"), None)
        resume.append(time.perf_counter() - t)
    resume.sort()
    assert resume[int(0.95 * len(resume)) - 1] <= 0.020, resume[-5:]


# ---------------------------------------------------------------- more behaviour
def test_auto_off_and_env_overrides(st, monkeypatch):
    monkeypatch.setenv("STACK_LIMITS_AUTO", "0")
    monkeypatch.setenv("STACK_MAXTURNS_CODER", "33")
    monkeypatch.setenv("STACK_PROMPT_CTX_BUDGET", "0")
    monkeypatch.setenv("STACK_SOFTCTX_SCOUT", "1e6")                         # not digits: ignored, logged
    _path, notice = L.apply_and_snapshot({"session_id": "s-off", "source": "startup"}, spawn=False)
    assert notice is None and not lim(st, "live.json").exists()
    snap = L.read_snapshot("s-off")[0]
    s = L.load_seed()
    assert snap["values"]["turns.coder"] == 33 and snap["origin"]["turns.coder"] == "env"
    assert snap["values"]["hard.prompt"] is None and snap["origin"]["hard.prompt"] == "env"
    assert snap["values"]["soft.agent.scout"] == s["vars"]["soft.agent.scout"]["seed"]
    assert snap["origin"]["soft.agent.scout"] == "seed" and snap["auto"] is False
    assert "STACK_SOFTCTX_SCOUT" in lim(st, "limits.log").read_text()


def test_tamper_and_session_limits(st, capsys, tmp_path):
    path, _ = L.apply_and_snapshot({"session_id": "s-tamp", "source": "startup"}, spawn=False)
    ok = L.session_limits("s-tamp")
    assert ok["state"] == "ok" and ok["values"]["turns.coder"] == 170 and len(ok["snap"]) == 16
    doc = json.loads(Path(path).read_text())
    doc["values"]["turns.coder"] = 9999
    os.chmod(path, 0o644)
    Path(path).write_text(json.dumps(doc))
    capsys.readouterr()
    for _ in range(3):
        r = L.session_limits("s-tamp", sdir=str(tmp_path / "sdir"))
        assert r["state"] == "tamper" and r["values"]["turns.coder"] == 170
    assert capsys.readouterr().err.count("seed values in use") == 1
    assert (tmp_path / "sdir" / "limits-tamper").exists()
    p2, notice = L.apply_and_snapshot({"session_id": "s-tamp", "source": "resume"}, spawn=False)
    assert p2 == path and "tamper" in notice
    # a missing snapshot is written on demand without applying
    assert L.session_limits("s-late")["state"] == "ok" and L.read_snapshot("s-late")[1] == "ok"


def test_rows_reader_v1_v2_and_regime(st):
    v1 = [dict(row("old", "a1", ctx=5e6, ts=T0 - 10), schema_version=1) for _ in range(1)]
    write_csv(st / "usage" / "runs.csv", v1, V1_COLUMNS)
    write_csv(st / "usage" / "runs2.csv", [row("old", "a1", ctx=6e6, ts=T0 - 5), row("new", "b1", typ="coder-copy"),
                                           row("new", "main", typ="blackcat", seg=2, ctx="", window_ctx=7e7,
                                               is_main=1),
                                           row("new", "session", typ="blackcat", ctx=3e8, is_main=1)])
    rows, _stats = L.read_rows(known={"coder"})
    by = {(r["session"], r["id"]): r for r in rows}
    assert by[("old", "a1")]["ctx"] == 6e6 and by[("old", "a1")]["src"] == "measured"     # runs2 wins
    assert by[("new", "b1")]["type"] == "coder" and by[("new", "main")]["scope"] == "main"
    assert by[("new", "session")]["scope"] == "session" and by[("new", "main")]["window_ctx"] == 7e7
    v1only, _ = L.read_rows([str(st / "usage" / "runs.csv")])
    assert v1only[0]["src"] == "seed_v1" and v1only[0]["regime"] is None
    # rows of another regime: all rows used, but only provisionally
    other = [dict(r, regime="0" * 16) for r in coder_rows()]
    write_csv(st / "usage" / "runs2.csv", other)
    doc = L.build_proposals(L.load_seed())
    assert doc["vars"]["soft.agent.coder"]["regime_ok"] is False
    write_csv(st / "usage" / "runs2.csv", coder_rows())
    doc = L.build_proposals(L.load_seed())
    assert doc["vars"]["soft.agent.coder"]["regime_ok"] is True
    assert doc["fingerprint"] == L.fingerprint() and L.proposals_stale()
    L.propose()
    assert not L.proposals_stale()


def test_main_and_session_rows_feed_the_scope_variables(st):
    rows = []
    for s in range(3):
        for w in range(10):
            rows.append(row(f"p{s}", "main", typ="blackcat", seg=w, ctx="", window_ctx=6e7 + 1e6 * w, is_main=1,
                            ts=T0 + 100 * s + w))
    for s in range(5):
        rows.append(row(f"q{s}", "session", typ="blackcat", ctx=4e8 + 1e7 * s, is_main=1, ts=T0 + s))
    _setup_rows(st, rows)
    doc = L.build_proposals(L.load_seed())
    assert doc["vars"]["soft.prompt"]["n"] == 30 and doc["vars"]["soft.prompt"]["sessions"] == 3
    assert doc["vars"]["hard.session"]["sessions"] == 5
    live = L.live_from_seed(L.load_seed())
    ok, _ = L.validate_proposals(doc, L.load_seed())
    new, recs, _ch = L.apply_proposals(L.load_seed(), live, ok)
    by = {r["var"]: r for r in recs}
    assert by["soft.prompt"]["decision"] == "step" and new["vars"]["soft.prompt"]["value"] > 33000000
    assert "soft.prompt.orchestrator" not in doc["vars"]                         # no orchestrator ran
    # the windows in which an orchestrator ran are the per-type prompt sample
    rows += [row(f"p{s}", f"o{s}", typ="orchestrator", seg=w, window=w, ts=T0 + 100 * s + w)
             for s in range(3) for w in (2, 5)]
    _setup_rows(st, rows)
    doc = L.build_proposals(L.load_seed())
    e = doc["vars"]["soft.prompt.orchestrator"]
    assert e["n"] == 6 and e["sessions"] == 3 and e["x"] == sorted([6.2e7, 6.5e7] * 3)
    assert new["vars"]["soft.session"]["value"] is not None                      # supported: >= 5 sessions
    assert invariants_ok(L.load_seed(), new) == (True, None)


def test_reader_keeps_rows_after_a_bad_line(tmp_path):
    """F2: a NUL line (csv on Python < 3.11 refuses it), an unbalanced quote and bad UTF-8 cost their own
    line only, never the rest of the file."""
    p = tmp_path / "runs2.csv"
    p.write_bytes(b"schema_version,session,id,type,seg,status,api_calls,ctx,last_ts\n"
                  b"2,s1,a1,coder,0,complete,5,1000,1790000000\n\x00bad\n"
                  b"2,s1,a2,coder,0,complete,6,2000,1790000001\n"
                  b'2,s1,"open,quote\n'
                  b"2,s1,a3,coder,0,complete,6,2000,1790000002\n\xff\xfe broken\n"
                  b"2,s1,a4,coder,0,complete,6,2000,1790000003\n")
    rows, stats = L.read_rows([str(p)])
    assert {r["id"] for r in rows} == {"a1", "a2", "a3", "a4"} and stats["errors"] == 0


def _scope_row(i, aid, hit_col=None, code=""):
    r = {c: "" for c in V2_COLUMNS}
    top = aid in ("main", "session")
    r.update(schema_version="2", session=f"s{i % 4}", id=aid, type="blackcat" if top else "coder",
             seg=str(i), status="complete", last_ts=str(T0 + i), ctx=str(int(4e8 + 1e6 * i)),
             window_ctx=str(int(5e7 + 1e5 * i)), is_main="1" if top else "0", src="measured",
             compacted="0", turn_limited="0", status_code=code,
             **{c: "0" for c in ("hit_soft", "hit_turn", "hit_hard_agent", "hit_hard_prompt", "hit_hard_session")})
    if hit_col:
        r[hit_col] = "1"
    return L.parse_row(r)


def test_tight_counts_main_and_session_rows_without_a_status_code():
    """M1: main-window and session rows carry no status code (the collector writes it empty); a hit of
    their own kind there is tight. Agent rows still need a done or partial status code."""
    main = [_scope_row(i, "main", "hit_hard_prompt" if i % 8 == 0 else None) for i in range(40)]
    assert all(r["status_code"] is None and r["scope"] == "main" for r in main)
    assert L._entry(main, "hard.prompt", "hard", 0.0, "k", {})["tight"] == 5
    soft = [_scope_row(i, "main", "hit_soft" if i < 3 else None) for i in range(40)]
    assert L._entry(soft, "soft.prompt", "soft", 0.0, "k", {})["tight"] == 3
    sess = [_scope_row(i, "session", "hit_hard_session" if i in (1, 4) else None) for i in range(8)]
    assert L._entry(sess, "hard.session", "hard", 0.0, "k", {})["tight"] == 2
    agents = [_scope_row(i, f"a{i}", "hit_hard_agent" if i < 4 else None, code="" if i < 2 else "1")
              for i in range(20)]
    assert L._entry(agents, "hard.agent", "hard", 0.0, "k", {})["tight"] == 2


def test_S3_compacted_is_a_count_not_a_flag(st):
    """S3: the collector writes `compacted` as a count; a twice-compacted segment was dropped (U1)."""
    r = {k: str(v) for k, v in row("s1", "a1").items()}
    assert L.parse_row(dict(r, compacted="2"))["compacted"] == 1
    assert L.parse_row(dict(r, compacted="1"))["compacted"] == 1
    assert L.parse_row(dict(r, compacted="0"))["compacted"] == 0
    assert L.parse_row(dict(r, compacted=""))["compacted"] is None
    for bad in ("-1", "nan", "inf", "x", "2e6"):
        assert L.parse_row(dict(r, compacted=bad)) is None, bad


def test_V1_a_running_session_keeps_its_snapshot_past_the_prune_age(st):
    """V1 (U4): the 30-day snapshot prune went by the snapshot's mtime, which nothing refreshed, inside
    another session's apply: a session older than 30 days lost its snapshot and the guard's
    session_limits wrote a new one from the current live.json (limits changed mid-session). The
    snapshot is touched at each SessionStart of its session, and a session whose guard folder changed
    lately is kept."""
    old = time.time() - 31 * 86400

    def backdate(sid):
        for p in Path(L.snapshots_dir()).glob(sid + ".*"):
            os.utime(p, (old, old))
    sids = ("s-live", "s-resumed", "s-gone")
    for sid in sids:
        L.apply_and_snapshot({"session_id": sid, "source": "startup"}, spawn=False)
    vals = {sid: L.session_limits(sid)["values"] for sid in sids}
    assert len(list(Path(L.snapshots_dir()).glob("s-live.*"))) == 2          # the snapshot and its model
    for sid in sids:
        backdate(sid)
    (st / "s-live").mkdir()                                  # the guard's folder of a running session
    assert L.apply_and_snapshot({"session_id": "s-resumed", "source": "resume"}, spawn=False)[1] is None
    _setup_rows(st, coder_rows())
    assert L.propose() is not None
    _p, note = L.apply_and_snapshot({"session_id": "s-new", "source": "startup"}, spawn=False)
    assert note and "coder.soft 19M→23.7M" in note                       # applied: the prune ran
    for sid in ("s-live", "s-resumed"):
        assert L.read_snapshot(sid)[1] == "ok", sid
        assert len(list(Path(L.snapshots_dir()).glob(sid + ".*"))) == 2, sid
        assert L.session_limits(sid)["values"] == vals[sid], sid
    assert L.read_snapshot("s-gone")[1] == "missing"                      # idle 31 days: pruned
    assert not list(Path(L.snapshots_dir()).glob("s-gone.*"))


def test_V2b_five_session_u4_loop(st):
    """V2(b): five sessions of SessionStart apply -> the collector's rows (stack_usage's writer) ->
    the collector-exit propose -> the next SessionStart. Every move is a bounded step (<= 25 % x d of
    the old value) except a first set or an invariant raise; every value stays in [floor, ceiling];
    nothing moves without new evidence; a session's values never change after its start (U4);
    soft.prompt.orchestrator never drops below its 80M floor."""
    U = _load("stack_usage_for_u4_loop", HOOKS / "stack_usage.py")
    seed = L.load_seed()
    spec = seed["vars"]
    live_p, hist_p = lim(st, "live.json"), lim(st, "history.jsonl")

    def hist():
        return [json.loads(x) for x in hist_p.read_text().splitlines()] if hist_p.exists() else []

    def collector_rows(sid, k):
        cells = U.snapshot_cells(sid)
        base = dict(U.EMPTY_ROW, schema_version=2, session=sid, seg=0, status="complete", compacted=0,
                    turn_limited=0, src="measured", **cells, **{c: 0 for c in U.HIT_COLS})
        t = T0 + 1000 * k
        rows = [dict(base, id=f"c{k}{a}", type="coder", api_calls=25 + 3 * a + k, ctx=30000000 + 4000000 * a
                     + 500000 * k, first_ts=t + a - 100, last_ts=t + a, status_code=0, is_main=0, window=1)
                for a in range(4)]
        rows.append(dict(base, id=f"o{k}", type="orchestrator", api_calls=40, ctx=20000000, first_ts=t + 5,
                         last_ts=t + 9, status_code=0, is_main=0, window=2))
        rows += [dict(base, id="main", type="blackcat", seg=w, window=w, window_ctx=60000000 + 1000000 * w + k,
                      api_calls=5, ctx=1000, first_ts=t + 10 * w, last_ts=t + 10 * w + 5, status_code="", is_main=1)
                 for w in range(10)]
        rows.append(dict(base, id="session", type="blackcat", ctx=400000000 + 10000000 * k, first_ts=t,
                         last_ts=t + 200, status_code="", is_main=1))
        return rows

    started, moved = {}, set()

    def start(sid):
        """SessionStart of sid; checks the records it wrote and its snapshot. (path, values)"""
        before = len(hist())
        path, _note = L.apply_and_snapshot({"session_id": sid, "source": "startup"}, spawn=False)
        snap = L.read_snapshot(sid)[0]
        live = json.loads(live_p.read_text())
        assert snap["values"] == {v: s["value"] for v, s in live["vars"].items()}, sid
        for r in hist()[before:]:
            if r["decision"] == "seeded":
                assert sid == "loop-0" and r["var"] == "*"
                continue
            assert r["session"] == sid
            if r["new"] == r["old"]:
                continue
            moved.add(r["var"])
            f, g = spec[r["var"]]["floor"], spec[r["var"]]["ceiling"]
            assert f <= r["new"] <= g, r
            if r["old"] is None or r.get("why") == "invariant":
                continue                                   # a first set, an invariant raise
            assert r["decision"] in ("step", "clamp"), r
            assert abs(r["new"] - r["old"]) <= L.STEP_MAX * r["d"] * r["old"] + 1, r
        for v, x in snap["values"].items():
            assert x is None or spec[v]["floor"] <= x <= spec[v]["ceiling"], (v, x)
        assert snap["values"]["soft.prompt.orchestrator"] >= 80000000
        return path, snap["values"]

    for k in range(5):
        sid = f"loop-{k}"
        path, vals = start(sid)
        started[sid] = (Path(path).read_bytes(), vals)
        # the session runs: the collector appends its rows, its exit proposes; nothing live changes
        live_bytes = live_p.read_bytes()
        U.append_rows(collector_rows(sid, k))
        assert L.propose() is not None and live_p.read_bytes() == live_bytes
        assert L.apply_and_snapshot({"session_id": sid, "source": "resume"}, spawn=False) == (path, None)
        assert live_p.read_bytes() == live_bytes
    # U4: every session still sees exactly what it started with
    for sid, (raw, vals) in started.items():
        assert Path(L.snapshot_path(sid)).read_bytes() == raw and L.session_limits(sid)["values"] == vals, sid
    assert {"soft.agent.coder", "soft.prompt"} <= moved                    # the loop is not vacuous
    # no new evidence: once the last session's rows are applied, a re-propose over the same rows (the
    # same evidence id) moves nothing at the next SessionStart
    start("loop-x")
    live_bytes, n = live_p.read_bytes(), len(hist())
    L.propose()
    L.apply_and_snapshot({"session_id": "loop-y", "source": "startup"}, spawn=False)
    assert live_p.read_bytes() == live_bytes and len(hist()) == n
    assert L.read_snapshot("loop-y")[0]["values"] == L.read_snapshot("loop-x")[0]["values"]


def test_collector_v2_rows_and_snapshot_cells_meet_the_proposer(st):
    """W3 (stack_usage.py) reads `regime`, `hash` and `source_event` of this module's snapshot and
    writes runs3.csv rows this module's proposer reads (same column names)."""
    U = _load("stack_usage_v2_for_limits", HOOKS / "stack_usage.py")
    rows = []
    for s in range(3):
        sid = f"sess-{s}"
        L.apply_and_snapshot({"session_id": sid, "source": "startup"}, spawn=False)
        cells = U.snapshot_cells(sid)
        snap = L.read_snapshot(sid)[0]
        assert cells == {"sess_src": "startup", "snap": snap["hash"][7:23], "regime": snap["regime"]}
        assert L.session_limits(sid)["snap"] == cells["snap"]
        for a in range(4):
            rows.append(dict(U.EMPTY_ROW, schema_version=U.SCHEMA_VERSION, session=sid, id=f"a{s}{a}", type="coder",
                             seg=0, status="complete", api_calls=30, ctx=40000000 + 1000 * a, last_ts=T0 + 10 * s + a,
                             compacted=0, turn_limited=0, status_code=0, is_main=0, src="measured",
                             model=SONNET if a % 2 else "", **cells))
    U.append_rows(rows)
    assert (st / "usage" / "runs3.csv").exists()
    assert not (st / "usage" / "runs.csv").exists() and not (st / "usage" / "runs2.csv").exists()
    e = L.build_proposals(L.load_seed())["vars"]["soft.agent.coder"]
    assert e["n"] == 12 and e["regime_ok"] is True               # coder is a sonnet agent: every row counts


# ---------------------------------------------------------------- /override-agent runs are no evidence (model)
def _ts(k):
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(T0 + k)) + ".250Z"


def _subagent(folder, aid, atype, models, k0, cr=20000):
    """A finished subagent transcript (prompt, tool calls, a text-only last call) whose assistant messages
    report `models` (one per call, the last repeated) and its meta file."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = [{"type": "user", "timestamp": _ts(k0), "message": {"role": "user", "content": "go"}}]
    for i, m in enumerate(models):
        last = i == len(models) - 1
        content = [{"type": "text", "text": "ok"}]
        if not last:
            content.append({"type": "tool_use", "id": f"tu{aid}{i}", "name": "Read", "input": {"file_path": "/r/a"}})
        lines.append({"type": "assistant", "requestId": f"req{aid}{i}", "timestamp": _ts(k0 + 2 * i + 1),
                      "uuid": f"u{aid}{i}", "message": {"id": f"msg{aid}{i}", "model": m, "content": content,
                                                        "usage": {"input_tokens": 3, "output_tokens": 50,
                                                                  "cache_creation_input_tokens": 1000,
                                                                  "cache_read_input_tokens": cr + 100 * i}}})
        if not last:
            lines.append({"type": "user", "timestamp": _ts(k0 + 2 * i + 2), "message": {
                "role": "user", "content": [{"type": "tool_result", "tool_use_id": f"tu{aid}{i}", "content": "r"}]}})
    (folder / f"agent-{aid}.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    (folder / f"agent-{aid}.meta.json").write_text(json.dumps({"agentType": atype, "description": "look it up"}))


def _scan_cli(tmp_path, sid, folder):
    """The collector's one-shot scan, as a hook runs it (stack_usage.py on the hooks' interpreter)."""
    env = dict(os.environ, HOME=str(tmp_path / "home"), PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([PY, str(HOOKS / "stack_usage.py"), "scan", "--session", sid, "--subagents", str(folder),
                        "--final"], env=env, capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr


def test_overridden_runs_are_no_evidence_for_the_type(st, tmp_path):
    """Audit MEDIUM (f235e7a): `/override-agent scout haiku` is that session's only, but its haiku scout
    runs fed soft.agent.scout, turns.scout and the scout pool for later sessions on scout's own model
    (sonnet). The collector now records each segment's model and the proposer skips such rows."""
    for s in range(4):              # sessions 0-2: scout on its frontmatter model; 3: /override-agent scout haiku
        sid = f"11111111-2222-3333-4444-55555555555{s}"
        folder = tmp_path / "projects" / "p" / sid / "subagents"
        if s < 3:
            _subagent(folder, f"s{s}", "scout", [SONNET] * 3, 1000 * s)
        else:                                                # the overridden runs: haiku, far more context
            for i in range(2):
                _subagent(folder, f"h{i}", "scout", [HAIKU] * 6, 1000 * s + 20 * i, cr=5000000)
        _scan_cli(tmp_path, sid, folder)
    doc = L.build_proposals(L.load_seed())
    soft, turns = doc["vars"]["soft.agent.scout"], doc["vars"]["turns.scout"]
    assert soft["n"] == 3 and turns["n"] == 3 and max(soft["x"]) < 1e6 and max(turns["x"]) == 3
    pools = [e for k, e in doc["pools"].items() if k.startswith("soft.agent:")]
    assert pools and all(max(e["x"]) < 1e6 for e in pools)
    assert doc.get("model_mismatch") == 2 and doc["rows"] == 3
    # the rows themselves are kept (append-only, provenance): only the readers that learn skip them
    raw = (st / "usage" / "runs3.csv").read_text()
    assert raw.count(HAIKU) == 2 and raw.count(SONNET) == 3


def test_model_mismatch_rules(tmp_path):
    agents = tmp_path / "agents"
    agents.mkdir()
    for name, fm in (("a-sonnet", "model: sonnet"), ("a-opus", "model: Opus  # tuned"), ("a-inherit", "model: inherit"),
                     ("a-none", "effort: low"), ("a-full", "model: " + HAIKU_SHORT)):
        (agents / f"{name}.md").write_text(f"---\nname: {name}\n{fm}\n---\nbody\nmodel: fable\n")
    (agents / "notes.txt").write_text("model: opus\n")
    models = L.agent_models(str(agents))
    assert models == {"a-sonnet": "sonnet", "a-opus": "opus", "a-inherit": "inherit", "a-full": HAIKU_SHORT}
    mm = (lambda t, m: L.model_mismatch(models, t, m))
    assert mm("a-sonnet", HAIKU) and mm("a-sonnet", OPUS) and mm("a-sonnet", "mixed")
    assert not mm("a-sonnet", SONNET) and not mm("a-sonnet", BEDROCK_SONNET)
    assert not mm("a-opus", OPUS_1M) and mm("a-opus", SONNET)
    assert mm("a-full", SONNET) and not mm("a-full", HAIKU)               # a full id: its family
    assert mm("a-sonnet-copy", HAIKU) and not mm("a-sonnet-copy", SONNET)  # a copy follows its base
    for m in ("", None):                                                   # unknown (v1/v2, none reported)
        assert not mm("a-sonnet", m)
    for t in ("a-inherit", "a-none", "no-such-type", "a-inherit-copy"):    # no family to hold the row to
        assert not mm(t, HAIKU)
    assert L.agent_models(str(tmp_path / "missing")) == {}


def test_agent_models_parse_as_the_guard_does():
    G = _load("agent_guard_for_limits", GUARD)
    models = L.agent_models(str(AGENTS_DIR))
    files = sorted(p.stem for p in AGENTS_DIR.glob("*.md"))
    assert files and set(models) <= set(files)
    for t in files:
        assert models.get(t) == (G.agent_defaults(t, str(AGENTS_DIR)) or (None, None))[0], t
    assert models["scout"] == "sonnet" and models["orchestrator"] == "opus"


def test_reader_skips_mismatched_rows_after_the_merge_and_keeps_unknown_models(st):
    """Rows are filtered after last-row-wins: a v2 row (no model) of a key whose v3 row is an overridden
    run never stands in for it. v1/v2 rows, an empty model, a type without a frontmatter family and the
    main thread's rows count as before."""
    u = st / "usage"
    write_csv(u / "runs.csv", [dict(row("s0", "v1a", typ="scout", ctx=3e5), schema_version=1)], V1_COLUMNS)
    write_csv(u / "runs2.csv", [row("s0", "v2a", typ="scout", ctx=3.1e5, regime=""),        # no regime: one sample
                                row("s1", "k", typ="scout", ctx=3.2e5, status="partial", regime="")])
    v3 = V2_COLUMNS + ["model"]
    r3 = (lambda *a, model="", **kw: dict(row(*a, **kw), schema_version=3, model=model, regime=""))
    write_csv(u / "runs3.csv", [r3("s1", "k", typ="scout", ctx=9e6, model=HAIKU),           # the same key, overridden
                                r3("s3", "e", typ="scout", ctx=3.3e5),                       # empty: unknown
                                r3("s4", "ok", typ="scout", ctx=3.4e5, model=SONNET),
                                r3("s1", "mx", typ="scout", ctx=9e6, model="mixed"),
                                r3("s5", "bad", typ="scout", ctx=3.5e5, model="not a model"),  # invalid: unknown
                                r3("s2", "c1", typ="scout-copy", ctx=9e6, model=HAIKU),
                                r3("s2", "x1", typ="custom-agent", ctx=9e6, model=HAIKU),
                                r3("s2", "main", typ="blackcat", seg=0, ctx="", window_ctx=5e7, is_main=1,
                                   model=HAIKU)], v3)
    rows, stats = L.read_rows(known={"scout"})
    ids = {r["id"] for r in rows}
    assert ids == {"v1a", "v2a", "e", "ok", "bad", "x1", "main"} and stats["model_mismatch"] == 3
    assert {r["model"] for r in rows if r["id"] in ("v1a", "v2a", "e", "bad")} == {None}
    rows, stats = L.read_rows(known={"scout"}, models={})                 # no frontmatter: nothing skipped
    assert len(rows) == 10 and stats["model_mismatch"] == 0
    doc = L.build_proposals(L.load_seed())
    assert doc["vars"]["soft.agent.scout"]["n"] == 5 and doc["model_mismatch"] == 3
    assert max(doc["vars"]["soft.agent.scout"]["x"]) < 1e6


def test_prompt_windows_of_an_overridden_agent_are_not_its_types(st):
    """soft.prompt.<type> reads the main windows in which an agent of that type ran: an overridden run
    (an orchestrator on sonnet) does not make its window that type's evidence."""
    rows = []
    for s in range(3):
        for w in range(10):
            rows.append(row(f"p{s}", "main", typ="blackcat", seg=w, ctx="", window_ctx=6e7 + 1e6 * w, is_main=1,
                            ts=T0 + 100 * s + w))
        rows.append(dict(row(f"p{s}", f"o{s}", typ="orchestrator", seg=0, window=2, ts=T0 + 100 * s + 2),
                         schema_version=3, model=OPUS))
        rows.append(dict(row(f"p{s}", f"n{s}", typ="orchestrator", seg=0, window=5, ts=T0 + 100 * s + 5),
                         schema_version=3, model=SONNET))
    write_csv(st / "usage" / "runs3.csv", rows, V2_COLUMNS + ["model"])
    doc = L.build_proposals(L.load_seed())
    e = doc["vars"]["soft.prompt.orchestrator"]
    assert e["n"] == 3 and e["x"] == [6.2e7] * 3 and doc["model_mismatch"] == 3
    assert doc["vars"]["soft.prompt"]["n"] == 30                        # the main windows themselves all count


def test_a_session_row_older_than_its_sessions_rows_is_not_learned(st):
    """Audit of the upgrade hand-off (MEDIUM): an older collector stopped mid-session writes a `complete`
    session row with the ctx of that moment; if the successor then idles out, nothing replaces it, and
    soft.session/hard.session would learn a truncated session. A session row whose last_ts is below
    another row of its session is left out (stats["stale_session"]); one that spans them all is kept."""
    rows = [row("ok", "a1", ts=T0 + 10), row("ok", "main", typ="blackcat", is_main=1, ts=T0 + 20),
            row("ok", "session", typ="blackcat", is_main=1, ctx=9e7, ts=T0 + 20),            # spans its rows
            row("cut", "a1", ts=T0 + 10), row("cut", "session", typ="blackcat", is_main=1, ctx=5e7, ts=T0 + 30),
            row("cut", "a2", ts=T0 + 50),                                                     # the session went on
            row("lone", "session", typ="blackcat", is_main=1, ctx=7e7, ts=T0 + 5)]            # no other rows
    write_csv(st / "usage" / "runs2.csv", rows)
    # the successor's rows (schema 3) for the cut session's agents: newer, and still no new session row
    write_csv(st / "usage" / "runs3.csv", [dict(row("cut", "a3", ts=T0 + 60), schema_version=3, model="")],
              V2_COLUMNS + ["model"])
    got, stats = L.read_rows(models={})
    sess = {r["session"]: r["ctx"] for r in got if r["scope"] == "session"}
    assert sess == {"ok": 9e7, "lone": 7e7} and stats["stale_session"] == 1
    assert {(r["session"], r["id"]) for r in got if r["scope"] != "session"} >= {("cut", "a1"), ("cut", "a2"), ("cut", "a3")}
    assert L.build_proposals(L.load_seed())["stale_session"] == 1
    # the successor's own final scan writes a session row spanning everything: learned again
    write_csv(st / "usage" / "runs3.csv", [dict(row("cut", "a3", ts=T0 + 60), schema_version=3, model=""),
                                           dict(row("cut", "session", typ="blackcat", is_main=1, ctx=9.5e7,
                                                    ts=T0 + 60), schema_version=3, model="")], V2_COLUMNS + ["model"])
    got, stats = L.read_rows(models={})
    assert {r["session"]: r["ctx"] for r in got if r["scope"] == "session"}["cut"] == 9.5e7
    assert stats["stale_session"] == 0
