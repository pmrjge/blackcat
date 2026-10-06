# A1.3 check: old R3 (distinct verified fact keys) vs new R3 (members with >=1 verified kind-matching fact).
import hashlib, random
FILE = {10: "x = 1", 11: "y = compute(x)", 12: "return y"}  # quote found on line 11 only
def found_line(path, line, quote):  # verify window l-1..l+1, return canonical line or None
    for l in (line - 1, line, line + 1):
        if quote in FILE.get(l, ""): return l
    return None
def key_old(path, line, quote): return (path, line, hashlib.sha256(quote.encode()).hexdigest()[:8])
def key_new(path, line, quote):
    l = found_line(path, line, quote); return None if l is None else (path, l, hashlib.sha256(quote.encode()).hexdigest()[:8])
# member m1 (cluster A) cites the same quote at lines 10, 11, 12; m2, m3 (cluster B) share one fact at line 11
cites = {"m1": ("A", [("f.py", 10, "y = compute"), ("f.py", 11, "y = compute"), ("f.py", 12, "y = compute")]),
         "m2": ("B", [("f.py", 11, "y = compute")]), "m3": ("B", [("f.py", 11, "y = compute")])}
def r3_old(c):
    keys = {}
    for m, (cl, fs) in c.items():
        for f in fs:
            if found_line(*f) is not None: keys.setdefault(cl, set()).add(key_old(*f))
    return {cl: len(k) for cl, k in keys.items()}
def r3_new(c, r0_votes, seed=366605965):
    score = {}
    for m, (cl, fs) in c.items():
        if any(found_line(*f) is not None for f in fs): score[cl] = score.get(cl, 0) + 1   # <= 1 per member per cluster
    if not score: return "R0", score
    top = max(score.values()); tied = sorted(cl for cl in score if score[cl] == top)
    if len(tied) == 1: return tied[0], score
    best = max(r0_votes[cl] for cl in tied); tied2 = sorted(cl for cl in tied if r0_votes[cl] == best)  # tie 1: plain votes
    return (tied2[0] if len(tied2) == 1 else random.Random(seed).choice(tied2)), score             # tie 2: seeded
print("old scores:", r3_old(cites), "-> A wins by padding")
print("new keys m1:", {key_new(*f) for f in cites["m1"][1]}, "(3 citations -> 1 canonical key)")
print("new R3:", r3_new(cites, {"A": 1, "B": 2}))
assert r3_new(cites, {"A": 1, "B": 2})[0] == "B"
# tie case: one verified member each, plain votes A=1, B=3 -> B
c2 = {"m1": ("A", [("f.py", 11, "y = compute")]), "m2": ("B", [("f.py", 11, "y = compute")]), "m3": ("B", []), "m4": ("B", [])}
print("tie -> plain votes:", r3_new(c2, {"A": 1, "B": 3}))
assert r3_new(c2, {"A": 1, "B": 3})[0] == "B"
print("no verified member ->", r3_new({"m1": ("A", [("f.py", 11, "zzz")])}, {"A": 1}))
