"""PF item families: Lean 4 statement, reference proof, planted-gap sketch, gap refutation.

Every candidate is a dict with keys:
  family, key, stmt (closed Prop, Lean), ref (tactic block proving stmt, indented 2),
  gap_lean (closed Prop: the sketch's false step, concrete), gap_refute (tactic block proving ¬gap_lean),
  wrong_tac (tactic a gap-following proof would use to assert gap_lean), steps (list[str]), gap_step (index).
No randomness: parameters are explicit lists or deterministic searches.
"""
from __future__ import annotations

from fractions import Fraction
from math import comb, factorial, gcd, isqrt

# ---------- formatting helpers ----------

def lit(z: int) -> str:
    """Integer literal usable as a factor or base (negatives parenthesised)."""
    return f"({z})" if z < 0 else str(z)


def terms(ts: list[tuple[int, str]]) -> str:
    """Render sum of coef*monomial with clean signs. monomial '' = constant."""
    out = []
    for c, m in ts:
        if c == 0:
            continue
        a = abs(c)
        if m == "":
            body = str(a)
        elif a == 1:
            body = m
        else:
            body = f"{a} * {m}"
        if not out:
            out.append(body if c > 0 else f"-{body}")
        else:
            out.append(("+ " if c > 0 else "- ") + body)
    return " ".join(out) if out else "0"


def fr(q: Fraction) -> str:
    return str(q.numerator) if q.denominator == 1 else f"{q.numerator}/{q.denominator}"


def cand(family, key, stmt, ref, gap_lean, gap_refute, wrong_tac, steps, gap_step):
    return dict(family=family, key=key, stmt=stmt, ref=ref, gap_lean=gap_lean, gap_refute=gap_refute,
                wrong_tac=wrong_tac, steps=steps, gap_step=gap_step)


REFUTE_AT = "intro h\n  have := h {pt}\n  norm_num at this"

# ---------- A: second-order linear recurrence ----------

def fam_rec2():
    params = [(2, 3, 1, 1), (3, -1, 2, -1), (2, -3, 1, 2), (4, 1, 1, -2), (3, 5, -1, 2), (-2, 5, 3, 1),
              (1, -4, 2, 1), (2, 5, 1, -3), (3, -2, -2, 5), (5, -3, 1, 1), (4, -2, 3, -1), (6, 1, -1, 4),
              (3, 4, 2, -3), (-3, 4, 1, 2)]
    out = []
    for r, s, al, be in params:
        P, Q = r + s, r * s
        A, B = al + be, al * r + be * s
        def closed(nx):
            return terms([(al, f"{lit(r)} ^ {nx}"), (be, f"{lit(s)} ^ {nx}")])
        rec = terms([(P, "f (n + 1)"), (-Q, "f n")])
        stmt = (f"∀ f : ℕ → ℤ, f 0 = {A} → f 1 = {B} → (∀ n, f (n + 2) = {rec}) → "
                f"∀ n, f n = {closed('n')}")
        ref = (f"  intro f h0 h1 hrec\n"
               f"  have key : ∀ n, f n = {closed('n')} ∧ f (n + 1) = {closed('(n + 1)')} := by\n"
               f"    intro n\n"
               f"    induction n with\n"
               f"    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩\n"
               f"    | succ k ih =>\n"
               f"      refine ⟨ih.2, ?_⟩\n"
               f"      rw [hrec, ih.2, ih.1]\n"
               f"      ring\n"
               f"  exact fun n => (key n).1")
        wrongval = al * (s - r)
        gap_lean = f"({B} : ℤ) - {lit(s)} * {lit(A)} = {wrongval}"
        steps = [
            f"The characteristic polynomial t^2 - ({P})t + ({Q}) factors as (t - ({r}))(t - ({s})), with roots {r} and {s}.",
            f"Let g n = f (n+1) - ({r})·f n. The recurrence gives g (n+1) = ({s})·g n, so g n = ({s})^n·g 0 = ({s})^n·({B} - ({r})·{A}) = {be * (s - r)}·({s})^n.",
            f"Symmetrically, h n = f (n+1) - ({s})·f n satisfies h (n+1) = ({r})·h n, and h 0 = {B} - ({s})·{A} = {wrongval}; hence f (n+1) - ({s})·f n = {wrongval}·({r})^n.",
            f"Subtracting the two relations eliminates f (n+1); dividing by ({s}) - ({r}) gives f n = ({al})·({r})^n + ({be})·({s})^n.",
            f"Check: ({al}) + ({be}) = {A} = f 0 and ({al})·({r}) + ({be})·({s}) = {B} = f 1.",
        ]
        out.append(cand("rec2", f"rec2_{r}_{s}_{al}_{be}", stmt, ref, gap_lean, "  norm_num", "norm_num", steps, 2))
    return out

# ---------- B: power sums from a+b, ab ----------

def waring(k):
    """a^k+b^k = sum_j coef_j * e1^(k-2j) * e2^j."""
    res = []
    for j in range(k // 2 + 1):
        c = Fraction((-1) ** j * k, k - j) * comb(k - j, j)
        assert c.denominator == 1
        res.append((int(c), k - 2 * j, j))
    return res


def mono(i, j, e1, e2):
    parts = []
    if i:
        parts.append(e1 if i == 1 else f"{e1} ^ {i}")
    if j:
        parts.append(e2 if j == 1 else f"{e2} ^ {j}")
    return " * ".join(parts)


def fam_powsum():
    params = [(5, 3, 4), (5, 3, 3), (4, 1, 5), (3, -2, 4), (6, 4, 5), (2, -5, 3), (7, 5, 4), (1, -3, 6),
              (4, 2, 6), (3, 1, 7), (5, -1, 5), (2, -1, 7), (6, 7, 3), (3, 2, 6)]
    out = []
    for S, P, k in params:
        w = waring(k)
        val = sum(c * S ** i * P ** j for c, i, j in w)
        correct = terms([(c, mono(i, j, "(a + b)", "(a * b)")) for c, i, j in w])
        wrong_w = list(w)
        c, i, j = wrong_w[-1]
        wrong_w[-1] = (c + (1 if c > 0 else -1), i, j)
        wrong_ab = terms([(c2, mono(i2, j2, "(a + b)", "(a * b)")) for c2, i2, j2 in wrong_w])
        wrong_sp = terms([(c2, mono(i2, j2, "s", "p")) for c2, i2, j2 in wrong_w])
        # check the wrong identity fails at a=b=1
        diff = sum(c2 * 2 ** i2 for c2, i2, j2 in wrong_w) - 2
        assert diff != 0
        stmt = f"∀ a b : ℝ, a + b = {S} → a * b = {P} → a ^ {k} + b ^ {k} = {val}"
        ref = (f"  intro a b h1 h2\n"
               f"  have e : a ^ {k} + b ^ {k} = {correct} := by ring\n"
               f"  rw [e, h1, h2]\n"
               f"  norm_num")
        gap_lean = f"∀ a b : ℝ, a ^ {k} + b ^ {k} = {wrong_ab}"
        steps = [
            f"Put s = a + b = {S} and p = ab = {P}.",
            "The power sums t_j = a^j + b^j satisfy t_j = s·t_(j-1) - p·t_(j-2), with t_0 = 2 and t_1 = s.",
            f"Unrolling the recursion, a^{k} + b^{k} = {wrong_sp} identically in a, b.",
            f"Substituting s = {S} and p = {P} gives a^{k} + b^{k} = {val}.",
        ]
        out.append(cand("powsum", f"powsum_{S}_{P}_{k}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="1 1"), "intro a b; ring", steps, 2))
    return out

# ---------- C: gcd of two linear forms ----------

def fam_gcdlin():
    pairs = [(21, 14), (12, 8), (15, 10), (9, 6), (10, 4), (14, 6), (8, 5), (7, 3), (11, 4), (13, 5),
             (18, 12), (20, 15), (16, 10), (25, 15)]
    out = []
    for a, c in pairs:
        g = gcd(a, c)
        u, v = c // g, a // g
        found = None
        for b in range(2, 10):
            for d in range(1, 10):
                if abs(v * d - u * b) == 1 and c * b - a * d != 1 and gcd(b, d) == 1:
                    found = (b, d)
                    break
            if found:
                break
        b, d = found
        if v * d - u * b == 1:
            comb_txt = f"{v} * ({c} * n + {d}) - {u} * ({a} * n + {b})"
            dv = f"Nat.dvd_sub (Dvd.dvd.mul_left h2 {v}) (Dvd.dvd.mul_left h1 {u})"
        else:
            comb_txt = f"{u} * ({a} * n + {b}) - {v} * ({c} * n + {d})"
            dv = f"Nat.dvd_sub (Dvd.dvd.mul_left h1 {u}) (Dvd.dvd.mul_left h2 {v})"
        stmt = f"∀ n : ℕ, Nat.gcd ({a} * n + {b}) ({c} * n + {d}) = 1"
        ref = (f"  intro n\n"
               f"  have h1 := Nat.gcd_dvd_left ({a} * n + {b}) ({c} * n + {d})\n"
               f"  have h2 := Nat.gcd_dvd_right ({a} * n + {b}) ({c} * n + {d})\n"
               f"  have h3 : Nat.gcd ({a} * n + {b}) ({c} * n + {d}) ∣ {comb_txt} := {dv}\n"
               f"  have e : {comb_txt} = 1 := by omega\n"
               f"  rw [e] at h3\n"
               f"  exact Nat.dvd_one.mp h3")
        gap_lean = f"∀ n : ℤ, {c} * ({a} * n + {b}) - {a} * ({c} * n + {d}) = 1"
        steps = [
            f"Let g = gcd({a}n + {b}, {c}n + {d}). Then g divides every integer combination x·({a}n + {b}) + y·({c}n + {d}).",
            f"Take x = {c} and y = -{a}: the terms in n cancel and {c}·({a}n + {b}) - {a}·({c}n + {d}) = 1.",
            "Hence g divides 1, so g = 1 for every natural number n.",
            "No case analysis on n (parity, residues) is needed.",
        ]
        out.append(cand("gcdlin", f"gcdlin_{a}_{b}_{c}_{d}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro n; ring", steps, 1))
    return out

# ---------- D: Diophantine non-solvability by a congruence ----------

def powers_mod(deg, m):
    return sorted({pow(x, deg, m) for x in range(m)})


def solvable_mod(a, b, deg, c, m):
    R = [pow(x, deg, m) for x in range(m)]
    return any((a * u + b * v - c) % m == 0 for u in R for v in R)


def fam_dioph():
    forms = [(1, 1, 2), (1, 2, 2), (1, 3, 2), (2, 3, 2), (1, -3, 2), (3, -5, 2), (1, 5, 2), (1, -7, 2),
             (1, 1, 3), (1, 2, 3), (2, -5, 3), (1, 1, 4), (1, 3, 4), (2, 5, 4), (1, -2, 2), (5, 7, 2)]
    out = []
    for a, b, deg in forms:
        chosen = None
        for c in list(range(3, 60)):
            mins = [m for m in range(2, 17) if not solvable_mod(a, b, deg, c, m)]
            if not mins:
                continue
            m = mins[0]
            if m < 5:
                continue
            if a > 0 and b > 0 and c < a + b:
                continue
            wrong = [mp for mp in (4, 3, 8, 5, 9, 7) if mp != m and solvable_mod(a, b, deg, c, mp)]
            if not wrong:
                continue
            chosen = (c, m, wrong[0])
            break
        if not chosen:
            continue
        c, m, mw = chosen
        lhs = terms([(a, f"x ^ {deg}"), (b, f"y ^ {deg}")])
        stmt = f"∀ x y : ℤ, {lhs} ≠ {c}"
        ref = (f"  intro x y h\n"
               f"  have h' := congrArg (fun z : ℤ => (z : ZMod {m})) h\n"
               f"  push_cast at h'\n"
               f"  generalize (x : ZMod {m}) = u at h'\n"
               f"  generalize (y : ZMod {m}) = v at h'\n"
               f"  revert u v\n"
               f"  decide")
        glhs = terms([(a, f"u ^ {deg}"), (b, f"v ^ {deg}")])
        gap_lean = f"∀ u v : ZMod {mw}, {glhs} ≠ {c}"
        word = {2: "squares", 3: "cubes", 4: "fourth powers"}[deg]
        R = powers_mod(deg, mw)
        steps = [
            f"Suppose {lhs.replace(' ^ ', '^').replace(' * ', '')} = {c} for some integers x, y.",
            f"A congruence obstruction suffices: reduce the equation modulo {mw}.",
            f"The {word} modulo {mw} are {{{', '.join(map(str, R))}}}, and no choice of u, v among them gives {a}·u + ({b})·v ≡ {c} (mod {mw}).",
            f"So the equation has no solution modulo {mw}, hence no integer solution.",
        ]
        out.append(cand("dioph", f"dioph_{a}_{b}_{deg}_{c}", stmt, ref, gap_lean, "  decide", "decide", steps, 2))
    return out

# ---------- E: m | n^k - n^j for all integers ----------

def primes_upto(n):
    return [p for p in range(2, n + 1) if all(p % q for q in range(2, isqrt(p) + 1))]


def fam_fermat():
    out = []
    for d in (2, 4, 6, 8, 10, 12):
        for j in (1, 2, 3):
            k = j + d
            ps = [p for p in primes_upto(d + 1) if d % (p - 1) == 0]
            m = 1
            for p in ps:
                m *= p
            if m > 500 and j > 1:
                continue
            pmax = max(ps)
            nj = "n" if j == 1 else f"n ^ {j}"
            stmt = f"∀ n : ℤ, ({m} : ℤ) ∣ n ^ {k} - {nj}"
            ref = (f"  intro n\n"
                   f"  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ {k} - {nj}) {m}).mp\n"
                   f"  push_cast\n"
                   f"  generalize (n : ZMod {m}) = u\n"
                   f"  revert u\n"
                   f"  decide +kernel")
            gap_lean = f"∀ n : ℤ, ({pmax} : ℤ) ∣ n ^ {pmax - 1} - 1"
            steps = [
                f"{m} = {'·'.join(map(str, ps))} is a product of distinct primes, so it suffices that each such prime p divides n^{k} - n^{j}.",
                f"Factor n^{k} - n^{j} = n^{j}·(n^{d} - 1); for each listed prime p, p - 1 divides {d}.",
                f"By Fermat's little theorem, n^(p-1) ≡ 1 (mod p) for every integer n; hence n^{d} ≡ 1 (mod p) and p divides n^{d} - 1.",
                "Distinct primes are pairwise coprime, so their product divides n^k - n^j.",
            ]
            out.append(cand("fermat", f"fermat_{k}_{j}", stmt, ref, gap_lean,
                            "  " + REFUTE_AT.format(pt="0"), "intro n; omega", steps, 2))
    return out

# ---------- F: eventually-exponential inequalities ----------

def min_threshold(pred, upto=400):
    N = None
    for n in range(upto, -1, -1):
        if not pred(n):
            N = n + 1
            break
    return 0 if N is None else N


def fam_expind():
    out = []
    for c, K in [(2, 2), (2, 3), (2, 4), (3, 3), (3, 4), (3, 5), (2, 5), (4, 5), (3, 6), (5, 6), (4, 6)]:
        N = min_threshold(lambda n: n ** K < c ** n)
        # step lemma coefficients c(N+t)^K - (N+t+1)^K in t, must be >= 0
        coeffs = [c * comb(K, i) * N ** (K - i) - comb(K, i) * (N + 1) ** (K - i) for i in range(K + 1)]
        if N < 4 or not all(x >= 0 for x in coeffs):
            continue
        R = terms([(coeffs[i], "" if i == 0 else ("t" if i == 1 else f"t ^ {i}")) for i in range(K + 1)])
        n0 = next(n for n in range(1, N) if all((m + 1) ** K <= c * m ** K for m in range(n, 400)))
        stmt = f"∀ n : ℕ, {N} ≤ n → n ^ {K} < {c} ^ n"
        ref = (f"  intro n hn\n"
               f"  induction n, hn using Nat.le_induction with\n"
               f"  | base => norm_num\n"
               f"  | succ m hm ih =>\n"
               f"    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm\n"
               f"    have step : ({N} + t + 1) ^ {K} ≤ {c} * ({N} + t) ^ {K} := by\n"
               f"      calc ({N} + t + 1) ^ {K} ≤ ({N} + t + 1) ^ {K} + ({R}) := Nat.le_add_right _ _\n"
               f"        _ = {c} * ({N} + t) ^ {K} := by ring\n"
               f"    calc ({N} + t + 1) ^ {K} ≤ {c} * ({N} + t) ^ {K} := step\n"
               f"      _ < {c} * {c} ^ ({N} + t) := by omega\n"
               f"      _ = {c} ^ ({N} + t + 1) := by ring")
        gap_lean = f"{N - 1} ^ {K} < {c} ^ {N - 1}"
        steps = [
            f"Induct on n, starting the induction at n = {N - 1}.",
            f"Base case: {N - 1}^{K} < {c}^{N - 1}.",
            f"Inductive step: for n ≥ {n0}, (n+1)^{K} ≤ {c}·n^{K}, since (1 + 1/n)^{K} ≤ (1 + 1/{n0})^{K} ≤ {c}.",
            f"Then {c}^(n+1) = {c}·{c}^n > {c}·n^{K} ≥ (n+1)^{K}; so the inequality holds for all n ≥ {N - 1}, in particular for n ≥ {N}.",
        ]
        out.append(cand("expind", f"expind_pow_{c}_{K}", stmt, ref, gap_lean, "  norm_num", "norm_num", steps, 1))
    for c in (2, 3, 4, 5, 6):
        N = min_threshold(lambda n: c ** n < factorial(n), upto=60)
        stmt = f"∀ n : ℕ, {N} ≤ n → {c} ^ n < Nat.factorial n"
        ref = (f"  intro n hn\n"
               f"  induction n, hn using Nat.le_induction with\n"
               f"  | base => decide\n"
               f"  | succ m hm ih =>\n"
               f"    rw [Nat.factorial_succ, pow_succ]\n"
               f"    have hc : {c} ≤ m + 1 := by omega\n"
               f"    have hf : 0 < Nat.factorial m := Nat.factorial_pos m\n"
               f"    nlinarith")
        gap_lean = f"{c} ^ {N - 1} < Nat.factorial {N - 1}"
        steps = [
            f"Induct on n, starting the induction at n = {N - 1}.",
            f"Base case: {c}^{N - 1} < {N - 1}!.",
            f"Inductive step: (n+1)! = (n+1)·n!, and n + 1 ≥ {c} for n ≥ {c - 1}.",
            f"So {c}^(n+1) = {c}·{c}^n < {c}·n! ≤ (n+1)·n! = (n+1)!; the inequality holds for all n ≥ {N - 1}, in particular for n ≥ {N}.",
        ]
        out.append(cand("expind", f"expind_fact_{c}", stmt, ref, gap_lean, "  decide", "decide", steps, 1))
    return out

# ---------- G: cubic with integer roots ----------

def fam_cubic():
    roots = [(1, 2, 3), (-1, 2, 4), (-3, 1, 2), (2, -5, 1), (3, -1, -4), (-2, -3, 5), (4, 1, -6), (1, 1, 3),
             (2, 2, -1), (-1, -1, 4), (5, -2, 3), (-4, 2, 6), (3, 3, -2), (1, -6, 2)]
    out = []
    for r1, r2, r3 in roots:
        e1, e2, e3 = r1 + r2 + r3, r1 * r2 + r2 * r3 + r1 * r3, r1 * r2 * r3
        poly = terms([(1, "x ^ 3"), (-e1, "x ^ 2"), (e2, "x"), (-e3, "")])
        distinct = []
        for r in (r1, r2, r3):
            if r not in distinct:
                distinct.append(r)
        concl = " ∨ ".join(f"x = {r}" for r in distinct)
        fx = lambda r: f"(x - {lit(r)})"
        ref = (f"  intro x h\n"
               f"  have h' : {fx(r1)} * ({fx(r2)} * {fx(r3)}) = 0 := by linear_combination h\n"
               f"  rcases mul_eq_zero.mp h' with h1 | h23\n"
               f"  · have hx : x = {r1} := by linarith\n"
               f"    rw [hx]; norm_num\n"
               f"  · rcases mul_eq_zero.mp h23 with h2 | h3\n"
               f"    · have hx : x = {r2} := by linarith\n"
               f"      rw [hx]; norm_num\n"
               f"    · have hx : x = {r3} := by linarith\n"
               f"      rw [hx]; norm_num")
        stmt = f"∀ x : ℝ, {poly} = 0 → {concl}"
        if r2 + r3 == 0:
            continue
        wq = terms([(1, "x ^ 2"), (r2 + r3, "x"), (r2 * r3, "")])
        gap_lean = f"∀ x : ℝ, {poly} = {fx(r1)} * ({wq})"
        t = next(t for t in (1, 2, 3, -1) if t not in (0, r1))
        steps = [
            f"x = {r1} is a root: substituting gives 0.",
            f"Dividing by x - ({r1}): {poly} = (x - ({r1}))·({wq}).",
            f"The quadratic factor has roots {r2} and {r3}.",
            "A product of real numbers is zero only if one factor is zero, so x is one of the three roots.",
        ]
        out.append(cand("cubic", f"cubic_{r1}_{r2}_{r3}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt=lit(t)), "intro x; ring", steps, 1))
    return out

# ---------- H: AM-GM type bounds ----------

def fam_amgm():
    out = []
    for a, b in [(4, 9), (1, 4), (2, 8), (9, 1), (3, 12), (1, 9), (4, 25), (5, 20)]:
        k = isqrt(a * b)
        assert k * k == a * b and a != b
        ax = "x" if a == 1 else f"{a} * x"
        stmt = f"∀ x : ℝ, 0 < x → {ax} + {b} / x ≥ {2 * k}"
        ref = (f"  intro x hx\n"
               f"  rw [ge_iff_le, ← sub_nonneg]\n"
               f"  have e : {ax} + {b} / x - {2 * k} = ({ax} - {k}) ^ 2 / ({ax}) := by\n"
               f"    field_simp\n"
               f"    ring\n"
               f"  rw [e]\n"
               f"  positivity")
        gap_lean = f"({a} : ℝ) * ({b} / {a}) + {b} / ({b} / {a}) = {2 * k}"
        steps = [
            f"For x > 0 both terms {ax.replace(' * ', '')} and {b}/x are positive.",
            f"The function {ax.replace(' * ', '')} + {b}/x attains its minimum at x = {b}/{a}, where its value is {2 * k}.",
            f"Hence {ax.replace(' * ', '')} + {b}/x ≥ {2 * k} for every x > 0.",
        ]
        out.append(cand("amgm", f"amgm1_{a}_{b}", stmt, ref, gap_lean, "  norm_num", "norm_num", steps, 1))
    for a, x0 in [(1, 2), (1, 3), (2, 1), (3, 2), (1, 1), (2, 3)]:
        b, c = 2 * a * x0 ** 3, 3 * a * x0 ** 2
        ax2 = "x ^ 2" if a == 1 else f"{a} * x ^ 2"
        stmt = f"∀ x : ℝ, 0 < x → {ax2} + {b} / x ≥ {c}"
        coef = "" if a == 1 else f"{a} * "
        ref = (f"  intro x hx\n"
               f"  rw [ge_iff_le, ← sub_nonneg]\n"
               f"  have e : {ax2} + {b} / x - {c} = {coef}(x - {x0}) ^ 2 * (x + {2 * x0}) / x := by\n"
               f"    field_simp\n"
               f"    ring\n"
               f"  rw [e]\n"
               f"  positivity")
        gap_lean = f"∀ x : ℝ, 0 < x → 2 * {a} * x - {b} / x ^ 2 = 0 → x ^ 3 = {b} / {a}"
        refute = f"  intro h\n  have := h {x0} (by norm_num) (by norm_num)\n  norm_num at this"
        steps = [
            f"For x > 0 let g(x) = {ax2.replace(' ^ ', '^').replace(' * ', '')} + {b}/x; g tends to +∞ as x → 0+ and as x → ∞.",
            f"g'(x) = {2 * a}x - {b}/x^2 vanishes exactly when x^3 = {b}/{a}.",
            f"At the critical point x = {x0}, g({x0}) = {c}; this is the global minimum on (0, ∞).",
            f"Hence g(x) ≥ {c} for all x > 0.",
        ]
        out.append(cand("amgm", f"amgm2_{a}_{x0}", stmt, ref, gap_lean, refute, "intro x hx h; field_simp at h; nlinarith", steps, 1))
    return out

# ---------- I: telescoping sums ----------

def fam_telescope():
    out = []
    for c, a in [(1, 1), (1, 2), (2, 1), (3, 2), (1, 3), (5, 1), (2, 3), (4, 1), (3, 4)]:
        cn = "n" if c == 1 else f"{c} * n"
        an = f"(n + {a})" if a == 1 else f"({a} * (n + {a}))"
        num = f"({c} : ℚ)"
        stmt = (f"∀ n : ℕ, ∑ i ∈ Finset.range n, {num} / (((i : ℚ) + {a}) * ((i : ℚ) + {a + 1})) = "
                f"{cn} / {an}")
        ref = (f"  intro n\n"
               f"  induction n with\n"
               f"  | zero => simp\n"
               f"  | succ k ih =>\n"
               f"    rw [Finset.sum_range_succ, ih]\n"
               f"    push_cast\n"
               f"    field_simp\n"
               f"    ring")
        gap_lean = f"∀ i : ℚ, ({c} : ℚ) / ((i + {a}) * (i + {a + 1})) = {c} / (i + {a}) + {c} / (i + {a + 1})"
        steps = [
            f"Partial fractions: {c}/((i+{a})(i+{a + 1})) = {c}/(i+{a}) + {c}/(i+{a + 1}).",
            f"Summing over i = 0, …, n-1, the terms telescope to {c}·(1/{a} - 1/(n+{a})).",
            f"Finally {c}·(1/{a} - 1/(n+{a})) = {c}n/({a}(n+{a})).",
            "Equivalently, induct on n: the inductive step is the same partial-fraction identity.",
        ]
        out.append(cand("telescope", f"tele1_{c}_{a}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro i; field_simp; ring", steps, 0))
    for a in (1, 2, 3, 4, 5):
        stmt = (f"∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + {a}) * ((i : ℚ) + {a + 2})) = "
                f"1 / 2 * (1 / {a} + 1 / {a + 1} - 1 / (n + {a}) - 1 / (n + {a + 1}))")
        ref = (f"  intro n\n"
               f"  induction n with\n"
               f"  | zero => norm_num\n"
               f"  | succ k ih =>\n"
               f"    rw [Finset.sum_range_succ, ih]\n"
               f"    push_cast\n"
               f"    field_simp\n"
               f"    ring")
        gap_lean = f"∀ i : ℚ, (1 : ℚ) / ((i + {a}) * (i + {a + 2})) = 1 / (i + {a}) - 1 / (i + {a + 2})"
        steps = [
            f"Partial fractions: 1/((i+{a})(i+{a + 2})) = 1/(i+{a}) - 1/(i+{a + 2}).",
            "Summing over i = 0, …, n-1, all terms cancel except the first two positive and the last two negative ones.",
            f"Multiplying by 1/2 gives (1/2)(1/{a} + 1/{a + 1} - 1/(n+{a}) - 1/(n+{a + 1})).",
            "Equivalently, induct on n using the same identity in the inductive step.",
        ]
        out.append(cand("telescope", f"tele2_{a}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro i; field_simp; ring", steps, 0))
    return out

# ---------- J: Pell witnesses ----------

def pell_fund(D):
    a0 = isqrt(D)
    m, d, a = 0, 1, a0
    p_prev, p = 1, a0
    q_prev, q = 0, 1
    while p * p - D * q * q != 1:
        m = d * a - m
        d = (D - m * m) // d
        a = (a0 + m) // d
        p_prev, p = p, a * p + p_prev
        q_prev, q = q, a * q + q_prev
    return p, q


def fam_pell():
    out = []
    for D, mpow in [(13, 2), (7, 3), (11, 2), (6, 3), (14, 2), (19, 2), (10, 3), (15, 3), (22, 2), (12, 3),
                    (17, 2), (21, 2), (5, 3), (23, 3)]:
        x1, y1 = pell_fund(D)
        x2, y2 = x1 * x1 + D * y1 * y1, 2 * x1 * y1
        x3, y3 = x1 * x2 + D * y1 * y2, x1 * y2 + x2 * y1
        if mpow == 2:
            B = y1 + (x1 * y1 - y1) // 2
            xs, ys = x2, y2
            xw, yw = x2, x1 * y1
            s3 = (f"For m = 2: ({x1} + {y1}√{D})^2 = {xw} + {yw}√{D}, so ({xw}, {yw}) is a solution.")
        else:
            B = y2 + (y3 - y2) // 3
            xs, ys = x3, y3
            xw, yw = x1 * x2 + y1 * y2, y3
            s3 = (f"m = 2 gives ({x2}, {y2}). For m = 3: x3 = x1·x2 + y1·y2 = {xw} and y3 = x1·y2 + x2·y1 = {yw}, "
                  f"so ({xw}, {yw}) is a solution.")
        assert y1 <= B < ys and xs * xs == D * ys * ys + 1 and xw * xw != D * yw * yw + 1
        stmt = f"∃ x y : ℕ, x ^ 2 = {D} * y ^ 2 + 1 ∧ {B} < y"
        ref = f"  exact ⟨{xs}, {ys}, by norm_num, by norm_num⟩"
        gap_lean = f"{xw} ^ 2 = {D} * {yw} ^ 2 + 1"
        steps = [
            f"The fundamental solution of x^2 - {D}y^2 = 1 is (x1, y1) = ({x1}, {y1}).",
            f"All positive solutions arise from x + y√{D} = ({x1} + {y1}√{D})^m, m ≥ 1, and y grows with m.",
            s3,
            f"Its y-coordinate exceeds {B}, so it is a witness.",
        ]
        out.append(cand("pell", f"pell_{D}_{mpow}", stmt, ref, gap_lean, "  norm_num", "norm_num", steps, 2))
    return out

# ---------- K: additive functional equation with a quadratic defect ----------

def fam_funeq():
    out = []
    for c, a in [(3, 2), (1, 1), (2, -1), (-1, 3), (5, 1), (-2, 2), (1, -3), (3, -2), (-3, 1), (2, 5), (6, 1),
                 (-1, -1), (4, 3), (-5, 2)]:
        fe = terms([(1, "f x"), (1, "f y"), (c, "x * y")])
        concl = terms([(c, "n * (n - 1)"), (2 * a, "n")])
        stmt = f"∀ f : ℤ → ℤ, (∀ x y, f (x + y) = {fe}) → f 1 = {a} → ∀ n, 2 * f n = {concl}"
        ref = (f"  intro f hf h1\n"
               f"  have h0 : f 0 = 0 := by\n"
               f"    have := hf 0 0\n"
               f"    simp at this\n"
               f"    linarith\n"
               f"  intro n\n"
               f"  induction n using Int.induction_on with\n"
               f"  | zero => simp [h0]\n"
               f"  | succ k ih =>\n"
               f"    have := hf k 1\n"
               f"    linear_combination 2 * this + ih + 2 * h1\n"
               f"  | pred k ih =>\n"
               f"    have := hf (-(k : ℤ) - 1) 1\n"
               f"    simp only [sub_add_cancel] at this\n"
               f"    linear_combination -2 * this + ih - 2 * h1")
        lhs = terms([(c, "k * (k - 1)"), (2 * a, "k"), (2 * a, ""), (2 * c, "k")])
        rhs = terms([(c, "(k + 1) * (k + 2)"), (2 * a, "(k + 1)")])
        gap_lean = f"∀ k : ℤ, {lhs} = {rhs}"
        steps = [
            "Setting x = y = 0 gives f 0 = 2·f 0, so f 0 = 0.",
            f"Setting y = 1 gives f (k+1) = f k + ({a}) + ({c})·k for every integer k.",
            f"Upward induction: if 2·f k = ({c})k(k-1) + ({2 * a})k, then 2·f (k+1) = ({c})k(k-1) + ({2 * a})k + ({2 * a}) + ({2 * c})k = ({c})(k+1)(k+2) + ({2 * a})(k+1).",
            f"Downward: f (k-1) = f k - ({a}) - ({c})(k-1); the same computation covers negative n, starting from n = 0.",
        ]
        out.append(cand("funeq", f"funeq_{c}_{a}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro k; ring", steps, 2))
    return out

# ---------- L: divisibility of p^(un+v) + q^(wn+z) ----------

def fam_divind():
    out, seen = [], set()
    for m in (7, 5, 11, 13, 17, 19):
        for p in range(2, 13):
            for q in range(2, 13):
                if p == q or p % m == 0 or q % m == 0:
                    continue
                for u in (2, 1, 3):
                    for w in (1, 2, 3):
                        if pow(p, u, m) != pow(q, w, m) or (p - q) % m == 0:
                            continue
                        for v in (1, 0, 2, 3):
                            for z in (2, 1, 0, 3):
                                if (p ** v + q ** z) % m:
                                    continue
                                if (m, u, w) in seen or len(out) >= 14:
                                    continue
                                seen.add((m, u, w))
                                out.append(_divind_item(m, p, u, v, q, w, z))
    return out


def _exp(u, v):
    base = "n" if u == 1 else f"{u} * n"
    return base if v == 0 else f"{base} + {v}"


def _divind_item(m, p, u, v, q, w, z):
    e1, e2 = _exp(u, v), _exp(w, z)
    pe = lambda e: e if e == "n" else f"({e})"
    stmt = f"∀ n : ℕ, {m} ∣ {p} ^ {pe(e1)} + {q} ^ {pe(e2)}"
    ref = (f"  intro n\n"
           f"  apply (ZMod.natCast_eq_zero_iff _ {m}).mp\n"
           f"  push_cast\n"
           f"  have hpq : ({p} : ZMod {m}) ^ {u} = ({q} : ZMod {m}) ^ {w} := by decide\n"
           f"  have hs : ({p} : ZMod {m}) ^ {v} + ({q} : ZMod {m}) ^ {z} = 0 := by decide\n"
           f"  generalize ({p} : ZMod {m}) = P at hpq hs ⊢\n"
           f"  generalize ({q} : ZMod {m}) = Q at hpq hs ⊢\n"
           f"  calc P ^ {pe(e1)} + Q ^ {pe(e2)} = (P ^ {u}) ^ n * P ^ {v} + (Q ^ {w}) ^ n * Q ^ {z} := by ring\n"
           f"    _ = (Q ^ {w}) ^ n * (P ^ {v} + Q ^ {z}) := by rw [hpq]; ring\n"
           f"    _ = 0 := by rw [hs, mul_zero]")
    D = p ** u - q ** w
    Dw = D + m if D + m != 0 else D - m
    gap_lean = f"({p} : ℤ) ^ {u} - {q} ^ {w} = {Dw}"
    steps = [
        f"Write {p}^({e1.replace(' * ', '')}) = {p}^{v}·({p}^{u})^n and {q}^({e2.replace(' * ', '')}) = {q}^{z}·({q}^{w})^n.",
        f"{p}^{u} - {q}^{w} = {Dw}, a multiple of {m}, so {p}^{u} ≡ {q}^{w} (mod {m}).",
        f"Hence the sum is ≡ ({q}^{w})^n·({p}^{v} + {q}^{z}) (mod {m}).",
        f"Finally {p}^{v} + {q}^{z} = {p ** v + q ** z} is divisible by {m}.",
    ]
    return cand("divind", f"divind_{m}_{p}_{u}_{v}_{q}_{w}_{z}", stmt, ref, gap_lean, "  norm_num", "norm_num",
                steps, 1)

# ---------- M: positivity of a quartic via a hidden SOS ----------

def fam_quartic():
    out = []
    for u, v, w, e in [(1, 2, 1, 1), (1, 1, 1, 1), (2, 1, 1, 1), (1, 3, 1, 1), (2, 2, 1, 1), (3, 2, 1, 1),
                       (1, 1, 2, 1), (2, 3, 1, 1), (1, 4, 1, 1), (2, 1, -1, 1), (3, 4, 1, 1), (1, 2, 2, 1),
                       (2, 2, -1, 1), (3, 1, 1, 1), (1, 3, -1, 2), (2, 4, 1, 1)]:
        A, B, C = v - 2 * u, -2 * v * w, u * u + v * w * w + e
        poly = terms([(1, "x ^ 4"), (A, "x ^ 2"), (B, "x"), (C, "")])
        f = lambda x: x ** 4 + A * x ** 2 + B * x + C
        t = next((t for t in (Fraction(1), Fraction(-1), Fraction(2), Fraction(-2), Fraction(1, 2), Fraction(-1, 2))
                  if f(t) < C), None)
        if t is None:
            continue
        tt = f"({fr(t)} : ℝ)" if t.denominator != 1 else lit(int(t))
        stmt = f"∀ x : ℝ, {poly} > 0"
        wpart = f"x - {w}" if w > 0 else f"x + {-w}"
        ref = f"  intro x\n  nlinarith [sq_nonneg (x ^ 2 - {u}), sq_nonneg ({wpart})]"
        gap_lean = f"∀ x : ℝ, {poly} ≥ {C}"
        steps = [
            f"Let p(x) = {poly.replace(' ^ ', '^').replace(' * ', '')}; then p(0) = {C} > 0.",
            f"The quartic and quadratic terms dominate the linear term {B}x, so p(x) ≥ p(0) = {C} for every real x.",
            f"Therefore p(x) ≥ {C} > 0 for all real x.",
        ]
        out.append(cand("quartic", f"quartic_{u}_{v}_{w}_{e}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt=tt), "intro x; nlinarith", steps, 1))
    return out

# ---------- N: closed forms of finite sums ----------

def fam_sums():
    out = []
    polys = [
        ("i ^ 2", 6, "n * (n + 1) * (2 * n + 1)", lambda i: i * i, lambda n: n * (n + 1) * (2 * n + 1), "ℕ"),
        ("i ^ 3", 4, "n ^ 2 * (n + 1) ^ 2", lambda i: i ** 3, lambda n: n * n * (n + 1) ** 2, "ℕ"),
        ("i * (i + 1)", 3, "n * (n + 1) * (n + 2)", lambda i: i * (i + 1), lambda n: n * (n + 1) * (n + 2), "ℕ"),
        ("i * (i + 1) * (i + 2)", 4, "n * (n + 1) * (n + 2) * (n + 3)", lambda i: i * (i + 1) * (i + 2),
         lambda n: n * (n + 1) * (n + 2) * (n + 3), "ℕ"),
        ("(2 * i + 1) ^ 2", 3, "(n + 1) * (2 * n + 1) * (2 * n + 3)", lambda i: (2 * i + 1) ** 2,
         lambda n: (n + 1) * (2 * n + 1) * (2 * n + 3), "ℕ"),
        ("(2 * i + 1) ^ 3", 1, "(n + 1) ^ 2 * (2 * n ^ 2 + 4 * n + 1)", lambda i: (2 * i + 1) ** 3,
         lambda n: (n + 1) ** 2 * (2 * n * n + 4 * n + 1), "ℕ"),
        ("i ^ 2 * (i + 1)", 12, "n * (n + 1) * (n + 2) * (3 * n + 1)", lambda i: i * i * (i + 1),
         lambda n: n * (n + 1) * (n + 2) * (3 * n + 1), "ℕ"),
        ("(i : ℤ) ^ 4", 30, "(n : ℤ) * (n + 1) * (2 * n + 1) * (3 * n ^ 2 + 3 * n - 1)", lambda i: i ** 4,
         lambda n: n * (n + 1) * (2 * n + 1) * (3 * n * n + 3 * n - 1), "ℤ"),
        ("(i : ℤ) ^ 5", 12, "(n : ℤ) ^ 2 * (n + 1) ^ 2 * (2 * n ^ 2 + 2 * n - 1)", lambda i: i ** 5,
         lambda n: n * n * (n + 1) ** 2 * (2 * n * n + 2 * n - 1), "ℤ"),
        ("i * (i + 1) * (2 * i + 1)", 2, "n * (n + 1) ^ 2 * (n + 2)", lambda i: i * (i + 1) * (2 * i + 1),
         lambda n: n * (n + 1) ** 2 * (n + 2), "ℕ"),
    ]
    for ftxt, k, Gtxt, f, G, ty in polys:
        for n in range(8):
            assert k * sum(f(i) for i in range(n + 1)) == G(n), ftxt
        kk = "" if k == 1 else f"{k} * "
        stmt = f"∀ n : ℕ, {kk}∑ i ∈ Finset.range (n + 1), {ftxt} = {Gtxt}"
        ref = (f"  intro n\n"
               f"  induction n with\n"
               f"  | zero => simp\n"
               f"  | succ k ih =>\n"
               f"    rw [Finset.sum_range_succ{', mul_add' if k != 1 else ''}, ih]\n"
               f"    push_cast\n"
               f"    ring")
        cast = "(n : ℤ)" if ty == "ℤ" else "n"
        # build G(n+1) and f(n) textually via substitution on a placeholder
        def subst(txt, expr):
            return txt.replace("(n : ℤ)", "N").replace("n", "N").replace("N", expr)
        fn = ftxt.replace("(i : ℤ)", "(n : ℤ)").replace("i", "n")
        gap_lean = (f"∀ n : ℕ, {subst(Gtxt, '(' + cast + ' + 1)')} = {subst(Gtxt, cast)} + {k} * ({fn})")
        assert f(1) != f(0)
        steps = [
            "Induct on n; for n = 0 both sides are equal.",
            f"Inductive step: expanding both sides, G(n+1) - G(n) = {k}·f(n), where G(n) = {Gtxt.replace('(n : ℤ)', 'n')} and f(i) = {ftxt.replace('(i : ℤ)', 'i')}.",
            f"Therefore {k}·(sum up to n+1) = G(n) + {k}·f(n+1) = G(n+1).",
        ]
        out.append(cand("sums", f"sums_{len(out)}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro n; push_cast; ring", steps, 1))
    for base in (3, 5, 7):
        stmt = f"∀ n : ℕ, {base - 1} * ∑ i ∈ Finset.range (n + 1), {base} ^ i + 1 = {base} ^ (n + 1)"
        ref = (f"  intro n\n"
               f"  induction n with\n"
               f"  | zero => simp\n"
               f"  | succ k ih =>\n"
               f"    rw [Finset.sum_range_succ, pow_succ {base} (k + 1)]\n"
               f"    omega")
        gap_lean = f"∀ n : ℕ, {base} ^ (n + 2) = {base} ^ (n + 1) + {base - 1} * {base} ^ n"
        steps = [
            "Induct on n; for n = 0 both sides equal " + str(base) + ".",
            f"Adding the next term: {base - 1}·(sum up to n+1) + 1 = ({base}^(n+1)) + {base - 1}·{base}^n.",
            f"And {base}^(n+1) + {base - 1}·{base}^n = {base}^(n+2), which closes the induction.",
        ]
        out.append(cand("sums", f"sums_geo_{base}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="0"), "intro n; ring", steps, 1))
    stmt = "∀ n : ℕ, ∑ i ∈ Finset.range (n + 1), i * Nat.factorial i + 1 = Nat.factorial (n + 1)"
    ref = ("  intro n\n"
           "  induction n with\n"
           "  | zero => simp\n"
           "  | succ k ih =>\n"
           "    rw [Finset.sum_range_succ, Nat.factorial_succ (k + 1)]\n"
           "    nlinarith [ih]")
    gap_lean = "∀ n : ℕ, Nat.factorial (n + 2) = Nat.factorial (n + 1) + n * Nat.factorial n"
    steps = [
        "Induct on n; for n = 0 both sides equal 1.",
        "Adding the next term: (sum up to n+1) + 1 = (n+1)! + n·n!.",
        "And (n+1)! + n·n! = (n+2)!, which closes the induction.",
    ]
    out.append(cand("sums", "sums_fact", stmt, ref, gap_lean, "  " + REFUTE_AT.format(pt="0"), "intro n; ring",
                    steps, 1))
    return out

# ---------- O: first-order recurrences ----------

def fam_rec1():
    out = []
    for k, c in [(1, 1), (1, 2), (2, 1), (2, 3), (3, 1), (1, 5), (3, 2)]:
        kx = "a n" if k == 1 else f"{k} * a n"
        kn = "n" if k == 1 else f"{k} * n"
        a0 = "1" if c == 1 else f"1 / {c}"
        stmt = (f"∀ a : ℕ → ℚ, a 0 = {a0} → (∀ n, a (n + 1) = a n / (1 + {kx})) → "
                f"∀ n, a n = 1 / ({kn} + {c})")
        kk = "(k : ℚ)" if k == 1 else f"{k} * (k : ℚ)"
        ref = (f"  intro a h0 hrec n\n"
               f"  induction n with\n"
               f"  | zero => rw [h0]; norm_num\n"
               f"  | succ k ih =>\n"
               f"    rw [hrec, ih]\n"
               f"    have hk : ({kk} + {c}) ≠ 0 := by positivity\n"
               f"    push_cast\n"
               f"    field_simp\n"
               f"    try ring")
        gap_lean = f"∀ x : ℚ, x / (1 + {k} * x) = x - {k} * x ^ 2"
        steps = [
            f"Expand the recursion: a (n+1) = a n/(1 + {k}·a n) = a n - {k}·(a n)^2.",
            f"Taking reciprocals, 1/a (n+1) = 1/a n + {k}.",
            f"With 1/a 0 = {c} this gives 1/a n = {k}n + {c}, i.e. a n = 1/({k}n + {c}).",
            "All a n are positive, so no division by zero occurs.",
        ]
        out.append(cand("rec1", f"rec1_inv_{k}_{c}", stmt, ref, gap_lean,
                        "  " + REFUTE_AT.format(pt="1"), "intro x; field_simp; ring", steps, 0))
    for m, d, e in [(2, 1, 0), (3, 4, 1), (2, 3, 1), (4, 6, -1), (5, -8, 3), (3, -2, 0), (6, 10, 2)]:
        dp = d // (m - 1)
        assert dp * (m - 1) == d
        rec = terms([(m, "a n"), (d, "")])
        closed = terms([(e + dp, f"{m} ^ n"), (-dp, "")])
        stmt = f"∀ a : ℕ → ℤ, a 0 = {e} → (∀ n, a (n + 1) = {rec}) → ∀ n, a n = {closed}"
        ref = (f"  intro a h0 hrec n\n"
               f"  induction n with\n"
               f"  | zero => rw [h0]; norm_num\n"
               f"  | succ k ih =>\n"
               f"    rw [hrec, ih]\n"
               f"    ring")
        gap_lean = f"({m} : ℚ) * ({d} / ({m} - 1)) + {d} = {d} / ({m} - 1)"
        steps = [
            f"Look for a fixed point L of x ↦ {m}x + ({d}): L = {m}L + ({d}).",
            f"Solving, L = ({d})/({m} - 1) = {Fraction(d, m - 1)}.",
            f"Then b n = a n - L satisfies b (n+1) = {m}·b n, so b n = {m}^n·b 0.",
            f"Hence a n = ({e + dp})·{m}^n - ({dp}).",
        ]
        out.append(cand("rec1", f"rec1_aff_{m}_{d}_{e}", stmt, ref, gap_lean, "  norm_num", "norm_num", steps, 1))
    return out


FAMILIES = [fam_rec2, fam_powsum, fam_gcdlin, fam_dioph, fam_fermat, fam_expind, fam_cubic, fam_amgm,
            fam_telescope, fam_pell, fam_funeq, fam_divind, fam_quartic, fam_sums, fam_rec1]


def all_candidates():
    out = []
    for f in FAMILIES:
        out.extend(f())
    keys = [c["key"] for c in out]
    assert len(keys) == len(set(keys)), "duplicate keys"
    return out
