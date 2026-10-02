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
