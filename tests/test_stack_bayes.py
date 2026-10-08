"""Bayes limits in the limits hook (WP3a, docs/BAYES.md sections 2, 3, A.8, A.9): stack_bayes_grid.py and the
Bayes tier of stack_limits.py, shadow by default.

Run: uv run --no-cache --with pytest pytest -q tests/test_stack_bayes.py
Tests B1-T1..T10, T12, T15..T19, S1, S2 of docs/BAYES.md A.9, the Q1 assertion on BAYES_LIVE, the rollback drill
(STACK_BAYES=off), and the byte-equality of shadow and off with main d6046693 on the frozen fixture
(tests/fixtures/bayes/b1v2). B1-T14 is tests/b1_backtest.py (a uv script, WP5). Every test uses its own
XDG_STATE_HOME under tmp_path, never the stack's.
"""
import ast
import hashlib
import importlib.util
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "dot-config" / "dot-claude" / "hooks"
LIMITS_PY = HOOKS / "stack_limits.py"
GRID_PY = HOOKS / "stack_bayes_grid.py"
AGENTS_DIR = ROOT / "dot-config" / "dot-claude" / "agents"
FIX = ROOT / "tests" / "fixtures" / "bayes" / "b1v2"
B1V2 = ROOT / "docs" / "bayes" / "b1v2"
HYPER_CTX, HYPER_TURNS = B1V2 / "out_v2" / "hyper_ctx.json", B1V2 / "out_v2" / "hyper_turns.json"
PY = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else sys.executable
MAIN_REV = "d6046693"            # main before WP3a (docs/BAYES.md: line numbers are at this commit)
FIX_REGIME = "6278adf0187ec069"  # the regime of the fixture's runs3.csv rows (state/proposals.json "regime")
P_RESUME = 0.3238434163701068    # docs/bayes/b1v2/out_v2/run_meta.json p_resume (the v2 fit's resume share)
FIT = "0123456789abcdef"
T0 = 1790000000.0
NOW = 1792000000.0


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("stack_limits", LIMITS_PY)
G = _load("stack_bayes_grid", GRID_PY)
SEED = L.load_seed()
TYPES = L._types(SEED)


@pytest.fixture
def st(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "st"))
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))     # no install manifest
    L._ENV_WARNED.clear()
    root = tmp_path / "st" / "claude-agent-stack"
    (root / "limits").mkdir(parents=True)
    return root


def lim(st, *parts):
    return st.joinpath("limits", *parts)


# ---------------------------------------------------------------- builders
GOOD_MODEL = {"gate": True, "diag": {"rhat_max": 1.0034, "ess_bulk_min": 1841, "ess_tail_min": 1680, "divergences": 0,
                                     "ebfmi_min": 0.76, "constant": ["z_s"], "nan": []}}
GOOD_DIAG = {"rhat": 1.002, "ess_bulk": 1810, "ess_tail": 1490, "mcse_rel": 0.006, "edge_mass": None}


def qtab_for(T, r, s=0.6):
    """A log-normal predictive table whose (1 - r) quantile is T."""
    zr = G.nppf(1 - r)
    return {"p": list(L.QTAB_P), "x": [T * math.exp((G.nppf(p) - zr) * s) for p in L.QTAB_P]}


def block(var, T, s=0.6, **kw):
    fam = L.split_var(var)[0]
    r = L.RISK[fam]
    b = {"tier": "nuts", "model": L.BAYES_MODEL.get(fam, "ctx-ln-h4"), "risk": r, "T": T, "T_raw": T * 0.99,
         "pi90": [T * 0.7, T * 1.4], "qtab": qtab_for(T, r, s), "at_bound": False, "n": 12, "n_cens": 1, "agents": 6,
         "sessions": 3, "shrink": 0.5, "status": "supported", "diag": dict(GOOD_DIAG)}
    b.update(kw)
    return b


def bayes_doc(eid, vars_, hyper=None, models=None, drift=None, fit_id=FIT, seed=SEED, **kw):
    d = {"schema_version": 1, "code": "stack_bayes/1", "generated": "2026-10-08T12:00:00Z", "evidence_id": eid,
         "seed_sha": seed["sha"], "fit_id": fit_id, "risk": dict(L.RISK),
         "sampler": {"seed": 20261003, "chains": 4, "draws": 3000, "tune": 2000, "target_accept": 0.98},
         "versions": {"python": "3.13.16", "pymc": "6.3.2"}, "data": {"rows": 320, "files": {"runs3.csv": "0" * 64}},
         "models": models if models is not None else {"turns-nb2s-h4": GOOD_MODEL, "ctx-ln-h4": GOOD_MODEL},
         "hyper": hyper or {}, "drift": drift or {}, "vars": vars_, "sched": None}
    d.update(kw)
    return d


def v2_hyper(seed=SEED):
    """The v2 fit's NUTS hyperparameters (docs/bayes/b1v2/out_v2/hyper_*.json "nuts") in the section 2.1 shape:
    tau_new = the files' tau_s (sqrt(tau_s^2 + tau_ts^2), fit_prototype.hyper_from_nuts), p_resume of
    run_meta.json; types restricted to today's seed types (rule 3: three v2 types were retired since)."""
    types = set(L._types(seed))
    out = {}
    for k, f in (("ctx", HYPER_CTX), ("turns", HYPER_TURNS)):
        h = json.loads(f.read_text())["nuts"]
        out[k] = {"tau_t": h["tau_t"], "tau_new": h["tau_s"], "rho": h["rho"], "p_resume": P_RESUME,
                  "types": {t: v for t, v in h["types"].items() if t in types}}
    return out


def ent(xs, agents=None, sessions=3, n_new=None, upto=T0, regime_ok=True, b=None):
    xs = sorted(float(v) for v in xs)
    lo, hi = L.boot_ci(xs, B=200, seed=1) if len(xs) >= 3 else (None, None)
    e = {"x": xs, "ci": [lo, hi], "agents": len(xs) if agents is None else agents, "sessions": sessions, "tight": 0,
         "n_new": len(xs) if n_new is None else n_new, "upto": upto, "top": sorted(xs, reverse=True)[:50],
         "regime_ok": regime_ok}
    if b is not None:
        e["b"] = b
    return e


def norm_ent(e, unit="ctx"):
    out = L._valid_entry(e, unit)
    assert out is not None, e
    return out


def props_doc(eid, vars_, pools=None, **kw):
    d = {"schema_version": 1, "generated": "2026-10-08T12:00:00Z", "evidence_id": eid, "vars": vars_,
         "pools": pools or {}, "regime": None, "fingerprint": []}
    d.update(kw)
    return d


def write_json(p, doc):
    p.write_text(json.dumps(doc, sort_keys=True))


def hist(st):
    p = lim(st, "history.jsonl")
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def start(sid, now=NOW):
    return L.apply_and_snapshot({"session_id": sid, "source": "startup"}, spawn=False, now=now)


_UPTO = [T0]


def coder_props(eid, n=12, base=20e6, agents=None, upto=None):
    """Supported own samples for three types (ctx and turns), newer than any earlier call's (each apply
    has new rows)."""
    if upto is None:
        _UPTO[0] += 10
        upto = _UPTO[0]
    V = {}
    for t, k in (("coder", 1.0), ("scout", 0.02), ("verifier", 0.3)):
        xs = [base * k * (1 + 0.05 * i) for i in range(n)]
        V[f"soft.agent.{t}"] = ent(xs, agents=agents, upto=upto)
        V[f"hard.agent.{t}"] = ent(xs, agents=agents, upto=upto)
        V[f"turns.{t}"] = ent([20 + i for i in range(n)], agents=agents, upto=upto)
    return props_doc(eid, V)


def coder_blocks():
    """Valid nuts blocks for coder_props's variables (all of them would move: T far from c)."""
    out = {}
    for t in ("coder", "scout", "verifier"):
        c = SEED["vars"][f"soft.agent.{t}"]["seed"]
        out[f"soft.agent.{t}"] = block(f"soft.agent.{t}", int(L.ceil2(c * 1.6)))
        out[f"hard.agent.{t}"] = block(f"hard.agent.{t}", 50000000)
        out[f"turns.{t}"] = block(f"turns.{t}", max(5, SEED["vars"][f"turns.{t}"]["seed"] // 3))
    return out


def setup_apply(st, eid=None, blocks=None, doc=None, upto=None):
    eid = eid or os.urandom(32).hex()
    write_json(lim(st, "proposals.json"), coder_props(eid, upto=upto))
    if doc is None and blocks is not None:
        doc = bayes_doc(eid, blocks)
    if doc is not None:
        (lim(st, "bayes.json").write_text(doc) if isinstance(doc, str) else write_json(lim(st, "bayes.json"), doc))
    return eid


# ---------------------------------------------------------------- B1-T1 grid vs scipy, p_hit
NB_REF = [(9.0, 2.0, 0.95, 24), (9.0, 2.0, 0.98, 29), (30.0, 0.8, 0.9, 75), (30.0, 0.8, 0.99, 158),
          (150.0, 5.0, 0.5, 141), (3.5, 1.2, 0.975, 14)]        # 1 + scipy.stats.nbinom.ppf(p, a, a / (a + mu))
LN_REF = [(math.log(2e6), 1.0, 0.0, 0.9, 7204448.958558313), (math.log(2e6), 1.0, 0.0, 0.99, 20480947.312624257),
          (14.3, 1.2, 0.0, 0.5, 1623345.9850084595), (14.3, 1.2, 0.55, 0.9, 8812631.160406573),
          (12.0, 0.6, 0.3, 0.999, 1293666.3163084276)]          # scipy.stats.lognorm.ppf(p, sqrt(s^2+tau^2), exp(m))


def test_B1_T1_grid_quantiles_equal_scipy_under_a_sharp_prior():
    for mu, a, p, ref in NB_REF:
        etas, w, _ = G.nb_post([], [], math.log(mu), 1e-6, a)
        q, _ci, _mix = G.nb_quantile(etas, w, p, a, kmax=2000)
        assert q == ref, (mu, a, p, q, ref)
    for m, s, tau, p, ref in LN_REF:
        etas, w, _ = G.lognormal_post([], [], m, 1e-6, s)
        lq, _ci = G.lognormal_quantile(etas, w, p, s, tau)
        assert math.exp(lq) == pytest.approx(ref, rel=1e-6), (m, s, tau, p)


def test_B1_T1_embedded_references_equal_scipy_live():
    """The embedded NB_REF / LN_REF values, recomputed with scipy where it is installed. scipy is not a
    dependency of the tools venv (requirements/tools.in): skipped there."""
    stats = pytest.importorskip("scipy.stats")
    for mu, a, p, ref in NB_REF:                                 # the embedded values, live
        assert 1 + int(stats.nbinom.ppf(p, a, a / (a + mu))) == ref
    for m, s, tau, p, ref in LN_REF:
        assert float(stats.lognorm.ppf(p, s=math.sqrt(s * s + tau * tau), scale=math.exp(m))) == pytest.approx(ref, rel=1e-12)


def test_B1_T1_p_hit_inverts_qtab_and_clamps_outside_it():
    qt = qtab_for(10e6, 0.1)
    X, P = qt["x"], qt["p"]
    for x, p in zip(X, P):
        assert L.p_hit(qt, x) == pytest.approx(1 - p, rel=1e-12)
    for k in range(len(X) - 1):                                  # log(1 - F) linear in log c between points
        c = math.sqrt(X[k] * X[k + 1])
        assert L.p_hit(qt, c) == pytest.approx(math.sqrt((1 - P[k]) * (1 - P[k + 1])), rel=1e-9)
        assert 1 - P[k + 1] <= L.p_hit(qt, c) <= 1 - P[k]
    assert L.p_hit(qt, X[0] * 0.999) == 0.5 and L.p_hit(qt, 1.0) == 0.5
    assert L.p_hit(qt, X[-1] * 1.001) == 0.001 and L.p_hit(qt, 1e12) == 0.001
    tied = {"p": list(L.QTAB_P), "x": [1, 2, 3, 3, 3, 4, 5, 6]}
    assert L.p_hit(tied, 3) == pytest.approx(1 - 0.9)             # equal x's: the larger 1 - p


def test_B1_T1_grid_vs_nuts_reported_not_gated(capsys):
    """The v2 fixture's soft.agent grid T (NUTS hyperparameters) against the v2 NUTS T: printed, no assertion."""
    p = fixture_props(hyper=(dict(v2_hyper(), breach=[]), "fit:" + FIT))
    ex = json.loads((B1V2 / "out_v2" / "proposals_bayes_example.json").read_text())
    lines = []
    for v, e in sorted(p["vars"].items()):
        if "bayes" in e and v in ex:
            lines.append(f"{v}: grid {e['bayes']['T']} nuts {ex[v]['T']}")
    print("\n".join(lines) or "no overlap")


# ---------------------------------------------------------------- B1-T2 stdlib only, Python 3.9
def _imports(path):
    mods = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            mods |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0
            mods.add(node.module.split(".")[0])
    return mods


def test_B1_T2_stdlib_only_and_imports_on_the_hook_interpreter():
    std = getattr(sys, "stdlib_module_names", None)
    if std is None:
        pytest.skip("needs Python >= 3.10 for sys.stdlib_module_names")
    assert _imports(GRID_PY) <= {"math", "random"}               # math at the top; random inside nig_lognormal
    assert _imports(GRID_PY) <= set(std)
    assert _imports(LIMITS_PY) - {"stack_io", "stack_bayes_grid"} <= set(std)
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import stack_bayes_grid, stack_limits; "
            "print(sys.version_info[:2], stack_limits.LIVE_SCHEMA)")
    p = subprocess.run([PY, "-c", code, str(HOOKS)], env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                       capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0, p.stderr
    p = subprocess.run([PY, str(GRID_PY)], capture_output=True, text=True, timeout=60, check=False)
    assert p.returncode == 0 and "self-check ok" in p.stdout, p.stderr


def test_install_stages_stack_bayes_grid():
    """install.sh stages hooks/stack_bayes_grid.py (644) in the folder of stack_limits.py, whose _grid_mod()
    loads it by path from there, tracks it in the manifest (STACK_SCRIPTS) and compiles it with the hook
    modules; the redundancy lint sees it staged (3a security review F2)."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    staged = _load("bayes_stack_diff", ROOT / "lib" / "stack_diff.py").staged_files(text)
    assert staged.get("hooks/stack_bayes_grid.py") == "dot-config/dot-claude/hooks/stack_bayes_grid.py"
    assert staged.get("hooks/stack_limits.py") == "dot-config/dot-claude/hooks/stack_limits.py"
    assert re.search(r'(?m)^for f in [^;\n]*\bstack_bayes_grid\.py\b[^;\n]*; do stage_script 644 "hooks/\$f"; done$', text)
    assert '"hooks/stack_bayes_grid.py"' in re.search(r"(?s)STACK_SCRIPTS = \[(.*?)\]", text).group(1)
    mods = re.search(r'(?m)^\s*for m in ([^;\n]+); do\n\s*if \[ -f "\$C/hooks/\$m\.py" \]', text)
    assert mods and "stack_bayes_grid" in mods.group(1).split()
    rl = _load("bayes_redundancy_lint", ROOT / "tests" / "redundancy_lint.py")
    assert "stack_bayes_grid.py" in rl.installer_staged_hooks(text)
    assert "stack_bayes_grid.py" not in [f for f, _why in rl.find_dead_hooks(ROOT)]


# ---------------------------------------------------------------- B1-T3 hostile bayes.json
def _hostile_docs(eid):
    good = bayes_doc(eid, coder_blocks())
    js = json.dumps(good)
    cases = {}

    def mod(name, fn):
        d = json.loads(js)
        fn(d)
        cases[name] = d
    cases["nan token"] = js.replace('"T_raw": ', '"T_raw": NaN, "x_": ', 1)
    cases["infinity token"] = js.replace('"shrink": 0.5', '"shrink": Infinity', 1)
    mod("negative", lambda d: d["vars"]["soft.agent.coder"].update(T=-1))
    mod("non-monotone qtab", lambda d: d["vars"]["soft.agent.coder"]["qtab"]["x"].reverse())
    mod("wrong qtab.p", lambda d: d["vars"]["soft.agent.coder"]["qtab"].update(p=[0.5] * 8))
    mod("wrong evidence_id", lambda d: d.update(evidence_id="f" * 64))
    mod("wrong seed_sha", lambda d: d.update(seed_sha="sha256:" + "0" * 64))
    mod("another risk table", lambda d: d["risk"].update({"soft.agent": 0.2}))
    mod("fixed guard var STACK_MAX_FANOUT", lambda d: d["vars"].update(STACK_MAX_FANOUT=block("soft.agent.coder", 1e6)))
    mod("fixed guard var STACK_BAYES", lambda d: d["vars"].update(STACK_BAYES=block("soft.agent.coder", 1e6)))
    mod("fixed guard model id", lambda d: d["models"].update(stack_max_fanout=GOOD_MODEL))
    mod("fixed guard nested key", lambda d: d["versions"].update(STACK_BAYES="on"))
    mod("fixed guard hyper type", lambda d: d.update(hyper={"ctx": dict(v2_hyper()["ctx"], types={"STACK_BAYES": {
        "mu": 14.0, "scale": 1.0}})}))
    mod("unknown name", lambda d: d["vars"].update({"soft.agent.no-such-type": block("soft.agent.coder", 1e6)}))
    mod("bool as number", lambda d: d["vars"]["soft.agent.coder"].update(n=True))
    mod("hyper type not in seed", lambda d: d.update(hyper={"ctx": dict(v2_hyper()["ctx"], types={"supreme-coder": {
        "mu": 14.0, "scale": 1.0}})}))
    mod("schema 2", lambda d: d.update(schema_version=2))
    mod("not stack_bayes code", lambda d: d.update(code="other/1"))
    cases["over 4 MiB"] = js[:-1] + ', "pad": "' + "x" * (4 << 20) + '"}'
    cases["deep nesting"] = js[:-1] + ', "deep": ' + "[" * 100000 + "]" * 100000 + "}"
    cases["moderate nesting"] = js[:-1] + ', "deep": ' + "[" * 40 + "]" * 40 + "}"
    cases["huge integer"] = js.replace('"n": 12', '"n": ' + "9" * 200000, 1)
    cases["not an object"] = "[1, 2, 3]"
    cases["not json"] = js[:100]
    return good, cases


RULE2_ONLY = {"wrong evidence_id", "another risk table"}           # load_hyper skips rule 2 but fit_id/seed_sha


def test_B1_T3_hostile_bayes_json_is_ignored_whole(st, monkeypatch):
    eid = setup_apply(st)
    good, cases = _hostile_docs(eid)
    good = dict(good, hyper=v2_hyper())
    assert L.load_bayes(SEED, eid, doc=json.loads(json.dumps(good))), "the positive control loads"
    lim(st, "live.json").write_text(json.dumps(L.live_from_seed(SEED)))
    base = None
    for name, doc in cases.items():
        raw = doc if isinstance(doc, str) else json.dumps(doc)
        lim(st, "bayes.json").write_text(raw)
        assert L.load_bayes(SEED, eid) is None, name
        if name not in RULE2_ONLY:
            assert L.load_hyper(SEED) == (None, None), name
        assert L.bayes_context(SEED, {"evidence_id": eid, "vars": {}}) is None or name in RULE2_ONLY, name
        # end to end: a new session applies section 4, method empirical, values equal off's
        for f in ("live.json", "history.jsonl"):
            if lim(st, f).exists():
                lim(st, f).unlink()
        lim(st, "live.json").write_text(json.dumps(L.live_from_seed(SEED)))
        path, notice = start("s-" + str(abs(hash(name)) % 10 ** 8))
        assert path and "error" not in (notice or ""), (name, notice)
        recs = hist(st)
        assert recs and all(r.get("method") == "empirical" for r in recs if r.get("var") != "*"), name
        vals = json.loads(Path(path).read_text())["values"]
        base = base or vals
        assert vals == base, name


def test_B1_T3_positive_control_v2_hyper_with_negative_rho_is_accepted(st):
    eid = "a" * 64
    hy = v2_hyper()
    assert hy["ctx"]["rho"] < 0 and hy["turns"]["rho"] < 0
    write_json(lim(st, "bayes.json"), bayes_doc(eid, coder_blocks(), hyper=hy))
    h, src = L.load_hyper(SEED)
    assert src == "fit:" + FIT and h["ctx"]["rho"] == hy["ctx"]["rho"] and h["turns"]["rho"] == hy["turns"]["rho"]
    acc = L.load_bayes(SEED, eid)
    assert set(acc) == set(coder_blocks()) and all(b["tier"] == "nuts" and b["fit_id"] == FIT for b in acc.values())


# ---------------------------------------------------------------- B1-T4 gates
def test_B1_T4_gate_failures_fall_back_to_section_4(st):
    eid = "b" * 64
    blocks = coder_blocks()
    bad = {"soft.agent.coder": {"rhat": 1.02}, "soft.agent.scout": {"ess_bulk": 300},
           "soft.agent.verifier": {"ess_tail": 300}, "hard.agent.coder": {"mcse_rel": 0.03},
           "hard.agent.scout": {"rhat": None}}
    for v, d in bad.items():
        blocks[v]["diag"].update(d)
    acc = L.load_bayes(SEED, eid, doc=bayes_doc(eid, blocks))
    assert set(acc) == set(blocks) - set(bad)
    for m in ({"divergences": 1}, {"ebfmi_min": 0.2}, {"rhat_max": 1.02}, {"ess_bulk_min": 399},
              {"nan": ["tau_t"]}, {"constant": ["tau_t"]}, {"rhat_max": None}):
        model = {"gate": True, "diag": dict(GOOD_MODEL["diag"], **m)}
        doc = bayes_doc(eid, blocks, models={"turns-nb2s-h4": model, "ctx-ln-h4": model})
        assert L.load_bayes(SEED, eid, doc=doc) == {}, m          # `gate: true` with a failing diag
        assert L.load_hyper(SEED, doc=dict(doc, hyper=v2_hyper())) == (None, None), m
    doc = bayes_doc(eid, blocks, models={"turns-nb2s-h4": dict(GOOD_MODEL, gate=False), "ctx-ln-h4": GOOD_MODEL})
    assert all(not v.startswith("turns.") for v in L.load_bayes(SEED, eid, doc=doc))
    # end to end with every model failing: method empirical, values as with no bayes.json
    model = {"gate": True, "diag": dict(GOOD_MODEL["diag"], divergences=1)}
    setup_apply(st, eid, doc=bayes_doc(eid, blocks, models={"turns-nb2s-h4": model, "ctx-ln-h4": model}))
    path, _ = start("s-gate")
    off = _values_without_bayes(st, eid)
    assert json.loads(Path(path).read_text())["values"] == off
    assert {r["method"] for r in hist(st) if r.get("var") != "*"} == {"empirical"}


def _values_without_bayes(st, eid):
    """The values a fresh state gets from the same proposals with no bayes.json (section 4 alone)."""
    live = L.live_from_seed(SEED)
    props, _ = L.validate_proposals(json.loads(lim(st, "proposals.json").read_text()), SEED)
    new, _r, _c = L.apply_proposals(SEED, live, props, now=NOW, bayes=None, mode="off")
    return L.snapshot_values(SEED, new, True)[0]


# ---------------------------------------------------------------- B1-T5 prior holds
def test_B1_T5_no_own_rows_never_moves_and_deny_types_need_support():
    rnd = random.Random(5)
    for _ in range(2000):
        t = rnd.choice(TYPES)
        fam = rnd.choice(("turns", "soft.agent", "hard.agent"))
        v = f"{fam}.{t}"
        spec = SEED["vars"][v]
        c = spec["seed"] or spec["floor"]
        st0 = L._var_state(c)
        unit = spec["unit"]
        big = 30 if unit == "turns" else 3e7
        pool = norm_ent(ent([big * (1 + 0.01 * i) for i in range(20)], sessions=5), unit)
        blk = L._valid_block(block(v, max(spec["floor"], rnd.uniform(0.2, 5) * c)), unit)
        if blk is None:
            continue
        s, rec = L.decide_bayes(v, spec, st0, blk, None, pool, None, NOW)     # no own rows, only a pool
        assert s["value"] == c and (rec is None or rec["decision"] == "hold:prior"), rec
        if fam in ("turns", "hard.agent"):                       # deny-type, not supported: never moves
            e = norm_ent(ent([big * rnd.uniform(0.5, 2) for _ in range(rnd.randint(1, 2))]), unit)
            s, rec = L.decide_bayes(v, spec, st0, blk, e, None, 1e6, NOW)
            assert s["value"] == c and rec["decision"] == "hold:unsupported"
            s, rec = L.decide_bayes(v, spec, L._var_state(None), blk, e, None, 1e6, NOW)
            assert s["value"] is None and rec["decision"] == "hold:unsupported"
    blk = L._valid_block(block("soft.agent.coder", 1e7, n=0, n_cens=0), "ctx")
    e = norm_ent(ent([1e7] * 6))
    s, rec = L.decide_bayes("soft.agent.coder", SEED["vars"]["soft.agent.coder"], L._var_state(19000000), blk, e)
    assert rec["decision"] == "hold:prior" and s["value"] == 19000000


# ---------------------------------------------------------------- B1-T6 censoring, A.3
def _r(**kw):
    r = {"session": "s1", "id": "a1", "seg": 0, "status": "complete", "compacted": 0, "turn_limited": 0,
         "api_calls": 30.0, "ctx": 5e6, "window": None, "status_code": 0, "sv": 3, "scope": "agent"}
    for h in L._HIT_COLS:
        r[h] = 0
    r.update(kw)
    return r


def test_B1_T6_censoring_table_per_family():
    nohits = {h: None for h in L._HIT_COLS}
    rows = [  # (A.3 line, row, turns flag, ctx flag)
        (1, _r(status="open"), True, True),
        (2, _r(compacted=1), True, True),
        (3, _r(turn_limited=1), True, True), (3, _r(hit_turn=1), True, True),
        (4, _r(hit_soft=1), True, True), (4, _r(hit_hard_agent=1), True, True),
        (4, _r(hit_hard_session=1), True, True),
        (5, _r(window=2), True, True),
        (6, _r(status_code=1, api_calls=30.0, ctx=5e6, **nohits), True, True),          # >= 0.5 x limit
        (6, _r(status_code=1, api_calls=10.0, ctx=1e6, **nohits), False, False),        # below
        (6, _r(status_code=1, api_calls=30.0, ctx=1e6, **nohits), True, False),
        (7, _r(status_code=1, api_calls=30.0, ctx=5e6), False, False),                  # hit_* measured 0
        (8, _r(status_code=2, **nohits), False, False),
        (9, _r(status_code=None, sv=3), True, True),
        (9, _r(status_code=None, sv=2), False, False),
        (0, _r(), False, False),
    ]
    win = {("s1", 2)}
    for line, row, t_flag, c_flag in rows:
        assert L.censor_flags(row, "turns", 40, win) is t_flag, (line, "turns", row)
        assert L.censor_flags(row, "ctx", 8e6, win) is c_flag, (line, "ctx", row)
    proxy = _r(status_code=1, api_calls=30.0, ctx=5e6, **nohits)
    assert L.censor_flags(proxy, "turns", 40, set()) and not L.censor_flags(dict(proxy, hit_soft=0), "turns", 40, set())
    assert not L.censor_flags(proxy, "turns", None, set())                      # limit off: no proxy
    for fam, own in (("soft.prompt", "hit_hard_prompt"), ("hard.session", "hit_hard_session")):
        main = _r(scope="main", hit_soft=0)
        assert not L.censor_flags(main, fam, None, set())
        assert L.censor_flags(dict(main, **{own: 1}), fam, None, set())
        assert L.censor_flags(dict(main, hit_soft=1), fam, None, set())


# ---------------------------------------------------------------- B1-T7 pins, env, names
def test_B1_T7_pins_never_move_under_random_blocks(st, monkeypatch):
    rnd = random.Random(7)
    for v, pin in (("soft.prompt.orchestrator", 140000000), ("hard.prompt", 300000000)):
        spec = SEED["vars"][v]
        assert spec["seed"] == spec["floor"] == spec["ceiling"] == pin
        for _ in range(10000):
            T = rnd.uniform(1e6, 3e9)
            blk = L._valid_block(dict(block("soft.agent.coder", T), risk=L.RISK[L.split_var(v)[0]]), "ctx")
            assert blk is not None
            xs = [rnd.uniform(1e6, 5e8) for _ in range(rnd.randint(1, 40))]
            e = norm_ent(ent(xs, sessions=rnd.randint(1, 10), regime_ok=rnd.random() < 0.8))
            st0 = L._var_state(pin)
            st0["d"] = rnd.choice(L.D_LEVELS)
            s, _rec = L.decide_bayes(v, spec, st0, blk, e, None, None, NOW)
            assert s["value"] == pin
    # load_bayes drops a block for a scope variable (A.8 item 13) and keeps the rest of the file
    eid = "c" * 64
    blocks = dict(coder_blocks(), **{"hard.prompt": dict(block("soft.agent.coder", 9e8), risk=0.01),
                                     "soft.prompt.orchestrator": block("soft.agent.coder", 1e8)})
    acc = L.load_bayes(SEED, eid, doc=bayes_doc(eid, blocks))
    assert "hard.prompt" not in acc and "soft.prompt.orchestrator" not in acc and "soft.agent.coder" in acc
    # env overrides: exact, origin env, with blocks present (on and shadow)
    monkeypatch.setattr(L, "BAYES_LIVE", frozenset({"soft.agent"}))
    monkeypatch.setenv("STACK_BAYES", "on")
    monkeypatch.setenv("STACK_SOFTCTX_CODER", "1234567")
    monkeypatch.setenv("STACK_SOFT_PROMPT_CTX_ORCHESTRATOR", "150000001")
    setup_apply(st, eid, doc=bayes_doc(eid, coder_blocks()))
    path, _ = start("s-env")
    snap = json.loads(Path(path).read_text())
    assert snap["values"]["soft.agent.coder"] == 1234567 and snap["origin"]["soft.agent.coder"] == "env"
    assert snap["values"]["soft.prompt.orchestrator"] == 150000001
    assert snap["values"]["hard.prompt"] == 300000000
    # no fixed-guard name in what was written
    for doc in (json.loads(lim(st, "live.json").read_text())["vars"], json.loads(lim(st, "proposals.json").read_text())["vars"],
                snap["values"], snap["prov"]["vars"]):
        assert not any(L.is_fixed_guard(k) for k in doc)


# ---------------------------------------------------------------- B1-T8 step bound
def test_B1_T8_step_bound_and_invariants_with_random_blocks(monkeypatch):
    rnd = random.Random(8)
    moved = 0
    for _ in range(10000):
        t = rnd.choice(TYPES)
        fam = rnd.choice(("turns", "soft.agent", "hard.agent"))
        v = f"{fam}.{t}"
        spec = SEED["vars"][v]
        unit = spec["unit"]
        f, g = spec["floor"], spec["ceiling"]
        c = rnd.randint(f, g)
        T = rnd.uniform(0.05, 20) * c
        blk = L._valid_block(block(v, min(T, L.TURNS_MAX if unit == "turns" else L.CTX_MAX), s=rnd.uniform(0.1, 2)), unit)
        if blk is None:                                          # its table left the variable's range
            continue
        xs = [c * rnd.uniform(0.2, 3) for _ in range(rnd.randint(5, 30))]
        e = norm_ent(ent(xs, sessions=rnd.randint(2, 8)), unit)
        st0 = L._var_state(c)
        st0["d"] = rnd.choice(L.D_LEVELS)
        st0["recent"] = [{"dec": "step", "sign": rnd.choice((-1, 1)), "rel": 0.1} for _ in range(rnd.randint(0, 5))]
        s, rec = L.decide_bayes(v, spec, st0, blk, e, None, rnd.choice((None, c / 3)), NOW)
        assert f <= s["value"] <= g
        if rec and rec["decision"] in ("step", "clamp") and "stepped" in rec:
            d = rec["d"]
            assert abs(rec["stepped"] - c) <= L.STEP_MAX * d * c + 1, (v, c, rec)
            moved += 1
    assert moved > 1000
    # invariants after a live Bayes apply (soft families acting): soft <= 0.8 hard for every pair
    monkeypatch.setattr(L, "BAYES_LIVE", frozenset({"soft.agent"}))
    for it in range(30):
        eid = os.urandom(32).hex()
        props, _ = L.validate_proposals(coder_props(eid, base=rnd.uniform(1e6, 9e7)), SEED)
        live = L.live_from_seed(SEED)
        live["vars"]["hard.agent.coder"]["value"] = 2000000
        blocks = {v: L._valid_block(dict(b, T=rnd.uniform(0.5, 2) * b["T"]), SEED["vars"][v]["unit"])
                  for v, b in coder_blocks().items()}
        bctx = {"nuts": {v: dict(b, fit_id=FIT) for v, b in blocks.items() if b}, "hyper_source": None,
                "breach": set(), "fit_id": FIT}
        new, recs, _ = L.apply_proposals(SEED, live, props, now=NOW + it, bayes=bctx, mode="on")
        assert any(r.get("method") == "bayes-nuts" for r in recs)
        for sv, hv, ratio in L._pairs(SEED):
            es, eh = L._eff(new["vars"][sv]), L._eff(new["vars"][hv])
            assert es is None or eh is None or es <= ratio * eh, (sv, es, hv, eh)


# ---------------------------------------------------------------- B1-T9 U4, proposals keys
def test_B1_T9_bayes_json_rewritten_mid_session_changes_nothing_a_session_reads(st):
    eid = setup_apply(st, blocks=coder_blocks())
    path, _ = start("s-one")
    before = Path(path).read_bytes()
    view = L.session_limits("s-one")
    v1 = json.loads(lim(st, "live.json").read_text())["version"]
    write_json(lim(st, "bayes.json"), bayes_doc(eid, coder_blocks(), fit_id="fedcba9876543210"))
    assert Path(path).read_bytes() == before and L.session_limits("s-one") == view
    start("s-one")                                                # resume: the same snapshot
    assert Path(path).read_bytes() == before
    eid2 = setup_apply(st, blocks={v: dict(b, T=b["T"] * 1.1) for v, b in coder_blocks().items()})
    p2, _ = start("s-two")
    snap2 = json.loads(Path(p2).read_text())
    v2 = json.loads(lim(st, "live.json").read_text())["version"]
    assert v2 == v1 + 1 and snap2["prov"]["fit_id"] == FIT and json.loads(lim(st, "live.json").read_text())["evidence_id"] == eid2
    p3, _ = start("s-three")                                      # applied once: no second decision on eid2
    assert json.loads(lim(st, "live.json").read_text())["version"] == v2
    assert json.loads(Path(p3).read_text())["values"] == snap2["values"]


SCOPE_VARS = ("soft.prompt", "soft.prompt.orchestrator", "hard.prompt", "soft.session", "hard.session")


def test_B1_T9_proposals_without_bayes_keys_equal_main_and_scope_vars_carry_none(tmp_path, monkeypatch):
    M = main_module(tmp_path)
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "x"))
    new = fixture_props(hyper=(dict(v2_hyper(), breach=[]), "fit:" + FIT))
    old = fixture_props(mod=M)
    assert new["bayes_hyper_source"] == "fit:" + FIT and any("bayes" in e for e in new["vars"].values())
    stripped = _strip_props(new)
    assert L._dumps(stripped) == M._dumps(old)
    for v in SCOPE_VARS:
        assert "bayes" not in new["vars"].get(v, {}) and "b" not in new["vars"].get(v, {}), v
    assert all("bayes" not in e for k, e in new["vars"].items() if not k.startswith("soft.agent."))


def _strip_props(p):
    out = {k: v for k, v in p.items() if k not in ("bayes_hyper_source", "bayes_seed_sha")}
    out["vars"] = {v: {k: x for k, x in e.items() if k not in ("b", "bayes")} for v, e in p["vars"].items()}
    return out


# ---------------------------------------------------------------- B1-T10 provenance, migration
def test_B1_T10_prov_is_hashed_and_the_guard_reads_the_snapshot(st):
    setup_apply(st, blocks=coder_blocks())
    path, _ = start("s-prov")
    snap = json.loads(Path(path).read_text())
    assert snap["prov"]["bayes_mode"] == "shadow" and snap["prov"]["fit_id"] == FIT
    assert set(snap["prov"]["vars"]) == set(coder_blocks())
    pv = snap["prov"]["vars"]["soft.agent.coder"]
    assert pv["method"] == "bayes-shadow" and pv["risk"] == 0.1 and 0 <= pv["p_hit"] <= 1
    assert snap["hash"] == L.snap_hash(snap)
    tampered = dict(snap, prov=dict(snap["prov"], fit_id="ffffffffffffffff"))
    assert L.snap_hash(tampered) != snap["hash"]
    code = ("import sys, os; sys.path.insert(0, sys.argv[1]); import agent_guard as g; "
            "d, s = g.read_limits_snapshot(sys.argv[2]); print(s, sorted(d['prov']) if d else None)")
    env = {k: v for k, v in os.environ.items() if not k.startswith("STACK_")}
    env.update(XDG_STATE_HOME=os.environ["XDG_STATE_HOME"], PYTHONDONTWRITEBYTECODE="1")
    p = subprocess.run([PY, "-c", code, str(HOOKS), "s-prov"], env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and p.stdout.split()[0] == "ok", (p.stdout, p.stderr)


def test_B1_T10_schema_1_live_with_learned_values_migrates_and_keeps_them(st):
    raw = (FIX / "state" / "live.json").read_bytes()           # the 2026-10-03 live.json (schema 1, learned)
    old = json.loads(raw)
    assert old["schema_version"] == 1
    learned = {v: s["value"] for v, s in old["vars"].items() if v in SEED["vars"] and s["value"] != SEED["vars"][v]["seed"]}
    assert learned
    lim(st, "live.json").write_bytes(raw)
    live, note = L.load_live_locked(SEED)
    assert note == "migrated" and lim(st, "live.v1.json").read_bytes() == raw
    live2, note2 = L.load_live_locked(SEED)
    assert note2 is None and live2 == live and live2["schema_version"] == 2
    for v, x in learned.items():
        spec = SEED["vars"][v]
        want = None if x is None else int(min(max(round(x), spec["floor"]), spec["ceiling"]))
        assert live2["vars"][v]["value"] == want, v
        assert live2["vars"][v]["bayes"] is None and live2["vars"][v]["method"] is None
    assert not list(lim(st).glob("live.invalid-*"))
    L.seed()                                                      # install.sh's step: no set-aside either
    assert not list(lim(st).glob("live.invalid-*"))


def test_B1_T10_live_keeps_a_valid_bayes_block_and_drops_an_invalid_one(st):
    live = L.live_from_seed(SEED)
    good = L._valid_block(block("soft.agent.coder", 2e7), "ctx")
    live["vars"]["soft.agent.coder"].update(bayes=good, method="bayes-nuts")
    live["vars"]["soft.agent.scout"].update(bayes=dict(good, T=-5), method="magic")
    out = L.validate_live(json.loads(L._dumps(live)), SEED)
    assert out["vars"]["soft.agent.coder"]["bayes"] == good and out["vars"]["soft.agent.coder"]["method"] == "bayes-nuts"
    assert out["vars"]["soft.agent.scout"]["bayes"] is None and out["vars"]["soft.agent.scout"]["method"] is None


# ---------------------------------------------------------------- B1-T12 latency
def test_B1_T12_apply_p95_under_300ms_with_176_blocks(st):
    rnd = random.Random(12)
    V, blocks = {}, {}
    for v in sorted(SEED["vars"]):
        fam, t = L.split_var(v)
        spec = SEED["vars"][v]
        base = (spec["seed"] or spec["floor"]) * 0.8
        blocks[v] = block(v, int(L.ceil2(base * rnd.uniform(0.7, 1.6))), risk=L.RISK[fam])
        if not t or fam not in L.BAYES_FAMILIES:
            continue
        xs = [base * rnd.uniform(0.3, 1.5) for _ in range(L.MAX_X)]
        b = {"y": [round(x) for x in xs], "cens": [int(rnd.random() < 0.1) for _ in xs],
             "resume": [int(rnd.random() < 0.3) for _ in xs], "sess": [i % 20 for i in range(len(xs))]}
        V[v] = ent(xs, agents=40, sessions=20, b=b)
    assert len(blocks) == 176 and len(V) == 171
    times = []
    for i in range(20):
        eid = os.urandom(32).hex()
        for e in V.values():
            e["upto"] = T0 + i                                   # new rows for every variable each session
        write_json(lim(st, "proposals.json"), props_doc(eid, V))
        write_json(lim(st, "bayes.json"), bayes_doc(eid, blocks))
        t0 = time.perf_counter()
        path, notice = start(f"s-lat-{i}", now=NOW + i)
        times.append(time.perf_counter() - t0)
        assert path and "error" not in (notice or "")
    snap = json.loads(Path(path).read_text())
    assert len(snap["prov"]["vars"]) == 171                       # the five scope blocks dropped (A.8 item 13)
    assert sum(1 for r in hist(st) if r.get("method") == "bayes-shadow" and r["live_version"] == snap["live_version"]) == 171
    times.sort()
    p95 = times[int(math.ceil(0.95 * len(times))) - 1]
    print(f"B1-T12 apply_and_snapshot p50 {1000 * times[len(times) // 2]:.0f} ms, p95 {1000 * p95:.0f} ms (176 blocks)")
    assert p95 <= 0.300


# ---------------------------------------------------------------- B1-T15 hold:sparse
def test_B1_T15_a_sparse_soft_type_never_falls():
    rnd = random.Random(15)
    seen = 0
    for _ in range(10000):
        t = rnd.choice(TYPES)
        v = "soft.agent." + t
        spec = SEED["vars"][v]
        c = rnd.randint(spec["floor"], spec["ceiling"])
        T = min(rnd.uniform(0.05, 4) * c, 9e9)
        blk = L._valid_block(block(v, T, s=rnd.uniform(0.1, 2)), "ctx")
        if blk is None:
            continue
        n = rnd.randint(1, 4)                                    # below support: n < 5 and too few agents / wide CI
        e = norm_ent(ent([c * rnd.uniform(0.05, 3) for _ in range(n)], agents=1, sessions=1,
                         regime_ok=rnd.random() < 0.5))
        assert L.classify("soft.agent", e, None)[0] != "supported"
        st0 = L._var_state(c)
        st0["d"] = rnd.choice(L.D_LEVELS)
        s, rec = L.decide_bayes(v, spec, st0, blk, e, None, None, NOW)
        assert s["value"] >= c, (v, c, T, rec)
        if rec and T < c and rec["decision"] == "hold:sparse":
            seen += 1
    assert seen > 1000


# ---------------------------------------------------------------- B1-T16 no moment hyperparameters
def test_B1_T16_moment_or_foreign_hyperparameters_never_feed_a_decision(st, monkeypatch):
    hy = (dict(v2_hyper(), breach=[]), "fit:" + FIT)
    p = fixture_props(hyper=hy)
    grid_vars = [v for v, e in p["vars"].items() if "bayes" in e]
    assert grid_vars and all(v.startswith("soft.agent.") for v in grid_vars)
    for src, sha in (("stdlib-moments", SEED["sha"]), (None, SEED["sha"]), ("fit:" + FIT, "sha256:" + "1" * 64),
                     ("fit:" + FIT.upper(), SEED["sha"]), ("fit:" + FIT + "0", SEED["sha"])):
        doc = dict(p, bayes_hyper_source=src, bayes_seed_sha=sha)
        if src is None:
            doc.pop("bayes_hyper_source")
        vp, _ = L.validate_proposals(json.loads(json.dumps(doc)), SEED)
        assert not any("bayes" in e for e in vp["vars"].values()), src
        assert vp["bayes_hyper_source"] is None
    # load_hyper without a gated bayes.json -> (None, None) and propose writes no grid block
    assert L.load_hyper(SEED) == (None, None)
    p0 = fixture_props()
    assert p0["bayes_hyper_source"] is None and not any("bayes" in e for e in p0["vars"].values())
    for model in ({"gate": False, "diag": GOOD_MODEL["diag"]}, {"gate": True, "diag": dict(GOOD_MODEL["diag"], ess_bulk_min=10)}):
        write_json(lim(st, "bayes.json"), bayes_doc("d" * 64, {}, hyper=v2_hyper(), models={"ctx-ln-h4": model}))
        assert L.load_hyper(SEED) == (None, None)
    # grid blocks in the proposals: used in shadow while apply's own load_hyper names the same fit ...
    eid = p["evidence_id"]
    write_json(lim(st, "proposals.json"), p)
    write_json(lim(st, "bayes.json"), bayes_doc("d" * 64, {}, hyper=v2_hyper()))
    vp, _ = L.validate_proposals(json.loads(json.dumps(p)), SEED)
    bctx = L.bayes_context(SEED, vp)
    used = [v for v in grid_vars if L.choose_block(v, bctx, vp)[1] == "grid"]
    assert used
    # ... and not after bayes.json is deleted, another fit, or a drift breach of soft.agent
    for case in ("deleted", "other fit", "breach"):
        if case == "deleted":
            lim(st, "bayes.json").unlink()
        elif case == "other fit":
            write_json(lim(st, "bayes.json"), bayes_doc("d" * 64, {}, hyper=v2_hyper(), fit_id="fedcba9876543210"))
        else:
            write_json(lim(st, "bayes.json"), bayes_doc("d" * 64, {}, hyper=v2_hyper(), drift={
                "soft.agent": {"ks_p": 0.001, "sessions": 5, "breach": True}}))
        bctx = L.bayes_context(SEED, vp)
        assert all(L.choose_block(v, bctx, vp) == (None, None) for v in grid_vars), case
        live = L.live_from_seed(SEED)
        new, recs, _ = L.apply_proposals(SEED, live, vp, now=NOW, bayes=bctx, mode="shadow")
        assert {r["method"] for r in recs} <= {"empirical"}, case
    assert eid


def _names(path):
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
        elif isinstance(node, ast.alias):
            out.add(node.name.split(".")[-1])
            if node.asname:
                out.add(node.asname)
    return out


def test_B1_T16_no_eb_hyper_defined_or_referenced():
    for path in (GRID_PY, LIMITS_PY):
        assert not [n for n in _names(path) if n.startswith("eb_hyper")], path
        assert "eb_hyper" not in path.read_text(encoding="utf-8"), path


# ---------------------------------------------------------------- B1-T17 NaN-strict model gate
def split_rhat(chains):
    """Split R-hat (Gelman et al. 2013) in the stdlib: NaN when the within-chain variance is 0."""
    halves = []
    for c in chains:
        h = len(c) // 2
        halves += [c[:h], c[h:2 * h]]
    n = len(halves[0])
    means = [sum(h) / n for h in halves]
    W = sum(sum((x - m) ** 2 for x in h) / (n - 1) for h, m in zip(halves, means)) / len(halves)
    gm = sum(means) / len(means)
    B = n * sum((m - gm) ** 2 for m in means) / (len(means) - 1)
    if W == 0:
        return float("nan")
    return math.sqrt(((n - 1) / n * W + B / n) / W)


def fake_posterior(constant=()):
    rnd = random.Random(17)
    post = {}
    for name in ("a0", "tau_t", "z_t[0]", "z_t[1]", "z_s[0]", "rho"):
        if name.split("[")[0] in constant or name in constant:
            chains = [[0.3 + k] * 400 for k in range(4)]          # constant per chain (differs across chains)
        else:
            chains = [[rnd.gauss(0, 1) for _ in range(400)] for _ in range(4)]
        r = split_rhat(chains)
        post[name] = {"rhat": r, "ess_bulk": float("nan") if math.isnan(r) else 1500.0,
                      "ess_tail": float("nan") if math.isnan(r) else 1400.0}
    return post


def test_B1_T17_a_nan_rhat_fails_the_gate_unless_constant_by_construction(st):
    bad = L.diag_summary(fake_posterior(constant=("tau_t",)), 0, 0.8)
    assert bad["nan"] == ["tau_t"] and not L.model_gate({"gate": True, "diag": bad})
    ok = L.diag_summary(fake_posterior(constant=("z_s",)), 0, 0.8)
    assert ok["nan"] == [] and ok["constant"] == ["z_s"] and ok["rhat_max"] <= 1.01
    assert L.model_gate({"gate": True, "diag": ok})
    # through the file: the NaN posterior's models -> every block dropped -> section 4
    eid = "e" * 64
    for diag, accepted in ((bad, False), (ok, True)):
        m = {"gate": True, "diag": diag}
        doc = json.loads(json.dumps(bayes_doc(eid, coder_blocks(), models={"turns-nb2s-h4": m, "ctx-ln-h4": m})))
        assert bool(L.load_bayes(SEED, eid, doc=doc)) is accepted


# ---------------------------------------------------------------- B1-T18 schemas
def test_B1_T18_only_live_json_is_schema_2(st):
    assert L.SCHEMA == 1 and L.LIVE_SCHEMA == 2
    assert json.loads((HOOKS / "stack_limits_seed.json").read_text())["schema_version"] == 1
    assert L.load_seed()["schema_version"] == 1
    setup_apply(st, blocks=coder_blocks())
    path, _ = start("s-schema")
    assert json.loads(lim(st, "proposals.json").read_text())["schema_version"] == 1
    assert json.loads(lim(st, "live.json").read_text())["schema_version"] == 2
    snap = json.loads(Path(path).read_text())
    assert snap["schema_version"] == 1 and "prov" in snap
    assert L.read_snapshot("s-schema")[1] == "ok"
    p = L.build_proposals(SEED, [], regime="", live=L.live_from_seed(SEED), now=NOW, models={}, hyper=None)
    assert p["schema_version"] == 1 and L.validate_proposals(json.loads(json.dumps(p)), SEED)[0] is not None


# ---------------------------------------------------------------- B1-T19 the main-window join
def _csv_rows(hit_col):
    """Two sessions: R (window 2, no hit) first, then S whose window-2 main row hit; three coder rows a
    window. Only S's window 2 is censored by the join (R has the same window number)."""
    from test_stack_limits import row as mk                       # the S6 row builder
    rows = []
    for sess, t0, hit_w in (("R", T0, None), ("S", T0 + 1000, 2)):
        for w in (1, 2):
            rows.append(mk(sess, "main", typ="blackcat", seg=w, ts=t0 + 100 * w, is_main=1, window_ctx=5e7,
                           **({hit_col: 1} if w == hit_w else {"hit_soft": 0, "hit_hard_prompt": 0})))
            for a in range(3):
                rows.append(mk(sess, f"a{w}{a}", typ="coder", ctx=4e6, api=20, ts=t0 + 100 * w + a + 1, window=w,
                               schema_version=3, status_code=0, hit_soft=0, hit_turn=0, hit_hard_agent=0,
                               hit_hard_prompt=0, hit_hard_session=0))
    return rows


@pytest.mark.parametrize("hit_col", ["hit_soft", "hit_hard_prompt"])
def test_B1_T19_a_main_window_hit_censors_that_windows_agent_rows_only(st, hit_col):
    sys.path.insert(0, str(ROOT / "tests"))
    from test_stack_limits import V2_COLUMNS, write_csv
    p = st / "usage" / "runs3.csv"
    write_csv(p, _csv_rows(hit_col), V2_COLUMNS + ["model"])
    doc = L.build_proposals(SEED, [str(p)], regime="", live=L.live_from_seed(SEED), now=NOW, models={}, hyper=None)
    for v in ("turns.coder", "soft.agent.coder", "hard.agent.coder"):
        b = doc["vars"][v]["b"]
        assert len(b["y"]) == 12
        assert b["cens"] == [0] * 6 + [0, 0, 0, 1, 1, 1], (v, b)  # sorted by ts: R, then S window 1, window 2
        assert b["resume"] == [0] * 12 and b["sess"] == [0] * 6 + [1] * 6


# ---------------------------------------------------------------- S1, S2 shadow
def test_S1_shadow_changes_no_value_record_or_snapshot_value(tmp_path, monkeypatch):
    out = {}
    for mode in ("off", "shadow"):
        root = tmp_path / mode / "claude-agent-stack"
        (root / "limits").mkdir(parents=True)
        monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / mode))
        monkeypatch.setenv("STACK_BAYES", mode)
        eid = "f" * 64
        setup_apply(root, eid, doc=bayes_doc(eid, coder_blocks()), upto=T0)
        path, notice = start("s-s1")
        live = json.loads(lim(root, "live.json").read_text())
        recs = hist(root)
        out[mode] = {"values": {v: s["value"] for v, s in live["vars"].items()},
                     "snap": {k: json.loads(Path(path).read_text())[k] for k in ("values", "origin")},
                     # section 4 records; the "seeded" line (var "*") carries the wall clock, not `now`
                     "sec4": [r for r in recs if r.get("method") != "bayes-shadow" and r.get("var") != "*"], "shadow": [
                         r for r in recs if r.get("method") == "bayes-shadow"], "notice": notice}
    assert L._dumps(out["shadow"]["values"]) == L._dumps(out["off"]["values"])
    assert L._dumps(out["shadow"]["snap"]) == L._dumps(out["off"]["snap"])
    assert L._dumps(out["shadow"]["sec4"]) == L._dumps(out["off"]["sec4"])
    assert out["shadow"]["notice"] == out["off"]["notice"]
    # the test has power: some shadow decision would set another value than section 4 did
    sec4 = {r["var"]: r["new"] for r in out["off"]["sec4"] if r.get("var") != "*"}
    assert any(r["would"] != sec4.get(r["var"]) for r in out["shadow"]["shadow"])


def test_S2_one_shadow_record_per_variable_with_a_block_and_none_when_off(st, monkeypatch):
    eid = setup_apply(st, blocks=coder_blocks())
    path, _ = start("s-s2")
    sh = [r for r in hist(st) if r.get("method") == "bayes-shadow"]
    assert sorted(r["var"] for r in sh) == sorted(coder_blocks())
    for r in sh:
        assert r["applied"] is False and r["fit_id"] == FIT and r["tier"] == "nuts" and r["decision"]
        assert "would" in r and "T" in r and "p_hit_c" in r and r["live_version"] == 2
    live = json.loads(lim(st, "live.json").read_text())
    assert live["vars"]["soft.agent.coder"]["bayes"]["T"] == coder_blocks()["soft.agent.coder"]["T"]
    assert live["vars"]["soft.agent.coder"]["method"] == "empirical"
    # off: no record, bayes.json never read
    monkeypatch.setenv("STACK_BAYES", "off")
    monkeypatch.setattr(L, "bayes_context", lambda *a: pytest.fail("bayes.json read while off"))
    n = len(hist(st))
    setup_apply(st, blocks=coder_blocks())
    p2, _ = start("s-s2-off")
    new = hist(st)[n:]
    assert new and not [r for r in new if r.get("method") == "bayes-shadow"]
    assert json.loads(Path(p2).read_text())["prov"] == {"bayes_mode": "off", "fit_id": None, "vars": {}}
    assert eid


# ---------------------------------------------------------------- Q1, modes, rollback drill
def test_Q1_bayes_live_holds_no_deny_type_family():
    assert L.BAYES_LIVE <= {"soft.agent", "soft.prompt", "soft.session"}
    assert not L.BAYES_LIVE & {"turns", "hard.agent", "hard.prompt", "hard.session"}
    assert L.BAYES_GRID_LIVE <= L.BAYES_LIVE
    assert L.BAYES_LIVE == frozenset() and L.BAYES_GRID_LIVE == frozenset()       # WP3a: the user's step (WP6)
    assert set(L.RISK) == {"soft.agent", "soft.prompt", "soft.session", "turns", "hard.agent", "hard.prompt",
                           "hard.session"}
    assert "STACK_BAYES" in L.FIXED_GUARDS and L.is_fixed_guard("STACK_BAYES") and L.is_fixed_guard("stack-bayes")
    for t in TYPES:                                               # no variable is a fixed-guard name
        assert not any(L.is_fixed_guard(f"{fam}.{t}") for fam in L.TYPE_FAMILIES)


def test_bayes_mode_parsing(monkeypatch, st):
    monkeypatch.delenv("STACK_BAYES", raising=False)
    assert L.bayes_mode() == "shadow"
    for raw, want in (("off", "off"), (" ON ", "on"), ("Shadow", "shadow"), ("yes", "shadow"), ("", "shadow")):
        monkeypatch.setenv("STACK_BAYES", raw)
        assert L.bayes_mode() == want, raw


def test_rollback_drill_off_makes_the_next_session_empirical(st, monkeypatch):
    monkeypatch.setattr(L, "BAYES_LIVE", frozenset({"soft.agent"}))
    monkeypatch.setenv("STACK_BAYES", "on")
    setup_apply(st, blocks=coder_blocks())
    start("s-on")
    live = json.loads(lim(st, "live.json").read_text())
    assert live["vars"]["soft.agent.coder"]["method"] == "bayes-nuts"
    on_value = live["vars"]["soft.agent.coder"]["value"]
    monkeypatch.setenv("STACK_BAYES", "off")                     # the rollback: no command
    setup_apply(st, blocks=coder_blocks())
    path, _ = start("s-after")
    live = json.loads(lim(st, "live.json").read_text())
    recs = [r for r in hist(st) if r.get("session") == "s-after"]
    assert recs and {r["method"] for r in recs} == {"empirical"}
    assert live["vars"]["soft.agent.coder"]["method"] == "empirical" and live["vars"]["soft.agent.coder"]["bayes"] is None
    assert json.loads(Path(path).read_text())["prov"]["bayes_mode"] == "off"
    assert on_value


# ---------------------------------------------------------------- the fixture, main d6046693
def test_the_fixture_matches_its_sha256sums():
    """The frozen B1 v2 data is byte-pinned (tests/lint_agents.py exempts its model IDs for that reason):
    SHA256SUMS lists every file of it and each one matches."""
    want = dict(reversed(line.split("  ", 1)) for line in (FIX / "SHA256SUMS").read_text(encoding="utf-8").splitlines())
    have = {p.relative_to(FIX).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in FIX.rglob("*")
            if p.is_file() and p.name != "SHA256SUMS" and not p.name.startswith(".")}
    assert have == want


def fixture_props(mod=None, hyper=L._UNSET):
    """build_proposals over the fixture rows (main's module: mod); hyper as build_proposals' (default: read
    limits/bayes.json of the test's state through load_hyper)."""
    mod = mod or L
    paths = [str(FIX / "runs.csv"), str(FIX / "runs3.csv")]
    kw = {} if mod is not L else {"hyper": hyper}
    return mod.build_proposals(mod.load_seed(), paths, regime=FIX_REGIME, live=mod.live_from_seed(mod.load_seed()),
                               now=NOW, models=mod.agent_models(str(AGENTS_DIR)), **kw)


def main_module(tmp_path):
    """stack_limits.py of main d6046693 beside its seed and scheduler model (git show), loaded as its own
    module."""
    d = tmp_path / "main_hooks"
    d.mkdir(exist_ok=True)
    for rel in ("stack_limits.py", "stack_limits_seed.json", "sched_model.json"):
        p = subprocess.run(["git", "-C", str(ROOT), "show", f"{MAIN_REV}:dot-config/dot-claude/hooks/{rel}"],
                           capture_output=True, check=False)
        if p.returncode != 0:
            pytest.skip(f"main {MAIN_REV} not in this checkout")
        (d / rel).write_bytes(p.stdout)
    return _load("stack_limits_main_" + MAIN_REV, d / "stack_limits.py")


def fixture_bayes(props, seed=SEED):
    """A gated bayes.json for the fixture's evidence: nuts blocks for every turns.* and hard.agent.* entry
    and half of the soft.agent.* ones (the rest use the proposals' grid blocks), from the v2 hyperparameters
    (log-normal predictive tables; synthetic, not a fit)."""
    hy = v2_hyper(seed)
    out = {}
    for i, v in enumerate(sorted(props["vars"])):
        fam, t = L.split_var(v)
        if fam not in L.BAYES_FAMILIES or (fam == "soft.agent" and i % 2):
            continue
        h = hy["turns" if fam == "turns" else "ctx"]
        tp = h["types"].get(t)
        if not tp:
            continue
        r = L.RISK[fam]
        s = math.sqrt((0.8 if fam == "turns" else tp["scale"]) ** 2 + h["tau_new"] ** 2)
        if fam == "turns":
            qx = [math.ceil(1 + math.exp(tp["mu"] + G.nppf(p) * s)) for p in L.QTAB_P]
            T = math.ceil(1 + math.exp(tp["mu"] + G.nppf(1 - r) * s))
        else:
            qx = [math.exp(tp["mu"] + G.nppf(p) * s) for p in L.QTAB_P]
            T = L.ceil2(math.exp(tp["mu"] + G.nppf(1 - r) * s))
        if qx[-1] > (L.TURNS_MAX if fam == "turns" else L.CTX_MAX):
            continue
        out[v] = block(v, T, qtab={"p": list(L.QTAB_P), "x": qx}, pi90=[T * 0.6, T * 1.7])
    return bayes_doc(props["evidence_id"], out, hyper=hy, seed=seed)


def _run_fixture(mod, state, monkeypatch, props, mode=None, bdoc=None, live_src="fixture"):
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    if mode is None:
        monkeypatch.delenv("STACK_BAYES", raising=False)
    else:
        monkeypatch.setenv("STACK_BAYES", mode)
    ld = state / "claude-agent-stack" / "limits"
    ld.mkdir(parents=True)
    if live_src == "fixture":                                     # else: created from the seed by the apply
        shutil.copyfile(FIX / "state" / "live.json", ld / "live.json")
    (ld / "proposals.json").write_text(mod._dumps(props))
    if bdoc is not None:
        (ld / "bayes.json").write_text(json.dumps(bdoc))
    path, notice = mod.apply_and_snapshot({"session_id": "s-fixture", "source": "startup"}, spawn=False, now=NOW)
    live = json.loads((ld / "live.json").read_text())
    recs = [json.loads(x) for x in (ld / "history.jsonl").read_text().splitlines()]
    recs = [r for r in recs if r.get("var") != "*"]               # "seeded": the wall clock, not `now`
    return {"live": live, "snap": json.loads(Path(path).read_text()), "recs": recs, "notice": notice}


@pytest.mark.parametrize("live_src", ["fixture", "seed"])
def test_shadow_and_off_equal_main_on_the_fixture_byte_for_byte(tmp_path, monkeypatch, capsys, live_src):
    """The hard property of WP3a: with STACK_BAYES unset (shadow, a gated bayes.json present) or off, the
    learned values, every section 4 decision record and the snapshot values/origin equal main d6046693's on
    the frozen fixture (its 2026-10-03 schema-1 live.json and rows), byte for byte after removing the keys
    the contract adds (states' bayes/method, records' method, the snapshot's prov)."""
    M = main_module(tmp_path)
    for k in [k for k in os.environ if k.startswith("STACK_")]:
        monkeypatch.delenv(k)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "props"))
    p_main = fixture_props(mod=M)
    p_new = fixture_props(hyper=(dict(v2_hyper(), breach=[]), "fit:" + FIT))
    assert p_main["evidence_id"] == "ce024a79b30f6986c3866d866963e27babc801ea58595de5005d2db7add65ef5"
    assert L._dumps(_strip_props(p_new)) == M._dumps(p_main)
    bdoc = fixture_bayes(p_new)
    runs = {"main": _run_fixture(M, tmp_path / "m", monkeypatch, p_main, live_src=live_src),
            "off": _run_fixture(L, tmp_path / "o", monkeypatch, p_new, "off", bdoc, live_src),
            "shadow": _run_fixture(L, tmp_path / "s", monkeypatch, p_new, None, bdoc, live_src)}
    sh = [r for r in runs["shadow"]["recs"] if r.get("method") == "bayes-shadow"]
    assert len(sh) >= 15 and {r["tier"] for r in sh} == {"nuts", "grid"}
    assert runs["shadow"]["live"]["schema_version"] == 2 and runs["main"]["live"]["schema_version"] == 1
    if live_src == "seed":                                        # here section 4 moves values: the test has power
        assert any(r.get("new") != r.get("old") for r in runs["main"]["recs"])

    def live_view(lv):
        return {"top": {k: v for k, v in lv.items() if k not in ("vars", "schema_version")},
                "vars": {v: {k: x for k, x in s.items() if k not in ("bayes", "method")} for v, s in lv["vars"].items()}}

    def recs_view(rs):
        return [{k: x for k, x in r.items() if k != "method"} for r in rs if r.get("method") != "bayes-shadow"]


    base = runs["main"]
    for name in ("off", "shadow"):
        run = runs[name]
        assert L._dumps(live_view(run["live"])) == L._dumps(live_view(base["live"])), name
        assert L._dumps(recs_view(run["recs"])) == L._dumps(recs_view(base["recs"])), name
        for k in ("values", "origin"):
            assert L._dumps(run["snap"][k]) == L._dumps(base["snap"][k]), (name, k)
        assert run["notice"] == base["notice"], name
    moved = sum(1 for r in recs_view(base["recs"]) if r.get("new") != r.get("old"))
    print(f"fixture ({live_src} live): {len(recs_view(base['recs']))} section-4 records ({moved} changes), "
          f"{len(sh)} shadow records; off and shadow byte-equal to main {MAIN_REV}")


def test_cli_views_print_method_T_pi90_p_hit_and_would(st, capsys):
    setup_apply(st, blocks=coder_blocks())
    start("s-cli")
    out = L.show("soft.agent.coder")
    assert "bayes shadow" in out.splitlines()[0] and "fit " + FIT in out.splitlines()[0]
    line = [x for x in out.splitlines() if x.startswith("soft.agent.coder")][0]
    assert "bayes-shadow T 31M [21.7M-43.4M] p_hit" in line, line
    js = json.loads(L.show("soft.agent.coder", as_json=True))["vars"]["soft.agent.coder"]
    assert js["method"] == "empirical" and js["bayes"]["T"] == 31000000 and js["bayes"]["tier"] == "nuts"
    assert 0 <= js["bayes"]["p_hit"] <= 1
    assert "bayes shadow (9 with a block)" in L.status_line()
    assert any("method: empirical" in x for x in L.stability_lines())
    assert any(r.get("method") == "bayes-shadow" for r in L.history("soft.agent.coder"))
    setup_apply(st, blocks=coder_blocks())
    dr = L.dry_run()
    assert "bayes shadow, 9 shadow" in dr[0] and any(" would " in x for x in dr[1:])


def test_B1_T14_backtest_script_runs_on_the_fixture(tmp_path):
    """tests/b1_backtest.py (the verifier's B1-T14, WP5) runs on the fixture under the hook interpreter and
    writes its summary; the fixture has too few sessions for the 3-fold rule, so its verdict is REJECT."""
    out = tmp_path / "bt.json"
    p = subprocess.run([PY, str(ROOT / "tests" / "b1_backtest.py"), "--sims", "200", "--strata", "ntrain",
                        "--min-train-sessions", "1", "--out", str(out)], capture_output=True, text=True, timeout=300,
                       env=dict(os.environ, B1_REPO=str(ROOT), PYTHONDONTWRITEBYTECODE="1"))
    assert p.returncode in (0, 1), p.stderr
    doc = json.loads(out.read_text())
    assert set(doc["families"]) == {"soft.agent", "hard.agent", "turns"} and len(doc["folds"]) == 3
    sa = doc["families"]["soft.agent"]
    assert sa["supported"]["n"] > 0 and sa["checks"]["folds"] is False and p.returncode == 1


# ---------------------------------------------------------------- review fixes (S7)
def test_B1_T3_adjacent_float_qtab_around_c_never_aborts_the_apply(st):
    c = SEED["vars"]["soft.agent.coder"]["seed"]
    lo, hi = math.nextafter(c, 0), math.nextafter(c, math.inf)
    assert L.p_hit({"p": list(L.QTAB_P), "x": [lo] + [hi] * 7}, c) == pytest.approx(0.5)
    blocks = coder_blocks()
    blocks["soft.agent.coder"]["qtab"]["x"] = [lo] + [hi] * 7
    setup_apply(st, blocks=blocks)
    lim(st, "live.json").write_text(json.dumps(L.live_from_seed(SEED)))
    path, notice = start("s-adjacent")
    assert "error" not in (notice or ""), notice
    assert "fallback" not in json.loads(Path(path).read_text())["origin"].values()
    assert any(r.get("method") == "bayes-shadow" for r in hist(st))


@pytest.mark.parametrize("mode", ["shadow", "on"])
def test_a_raising_decide_bayes_leaves_section_4_and_no_fallback(st, monkeypatch, mode):
    """Any exception inside decide_bayes (shadow, or a family acting live) costs that variable's Bayes
    decision only: section 4 decides, values equal a run without bayes.json, no seed-fallback snapshot."""
    def boom(*a, **k):
        raise RuntimeError("decide_bayes failed")
    monkeypatch.setattr(L, "decide_bayes", boom)
    if mode == "on":
        monkeypatch.setattr(L, "BAYES_LIVE", frozenset({"soft.agent"}))
    monkeypatch.setenv("STACK_BAYES", mode)
    eid = setup_apply(st, blocks=coder_blocks())
    path, notice = start("s-raise-" + mode)
    snap = json.loads(Path(path).read_text())
    assert "error" not in (notice or ""), notice
    assert "fallback" not in snap["origin"].values()
    assert snap["values"] == _values_without_bayes(st, eid)
    recs = [r for r in hist(st) if r.get("var") != "*"]
    assert recs and {r["method"] for r in recs} == {"empirical"}
    assert "RuntimeError" in lim(st, "limits.log").read_text()


def test_grid_module_loads_by_path_only(st, tmp_path, monkeypatch):
    """stack_bayes_grid is loaded from the hooks folder (HERE) only: with the file absent there, a planted
    stack_bayes_grid.py on sys.path is never imported, no grid block is built and limits.log says so once."""
    empty, planted = tmp_path / "hooks-empty", tmp_path / "planted"
    empty.mkdir()
    planted.mkdir()
    marker = tmp_path / "planted-imported"
    (planted / "stack_bayes_grid.py").write_text(f"open({str(marker)!r}, 'w').close()\n")
    monkeypatch.syspath_prepend(str(planted))
    monkeypatch.delitem(sys.modules, "stack_bayes_grid", raising=False)
    monkeypatch.setattr(L, "HERE", str(empty))
    monkeypatch.setattr(L, "_GRID", {}, raising=False)
    p = fixture_props(hyper=(dict(v2_hyper(), breach=[]), "fit:" + FIT))
    assert not marker.exists()                                    # the planted module never ran
    assert "stack_bayes_grid" not in sys.modules
    assert not any("bayes" in e for e in p["vars"].values())
    log = lim(st, "limits.log").read_text().splitlines()
    assert len([x for x in log if "stack_bayes_grid" in x]) == 1, log


def test_scan_rejects_an_oversized_container_before_walking_it():
    class Boom(list):
        def __iter__(self):
            raise AssertionError("walked an oversized list")
    with pytest.raises(L._BayesInvalid):
        L._scan({"schema_version": 1, "code": "stack_bayes/1", "x": Boom([0] * 50001)})


def test_deeply_nested_proposals_json_is_unreadable_not_an_exception(st):
    lim(st, "proposals.json").write_text("[" * 100000 + "]" * 100000)
    props, why = L.load_proposals(SEED)
    assert props is None and "RecursionError" in why


def test_hard_agent_T_is_the_blocks():
    spec = SEED["vars"]["hard.agent.coder"]
    blk = L._valid_block(block("hard.agent.coder", 30000000), "ctx")
    e = norm_ent(ent([2e7 * (1 + 0.05 * i) for i in range(12)]))
    _s, rec = L.decide_bayes("hard.agent.coder", spec, L._var_state(40000000), blk, e, None, 25000000, NOW)
    assert rec["T"] == 30000000
