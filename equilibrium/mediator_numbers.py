# Numbers for MEDIATOR.md: H4 sample sizes (exact, two routes), subset counts, Borda IIA example.
import functools, itertools, math
import numpy as np
from scipy import stats
import derive_numbers as d

d.k_crit = functools.lru_cache(maxsize=None)(d.k_crit)  # route 1 (math.comb), cached

def kc_scipy(n, a):  # route 2 critical count via scipy binom.sf
    for k in range(math.ceil(n/2), n+1):
        if min(1.0, 2*stats.binom.sf(k-1, n, 0.5)) <= a: return k
    return None

def pw2(n, delta, pi, a):
    pmf = stats.binom.pmf(np.arange(n+1), n, delta)
    tot = 0.0
    for D in range(1, n+1):
        k = kc_scipy(D, a)
        if k is not None: tot += pmf[D]*stats.binom.sf(k-1, D, pi)
    return tot

for delta in (0.05, 0.10, 0.15):
    for pi in (0.75, 0.85):
        n1 = d.min_items(delta, pi, 0.05, start=20)
        print(f"H4 alpha .05 delta={delta} pi={pi}: min items {n1}; route1 power {d.power_unconditional(n1,delta,pi,.05):.3f}, route2 {pw2(n1,delta,pi,.05):.3f}")
print("pilot E items (60) at delta .10 pi .75 power:", round(d.power_unconditional(60,.10,.75,.05),4))
print("subsets per item N=5 (Shapley coalitions):", 2**5, "; LOO reducer runs:", 5, "; M1 subsets m=1..5:", sum(math.comb(5,m) for m in range(1,6)))
# Shapley check: plurality agreement game, votes A,A,A,B,C -> value 1[reducer(S)==A]; ties broken by fixed order A<B<C
votes = ["A","A","A","B","C"]
def red(S):
    if not S: return None
    c = {}
    for i in S: c[votes[i]] = c.get(votes[i],0)+1
    m = max(c.values()); return sorted(k for k,v in c.items() if v==m)[0]
v = lambda S: 1.0 if red(S)=="A" else 0.0
N=5; phi=[0.0]*N
for i in range(N):
    for r in range(N):
        for S in itertools.combinations([j for j in range(N) if j!=i], r):
            w = math.factorial(r)*math.factorial(N-r-1)/math.factorial(N)
            phi[i] += w*(v(set(S)|{i}) - v(set(S)))
print("Shapley A,A,A,B,C (agreement game, lexicographic ties):", [round(x,4) for x in phi], "sum", round(sum(phi),4), "HHI", round(sum(x*x for x in phi)/sum(phi)**2,4))
# Borda IIA: removing a non-winner can change the winner
def borda(rankings, cands):
    s = {c:0 for c in cands}
    for r in rankings:
        rr = [c for c in r if c in cands]
        for pos,c in enumerate(rr): s[c] += len(rr)-1-pos
    m = max(s.values()); return sorted(c for c in s if s[c]==m), s
R = [["x","y","z"],["y","z","x"]]   # two judge orders' rankings
print("Borda full:", borda(R, {"x","y","z"}), " without z:", borda(R, {"x","y"}))
print("-- multi-reducer family (Holm over 3, first step 0.05/3) --")
a3 = 0.05/3
n=1
while d.k_crit(n, a3) is None: n += 1
print(f"first reachable at alpha {a3:.4f}: {d.k_crit(n,a3)}/{n} p={d.p_two_sided_exact(n,n):.4f}")
for delta in (0.10, 0.15):
    for pi in (0.75, 0.85):
        n1 = d.min_items(delta, pi, a3, start=20)
        print(f"H4 Holm1st/3 delta={delta} pi={pi}: min items {n1}; route2 power {pw2(n1,delta,pi,a3):.3f}")
for n_items, delta, pi in [(25,.15,.85),(25,.10,.75),(306,.10,.75),(306,.15,.85)]:
    print(f"power n={n_items} delta={delta} pi={pi} alpha .0167: r1 {d.power_unconditional(n_items,delta,pi,a3):.3f} r2 {pw2(n_items,delta,pi,a3):.3f}")
