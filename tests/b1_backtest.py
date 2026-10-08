#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
"""B1-T14 (docs/BAYES.md A.9): the rolling-origin calibration backtest of the Bayes limits, stdlib only.

Run (the verifier, WP5):  B1_REPO=<main checkout> uv run --no-cache --script tests/b1_backtest.py \
                              [--data DIR] [--hyper-ctx F --hyper-turns F | --hyper-dir D] [--out summary.json]

Rolling origin over the sessions of the rows (usage runs*.csv, read by stack_limits.read_rows of B1_REPO's hooks),
ordered by their first row: fold k tests on session k and trains on every earlier session; only folds that train on
at least --min-train-sessions sessions count (3.3 item 2: at least 3 such folds with at least 2 sessions). For each
family (soft.agent, hard.agent, turns) and type with test rows, the grid tier of stack_bayes_grid, conditional on
the hyperparameters (2.1 `hyper` shape, or the v2 `{"nuts": ...}` files with tau_new = tau_s), gives the posterior of
the type's location from the fold's training rows (censored per A.3) and the new-session predictive: T = its
(1 - r) quantile (hard.agent: max(q_.99, 2 x soft T), clamped [2M, 200M]); the deployed value = decide_bayes at
c = the value in force (the seed of the data's day, --seed-file: the prototype's approximation, A.10).

Scoring per family x stratum (supported: stack_limits.classify on the training sample, or --strata ntrain: at least
5 training rows, the frozen-fixture convention of A.10; sparse: not), for T, the
deployed value and c: an uncensored test row above the value is a hit; a censored row (a lower bound) above it is a
hit, below it unknown, so counts are intervals [lo, hi]. PIT: F(y) for an uncensored row, U(F(y), 1) for a censored
one (randomized), the NB discrete ones U(F(y - 1), F(y)); coverage90 = share of PITs in [0.05, 0.95]. The
session-clustered check simulates the test rows from the predictive with one shared new-session effect per fold
(--sims draws) and reports P(K >= lo) and P(K <= hi).

Accept a family when, on T in the supported stratum, P(K >= lo) >= 0.05, P(K <= hi) >= 0.05 and coverage90 is in
[0.8, 0.97], and in the sparse stratum hits(deployed) <= hits(current) (both ends of the intervals), with enough
folds. Exit 0 when every family of --families is accepted, 1 when one is not (or folds are too few), 2 on error.
Hyperparameters fitted on all rows (the default v2 files) include the test rows: the verdict is then optimistic and
is printed as such; WP5 passes fold-specific files (--hyper-dir D: D/fold<k>_ctx.json, D/fold<k>_turns.json).
"""
import argparse
import json
import math
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("B1_REPO") or os.path.dirname(HERE)
HOOKS = os.path.join(REPO, "dot-config", "dot-claude", "hooks")
sys.path.insert(0, HOOKS)
import stack_bayes_grid as G  # noqa: E402
import stack_limits as L  # noqa: E402

FIX = os.path.join(HERE, "fixtures", "bayes", "b1v2")
V2_OUT = os.path.join(REPO, "docs", "bayes", "b1v2", "out_v2")
FAMILIES = ("soft.agent", "hard.agent", "turns")
P_RESUME_V2 = 0.3238434163701068


# ---------------------------------------------------------------- inputs
def load_hyper_file(path, p_resume):
    """2.1 `hyper.<model>` shape, or the v2 prototype's {"nuts": {tau_t, tau_s, rho, types}} (tau_new = tau_s)."""
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    h = doc.get("nuts", doc)
    return {"tau_t": float(h["tau_t"]), "tau_new": float(h.get("tau_new", h.get("tau_s", 0.0))),
            "rho": float(h.get("rho", 0.0)), "p_resume": float(h.get("p_resume", p_resume)),
            "types": {t: {"mu": float(v["mu"]), "scale": float(v["scale"])} for t, v in h["types"].items()}}


def session_order(rows):
    first = {}
    for r in rows:
        first[r["session"]] = min(first.get(r["session"], r["ts"]), r["ts"])
    return sorted(first, key=lambda s: (first[s], s))


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

    def quantile(self, p):
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
        e = rnd.choices(self.etas, weights=self.w)[0]
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
    if cens:
        f = pred.cdf(y)
        return f + (1 - f) * rnd.random()
    if pred.fam == "turns":
        a, b = pred.cdf(y - 1), pred.cdf(y)
        return a + (b - a) * rnd.random()
    return pred.cdf(y)


def run(args):
    seed = L.load_seed(args.seed_file) if args.seed_file else L.load_seed()
    paths = [os.path.join(args.data, n) for n in ("runs.1.csv", "runs.csv", "runs2.1.csv", "runs2.csv",
                                                  "runs3.1.csv", "runs3.csv") if os.path.exists(os.path.join(args.data, n))]
    rows, _stats = L.read_rows(paths, models=L.agent_models(os.path.join(REPO, "dot-config", "dot-claude", "agents")))
    order = session_order(rows)
    by_sess = {}
    for r in rows:
        by_sess.setdefault(r["session"], []).append(r)
    folds = [k for k in range(1, len(order)) if k >= args.min_train_sessions]
    folds = folds[-args.folds:] if args.folds else folds
    rnd = random.Random(args.rng_seed)
    acc = {(f, s): {"T": [0, 0], "deployed": [0, 0], "current": [0, 0], "n": 0, "pits": [], "folds": [],
                    "types": 0} for f in FAMILIES for s in ("supported", "sparse")}
    leak = not args.hyper_dir
    for k in folds:
        test_s = order[k]
        train = [r for s in order[:k] for r in by_sess[s]]
        test = by_sess[test_s]
        pres = sum(1 for r in train if r["scope"] == "agent" and r["seg"] > 0) / max(
            1, sum(1 for r in train if r["scope"] == "agent"))
        hy = {}
        for fam_key, default in (("ctx", args.hyper_ctx), ("turns", args.hyper_turns)):
            path = os.path.join(args.hyper_dir, f"fold{k}_{fam_key}.json") if args.hyper_dir else default
            hy[fam_key] = load_hyper_file(path, pres)
        wh_train, wh_test = L.win_hits_of(train), L.win_hits_of(test)
        types = sorted({r["type"] for r in test if r["scope"] == "agent"})
        softT = {}
        for fam in FAMILIES:                                     # soft.agent first: hard.agent needs its T
            h = hy["turns" if fam == "turns" else "ctx"]
            per_stratum = {"supported": [], "sparse": []}
            for t in types:
                v = f"{fam}.{t}"
                if v not in seed["vars"] or t not in h["types"]:
                    continue
                tr_rows = [r for r in train if r["scope"] == "agent" and r["type"] == t]
                te = [(y, c) for y, c, _ in blists([r for r in test if r["scope"] == "agent" and r["type"] == t],
                                                   fam, seed, wh_test, t)]
                if not te:
                    continue
                tr = blists(tr_rows, fam, seed, wh_train, t)
                pred = Pred(fam, t, tr, h)
                r_ = L.RISK[fam]
                if fam == "hard.agent":
                    T, _ab = L.hard_agent_T(pred.quantile(0.99), softT.get(t))
                elif fam == "turns":
                    T = math.ceil(pred.quantile(1 - r_))
                else:
                    T = int(L.ceil2(pred.quantile(1 - r_)))
                    softT[t] = T
                spec = seed["vars"][v]
                ent = L._entry(tr_rows, fam, spec["kind"], 0, f"bt:{k}:{v}", {}) if tr_rows else None
                if ent:
                    ent["regime_ok"] = True
                    ent = L._valid_entry(ent, spec["unit"])
                status = L.classify(fam, ent, None)[0] if ent else None
                if args.strata == "ntrain":                      # the frozen-fixture convention (A.10, T4a)
                    stratum = "supported" if len(tr) >= 5 else "sparse"
                else:
                    stratum = "supported" if status == "supported" else "sparse"
                c = spec["seed"]
                deployed = c
                if ent:
                    blk = {"tier": "grid", "model": "backtest", "risk": r_, "T": T, "T_raw": T, "pi90": [T, T],
                           "qtab": pred.qtab(), "at_bound": False, "n": len(tr), "n_cens": sum(x[1] for x in tr),
                           "agents": ent["agents"], "sessions": ent["sessions"], "shrink": None, "status": "pooled",
                           "diag": {}}
                    st, _rec = L.decide_bayes(v, spec, L._var_state(c), blk, ent, None,
                                              softT.get(t) if fam == "hard.agent" else None, 1.0)
                    deployed = st["value"]
                per_stratum[stratum].append((pred, T, te))
                a = acc[(fam, stratum)]
                for key, val in (("T", T), ("deployed", deployed), ("current", c)):
                    lo, hi = hits(te, val)
                    a[key][0] += lo
                    a[key][1] += hi
                a["n"] += len(te)
                a["types"] += 1
                a["pits"] += [pit(pred, y, cc, rnd) for y, cc in te]
            for stratum, items in per_stratum.items():
                if items:                                        # the fold's simulated K (one session effect)
                    ks = []
                    for _ in range(args.sims):
                        w = rnd.gauss(0, 1)
                        ks.append(sum(1 for pred, T, te in items for _y in te if pred.draw(rnd, w) > T))
                    acc[(fam, stratum)]["folds"].append(ks)
    out = {"repo": REPO, "data": args.data, "folds": [order[k] for k in folds], "min_train_sessions": args.min_train_sessions,
           "strata": args.strata,
           "hyper": "fold-specific" if args.hyper_dir else "single (includes the test rows: optimistic)", "families": {}}
    enough = len(folds) >= 3 and args.min_train_sessions >= 2
    ok_all = enough
    for fam in FAMILIES:
        res = {}
        for stratum in ("supported", "sparse"):
            a = acc[(fam, stratum)]
            if not a["n"]:
                res[stratum] = {"n": 0}
                continue
            tot = [sum(x) for x in zip(*a["folds"])] if a["folds"] else []
            lo, hi = a["T"]
            pits = a["pits"]
            cov = sum(1 for u in pits if 0.05 <= u <= 0.95) / len(pits)
            res[stratum] = {"n": a["n"], "types": a["types"], "hits_T": a["T"], "hits_deployed": a["deployed"],
                            "hits_current": a["current"], "coverage90": round(cov, 4),
                            "pit_mean": round(sum(pits) / len(pits), 4),
                            "p_ge_lo": round(sum(1 for x in tot if x >= lo) / len(tot), 4) if tot else None,
                            "p_le_hi": round(sum(1 for x in tot if x <= hi) / len(tot), 4) if tot else None}
        sup, spa = res["supported"], res["sparse"]
        checks = {}
        if sup.get("n"):
            checks["clustered"] = sup["p_ge_lo"] >= 0.05 and sup["p_le_hi"] >= 0.05
            checks["coverage90"] = 0.8 <= sup["coverage90"] <= 0.97
        else:
            checks["supported_rows"] = False
        if spa.get("n"):
            checks["sparse_deployed_le_current"] = (spa["hits_deployed"][0] <= spa["hits_current"][0]
                                                    and spa["hits_deployed"][1] <= spa["hits_current"][1])
        checks["folds"] = enough
        accept = all(checks.values())
        res["checks"], res["accept"] = checks, accept
        out["families"][fam] = res
        if fam in args.families:
            ok_all = ok_all and accept
    out["accept"] = ok_all
    return out, leak


def main(argv=None):
    ap = argparse.ArgumentParser(description="B1-T14 rolling-origin backtest (docs/BAYES.md A.9)")
    ap.add_argument("--data", default=FIX, help="directory with runs*.csv (default: the frozen fixture)")
    ap.add_argument("--seed-file", default=None, help="limits seed (the values in force); default: B1_REPO's")
    ap.add_argument("--hyper-ctx", default=os.path.join(V2_OUT, "hyper_ctx.json"))
    ap.add_argument("--hyper-turns", default=os.path.join(V2_OUT, "hyper_turns.json"))
    ap.add_argument("--hyper-dir", default=None, help="fold-specific hyperparameters fold<k>_{ctx,turns}.json")
    ap.add_argument("--folds", type=int, default=0, help="use the last N eligible folds (0: all)")
    ap.add_argument("--min-train-sessions", type=int, default=2)
    ap.add_argument("--strata", choices=("support", "ntrain"), default="support",
                    help="supported = stack_limits support on the training sample (default) or n_train >= 5 (A.10)")
    ap.add_argument("--families", default="soft.agent", help="comma-separated families the exit code covers")
    ap.add_argument("--sims", type=int, default=2000)
    ap.add_argument("--rng-seed", type=int, default=20261008)
    ap.add_argument("--out", default=None, help="write the summary JSON here")
    a = ap.parse_args(argv)
    a.families = tuple(x.strip() for x in a.families.split(",") if x.strip())
    try:
        out, leak = run(a)
    except (OSError, ValueError, KeyError, L.SeedError) as exc:
        sys.stderr.write(f"b1_backtest: {type(exc).__name__}: {exc}\n")
        return 2
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, indent=1, sort_keys=True)
    print(f"B1-T14 backtest: {len(out['folds'])} folds (>= {a.min_train_sessions} training sessions), hyperparameters "
          f"{out['hyper']}")
    for fam, res in out["families"].items():
        for stratum in ("supported", "sparse"):
            r = res[stratum]
            if not r.get("n"):
                print(f"  {fam:<11} {stratum:<9} no test rows")
                continue
            print(f"  {fam:<11} {stratum:<9} n {r['n']:<4} hits T {r['hits_T']} deployed {r['hits_deployed']} "
                  f"current {r['hits_current']}  cov90 {r['coverage90']}  PIT mean {r['pit_mean']}  "
                  f"P(K>=lo) {r['p_ge_lo']} P(K<=hi) {r['p_le_hi']}")
        print(f"  {fam:<11} accept {res['accept']} {res['checks']}")
    if leak:
        print("  note: one hyperparameter set for every fold (it saw the test rows): optimistic; WP5 uses --hyper-dir")
    print("ACCEPT" if out["accept"] else "REJECT")
    return 0 if out["accept"] else 1


if __name__ == "__main__":
    sys.exit(main())
