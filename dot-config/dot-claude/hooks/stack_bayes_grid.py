"""stack_bayes_grid.py - the stdlib (Python 3.9, no third-party import) grid tier of the learned limits.

From docs/bayes/b1v2/bayes_grid.py (docs/BAYES.md section A.8 item 1). stack_limits.propose() runs it
in-process (detached, /usr/bin/python3): for one variable of one agent type, the exact grid posterior
of the type's location parameter given the hierarchical hyperparameters of a gated sampler fit
(stack_limits.load_hyper: there is no moment-hyperparameter path), with right-censored observations,
then the posterior-predictive quantile at 1 - risk, a 90% interval of that quantile, and the
predicted cap-hit probability at any value c. Soft families only.

Likelihoods (design.md section 3):
  ctx-like (tokens, seconds)   log y ~ Normal(eta + rho*resume, sigma)           (log-normal)
  count-like (turns, tools)    y - 1 ~ NegBin(mu = exp(eta + rho*resume), alpha) (shifted NB2, y >= 1)
A censored row (true value >= observed c) contributes log P(Y >= c). A new run's predictive mixes the
grid posterior of eta, a new session effect w ~ N(0, tau_s) (analytic for the log-normal, 7-node
Gauss-Hermite for the NB) and resume ~ Bernoulli(p_resume).

Cost: the uncensored part of the log-likelihood is O(1) per grid point (sufficient statistics), the
censored part O(n_censored); a 241-point grid over 55 types x 400 rows runs in well under a second.
"""
import math

GRID = 241
SPAN = 7.0
Z90 = 1.6448536269514722
# probabilists' Gauss-Hermite nodes/weights for E[f(W)], W ~ N(0, 1) (7 nodes, exact to degree 13)
GH_X = (-3.750439717725742, -2.366759410734541, -1.154405394739968, 0.0,
        1.154405394739968, 2.366759410734541, 3.750439717725742)
GH_W = (0.0005482688559722184, 0.030757123967586, 0.2401231786050126, 0.4571428571428571,
        0.2401231786050126, 0.030757123967586, 0.0005482688559722184)


# ---------------------------------------------------------------- normal helpers
def ncdf(z):
    return 0.5 * math.erfc(-z / math.sqrt(2.0))


def log_nsf(z):
    """log P(Z > z), stable in both tails."""
    if z < 5.0:
        return math.log(max(0.5 * math.erfc(z / math.sqrt(2.0)), 1e-300))
    z2 = z * z
    return -0.5 * z2 - math.log(z) - 0.5 * math.log(2 * math.pi) + math.log1p(-1 / z2 + 3 / (z2 * z2))


def nppf(p):
    """Inverse standard normal CDF (Acklam's rational approximation + one Halley step)."""
    if not 0.0 < p < 1.0:
        raise ValueError("p")
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02,
         -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01,
         -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00,
         4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    pl = 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    elif p <= 1 - pl:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
            (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    e = ncdf(x) - p
    u = e * math.sqrt(2 * math.pi) * math.exp(x * x / 2)
    return x - u / (1 + x * u / 2)


def _normalize(logw):
    m = max(logw)
    w = [math.exp(v - m) for v in logw]
    s = sum(w)
    return [v / s for v in w]


def wquantile(vals, w, p):
    """Weighted quantile (step function) of values with weights summing to 1."""
    pairs = sorted(zip(vals, w))
    acc = 0.0
    for v, wi in pairs:
        acc += wi
        if acc >= p:
            return v
    return pairs[-1][0]


# ---------------------------------------------------------------- log-normal tier
def lognormal_post(obs, cens, prior_mu, prior_sd, sigma, offs_obs=None, offs_cens=None, grid=GRID):
    """Grid posterior of eta. obs/cens: log values (cens: log of the observed lower bound); offs_*: the
    per-row known offset (rho * resume). Prior eta ~ N(prior_mu, prior_sd). Returns (etas, weights, info)."""
    oo = offs_obs or [0.0] * len(obs)
    oc = offs_cens or [0.0] * len(cens)
    r = [y - o for y, o in zip(obs, oo)]
    n = len(r)
    mean = sum(r) / n if n else 0.0
    ss = sum((v - mean) ** 2 for v in r)
    # grid: the prior's +-SPAN sd, widened to cover the data's likelihood mode
    lo, hi = prior_mu - SPAN * prior_sd, prior_mu + SPAN * prior_sd
    if n:
        se = sigma / math.sqrt(n)
        lo, hi = min(lo, mean - SPAN * se), max(hi, mean + SPAN * se)
    if cens:
        hi = max(hi, max(c - o for c, o in zip(cens, oc)) + 3 * sigma)
    etas = [lo + (hi - lo) * i / (grid - 1) for i in range(grid)]
    logw = []
    for e in etas:
        lp = -0.5 * ((e - prior_mu) / prior_sd) ** 2
        if n:
            lp += -(ss + n * (mean - e) ** 2) / (2 * sigma * sigma)
        for c, o in zip(cens, oc):
            lp += log_nsf((c - o - e) / sigma)
        logw.append(lp)
    w = _normalize(logw)
    edge = w[0] + w[-1]
    return etas, w, {"edge_mass": edge, "n_obs": n, "n_cens": len(cens)}


def lognormal_pred_cdf(etas, w, x_log, sigma, tau_s=0.0, rho=0.0, p_resume=0.0):
    s = math.sqrt(sigma * sigma + tau_s * tau_s)
    tot = 0.0
    for e, wi in zip(etas, w):
        if wi < 1e-14:
            continue
        f0 = ncdf((x_log - e) / s)
        f1 = ncdf((x_log - e - rho) / s) if p_resume else 0.0
        tot += wi * ((1 - p_resume) * f0 + p_resume * f1)
    return tot


def lognormal_quantile(etas, w, p, sigma, tau_s=0.0, rho=0.0, p_resume=0.0):
    """Predictive quantile (log scale) of a new run, and the 90% interval of the per-eta conditional
    quantile (log scale)."""
    lo, hi = etas[0] - 12 * sigma - abs(rho), etas[-1] + 12 * sigma + abs(rho)
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if lognormal_pred_cdf(etas, w, mid, sigma, tau_s, rho, p_resume) < p:
            lo = mid
        else:
            hi = mid
    q = 0.5 * (lo + hi)
    s = math.sqrt(sigma * sigma + tau_s * tau_s)
    zc = nppf(p)
    # conditional quantile per eta (resume mixture approximated by the mean offset: interval only)
    cq = [e + p_resume * rho + zc * s for e in etas]
    return q, (wquantile(cq, w, 0.05), wquantile(cq, w, 0.95))


# ---------------------------------------------------------------- negative-binomial tier
def _nb_logpmf_terms(alpha, mu):
    return math.log(alpha / (alpha + mu)), math.log(mu / (alpha + mu))


def nb_log_sf(k, mu, alpha):
    """log P(Y >= k) for Y ~ NB2(mu, alpha), k >= 0 integer (iterative pmf; k <= 1e4)."""
    if k <= 0:
        return 0.0
    la, lm = _nb_logpmf_terms(alpha, mu)
    p = math.exp(alpha * la)
    cdf = p
    ratio = math.exp(lm)
    for j in range(k - 1):
        p *= (j + alpha) / (j + 1) * ratio
        cdf += p
    return math.log(max(1.0 - cdf, 1e-300)) if cdf < 1 - 1e-12 else _nb_log_sf_tail(k, mu, alpha)


def _nb_log_sf_tail(k, mu, alpha):
    """Upper tail summed directly (when 1 - cdf underflows): sum_{j >= k} pmf(j) in log space."""
    la, lm = _nb_logpmf_terms(alpha, mu)
    lp = math.lgamma(k + alpha) - math.lgamma(alpha) - math.lgamma(k + 1) + alpha * la + k * lm
    tot, term, j = 1.0, 1.0, k
    for _ in range(100000):
        term *= (j + alpha) / (j + 1) * math.exp(lm)
        tot += term
        j += 1
        if term < 1e-16 * tot:
            break
    return lp + math.log(tot)


def nb_post(obs, cens, prior_mu, prior_sd, alpha, offs_obs=None, offs_cens=None, grid=161):
    """Grid posterior of eta = log mean of (y - 1). obs: counts y >= 1; cens: lower bounds c (true y >= c)."""
    oo = offs_obs or [0.0] * len(obs)
    oc = offs_cens or [0.0] * len(cens)
    ys = [y - 1 for y in obs]
    n = len(ys)
    lo, hi = prior_mu - SPAN * prior_sd, prior_mu + SPAN * prior_sd
    if n:
        m = math.log(max(sum(ys) / n, 0.05))
        lo, hi = min(lo, m - 3.0), max(hi, m + 3.0)
    if cens:
        hi = max(hi, math.log(max(cens)) + 2.0)
    etas = [lo + (hi - lo) * i / (grid - 1) for i in range(grid)]
    logw = []
    for e in etas:
        lp = -0.5 * ((e - prior_mu) / prior_sd) ** 2
        for y, o in zip(ys, oo):            # offsets differ per row: O(n), still cheap
            mu = math.exp(e + o)
            la, lm = _nb_logpmf_terms(alpha, mu)
            lp += alpha * la + y * lm
        for c, o in zip(cens, oc):
            lp += nb_log_sf(int(c) - 1, math.exp(e + o), alpha)
        logw.append(lp)
    w = _normalize(logw)
    return etas, w, {"edge_mass": w[0] + w[-1], "n_obs": n, "n_cens": len(cens)}


def _nb_cdf_upto(K, mu, alpha):
    """[P(Y <= k) for k in 0..K]."""
    la, lm = _nb_logpmf_terms(alpha, mu)
    p = math.exp(alpha * la)
    ratio = math.exp(lm)
    out, cdf = [], 0.0
    for j in range(K + 1):
        cdf += p
        out.append(min(cdf, 1.0))
        p *= (j + alpha) / (j + 1) * ratio
    return out


def nb_predictive(etas, w, alpha, tau_s=0.0, rho=0.0, p_resume=0.0, kmax=4000, wmin=1e-9):
    """Predictive cdf of y - 1 for a new run (mixture over the eta grid, a new session effect by
    Gauss-Hermite and resume), plus the per-eta conditional cdfs for the quantile's interval."""
    keep = [(e, wi) for e, wi in zip(etas, w) if wi >= wmin]
    s = sum(wi for _, wi in keep)
    mix = [0.0] * (kmax + 1)
    conds = []
    for e, wi in keep:
        wi /= s
        cond = [0.0] * (kmax + 1)
        for rr, pr in ((0.0, 1 - p_resume), (rho, p_resume)):
            if pr <= 0:
                continue
            for gx, gw in zip(GH_X, GH_W):
                cd = _nb_cdf_upto(kmax, math.exp(e + rr + tau_s * gx), alpha)
                f = pr * gw
                for k in range(kmax + 1):
                    cond[k] += f * cd[k]
        for k in range(kmax + 1):
            mix[k] += wi * cond[k]
        conds.append((wi, cond))
    return {"mix": mix, "conds": conds, "kmax": kmax}


def nb_quantile_from(pred, p):
    """(smallest y with predictive P(Y <= y) >= p, 90% interval of the per-eta conditional quantile)."""
    km = pred["kmax"]
    q = 1 + next((k for k in range(km + 1) if pred["mix"][k] >= p), km)
    cq = [1 + next((k for k in range(km + 1) if c[k] >= p), km) for _, c in pred["conds"]]
    cw = [wi for wi, _ in pred["conds"]]
    return q, (wquantile(cq, cw, 0.05), wquantile(cq, cw, 0.95))


def nb_quantile(etas, w, p, alpha, tau_s=0.0, rho=0.0, p_resume=0.0, kmax=4000):
    pred = nb_predictive(etas, w, alpha, tau_s, rho, p_resume, kmax)
    q, ci = nb_quantile_from(pred, p)
    return q, ci, pred["mix"]


def nb_p_hit(mix, c):
    """Predicted P(Y > c) for y = 1 + NB from the mixture cdf list (cdf of y - 1)."""
    k = int(c) - 1
    if k < 0:
        return 1.0
    if k >= len(mix):
        return 0.0
    return max(0.0, 1.0 - mix[k])


# ---------------------------------------------------------------- seed-anchored scopes, fixer
def anchor_mu(seed_value, risk, sigma, prior_sd):
    """Prior mean of eta (log scale) whose prior-predictive (1 - risk) quantile equals seed_value:
    with no data the learned value is the seed (seed-anchored prior for single-variable scopes)."""
    return math.log(seed_value) - nppf(1 - risk) * math.sqrt(sigma * sigma + prior_sd * prior_sd)


def nig_lognormal(xs, mu0, k0=1.0, a0=2.0, b0=2.0, draws=20000, seed=0):
    """Normal-Inverse-Gamma conjugate posterior on log values (stdlib): (posterior median of the
    log-normal median exp(mu), 2.5 %, 97.5 % of exp(mu) by seeded Monte Carlo, n)."""
    import random
    n = len(xs)
    if n == 0:
        return None
    m = sum(xs) / n
    ss = sum((x - m) ** 2 for x in xs)
    kn = k0 + n
    mun = (k0 * mu0 + n * m) / kn
    an = a0 + n / 2.0
    bn = b0 + 0.5 * ss + k0 * n * (m - mu0) ** 2 / (2 * kn)
    rnd = random.Random(seed)
    mus = sorted(rnd.gauss(mun, math.sqrt(1.0 / rnd.gammavariate(an, 1.0 / bn) / kn)) for _ in range(draws))
    q = lambda p: mus[min(int(p * draws), draws - 1)]  # noqa: E731
    return math.exp(mun), math.exp(q(0.025)), math.exp(q(0.975)), n


if __name__ == "__main__":       # self-check: grid NB quantile vs an analytic NB with a sharp prior
    etas, w, _ = nb_post([], [], math.log(9.0), 1e-4, 2.0)
    q, ci, mix = nb_quantile(etas, w, 0.95, 2.0, kmax=200)
    # NB2(mu=9, alpha=2): q95 of y-1 found by direct summation
    cd = _nb_cdf_upto(200, 9.0, 2.0)
    q_ref = 1 + next(k for k in range(201) if cd[k] >= 0.95)
    assert q == q_ref, (q, q_ref)
    e2, w2, _ = lognormal_post([], [], 0.0, 1e-4, 1.0)
    lq, _ = lognormal_quantile(e2, w2, 0.95, 1.0)
    assert abs(lq - Z90) < 1e-3, lq
    assert abs(nppf(0.995) - 2.5758293035489) < 1e-9
    print("bayes_grid self-check ok", q, round(lq, 4))
