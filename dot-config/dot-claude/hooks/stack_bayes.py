"""stack_bayes.py - the detached Bayes fitter of the learned limits and the scheduler estimates
(docs/BAYES.md sections 1, 2.1, 2.2, A and B; plan row WP3b).

Run only by stack_usage.bayes_fit() when a session's collector exits (after propose(), before the scheduler
refresh): the tools venv's interpreter with its opt-in Bayes lock (pymc, pytensor, nutpie, arviz, scipy,
numpy), niced, under usage/bayes.lock and <state>/accel.lock, with a 900 s timeout, at most once per evidence
id and once per 6 h:

  <config>/venvs/tools/bin/python -I stack_bayes.py fit [--out FILE] [--chains N] [--draws N] [--tune N]
                                                        [--seed N] [--no-sched] [--timeout S] [--regime HEX16]
  <config>/venvs/tools/bin/python -I stack_bayes.py check        exit 0 when the Bayes stack imports, else 3

--regime (BAYES.md A.11.3, the fold driver): the regime the fit treats as current, in place of proposals.json's
`regime` or stack_limits.current_regime(); 16 lowercase hex digits, else the fit fails before it starts.

`fit` ends itself after --timeout seconds (FIT_TIMEOUT_S: the collector's 900 s plus 30 s): SIGALRM with its
default action, which the kernel carries out whatever the sampler's threads are doing, so a fit orphaned by a
SIGKILLed collector releases the inherited locks by then (docs/BAYES.md 2.8).

It reads what the proposer reads (stack_limits.read_rows over usage/runs*.csv, so the same evidence id; the
seed; the session snapshots for the censoring proxy; proposals.json for support and the current regime),
fits the hierarchical models of BAYES.md 1.2/1.3 with NUTS (no reports, no backtest, no LOO: those are the
prototype's, docs/bayes/b1v2/fit_prototype.py) and writes limits/bayes.json atomically: the tier-nuts blocks
of turns.<t>, soft.agent.<t> and hard.agent.<t>, the turns/ctx hyperparameters (the grid tier's input), the
NaN-strict model diagnostics and the `sched` block (2.2). Nothing acts on it but stack_limits' apply, which
runs Bayes in shadow (STACK_BAYES=shadow, BAYES_LIVE empty), and the scheduler refresh after a promotion.
The document is checked with stack_limits' own reader first: one the reader would refuse is never written.

Rules this file adds to the contract (WP2 findings, BAYES.md 2.1 rule 4 and A.4):
- clamp at the cap: a block's T, T_raw, pi90 and qtab.x are clamped to [0, CTX_MAX] (ctx) or to the turns
  sweep's end (<= KMAX < TURNS_MAX), and `at_bound` is set when any was clamped; a T beyond the turns sweep
  has no MCSE (null), so its block fails the quantity gate;
- MCSE(T) by the delta method: T solves Fbar(T) = p with Fbar the mean over draws of the per-draw predictive
  CDF F_d, so MCSE(T) = MCSE(mean of F_d(T)) / fbar(T), where the MCSE of that mean uses the split-chain
  autocorrelation ESS (Geyer's initial monotone sequence, as arviz) over every draw; mcse_rel = MCSE(T)/T
  (the log-scale density for the log-normal, the interpolated pmf for the NB). It replaces WP2's batch
  means over 20 batches, whose own sampling noise moved blocks across the 2 % gate between two runs with
  one seed;
- 8 chains x 4000 draws after 2000 tuning (WP2: 4 x 3000 left the supported blocks' MCSE at the gate;
  WP3b on the WP2 copy: 8 x 3000 left 10/57 hard.agent blocks above 2 %, 8 x 4000 1/57, in 348 s vs 276 s).
- the drift check (BAYES.md 2.1 rule 7, A.12; WP5 5c): a posterior predictive check of the last 5 sessions'
  rows per model (turns; ctx for soft.agent and hard.agent), randomized PITs, two-sided KS with a
  session-clustered Monte Carlo p, and a sticky breach carried through the bayes.json on disk.

Exit 0 written; 3 skipped:no-pymc (a dependency does not import: nothing written, no traceback); 4
skipped:no-rows; 1 failed (nothing written). The last stdout line is the summary "bayes: ...".
"""
import argparse
import hashlib
import importlib.util
import json
import math
import os
import signal
import sys
import time

try:
    import numpy as np
except ImportError:                 # reported by the dependency check (exit 3), never a traceback
    np = None

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:            # -I leaves the script's folder off sys.path; the hooks folder is ours
    sys.path.insert(0, HERE)
import stack_limits as L  # noqa: E402  (stdlib)
from stack_io import write_atomic  # noqa: E402

SEED = 20261003
CHAINS = 8
DRAWS = 4000
TUNE = 2000
TARGET_ACCEPT = 0.98
KMAX = 5000                         # the turns sweep never passes this (< stack_limits.TURNS_MAX)
SWEEP_FACTOR = 4                    # a type's turns sweep ends at max(SWEEP_MIN, 4 x its ceiling): a larger T
SWEEP_MIN = 400                     # acts as the ceiling (A.2 L1), so it is reported at_bound, not computed
RETIRE_EPS = 1e-12                  # a draw whose CDF is within this of 1 leaves the sweep (contributes 1)
CODE = "stack_bayes/1"
DEPS = ("numpy", "scipy", "pymc", "pytensor", "nutpie", "arviz")
EXIT_OK, EXIT_FAIL, EXIT_NO_PYMC, EXIT_NO_ROWS = 0, 1, 3, 4
FIT_TIMEOUT_S = 930                 # the fit's own cap: stack_usage.BAYES_TIMEOUT_S (900) + 30, so while the
                                    # collector lives its kill (failed:timeout) comes first; this one ends an orphan
TIMEOUT_MAX_S = 86400
MODEL_ID = {"turns": "turns-nb2s-h4", "ctx": "ctx-ln-h4", "spc": "spc-ln-h4", "static_cc": "static_cc-ln-h2",
            "ctx_ab": "ctx_ab-kq-h2", "resume_ctx": "resume_ctx-t-1"}
ZERO_AVOID = ("tau_t", "tau_s", "tau_ts")
SCHED_GATES = {"turns": "turns", "spc": "spc", "ctx_ab": "ctx_ab", "static_cc": "static_cc"}
MIN_SEG, MIN_AGENTS = 5, 3          # derive_sched_model's support (stack_sched_refresh recomputes it)
# the drift check (BAYES.md A.12)
DRIFT_FAMILIES = {"turns": ("turns",), "ctx": ("soft.agent", "hard.agent")}    # model -> families (one PIT set)
DRIFT_SESSIONS = 5                  # the last 5 sessions of the window with a row of the model
DRIFT_MIN_ROWS, DRIFT_MIN_UNCENS, DRIFT_MIN_SESSIONS = 20, 10, 3
DRIFT_ALPHA = 0.01                  # breach when the clustered KS p < 0.01
DRIFT_B = 999                       # Monte Carlo replicates: p = (1 + #{D* >= D}) / (B + 1) >= 0.001
DRIFT_DRAWS = 400                   # posterior draws (evenly thinned) that average the predictive CDF
DRIFT_GRID = 2049                   # log-scale grid of a log-normal predictive CDF (linear interpolation)
DRIFT_EPS = 1e-10                   # an NB CDF table ends where the mixture CDF reaches 1 - eps
DRIFT_STREAM = 0xD21F7              # the drift RNG: default_rng((sampler seed, DRIFT_STREAM, model index))
SUMMARY_MAX = 287                   # stack_usage.SUMMARY_RE keeps a summary line of "bayes: " + at most 280 chars
EXTRA_COLS = {"wall_s": 1e8, "first_cc": L.CTX_MAX, "first_ctx": L.CTX_MAX, "ctx_at_first_write": L.CTX_MAX,
              "prev_peak": L.CTX_MAX}


# ---------------------------------------------------------------- environment
def cache_dirs(root=None):
    """(pytensor, numba) compile caches: <state>/bayes-cache/{pytensor,numba}."""
    base = os.path.join(root or L.state_root(), "bayes-cache")
    return os.path.join(base, "pytensor"), os.path.join(base, "numba")


def cache_env(root=None):
    """PYTENSOR_FLAGS and NUMBA_CACHE_DIR inside the state directory (never a shared /tmp): the compiled
    code the fit loads is as private as the state it comes from. No C compiler (cxx=): pytensor runs its
    NUMBA backend. stack_usage.bayes_env() sets the same values for the child."""
    pyt, nb = cache_dirs(root)
    return {"PYTENSOR_FLAGS": "base_compiledir=%s,cxx=,mode=NUMBA" % pyt, "NUMBA_CACHE_DIR": nb}


def arm_deadline(secs):
    """The fit's own wall-clock cap: SIGALRM after `secs` with its default action (terminate). No Python
    handler: one would wait for the main thread to leave a long C call (NUTS, a numba compile), the default
    action does not. Returns the previous SIGALRM disposition for disarm_deadline; None off the main thread
    (no cap here then; the collector's timeout still holds while it lives)."""
    try:
        prev = signal.signal(signal.SIGALRM, signal.SIG_DFL)
    except ValueError:
        return None
    signal.alarm(int(secs))
    return prev


def disarm_deadline(prev):
    if prev is None:
        return
    signal.alarm(0)
    signal.signal(signal.SIGALRM, prev)


def missing_deps():
    """The Bayes stack's modules that do not resolve (importlib.util.find_spec: nothing is imported)."""
    out = []
    for name in DEPS:
        try:
            if importlib.util.find_spec(name) is None:
                out.append(name)
        except (ImportError, ValueError):
            out.append(name)
    return out


# ---------------------------------------------------------------- Monte Carlo error (numpy only)
def split_chains(x):
    x = np.asarray(x, float)
    if x.ndim == 1:
        x = x[None, :]
    half = x.shape[1] // 2
    return np.vstack((x[:, :half], x[:, -half:]))


def _autocov(x):
    n = x.shape[1]
    x = x - x.mean(axis=1, keepdims=True)
    f = np.fft.rfft(x, n=2 * n, axis=1)
    return np.fft.irfft(f * np.conjugate(f), n=2 * n, axis=1)[:, :n] / n


def ess_of(x):
    """arviz-stats' _ess (Stan's multi-chain ESS with Geyer's initial positive and monotone sequences) of a
    (chain, draw) array, as written in arviz_stats/base/diagnostics.py."""
    x = np.asarray(x, float)
    if np.max(x) - np.min(x) < np.finfo(float).resolution:
        return float(x.size)
    m, n = x.shape
    acov = _autocov(x)
    mean_var = np.mean(acov[:, 0]) * n / (n - 1.0)
    var_plus = mean_var * (n - 1.0) / n
    if m > 1:
        var_plus += np.var(x.mean(axis=1), ddof=1)
    rho = np.zeros(n)
    even, odd = 1.0, 1.0 - (mean_var - np.mean(acov[:, 1])) / var_plus
    rho[0], rho[1] = even, odd
    t = 1
    while t < n - 3 and even + odd > 0.0:
        even = 1.0 - (mean_var - np.mean(acov[:, t + 1])) / var_plus
        odd = 1.0 - (mean_var - np.mean(acov[:, t + 2])) / var_plus
        if even + odd >= 0:
            rho[t + 1], rho[t + 2] = even, odd
        t += 2
    max_t = t - 2
    if even > 0:
        rho[max_t + 1] = even
    t = 1
    while t <= max_t - 2:
        if rho[t + 1] + rho[t + 2] > rho[t - 1] + rho[t]:
            rho[t + 1] = rho[t + 2] = (rho[t - 1] + rho[t]) / 2.0
        t += 2
    tau = -1.0 + 2.0 * np.sum(rho[:max_t + 1]) + np.sum(rho[max_t + 1:max_t + 2])
    tau = max(tau, 1.0 / np.log10(x.size))
    return float("nan") if np.isnan(rho).any() else float(x.size / tau)


def mcse_mean(x):
    """MCSE of the mean of a (chain, draw) array: sd / sqrt(split-chain ESS), arviz's mcse(method="mean")."""
    x = np.asarray(x, float)
    if np.max(x) - np.min(x) < np.finfo(float).resolution:
        return 0.0
    return float(np.std(x, ddof=1) / math.sqrt(ess_of(split_chains(x))))


def delta_mcse(F_at_T, density):
    """MCSE of the mixture quantile T (Fbar(T) = p) by the delta method: the MCSE of the mean of the
    per-draw CDFs at T over the mixture's density at T. Same units as the density's variable (log T for a
    log-scale density: then it is MCSE(T)/T). None when the density is not positive (T at the sweep's end)."""
    if not (density > 0) or not math.isfinite(density):
        return None
    return mcse_mean(F_at_T) / density


# ---------------------------------------------------------------- predictive distributions
_NDTR = []


def ndtr(x):
    """Standard normal CDF (scipy.special.ndtr; the slow math.erfc route only where scipy is absent: tests)."""
    if not _NDTR:
        try:
            from scipy.special import ndtr as f
        except ImportError:
            v = np.vectorize(lambda z: 0.5 * math.erfc(-z / math.sqrt(2.0)), otypes=[float])
            f = v
        _NDTR.append(f)
    return _NDTR[0](x)


def npdf(z):
    return np.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)


class PredLN:
    """The new-run predictive of a log-normal model, per posterior draw d: log Y ~ N(e_d + rr_d R, sd_d),
    R ~ Bernoulli(pr) (the resume mix). e, sd, rr: flat arrays over (chain, draw) = shape."""

    def __init__(self, e, sd, rr, pr, shape):
        self.e, self.sd = np.asarray(e, float).ravel(), np.asarray(sd, float).ravel()
        self.rr = np.zeros_like(self.e) if rr is None else np.asarray(rr, float).ravel()
        self.pr, self.shape = float(pr), tuple(shape)

    def Fd(self, x):
        """Per-draw P(log Y <= x); x a scalar, a (N,) per-draw array or a (m, 1) column."""
        return (1 - self.pr) * ndtr((x - self.e) / self.sd) + self.pr * ndtr((x - self.e - self.rr) / self.sd)

    def fd(self, x):
        """Per-draw density of log Y at x."""
        return ((1 - self.pr) * npdf((x - self.e) / self.sd) + self.pr * npdf((x - self.e - self.rr) / self.sd)) \
            / self.sd

    def _span(self):
        r = np.abs(self.rr)
        return float(np.min(self.e - 12 * self.sd - r)), float(np.max(self.e + 12 * self.sd + r))

    def quantiles(self, ps, iters=64):
        """Mixture quantiles (on the natural scale) at each p in ps, by one vectorized bisection."""
        ps = np.asarray(ps, float)
        lo0, hi0 = self._span()
        lo, hi = np.full(ps.shape, lo0), np.full(ps.shape, hi0)
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            low = self.Fd(mid[:, None]).mean(axis=1) < ps
            lo, hi = np.where(low, mid, lo), np.where(low, hi, mid)
        return np.exp(0.5 * (lo + hi))

    def draw_quantile(self, p, iters=56):
        """Per-draw quantile at p (natural scale), shape (chain, draw)."""
        r = np.abs(self.rr)
        lo, hi = self.e - 12 * self.sd - r, self.e + 12 * self.sd + r
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            low = self.Fd(mid) < p
            lo, hi = np.where(low, mid, lo), np.where(low, hi, mid)
        return np.exp(0.5 * (lo + hi)).reshape(self.shape)

    def mcse_rel(self, T):
        """MCSE(T)/T of the mixture quantile T (delta method on the log scale)."""
        x = math.log(T)
        return delta_mcse(self.Fd(x).reshape(self.shape), float(self.fd(x).mean()))


class PredNB:
    """The new-run predictive of a shifted NB2 model, per draw d: Y - 1 ~ NB(mu, a_d), log mu = e_d + rr_d R +
    tn_d W, W ~ N(0, 1) integrated by 7-node Gauss-Hermite (BAYES.md 1.2), R ~ Bernoulli(pr)."""

    def __init__(self, e, a, tn, rr, pr, shape):
        from stack_bayes_grid import GH_W, GH_X
        self.e, self.a = np.asarray(e, float).ravel(), np.asarray(a, float).ravel()
        self.tn = np.asarray(tn, float).ravel()
        self.rr = np.zeros_like(self.e) if rr is None else np.asarray(rr, float).ravel()
        self.pr, self.shape = float(pr), tuple(shape)
        gx, gw = np.asarray(GH_X), np.asarray(GH_W)
        self.wts = np.concatenate([(1 - self.pr) * gw, self.pr * gw])          # (J,)
        self.gx = np.concatenate([gx, gx])
        self.rflag = np.concatenate([np.zeros(len(gx)), np.ones(len(gx))])

    def sweep(self, mix_ps, draw_ps, kcap):
        """One pass over k = 0..kcap of the per-draw and mixture CDFs P(Y - 1 <= k) (the pmf by its
        recurrence in log space). Returns {"mix": {p: (k_p, Fbar(k_p - 1), Fbar(k_p), F_d(k_p - 1), F_d(k_p))
        or None beyond kcap}, "draw": {p: per-draw first k with F_d(k) >= p, kcap + 1 when not reached}}."""
        N = self.e.size
        a = self.a[:, None]
        logmu = self.e[:, None] + self.rflag[None, :] * self.rr[:, None] + self.tn[:, None] * self.gx[None, :]
        lse = np.logaddexp(np.log(a), logmu)                   # log(a + mu)
        lp = a * (np.log(a) - lse)                             # log pmf at k = 0
        lq = logmu - lse                                       # log(1 - p) = log(mu / (a + mu))
        cdf = np.exp(lp)
        idx = np.arange(N)
        F = np.empty(N)
        F[:] = cdf @ self.wts
        prevF, prevbar = np.zeros(N), 0.0
        mix = {p: None for p in mix_ps}
        draw = {p: np.full(N, kcap + 1, dtype=float) for p in draw_ps}
        aa = np.broadcast_to(a, lp.shape).copy()
        for k in range(kcap + 1):
            Fa = F[idx]                                        # F_d(k) of the draws still in the sweep
            for p in draw_ps:
                hit = (Fa >= p) & (draw[p][idx] > kcap)
                if hit.any():
                    draw[p][idx[hit]] = k
            Fbar = float(F.mean())
            for p in mix_ps:
                if mix[p] is None and Fbar >= p:
                    mix[p] = (k, prevbar, Fbar, prevF.copy(), F.copy())
            if k == kcap or (all(v is not None for v in mix.values())
                             and all((d <= kcap).all() for d in draw.values())):
                break
            if k % 16 == 15:          # retire draws whose CDF is 1 (their crossings at k are recorded above)
                keep = Fa < 1.0 - RETIRE_EPS
                if not keep.all():
                    idx, lp, lq, cdf, aa = idx[keep], lp[keep], lq[keep], cdf[keep], aa[keep]
            prevF[:] = F
            prevbar = Fbar
            lp += np.log1p((aa - 1.0) / (k + 1.0)) + lq
            cdf += np.exp(lp)
            F[idx] = np.minimum(cdf @ self.wts, 1.0)
        return {"mix": mix, "draw": draw}

    @staticmethod
    def quantile_of(m, p):
        """(integer quantile of Y, continuous T_raw within its step, the pmf there) from a sweep's mix entry."""
        k, f0, f1 = m[0], m[1], m[2]
        pmf = f1 - f0
        frac = (p - f0) / pmf if pmf > 0 else 1.0
        return 1 + k, k + min(max(frac, 0.0), 1.0), pmf

    def mcse_rel(self, m, p):
        """MCSE(T_raw)/T_raw (delta method on the CDF interpolated within the step of T)."""
        q, t_raw, pmf = self.quantile_of(m, p)
        frac = t_raw - m[0]
        Fd = (m[3] + frac * (m[4] - m[3])).reshape(self.shape)
        s = delta_mcse(Fd, pmf)
        return None if s is None else s / t_raw


# ---------------------------------------------------------------- data
def read_extra(paths, keys):
    """The scheduler columns of EXTRA_COLS per (session, id, seg) in `keys`, last row winning (the order of
    stack_limits.read_rows); a cell that is not a finite number in [0, cap] is None."""
    out = {}
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace", newline="") as fh:
                for i, r in enumerate(L._csv_rows(fh)):
                    if i >= L.MAX_LINES_PER_FILE:
                        break
                    try:
                        k = ((r.get("session") or "").strip(), (r.get("id") or "").strip(),
                             int((r.get("seg") or "").strip()))
                    except ValueError:
                        continue
                    if k not in keys:
                        continue
                    ex = {}
                    for c, cap in EXTRA_COLS.items():
                        s = (r.get(c) or "").strip()
                        try:
                            v = float(s) if s else None
                        except ValueError:
                            v = None
                        ex[c] = v if v is not None and math.isfinite(v) and 0 <= v <= cap else None
                    out[k] = ex
        except OSError:
            continue
    return out


def agent_records(rows, seed, extra, limit_of):
    """Agent rows of the proposer window (last 20 sessions) of seed types with api_calls > 0, each with its
    A.3 censoring for turns and ctx (stack_limits.censor_flags, the main-window join included)."""
    types = set(L._types(seed))
    win = L._window(rows)
    wh = L.win_hits_of(win)
    lim = {}
    out = []
    for r in win:
        if r["scope"] != "agent" or r["type"] not in types or not (r["api_calls"] or 0) > 0:
            continue
        t = r["type"]
        if t not in lim:
            lim[t] = (limit_of("turns." + t), limit_of("soft.agent." + t))
        lt, lc = lim[t][0](r), lim[t][1](r)
        rec = {"session": r["session"], "id": r["id"], "seg": r["seg"], "type": t, "ts": r["ts"],
               "api_calls": float(r["api_calls"]), "ctx": r["ctx"], "status": r["status"],
               "compacted": r["compacted"], "regime": r["regime"] or "none", "resume": int(r["seg"] > 0),
               "cens_turns": bool(L.censor_flags(r, "turns", lt, wh)),
               "cens_ctx": bool(L.censor_flags(r, "ctx", lc, wh))}
        rec.update(extra.get((r["session"], r["id"], r["seg"])) or dict.fromkeys(EXTRA_COLS))
        out.append(rec)
    return out


class Index:
    """Positions of types, pools (and pools with >= 2 members: the u_pool effect), model families,
    sessions and regimes, as the prototype's Index."""

    def __init__(self, seed, models, sessions, regimes):
        self.types = L._types(seed)
        self.pool_of = L._pool_of(seed)
        self.pools = sorted(seed["pools"])
        self.fams = ["opus", "sonnet"]
        self.fam_of = {t: (L.model_family(models.get(t)) or "opus") for t in self.types}
        for f in self.fam_of.values():
            if f not in self.fams:
                self.fams.append(f)
        self.sessions, self.regimes = list(sessions), list(regimes)
        mt = np.array([seed["vars"]["turns." + t]["ceiling"] for t in self.types], float)
        self.zmt = np.log(mt) - np.log(mt).mean()
        self.ceiling = {t: float(seed["vars"]["turns." + t]["ceiling"]) for t in self.types}
        self.t_pool = np.array([self.pools.index(self.pool_of[t]) for t in self.types])
        size = {p: sum(1 for t in self.types if self.pool_of[t] == p) for p in self.pools}
        self.peff = [p for p in self.pools if size[p] >= 2]
        self.t_peff = np.array([self.peff.index(self.pool_of[t]) if self.pool_of[t] in self.peff else len(self.peff)
                                for t in self.types])
        self.t_fam = np.array([self.fams.index(self.fam_of[t]) for t in self.types])
        self._t = {t: i for i, t in enumerate(self.types)}
        self._s = {s: i for i, s in enumerate(self.sessions)}
        self._g = {g: i for i, g in enumerate(self.regimes)}

    def ti(self, recs):
        return np.array([self._t[r["type"]] for r in recs], int)

    def si(self, recs):
        return np.array([self._s[r["session"]] for r in recs], int)

    def gi(self, recs):
        return np.array([self._g[r["regime"]] for r in recs], int)

    def members(self, pool):
        return [j for j, t in enumerate(self.types) if self.pool_of[t] == pool]


# ---------------------------------------------------------------- the hierarchical model (h4)
def _scale(pm, name, sd, zero_avoid=()):
    if name in zero_avoid:
        m = sd * math.sqrt(2 / math.pi)
        return pm.Gamma(name, alpha=2.0, beta=2.0 / m)
    return pm.HalfNormal(name, sd)


def sample(pm, model, draws, tune, chains, seed):
    with model:
        return pm.sample(draws=draws, tune=tune, chains=chains, cores=chains, random_seed=seed, progressbar=False,
                         nuts_sampler="nutpie", target_accept=TARGET_ACCEPT, compute_convergence_checks=False)


def fit_hier(recs, ycol, kind, ix, center, cfg, seed, sess=True, resume=True, regime=True, type_scale=True,
             zero_avoid=ZERO_AVOID):
    """The prototype's fit_hier (every type non-centred) plus the regime term tau_g z_g (BAYES.md 1.2).
    Returns (DataTree, free RV names, seconds, names dropped as constant by construction)."""
    import pymc as pm
    import pytensor.tensor as pt
    t0 = time.perf_counter()
    y = np.array([r[ycol] for r in recs], float)
    cens = np.array([bool(r.get("cens")) for r in recs])
    if kind == "nb":
        cens = cens & (y > 1)
    t_i, r_i = ix.ti(recs), np.array([r["resume"] for r in recs], float)
    dropped = []
    sess = sess and len(ix.sessions) >= 2
    regime = regime and len(ix.regimes) >= 2
    if not sess:
        dropped.append("z_s")
    if not regime:
        dropped.append("z_g")
    keys = [(r["type"], r["session"]) for r in recs]
    pairs = sorted(set(keys))
    ppos = {k: i for i, k in enumerate(pairs)}
    pr_i = np.array([ppos[k] for k in keys], int)
    coords = {"type": ix.types, "pool": ix.pools, "peff": ix.peff, "fam": ix.fams, "sess": ix.sessions,
              "pair": ["%s|%s" % k for k in pairs], "reg": ix.regimes}
    with pm.Model(coords=coords) as m:
        a0 = pm.Normal("a0", center, 1.5)
        b_fam = pm.ZeroSumNormal("b_fam", 0.5, dims="fam")
        g = pm.Normal("g", 0.5, 0.5)
        u_p = pm.ZeroSumNormal("u_p", 0.7, dims="peff")
        zp = pt.concatenate([u_p, pt.zeros(1)])
        tau_t = _scale(pm, "tau_t", 0.7, zero_avoid)
        dev = tau_t * pm.Normal("z_poor_t", 0, 1, shape=len(ix.types))
        eta = pm.Deterministic("eta_type", a0 + b_fam[ix.t_fam] + g * ix.zmt + zp[ix.t_peff] + dev, dims="type")
        lin = eta[t_i]
        if sess:
            tau_s = _scale(pm, "tau_s", 0.3, zero_avoid)
            z_s = pm.ZeroSumNormal("z_s", 1.0, dims="sess")
            tau_ts = _scale(pm, "tau_ts", 0.5, zero_avoid)
            npair = np.bincount(pr_i, minlength=len(pairs))
            rich, poor = np.where(npair >= 20)[0], np.where(npair < 20)[0]
            d_ts = pt.zeros(len(pairs))
            if kind == "nb" and len(rich):                      # the prototype's PARAM["turns"]["rich_pairs"]
                d_ts = pt.set_subtensor(d_ts[rich], pm.Normal("dev_rich_ts", 0, tau_ts, shape=len(rich)))
                idx = poor
            else:
                idx = np.arange(len(pairs))
            if len(idx):
                d_ts = pt.set_subtensor(d_ts[idx], tau_ts * pm.Normal("z_poor_ts", 0, 1, shape=len(idx)))
            lin = lin + tau_s * z_s[ix.si(recs)] + d_ts[pr_i]
        if regime:
            tau_g = pm.Gamma("tau_g", alpha=2.0, beta=2.0 / 0.3)
            z_g = pm.ZeroSumNormal("z_g", 1.0, dims="reg")
            lin = lin + tau_g * z_g[ix.gi(recs)]
        if resume:
            lin = lin + pm.Normal("rho", 0, 0.5) * r_i
        u, c = ~cens, cens
        if kind == "nb":
            la = pm.Normal("log_alpha", 0.7, 0.75, dims="pool")
            tla, zla = _scale(pm, "tau_la", 0.3, zero_avoid), pm.Normal("z_la", 0, 1, dims="type")
            lat = pm.Deterministic("log_alpha_t", la[ix.t_pool] + tla * zla, dims="type")
            alpha, mu = pt.exp(lat)[t_i], pt.exp(lin)
            pm.NegativeBinomial("y", mu=mu[u], alpha=alpha[u], observed=y[u] - 1)
            if c.any():
                lc = pm.logcdf(pm.NegativeBinomial.dist(mu=mu[c], alpha=alpha[c]), y[c] - 2)
                pm.Potential("cens", pt.sum(pt.log1mexp(lc)))
        else:
            ls = pm.Normal("log_sigma", 0.0, 0.5, dims="pool")
            if type_scale:
                tls, zls = pm.HalfNormal("tau_ls", 0.3), pm.Normal("z_ls", 0, 1, dims="type")
                lst = pm.Deterministic("log_sigma_t", ls[ix.t_pool] + tls * zls, dims="type")
            else:
                lst = pm.Deterministic("log_sigma_t", ls[ix.t_pool], dims="type")
            sig, ly = pt.exp(lst)[t_i], np.log(y)
            pm.Normal("y", lin[u], sig[u], observed=ly[u])
            if c.any():
                pm.Potential("cens", pt.sum(pm.logcdf(pm.Normal.dist(-lin[c], sig[c]), -ly[c])))
        free = [v.name for v in m.free_RVs]
    dt = sample(pm, m, cfg["draws"], cfg["tune"], cfg["chains"], seed)
    return dt, free, time.perf_counter() - t0, dropped


def fit_ctx_ab(recs, ix, cfg, seed):
    """ctx(n) = a n + b n^2 through (k_t, q_t) at n_ref (the prototype's ctx_ab, version 2)."""
    import pymc as pm
    import pytensor.tensor as pt
    t0 = time.perf_counter()
    t_i = ix.ti(recs)
    n = np.array([r["api_calls"] for r in recs], float)
    ly = np.log(np.array([r["ctx"] for r in recs], float))
    n_ref = float(np.exp(np.mean(np.log(n))))
    with pm.Model(coords={"type": ix.types, "pool": ix.pools, "peff": ix.peff}) as m:
        K0 = pm.Normal("K0", math.log(5e4 + 2e3 * n_ref), 1.5)
        Q0 = pm.Normal("Q0", math.log(2e3 * n_ref / 5e4), 1.5)
        upk = pt.concatenate([pm.ZeroSumNormal("u_pk", 0.7, dims="peff"), pt.zeros(1)])
        upq = pt.concatenate([pm.ZeroSumNormal("u_pq", 0.7, dims="peff"), pt.zeros(1)])
        ttk, ttq = pm.HalfNormal("tau_tk", 0.7), pm.HalfNormal("tau_tq", 0.7)
        kt = pm.Deterministic("k_t", K0 + upk[ix.t_peff] + ttk * pm.Normal("z_k", 0, 1, dims="type"), dims="type")
        qt = pm.Deterministic("q_t", Q0 + upq[ix.t_peff] + ttq * pm.Normal("z_q", 0, 1, dims="type"), dims="type")
        st = pt.sigmoid(qt)
        mu = pt.log(n) + kt[t_i] + pt.log1p(st[t_i] * (n / n_ref - 1.0))
        pm.Normal("y", mu, pm.HalfNormal("sigma", 1.0), observed=ly)
        free = [v.name for v in m.free_RVs]
    dt = sample(pm, m, cfg["draws"], cfg["tune"], cfg["chains"], seed)
    return dt, free, time.perf_counter() - t0, n_ref


def fit_resume_ctx(recs, cfg, seed):
    """(ctx / n - prev_peak) / 1e4 = alpha + gamma n + e, e ~ StudentT(4, sigma) on healthy resumed segments."""
    import pymc as pm
    t0 = time.perf_counter()
    n = np.array([r["api_calls"] for r in recs], float)
    y = (np.array([r["ctx"] for r in recs], float) / n - np.array([r["prev_peak"] for r in recs], float)) / 1e4
    with pm.Model() as m:
        al, ga, sg = pm.HalfNormal("alpha", 10.0), pm.HalfNormal("gamma", 1.0), pm.HalfNormal("sigma", 10.0)
        pm.StudentT("y", nu=4, mu=al + ga * n, sigma=sg, observed=y)
        free = [v.name for v in m.free_RVs]
    dt = sample(pm, m, cfg["draws"], cfg["tune"], cfg["chains"], seed)
    return dt, free, time.perf_counter() - t0


def _finite_or_none(x):
    x = float(x)
    return x if math.isfinite(x) else None


def diagnostics(dt, free, dropped=()):
    """NaN-strict model diagnostics (A.4) over every element of every free parameter, through
    stack_limits.diag_summary: a non-finite R-hat/ESS goes to `constant` (CONSTANT_BY_CONSTRUCTION names)
    or `nan` (the gate fails); names dropped from the model as constant by construction are listed."""
    import arviz as az
    post = dt["posterior"].dataset
    names = [n for n in free if n in post]
    s = az.summary(post[names], kind="diagnostics", round_to="none")
    params = {str(k): {"rhat": _finite_or_none(r["r_hat"]), "ess_bulk": _finite_or_none(r["ess_bulk"]),
                       "ess_tail": _finite_or_none(r["ess_tail"])} for k, r in s.iterrows()}
    div = int(dt["sample_stats"].dataset["diverging"].values.sum())
    en = dt["sample_stats"].dataset["energy"].values
    bf = float(np.min(np.mean(np.diff(en, axis=1) ** 2, axis=1) / np.var(en, axis=1)))
    d = L.diag_summary(params, div, bf)
    for c in dropped:
        if c not in d["constant"]:
            d["constant"].append(c)
    return d


def qdiag(qd):
    """R-hat (rank), bulk and tail ESS of a per-draw quantity (chain, draw): the quantity gate's inputs."""
    import arviz as az
    qd = np.asarray(qd, float)
    if np.ptp(qd) == 0:
        return {"rhat": 1.0, "ess_bulk": float(qd.size), "ess_tail": float(qd.size)}
    return {"rhat": _finite_or_none(az.rhat(qd, method="rank")), "ess_bulk": _finite_or_none(az.ess(qd, method="bulk")),
            "ess_tail": _finite_or_none(az.ess(qd, method="tail", prob=0.05))}


# ---------------------------------------------------------------- posterior helpers
def _v(post, name):
    return post[name].values


def tau_new_sq(post):
    z = np.zeros(post["a0"].shape)
    ts = _v(post, "tau_s") if "tau_s" in post else z
    tts = _v(post, "tau_ts") if "tau_ts" in post else z
    return ts ** 2 + tts ** 2


def regime_terms(post, ix, cur_reg, rng):
    """(offset per draw, extra variance per draw, note) of the current regime: its z_g when it has rows; a
    new regime's effect integrated otherwise (tau_g from the posterior, or its prior with one regime)."""
    shape = post["a0"].shape
    if "z_g" in post and cur_reg in ix.regimes:
        j = ix.regimes.index(cur_reg)
        return _v(post, "tau_g") * _v(post, "z_g")[..., j], np.zeros(shape), "seen"
    if "tau_g" in post:
        return np.zeros(shape), _v(post, "tau_g") ** 2, "new"
    if cur_reg in ix.regimes:
        return np.zeros(shape), np.zeros(shape), "only"
    return np.zeros(shape), rng.gamma(2.0, 0.15, size=shape) ** 2, "new-prior"


def pool_eta(post, ix, pool, rng):
    """Per-draw location of a new type of `pool` (the class-level predictive): a0 + the members' mean of
    b_fam + g zmt + u_pool + tau_t xi, xi ~ N(0, 1) per draw."""
    mem = ix.members(pool)
    a0 = _v(post, "a0")
    bf = _v(post, "b_fam")
    g = _v(post, "g")
    up = np.concatenate([_v(post, "u_p"), np.zeros(a0.shape + (1,))], axis=-1)
    fixed = np.mean([bf[..., ix.t_fam[j]] + g * ix.zmt[j] + up[..., ix.t_peff[j]] for j in mem], axis=0)
    return a0 + fixed + _v(post, "tau_t") * rng.standard_normal(a0.shape)


def pool_log_scale(post, ix, pool, name, rng):
    """Per-draw log scale (log_sigma or log_alpha) of a new type of `pool`."""
    p = ix.pools.index(pool)
    base = _v(post, "log_sigma" if name == "log_sigma_t" else "log_alpha")[..., p]
    tl = "tau_ls" if name == "log_sigma_t" else "tau_la"
    if tl in post:
        return base + _v(post, tl) * rng.standard_normal(base.shape)
    return base


def pred_ln(post, j, p_resume, off, extra, pool=None, ix=None, rng=None):
    if pool is None:
        e = _v(post, "eta_type")[..., j] + off
        ls = _v(post, "log_sigma_t")[..., j]
    else:
        e = pool_eta(post, ix, pool, rng) + off
        ls = pool_log_scale(post, ix, pool, "log_sigma_t", rng)
    sd = np.sqrt(np.exp(ls) ** 2 + tau_new_sq(post) + extra)
    rr = _v(post, "rho") if "rho" in post else None
    return PredLN(e, sd, rr, p_resume, e.shape)


def pred_nb(post, j, p_resume, off, extra, pool=None, ix=None, rng=None):
    if pool is None:
        e = _v(post, "eta_type")[..., j] + off
        la = _v(post, "log_alpha_t")[..., j]
    else:
        e = pool_eta(post, ix, pool, rng) + off
        la = pool_log_scale(post, ix, pool, "log_alpha_t", rng)
    tn = np.sqrt(tau_new_sq(post) + extra)
    rr = _v(post, "rho") if "rho" in post else None
    return PredNB(e, np.exp(la), tn, rr, p_resume, e.shape)


def hyper_of(post, kind, ix, p_resume, off, extra):
    """BAYES.md 2.1 `hyper.<model>`: posterior medians; the current regime's offset folded into each type's
    mu, a new regime's variance into tau_new."""
    med = lambda v: np.median(_v(post, v), axis=(0, 1))  # noqa: E731
    a0, bf, tt = med("a0"), med("b_fam"), med("tau_t")
    g = med("g") if "g" in post else 0.0
    zp = np.concatenate([med("u_p"), [0.0]])
    o = float(np.median(off))
    tn = float(np.median(np.sqrt(tau_new_sq(post) + extra)))
    h = {"tau_t": float(tt), "tau_new": max(tn, 1e-6), "rho": float(med("rho")) if "rho" in post else 0.0,
         "p_resume": float(p_resume), "types": {}}
    scale = np.exp(med("log_alpha_t" if kind == "nb" else "log_sigma_t"))
    for j, t in enumerate(ix.types):
        h["types"][t] = {"mu": float(a0 + bf[ix.t_fam[j]] + g * ix.zmt[j] + zp[ix.t_peff[j]] + o),
                         "scale": float(scale[j])}
    return h


def shrink_of(post, j):
    sd_post = float(np.std(_v(post, "eta_type")[..., j]))
    tt = float(np.median(_v(post, "tau_t")))
    return float(min(1.0, max(-10.0, 1 - sd_post / tt))) if tt > 0 else None


# ---------------------------------------------------------------- blocks (BAYES.md 2.1)
def clamp_at_cap(T, T_raw, pi90, qx, cap):
    """Rule 4's range: T, T_raw, pi90 and qtab.x clamped to [0, cap] (WP2: the ctx predictives of sparse
    types pass CTX_MAX = 1e10). Returns (T, T_raw, pi90, qx, clamped): clamped when a value reached the cap
    (the reader's rule: a value at the cap needs at_bound, e.g. a soft T = ceil2(T_raw) rounded up to 1e10)."""
    vals = [T, T_raw] + list(pi90) + list(qx)
    clamped = any(v >= cap for v in vals)             # reached or passed: the reader's rule (2.1 rule 4)
    c = lambda v: min(max(float(v), 0.0), cap)  # noqa: E731
    return c(T), c(T_raw), [c(v) for v in pi90], [c(v) for v in qx], clamped


def _qx_monotone(xs):
    out = [max(float(x), 1e-9) for x in xs]
    for k in range(1, len(out)):
        out[k] = max(out[k], out[k - 1])
    return out


def make_block(fam, model_id, T, T_raw, pi90, qx, at_bound, counts, shrink, status, qd_diag, mcse_rel, cap):
    T, T_raw, pi90, qx, clamped = clamp_at_cap(T, T_raw, pi90, _qx_monotone(qx), cap)
    if pi90[0] > pi90[1]:
        pi90 = [pi90[1], pi90[0]]
    diag = {"rhat": qd_diag["rhat"], "ess_bulk": qd_diag["ess_bulk"], "ess_tail": qd_diag["ess_tail"],
            "mcse_rel": None if mcse_rel is None or not math.isfinite(mcse_rel) else float(mcse_rel),
            "edge_mass": None}
    blk = {"tier": "nuts", "model": model_id, "risk": L.RISK[fam], "T": int(T) if float(T).is_integer() else T,
           "T_raw": float(T_raw), "pi90": [float(v) for v in pi90], "qtab": {"p": list(L.QTAB_P), "x": qx},
           "at_bound": bool(at_bound or clamped), "shrink": shrink, "status": status, "diag": diag}
    blk.update(counts)
    return blk


def type_counts(recs, t):
    sub = [r for r in recs if r["type"] == t]
    return {"n": len(sub), "n_cens": sum(1 for r in sub if r["cens"]),
            "agents": len({(r["session"], r["id"]) for r in sub}), "sessions": len({r["session"] for r in sub})}


# ---------------------------------------------------------------- the sched block (BAYES.md 2.2, B)
def _pos(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) and x > 0


def sched_entry_ok(e, typed):
    """BAYES.md 2.2's validity of one entry (stack_sched_refresh.load_bayes_sched checks the same): every
    number finite and > 0, S <= M <= L, p50 <= p90, lo <= med <= hi per band quantity."""
    try:
        t, spc, b = e["turns"], e["sec_per_call"], e["band"]
        nums = [t["S"], t["M"], t["L"], spc["p50"], spc["p90"], e["ctx"]["a"], e["ctx"]["b"], e["static_cc"],
                b["level"], b["n_ref"]]
        ok = all(_pos(v) for v in nums) and t["S"] <= t["M"] <= t["L"] and spc["p50"] <= spc["p90"] \
            and b["level"] < 1 and b["method"] == "bayes"
        for q in ("turns", "sec_per_call", "ctx"):
            lo, med, hi = b[q]["lo"], b[q]["med"], b[q]["hi"]
            ok = ok and _pos(lo) and _pos(med) and _pos(hi) and lo <= med <= hi
        ok = ok and all(type(e[k]) is int and e[k] >= 0 for k in ("n_seg", "n_agents", "n_first"))
        return bool(ok and (not typed or e.get("status") in ("supported", "provisional")))
    except (KeyError, TypeError):
        return False


def _r(x, nd=6):
    return float(f"{float(x):.{nd}g}")


def sched_entry(turns_sw, spc_pred, static_pred, ab_draws, counts, typed):
    """One `types.<t>` / `pools.<p>` entry from its predictives (B, decision mapping)."""
    mix = turns_sw["mix"]
    if any(mix.get(p) is None for p in (0.25, 0.5, 0.9)):
        return None
    S, M, Lq = (float(PredNB.quantile_of(mix[p], p)[0]) for p in (0.25, 0.5, 0.9))
    med_d = 1.0 + turns_sw["draw"][0.5]
    q05m, q50m, q95m = np.quantile(med_d, (0.05, 0.5, 0.95))
    p50, p90 = spc_pred.quantiles((0.5, 0.9))
    sm = spc_pred.draw_quantile(0.5)
    s05, s50, s95 = np.quantile(sm, (0.05, 0.5, 0.95))
    static_cc = float(static_pred.quantiles((0.1,))[0])
    a_d, b_d = ab_draws
    cM = a_d * M + b_d * M * M
    c05, c50, c95 = np.quantile(cM, (0.05, 0.5, 0.95))
    e = {"turns": {"S": S, "M": M, "L": Lq},
         "sec_per_call": {"p50": _r(p50, 4), "p90": _r(p90, 4)},
         "ctx": {"a": _r(np.median(a_d)), "b": _r(np.median(b_d))},
         "static_cc": _r(static_cc),
         "band": {"level": 0.9, "method": "bayes", "n_ref": M,
                  "turns": {"lo": _r(M * q05m / q50m, 4), "med": M, "hi": _r(M * q95m / q50m, 4)},
                  "sec_per_call": {"lo": _r(p50 * s05 / s50, 4), "med": _r(p50, 4), "hi": _r(p50 * s95 / s50, 4)},
                  "ctx": {"lo": _r(c05 / c50, 4), "med": 1.0, "hi": _r(c95 / c50, 4)}}}
    e.update(counts)
    if typed:
        e["status"] = "supported" if counts["n_seg"] >= MIN_SEG and counts["n_agents"] >= MIN_AGENTS else "provisional"
    b = e["band"]
    for q in ("turns", "sec_per_call", "ctx"):          # rounding must not break lo <= med <= hi
        b[q]["lo"], b[q]["hi"] = min(b[q]["lo"], b[q]["med"]), max(b[q]["hi"], b[q]["med"])
    return e if sched_entry_ok(e, typed) else None


def sched_counts(recs, keep):
    """n_seg (healthy segments: complete, turns not censored), n_agents, n_first (healthy first segments)."""
    seg = [r for r in recs if keep(r) and r["status"] == "complete" and not r["cens_turns"]]
    return {"n_seg": len(seg), "n_agents": len({(r["session"], r["id"]) for r in seg}),
            "n_first": sum(1 for r in seg if r["seg"] == 0)}


# ---------------------------------------------------------------- the drift check (BAYES.md 2.1 rule 7, A.12)
def drift_rows(frame, last=DRIFT_SESSIONS):
    """(rows, sessions): the model's rows (the frame the model saw: quantity > 0, with `cens`) of the last
    `last` sessions, sessions ordered by their first row (ts, then id), rows in session order then (ts, id,
    seg). Only sessions with a row of the model count."""
    first = {}
    for r in frame:
        s = r["session"]
        first[s] = min(first.get(s, r["ts"]), r["ts"])
    order = sorted(first, key=lambda s: (first[s], s))
    keep = order[-last:] if last > 0 else []
    rank = {s: i for i, s in enumerate(keep)}
    rows = sorted((r for r in frame if r["session"] in rank),
                  key=lambda r: (rank[r["session"]], r["ts"], r["id"], r["seg"]))
    return rows, keep


def drift_enough(n, n_cens, sessions):
    """A.12's minimum: >= 20 rows, >= 10 of them uncensored, from >= 3 sessions."""
    return n >= DRIFT_MIN_ROWS and n - n_cens >= DRIFT_MIN_UNCENS and sessions >= DRIFT_MIN_SESSIONS


def ks_stat(u):
    """Two-sided KS distance of each row of `u` (..., n) from U(0, 1)."""
    u = np.sort(np.asarray(u, float), axis=-1)
    n = u.shape[-1]
    i = np.arange(1, n + 1)
    return np.maximum((i / n - u).max(axis=-1), (u - (i - 1) / n).max(axis=-1))


def mc_pvalue(D, Dstar):
    """(1 + #{D* >= D}) / (B + 1): the Monte Carlo p of D against the clustered replicates D* (B,)."""
    Dstar = np.asarray(Dstar, float)
    return float((1 + np.count_nonzero(Dstar >= D - 1e-12)) / (Dstar.size + 1))


def pit_of(lo, hi, u):
    """Randomized PIT lo + u (hi - lo): an exact log-normal row has lo = hi = F(y); an exact NB row
    [F(y - 1), F(y)]; a censored row [F(y-), 1] with F(y-) = P(Y < y)."""
    return lo + u * (hi - lo)


def nb_bounds(Fx, y, cens):
    """(lo, hi) of the PIT of NB rows: Fx[k] = P(Y - 1 <= k), k = 0..K (clamped at K beyond it), y >= 1
    integer counts. Exact: [F(y - 1), F(y)] = [Fx[y - 2], Fx[y - 1]]; censored at y (A.3): [F(y - 1), 1],
    F(y-) = P(Y < y) = F(y - 1), so the atom P(Y = y) is kept (the fitter's log P(Y >= y))."""
    K = Fx.size - 1
    y = np.asarray(y, np.int64)
    hi = Fx[np.clip(y - 1, 0, K)]
    lo = np.where(y >= 2, Fx[np.clip(y - 2, 0, K)], 0.0)
    return lo, np.where(cens, 1.0, hi)


def ln_bounds(Fy, cens):
    """(lo, hi) of the PIT of log-normal rows: Fy = F(y); censored at y: [F(y), 1] (F(y-) = F(y))."""
    return Fy, np.where(cens, 1.0, Fy)


def nb_table(m, a, tn, kneed, eps=DRIFT_EPS, kmax=KMAX):
    """The new-session predictive CDF Fx[k] = P(Y - 1 <= k), k = 0..K, of one (type, resume, regime): the
    mean over draws of Y - 1 ~ NB(exp(m_d + tn_d W), a_d), W ~ N(0, 1) by 7-node Gauss-Hermite (PredNB).
    It runs to k >= kneed and stops where the mixture CDF reaches 1 - eps (at most max(kmax, kneed))."""
    from stack_bayes_grid import GH_W, GH_X
    gx, gw = np.asarray(GH_X), np.asarray(GH_W)
    a2 = np.asarray(a, float)[:, None]
    logmu = np.asarray(m, float)[:, None] + np.asarray(tn, float)[:, None] * gx[None, :]
    lse = np.logaddexp(np.log(a2), logmu)
    lp = a2 * (np.log(a2) - lse)
    lq = logmu - lse
    cdf = np.exp(lp)
    nd = a2.shape[0]
    out = []
    for k in range(max(kmax, int(kneed)) + 1):
        F = min(float((cdf @ gw).sum()) / nd, 1.0)
        out.append(F)
        if k >= kneed and F >= 1.0 - eps:
            break
        lp = lp + np.log1p((a2 - 1.0) / (k + 1.0)) + lq
        cdf = cdf + np.exp(lp)
    return np.array(out)


def ln_table(m, sd, x_lo, x_hi, grid=DRIFT_GRID):
    """(xs, F) of one (type, resume, regime)'s new-session predictive CDF of log Y on a grid that covers the
    draws' +-12 sd and [x_lo, x_hi]: F(x) = mean over draws of Phi((x - m_d) / sd_d)."""
    lo = min(float(np.min(m - 12 * sd)), x_lo)
    hi = max(float(np.max(m + 12 * sd)), x_hi)
    xs = np.linspace(lo, hi, grid)
    F = ndtr((xs[:, None] - m[None, :]) / sd[None, :]).mean(axis=1)
    return xs, np.maximum.accumulate(np.clip(F, 0.0, 1.0))


def _thin(post, name, idx):
    v = _v(post, name)
    return v.reshape((-1,) + v.shape[2:])[idx]


def drift_params(post, kind, ix, rows, draws=DRIFT_DRAWS):
    """Per thinned draw and row: m (the row's location: its type, its resume offset rho when seg > 0, its own
    regime's offset tau_g z_g), scale (sigma of the type for "ln", alpha for "nb"), and the new session's
    effect split as in the model, tau_s (shared by the session's rows) and tau_ts (by its rows of one type)."""
    shape = _v(post, "a0").shape
    N = shape[0] * shape[1]
    idx = np.unique(np.linspace(0, N - 1, min(N, draws)).round().astype(int))
    zero = np.zeros(idx.size)
    j, g = ix.ti(rows), ix.gi(rows)
    res = np.array([float(r["resume"]) for r in rows])
    m = _thin(post, "eta_type", idx)[:, j]
    if "rho" in post:
        m = m + _thin(post, "rho", idx)[:, None] * res[None, :]
    if "z_g" in post:
        m = m + _thin(post, "tau_g", idx)[:, None] * _thin(post, "z_g", idx)[:, g]
    scale = np.exp(_thin(post, "log_alpha_t" if kind == "nb" else "log_sigma_t", idx)[:, j])
    ts = _thin(post, "tau_s", idx) if "tau_s" in post else zero
    tts = _thin(post, "tau_ts", idx) if "tau_ts" in post else zero
    return m, scale, ts, tts


def drift_check(post, kind, ix, frame, seed, B=DRIFT_B, draws=DRIFT_DRAWS):
    """A.12's check of one model: (entry or None, stats). entry = {"ks_p", "sessions", "breach"} when the
    minimum holds, else None; stats (n, n_cens, sessions, D) go to the log and the summary line only.

    PIT per row from the new-session predictive F (draws averaged, the session effect integrated):
    log-normal exact F(y); NB exact U(F(y - 1), F(y)); censored U(F(y-), 1). p is a session-clustered
    Monte Carlo: each replicate takes one posterior draw, one effect per session (tau_s) and per session and
    type (tau_ts), a y* per row from its predictive given them; a censored row stays censored at its point c
    when y* >= c, else it is exact; every PIT is recomputed with the same F and D* taken. Seeded by `seed`."""
    rows, sess = drift_rows(frame)
    cens = np.array([bool(r["cens"]) for r in rows], bool)
    st = {"n": len(rows), "n_cens": int(cens.sum()), "sessions": len(sess), "D": None}
    if not drift_enough(st["n"], st["n_cens"], st["sessions"]):
        return None, st
    rng = np.random.default_rng(seed)
    ycol = "api_calls" if kind == "nb" else "ctx"
    y = np.array([float(r[ycol]) for r in rows])
    if kind == "nb":
        y = np.maximum(np.rint(y), 1.0).astype(np.int64)
    m, scale, ts, tts = drift_params(post, kind, ix, rows, draws)
    nd, n = m.shape
    # replicates: one draw each; the session and session x type effects; y* from the row's predictive
    sidx = {s: i for i, s in enumerate(sess)}
    s_i = np.array([sidx[r["session"]] for r in rows])
    pairs = sorted({(r["session"], r["type"]) for r in rows})
    pidx = {p: i for i, p in enumerate(pairs)}
    p_i = np.array([pidx[(r["session"], r["type"])] for r in rows])
    u_obs = rng.random(n)
    d_b = rng.integers(0, nd, size=B)
    w = ts[d_b][:, None] * rng.standard_normal((B, len(sess)))[:, s_i] \
        + tts[d_b][:, None] * rng.standard_normal((B, len(pairs)))[:, p_i]
    loc = m[d_b] + w
    if kind == "nb":
        a = scale[d_b]
        mu = np.exp(np.minimum(loc, 40.0))
        lam = np.minimum(rng.gamma(a, mu / a), 1e12)
        yr = rng.poisson(lam).astype(np.int64) + 1
        rcens = cens[None, :] & (yr >= y[None, :])
    else:
        ly = np.log(y)
        xr = loc + scale[d_b] * rng.standard_normal((B, n))
        rcens = cens[None, :] & (xr >= ly[None, :])
    u_rep = rng.random((B, n))
    lo, hi = np.empty(n), np.empty(n)
    lo_r, hi_r = np.empty((B, n)), np.empty((B, n))
    combos = {}
    for i, r in enumerate(rows):
        combos.setdefault((r["type"], r["resume"], r["regime"]), []).append(i)
    for key in sorted(combos):
        ic = np.array(combos[key])
        i0 = ic[0]
        if kind == "nb":
            tn = np.sqrt(ts ** 2 + tts ** 2)
            Fx = nb_table(m[:, i0], scale[:, i0], tn, int(y[ic].max()) - 1)
            lo[ic], hi[ic] = nb_bounds(Fx, y[ic], cens[ic])
            ye = np.where(rcens[:, ic], y[ic][None, :], yr[:, ic])
            lo_r[:, ic], hi_r[:, ic] = nb_bounds(Fx, ye, rcens[:, ic])
        else:
            sd = np.sqrt(scale[:, i0] ** 2 + ts ** 2 + tts ** 2)
            xs, F = ln_table(m[:, i0], sd, float(ly[ic].min()), float(ly[ic].max()))
            lo[ic], hi[ic] = ln_bounds(np.interp(ly[ic], xs, F), cens[ic])
            xe = np.where(rcens[:, ic], ly[ic][None, :], xr[:, ic])
            lo_r[:, ic], hi_r[:, ic] = ln_bounds(np.interp(xe, xs, F), rcens[:, ic])
    pit = pit_of(lo, hi, u_obs)
    D = float(ks_stat(pit))
    p = mc_pvalue(D, ks_stat(pit_of(lo_r, hi_r, u_rep)))
    st.update(D=D, p=p, pit=pit)
    return {"ks_p": p, "sessions": len(sess), "breach": bool(p < DRIFT_ALPHA)}, st


def drift_entry(check, gate_ok, prev):
    """The sticky breach (A.12) of one family: `check` the fit's own entry or None (under the minimum),
    `gate_ok` the family model's gate (rule 6), `prev` the previous file's entry when it is a breach.
    - the check ran and the gate passes: its own entry (only this clears a breach, with ks_p >= 0.01);
    - the gate fails: its own entry when it breaches, else the previous breach carried, else none;
    - under the minimum: the previous breach carried, else none."""
    if check is not None and (gate_ok or check["breach"]):
        return dict(check)
    if prev is not None and prev.get("breach") is True:
        return dict(prev)
    return None


def drift_block(checks, gates, prev):
    """bayes.json `drift` from the checks per model ({"turns"|"ctx": entry or None}), the model gates
    ({model id: bool}) and the previous file's breached entries ({family: entry})."""
    out = {}
    for name, fams in DRIFT_FAMILIES.items():
        ok = bool(gates.get(MODEL_ID[name]))
        for fam in fams:
            e = drift_entry(checks.get(name), ok, prev.get(fam))
            if e is not None:
                out[fam] = {"ks_p": float(e["ks_p"]), "sessions": int(e["sessions"]), "breach": bool(e["breach"])}
    return out


def previous_breaches(path, seed):
    """{family: entry} of the breached drift entries of the bayes.json at `path` when it passes the readers'
    rules 1, 3 and 4 (stack_limits._bayes_doc_checked: also its fit_id and seed_sha); {} when it is absent or
    refused. An unexpected error propagates: the fit fails and the file on disk, with its breach, stays."""
    doc, _why = L._read_bayes(path)
    if doc is None:
        return {}
    try:
        L._bayes_doc_checked(doc, seed)
    except L._BayesInvalid:
        return {}
    out = {}
    for fams in DRIFT_FAMILIES.values():
        for fam in fams:
            e = (doc.get("drift") or {}).get(fam)
            if isinstance(e, dict) and e.get("breach") is True:
                out[fam] = {"ks_p": e["ks_p"], "sessions": e["sessions"], "breach": True}
    return out


def drift_summary(dstats):
    """The summary line's drift part: per model D, n/n_cens, p (or `min` under the minimum)."""
    parts = []
    for name in DRIFT_FAMILIES:
        s = dstats.get(name) or {}
        if s.get("D") is None:
            parts.append(f"{name} n {s.get('n', 0)}/{s.get('n_cens', 0)} min")
        else:
            parts.append(f"{name} D {s['D']:.3f} n {s['n']}/{s['n_cens']} p {s['p']:.3f}")
    return " ".join(parts)


# ---------------------------------------------------------------- the fit
def _now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def regime_ok(regime):
    """--regime's form: a regime hash as the rows carry it (stack_limits.HEX16_RE: 16 lowercase hex)."""
    return isinstance(regime, str) and bool(L.HEX16_RE.match(regime))


def load_inputs(seed, regime=None):
    """(models, paths, rows, stats, proposals, current regime). `regime` (--regime) replaces the lookup
    (proposals' regime, else stack_limits.current_regime(): the checkout's and the environment's)."""
    models = L.agent_models()
    paths = L.csv_paths()
    rows, stats = L.read_rows(paths, models=models)
    props, _why = L.load_proposals(seed)
    if regime is None:
        regime = (props or {}).get("regime") or L.current_regime()
    return models, paths, rows, stats, props, regime


def fit(cfg, out, log=print):
    """Fit and write `out`. Returns (exit code, summary)."""
    t_start = time.perf_counter()
    import pymc as pm
    import arviz as az
    import pytensor
    import nutpie
    import scipy
    seed = L.load_seed()
    if cfg.get("regime") is not None and not regime_ok(cfg["regime"]):
        return EXIT_FAIL, "bayes: failed: --regime is not 16 lowercase hex digits"
    prev_drift = previous_breaches(out, seed)          # the sticky breach: the file on disk at fit start
    models, paths, rows, stats, props, cur_reg = load_inputs(seed, cfg.get("regime"))
    eid = L.evidence_id(rows)
    limit_of = L._limits_in_force(seed)
    keys = {(r["session"], r["id"], r["seg"]) for r in rows if r["scope"] == "agent"}
    recs = agent_records(rows, seed, read_extra(paths, keys), limit_of)
    if len(recs) < 10 or len({r["session"] for r in recs}) < 2:
        return EXIT_NO_ROWS, "bayes: skipped:no-rows (agent rows %d)" % len(recs)
    ix = Index(seed, models, sorted({r["session"] for r in recs}), sorted({r["regime"] for r in recs}))
    p_resume = float(np.mean([r["resume"] for r in recs]))
    rng = np.random.default_rng(cfg["seed"])
    timing, diags, posts = {}, {}, {}
    # --- M1 turns, M2 ctx: the limit variables
    frames = {}
    for name, ycol, kind, center, off in (("turns", "api_calls", "nb", math.log(10), 0),
                                         ("ctx", "ctx", "ln", math.log(1e6), 1)):
        fr = [dict(r, cens=r["cens_" + name]) for r in recs if (r[ycol] or 0) > 0]
        dt, free, secs, dropped = fit_hier(fr, ycol, kind, ix, center, cfg, cfg["seed"] + off)
        diags[MODEL_ID[name]] = diagnostics(dt, free, dropped)
        timing[name] = secs
        posts[name], frames[name] = dt["posterior"].dataset, fr
        log("fit %s: n %d (cens %d) %.1f s" % (name, len(fr), sum(r["cens"] for r in fr), secs))
    # --- M3 scheduler models
    sched_ok, n_ref_ab = not cfg["no_sched"], None
    if sched_ok:
        comp = [dict(r, spc=r["wall_s"] / r["api_calls"], cens=False) for r in recs
                if r["status"] == "complete" and (r["wall_s"] or 0) > 0]
        first = [dict(r, cens=False) for r in recs
                 if r["seg"] == 0 and (r["first_cc"] or 0) > 0 and r["compacted"] != 1]
        abr = [r for r in recs if r["seg"] == 0 and r["status"] == "complete" and r["compacted"] != 1
               and (r["ctx"] or 0) > 0]
        if min(len(comp), len(first), len(abr)) < 10:
            sched_ok = False
    if sched_ok:
        dt, free, secs, dropped = fit_hier(comp, "spc", "ln", ix, math.log(15), cfg, cfg["seed"] + 3,
                                           type_scale=False, zero_avoid=())
        diags[MODEL_ID["spc"]], timing["spc"] = diagnostics(dt, free, dropped), secs
        posts["spc"] = dt["posterior"].dataset
        dt, free, secs, dropped = fit_hier(first, "first_cc", "ln", ix, math.log(3e4), cfg, cfg["seed"] + 4,
                                           sess=False, resume=False, regime=False, type_scale=False, zero_avoid=())
        diags[MODEL_ID["static_cc"]], timing["static_cc"] = diagnostics(dt, free, dropped), secs
        posts["static_cc"] = dt["posterior"].dataset
        dt, free, secs, n_ref_ab = fit_ctx_ab(abr, ix, cfg, cfg["seed"] + 6)
        diags[MODEL_ID["ctx_ab"]], timing["ctx_ab"] = diagnostics(dt, free), secs
        posts["ctx_ab"] = dt["posterior"].dataset
        rcr = [r for r in recs if r["seg"] > 0 and not r["cens_ctx"] and r["prev_peak"] is not None
               and (r["ctx"] or 0) > 0]
        if len(rcr) >= 5:
            dt, free, secs = fit_resume_ctx(rcr, cfg, cfg["seed"] + 11)
            diags[MODEL_ID["resume_ctx"]], timing["resume_ctx"] = diagnostics(dt, free), secs
            posts["resume_ctx"] = dt["posterior"].dataset
        log("fit sched: %s" % {k: round(v, 1) for k, v in timing.items()})
    nuts_s = sum(timing.values())
    gates = {k: bool(L.model_gate({"gate": True, "diag": d})) for k, d in diags.items()}
    t_post = time.perf_counter()
    pv = props or {"vars": {}, "pools": {}}
    hyper, vars_, sched, reg_note = assemble(posts, frames, ix, seed, cur_reg, p_resume, rng, pv,
                                             n_ref_ab, gates, recs, sched_ok)
    post_s = time.perf_counter() - t_post
    t_drift = time.perf_counter()
    checks, dstats = {}, {}
    for k, (name, kind) in enumerate((("turns", "nb"), ("ctx", "ln"))):
        checks[name], dstats[name] = drift_check(posts[name], kind, ix, frames[name], (cfg["seed"], DRIFT_STREAM, k))
    drift = drift_block(checks, gates, prev_drift)
    drift_s = time.perf_counter() - t_drift
    log(f"drift: {drift_summary(dstats)} -> {json.dumps(drift, sort_keys=True)} "
        f"(carried in: {','.join(sorted(prev_drift)) or 'none'}) {drift_s:.1f} s")
    versions = {"python": sys.version.split()[0], "pymc": pm.__version__, "pytensor": pytensor.__version__,
                "nutpie": nutpie.__version__, "arviz": az.__version__, "numpy": np.__version__,
                "scipy": scipy.__version__}
    mids = sorted(diags)
    fit_id = hashlib.sha256(json.dumps([eid, mids, cfg["seed"], versions], sort_keys=True).encode()).hexdigest()[:16]
    doc = {"schema_version": 1, "code": CODE, "generated": _now_iso(), "evidence_id": eid, "seed_sha": seed["sha"],
           "fit_id": fit_id, "risk": dict(L.RISK),
           "sampler": {"seed": cfg["seed"], "chains": cfg["chains"], "draws": cfg["draws"], "tune": cfg["tune"],
                       "target_accept": TARGET_ACCEPT},
           "versions": versions,
           "data": {"rows": len(rows), "agent_rows": len(recs), "sessions": len(ix.sessions),
                    "regimes": len(ix.regimes), "regime_current": reg_note.get("ctx"),
                    "files": {os.path.basename(p): _sha256(p) for p in paths if os.path.exists(p)}},
           "models": {k: {"gate": gates[k], "diag": {kk: d[kk] for kk in (
               "rhat_max", "ess_bulk_min", "ess_tail_min", "divergences", "ebfmi_min", "constant", "nan")}}
               for k, d in diags.items()},
           "hyper": hyper, "drift": drift, "vars": vars_, "sched": sched}
    doc = json.loads(json.dumps(doc))                   # plain floats, no numpy scalars
    why = self_check(doc, seed, eid)
    if why:
        return EXIT_FAIL, "bayes: failed: the document does not validate (%s); nothing written" % why
    write_atomic(out, (json.dumps(doc, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8"))
    acc = L.load_bayes(seed, eid, doc) or {}
    total = time.perf_counter() - t_start
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (2 ** 20 if sys.platform == "darwin" else 2.0 ** 10)
    except (ImportError, OSError):
        rss = 0.0
    line = ("bayes: fit %s rows %d agent_rows %d sessions %d models %d/%d gated blocks %d accepted %d "
            "sched %s nuts_s %.0f post_s %.0f total_s %.0f rss_mib %.0f" % (
                fit_id, len(rows), len(recs), len(ix.sessions), sum(gates.values()), len(gates), len(vars_),
                len(acc), "%d/%d" % (len(sched["types"]), len(sched["pools"])) if sched else "none",
                nuts_s, post_s, total, rss))
    breached = ",".join(sorted(f for f, e in drift.items() if e["breach"])) or "none"
    tail = f" drift {drift_summary(dstats)} breach {breached} drift_s {drift_s:.1f}"
    return EXIT_OK, line + tail[:max(0, SUMMARY_MAX - len(line))]


def assemble(posts, frames, ix, seed, cur_reg, p_resume, rng, pv, n_ref_ab, gates, recs, sched_ok=True, qd_fn=None):
    """The post-sampling part of fit(), numpy only: the turns/ctx hyperparameters, the blocks of turns.<t>,
    soft.agent.<t> and hard.agent.<t> for every seed type, and the sched block (None unless sched_ok).
    posts: {"turns", "ctx"[, "spc", "static_cc", "ctx_ab", "resume_ctx"]: posterior}, each posterior a
    mapping of names to arrays with `.values` shaped (chain, draw[, k]) (an xarray Dataset in the fit);
    frames: the turns and ctx rows each model saw (with `cens`); qd_fn: the per-draw quantity diagnostics
    (qdiag, arviz). Returns (hyper, vars, sched, regime notes)."""
    qd_fn = qd_fn or qdiag
    pool_of = L._pool_of(seed)
    hyper, vars_, sw_types, reg_note = {}, {}, {}, {}
    for name, kind in (("ctx", "ln"), ("turns", "nb")):
        post = posts[name]
        off, extra, reg_note[name] = regime_terms(post, ix, cur_reg, rng)
        hyper[name] = hyper_of(post, kind, ix, p_resume, off, extra)
        for j, t in enumerate(ix.types):
            counts = type_counts(frames[name], t)
            if kind == "ln":
                P = pred_ln(post, j, p_resume, off, extra)
                ps = sorted(set(L.QTAB_P))
                qx = [float(v) for v in P.quantiles(ps)]
                soft_T = None
                for fam in ("soft.agent", "hard.agent"):
                    v = "%s.%s" % (fam, t)
                    if v not in seed["vars"]:
                        continue
                    p = 1 - L.RISK[fam]
                    T_raw = qx[ps.index(p)] if p in ps else float(P.quantiles((p,))[0])
                    qd = P.draw_quantile(p)
                    mrel = P.mcse_rel(T_raw)
                    if fam == "soft.agent":
                        T, at_b = L.ceil2(T_raw), False
                        soft_T, soft_mrel = T, mrel
                    else:
                        T, at_b = L.hard_agent_T(T_raw, soft_T)
                        if soft_T and L.HARD_OVER_SOFT * soft_T > T_raw:     # the binding term: 2 x soft T
                            T_raw, mrel = L.HARD_OVER_SOFT * soft_T, soft_mrel
                    vars_[v] = make_block(fam, MODEL_ID[name], T, T_raw,
                                          [float(np.quantile(qd, .05)), float(np.quantile(qd, .95))], qx, at_b,
                                          counts, shrink_of(post, j), _status(fam, t, counts, pv, pool_of),
                                          qd_fn(qd), mrel, L.CTX_MAX)
            else:
                v = "turns." + t
                P = pred_nb(post, j, p_resume, off, extra)
                kcap = int(min(KMAX, max(SWEEP_MIN, SWEEP_FACTOR * ix.ceiling[t])))
                p = 1 - L.RISK["turns"]
                mix_ps = sorted(set(L.QTAB_P) | {p, 0.25})
                sw = P.sweep(mix_ps, (p, 0.5), kcap)
                sw_types[t] = sw
                if v not in seed["vars"]:
                    continue
                qx = [float(PredNB.quantile_of(sw["mix"][q], q)[0]) if sw["mix"][q] else float(kcap + 1)
                      for q in L.QTAB_P]
                if sw["mix"][p] is not None:
                    _q, T_raw, _pmf = PredNB.quantile_of(sw["mix"][p], p)
                    T, mrel, at_b = int(math.ceil(T_raw)), P.mcse_rel(sw["mix"][p], p), False
                else:                                   # beyond the sweep: T >= kcap + 1 acts as the ceiling
                    T_raw, T, mrel, at_b = float(kcap + 1), kcap + 1, None, True
                qd = 1.0 + sw["draw"][p].reshape(P.shape)
                at_b = at_b or any(x > kcap for x in qx)
                qx = [min(x, float(kcap + 1)) for x in qx]
                vars_[v] = make_block("turns", MODEL_ID[name], T, T_raw,
                                      [float(np.quantile(qd, .05)), float(np.quantile(qd, .95))], qx, at_b, counts,
                                      shrink_of(post, j), _status("turns", t, counts, pv, pool_of), qd_fn(qd), mrel,
                                      float(kcap + 1))
    # --- the sched block
    sched = build_sched(posts, gates, ix, recs, sw_types, p_resume, cur_reg, rng, n_ref_ab) if sched_ok else None
    return hyper, vars_, sched, reg_note


def _status(fam, t, counts, pv, pool_of):
    ent = pv["vars"].get("%s.%s" % (fam, t))
    pool = pv["pools"].get("%s:%s" % (fam, pool_of.get(t)))
    cls = L.classify(fam, ent, pool)[0] if (ent or pool) else None
    return "supported" if cls == "supported" else ("pooled" if counts["n"] > 0 else "prior")


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _ab_draws(k, q, n_ref):
    """(a, b) per draw of ctx(n) = a n + b n^2 from (k, q) at n_ref: a = e^k (1 - s), b = e^k s / n_ref."""
    s = 1.0 / (1.0 + np.exp(-q))
    return (np.exp(k) * (1 - s)).ravel(), (np.exp(k) * s / n_ref).ravel()


def build_sched(posts, gates, ix, recs, sw_types, p_resume, cur_reg, rng, n_ref_ab):
    """BAYES.md 2.2: `types` with own healthy segments, `pools` with such a member (a new type of the pool:
    the class-level predictive), `resume_ctx` and `fixer` when their models qualify; `model_gate` from the
    four source models' gates (the reader uses the block only when all four pass). None without the
    scheduler models."""
    if any(k not in posts for k in ("turns", "spc", "static_cc", "ctx_ab")):
        return None
    ps, pst, pab, ptu = posts["spc"], posts["static_cc"], posts["ctx_ab"], posts["turns"]
    off_s, ex_s, _ = regime_terms(ps, ix, cur_reg, rng)
    off_t, ex_t, _ = regime_terms(ptu, ix, cur_reg, rng)
    zero = np.zeros(pst["a0"].shape)
    k_t, q_t = _v(pab, "k_t"), _v(pab, "q_t")
    shape = k_t.shape[:2]
    types, pools = {}, {}
    for j, t in enumerate(ix.types):
        cnt = sched_counts(recs, lambda r, t=t: r["type"] == t)
        if cnt["n_seg"] < 1 or t not in sw_types:
            continue
        e = sched_entry(sw_types[t], pred_ln(ps, j, p_resume, off_s, ex_s), pred_ln(pst, j, 0.0, zero, zero),
                        _ab_draws(k_t[..., j], q_t[..., j], n_ref_ab), cnt, True)
        if e:
            types[t] = e
    upk = np.concatenate([_v(pab, "u_pk"), np.zeros(shape + (1,))], axis=-1)
    upq = np.concatenate([_v(pab, "u_pq"), np.zeros(shape + (1,))], axis=-1)
    for pool in ix.pools:
        mj = ix.members(pool)
        mem = {ix.types[j] for j in mj}
        cnt = sched_counts(recs, lambda r, mem=mem: r["type"] in mem)
        if not mj or cnt["n_seg"] < 1:
            continue
        P = pred_nb(ptu, None, p_resume, off_t, ex_t, pool=pool, ix=ix, rng=rng)
        kcap = int(min(KMAX, max(SWEEP_MIN, SWEEP_FACTOR * max(ix.ceiling[t] for t in mem))))
        sw = P.sweep((0.25, 0.5, 0.9), (0.5,), kcap)
        pe = ix.t_peff[mj[0]]
        kk = _v(pab, "K0") + upk[..., pe] + _v(pab, "tau_tk") * rng.standard_normal(shape)
        qq = _v(pab, "Q0") + upq[..., pe] + _v(pab, "tau_tq") * rng.standard_normal(shape)
        e = sched_entry(sw, pred_ln(ps, None, p_resume, off_s, ex_s, pool=pool, ix=ix, rng=rng),
                        pred_ln(pst, None, 0.0, zero, zero, pool=pool, ix=ix, rng=rng),
                        _ab_draws(kk, qq, n_ref_ab), cnt, False)
        if e:
            pools[pool] = e
    if not types and not pools:
        return None
    out = {"model_gate": {k: bool(gates.get(MODEL_ID[m])) for k, m in SCHED_GATES.items()},
           "types": types, "pools": pools}
    if "resume_ctx" in posts and gates.get(MODEL_ID["resume_ctx"]):
        pr = posts["resume_ctx"]
        q = lambda v, p: _r(float(np.quantile(_v(pr, v), p)) * 1e4)  # noqa: E731
        rc = {"alpha": q("alpha", .5), "gamma": q("gamma", .5), "lo": [q("alpha", .05), q("gamma", .05)],
              "hi": [q("alpha", .95), q("gamma", .95)]}
        if all(_pos(x) for x in [rc["alpha"], rc["gamma"]] + rc["lo"] + rc["hi"]) \
                and all(a <= b for a, b in zip(rc["lo"], rc["hi"])):
            out["resume_ctx"] = rc
    fx = fixer_entry(recs, ix)
    if fx:
        out["fixer"] = fx
    return out


def fixer_entry(recs, ix):
    """The fixer's reread (conjugate NIG on log values, stack_bayes_grid.nig_lognormal): builder-pool first
    segments with ctx_at_first_write > first_ctx; only with >= 5 rows from >= 3 agents."""
    from stack_bayes_grid import nig_lognormal
    mem = {t for t in ix.types if ix.pool_of[t] == "builder"}
    f = [r for r in recs if r["seg"] == 0 and r["type"] in mem and r["ctx_at_first_write"] is not None
         and r["first_ctx"] is not None and r["ctx_at_first_write"] > r["first_ctx"]]
    if len(f) < 5 or len({(r["session"], r["id"]) for r in f}) < 3:
        return None
    res = nig_lognormal([math.log(r["ctx_at_first_write"] - r["first_ctx"]) for r in f], math.log(2e5))
    if res is None:
        return None
    med, lo, hi, n = res
    fx = {"reread": _r(med), "lo": _r(min(lo, med)), "hi": _r(max(hi, med)), "level": 0.95, "n": int(n)}
    return fx if all(_pos(fx[k]) for k in ("reread", "lo", "hi")) else None


def self_check(doc, seed, eid):
    """None when stack_limits' reader takes the document whole (rules 1, 3, 4 and the fields every reader
    checks) and every sched entry is valid; else the reason. A refused document is never written."""
    try:
        raw = json.dumps(doc).encode("utf-8")
        if len(raw) > L.BAYES_MAX_BYTES:
            return "size %d" % len(raw)
        L._bayes_doc_checked(doc, seed)
    except L._BayesInvalid as exc:
        return str(exc)
    if doc["evidence_id"] != eid:
        return "evidence_id"
    sc = doc.get("sched")
    if sc is not None:
        for group, typed in (("types", True), ("pools", False)):
            for k, e in sc[group].items():
                if not sched_entry_ok(e, typed):
                    return "sched %s %s" % (group, k)
    return None


# ---------------------------------------------------------------- CLI
def main(argv=None):
    ap = argparse.ArgumentParser(prog="stack_bayes.py")
    ap.add_argument("cmd", choices=("fit", "check"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--chains", type=int, default=CHAINS)
    ap.add_argument("--draws", type=int, default=DRAWS)
    ap.add_argument("--tune", type=int, default=TUNE)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--no-sched", action="store_true")
    ap.add_argument("--timeout", type=int, default=FIT_TIMEOUT_S)
    ap.add_argument("--regime", default=None)
    a = ap.parse_args(argv)
    if a.cmd != "fit":
        return _main(a)
    if not 1 <= a.timeout <= TIMEOUT_MAX_S:
        print("bayes: failed: timeout out of range", flush=True)
        return EXIT_FAIL
    if a.regime is not None and not regime_ok(a.regime):
        print("bayes: failed: --regime is not 16 lowercase hex digits", flush=True)
        return EXIT_FAIL
    prev = arm_deadline(a.timeout)
    try:
        return _main(a)
    finally:
        disarm_deadline(prev)


def _main(a):
    os.environ.update(cache_env())                 # before pytensor or numba is imported
    miss = missing_deps()
    if miss:
        print("bayes: skipped:no-pymc (missing: %s)" % ", ".join(miss), flush=True)
        return EXIT_NO_PYMC
    if a.cmd == "check":
        print("bayes: check ok", flush=True)
        return EXIT_OK
    if not (1 <= a.chains <= 64 and 100 <= a.draws <= 100000 and 100 <= a.tune <= 100000):
        print("bayes: failed: sampler settings out of range", flush=True)
        return EXIT_FAIL
    for d in cache_dirs():
        os.makedirs(d, mode=0o700, exist_ok=True)
    out = a.out or L.bayes_path()
    cfg = {"chains": a.chains, "draws": a.draws, "tune": a.tune, "seed": a.seed, "no_sched": a.no_sched,
           "regime": a.regime}
    try:
        rc, line = fit(cfg, out, log=lambda s: print(s, file=sys.stderr, flush=True))
    except Exception as exc:  # noqa: BLE001 - detached: one line, the type only (no row data in the record)
        rc, line = EXIT_FAIL, "bayes: failed: %s" % type(exc).__name__
    print(line, flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
