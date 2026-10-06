# /// script
# requires-python = ">=3.11"
# dependencies = ["scipy>=1.11", "numpy>=1.26"]
# ///
"""Re-derive every number quoted in COMPARE_eq.md §8 by two routes.

Route 1: exact binomial arithmetic with math.comb (no library tests).
Route 2: scipy.stats.binomtest / binom, plus a Monte-Carlo check of unconditional power.
Run: uv run --script derive_numbers.py
"""
from __future__ import annotations

import hashlib
import math

import numpy as np
from scipy import stats

SEED = 20261004


def p_two_sided_exact(k: int, n: int) -> float:
    """Route 1: two-sided sign-test p for k successes of n at p=0.5 (symmetric, so 2*tail, capped at 1)."""
    k = max(k, n - k)
    tail = sum(math.comb(n, j) for j in range(k, n + 1)) / 2**n
    return min(1.0, 2 * tail)


def k_crit(n: int, alpha: float) -> int | None:
    """Smallest k (>= n/2) with two-sided p <= alpha; None if unreachable."""
    for k in range(math.ceil(n / 2), n + 1):
        if p_two_sided_exact(k, n) <= alpha:
            return k
    return None


def k_crit_scipy(n: int, alpha: float) -> int | None:
    for k in range(math.ceil(n / 2), n + 1):
        if stats.binomtest(k, n, 0.5, alternative="two-sided").pvalue <= alpha + 1e-15:
            return k
    return None


def n_d_normal(pi: float, alpha: float, power: float) -> float:
    za = stats.norm.ppf(1 - alpha / 2)
    zb = stats.norm.ppf(power)
    return (za * 0.5 + zb * math.sqrt(pi * (1 - pi))) ** 2 / (pi - 0.5) ** 2


def power_conditional(n_d: int, pi: float, alpha: float) -> float:
    """Exact power of the two-sided sign test given n_d discordant items, in the favourable direction."""
    k = k_crit(n_d, alpha)
    if k is None:
        return 0.0
    return float(stats.binom.sf(k - 1, n_d, pi))


def power_unconditional(n_items: int, delta: float, pi: float, alpha: float) -> float:
    """Exact: D ~ Bin(n_items, delta) discordant items, then the sign test on D."""
    pmf = stats.binom.pmf(np.arange(n_items + 1), n_items, delta)
    return float(sum(pmf[d] * power_conditional(d, pi, alpha) for d in range(n_items + 1)))


def power_mc(n_items: int, delta: float, pi: float, alpha: float, reps: int, rng) -> float:
    d = rng.binomial(n_items, delta, size=reps)
    w = rng.binomial(d, pi)
    hits = 0
    for di, wi in zip(d, w):
        if di > 0 and stats.binomtest(int(wi), int(di), 0.5).pvalue <= alpha and wi > di - wi:
            hits += 1
    return hits / reps


def min_items(delta: float, pi: float, alpha: float, power: float = 0.8, start: int = 10) -> int:
    n = start
    while power_unconditional(n, delta, pi, alpha) < power:
        n += 1
    # power is not monotone in n for discrete tests: require it to stay >= power for the next 5 n
    while any(power_unconditional(n + j, delta, pi, alpha) < power for j in range(1, 6)):
        n += 1
        while power_unconditional(n, delta, pi, alpha) < power:
            n += 1
    return n


def seed_for(tag: str) -> int:
    return SEED ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)


def cp_upper(k: int, n: int, conf: float = 0.95) -> float:
    """Two-sided Clopper-Pearson upper limit."""
    if k == n:
        return 1.0
    return float(stats.beta.ppf(1 - (1 - conf) / 2, k + 1, n - k))


def main() -> None:
    print("== 1. Critical counts, exact two-sided sign test (route1 | route2) ==")
    alphas = {"0.05": 0.05, "0.025 (Holm 1st of 2)": 0.025, "0.0125 (Holm 1st of 4)": 0.0125,
              "0.05/6=0.00833 (Bonferroni/Holm 1st of 6)": 0.05 / 6}
    for name, a in alphas.items():
        row = []
        for n in (5, 6, 7, 8, 9, 10, 12, 15, 20, 25, 30, 40):
            k1, k2 = k_crit(n, a), k_crit_scipy(n, a)
            assert k1 == k2, (name, n, k1, k2)
            row.append(f"{n}:{'-' if k1 is None else k1}")
        print(f"alpha {name}: " + "  ".join(row))
    print("smallest n with any reachable result:")
    for name, a in alphas.items():
        n = 1
        while k_crit(n, a) is None:
            n += 1
        print(f"  alpha {name}: n={n} needs {k_crit(n, a)}/{n}, p={p_two_sided_exact(n, n):.5f}")
    print("planner claims:")
    for k, n, a in [(6, 6, .05), (9, 10, .05), (15, 20, .05), (21, 30, .05), (7, 7, .025),
                    (8, 8, .05 / 6), (10, 10, .05 / 6), (11, 12, .05 / 6), (17, 20, .05 / 6)]:
        p1 = p_two_sided_exact(k, n)
        p2 = stats.binomtest(k, n, 0.5).pvalue
        print(f"  {k}/{n}: p={p1:.5f} (scipy {p2:.5f}) <= {a:.5f}? {p1 <= a}; minimal k? {k_crit(n, a) == k}")

    print("\n== 2. Normal-approximation n_d (pi=0.75, power 0.8) and exact conditional power ==")
    for name, a in alphas.items():
        nd = n_d_normal(0.75, a, 0.8)
        nd_c = math.ceil(nd)
        # exact: smallest n_d with conditional power >= 0.8 that stays >= 0.8 afterwards
        n = 1
        while not all(power_conditional(n + j, 0.75, a) >= 0.8 for j in range(0, 6)):
            n += 1
        print(f"  alpha {name}: normal n_d={nd:.2f} -> {nd_c}; exact power at {nd_c} = "
              f"{power_conditional(nd_c, 0.75, a):.3f}; exact stable n_d = {n}")

    print("\n== 3. Items per class per contrast (pi=0.75, power 0.8), unconditional exact ==")
    for delta in (0.2, 0.3, 0.4):
        for name, a in alphas.items():
            nd = math.ceil(n_d_normal(0.75, a, 0.8))
            ni = min_items(delta, 0.75, a)
            print(f"  delta={delta} alpha {name}: n_d/delta = {nd}/{delta} = {math.ceil(nd / delta)}; "
                  f"exact unconditional min items = {ni} (power there {power_unconditional(ni, delta, 0.75, a):.3f})")

    print("\n== 3b. Monte-Carlo second route at the delta=0.3 exact minima (reps 20000) ==")
    rng = np.random.default_rng(seed_for("eq|derive|mc"))
    for name, a in alphas.items():
        ni = min_items(0.3, 0.75, a)
        print(f"  alpha {name}: n={ni}: exact {power_unconditional(ni, 0.3, 0.75, a):.3f}, "
              f"MC {power_mc(ni, 0.3, 0.75, a, 20000, rng):.3f}")

    print("\n== 4. Pilot reach: 10 items, delta 0.3, pi 0.75, alpha 0.05 ==")
    print(f"  unconditional power = {power_unconditional(10, 0.3, 0.75, 0.05):.4f}")
    print(f"  P(D>=6 | n=10, delta=0.3) = {stats.binom.sf(5, 10, 0.3):.4f}")

    print("\n== 5. Refutation bound: CP 95% upper limit of pi < 0.6 needs ==")
    for n in (10, 20, 30, 40, 50, 60):
        ks = [k for k in range(n + 1) if cp_upper(k, n) < 0.6]
        print(f"  n_d={n}: k <= {max(ks) if ks else '-'} (upper at that k = {cp_upper(max(ks), n):.3f})" if ks
              else f"  n_d={n}: unreachable")

    print("\n== 6. tau and kappa at small N ==")
    for N in (3, 5, 7, 9):
        print(f"  N={N}: kappa>=0.6 <=> top cluster >= {math.ceil(0.6 * N)}/{N}")

    print("\n== 7. Seeds (SEED ^ int(sha256(tag)[:8],16)) ==")
    for tag in ["eq|order", "eq|items", "eq|views", "eq|grader", "eq|ties",
                "eq|S*|P1", "eq|G|P1", "eq|E|P1", "eq|EG|P1", "eq|S*|P4", "eq|G|P4", "eq|E|P4", "eq|EG|P4",
                "eq|derive|mc"]:
        print(f"  {tag!r}: {seed_for(tag)}")


if __name__ == "__main__":
    main()
