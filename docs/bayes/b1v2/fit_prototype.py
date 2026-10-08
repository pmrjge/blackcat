# /// script
# requires-python = ">=3.13,<3.14"
# dependencies = [
#   "pymc==6.3.2", "pytensor==3.3.3", "nutpie==0.16.11", "arviz==1.3.0",
#   "numpy==2.5.3", "scipy==1.18.1", "pandas==3.0.6",
# ]
# ///
"""fit_prototype.py - B1 prototype: Bayesian inference of the stack's learned values on a frozen data copy.

  cd .claude-work/agents-b0b3/b1
  PYTENSOR_FLAGS="base_compiledir=$TMPDIR/pytensor,cxx=,mode=NUMBA" UV_CACHE_DIR=$TMPDIR/uv-cache-b1 \
      uv run --script fit_prototype.py [--quick] [--no-backtest] [--no-scope2] [--data data] [--out out]

Reads only b1/data (copies with SHA256SUMS) and the repo's seed/agents (read-only: stack_limits.read_rows does
the hostile-CSV filter, the last-row-wins merge and the model-mismatch filter, exactly as the proposer).
Writes only b1/out. Fixed seeds; versions and the evidence id are recorded in out/run_meta.json.

Scope 1 (design.md section 3): hierarchical NUTS fits (type -> pool, model family, log maxTurns; session
effect; resume effect) for turns (shifted NB, censored), ctx (log-normal, censored), sec_per_call
(log-normal), static_cc (log-normal), tool_calls (shifted NB, censored), ctx(n) = a n + b n^2
(log-normal regression); the stdlib grid tier (bayes_grid.py) conditional on the NUTS hyperparameters and
on stdlib moment hyperparameters; seed-anchored grids for the prompt and session scopes; the section 4
empirical estimator side by side; a rolling-origin (session-start) held-out calibration check.
Scope 2: ordinal (fail < partial < pass) model of grades by agent type x task family, provisional.
"""
import argparse
import hashlib
import json
import math
import os
import sys
import time

os.environ.setdefault("PYTENSOR_FLAGS", "base_compiledir=%s/pytensor,cxx=,mode=NUMBA" % os.environ.get("TMPDIR", "/tmp"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pymc as pm  # noqa: E402
import pytensor.tensor as pt  # noqa: E402
import arviz as az  # noqa: E402
import xarray as xr  # noqa: E402
from scipy import stats as sst  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
# The repo whose stack_limits / seed / agents the fit reads (read-only). v1 ran from W/.claude-work/agents-b0b3/b1,
# where HERE/../../.. was the worktree W. v2 runs from M/.claude-work/step6-data/b1, where that path reaches the main
# checkout, whose stack_limits_seed.json and stack_limits.py differ from W's. To keep v1's seed, read_rows and
# evidence id, v2 pins W through B1_REPO (default W when it exists).
_W = ""  # absolute worktree path scrubbed for publication (WP0a)
REPO = os.path.abspath(os.environ.get("B1_REPO") or (_W if os.path.isdir(_W) else os.path.join(HERE, "..", "..", "..")))
sys.path[:0] = [os.path.join(REPO, "dot-config", "dot-claude", "hooks"), HERE]
import stack_limits as L  # noqa: E402  (stdlib, read-only use)
import bayes_grid as G  # noqa: E402

SEED = 20261003
CHAINS = 4
TARGET_ACCEPT = 0.98
# cap-hit risk targets per family (design.md section 5.1): P(new run's demand > limit). v2: user decision
# 2026-10-03 (settled): soft 10 %, turns 2 %, hard 1 % (v1 ran 5 % / 1 % / 0.5 %).
RISK = {"soft.agent": 0.10, "hard.agent": 0.01, "turns": 0.02, "soft.prompt": 0.10, "hard.prompt": 0.01,
        "soft.session": 0.10, "hard.session": 0.01}
CODE_VERSION = "b1-prototype/2"
# Per-model parameterization (design.md 3.3, v2): rich = row threshold for a centered type deviation (10**9: every
# type non-centered), rich_pairs = threshold for a centered type x session deviation (None: all non-centered),
# zero_avoid = group scales with the boundary-avoiding Gamma(2, 2/m) prior (same mean m as v1's HalfNormal; _scale).
# History (fit_report "Diagnostics", out_v2_attempt1/2):
#  attempt 1: turns, tool_calls fully non-centered (v1 divergences sat at tau_t -> 0, the funnel neck of the
#             centered deviations of the >= 20-row types); ctx(n) reparameterized (ctx_ab). Full run: turns 2 and
#             ctx 1 divergences at the session scales.
#  attempt 2: + Gamma(2, .) on tau_s, tau_ts (1-4 sessions cannot keep them off 0). Full run: ctx 1 divergence at
#             tau_t (its centered rich types), all others clean.
#  attempt 3: turns and ctx: every type non-centered + Gamma(2, .) on tau_t as well (37 observed types whose medians
#             differ by > 10x: tau_t = 0 is implausible a priori). tool_calls stays at attempt 2 (adding tau_t gave a
#             divergence on its run seed in probes).
PARAM = {"turns": {"rich": 10 ** 9, "rich_pairs": 20, "zero_avoid": ("tau_t", "tau_s", "tau_ts")},
         "ctx": {"rich": 10 ** 9, "zero_avoid": ("tau_t", "tau_s", "tau_ts")},
         "tool_calls": {"rich": 10 ** 9, "zero_avoid": ("tau_s", "tau_ts")}}
DRAWS, TUNE = 3000, 2000     # v1: 2000 / 1500; more draws shrink the Monte Carlo noise of R-hat near the 1.01 gate
GATE = {"rhat": 1.01, "ess": 400, "div": 0, "ebfmi": 0.3, "edge": 1e-3}
PIN = {"soft.prompt.orchestrator": 80000000}          # user-pinned hard floors (seed = floor)


# ============================================================================ data
def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def load(data_dir):
    seed = L.load_seed()
    types = L._types(seed)
    models = L.agent_models(os.path.join(REPO, "dot-config", "dot-claude", "agents"))
    paths = [os.path.join(data_dir, "runs.csv"), os.path.join(data_dir, "runs3.csv")]
    rows, stats = L.read_rows(paths, known=set(types), models=models)
    eid = L.evidence_id(rows)
    d = pd.DataFrame(rows)
    raw = pd.concat([pd.read_csv(p, low_memory=False, dtype={"session": str, "id": str}) for p in paths],
                    ignore_index=True)
    raw = raw.drop_duplicates(["session", "id", "seg"], keep="last")
    keep = ["session", "id", "seg", "first_ts", "wall_s", "first_cc", "tool_calls", "first_ctx",
            "ctx_at_first_write", "prev_peak", "gap_s", "schema_version"]
    d = d.merge(raw[keep], on=["session", "id", "seg"], how="left")
    meta = {"evidence_id": eid, "read_rows_stats": stats,
            "files": {os.path.basename(p): sha256(p) for p in paths}}
    return seed, types, models, d, meta


NEAR = 0.5          # status_code 1 with unmeasured hit columns: censored when x >= NEAR x the per-agent limit


def censor_flags(df, seed, mode="near"):
    """{family: bool array}, True = the row's value is a lower bound (design.md section 3.2).
    Always censored: status != complete (open or truncated), compacted, turn_limited, any measured hit_*
    (a stop is a stop, whatever scope fired). status_code 2 (blocked) is an environment stop: observed.
    status_code 1 (partial) when every hit_* cell is empty (unmeasured, U1): mode "near" censors it only for a
    family whose per-agent limit in force (the seed: turns = frontmatter maxTurns, soft.agent) it reached
    within NEAR; "all" censors it everywhere, "none" nowhere (sensitivity)."""
    f = lambda c: df[c].fillna(0).astype(float) == 1  # noqa: E731
    hits = ["hit_soft", "hit_turn", "hit_hard_agent", "hit_hard_prompt", "hit_hard_session"]
    base = (df.status != "complete") | f("compacted") | f("turn_limited") \
        | ((df.schema_version.astype(float) == 3) & df.status_code.isna())   # ended on a tool_use: truncated
    for h in hits:
        base = base | f(h)
    unmeasured = df[hits].isna().all(axis=1)
    p1 = (df.status_code == 1) & unmeasured
    out = {}
    for fam, col, var in (("turns", "api_calls", "turns."), ("ctx", "ctx", "soft.agent.")):
        lim = np.array([float(seed["vars"].get(var + t, {}).get("seed") or np.inf) for t in df.type])
        if mode == "all":
            extra = p1
        elif mode == "none":
            extra = p1 & False
        else:
            extra = p1 & (df[col].astype(float).values >= NEAR * lim)
        out[fam] = (base | extra).values
    return out


def agent_frame(d, seed, mode="near"):
    a = d[d.scope == "agent"].copy()
    a = a[a.type.isin(L._types(seed))]
    cf = censor_flags(a, seed, mode)
    a["cens_turns"], a["cens_ctx"] = cf["turns"], cf["ctx"]
    a["cens"] = a.cens_turns
    a["resume"] = (a.seg > 0).astype(int)
    a = a[(a.api_calls.fillna(0) > 0)]
    return a.reset_index(drop=True)


def window_cap(a):
    """The proposer's evidence window (last 20 sessions). The section 4 per-type session cap (<= 50 % of a
    sample from one session) is NOT applied: it drops every single-session type outright (scout: 12 rows) and
    the session random effect models the clustering it guarded against (design.md section 3.4)."""
    return pd.DataFrame(L._window(a.to_dict("records")))


def with_cens(df, fam):
    """The frame with `cens` set to the family's censoring column (turns -> cens_turns, ctx -> cens_ctx)."""
    out = df.copy()
    out["cens"] = out["cens_" + fam]
    return out


class Index:
    def __init__(self, seed, models, sessions):
        self.types = L._types(seed)
        self.pool_of = L._pool_of(seed)
        self.pools = sorted(seed["pools"])
        self.fams = ["opus", "sonnet"]
        self.fam_of = {t: (L.model_family(models.get(t)) or "opus") for t in self.types}
        for t, f in self.fam_of.items():
            if f not in self.fams:
                self.fams.append(f)
        self.sessions = list(sessions)
        mt = np.array([seed["vars"]["turns." + t]["ceiling"] for t in self.types], float)
        self.zmt = np.log(mt) - np.log(mt).mean()
        self.t_pool = np.array([self.pools.index(self.pool_of[t]) for t in self.types])
        # a pool effect only for pools with >= 2 member types: a one-type pool's effect is not identified apart
        # from its type's (coordinator = orchestrator, verifier = verifier); those types shrink to the global level
        size = {p: sum(1 for t in self.types if self.pool_of[t] == p) for p in self.pools}
        self.peff = [p for p in self.pools if size[p] >= 2]
        self.t_peff = np.array([self.peff.index(self.pool_of[t]) if self.pool_of[t] in self.peff else len(self.peff)
                                for t in self.types])
        self.t_fam = np.array([self.fams.index(self.fam_of[t]) for t in self.types])

    def ti(self, s):
        return np.array([self.types.index(t) for t in s])

    def si(self, s):
        return np.array([self.sessions.index(x) for x in s])


# ============================================================================ hierarchical models
RICH = 20           # a type with >= RICH rows gets a centered deviation (non-centered below: Betancourt & Girolami)


def _devs(name, tau, counts, ix, thr=None):
    """Type deviations with scale tau: centered for types with >= thr rows (default RICH), non-centered otherwise."""
    n_t = np.array([(counts or {}).get(t, 0) for t in ix.types])
    thr = RICH if thr is None else thr
    rich, poor = np.where(n_t >= thr)[0], np.where(n_t < thr)[0]
    dev = pt.zeros(len(ix.types))
    if len(rich):
        dev = pt.set_subtensor(dev[rich], pm.Normal("dev_rich_" + name, 0, tau, shape=len(rich)))
    if len(poor):
        dev = pt.set_subtensor(dev[poor], tau * pm.Normal("z_poor_" + name, 0, 1, shape=len(poor)))
    return dev


def _scale(name, sd, zero_avoid=()):
    """Group-level scale: HalfNormal(sd), or for names in zero_avoid a boundary-avoiding Gamma(2, 2 / m) with the
    same mean m = sd sqrt(2 / pi) (Chung et al. 2013): density 0 at 0, so the sampler cannot wander into the
    funnel neck tau -> 0 when the data barely identify the scale (tool_calls: 2 sessions, design.md 3.3)."""
    if name in zero_avoid:
        m = sd * math.sqrt(2 / math.pi)
        return pm.Gamma(name, alpha=2.0, beta=2.0 / m)
    return pm.HalfNormal(name, sd)


def _type_effects(ix, center, sd_center=1.5, cov=True, counts=None, rich=None, zero_avoid=()):
    a0 = pm.Normal("a0", center, sd_center)
    b_fam = pm.ZeroSumNormal("b_fam", 0.5, dims="fam")
    g = pm.Normal("g", 0.5, 0.5) if cov else 0.0
    # pool effects with a fixed prior scale: a scale estimated from 4 pools mixes badly and says little
    u_p = pm.ZeroSumNormal("u_p", 0.7, dims="peff")       # sum-to-zero: a0 stays identified
    zp_full = pt.concatenate([u_p, pt.zeros(1)])
    tau_t = _scale("tau_t", 0.7, zero_avoid)
    dev = _devs("t", tau_t, counts, ix, RICH if rich is None else rich)
    eta = pm.Deterministic("eta_type", a0 + b_fam[ix.t_fam] + g * ix.zmt + zp_full[ix.t_peff] + dev, dims="type")
    return eta


def fit_hier(df, ycol, kind, ix, center, draws=1000, tune=1000, seed=SEED, cov=True, sess=True, resume=True,
             ccol="cens", prior_only=False, type_scale=True, rich=None, rich_pairs=None, zero_avoid=()):
    """rich / rich_pairs: row-count threshold for a centered type / type x session deviation (None: RICH for
    types, no centered pair); a parameterization choice made per model from the diagnostics (fit_report).
    zero_avoid: names of group scales given the boundary-avoiding Gamma(2, .) prior (_scale).
    kind 'nb': y - 1 ~ NB2(exp(lin), alpha_t); 'ln': log y ~ N(lin, sigma_t); 'gamma': y ~ Gamma(k_t, k_t / exp(lin)).
    Censored rows (df[ccol]) contribute log P(Y >= y). Returns (DataTree, diagnostics dict)."""
    y = df[ycol].values.astype(float)
    cens = df[ccol].values.astype(bool) if ccol in df else np.zeros(len(df), bool)
    if kind == "nb":
        cens = cens & (y > 1)                       # a lower bound of 1 carries no information
    t_i, s_i = ix.ti(df.type), ix.si(df.session)
    r_i = df.resume.values.astype(float)
    pairs, pr_i = pair_index(df, ix)
    coords = {"type": ix.types, "pool": ix.pools, "peff": ix.peff, "fam": ix.fams, "sess": ix.sessions, "pair": pairs}
    with pm.Model(coords=coords) as m:
        eta = _type_effects(ix, center, cov=cov, counts=df.type.value_counts().to_dict(),
                            rich=RICH if rich is None else rich, zero_avoid=zero_avoid)
        lin = eta[t_i]
        if sess:
            tau_s = _scale("tau_s", 0.3, zero_avoid)
            z_s = pm.ZeroSumNormal("z_s", 1.0, dims="sess")
            tau_ts = _scale("tau_ts", 0.5, zero_avoid)     # type x session (job mix) heterogeneity
            npair = np.bincount(pr_i, minlength=len(pairs))
            thr = 10 ** 9 if rich_pairs is None else rich_pairs
            rich, poor = np.where(npair >= thr)[0], np.where(npair < thr)[0]
            d_ts = pt.zeros(len(pairs))
            if len(rich):
                d_ts = pt.set_subtensor(d_ts[rich], pm.Normal("dev_rich_ts", 0, tau_ts, shape=len(rich)))
            if len(poor):
                d_ts = pt.set_subtensor(d_ts[poor], tau_ts * pm.Normal("z_poor_ts", 0, 1, shape=len(poor)))
            pm.Deterministic("d_ts", d_ts, dims="pair")
            lin = lin + tau_s * z_s[s_i] + d_ts[pr_i]
        if resume:
            rho = pm.Normal("rho", 0, 0.5)
            lin = lin + rho * r_i
        u, c = ~cens, cens
        if kind == "nb":
            la = pm.Normal("log_alpha", 0.7, 0.75, dims="pool")
            tla, zla = _scale("tau_la", 0.3, zero_avoid), pm.Normal("z_la", 0, 1, dims="type")
            lat = pm.Deterministic("log_alpha_t", la[ix.t_pool] + tla * zla, dims="type")
            alpha = pt.exp(lat)[t_i]
            mu = pt.exp(lin)
            pm.NegativeBinomial("y", mu=mu[u], alpha=alpha[u], observed=y[u] - 1)
            if c.any():
                lc = pm.logcdf(pm.NegativeBinomial.dist(mu=mu[c], alpha=alpha[c]), y[c] - 2)
                pm.Potential("cens", pt.sum(pt.log1mexp(lc)))
        elif kind == "gamma":
            lk = pm.Normal("log_k", 0.0, 1.0, dims="pool")
            tlk, zlk = pm.HalfNormal("tau_lk", 0.3), pm.Normal("z_lk", 0, 1, dims="type")
            lkt = pm.Deterministic("log_k_t", lk[ix.t_pool] + tlk * zlk, dims="type")
            k = pt.exp(lkt)[t_i]
            mu = pt.exp(lin)
            pm.Gamma("y", alpha=k[u], beta=k[u] / mu[u], observed=y[u])
            if c.any():
                lc = pm.logcdf(pm.Gamma.dist(alpha=k[c], beta=k[c] / mu[c]), y[c])
                pm.Potential("cens", pt.sum(pt.log1mexp(lc)))
        else:
            ls = pm.Normal("log_sigma", 0.0, 0.5, dims="pool")
            if type_scale:
                tls, zls = pm.HalfNormal("tau_ls", 0.3), pm.Normal("z_ls", 0, 1, dims="type")
                lst = pm.Deterministic("log_sigma_t", ls[ix.t_pool] + tls * zls, dims="type")
            else:
                lst = pm.Deterministic("log_sigma_t", ls[ix.t_pool], dims="type")
            sig = pt.exp(lst)[t_i]
            ly = np.log(y)
            pm.Normal("y", lin[u], sig[u], observed=ly[u])
            if c.any():
                pm.Potential("cens", pt.sum(pm.logcdf(pm.Normal.dist(-lin[c], sig[c]), -ly[c])))
        if prior_only:
            return pm.sample_prior_predictive(draws=1000, random_seed=seed), None
        dt = pm.sample(draws=draws, tune=tune, chains=CHAINS, random_seed=seed, progressbar=False,
                       nuts_sampler="nutpie", target_accept=TARGET_ACCEPT)
    return dt, diagnostics(dt)


def prior_check(df, ycol, kind, ix, center, ceiling):
    """Prior predictive of the observed (uncensored) rows: pooled quantiles and the share above the largest
    ceiling (plausibility of the priors before any data)."""
    pp, _ = fit_hier(df, ycol, kind, ix, center, prior_only=True, seed=SEED + 99)
    y = pp["prior_predictive"].dataset["y"].values.ravel()
    y = (y + 1) if kind == "nb" else np.exp(y)
    obs = df[~df.cens][ycol].values
    return {"q05": float(np.quantile(y, .05)), "q50": float(np.quantile(y, .5)), "q95": float(np.quantile(y, .95)),
            "q99": float(np.quantile(y, .99)), "share_above_ceiling": float(np.mean(y > ceiling)), "ceiling": ceiling,
            "obs_q05": float(np.quantile(obs, .05)), "obs_q50": float(np.quantile(obs, .5)),
            "obs_q95": float(np.quantile(obs, .95))}


def fit_resume_ctx_bayes(agent, draws, tune):
    """resume_ctx (derive_sched_model.fit_resume_ctx, Bayesian): (ctx / n - prev_peak) = alpha + gamma n + e,
    e ~ StudentT(4, sigma), alpha, gamma >= 0; healthy resumed segments with prev_peak."""
    r = agent[(agent.seg > 0) & ~agent.cens_ctx & agent.prev_peak.notna() & (agent.api_calls > 0)].copy()
    if len(r) < 5:
        return {"n": int(len(r)), "status": "below gate"}
    n = r.api_calls.values.astype(float)
    y = (r.ctx.values / n - r.prev_peak.values) / 1e4
    with pm.Model():
        al = pm.HalfNormal("alpha", 10.0)
        ga = pm.HalfNormal("gamma", 1.0)
        sg = pm.HalfNormal("sigma", 10.0)
        pm.StudentT("y", nu=4, mu=al + ga * n, sigma=sg, observed=y)
        dt = pm.sample(draws=draws, tune=tune, chains=CHAINS, random_seed=SEED + 11, progressbar=False,
                       nuts_sampler="nutpie", target_accept=TARGET_ACCEPT)
    post = dt["posterior"].dataset
    q = lambda v, p: float(np.quantile(post[v].values, p) * 1e4)  # noqa: E731
    return {"n": int(len(r)), "n_agents": int(r.id.nunique()), "diag": diagnostics(dt),
            "alpha": q("alpha", .5), "alpha_ci": [q("alpha", .05), q("alpha", .95)],
            "gamma": q("gamma", .5), "gamma_ci": [q("gamma", .05), q("gamma", .95)]}


def fit_fixer_nig(agent, seed):
    """fixer reread (derive_sched_model.fit_fixer, conjugate NIG on log values, stdlib bayes_grid)."""
    mem = set(seed["pools"]["builder"])
    f = agent[(agent.seg == 0) & agent.type.isin(mem) & agent.ctx_at_first_write.notna() & agent.first_ctx.notna()]
    x = (f.ctx_at_first_write - f.first_ctx).values.astype(float)
    x = x[x > 0]
    res = G.nig_lognormal([math.log(v) for v in x], math.log(2e5))
    if res is None:
        return {"n": 0}
    med, lo, hi, n = res
    return {"n": int(n), "n_agents": int(f.id.nunique()), "reread": med, "ci95": [lo, hi],
            "gate": bool(n >= 5 and f.id.nunique() >= 3),
            "empirical_median": float(np.median(x)) if len(x) else None}


def diagnostics(dt, var_names=None):
    post = dt["posterior"].dataset
    names = var_names or [v for v in post.data_vars if v not in ("eta_type", "log_sigma_t", "log_alpha_t", "log_k_t",
                                                                 "log_a", "log_b", "u_agent", "v_family", "d_ts",
                                                                 "k_t", "q_t")]
    s = az.summary(post[names], kind="diagnostics", round_to="none")
    div = int(dt["sample_stats"].dataset["diverging"].values.sum())
    en = dt["sample_stats"].dataset["energy"].values            # (chain, draw): E-BFMI per chain
    bf = float(np.min(np.mean(np.diff(en, axis=1) ** 2, axis=1) / np.var(en, axis=1)))
    return {"rhat_max": float(s["r_hat"].max()), "ess_bulk_min": float(s["ess_bulk"].min()),
            "ess_tail_min": float(s["ess_tail"].min()), "divergences": div, "ebfmi_min": bf,
            "worst": str(s["r_hat"].idxmax())}


def pointwise_loglik(dt, df, ycol, kind, ix):
    """(chain, draw, row) log-likelihood on the raw scale (log-normal includes the -log y Jacobian), censored rows
    as log P(Y >= y): the input of PSIS-LOO between likelihood families."""
    post = dt["posterior"].dataset
    eta = post["eta_type"].values
    t_i, s_i = ix.ti(df.type), ix.si(df.session)
    pairs, pr_i = pair_index(df, ix)
    lin = eta[..., t_i]
    if "z_s" in post:
        lin = lin + post["tau_s"].values[..., None] * post["z_s"].values[..., s_i]
    if "d_ts" in post:
        lin = lin + post["d_ts"].values[..., pr_i]
    if "rho" in post:
        lin = lin + post["rho"].values[..., None] * df.resume.values[None, None, :]
    y = df[ycol].values.astype(float)
    c = df.cens.values.astype(bool)
    if kind == "ln":
        sd = np.exp(post["log_sigma_t"].values[..., t_i])
        z = (np.log(y) - lin) / sd
        ll = np.where(c, sst.norm.logsf(z), sst.norm.logpdf(z) - np.log(sd) - np.log(y))
    elif kind == "gamma":
        k = np.exp(post["log_k_t"].values[..., t_i])
        sc = np.exp(lin) / k
        ll = np.where(c, sst.gamma.logsf(y, k, scale=sc), sst.gamma.logpdf(y, k, scale=sc))
    else:
        a = np.exp(post["log_alpha_t"].values[..., t_i])
        mu = np.exp(lin)
        pp = a / (a + mu)
        ll = np.where(c, sst.nbinom.logsf(y - 2, a, pp), sst.nbinom.logpmf(y - 1, a, pp))
    return ll


def loo_of(ll):
    """PSIS-LOO elpd from a (chain, draw, obs) log-likelihood array (ArviZ 1.x)."""
    ds = xr.Dataset({"y": (("chain", "draw", "obs"), ll)})
    tree = xr.DataTree.from_dict({"log_likelihood": ds, "posterior": xr.Dataset({"d": (("chain", "draw"), ll[..., 0])})})
    r = az.loo(tree, pointwise=True)
    pk = np.asarray(r.pareto_k)
    return {"elpd": float(r.elpd), "se": float(r.se), "p": float(r.p), "good_k": float(r.good_k),
            "n_bad_k": int(np.sum(pk > r.good_k)), "elpd_i": np.asarray(r.elpd_i).ravel()}


def compare_loo(a, b):
    """elpd(a) - elpd(b) with the paired SE (sqrt(n) x sd of the pointwise differences)."""
    dlt = a["elpd_i"] - b["elpd_i"]
    return {"d_elpd": float(dlt.sum()), "se": float(math.sqrt(len(dlt)) * dlt.std(ddof=1)),
            "a_bad_k": a["n_bad_k"], "b_bad_k": b["n_bad_k"]}


def model_gate(dg):
    return (dg["rhat_max"] <= GATE["rhat"] and dg["ess_bulk_min"] >= GATE["ess"] and dg["ess_tail_min"] >= GATE["ess"]
            and dg["divergences"] <= GATE["div"] and not (dg["ebfmi_min"] < GATE["ebfmi"]))


def pair_index(df, ix):
    """Observed (type, session) pairs, sorted, and each row's pair index."""
    keys = list(zip(df.type, df.session))
    pairs = sorted(set(keys))
    pos = {k: i for i, k in enumerate(pairs)}
    return ["%s|%s" % k for k in pairs], np.array([pos[k] for k in keys])


def _tau_new(dt):
    """sd of a new session's effect on a type: sqrt(tau_s^2 + tau_ts^2), per draw (chain, draw)."""
    ds = dt["posterior"].dataset
    z = np.zeros(ds["a0"].shape)
    ts = ds["tau_s"].values if "tau_s" in ds else z
    tts = ds["tau_ts"].values if "tau_ts" in ds else z
    return np.sqrt(ts ** 2 + tts ** 2)


def _draws(dt, name):
    return dt["posterior"].dataset[name].values           # (chain, draw, ...)


def _get(dt, name, default=0.0):
    ds = dt["posterior"].dataset
    return ds[name].values if name in ds else None


# ---------------------------------------------------------------- predictive quantiles
def pred_ln(dt, ix, p_resume, probs, cvals=None):
    """Per type: predictive quantiles (raw units) of a new run (new session, resume mixture), the per-draw
    conditional quantile draws (chain, draw) for each prob, and P(X > c)."""
    eta = _draws(dt, "eta_type")                           # (C, D, T)
    sig = np.exp(_draws(dt, "log_sigma_t"))
    ts = _tau_new(dt)
    rho = _get(dt, "rho")
    rho = np.zeros(eta.shape[:2]) if rho is None else rho
    s = np.sqrt(sig ** 2 + ts[..., None] ** 2)
    out = {}
    for j, t in enumerate(ix.types):
        e, sd, rr = eta[..., j], s[..., j], rho

        def F(x, axis_mean=True, e=e, sd=sd, rr=rr):
            v = (1 - p_resume) * sst.norm.cdf((x - e) / sd) + p_resume * sst.norm.cdf((x - e - rr) / sd)
            return v.mean() if axis_mean else v
        res = {"q": {}, "qd": {}}
        for p in probs:
            lo, hi = float((e - 12 * sd).min() - abs(rr).max()), float((e + 12 * sd).max() + abs(rr).max())
            for _ in range(70):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if F(mid) < p else (lo, mid)
            res["q"][p] = float(np.exp(0.5 * (lo + hi)))
            lo_d, hi_d = e - 12 * sd - abs(rr), e + 12 * sd + abs(rr)
            for _ in range(60):
                mid = 0.5 * (lo_d + hi_d)
                low = F(mid, False) < p
                lo_d, hi_d = np.where(low, mid, lo_d), np.where(low, hi_d, mid)
            res["qd"][p] = np.exp(0.5 * (lo_d + hi_d))
        res["med_d"] = np.exp(e + p_resume * rr)            # the type's median (log-normal location)
        res["phit"] = {}
        for k, c in (cvals or {}).get(t, {}).items():
            res["phit"][k] = None if c is None else float(1 - F(math.log(c)))
        res["F"] = F
        out[t] = res
    return out


def pred_nb(dt, ix, p_resume, probs, cvals=None, kmax=5000, thin=2):
    eta = _draws(dt, "eta_type")[:, ::thin]
    al = np.exp(_draws(dt, "log_alpha_t"))[:, ::thin]
    ts = _tau_new(dt)[:, ::thin]
    rho = _get(dt, "rho")
    rho = np.zeros(eta.shape[:2]) if rho is None else rho[:, ::thin]
    gx, gw = np.array(G.GH_X), np.array(G.GH_W)
    out = {}
    for j, t in enumerate(ix.types):
        e, a = eta[..., j], al[..., j]

        def Fd(k, e=e, a=a):                         # per-draw P(Y - 1 <= k), k scalar or (C, D)
            k = np.asarray(k, float)
            tot = 0.0
            for rr, pr in ((0.0, 1 - p_resume), (rho, p_resume)):
                for x, w in zip(gx, gw):
                    mu = np.exp(e + rr + ts * x)
                    tot = tot + pr * w * sst.nbinom.cdf(k, a, a / (a + mu))
            return tot

        res = {"q": {}, "qd": {}}
        for p in probs:
            lo, hi = 0, kmax
            while lo < hi:
                mid = (lo + hi) // 2
                lo, hi = (mid + 1, hi) if Fd(mid).mean() < p else (lo, mid)
            res["q"][p] = float(1 + lo)
            lo_d, hi_d = np.zeros(e.shape), np.full(e.shape, float(kmax))
            for _ in range(14):
                mid = np.floor(0.5 * (lo_d + hi_d))
                low = Fd(mid) < p
                lo_d, hi_d = np.where(low, mid + 1, lo_d), np.where(low, hi_d, mid)
            res["qd"][p] = 1 + lo_d
        res["med_d"] = 1 + np.exp(e + p_resume * rho)       # the type's mean of y (location summary)
        res["phit"] = {}
        for k, c in (cvals or {}).get(t, {}).items():
            res["phit"][k] = None if c is None else float(1 - Fd(c - 1).mean())
        res["Fd"] = Fd
        out[t] = res
    return out


def qdiag(qd):
    """R-hat / ESS of a derived quantity's draws (chain, draw)."""
    if np.ptp(qd) == 0:
        return {"rhat": 1.0, "ess_bulk": float(qd.size), "ess_tail": float(qd.size)}
    s = az.summary(xr.Dataset({"q": (("chain", "draw"), np.asarray(qd, float))}), kind="diagnostics",
                   round_to="none")
    return {"rhat": float(s["r_hat"].iloc[0]), "ess_bulk": float(s["ess_bulk"].iloc[0]),
            "ess_tail": float(s["ess_tail"].iloc[0])}


def ppc(dt, df, ycol, kind, ix, cv, min_n=5):
    """Per type with >= min_n rows: observed fraction above thresholds (the current value, the type's observed
    p50 and p90) vs the posterior predictive for the same rows (own session effect, own resume flag) and for a
    new session."""
    post = dt["posterior"].dataset
    eta = post["eta_type"].values
    ts = post["tau_s"].values if "tau_s" in post else np.zeros(eta.shape[:2])
    zs = post["z_s"].values if "z_s" in post else None
    dts = post["d_ts"].values if "d_ts" in post else None
    pairs, _ = pair_index(df, ix)
    tnew = _tau_new(dt)
    rho = post["rho"].values if "rho" in post else np.zeros(eta.shape[:2])
    scale = np.exp(post["log_alpha_t" if kind == "nb" else "log_sigma_t"].values)
    out = {}
    for t in ix.types:
        sub = df[df.type == t]
        if len(sub) < min_n:
            continue
        j = ix.types.index(t)
        y = sub[ycol].values.astype(float)
        cur = (cv.get(t) or {}).get("cur" if kind == "nb" else "soft_cur")
        ths = [("p50", float(np.quantile(y, 0.5))), ("p90", float(np.quantile(y, 0.9)))]
        if cur:
            ths.append(("cur", float(cur)))
        sc = scale[..., j]
        rows = []
        for lab, c in ths:
            obs = float(np.mean(y > c))
            pin, pnew = [], []
            for (_, r) in sub.iterrows():
                lin = eta[..., j] + rho * r["resume"]
                linin = lin + (ts * zs[..., ix.sessions.index(r["session"])] if zs is not None else 0.0)
                if dts is not None:
                    linin = linin + dts[..., pairs.index("%s|%s" % (t, r["session"]))]
                if kind == "nb":
                    f = lambda L_: 1 - sst.nbinom.cdf(c - 1, sc, sc / (sc + np.exp(L_)))  # noqa: E731
                    pin.append(float(f(linin).mean()))
                    pnew.append(float(np.mean([gw * f(lin + tnew * gx) for gx, gw in zip(G.GH_X, G.GH_W)]) * len(G.GH_X)))
                else:
                    pin.append(float((1 - sst.norm.cdf((math.log(c) - linin) / sc)).mean()))
                    pnew.append(float((1 - sst.norm.cdf((math.log(c) - lin) / np.sqrt(sc ** 2 + tnew ** 2))).mean()))
            rows.append({"label": lab, "c": c, "n": int(len(sub)), "obs": obs, "pred_in": float(np.mean(pin)),
                         "pred_new": float(np.mean(pnew))})
        out[t] = rows
    return out


# ============================================================================ grid tier (stdlib)
def hyper_from_nuts(dt, kind, ix):
    """Posterior medians the stdlib grid conditions on: per type prior mean (a0 + b_fam + g z + u_pool) and
    sd (tau_t), the pool scale (sigma or alpha), tau_s, rho."""
    post = dt["posterior"].dataset
    med = lambda v: np.median(post[v].values, axis=(0, 1))  # noqa: E731
    a0, bf, tt = med("a0"), med("b_fam"), med("tau_t")
    g = med("g") if "g" in post else 0.0
    zp = np.concatenate([med("u_p"), [0.0]])
    h = {"tau_t": float(tt), "tau_s": float(np.median(_tau_new(dt))),
         "rho": float(med("rho")) if "rho" in post else 0.0, "types": {}}
    scale = np.exp(med("log_alpha_t" if kind == "nb" else "log_sigma_t"))
    for j, t in enumerate(ix.types):
        h["types"][t] = {"mu": float(a0 + bf[ix.t_fam[j]] + g * ix.zmt[j] + zp[ix.t_peff[j]]),
                         "scale": float(scale[j])}
    return h


def hyper_eb(df, ycol, kind, ix):
    """Stdlib-only hyperparameters (no sampler): per pool moment estimates on the log scale over
    uncensored rows (bayes_grid.eb_hyper_lognormal); NB alpha from the pooled moment estimate."""
    h = {"tau_s": 0.0, "rho": 0.0, "types": {}}
    taus = []
    for pool in ix.pools:
        mem = [t for t in ix.types if ix.pool_of[t] == pool]
        sub = df[df.type.isin(mem) & ~df.cens]
        if kind == "nb":
            groups = {t: [math.log(v) for v in sub[sub.type == t][ycol] if v > 0] for t in mem}
        else:
            groups = {t: [math.log(v) for v in sub[sub.type == t][ycol] if v > 0] for t in mem}
        allv = [v for xs in groups.values() for v in xs]
        if len(allv) >= 3:
            gm, tau, sig = G.eb_hyper_lognormal(groups)
        else:
            gm, tau, sig = (float(np.mean(allv)) if allv else math.log(10.0 if kind == "nb" else 3e5)), 1.0, 1.0
        taus.append(tau)
        for t in mem:
            if kind == "nb":
                ys = sub[ycol].values - 1.0
                m, v = (ys.mean(), ys.var()) if len(ys) > 2 else (math.exp(gm), math.exp(gm) * 3)
                alpha = m * m / (v - m) if v > m else 50.0
                h["types"][t] = {"mu": float(gm), "scale": float(min(max(alpha, 0.2), 50.0))}
            else:
                h["types"][t] = {"mu": float(gm), "scale": float(sig)}
    h["tau_t"] = float(np.median(taus)) if taus else 1.0
    return h


def grid_values(df, ycol, kind, ix, h, probs, p_resume, cvals=None, kmax_of=None):
    out = {}
    for t in ix.types:
        sub = df[df.type == t]
        hp = h["types"][t]
        u, c = sub[~sub.cens], sub[sub.cens]
        ou = [h["rho"] * r for r in u.resume]
        oc = [h["rho"] * r for r in c.resume]
        if kind == "nb":
            cc = [int(v) for v in c[ycol] if v > 1]
            oc = [o for o, v in zip(oc, c[ycol]) if v > 1]
            etas, w, info = G.nb_post([int(v) for v in u[ycol]], cc, hp["mu"], h["tau_t"], hp["scale"], ou, oc)
            km = (kmax_of or {}).get(t, 2000)
            res = {"q": {}, "ci": {}, "phit": {}}
            pred = G.nb_predictive(etas, w, hp["scale"], h["tau_s"], h["rho"], p_resume, kmax=km)
            for p in probs:
                res["q"][p], res["ci"][p] = G.nb_quantile_from(pred, p)
            for k, cv in (cvals or {}).get(t, {}).items():
                res["phit"][k] = None if cv is None else G.nb_p_hit(pred["mix"], cv)
        else:
            etas, w, info = G.lognormal_post([math.log(v) for v in u[ycol]], [math.log(v) for v in c[ycol]],
                                             hp["mu"], h["tau_t"], hp["scale"], ou, oc)
            res = {"q": {}, "ci": {}, "phit": {}}
            for p in probs:
                lq, (l5, l95) = G.lognormal_quantile(etas, w, p, hp["scale"], h["tau_s"], h["rho"], p_resume)
                res["q"][p], res["ci"][p] = math.exp(lq), (math.exp(l5), math.exp(l95))
            for k, cv in (cvals or {}).get(t, {}).items():
                res["phit"][k] = None if cv is None else 1 - G.lognormal_pred_cdf(
                    etas, w, math.log(cv), hp["scale"], h["tau_s"], h["rho"], p_resume)
        res["edge_mass"] = info["edge_mass"]
        out[t] = res
    return out


# ============================================================================ section 4 (empirical) side by side
def empirical(seed, live, paths, regime, models, now):
    props = L.build_proposals(seed, paths, regime=regime, live=live, now=now, models=models)
    pv, _ = L.validate_proposals(json.loads(json.dumps(props)), seed)
    pool_of = L._pool_of(seed)
    out = {}
    for v in sorted(seed["vars"]):
        fam, t = L.split_var(v)
        spec = seed["vars"][v]
        ent = pv["vars"].get(v)
        pool = pv["pools"].get("%s:%s" % (fam, pool_of[t])) if t and t in pool_of else None
        status, use, p90e = L.classify(fam, ent, pool) if (ent or pool) else (None, None, None)
        T = None
        if status:
            soft_ref = None
            if fam == "hard.agent":
                soft_ref = L._eff(live["vars"]["soft.agent." + t])
            T = L.target(spec["kind"], spec["unit"], use["x"], p90e, soft_ref)
        out[v] = {"status": status, "T": T, "n": (ent or {}).get("n", 0)}
    new, recs, changes = L.apply_proposals(seed, live, pv, sid="b1-prototype", now=now)
    for v in out:
        out[v]["next"] = new["vars"][v]["value"]
        out[v]["cur"] = live["vars"][v]["value"]
    return out, pv


def emp_target_from_rows(sub, ycol, kind_rule, soft_ref=None):
    """Section 4 raw target from a training sample (healthy rows only), for the backtest: soft rule
    (derive) or hard rule (max(1.5 p90, 1.1 hmax)); None below n = 3 (the value would hold)."""
    xs = sorted(float(v) for v in sub[~sub.cens][ycol])
    if len(xs) < 3:
        return None
    p90 = L._qs(xs, 0.9)
    unit = "turns" if ycol == "api_calls" else "ctx"
    return L.target(kind_rule, unit, xs, p90, soft_ref)


# ============================================================================ decision rule (reference for the integrator)
def decide_bayes(c, T, phit_c, r, status, kind, f, g, hmax=None, pin=None, d=1.0):
    """The B1 replacement of section 4's target/dead-band (design.md section 5), without damping state:
    returns (new value, decision)."""
    if status == "prior":
        return c, "hold:prior"
    if kind == "hard" and status != "supported":
        return c, "hold:unsupported"
    if c is None:
        x = min(max(T, f), g)
        return (max(x, pin) if pin else x), "set"
    if phit_c is not None and r / 2 <= phit_c <= 2 * r:
        return c, "dead:risk"
    if abs(T - c) <= 0.10 * c:
        return c, "dead:10%"
    if T < c and kind == "hard" and hmax:
        T = max(T, min(c, hmax))
        if T >= c:
            return c, "hold:hmax"
    x = min(max(T, c * (1 - 0.25 * d)), c * (1 + 0.25 * d))
    x = min(max(round(x), f), g)
    if pin:
        x = max(x, pin)
    return x, ("step" if x != c else "hold")


# ============================================================================ scope 2
def scope2_units(data_dir):
    """Graded units for scope 2. v2: one unit per run (install x prompt x variant), not per prompt id.
    With data/runs_before.csv (stats_before v1.1: one row per graded run, with install, variant, the agent that ran,
    family, cost_class, target_agent, tokens), the units come from it and every grade is cross-checked against the
    grade files (baseline_grades + grades_T8b = old_install v1; grades_b0v2 = new_install, keyed by id and variant).
    Without it (v1 data), the v1 rule: the first root run per prompt id joined to the grades by prompt id. That rule
    mis-pairs once grades_b0v2.csv is present: its v2 grades would overwrite the old-install grades of the same ids
    and be joined to the old-install runs, and its 24 wave-M ids have no row in baseline_runs.csv."""
    gfiles = [f for f in sorted(os.listdir(data_dir)) if f.startswith("baseline_grades") or f.startswith("grades_")]
    rb = os.path.join(data_dir, "runs_before.csv")
    if not os.path.exists(rb):
        runs = pd.read_csv(os.path.join(data_dir, "baseline_runs.csv"))
        grades = pd.concat([pd.read_csv(os.path.join(data_dir, f)) for f in gfiles]).drop_duplicates("id", keep="last")
        root = runs[(runs.is_root == 1) & runs.prompt_id.notna()].copy()
        root = root.sort_values("start").drop_duplicates("prompt_id", keep="first")
        df = root.merge(grades[["id", "check_result"]].rename(columns={"id": "prompt_id", "check_result": "grade"}),
                        on="prompt_id")
        df["install"], df["variant"] = "old_install", "v1"
        return df, gfiles, {"source": "baseline_runs.csv (v1 rule)"}
    df = pd.read_csv(rb)
    chk = {}
    for f in gfiles:
        g = pd.read_csv(os.path.join(data_dir, f))
        inst = "new_install" if "variant" in g.columns else "old_install"
        var = g["variant"] if "variant" in g.columns else pd.Series("v1", index=g.index)
        for i, v, c in zip(g["id"], var, g["check_result"]):
            chk[(inst, str(i), str(v))] = str(c)
    keys = list(zip(df.install, df.prompt_id.astype(str), df.variant.astype(str)))
    mism = [(k, gr, chk.get(k)) for k, gr in zip(keys, df.grade) if chk.get(k) != gr]
    info = {"source": "runs_before.csv", "units": int(len(df)), "grade_file_rows": len(chk),
            "mismatch_vs_grade_files": [list(map(str, m)) for m in mism],
            "units_by_install_variant": {"%s/%s" % k: int(v) for k, v in df.groupby(["install", "variant"]).size().items()}}
    return df, gfiles, info


def scope2(data_dir, seed, draws, tune):
    df, gfiles, src = scope2_units(data_dir)
    n_units = int(len(df))
    excl = list(df.grade[~df.grade.isin(["fail", "partial", "pass"])].astype(str))   # tool-absent etc.: not graded
    df = df[df.grade.isin(["fail", "partial", "pass"])].copy()
    lvl = {"fail": 0, "partial": 1, "pass": 2}
    df["y"] = df.grade.map(lvl)
    df["match"] = [int(str(a) in str(tg)) for a, tg in zip(df.agent_type, df.target_agent)]
    installs = sorted(df.install.unique())
    df["new_install"] = (df.install == "new_install").astype(float)
    pool_of = L._pool_of(seed)
    agents = sorted(df.agent_type.unique())
    famlist = sorted(df.family.unique())
    pools = sorted({pool_of.get(a, "builder") for a in agents})
    sizes = ["S", "M", "L"]
    a_i = np.array([agents.index(a) for a in df.agent_type])
    f_i = np.array([famlist.index(f) for f in df.family])
    ap_i = np.array([pools.index(pool_of.get(a, "builder")) for a in agents])
    sz_i = np.array([sizes.index(s) for s in df.cost_class])
    with pm.Model(coords={"agent": agents, "family": famlist, "pool": pools, "size": sizes, "cutpoint": [0, 1]}):
        tp = pm.HalfNormal("tau_pool", 0.5)
        zp = pm.Normal("z_pool", 0, 1, dims="pool")
        ta = pm.HalfNormal("tau_agent", 0.5)
        za = pm.Normal("z_agent", 0, 1, dims="agent")
        u = pm.Deterministic("u_agent", tp * zp[ap_i] + ta * za, dims="agent")
        tf = pm.HalfNormal("tau_family", 0.5)
        zf = pm.Normal("z_family", 0, 1, dims="family")
        v = pm.Deterministic("v_family", tf * zf, dims="family")
        b = pm.Normal("b_match", 0, 0.5)
        gs = pm.ZeroSumNormal("g_size", 0.5, dims="size")
        # install effect (v2): the new install is a different stack version; N(0, 0.5) on the logit scale
        bi = pm.Normal("b_install", 0, 0.5) if len(installs) > 1 else pt.zeros(())
        cut = pm.Normal("cut", mu=np.array([-3.0, -1.0]), sigma=1.0, dims="cutpoint",
                        transform=pm.distributions.transforms.ordered, initval=np.array([-3.0, -1.0]))
        eta = u[a_i] + v[f_i] + b * df.match.values + gs[sz_i] + bi * df.new_install.values
        pm.OrderedLogistic("y", eta=eta, cutpoints=cut, observed=df.y.values)
        dt = pm.sample(draws=draws, tune=tune, chains=CHAINS, random_seed=SEED + 2, progressbar=False,
                       nuts_sampler="nutpie", target_accept=TARGET_ACCEPT)
    dg = diagnostics(dt, ["tau_pool", "z_pool", "tau_agent", "z_agent", "tau_family", "z_family", "b_match",
                          "g_size", "cut"] + (["b_install"] if len(installs) > 1 else []))
    post = dt["posterior"].dataset
    uu, vv, cc = post["u_agent"].values, post["v_family"].values, post["cut"].values
    bb, gg = post["b_match"].values, post["g_size"].values
    bi_d = post["b_install"].values if "b_install" in post else np.zeros(bb.shape)
    cur_inst = 1.0 if "new_install" in installs else 0.0       # agent marginals: the current (newest) install
    cells = []
    for (a, fm, ins), grp in df.groupby(["agent_type", "family", "install"]):
        ai, fi = agents.index(a), famlist.index(fm)
        m = int(grp.match.iloc[0])
        si = sizes.index(grp.cost_class.iloc[0])
        eta = uu[..., ai] + vv[..., fi] + bb * m + gg[..., si] + bi_d * float(ins == "new_install")
        ppass = 1 - 1 / (1 + np.exp(-(cc[..., 1] - eta)))
        cells.append({"agent": a, "family": fm, "install": ins, "n": len(grp), "n_pass": int((grp.y == 2).sum()), "match": m,
                      "p_pass_mean": float(ppass.mean()), "p_pass_lo": float(np.quantile(ppass, 0.05)),
                      "p_pass_hi": float(np.quantile(ppass, 0.95))})
    agent_marg = []
    for a in agents:
        ai = agents.index(a)
        eta = uu[..., ai] + bb * 1 + bi_d * cur_inst
        ppass = 1 - 1 / (1 + np.exp(-(cc[..., 1] - eta)))
        agent_marg.append({"agent": a, "n": int((df.agent_type == a).sum()), "p_pass_mean": float(ppass.mean()),
                           "p_pass_lo": float(np.quantile(ppass, 0.05)), "p_pass_hi": float(np.quantile(ppass, 0.95)),
                           "tokens_med": float(df[df.agent_type == a].tokens_total.median())})
    # conjugate cross-check: Beta(1, 1)-binomial pass rate per agent (no pooling)
    for r in agent_marg:
        sub = df[df.agent_type == r["agent"]]
        k, n = int((sub.y == 2).sum()), len(sub)
        r["beta_pass_mean"] = (k + 1) / (n + 2)
    return {"n": int(len(df)), "n_units": n_units, "excluded_grades": {str(k): int(v) for k, v in
                                                                      pd.Series(excl).value_counts().items()},
            "source": src, "installs": installs, "grades_files": gfiles, "levels": lvl, "diag": dg,
            "gate": model_gate(dg), "b_match": [float(np.quantile(bb, q)) for q in (0.05, 0.5, 0.95)],
            "b_install": [float(np.quantile(bi_d, q)) for q in (0.05, 0.5, 0.95)] if len(installs) > 1 else None,
            "n_by_install": df.groupby("install").y.size().to_dict(),
            "cells": cells, "agents": agent_marg, "n_by_grade": df.grade.value_counts().to_dict()}


# ============================================================================ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.path.join(HERE, "data"))
    ap.add_argument("--out", default=os.path.join(HERE, "out"))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--no-backtest", action="store_true")
    ap.add_argument("--no-scope2", action="store_true")
    ap.add_argument("--scope2-only", action="store_true")
    ap.add_argument("--backtest-only", action="store_true")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    draws, tune = (500, 500) if a.quick else (DRAWS, TUNE)
    t0 = time.time()
    seed, types, models, d, meta = load(a.data)
    versions = {"python": sys.version.split()[0], "pymc": pm.__version__, "arviz": az.__version__,
                "numpy": np.__version__, "pandas": pd.__version__, "scipy": __import__("scipy").__version__,
                "pytensor": __import__("pytensor").__version__, "nutpie": __import__("nutpie").__version__}
    meta.update(versions=versions, seed=SEED, chains=CHAINS, draws=draws, tune=tune, risk=RISK, gate=GATE,
                code_version=CODE_VERSION, seed_sha=seed["sha"], param=PARAM)
    print("data", meta["evidence_id"][:16], meta["read_rows_stats"], flush=True)

    if a.backtest_only:                       # supplementary: the rolling-origin backtest alone (same fold seeds)
        bt = backtest(d, seed, models, draws, tune)
        pd.DataFrame(bt["rows"]).to_csv(os.path.join(a.out, "backtest_rows.csv"), index=False)
        json.dump(bt["summary"], open(os.path.join(a.out, "backtest_summary.json"), "w"), indent=1, default=float)
        meta["elapsed_s"] = round(time.time() - t0, 1)
        json.dump(meta, open(os.path.join(a.out, "run_meta.json"), "w"), indent=1, default=str)
        return 0
    s2 = None
    if not a.no_scope2:
        s2 = scope2(a.data, seed, draws, tune)
        json.dump(s2, open(os.path.join(a.out, "scope2.json"), "w"), indent=1, default=float)
        print("scope2", s2["n"], s2["diag"], flush=True)
    if a.scope2_only:
        open(os.path.join(a.out, "scope2_tables.md"), "w").write(
            "# B1 scope 2 tables (generated by fit_prototype.py --scope2-only; do not edit)\n" + "\n".join(scope2_lines(s2)) + "\n")
        return 0

    agent = agent_frame(d, seed)
    agent = window_cap(agent)
    sessions = sorted(agent.session.unique())
    ix = Index(seed, models, sessions)
    p_resume = float(agent.resume.mean())
    meta["p_resume"] = p_resume
    meta["n_agent_rows"] = int(len(agent))
    meta["n_censored"] = {"turns": int(agent.cens_turns.sum()), "ctx": int(agent.cens_ctx.sum())}

    # current (live copy) and seed values for p_hit
    live_doc = json.load(open(os.path.join(a.data, "state", "live.json")))
    live = L.validate_live(live_doc, seed)
    props_doc = json.load(open(os.path.join(a.data, "state", "proposals.json")))
    now = time.time()
    emp, _ = empirical(seed, live, [os.path.join(a.data, "runs.csv"), os.path.join(a.data, "runs3.csv")],
                       props_doc.get("regime"), models, now)

    def cvals(fam):
        return {t: {"cur": live["vars"]["%s.%s" % (fam, t)]["value"], "seed": seed["vars"]["%s.%s" % (fam, t)]["seed"],
                    "emp_T": emp["%s.%s" % (fam, t)]["T"]} for t in types}

    fits, diags, preds, grids, gridseb, ppcs = {}, {}, {}, {}, {}, {}
    # --- turns (NB) and ctx (log-normal): the limit variables
    cc_ctx = {t: {**{("soft_" + k): v for k, v in cvals("soft.agent")[t].items()},
                  **{("hard_" + k): v for k, v in cvals("hard.agent")[t].items()}} for t in types}
    probs_turns = (0.25, 0.5, 0.9, 1 - RISK["turns"])
    probs_ctx = (0.05, 0.5, 0.95, 1 - RISK["soft.agent"], 1 - RISK["hard.agent"])
    kmax_of = {t: int(2 * seed["vars"]["turns." + t]["ceiling"]) + 50 for t in types}
    for name, ycol, kind, center, probs, cv in (
            ("turns", "api_calls", "nb", math.log(10), probs_turns, cvals("turns")),
            ("ctx", "ctx", "ln", math.log(1e6), probs_ctx, cc_ctx)):
        tt = time.time()
        dfc = with_cens(agent, name)
        dt, dg = fit_hier(dfc, ycol, kind, ix, center, draws, tune, **PARAM[name])
        fits[name], diags[name] = dt, dg
        preds[name] = (pred_nb if kind == "nb" else pred_ln)(dt, ix, p_resume, probs, cv)
        ppcs[name] = ppc(dt, dfc, ycol, kind, ix, cv)
        h = hyper_from_nuts(dt, kind, ix)
        grids[name] = grid_values(dfc, ycol, kind, ix, h, probs, p_resume, cv, kmax_of)
        heb = hyper_eb(dfc, ycol, kind, ix)
        gridseb[name] = grid_values(dfc, ycol, kind, ix, heb, probs, p_resume, cv, kmax_of)
        json.dump({"nuts": h, "eb": heb}, open(os.path.join(a.out, "hyper_%s.json" % name), "w"), indent=1)
        print(name, dg, "%.0fs" % (time.time() - tt), flush=True)

    # --- likelihood family check (design.md 3.1): log-normal vs gamma by PSIS-LOO on the raw scale
    fam_cmp = {}
    dfc = with_cens(agent, "ctx")
    ll_ln = loo_of(pointwise_loglik(fits["ctx"], dfc, "ctx", "ln", ix))
    dtg, dgg = fit_hier(dfc, "ctx", "gamma", ix, math.log(1e6), draws, tune, seed=SEED + 8)
    ll_g = loo_of(pointwise_loglik(dtg, dfc, "ctx", "gamma", ix))
    fam_cmp["ctx"] = dict(compare_loo(ll_ln, ll_g), ln_elpd=ll_ln["elpd"], gamma_elpd=ll_g["elpd"], gamma_diag=dgg)
    print("ctx ln vs gamma", {k: v for k, v in fam_cmp["ctx"].items() if k != "gamma_diag"}, flush=True)

    # --- scheduler-only quantities
    comp = agent[agent.status == "complete"].copy()
    spc = comp[(comp.wall_s.fillna(0) > 0)].copy()
    spc["spc"] = spc.wall_s / spc.api_calls
    spc["cens"] = False
    dt, dg = fit_hier(spc, "spc", "ln", ix, math.log(15), draws, tune, seed=SEED + 3, type_scale=False, rich=10 ** 9)
    fits["spc"], diags["spc"] = dt, dg
    preds["spc"] = pred_ln(dt, ix, p_resume, (0.05, 0.5, 0.9, 0.95))
    print("spc", dg, flush=True)
    ll_ln = loo_of(pointwise_loglik(dt, spc, "spc", "ln", ix))
    dtg, dgg = fit_hier(spc, "spc", "gamma", ix, math.log(15), draws, tune, seed=SEED + 9, rich=10 ** 9)
    ll_g = loo_of(pointwise_loglik(dtg, spc, "spc", "gamma", ix))
    fam_cmp["spc"] = dict(compare_loo(ll_ln, ll_g), ln_elpd=ll_ln["elpd"], gamma_elpd=ll_g["elpd"], gamma_diag=dgg)
    print("spc ln vs gamma", {k: v for k, v in fam_cmp["spc"].items() if k != "gamma_diag"}, flush=True)
    json.dump(fam_cmp, open(os.path.join(a.out, "family_loo.json"), "w"), indent=1, default=float)
    first = agent[(agent.seg == 0) & (agent.first_cc.fillna(0) > 0) & (agent.compacted.fillna(0) != 1)].copy()
    first["cens"] = False
    dt, dg = fit_hier(first, "first_cc", "ln", ix, math.log(3e4), draws, tune, seed=SEED + 4, resume=False,
                      sess=False, type_scale=False)     # the static prompt does not depend on the job
    fits["static_cc"], diags["static_cc"] = dt, dg
    preds["static_cc"] = pred_ln(dt, ix, 0.0, (0.1, 0.5))
    print("static_cc", dg, flush=True)
    tc = with_cens(agent[agent.tool_calls.notna() & (agent.tool_calls >= 0)], "turns")
    tc["tc1"] = tc.tool_calls + 1                      # y >= 1 for the shifted NB
    if len(tc) >= 20:
        dt, dg = fit_hier(tc, "tc1", "nb", ix, math.log(10), draws, tune, seed=SEED + 5, **PARAM["tool_calls"])
        fits["tool_calls"], diags["tool_calls"] = dt, dg
        preds["tool_calls"] = pred_nb(dt, ix, p_resume, (0.5, 0.9), kmax=3000)
        print("tool_calls", dg, flush=True)
    ab = ctx_ab(agent, ix, draws, tune)
    diags["ctx_ab"] = ab["diag"]
    print("ctx_ab", ab["diag"], flush=True)
    extras = {"resume_ctx": fit_resume_ctx_bayes(agent, draws, tune), "fixer": fit_fixer_nig(agent, seed),
              "prior_turns": prior_check(with_cens(agent, "turns"), "api_calls", "nb", ix, math.log(10), 350),
              "prior_ctx": prior_check(with_cens(agent, "ctx"), "ctx", "ln", ix, math.log(1e6), 2e8)}
    if "diag" in extras["resume_ctx"]:
        diags["resume_ctx"] = extras["resume_ctx"]["diag"]
    json.dump(extras, open(os.path.join(a.out, "extras.json"), "w"), indent=1, default=float)
    print("extras", {k: {kk: vv for kk, vv in v.items() if kk != "diag"} for k, v in extras.items()}, flush=True)

    # --- prompt and session scopes (no hierarchy; seed-anchored grids, stdlib)
    scoped = scope_vars(d, seed, live)

    # --- assemble the per-variable table
    table = assemble(seed, ix, agent, preds, grids, gridseb, diags, emp, live, scoped)
    sched = sched_table(ix, agent, preds, ab, diags)
    pd.DataFrame(table).to_csv(os.path.join(a.out, "limits_compare.csv"), index=False)
    pd.DataFrame(sched).to_csv(os.path.join(a.out, "sched_compare.csv"), index=False)
    json.dump(diags, open(os.path.join(a.out, "diagnostics.json"), "w"), indent=1, default=float)
    json.dump(ppcs, open(os.path.join(a.out, "ppc.json"), "w"), indent=1, default=float)
    example_prov(table, meta, os.path.join(a.out, "proposals_bayes_example.json"))

    sens = sensitivity(d, seed, ix, models, draws, tune, preds)
    json.dump(sens, open(os.path.join(a.out, "sensitivity.json"), "w"), indent=1, default=float)

    bt = None
    if not a.no_backtest:
        bt = backtest(d, seed, models, draws, tune)
        pd.DataFrame(bt["rows"]).to_csv(os.path.join(a.out, "backtest_rows.csv"), index=False)
        json.dump(bt["summary"], open(os.path.join(a.out, "backtest_summary.json"), "w"), indent=1, default=float)
    meta["elapsed_s"] = round(time.time() - t0, 1)
    json.dump(meta, open(os.path.join(a.out, "run_meta.json"), "w"), indent=1, default=str)
    write_tables(a.out, meta, diags, table, sched, scoped, bt, s2, sens, ppcs, fam_cmp, extras)
    print("done in %.0fs" % (time.time() - t0))
    return 0


# ---------------------------------------------------------------- ctx(n) = a n + b n^2
def ctx_ab(agent, ix, draws, tune, seed=SEED + 6, version=2):
    """ctx(n) = a n + b n^2 per type, log-normal errors, first healthy segments.
    v2 (design.md 3.1/4 S4): per type, k_t = log(a_t + b_t n_ref) (log ctx per call at the reference length n_ref =
    geometric mean of n) and q_t = logit(b_t n_ref / (a_t + b_t n_ref)) (share of the quadratic term at n_ref):
        log y = log n + k_t + log1p(sigmoid(q_t) (n / n_ref - 1)) + e,   a = e^k (1 - s), b = e^k s / n_ref.
    k_t is pinned by any data near n_ref; q_t only by a type's spread in n, so it shrinks to its pool when n is
    narrow. v1's (log a, log b) pair is a ridge for every type observed over a narrow n range (a and b trade off
    one for one), which together with centered deviations gave 21 divergences at tau -> 0. All type deviations
    non-centered. version=1 reproduces v1."""
    f = agent[(agent.seg == 0) & (agent.status == "complete") & (agent.compacted.fillna(0) != 1)
              & (agent.api_calls > 0) & (agent.ctx > 0)].copy()
    t_i, n = ix.ti(f.type), f.api_calls.values.astype(float)
    ly = np.log(f.ctx.values.astype(float))
    counts = f.type.value_counts().to_dict()
    n_ref = float(np.exp(np.mean(np.log(n))))
    with pm.Model(coords={"type": ix.types, "pool": ix.pools, "peff": ix.peff}):
        if version == 1:
            A0 = pm.Normal("A0", math.log(5e4), 1.5)
            B0 = pm.Normal("B0", math.log(2e3), 2.0)
            upa = pt.concatenate([pm.ZeroSumNormal("u_pa", 0.7, dims="peff"), pt.zeros(1)])
            upb = pt.concatenate([pm.ZeroSumNormal("u_pb", 0.7, dims="peff"), pt.zeros(1)])
            tta, ttb = pm.HalfNormal("tau_ta", 0.7), pm.HalfNormal("tau_tb", 0.7)
            la = pm.Deterministic("log_a", A0 + upa[ix.t_peff] + _devs("a", tta, counts, ix), dims="type")
            lb = pm.Deterministic("log_b", B0 + upb[ix.t_peff] + _devs("b", ttb, counts, ix), dims="type")
            mu = pt.log(pt.exp(la[t_i]) * n + pt.exp(lb[t_i]) * n * n)
        else:
            a_c, b_c = 5e4, 2e3                          # v1's prior centres for a and b, mapped to (k, q) at n_ref
            K0 = pm.Normal("K0", math.log(a_c + b_c * n_ref), 1.5)
            Q0 = pm.Normal("Q0", math.log(b_c * n_ref / a_c), 1.5)     # logit(s) = log(b n_ref / a)
            upk = pt.concatenate([pm.ZeroSumNormal("u_pk", 0.7, dims="peff"), pt.zeros(1)])
            upq = pt.concatenate([pm.ZeroSumNormal("u_pq", 0.7, dims="peff"), pt.zeros(1)])
            ttk, ttq = pm.HalfNormal("tau_tk", 0.7), pm.HalfNormal("tau_tq", 0.7)
            kt = pm.Deterministic("k_t", K0 + upk[ix.t_peff] + ttk * pm.Normal("z_k", 0, 1, dims="type"), dims="type")
            qt = pm.Deterministic("q_t", Q0 + upq[ix.t_peff] + ttq * pm.Normal("z_q", 0, 1, dims="type"), dims="type")
            st = pt.sigmoid(qt)
            mu = pt.log(n) + kt[t_i] + pt.log1p(st[t_i] * (n / n_ref - 1.0))
            pm.Deterministic("log_a", kt + pt.log1p(-st), dims="type")
            pm.Deterministic("log_b", kt + pt.log(st) - math.log(n_ref), dims="type")
        sig = pm.HalfNormal("sigma", 1.0)
        pm.Normal("y", mu, sig, observed=ly)
        dt = pm.sample(draws=draws, tune=tune, chains=CHAINS, random_seed=seed, progressbar=False,
                       nuts_sampler="nutpie", target_accept=TARGET_ACCEPT)
    dg = diagnostics(dt)
    post = dt["posterior"].dataset
    out = {"diag": dg, "n": int(len(f)), "n_ref": n_ref, "types": {}, "_dt": dt}
    for j, t in enumerate(ix.types):
        av, bv = np.exp(post["log_a"].values[..., j]), np.exp(post["log_b"].values[..., j])
        out["types"][t] = {"a": float(np.median(av)), "a_ci": [float(np.quantile(av, .05)), float(np.quantile(av, .95))],
                           "b": float(np.median(bv)), "b_ci": [float(np.quantile(bv, .05)), float(np.quantile(bv, .95))],
                           "n_first": int((f.type == t).sum())}
    return out


# ---------------------------------------------------------------- prompt / session scopes
def scope_vars(d, seed, live):
    main = d[(d.scope == "main") & d.window_ctx.notna() & (d.window_ctx > 0)]
    sess = d[(d.scope == "session") & d.ctx.notna() & (d.ctx > 0)]
    out = {}
    specs = (("soft.prompt", main, "window_ctx"), ("hard.prompt", main, "window_ctx"),
             ("soft.prompt.orchestrator", main.iloc[0:0], "window_ctx"),
             ("soft.session", sess, "ctx"), ("hard.session", sess, "ctx"))
    for v, rows, col in specs:
        fam, _ = L.split_var(v)
        r = RISK[fam]
        anchor_var = "soft.prompt" if fam.endswith("prompt") else "hard.session"
        anchor_r = RISK["soft.prompt"] if anchor_var == "soft.prompt" else RISK["hard.session"]
        sigma, psd = 1.0, 1.0
        mu0 = G.anchor_mu(seed["vars"][anchor_var]["seed"], anchor_r, sigma, psd)
        cens = (rows.get("hit_soft", pd.Series(dtype=float)).fillna(0) == 1) if len(rows) else pd.Series(dtype=bool)
        obs = [math.log(x) for x, c in zip(rows[col], cens) if not c] if len(rows) else []
        cl = [math.log(x) for x, c in zip(rows[col], cens) if c] if len(rows) else []
        etas, w, info = G.lognormal_post(obs, cl, mu0, psd, sigma)
        lq, ci = G.lognormal_quantile(etas, w, 1 - r, sigma)
        sessions = rows.session.nunique() if len(rows) else 0
        need = (L.PROMPT_MIN_N, L.PROMPT_MIN_SESSIONS) if fam.endswith("prompt") else (0, L.SESSION_MIN_SESSIONS)
        supported = len(rows) >= need[0] and sessions >= need[1]
        T = math.exp(lq)
        cur = live["vars"][v]["value"]
        pin = PIN.get(v)
        out[v] = {"n": len(rows), "sessions": int(sessions), "T": T, "ci": [math.exp(ci[0]), math.exp(ci[1])],
                  "risk": r, "anchor": anchor_var, "supported": supported, "cur": cur, "seed": seed["vars"][v]["seed"],
                  "method": "bayes-grid" if supported else "fallback:empirical(hold)",
                  "next": cur if not supported else max(T, pin or 0), "pin": pin}
    return out


# ---------------------------------------------------------------- assembly
def _status(n, agents):
    if n == 0:
        return "prior"
    return "supported" if (n >= 5 and agents >= 3) else "pooled"


def assemble(seed, ix, agent, preds, grids, gridseb, diags, emp, live, scoped):
    rows = []
    gates = {k: model_gate(diags[k]) for k in ("turns", "ctx")}
    for t in ix.types:
        sub = agent[agent.type == t]
        n = int(len(sub))
        ag = int(sub.id.nunique())
        st = _status(n, ag)
        for fam, model, r in (("turns", "turns", RISK["turns"]), ("soft.agent", "ctx", RISK["soft.agent"]),
                              ("hard.agent", "ctx", RISK["hard.agent"])):
            v = "%s.%s" % (fam, t)
            spec = seed["vars"][v]
            p = 1 - r
            pr, gr, ge = preds[model][t], grids[model][t], gridseb[model][t]
            qd = pr["qd"][p]
            dq = qdiag(qd)
            T = pr["q"][p]
            T_r = math.ceil(T) if fam == "turns" else int(L.ceil2(T))
            if fam == "hard.agent":
                soft_T = preds["ctx"][t]["q"][1 - RISK["soft.agent"]]
                T_r = max(T_r, int(L.ceil2(L.HARD_OVER_SOFT * soft_T)))
            key = {"turns": "cur", "soft.agent": "soft_cur", "hard.agent": "hard_cur"}[fam]
            ph_cur = pr["phit"].get(key)
            ph_seed = pr["phit"].get(key.replace("cur", "seed"))
            ph_emp = pr["phit"].get(key.replace("cur", "emp_T"))
            gate_ok = gates[model] and dq["rhat"] <= GATE["rhat"] and dq["ess_bulk"] >= GATE["ess"] \
                and dq["ess_tail"] >= GATE["ess"]
            col = "api_calls" if fam == "turns" else "ctx"
            healthy = sub[~sub["cens_" + model]]
            nc = int(sub["cens_" + model].sum())
            hmax = float(healthy[col].max()) if len(healthy) else None
            cur = live["vars"][v]["value"]
            nxt, dec = decide_bayes(cur, T_r, ph_cur, r, st, spec["kind"], spec["floor"], spec["ceiling"], hmax,
                                    PIN.get(v))
            if not gate_ok:
                nxt, dec = emp[v]["next"], "fallback:empirical"
            rows.append({"var": v, "type": t, "pool": ix.pool_of[t], "fam_model": ix.fam_of[t], "n": n, "n_cens": nc,
                         "agents": ag, "status": st, "risk": r,
                         "T_bayes": T, "T_bayes_rounded": T_r,
                         "T_lo90": float(np.quantile(qd, 0.05)), "T_hi90": float(np.quantile(qd, 0.95)),
                         "T_grid_nutshyper": gr["q"][p], "T_grid_eb": ge["q"][p], "grid_edge": gr["edge_mass"],
                         "rhat_T": dq["rhat"], "ess_bulk_T": dq["ess_bulk"], "ess_tail_T": dq["ess_tail"],
                         "gate": gate_ok, "cur": cur, "seed": spec["seed"], "floor": spec["floor"],
                         "ceiling": spec["ceiling"], "emp_status": emp[v]["status"], "emp_T": emp[v]["T"],
                         "emp_next": emp[v]["next"], "phit_cur": ph_cur, "phit_seed": ph_seed, "phit_empT": ph_emp,
                         "bayes_next": nxt, "bayes_decision": dec, "hmax_healthy": hmax})
    for v, s in scoped.items():
        fam, _ = L.split_var(v)
        rows.append({"var": v, "type": None, "n": s["n"], "status": "supported" if s["supported"] else "prior",
                     "risk": s["risk"], "T_bayes": s["T"], "T_lo90": s["ci"][0], "T_hi90": s["ci"][1],
                     "gate": s["supported"], "cur": s["cur"], "seed": s["seed"], "floor": seed["vars"][v]["floor"],
                     "ceiling": seed["vars"][v]["ceiling"], "emp_status": emp[v]["status"], "emp_T": emp[v]["T"],
                     "emp_next": emp[v]["next"], "bayes_next": s["next"], "bayes_decision": s["method"]})
    return rows


def sched_table(ix, agent, preds, ab, diags):
    rows = []
    for t in ix.types:
        sub = agent[agent.type == t]
        pt_, pc, ps = preds["turns"][t], preds["ctx"][t], preds["spc"][t]
        med_d = pt_["med_d"]
        sm = preds["static_cc"][t]
        row = {"type": t, "n": int(len(sub)), "n_healthy": int((~sub.cens_turns).sum()),
               "turns_S": pt_["q"][0.25], "turns_M": pt_["q"][0.5], "turns_L": pt_["q"][0.9],
               "turns_band_lo": float(np.quantile(pt_["qd"][0.5], 0.05)), "turns_band_hi": float(np.quantile(pt_["qd"][0.5], 0.95)),
               "spc_p50": ps["q"][0.5], "spc_p90": ps["q"][0.9],
               "spc_band_lo": float(np.quantile(ps["qd"][0.5], 0.05)), "spc_band_hi": float(np.quantile(ps["qd"][0.5], 0.95)),
               "ctx_med": pc["q"][0.5], "ctx_pi90": [pc["q"][0.05], pc["q"][0.95]],
               "static_cc_q10": sm["q"][0.1], "ctx_a": ab["types"][t]["a"], "ctx_b": ab["types"][t]["b"],
               "ctx_a_ci": ab["types"][t]["a_ci"], "ctx_b_ci": ab["types"][t]["b_ci"]}
        if "tool_calls" in preds:
            row["tool_calls_med"] = preds["tool_calls"][t]["q"][0.5] - 1
            row["tool_calls_p90"] = preds["tool_calls"][t]["q"][0.9] - 1
        h = sub[~sub.cens_turns]
        if len(h):
            row["emp_turns_p50"] = float(np.quantile(h.api_calls, 0.5))
            row["emp_turns_p90"] = float(np.quantile(h.api_calls, 0.9))
        rows.append(row)
    return rows


def example_prov(table, meta, path):
    """What proposals.json / live.json / snapshot would carry per variable (design.md section 6)."""
    ex = {}
    for r in table:
        if r["var"] in ("turns.claude-code-engineer", "soft.agent.orchestrator", "hard.agent.coder",
                        "soft.agent.scout", "soft.prompt.orchestrator", "hard.session"):
            ex[r["var"]] = {"method": "bayes-nuts" if r.get("gate") else r.get("bayes_decision"),
                            "model": "turns-nb-h1" if r["var"].startswith("turns") else "ctx-ln-h1",
                            "risk": r["risk"], "T": r.get("T_bayes_rounded") or r.get("T_bayes"),
                            "pi90": [r.get("T_lo90"), r.get("T_hi90")], "p_hit_cur": r.get("phit_cur"),
                            "status": r["status"], "n": r["n"], "n_cens": r.get("n_cens"), "agents": r.get("agents"),
                            "diag": {"rhat": r.get("rhat_T"), "ess_bulk": r.get("ess_bulk_T"),
                                     "ess_tail": r.get("ess_tail_T")},
                            "fit": {"evidence_id": meta["evidence_id"], "data_sha256": meta["files"],
                                    "seed": meta["seed"], "versions": meta["versions"],
                                    "code": meta["code_version"]}}
    json.dump(ex, open(path, "w"), indent=1, default=float)


# ---------------------------------------------------------------- sensitivity: status_code 1/2 not censored
def sensitivity(d, seed, ix, models, draws, tune, preds):
    """status_code 1 with unmeasured hits: censored everywhere ("all") or nowhere ("none") vs "near"."""
    out = {"types": {}}
    for mode in ("all", "none"):
        a2 = window_cap(agent_frame(d, seed, mode))
        out["n_cens_" + mode] = {"turns": int(a2.cens_turns.sum()), "ctx": int(a2.cens_ctx.sum())}
        p_resume = float(a2.resume.mean())
        for name, ycol, kind, center, p in (("turns", "api_calls", "nb", math.log(10), 1 - RISK["turns"]),
                                            ("ctx", "ctx", "ln", math.log(1e6), 1 - RISK["soft.agent"])):
            dt, dg = fit_hier(with_cens(a2, name), ycol, kind, ix, center, draws, tune, seed=SEED + 7, **PARAM[name])
            pr = (pred_nb if kind == "nb" else pred_ln)(dt, ix, p_resume, (p,))
            out["%s_diag_%s" % (name, mode)] = dg
            for t in ix.types:
                e = out["types"].setdefault(t, {}).setdefault(name, {"near": preds[name][t]["q"][p]})
                e[mode] = pr[t]["q"][p]
    return out


# ---------------------------------------------------------------- rolling-origin backtest
def clustered_hits(dt, kind, ix, units, n_sim=4000, seed=SEED):
    """Session-clustered predictive of the number of cap hits among a test session's scorable (uncensored) rows:
    per posterior draw, one new-session effect w_s ~ N(0, tau_s) shared by every row and one w_ts[t] ~ N(0, tau_ts)
    per type (the generative story of design.md 2), then each row hits with P(Y > T_i | draw, w). The iid Jeffreys
    interval ignores that every row of one test session shares w; this check does not.
    units: list of (type, resume, T). Returns an int array of simulated hit counts (n_sim,)."""
    rng = np.random.default_rng(seed)
    post = dt["posterior"].dataset
    eta = post["eta_type"].values.reshape(-1, len(ix.types))
    m = eta.shape[0]
    pick = rng.integers(0, m, n_sim)
    z = np.zeros(m)
    ts = (post["tau_s"].values.ravel() if "tau_s" in post else z)[pick]
    tts = (post["tau_ts"].values.ravel() if "tau_ts" in post else z)[pick]
    rho = (post["rho"].values.ravel() if "rho" in post else z)[pick]
    sc = np.exp(post["log_alpha_t" if kind == "nb" else "log_sigma_t"].values.reshape(m, -1))[pick]
    eta = eta[pick]
    w_s = rng.standard_normal(n_sim) * ts
    tidx = sorted({ix.types.index(t) for t, _, _ in units})
    w_t = {j: rng.standard_normal(n_sim) * tts for j in tidx}
    k = np.zeros(n_sim, int)
    for t, r, T in units:
        j = ix.types.index(t)
        lin = eta[:, j] + rho * r + w_s + w_t[j]
        if kind == "nb":
            a = sc[:, j]
            p_hit = sst.nbinom.sf(math.floor(T) - 1, a, a / (a + np.exp(lin)))     # P(Y - 1 >= floor T) = P(Y > T)
        else:
            p_hit = sst.norm.sf((math.log(T) - lin) / sc[:, j])
        k += rng.random(n_sim) < p_hit
    return k


def backtest(d, seed, models, draws, tune):
    agent_all = agent_frame(d, seed)
    csim = {}                                    # fam -> list of per-fold simulated hit counts (summed later)
    starts = agent_all.groupby("session").first_ts.min().sort_values()
    rows, folds = [], []
    for k in range(1, len(starts)):
        s_test, origin = starts.index[k], float(starts.iloc[k])
        train = agent_all[agent_all.ts < origin]
        test = agent_all[agent_all.session == s_test]
        if len(train) < 30 or not len(test):
            continue
        train = window_cap(train)
        ix = Index(seed, models, sorted(train.session.unique()))
        pr_ = float(train.resume.mean())
        fold = {"test_session": s_test, "origin": origin, "n_train": int(len(train)), "n_test": int(len(test))}
        train_all, test_all = train, test
        for name, ycol, kind, center, fams in (("turns", "api_calls", "nb", math.log(10), ("turns",)),
                                               ("ctx", "ctx", "ln", math.log(1e6), ("soft.agent", "hard.agent"))):
            train, test = with_cens(train_all, name), with_cens(test_all, name)
            probs = tuple(sorted({1 - RISK[f] for f in fams} | {0.05, 0.25, 0.5, 0.75, 0.95}))
            dt, dg = fit_hier(train, ycol, kind, ix, center, draws, tune, seed=SEED + 10 + k, **PARAM[name])
            fold[name + "_diag"] = dg
            pr = (pred_nb if kind == "nb" else pred_ln)(dt, ix, pr_, probs)
            heb = hyper_eb(train, ycol, kind, ix)
            kmax_of = {t: int(2 * seed["vars"]["turns." + t]["ceiling"]) + 50 for t in ix.types}
            ge = grid_values(train, ycol, kind, ix, heb, probs, pr_, None, kmax_of)
            units = {f: [] for f in fams}
            for _, r in test.iterrows():
                t = r["type"]
                ntr = int((train.type == t).sum())
                y, c = float(r[ycol]), bool(r["cens"])
                if kind == "nb":
                    Fd = pr[t]["Fd"]
                    F_hi = float(Fd(y - 1).mean())
                    F_lo = float(Fd(y - 2).mean()) if y >= 2 else 0.0
                    pit = 0.5 * (F_lo + F_hi)
                else:
                    pit = float(pr[t]["F"](math.log(y)))
                for fam in fams:
                    rk = RISK[fam]
                    p = 1 - rk
                    T_b = pr[t]["q"][p] if ntr > 0 else None
                    T_g = ge[t]["q"][p] if ntr > 0 else None
                    seedv = seed["vars"]["%s.%s" % (fam, t)]["seed"]
                    rule = "soft" if fam == "soft.agent" else "hard"
                    soft_ref = None
                    if fam == "hard.agent":
                        soft_ref = emp_target_from_rows(train[train.type == t], ycol, "soft")
                    T_e = emp_target_from_rows(train[train.type == t], ycol, rule, soft_ref)
                    rec = {"fold": k, "test_session": s_test[:8], "type": t, "fam": fam, "risk": rk, "y": y, "cens": c,
                           "n_train_type": ntr, "pit": pit if not c else None,
                           "T_bayes": T_b, "T_grid_eb": T_g, "T_emp": T_e, "T_seed": seedv}
                    if fam == "hard.agent" and T_b is not None:
                        rec["T_bayes"] = max(T_b, L.HARD_OVER_SOFT * pr[t]["q"][1 - RISK["soft.agent"]])
                    for est in ("bayes", "grid_eb", "emp", "seed"):
                        T = rec["T_" + est]
                        if T is None:
                            rec["hit_" + est] = None
                        elif c:
                            rec["hit_" + est] = 1 if y > T else None     # censored below T: unknown
                        else:
                            rec["hit_" + est] = int(y > T)
                    if rec["T_bayes"] is not None:          # every test row; censored rows bound the count
                        units[fam].append((t, float(r["resume"]), float(rec["T_bayes"]), int(y > rec["T_bayes"]),
                                           int(c and y <= rec["T_bayes"])))
                    rows.append(rec)
            for fam in fams:
                if units[fam]:
                    ks = clustered_hits(dt, kind, ix, [u[:3] for u in units[fam]], seed=SEED + 50 + k)
                    k_lo = sum(u[3] for u in units[fam])          # known hits (a censored row above T is a hit)
                    k_hi = k_lo + sum(u[4] for u in units[fam])   # + censored rows below T (outcome unknown)
                    fold[fam + "_clustered"] = {"n": len(units[fam]), "hits_lo": k_lo, "hits_hi": k_hi,
                                                "pred_mean": float(ks.mean()), "pred90": [int(np.quantile(ks, .05)), int(np.quantile(ks, .95))],
                                                "p_ge_lo": float(np.mean(ks >= k_lo)), "p_le_hi": float(np.mean(ks <= k_hi))}
                    csim.setdefault(fam, []).append((ks, k_lo, k_hi, len(units[fam])))
        folds.append(fold)
    df = pd.DataFrame(rows)
    summ = {"folds": folds, "by_fam": {}}
    for fam, g in df.groupby("fam"):
        s = {"n_rows": int(len(g)), "risk": float(g.risk.iloc[0])}
        for est in ("bayes", "grid_eb", "emp", "seed"):
            h = g["hit_" + est].dropna()
            k_, n_ = int(h.sum()), int(len(h))
            lo, hi = (sst.beta.ppf(0.05, k_ + 0.5, n_ - k_ + 0.5), sst.beta.ppf(0.95, k_ + 0.5, n_ - k_ + 0.5)) if n_ else (None, None)
            s[est] = {"hits": k_, "n": n_, "rate": (k_ / n_) if n_ else None, "jeffreys90": [lo, hi]}
        pit = g.pit.dropna().values
        if len(pit):
            s["pit_n"] = int(len(pit))
            s["coverage50"] = float(np.mean((pit > 0.25) & (pit < 0.75)))
            s["coverage90"] = float(np.mean((pit > 0.05) & (pit < 0.95)))
            s["pit_ks_p"] = float(sst.kstest(pit, "uniform").pvalue)
        s["by_fold"] = {}
        for fk, gf in g.groupby("fold"):
            h = gf["hit_bayes"].dropna()
            he = gf["hit_emp"].dropna()
            s["by_fold"][int(fk)] = {"bayes": [int(h.sum()), int(len(h))], "emp": [int(he.sum()), int(len(he))]}
        if fam in csim:                           # all folds together: independent sessions, simulated counts add
            ks = sum(x[0] for x in csim[fam])
            k_lo, k_hi, n_u = (sum(x[i] for x in csim[fam]) for i in (1, 2, 3))
            s["clustered"] = {"n": n_u, "hits_lo": k_lo, "hits_hi": k_hi, "pred_mean": float(ks.mean()),
                              "pred90": [int(np.quantile(ks, .05)), int(np.quantile(ks, .95))],
                              "p_ge_lo": float(np.mean(ks >= k_lo)), "p_le_hi": float(np.mean(ks <= k_hi))}
        summ["by_fam"][fam] = s
    return {"rows": rows, "summary": summ}


# ---------------------------------------------------------------- tables
def _f(v, unit="ctx"):
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return "-"
    if unit == "turns":
        return "%d" % round(v)
    if unit == "p":
        return "%.3f" % v
    return L.fmt(v, "ctx")


def write_tables(out, meta, diags, table, sched, scoped, bt, s2, sens, ppcs, fam_cmp, extras):
    L_ = []
    w = L_.append
    w("# B1 prototype tables (generated by fit_prototype.py; do not edit)\n")
    w("evidence_id %s; rows %d agent rows (censored %s); p_resume %.3f; versions %s; seed %d; %d chains x %d draws "
      "(+%d tune); elapsed %.0fs\n" % (meta["evidence_id"], meta["n_agent_rows"], json.dumps(meta["n_censored"]), meta["p_resume"],
                                       json.dumps(meta["versions"]), meta["seed"], meta["chains"], meta["draws"],
                                       meta["tune"], meta.get("elapsed_s", 0)))
    w("## Diagnostics per model\n")
    w("| model | R-hat max | ESS bulk min | ESS tail min | divergences | E-BFMI min | gate |")
    w("|---|---|---|---|---|---|---|")
    for k, dg in diags.items():
        w("| %s | %.4f | %.0f | %.0f | %d | %.2f | %s |" % (k, dg["rhat_max"], dg["ess_bulk_min"], dg["ess_tail_min"],
                                                         dg["divergences"], dg["ebfmi_min"], "pass" if model_gate(dg) else "FAIL"))
    w("\n## Prior predictive check (pooled over the observed rows' types and sessions)\n")
    w("| model | prior q05 / q50 / q95 / q99 | share above %s | observed q05 / q50 / q95 |" % "largest ceiling")
    w("|---|---|---|---|")
    for k, u in (("prior_turns", "turns"), ("prior_ctx", "ctx")):
        e = extras[k]
        w("| %s | %s / %s / %s / %s | %.3f (> %s) | %s / %s / %s |" % (
            k, _f(e["q05"], u), _f(e["q50"], u), _f(e["q95"], u), _f(e["q99"], u), e["share_above_ceiling"],
            _f(e["ceiling"], u), _f(e["obs_q05"], u), _f(e["obs_q50"], u), _f(e["obs_q95"], u)))
    rc, fx = extras["resume_ctx"], extras["fixer"]
    w("\n## Global scheduler quantities\n")
    if "alpha" in rc:
        w("- resume_ctx (Student-t, n = %d resumes from %d agents): alpha %s [%s, %s], gamma %.0f [%.0f, %.0f] (90%% ETI)"
          % (rc["n"], rc["n_agents"], L.fmt(rc["alpha"]), L.fmt(rc["alpha_ci"][0]), L.fmt(rc["alpha_ci"][1]),
             rc["gamma"], rc["gamma_ci"][0], rc["gamma_ci"][1]))
    else:
        w("- resume_ctx: %s (n = %d)" % (rc.get("status"), rc["n"]))
    if fx.get("n"):
        w("- fixer reread (NIG conjugate, stdlib): %s [%s, %s] (95%% ETI of the median), n = %d from %d agents, gate %s;"
          " empirical median %s" % (L.fmt(fx["reread"]), L.fmt(fx["ci95"][0]), L.fmt(fx["ci95"][1]), fx["n"],
                                    fx["n_agents"], fx["gate"], L.fmt(fx["empirical_median"])))
    else:
        w("- fixer: no rows")
    w("\n## Likelihood family (PSIS-LOO, raw scale; positive = log-normal better)\n")
    w("| quantity | elpd log-normal | elpd gamma | d_elpd (LN - gamma) | paired SE | Pareto k > good_k (LN / gamma) |")
    w("|---|---|---|---|---|---|")
    for q, c in fam_cmp.items():
        w("| %s | %.1f | %.1f | %.1f | %.1f | %d / %d |" % (q, c["ln_elpd"], c["gamma_elpd"], c["d_elpd"], c["se"],
                                                          c["a_bad_k"], c["b_bad_k"]))
    w("\n## Limits: Bayes vs section 4 (observed types, plus the scoped variables)\n")
    w("T = posterior-predictive quantile at 1 - risk (rounded as the proposer would: turns up to an integer, ctx ceil2;"
      " hard.agent >= 2 x soft T); [lo, hi] = 90% ETI of T; p_hit(cur) = predicted P(new run > current value).\n")
    w("| var | n (cens) | status | risk | T bayes [90%] | grid|NUTS-hyper | grid|EB | cur | p_hit(cur) | sec4 T | sec4 next | bayes next (decision) |")
    w("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in table:
        if r.get("type") is not None and r["n"] == 0:
            continue
        u = "turns" if r["var"].startswith("turns") else "ctx"
        w("| %s | %s (%s) | %s | %s | %s [%s, %s] | %s | %s | %s | %s | %s | %s | %s (%s) |" % (
            r["var"], r["n"], r.get("n_cens", "-"), r["status"], r["risk"],
            _f(r.get("T_bayes_rounded") or r["T_bayes"], u), _f(r["T_lo90"], u), _f(r["T_hi90"], u),
            _f(r.get("T_grid_nutshyper"), u), _f(r.get("T_grid_eb"), u), _f(r["cur"], u),
            _f(r.get("phit_cur"), "p"), _f(r["emp_T"], u), _f(r["emp_next"], u), _f(r["bayes_next"], u),
            r["bayes_decision"]))
    nprior = sum(1 for r in table if r.get("type") is not None and r["n"] == 0)
    w("\n%d type variables have no own rows (status prior: value holds; their predictive is the pool's).\n" % nprior)
    w("## Scheduler estimates (observed types)\n")
    w("| type | n | turns S/M/L bayes | band M [90%] | emp p50/p90 | spc p50/p90 s | ctx a / b | static_cc q10 |")
    w("|---|---|---|---|---|---|---|---|")
    for r in sched:
        if r["n"] == 0:
            continue
        w("| %s | %d | %d/%d/%d | [%.0f, %.0f] | %s/%s | %.1f/%.1f | %s / %.0f | %s |" % (
            r["type"], r["n"], r["turns_S"], r["turns_M"], r["turns_L"], r["turns_band_lo"], r["turns_band_hi"],
            _f(r.get("emp_turns_p50"), "turns"), _f(r.get("emp_turns_p90"), "turns"), r["spc_p50"], r["spc_p90"],
            L.fmt(r["ctx_a"]), r["ctx_b"], L.fmt(r["static_cc_q10"])))
    w("\n## Sensitivity: status_code 1/2 censored (design) vs observed\n")
    w("censored rows: near %s; all %s; none %s\n" % (json.dumps(meta["n_censored"]), json.dumps(sens["n_cens_all"]),
                                                    json.dumps(sens["n_cens_none"])))
    w("| type | turns q99 near / all / none | soft ctx q95 near / all / none |")
    w("|---|---|---|")
    for t, v in sens["types"].items():
        if t in {r["type"] for r in sched if r["n"] >= 5}:
            w("| %s | %d / %d / %d | %s / %s / %s |" % (t, v["turns"]["near"], v["turns"]["all"], v["turns"]["none"],
                                                     L.fmt(v["ctx"]["near"]), L.fmt(v["ctx"]["all"]), L.fmt(v["ctx"]["none"])))
    w("\n## Posterior predictive check (in-sample, each row's own session effect)\n")
    w("Observed vs predicted fraction of rows above a threshold (censored rows count as above when their lower bound is).\n")
    w("| quantity | type | n | threshold | observed | predicted (rows' sessions) | predicted (new session) |")
    w("|---|---|---|---|---|---|---|")
    for q, per in ppcs.items():
        for t, rs in per.items():
            for r in rs:
                u = "turns" if q == "turns" else "ctx"
                w("| %s | %s | %d | %s %s | %.3f | %.3f | %.3f |" % (q, t, r["n"], r["label"], _f(r["c"], u), r["obs"],
                                                                 r["pred_in"], r["pred_new"]))
    if bt:
        w("\n## Rolling-origin held-out calibration (origin = each session's start; train = rows ended before it)\n")
        for f in bt["summary"]["folds"]:
            w("- fold test %s: train %d rows, test %d rows; turns R-hat %.3f div %d; ctx R-hat %.3f div %d" % (
                f["test_session"][:8], f["n_train"], f["n_test"], f["turns_diag"]["rhat_max"], f["turns_diag"]["divergences"],
                f["ctx_diag"]["rhat_max"], f["ctx_diag"]["divergences"]))
        w("\n| family | risk target | bayes hits/n (rate) [90% Jeffreys] | grid-EB | section 4 | seed | PIT n | cov50 | cov90 | KS p |")
        w("|---|---|---|---|---|---|---|---|---|---|")
        for fam, s in bt["summary"]["by_fam"].items():
            cell = lambda e: "%d/%d (%s) [%s, %s]" % (s[e]["hits"], s[e]["n"], _f(s[e]["rate"], "p"),  # noqa: E731
                                                     _f(s[e]["jeffreys90"][0], "p"), _f(s[e]["jeffreys90"][1], "p"))
            w("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
                fam, s["risk"], cell("bayes"), cell("grid_eb"), cell("emp"), cell("seed"), s.get("pit_n", "-"),
                _f(s.get("coverage50"), "p"), _f(s.get("coverage90"), "p"), _f(s.get("pit_ks_p"), "p")))
        w("\nHits per fold (bayes k/n; section 4 k/n):\n")
        for fam, s in bt["summary"]["by_fam"].items():
            w("- %s: %s" % (fam, "; ".join("fold %d: %d/%d; %d/%d" % (k, v["bayes"][0], v["bayes"][1], v["emp"][0], v["emp"][1])
                                           for k, v in s["by_fold"].items())))
        w("\nSession-clustered predictive of the Bayes hit count over every test row (one new-session effect per test"
          " session; observed hits are an interval: known hits .. known + censored rows below T):\n")
        w("| family | risk | hits [lo, hi] / n | predicted mean [90%] | P(K >= lo) | P(K <= hi) |")
        w("|---|---|---|---|---|---|")
        for fam, s in bt["summary"]["by_fam"].items():
            c = s.get("clustered")
            if c:
                w("| %s | %s | [%d, %d] / %d | %.1f [%d, %d] | %.3f | %.3f |" % (
                    fam, s["risk"], c["hits_lo"], c["hits_hi"], c["n"], c["pred_mean"], c["pred90"][0], c["pred90"][1],
                    c["p_ge_lo"], c["p_le_hi"]))
    if s2:
        L_.extend(scope2_lines(s2))
    open(os.path.join(out, "tables.md"), "w").write("\n".join(L_) + "\n")



def scope2_lines(s2):
    L_ = []
    w = L_.append
    w("\n## Scope 2 (provisional): P(pass) by agent, ordinal model\n")
    w("n = %d graded units of %d (%s; excluded, not graded: %s); source %s; installs %s; grade files %s" % (
        s2["n"], s2.get("n_units", s2["n"]), s2["n_by_grade"], s2.get("excluded_grades", {}),
        (s2.get("source") or {}).get("source", "-"), s2.get("installs", ["old_install"]), s2["grades_files"]))
    src = s2.get("source") or {}
    if "mismatch_vs_grade_files" in src:
        w("\nunits by install/variant %s; runs_before grade vs grade files: %d mismatches %s" % (
            src["units_by_install_variant"], len(src["mismatch_vs_grade_files"]), src["mismatch_vs_grade_files"]))
    w("\ndiagnostics %s; gate %s; b_match 5/50/95%% = %s; b_install (new vs old) 5/50/95%% = %s; n by install %s\n" % (
        json.dumps(s2["diag"]), "pass" if s2["gate"] else "FAIL", [round(x, 2) for x in s2["b_match"]],
        None if not s2.get("b_install") else [round(x, 2) for x in s2["b_install"]], s2.get("n_by_install")))
    w("| agent | n | P(pass) mean [90%] (match, current install) | Beta(1,1) unpooled mean | tokens median |")
    w("|---|---|---|---|---|")
    for r in sorted(s2["agents"], key=lambda r: -r["p_pass_mean"]):
        w("| %s | %d | %.2f [%.2f, %.2f] | %.2f | %s |" % (r["agent"], r["n"], r["p_pass_mean"], r["p_pass_lo"],
                                                        r["p_pass_hi"], r["beta_pass_mean"], L.fmt(r["tokens_med"])))
    w("\n| agent x family x install | n | pass | match | P(pass) [90%] |")
    w("|---|---|---|---|---|")
    for r in s2["cells"]:
        w("| %s x %s x %s | %d | %d | %d | %.2f [%.2f, %.2f] |" % (
            r["agent"], r["family"], r.get("install", "old_install"), r["n"], r["n_pass"], r["match"],
            r["p_pass_mean"], r["p_pass_lo"], r["p_pass_hi"]))
    return L_


if __name__ == "__main__":
    sys.exit(main())
