#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""B1-T14 (docs/BAYES.md A.9, A.11): the rolling-origin calibration backtest of the Bayes limits, stdlib only.

Run (the verifier, WP5):  B1_REPO=<main checkout> uv run --no-cache --script tests/b1_backtest.py \
                              [--data DIR] [--hyper-ctx F --hyper-turns F | --hyper-dir D] [--support production|any]
                              [--out summary.json]

Rolling origin over the sessions of the rows (usage runs*.csv, read by stack_limits.read_rows of B1_REPO's hooks),
ordered by their first row: fold k tests on session k and trains on sessions 0 .. k - 1 only. A fold is eligible
when it trains on at least 2 sessions (A.11.3); --min-train-sessions only chooses which folds are scored. For each
family (soft.agent, hard.agent, turns) and type with test rows, the grid tier of stack_bayes_grid, conditional on
the hyperparameters (2.1 `hyper` shape, or the v2 `{"nuts": ...}` files with tau_new = tau_s), gives the posterior of
the type's location from the fold's training rows (censored per A.3) and the new-session predictive: T = its
(1 - r) quantile (hard.agent: max(q_.99, 2 x soft T), clamped [2M, 200M]); the deployed value = decide_bayes at
c = the value in force (the seed of the data's day, --seed-file: the prototype's approximation, A.10).

Strata (A.11.2), both scored and printed: *production* = support as apply computes it, on the training rows of the
test session's own regime (its earliest row's `regime` cell; stack_limits._entry_regime, then classify); *any* =
support with regime_ok forced true on every training row of the type. --support names the gating one (default
production; any-regime is a calibration diagnostic, never binding). --strata ntrain replaces stack_limits support by
"at least 5 training rows" (in the test regime for production): the frozen-fixture convention of A.10.

Scoring per family x stratum (supported / sparse), for T, the deployed value and c: an uncensored test row above
the value is a hit; a censored row (a lower bound) above it is a hit, below it unknown, so counts are intervals
[lo, hi]. PIT: F(y) for an uncensored log-normal row, U(F(y - 1), F(y)) for an uncensored NB row, the randomized
U(F(y-), 1) for a censored one, F(y-) = P(Y < y): F(y) for the log-normal, F(y - 1) for the NB; coverage90 = share
of PITs in [0.05, 0.95]. The session-clustered check simulates the test rows from the predictive with one shared
new-session effect per fold (--sims draws K0) and reports P(K >= lo) and P(K <= hi) (deny-type families are read
one-sided, "no excess": P(K >= lo) only, A.7, A.11.1).

Informativeness (A.11.1) on the gating stratum's supported rows: n rows, u = hi - lo unknown, m = n - u scorable;
I1 m >= 40, I2 u / n <= 0.10, I3 (soft families) u < q05 = min{k : #{K0 <= k} >= 0.05 sims} on the same K0.
Power (A.11.1): power_2.5r, the share of --sims replicates (one w per fold, y* = pred.draw(rnd, w) for every row, a
hit when y* > T_alt = pred.quantile(1 - 2.5 r), the marginal quantile, counted on the rows scorable in the data;
hi_sim = lo_sim + u) with P0(K >= lo_sim) < 0.05; power_r/5 the same with T_alt = pred.quantile(1 - r/5) and
P0(K <= hi_sim) < 0.05 (reported, never gated). power_ok = power_2.5r >= B1_MIN_POWER.

Verdict per family (A.11.4), first match wins: an error exits 2; fewer than 3 eligible folds with >= 1 test row in
the gating stratum's supported rows: REJECT (folds); a failed fold gate (fold<k>_gate.json of --hyper-dir, written
by tests/b1_folds.py, for the family's model) for any scored fold: blocked:gate; informative false: REJECT
(informative); a failed check (clustered, coverage90, sparse hits(deployed) <= hits(current) at both ends): REJECT;
else ACCEPT, with power_ok. Exit 0 when every family of --families is ACCEPT (power_ok false keeps it), else 1.
Hyperparameters fitted on all rows (the default v2 files) include the test rows: the verdict is then optimistic and
is printed as such; WP5 passes fold-specific files (--hyper-dir D: D/fold<k>_ctx.json, D/fold<k>_turns.json and
D/fold<k>_gate.json, whose evidence_id must be the fold's training rows').
"""
import argparse
import itertools
import json
import math
import os
import random
import sys
from bisect import bisect_left, bisect_right

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("B1_REPO") or os.path.dirname(HERE)
HOOKS = os.path.join(REPO, "dot-config", "dot-claude", "hooks")
sys.path.insert(0, HOOKS)
import stack_bayes_grid as G  # noqa: E402
import stack_limits as L  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "bayes", "b1v2")
V2_OUT = os.path.join(REPO, "docs", "bayes", "b1v2", "out_v2")
FAMILIES = ("soft.agent", "hard.agent", "turns")
SOFT_FAMILIES = ("soft.agent",)          # I3 and the two-sided check; turns and hard.agent are deny-type (A.7)
P_RESUME_V2 = 0.3238434163701068
B1_MIN_POWER = 0.5                       # user decision 2026-10-09 (A.11.1)
ALPHA = 0.05
I1_MIN_M = 40                            # scorable rows
I2_MAX_U_TENTHS = 1                      # u / n <= 0.10, as u * 10 <= n
MIN_FOLDS = 3
ELIGIBLE_TRAIN = 2                       # a fold is eligible when it trains on >= 2 sessions
SETS = ("production", "any")
STRATA = ("supported", "sparse")
CSV_NAMES = ("runs.1.csv", "runs.csv", "runs2.1.csv", "runs2.csv", "runs3.1.csv", "runs3.csv")


# ---------------------------------------------------------------- inputs
def load_hyper_file(path, p_resume):
    """2.1 `hyper.<model>` shape, or the v2 prototype's {"nuts": {tau_t, tau_s, rho, types}} (tau_new = tau_s)."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    h = doc.get("nuts", doc)
    return {"tau_t": float(h["tau_t"]), "tau_new": float(h.get("tau_new", h.get("tau_s", 0.0))),
            "rho": float(h.get("rho", 0.0)), "p_resume": float(h.get("p_resume", p_resume)),
            "types": {t: {"mu": float(v["mu"]), "scale": float(v["scale"])} for t, v in h["types"].items()}}


def data_paths(data):
    return [os.path.join(data, n) for n in CSV_NAMES if os.path.exists(os.path.join(data, n))]


def read_data(data):
    """(rows, session order, rows by session) of a usage directory, as the proposer reads them."""
    rows, _stats = L.read_rows(data_paths(data), models=L.agent_models(os.path.join(REPO, "dot-config", "dot-claude",
                                                                                     "agents")))
    by_sess = {}
    for r in rows:
        by_sess.setdefault(r["session"], []).append(r)
    return rows, session_order(rows), by_sess


def session_order(rows):
    first = {}
    for r in rows:
        first[r["session"]] = min(first.get(r["session"], r["ts"]), r["ts"])
    return sorted(first, key=lambda s: (first[s], s))


def fold_ids(n_sessions, min_train, last):
    """The scored folds: k trains on sessions 0 .. k - 1, so k >= max(1, min_train); the last `last` (0: all)."""
    ks = [k for k in range(1, n_sessions) if k >= min_train]
    return ks[-last:] if last else ks


def fold_regime(rows):
    """A test session's regime: the `regime` cell of its earliest row that has one (the regime current at that
    session's start, A.11.2/A.11.3); None when no row has one."""
    for r in sorted(rows, key=lambda r: (r["ts"], r["id"], r["seg"])):
        if r.get("regime"):
            return r["regime"]
    return None


def blists(rows, fam, seed, win_hits, t):
    """(y, cens, resume) of a type's rows for a family (A.3 censoring; the limit in force: the seed)."""
    qn = "api_calls" if fam == "turns" else "ctx"
    cf = "turns" if fam == "turns" else "ctx"
    lim = seed["vars"].get(("turns." if fam == "turns" else "soft.agent.") + t, {}).get("seed")
    out = []
    for r in sorted(rows, key=lambda r: (r["ts"], r["session"], r["id"], r["seg"])):
        y = r[qn]
        if y is None or y <= 0:
            continue
        out.append((float(y), int(L.censor_flags(r, cf, lim, win_hits)), int(r["seg"] > 0)))
    return out


def read_gate(hyper_dir, k, eid):
    """fold<k>_gate.json (tests/b1_folds.py): {"ok", "models": {model: {"ok"}}, "reason"}. A missing or malformed
    file is a failed gate (A.11.3: no valid fit counts as a failed gate). ValueError when its evidence_id is not the
    fold's training rows' (hyperparameters of another fold or other data: an error, exit 2)."""
    p = os.path.join(hyper_dir, f"fold{k}_gate.json")
    try:
        with open(p, encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError) as exc:
        return {"ok": False, "models": {}, "reason": f"no readable gate file ({type(exc).__name__})"}
    if not isinstance(doc, dict) or doc.get("fold") != k or not isinstance(doc.get("models"), dict):
        return {"ok": False, "models": {}, "reason": "malformed gate file"}
    if doc.get("evidence_id") != eid:
        raise ValueError(f"fold {k}: {p} has evidence_id {str(doc.get('evidence_id'))[:16]}..., not the fold's "
                         f"training rows' {eid[:16]}...: hyperparameters of another fold or other data")
    models = {m: {"ok": isinstance(v, dict) and v.get("ok") is True} for m, v in doc["models"].items()
              if isinstance(m, str)}
    return {"ok": doc.get("ok") is True, "models": models, "reason": doc.get("reason"), "regime": doc.get("regime")}


def gate_ok(gate, model):
    return gate is None or gate["models"].get(model, {}).get("ok") is True


# ---------------------------------------------------------------- the grid tier per type
class Pred:
    """The grid posterior and new-session predictive of one type and family."""

    def __init__(self, fam, atype, train, h):
        self.fam, self.h = fam, h
        self.rho, self.tau, self.tnew, self.pres = h["rho"], h["tau_t"], h["tau_new"], h["p_resume"]
        tp = h["types"][atype]
        self.mu, self.scale = tp["mu"], tp["scale"]
        obs = [(y, rs) for y, c, rs in train if not c]
        cen = [(y, rs) for y, c, rs in train if c]
        if fam == "turns":
            ys = [int(round(y)) for y, _ in obs]
            cs = [(int(round(y)), rs) for y, rs in cen if y > 1]
            self.etas, self.w, self.info = G.nb_post(ys, [c for c, _ in cs], self.mu, self.tau, self.scale,
                                                     [self.rho * rs for _, rs in obs], [self.rho * rs for _, rs in cs])
            kmax = int(min(5000, max(200, 4 * max([y for y, _, _ in train] or [50]))))
            self.pred = G.nb_predictive(self.etas, self.w, self.scale, self.tnew, self.rho, self.pres, kmax=kmax)
        else:
            self.etas, self.w, self.info = G.lognormal_post([math.log(y) for y, _ in obs], [math.log(y) for y, _ in cen],
                                                            self.mu, self.tau, self.scale,
                                                            [self.rho * rs for _, rs in obs], [self.rho * rs for _, rs in cen])
        self.cw = list(itertools.accumulate(self.w))      # rnd.choices(weights=w) draws the same stream

    def quantile(self, p):
        """The marginal (new-session effect integrated) predictive p quantile of a new run."""
        if self.fam == "turns":
            return float(G.nb_quantile_from(self.pred, p)[0])
        return math.exp(G.lognormal_quantile(self.etas, self.w, p, self.scale, self.tnew, self.rho, self.pres)[0])

    def cdf(self, y):
        """P(Y <= y) of a new run."""
        if self.fam == "turns":
            k = int(math.floor(y)) - 1
            mix = self.pred["mix"]
            return 0.0 if k < 0 else (mix[k] if k < len(mix) else 1.0)
        return G.lognormal_pred_cdf(self.etas, self.w, math.log(y), self.scale, self.tnew, self.rho, self.pres)

    def qtab(self):
        x = [max(self.quantile(p), 1e-9) for p in L.QTAB_P]
        for k in range(1, len(x)):
            x[k] = max(x[k], x[k - 1])
        return {"p": list(L.QTAB_P), "x": x}

    def draw(self, rnd, w):
        """One new run's demand given the shared session effect w (standard normal units)."""
        e = rnd.choices(self.etas, cum_weights=self.cw)[0]
        rr = self.rho if rnd.random() < self.pres else 0.0
        if self.fam == "turns":
            mu = math.exp(e + rr + self.tnew * w)
            lam = rnd.gammavariate(self.scale, mu / self.scale) if mu > 0 else 0.0
            return 1 + poisson(rnd, lam)
        return math.exp(e + rr + self.tnew * w + self.scale * rnd.gauss(0, 1))


def poisson(rnd, lam):
    if lam > 500:
        return max(0, int(round(rnd.gauss(lam, math.sqrt(lam)))))
    k, p, u = 0, math.exp(-lam), rnd.random()
    c = p
    while u > c and k < 100000:
        k += 1
        p *= lam / k
        c += p
    return k


# ---------------------------------------------------------------- scoring
def hits(rows, value):
    """[lo, hi] hit counts of test rows (y, cens) against a value (None = off: no hit)."""
    if value is None:
        return [0, 0]
    lo = sum(1 for y, c in rows if y > value)
    unknown = sum(1 for y, c in rows if c and y <= value)
    return [lo, lo + unknown]


def pit(pred, y, cens, rnd):
    """Randomized PIT: censored U(F(y-), 1) with F(y-) = P(Y < y) (F(y - 1) for the NB, whose censored term is
    log P(Y >= y)); uncensored NB U(F(y - 1), F(y)); uncensored log-normal F(y)."""
    if cens:
        f = pred.cdf(y - 1) if pred.fam == "turns" else pred.cdf(y)
        return f + (1 - f) * rnd.random()
    if pred.fam == "turns":
        a, b = pred.cdf(y - 1), pred.cdf(y)
        return a + (b - a) * rnd.random()
    return pred.cdf(y)


def p_ge(k0_sorted, x):
    """P0(K >= x) on the empirical CDF of the sorted null draws."""
    return (len(k0_sorted) - bisect_left(k0_sorted, x)) / len(k0_sorted)


def p_le(k0_sorted, x):
    """P0(K <= x) on the empirical CDF of the sorted null draws."""
    return bisect_right(k0_sorted, x) / len(k0_sorted)


def q05_of(k0):
    """I3's q05 = min{k : #{K0 <= k} >= 0.05 sims} (A.11.1), on the same empirical CDF as P(K <= hi); None without
    draws. #{K0 <= k} >= sims / 20 holds first at the ceil(sims / 20)-th smallest draw, so exactly 5 % of draws at 0
    gives 0 (an index K0[int(0.05 sims)] would give the next value)."""
    if not k0:
        return None
    s = sorted(k0)
    need = (len(s) + 19) // 20                           # ceil(sims / 20) >= 1
    return s[need - 1]


def simulate_null(fold_items, sims, rnd):
    """K0 per replicate: per fold one shared new-session effect w, every stratum row drawn from its type's
    predictive, a hit when y* > T; summed over the folds."""
    k0 = [0] * sims
    for items in fold_items:
        for s in range(sims):
            w = rnd.gauss(0, 1)
            k0[s] += sum(1 for pred, T, te in items for _y in te if pred.draw(rnd, w) > T)
    return k0


def simulate_power(fold_items, k0, sims, rnd, r):
    """(power_2.5r, power_r/5), A.11.1: replicates as the null's (one w per fold, y* = pred.draw(rnd, w) for every
    row of the stratum), hits counted only on the rows scorable in the data (uncensored, or censored above T);
    the rows unknown in the data add 1 each to hi_sim = lo_sim + u. power_2.5r: hit when y* > T_alt =
    pred.quantile(1 - 2.5 r), the marginal quantile (marginal hit rate 2.5 r, hits clustered by session), rejected
    on the too-many side only, P0(K >= lo_sim) < 0.05. power_r/5: T_alt = pred.quantile(1 - r/5), the too-few side,
    P0(K <= hi_sim) < 0.05. P0 = the empirical CDF of k0 (the null draws). None without rows or draws."""
    if not fold_items or not k0:
        return None, None
    ks = sorted(k0)
    lo_many, lo_few, u = [0] * sims, [0] * sims, 0
    for items in fold_items:
        rows = []
        for pred, T, te in items:
            ta, tb = pred.quantile(1 - 2.5 * r), pred.quantile(1 - r / 5)
            for y, c in te:
                sc = (not c) or y > T
                u += not sc
                rows.append((pred, ta, tb, sc))
        for s in range(sims):
            w = rnd.gauss(0, 1)
            for pred, ta, tb, sc in rows:
                ys = pred.draw(rnd, w)
                if sc:
                    lo_many[s] += ys > ta
                    lo_few[s] += ys > tb
    many = sum(1 for s in range(sims) if p_ge(ks, lo_many[s]) < ALPHA) / sims
    few = sum(1 for s in range(sims) if p_le(ks, lo_few[s] + u) < ALPHA) / sims
    return many, few


def informativeness(fam, n, lo, hi, k0):
    """A.11.1 on the gating stratum: I1 m >= 40, I2 u / n <= 0.10, I3 (soft families) u < q05."""
    u = hi - lo
    m = n - u
    q05 = q05_of(k0)
    failed = []
    if m < I1_MIN_M:
        failed.append("I1")
    if not n or u * 10 > n * I2_MAX_U_TENTHS:
        failed.append("I2")
    if fam in SOFT_FAMILIES and (q05 is None or not u < q05):
        failed.append("I3")
    return {"ok": not failed, "n": n, "m": m, "u": u, "q05": q05, "failed": failed}


def verdict_of(folds_ok, gate_failed, informative_ok, checks_ok):
    """A.11.4, first match wins (an error is exit 2 before this): (verdict, reason)."""
    if not folds_ok:
        return "REJECT", "folds"
    if gate_failed:
        return "blocked:gate", "gate"
    if not informative_ok:
        return "REJECT", "informative"
    if not checks_ok:
        return "REJECT", "check"
    return "ACCEPT", None


def power_ok_of(power):
    return power is not None and power >= B1_MIN_POWER


def _new_acc():
    return {"T": [0, 0], "deployed": [0, 0], "current": [0, 0], "n": 0, "pits": [], "types": 0}


def _stratum_summary(a, k0):
    if not a["n"]:
        return {"n": 0}
    lo, hi = a["T"]
    pits = a["pits"]
    ks = sorted(k0) if k0 else []
    return {"n": a["n"], "types": a["types"], "hits_T": a["T"], "hits_deployed": a["deployed"],
            "hits_current": a["current"], "coverage90": round(sum(1 for u in pits if 0.05 <= u <= 0.95) / len(pits), 4),
            "pit_mean": round(sum(pits) / len(pits), 4),
            "p_ge_lo": round(p_ge(ks, lo), 4) if ks else None, "p_le_hi": round(p_le(ks, hi), 4) if ks else None}


def _checks(fam, sup, spa):
    checks = {}
    if sup.get("n"):
        two_sided = fam in SOFT_FAMILIES
        checks["clustered"] = sup["p_ge_lo"] >= ALPHA and (sup["p_le_hi"] >= ALPHA or not two_sided)
        checks["coverage90"] = 0.8 <= sup["coverage90"] <= 0.97
    else:
        checks["supported_rows"] = False
    if spa.get("n"):
        checks["sparse_deployed_le_current"] = (spa["hits_deployed"][0] <= spa["hits_current"][0]
                                                and spa["hits_deployed"][1] <= spa["hits_current"][1])
    return checks


def run(args):
    seed = L.load_seed(args.seed_file) if args.seed_file else L.load_seed()
    _rows, order, by_sess = read_data(args.data)
    folds = fold_ids(len(order), args.min_train_sessions, args.folds)
    gating = "production" if args.support in ("production", "regime") else "any"
    rnd = random.Random(args.rng_seed)
    acc = {(f, ss, s): _new_acc() for f in FAMILIES for ss in SETS for s in STRATA}
    items = {(f, ss): {} for f in FAMILIES for ss in SETS}         # fold -> [(pred, T, te)] of the supported rows
    rowfolds = {(f, ss): set() for f in FAMILIES for ss in SETS}   # folds with >= 1 supported test row
    gates, blocked = {}, {f: [] for f in FAMILIES}
    leak = not args.hyper_dir
    fold_info = []
    for k in folds:
        test_s, train_s = order[k], order[:k]
        if test_s in train_s:                                      # A.11.3: never trains on the test session
            raise ValueError(f"fold {k}: the test session is in its training set")
        train = [r for s in train_s for r in by_sess[s]]
        test = by_sess[test_s]
        regime = fold_regime(test)
        eid = L.evidence_id(train)
        gate = read_gate(args.hyper_dir, k, eid) if args.hyper_dir else None
        gates[k] = gate
        fold_info.append({"fold": k, "test_session": test_s, "train_sessions": len(train_s), "regime": regime,
                          "evidence_id": eid})
        pres = sum(1 for r in train if r["scope"] == "agent" and r["seg"] > 0) / max(
            1, sum(1 for r in train if r["scope"] == "agent"))
        hy = {}
        for fam_key, default in (("ctx", args.hyper_ctx), ("turns", args.hyper_turns)):
            path = os.path.join(args.hyper_dir, f"fold{k}_{fam_key}.json") if args.hyper_dir else default
            if not gate_ok(gate, L.HYPER_MODEL[fam_key]) and not os.path.exists(path):
                hy[fam_key] = None                                 # no valid fit: nothing to score (blocked)
                continue
            hy[fam_key] = load_hyper_file(path, pres)
        wh_train, wh_test = L.win_hits_of(train), L.win_hits_of(test)
        types = sorted({r["type"] for r in test if r["scope"] == "agent"})
        softT = {}
        for fam in FAMILIES:                                     # soft.agent first: hard.agent needs its T
            if not gate_ok(gate, L.BAYES_MODEL[fam]):
                blocked[fam].append(k)
            h = hy["turns" if fam == "turns" else "ctx"]
            for t in types:
                v = f"{fam}.{t}"
                if v not in seed["vars"] or (h is not None and t not in h["types"]):
                    continue
                te = [(y, c) for y, c, _ in blists([r for r in test if r["scope"] == "agent" and r["type"] == t],
                                                   fam, seed, wh_test, t)]
                if not te:
                    continue
                spec = seed["vars"][v]
                tr_rows = [r for r in train if r["scope"] == "agent" and r["type"] == t]
                tr = blists(tr_rows, fam, seed, wh_train, t)
                key = f"bt:{k}:{v}"
                ents, sup = {}, {}
                ents["any"] = L._entry(tr_rows, fam, spec["kind"], 0, key, {}) if tr_rows else None
                if ents["any"]:
                    ents["any"]["regime_ok"] = True
                ents["production"] = (L._entry_regime(tr_rows, fam, spec["kind"], 0, key, regime, {})
                                      if tr_rows else None)
                for ss in SETS:
                    if ents[ss]:
                        ents[ss] = L._valid_entry(ents[ss], spec["unit"])
                    if args.strata == "ntrain":                  # the frozen-fixture convention (A.10, T4a)
                        pool = tr if ss == "any" else blists([r for r in tr_rows if regime and r["regime"] == regime],
                                                             fam, seed, wh_train, t)
                        sup[ss] = len(pool) >= 5
                    else:
                        sup[ss] = bool(ents[ss]) and L.classify(fam, ents[ss], None)[0] == "supported"
                if h is None:                                    # a failed fold without hyperparameters: the
                    for ss in SETS:                              # fold count only (the family is blocked)
                        if sup[ss]:
                            rowfolds[(fam, ss)].add(k)
                    continue
                pred = Pred(fam, t, tr, h)
                r_ = L.RISK[fam]
                if fam == "hard.agent":
                    T, _ab = L.hard_agent_T(pred.quantile(0.99), softT.get(t))
                elif fam == "turns":
                    T = math.ceil(pred.quantile(1 - r_))
                else:
                    T = int(L.ceil2(pred.quantile(1 - r_)))
                    softT[t] = T
                c = spec["seed"]
                qt = pred.qtab()
                pits = [pit(pred, y, cc, rnd) for y, cc in te]
                for ss in SETS:
                    ent = ents[ss]
                    deployed = c
                    if ent:
                        blk = {"tier": "grid", "model": "backtest", "risk": r_, "T": T, "T_raw": T, "pi90": [T, T],
                               "qtab": qt, "at_bound": False, "n": len(tr), "n_cens": sum(x[1] for x in tr),
                               "agents": ent["agents"], "sessions": ent["sessions"], "shrink": None,
                               "status": "pooled", "diag": {}}
                        st, _rec = L.decide_bayes(v, spec, L._var_state(c), blk, ent, None,
                                                  softT.get(t) if fam == "hard.agent" else None, 1.0)
                        deployed = st["value"]
                    stratum = "supported" if sup[ss] else "sparse"
                    a = acc[(fam, ss, stratum)]
                    for name, val in (("T", T), ("deployed", deployed), ("current", c)):
                        lo, hi = hits(te, val)
                        a[name][0] += lo
                        a[name][1] += hi
                    a["n"] += len(te)
                    a["types"] += 1
                    a["pits"] += pits
                    if sup[ss]:
                        items[(fam, ss)].setdefault(k, []).append((pred, T, te))
                        rowfolds[(fam, ss)].add(k)
    out = {"repo": REPO, "data": args.data, "folds": [order[k] for k in folds], "fold_info": fold_info,
           "min_train_sessions": args.min_train_sessions, "strata": args.strata, "support": gating,
           "b1_min_power": B1_MIN_POWER,
           "hyper": "fold-specific" if args.hyper_dir else "single (includes the test rows: optimistic)", "families": {}}
    ok_all = True
    for fam in FAMILIES:
        res = {"strata": {}}
        k0s = {}
        for ss in SETS:
            fold_items = [items[(fam, ss)][k] for k in folds if k in items[(fam, ss)]]
            k0s[ss] = simulate_null(fold_items, args.sims, rnd) if fold_items else []
            sup = _stratum_summary(acc[(fam, ss, "supported")], k0s[ss])
            spa = _stratum_summary(acc[(fam, ss, "sparse")], [])
            res["strata"][ss] = {"supported": sup, "sparse": spa, "checks": _checks(fam, sup, spa)}
        nfolds = {ss: sum(1 for k in rowfolds[(fam, ss)] if k >= ELIGIBLE_TRAIN) for ss in SETS}
        a = acc[(fam, gating, "supported")]
        info = informativeness(fam, a["n"], a["T"][0], a["T"][1], k0s[gating])
        info.update(folds_production=nfolds["production"], folds_any=nfolds["any"])
        fold_items = [items[(fam, gating)][k] for k in folds if k in items[(fam, gating)]]
        p_many, p_few = simulate_power(fold_items, k0s[gating], args.sims, rnd, L.RISK[fam])
        folds_ok = nfolds[gating] >= MIN_FOLDS
        checks = dict(res["strata"][gating]["checks"], folds=folds_ok)
        verdict, reason = verdict_of(folds_ok, bool(blocked[fam]), info["ok"],
                                     all(v for kk, v in checks.items() if kk != "folds"))
        res.update(verdict=verdict, reason=reason, accept=verdict == "ACCEPT", gating=gating, informative=info,
                   checks=checks, blocked_folds=blocked[fam], power_ok=power_ok_of(p_many),
                   gates=({str(k): g for k, g in gates.items()} if args.hyper_dir else None))
        res["power_2.5r"], res["power_r/5"] = p_many, p_few
        out["families"][fam] = res
        if fam in args.families:
            ok_all = ok_all and verdict == "ACCEPT"
    out["accept"] = ok_all
    return out, leak


def _fmt_stratum(fam, ss, stratum, r):
    if not r.get("n"):
        return f"  {fam:<11} {ss:<10} {stratum:<9} no test rows"
    return (f"  {fam:<11} {ss:<10} {stratum:<9} n {r['n']:<4} hits T {r['hits_T']} deployed {r['hits_deployed']} "
            f"current {r['hits_current']}  cov90 {r['coverage90']}  PIT mean {r['pit_mean']}  "
            f"P(K>=lo) {r.get('p_ge_lo')} P(K<=hi) {r.get('p_le_hi')}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="B1-T14 rolling-origin backtest (docs/BAYES.md A.9, A.11)")
    ap.add_argument("--data", default=FIX, help="directory with runs*.csv (default: the frozen fixture)")
    ap.add_argument("--seed-file", default=None, help="limits seed (the values in force); default: B1_REPO's")
    ap.add_argument("--hyper-ctx", default=os.path.join(V2_OUT, "hyper_ctx.json"))
    ap.add_argument("--hyper-turns", default=os.path.join(V2_OUT, "hyper_turns.json"))
    ap.add_argument("--hyper-dir", default=None,
                    help="fold-specific fold<k>_{ctx,turns,gate}.json (tests/b1_folds.py)")
    ap.add_argument("--folds", type=int, default=0, help="use the last N folds (0: all)")
    ap.add_argument("--min-train-sessions", type=int, default=2,
                    help="score folds that train on at least this many sessions (eligible: >= 2, A.11.3)")
    ap.add_argument("--support", choices=("production", "regime", "any"), default="production",
                    help="the gating stratum: production (= regime, apply's support at the test session's regime; "
                         "default) or any (regime_ok forced: a diagnostic, never binding)")
    ap.add_argument("--strata", choices=("support", "ntrain"), default="support",
                    help="supported = stack_limits support on the training sample (default) or n_train >= 5 (A.10)")
    ap.add_argument("--families", default="soft.agent", help="comma-separated families the exit code covers")
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--rng-seed", type=int, default=20261008)
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    a = ap.parse_args(argv)
    a.families = tuple(x.strip() for x in a.families.split(",") if x.strip())
    if a.sims < 1 or not set(a.families) <= set(FAMILIES):
        sys.stderr.write(f"b1_backtest: --sims must be >= 1 and --families a subset of {','.join(FAMILIES)}\n")
        return 2
    try:
        out, leak = run(a)
    except (OSError, ValueError, KeyError, L.SeedError) as exc:
        sys.stderr.write(f"b1_backtest: {type(exc).__name__}: {exc}\n")
        return 2
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
    print(f"B1-T14 backtest: {len(out['folds'])} folds scored (>= {a.min_train_sessions} training sessions), gating "
          f"stratum {out['support']}, hyperparameters {out['hyper']}")
    for fam, res in out["families"].items():
        for ss in SETS:
            for stratum in STRATA:
                print(_fmt_stratum(fam, ss, stratum, res["strata"][ss][stratum]))
        i = res["informative"]
        print(f"  {fam:<11} informative {i['ok']} n {i['n']} m {i['m']} u {i['u']} q05 {i['q05']} failed "
              f"{i['failed'] or '-'}  eligible folds production {i['folds_production']} any {i['folds_any']}")
        print(f"  {fam:<11} power_2.5r {res['power_2.5r']} power_r/5 {res['power_r/5']} power_ok {res['power_ok']} "
              f"(B1_MIN_POWER {B1_MIN_POWER})" + (f"  blocked folds {res['blocked_folds']}" if res["blocked_folds"]
                                                  else ""))
        print(f"  {fam:<11} {res['verdict']}" + (f" ({res['reason']})" if res["reason"] else "")
              + f" {res['checks']}")
    if leak:
        print("  note: one hyperparameter set for every fold (it saw the test rows): optimistic; WP5 uses --hyper-dir")
    if out["support"] != "production":
        print("  note: any-regime gating is a calibration diagnostic, never promotion evidence (A.11.2)")
    print("ACCEPT" if out["accept"] else "REJECT")
    return 0 if out["accept"] else 1


if __name__ == "__main__":
    sys.exit(main())
