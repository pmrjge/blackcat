"""Tests of tests/derive_sched_model.py's pure fit() on synthetic segments (no transcripts).

Run: uv run --with pytest --with pandas --with numpy pytest -q tests/test_derive_sched_model.py
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import derive_sched_model as D  # noqa: E402

FM = {t: {"model": "sonnet", "maxTurns": 40, "cacheTtl": "5m"}
      for t in ("scout", "claude-code-guide", "oracle", "explore", "mcp-broker")}
SOFT = {t: 450000 for t in FM}


def agents(atype, n_agents, segs=1, seed=1, calls=40.0, session="s1"):
    """Synthetic healthy segments: api_calls ~ lognormal around `calls`, ctx = a*n + b*n^2 with noise."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n_agents):
        for k in range(segs):
            n = max(1, int(round(calls * rng.lognormal(0, 0.5))))
            rows.append(dict(session=session, id=f"{atype}-{seed}-{i}", type=atype, seg=k, api_calls=n,
                             ctx=float((20000 * n + 800 * n * n) * rng.lognormal(0, 0.2)),
                             first_cc=float(18000 * rng.lognormal(0, 0.1)),
                             wall_s=float(n * 9 * rng.lognormal(0, 0.4))))
    return pd.DataFrame(rows)


def pool_rows():
    return agents("claude-code-guide", 12, seed=7, calls=20.0)


def width(b):
    return (b["hi"] - b["lo"]) / b["med"]


def test_provisional_to_supported_switch():
    base = pool_rows()
    J = D.fit(pd.concat([base, agents("scout", 4)]), FM, SOFT, B=300)
    assert J["types"]["scout"]["status"] == "provisional"
    assert J["types"]["scout"]["band"]["method"] == "pool-prior"
    assert J["types"]["scout"]["source"] == "pool:lookup"
    J = D.fit(pd.concat([base, agents("scout", 5)]), FM, SOFT, B=300)
    assert J["types"]["scout"]["status"] == "supported"
    assert J["types"]["scout"]["band"]["method"] == "bootstrap"
    assert J["types"]["scout"]["source"] == "own"
    # 6 segments but only 2 agents: still provisional
    J = D.fit(pd.concat([base, agents("scout", 2, segs=3)]), FM, SOFT, B=300)
    assert J["types"]["scout"]["status"] == "provisional"


def replicate(df, k):
    """k copies of the agents in df under new ids: the same spread, k times the agents."""
    return pd.concat([df.assign(id=df.id + f"-r{i}") for i in range(k)], ignore_index=True)


@pytest.mark.parametrize("seed", [3, 4, 11])
def test_band_narrows_as_n_grows(seed):
    base = pool_rows()
    five = agents("scout", 5, seed=seed)
    widths = []
    for k in (1, 4, 24):                      # 5, 20, 120 agents with the same spread
        b = D.fit(pd.concat([base, replicate(five, k)]), FM, SOFT, B=1000)["types"]["scout"]["band"]
        widths.append({q: width(b[q]) for q in ("turns", "sec_per_call", "ctx")})
    for q in ("turns", "sec_per_call", "ctx"):
        assert widths[2][q] < widths[1][q] < widths[0][q], (q, widths)


def test_provisional_band_never_narrower_than_pool():
    J = D.fit(pd.concat([pool_rows(), agents("scout", 2, segs=2, seed=5, calls=60.0)]), FM, SOFT, B=1000)
    pool = J["pools"]["lookup"]["band"]
    for t in ("scout", "oracle"):          # provisional with data; unobserved
        b = J["types"][t]["band"]
        assert J["types"][t]["status"] == "provisional"
        for q in ("turns", "sec_per_call", "ctx"):
            assert b[q]["hi"] / b[q]["med"] >= pool[q]["hi"] / pool[q]["med"] - 1e-3, (t, q)
            assert b[q]["lo"] / b[q]["med"] <= pool[q]["lo"] / pool[q]["med"] + 1e-3, (t, q)
            assert b[q]["lo"] <= b[q]["med"] <= b[q]["hi"]
    assert J["types"]["oracle"]["band"] == pool | {"method": "pool-prior"}


def test_deterministic_apart_from_generated():
    seg = pd.concat([pool_rows(), agents("scout", 6)])
    a, b = D.fit(seg, FM, SOFT, B=300), D.fit(seg, FM, SOFT, B=300)
    a.pop("generated"), b.pop("generated")
    assert a == b


def test_unknown_type_refused():
    with pytest.raises(ValueError):
        D.fit(pool_rows(), FM | {"no-such-agent": FM["scout"]}, SOFT, B=50)


# ---------------------------------------------------------------- S1e: resume ctx, fixer re-read, per-run intervals
FMB = FM | {t: {"model": "sonnet", "maxTurns": 60, "cacheTtl": "5m"} for t in ("coder", "claude-code-engineer")}
SOFTB = {t: 450000 for t in FMB}


def builders(n_agents=12, seed=21, alpha=6000.0, gamma=400.0, ramp=90000.0):
    """coder agents with one fresh segment and one resume each: resume ctx = n * (prior peak + alpha + gamma * n)
    (times a little noise); fresh segments carry first_ctx and ctx_at_first_write = first_ctx + ramp * noise."""
    rng = np.random.default_rng(seed)
    d = agents("coder", n_agents, segs=2, seed=seed, calls=30.0)
    d["prev_peak"] = np.nan
    d["first_ctx"] = np.nan
    d["ctx_at_first_write"] = np.nan
    for i in d.index:
        n = d.at[i, "api_calls"]
        if d.at[i, "seg"] == 0:
            d.at[i, "first_ctx"] = 25000.0
            d.at[i, "ctx_at_first_write"] = 25000.0 + ramp * rng.lognormal(0, 0.3)
        else:
            pk = float(150000 * rng.lognormal(0, 0.3))
            d.at[i, "prev_peak"] = pk
            d.at[i, "ctx"] = n * (pk + alpha + gamma * n) * rng.lognormal(0, 0.02)
    return d


def test_resume_ctx_recovers_alpha_and_gamma():
    J = D.fit(pd.concat([pool_rows(), builders()]), FMB, SOFTB, B=100, run_interval=False)
    rc = J["resume_ctx"]
    assert rc["n"] == 12 and rc["n_agents"] == 12
    # the noise is on ctx (2%), i.e. ~3000 tokens per call on ctx/n: alpha is loose, gamma tight
    assert rc["gamma"] == pytest.approx(400.0, rel=0.25) and 0 <= rc["alpha"] < 20000
    # below the support gate (5 resumes from 3 agents): null
    J = D.fit(pd.concat([pool_rows(), builders(n_agents=2)]), FMB, SOFTB, B=100, run_interval=False)
    assert J["resume_ctx"] is None
    # no prev_peak column at all: null, not an error
    assert D.fit(pool_rows(), FM, SOFT, B=50, run_interval=False)["resume_ctx"] is None


def test_fixer_is_the_median_ramp_with_an_order_statistic_interval():
    seg = pd.concat([pool_rows(), builders(ramp=90000.0)])
    J = D.fit(seg, FMB, SOFTB, B=100, run_interval=False)
    fx = J["fixer"]
    ramp = (seg.ctx_at_first_write - seg.first_ctx).dropna()
    assert fx["n"] == 12 and fx["reread"] == int(round(ramp.median()))
    assert fx["lo"] <= fx["reread"] <= fx["hi"] and fx["level"] == 0.95
    assert fx["lo"] in set(ramp.round().astype(int)) and fx["hi"] in set(ramp.round().astype(int))
    # lookup-tier first segments never enter the fixer; without the columns there is none
    assert D.fit(pool_rows(), FM, SOFT, B=50, run_interval=False)["fixer"] is None


def test_median_ci_and_conformal_order_statistics():
    x = np.arange(1, 15, dtype=float)                      # n = 14: the 95% interval is (x(3), x(12))
    med, lo, hi = D.median_ci(x[::-1])
    assert (med, lo, hi) == (7.5, 3.0, 12.0)
    assert D.median_ci(np.arange(5.0))[1:] == (None, None)  # n = 5 cannot reach 95%
    # 19 residuals, level 0.9: the 1st and 19th order statistics; 39: the 2nd and 38th ((1 - 0.9) / 2 * 40 is 1.999... in floats)
    assert D.conformal(np.arange(19.0)) == (0.0, 18.0)
    assert D.conformal(np.arange(39.0)) == (1.0, 37.0)


def test_run_interval_groups_and_coverage():
    seg = pd.concat([pool_rows(), agents("scout", 12, seed=9), builders(n_agents=14)])
    J = D.fit(seg, FMB, SOFTB, B=100)
    ri = J["run_interval"]
    assert ri["level"] == 0.9 and "pooled" in ri["groups"]
    assert set(ri["groups"]) <= {"pooled", "lookup:fresh", "builder:fresh", "builder:resume"}
    assert {"lookup:fresh", "builder:fresh", "builder:resume"} <= set(ri["groups"])
    for g, r in ri["groups"].items():
        for q in ("turns", "ctx", "wall"):
            if r[q]["n"]:
                assert r[q]["lo"] <= 1.0 <= r[q]["hi"], (g, q, r[q])
    # turns ~ lognormal(0, 0.5) around the type's median: the 90% factor is near exp(1.645 * 0.5) = 2.3
    assert 1.5 < ri["groups"]["lookup:fresh"]["turns"]["hi"] < 4.0
    # pure: the same inputs give the same file
    assert D.fit(seg, FMB, SOFTB, B=100, generated="x") == D.fit(seg, FMB, SOFTB, B=100, generated="x")


COLD = ("first_cr", "prev_peak", "gap_s", "cache_creation_input_tokens")


def arrow_types(df):
    """df with its type column as Arrow strings: pandas 3's default str once pyarrow is installed (nutpie needs it)."""
    pytest.importorskip("pyarrow")
    return df.assign(type=df.type.astype("string[pyarrow]"))


def test_no_resumes_under_arrow_strings_is_no_cold_calibration():
    """Regression: with the cold-resume columns but no resume, cold_resumes() compared gap_s with an empty Arrow
    string column (TypeError in fit(), stack_sched_refresh's B1-T13/T20 under the tools venv with nutpie)."""
    seg = arrow_types(pool_rows().assign(**{c: np.nan for c in COLD}))
    r = D.cold_resumes(D.prepare(seg), FM)
    assert len(r) == 0 and r.ttl_s.dtype.kind == "i" and r.over_ttl.dtype == bool
    J = D.fit(seg, FM, SOFT, B=50, run_interval=False)
    assert J["types"]["claude-code-guide"]["cold"]["frac"] is None


def test_cold_resume_ttl_follows_the_frontmatter_under_arrow_strings():
    fm = dict(FM, scout=dict(FM["scout"], cacheTtl="1h"))
    rows = [{"session": "s1", "id": f"{t}-{i}", "type": t, "seg": 1, "api_calls": 10, "ctx": 1e5, "first_cc": 1e4,
             "wall_s": 90.0, "first_cr": 100.0, "prev_peak": 5e4, "gap_s": gap, "cache_creation_input_tokens": 6e4}
            for i, (t, gap) in enumerate((("scout", 1000.0), ("scout", 4000.0), ("oracle", 1000.0), ("other", 200.0)))]
    r = D.cold_resumes(D.prepare(arrow_types(pd.DataFrame(rows))), fm)
    assert list(r.ttl_s) == [3600, 3600, 300, 300]                # 1h, 1h, 5m, no frontmatter: 5m
    assert list(r.over_ttl) == [False, True, True, False]
    assert r.cold.all() and list(r.frac) == pytest.approx([0.2] * 4)  # first_cc / min(cache_creation, prev_peak)
