"""Reducer determinism under input permutation, seeded tie-break, and reducer semantics."""

from __future__ import annotations

import math
import random
from collections import Counter

import eq_harness as eh

PERMS = 200


def shuffles(xs: list, k: int = PERMS, seed: int = 7) -> list[list]:
    rng = random.Random(seed)
    out = []
    for _ in range(k):
        y = list(xs)
        rng.shuffle(y)
        out.append(y)
    return out


def test_plurality_invariant_under_permutation_with_ties() -> None:
    answers = ["B", "a", " A ", "b", None, "c", ""]
    for seed in range(30):
        ref = eh.plurality(answers, seed)
        assert ref.tied == ("a", "b") and ref.top == 2 and ref.kappa == 2 / 7
        rep = {k: eh.representative(answers, k) for k in ref.tied}
        for p in shuffles(answers, 40, seed):
            assert eh.plurality(p, seed) == ref
            assert {k: eh.representative(p, k) for k in ref.tied} == rep


def test_tie_break_is_seeded_and_order_free() -> None:
    cands = ["x", "y", "z"]
    winners = Counter(eh.tie_break(cands, s) for s in range(300))
    assert set(winners) == {"x", "y", "z"} and min(winners.values()) > 60
    for s in range(50):
        w = eh.tie_break(cands, s)
        assert all(eh.tie_break(p, s) == w for p in shuffles(cands, 10, s))
    assert eh.tie_break(["b", "a"], eh.SEED_TIES) == eh.tie_break(["a", "b"], eh.SEED_TIES)


def test_plurality_abstain_and_kappa() -> None:
    r = eh.plurality([None, "", None], 1)
    assert r.winner is None and r.kappa == 0.0
    r = eh.plurality(["4", "4", "4", "5", None], 1)
    assert r.winner == "4" and r.top == 3 and r.kappa == 0.6


def test_verify_then_select_order_free_and_seeded() -> None:
    passed = {0: False, 1: True, 2: False, 3: True, 4: True}
    for seed in range(100):
        ref = eh.verify_then_select(passed, seed)
        assert ref in (1, 3, 4)
        for p in shuffles(list(passed.items()), 10, seed):
            assert eh.verify_then_select(dict(p), seed) == ref
    assert len({eh.verify_then_select(passed, s) for s in range(100)}) == 3
    assert eh.verify_then_select({0: False, 1: False}, 3) is None


def _findings(seed: int) -> list[eh.Finding]:
    rng = random.Random(seed)
    out = []
    for m in range(1, 6):
        for _ in range(rng.randint(0, 5)):
            out.append(eh.Finding(rng.choice(["a.py", "b.py"]), rng.randint(1, 30), rng.choice(["x", "y"]), m,
                                  f'{{"m": {m}, "r": {rng.random()}}}'))
    return out


def _sig(cl: list[eh.Cluster]) -> list[tuple[str, int, int, frozenset[int]]]:
    return [(c.key, c.line_hi, c.support, c.members) for c in cl]


def test_cluster_findings_order_free() -> None:
    for seed in range(40):
        fs = _findings(seed)
        ref = eh.cluster_findings(fs)
        for c in ref:
            assert c.line_hi - c.line_lo <= 3
        for p in shuffles(fs, 20, seed):
            got = eh.cluster_findings(p)
            assert _sig(got) == _sig(ref)
            assert [c.key for c in eh.accept_findings(got, 2)] == [c.key for c in eh.accept_findings(ref, 2)]
            assert [c.key for c in eh.singles_for_verifier(got, 2, 11)] == \
                   [c.key for c in eh.singles_for_verifier(ref, 2, 11)]


def test_cluster_semantics() -> None:
    fs = [eh.Finding("a.py", 10, "x", 1, "1"), eh.Finding("a.py", 12, "x", 2, "2"), eh.Finding("a.py", 13, "x", 2, "3"),
          eh.Finding("a.py", 14, "x", 3, "4"), eh.Finding("a.py", 10, "y", 4, "5")]
    cl = eh.cluster_findings(fs)
    assert [(c.line_lo, c.claim_class, c.support) for c in cl] == [(10, "x", 2), (14, "x", 1), (10, "y", 1)]
    acc = eh.accept_findings(cl, 2, verified=[cl[2].key])
    assert {c.key for c in acc} == {cl[0].key, cl[2].key}
    assert eh.kappa_findings(cl, 2) == 1 / 3
    assert len(eh.singles_for_verifier(cl, 2, 5, max_calls=1)) == 1


def test_parse_findings_drops_malformed() -> None:
    fields = {"file": "file", "line": "line", "claim_class": "claim_class"}
    ans = [{"file": "./a.py", "line": "7", "claim_class": " Off-By-One "}, {"file": "a.py"}, "junk"]
    got = eh.parse_findings(ans, 2, fields)
    assert [(f.file, f.line, f.claim_class, f.member) for f in got] == [("a.py", 7, "off-by-one", 2)]


def test_median_ln_order_free_and_values() -> None:
    vals = [100.0, 400.0, 0, -3, None, "x", 25.0]
    ref = eh.median_ln(vals)
    assert ref == 100.0
    for p in shuffles(vals, 50):
        assert eh.median_ln(p) == ref and eh.kappa_numeric(p) == eh.kappa_numeric(vals)
    m = eh.median_ln([10, 1000])
    assert m is not None and math.isclose(m, 100.0)
    assert eh.median_ln([None, -1]) is None
    assert eh.kappa_numeric([100, 150, 199, 400, 49]) == 3 / 5  # within a factor 2 of 150: 100, 150, 199


def test_borda_order_free_and_seeded() -> None:
    r1, r2 = [2, 0, 1, 3], [0, 3, 1, 2]
    w, scores = eh.borda([r1, r2], 4, 5)
    assert scores == [5, 2, 3, 2] and w == 0
    assert eh.borda([r2, r1], 4, 5) == (w, scores)
    tie = [[0, 1], [1, 0]]
    assert {eh.borda(tie, 2, s)[0] for s in range(50)} == {0, 1}
    assert eh.borda([[0, 0, 9, True, 1]], 2, 1)[1] == [1, 0]


def test_medoid_plan_ties_to_g() -> None:
    def plan(*owners: str) -> eh.Plan:
        nodes = [{"id": f"n{i}", "owner": o, "brief": "b", "deps": [f"n{i - 1}"] if i else [], "kind": "other",
                  "weight": 1} for i, o in enumerate(owners)]
        p = eh.parse_plan({"nodes": nodes}, ["coder", "writer"])
        assert p is not None
        return p

    a, b = plan("coder"), plan("writer")
    assert eh.medoid_plan([a, b, None]) == 0
    assert eh.medoid_plan([a, b, b]) == 1
    assert eh.medoid_plan([None, b, a]) == 1
    assert eh.medoid_plan([None, None]) is None


def test_parse_plan_rejects_cycles_and_unknown_owner() -> None:
    owners = ["coder"]
    good = {"nodes": [{"id": "b", "owner": "coder", "brief": "x", "deps": ["a"], "kind": "other", "weight": 1},
                      {"id": "a", "owner": "coder", "brief": "x", "deps": [], "kind": "other", "weight": 1}]}
    p = eh.parse_plan(good, owners)
    assert p is not None and [n.id for n in p.nodes] == ["a", "b"]
    cyc = {"nodes": [{"id": "a", "owner": "coder", "brief": "x", "deps": ["b"], "kind": "other", "weight": 1},
                     {"id": "b", "owner": "coder", "brief": "x", "deps": ["a"], "kind": "other", "weight": 1}]}
    assert eh.parse_plan(cyc, owners) is None
    bad_owner = {"nodes": [{"id": "a", "owner": "Agent", "brief": "x", "deps": [], "kind": "other", "weight": 1}]}
    assert eh.parse_plan(bad_owner, owners) is None
    nine = {"nodes": [{"id": f"n{i}", "owner": "coder", "brief": "x", "deps": [], "kind": "other", "weight": 1}
                      for i in range(9)]}
    assert eh.parse_plan(nine, owners) is None
