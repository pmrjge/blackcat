"""Leave-one-out in every round (RUNTIME_EQUILIBRIUM §4): `summary(exclude=)` (LOO views, §4.2), `loo_exclude`
(none / rotation / random / leader) and `round_loo` (the reducer-side jackknife, answer-keyed tie seeds, λ per
family, pivotal members, §4.1). Parity with the runtime port (dot-claude/hooks/eq_core.py) is tests/test_eq_parity.py.
"""

from __future__ import annotations

import hashlib
import random
from collections import Counter
from typing import Any

import pytest

import eq_harness as eh
import eq_mediator as md

V, R, U = md.VERIFIED, md.REFUTED, md.UNVERIFIABLE
RS_KEY = eh.make_answer_key(eh.DEFAULT_FLAGS["answer_key"]["RS"])


def outs_of(answers: list[Any]) -> list[md.MemberOut]:
    return [md.MemberOut(i + 1, a) for i, a in enumerate(answers)]


# ---- summary(exclude=) ---------------------------------------------------------------------------------------------


def summary_cases() -> list[tuple[Any, ...]]:
    """Deterministic summary inputs (discrete and numeric, 1-6 members, verified / refuted / unverifiable facts)."""
    rng = random.Random(4242)
    cases = []
    for _ in range(80):
        family = rng.choice(["discrete", "numeric"])
        n = rng.randint(1, 6)
        pool: list[Any] = ["A", "a ", "B", "C", None, {"label": "x"}] if family == "discrete" else \
            [None, 1, 2, 3, 10, 12, 100, 0.5, -1, "x"]
        answers = {m: rng.choice(pool) for m in range(1, n + 1)}
        fkeys = [f"k{j}" for j in range(6)]
        member_facts = {m: rng.sample(fkeys, rng.randint(0, 4)) for m in answers}
        facts = {k: md.Fact(k, rng.choice(["quote", "file_line", "odd"]), f"ref {k}", f"detail {k}",
                            rng.choice([V, R, U]), "m", None) for k in fkeys}
        ctx = md.Ctx(family=family)
        cl = md.cluster([md.MemberOut(m, a) for m, a in answers.items()], ctx)
        cases.append((answers, cl, member_facts, facts, rng.randrange(2**32), ctx))
    return cases


# sha256 of the 80 summaries above joined by "\n\x00\n", computed with eq_mediator.summary BEFORE `exclude` existed
# (eq-runtime d8e7ab9): the shared summary must stay byte-identical.
GOLDEN_SHARED = "e9dc37515ac935e2ba2c8851388229b6ccab43d0d9529ef992e1f03c13827dd1"


def test_exclude_none_is_the_shared_summary_byte_for_byte() -> None:
    texts = [md.summary(*c) for c in summary_cases()]
    assert hashlib.sha256("\n\x00\n".join(texts).encode()).hexdigest() == GOLDEN_SHARED
    for c in summary_cases():
        assert md.summary(*c, exclude=None) == md.summary(*c)
        assert md.summary(*c, exclude=99) == md.summary(*c)  # excluding a non-member changes nothing


def canary_round(rng: random.Random, family: str) -> tuple[Any, ...]:
    """A round where some members hold a unique answer token and every fact carries a unique token."""
    n = rng.randint(2, 6)
    if family == "discrete":
        answers: dict[int, Any] = {m: rng.choice(["shared-a", "shared-b", f"UNIQ{m}ANS"]) for m in range(1, n + 1)}
    else:
        uniq = {1: 1234.5, 2: 2718.3, 3: 3141.6, 4: 5772.1, 5: 6180.3, 6: 8314.4}  # no geometric mean collides
        answers = {m: rng.choice([10, 20, uniq[m]]) for m in range(1, n + 1)}
    fkeys = [f"F{j}X" for j in range(8)]
    member_facts = {m: rng.sample(fkeys, rng.randint(0, 4)) for m in answers}
    facts = {k: md.Fact(k, "quote", f"ref-{k}", f"detail-{k}", rng.choice([V, R]), "m", None) for k in fkeys}
    return answers, member_facts, facts, rng.randrange(2**32)


@pytest.mark.parametrize("family", ["discrete", "numeric"])
def test_canary_the_excluded_member_never_reaches_the_view(family: str) -> None:
    """summary(exclude=j) never holds j's answer text nor a fact only j cited, whatever clusters the caller passes
    (here: those of the full round, j included); a fact an included member also cited is still there when refuted
    (refuted facts are always listed); every other member's answer is still counted."""
    rng = random.Random(f"canary-{family}")
    seen_drop = seen_keep = 0
    for _ in range(400):
        answers, member_facts, facts, seed = canary_round(rng, family)
        ctx = md.Ctx(family=family)
        full = md.cluster([md.MemberOut(m, a) for m, a in answers.items()], ctx)
        for j in answers:
            text = md.summary(answers, full, member_facts, facts, seed, ctx, exclude=j)
            mine = answers[j]
            token = (mine if family == "discrete" else f"{mine:.6g}")
            others = [a if family == "discrete" else f"{a:.6g}" for m, a in answers.items() if m != j]
            if token not in others:
                assert token not in text, (j, answers, text)
            only_j = set(member_facts[j]) - {k for m, ks in member_facts.items() if m != j for k in ks}
            for k in only_j:
                assert f"ref-{k}" not in text and f"detail-{k}" not in text, (j, k, text)
                seen_drop += 1
            for k in set(member_facts[j]) - only_j:
                if facts[k].status == R:
                    assert f"ref-{k}" in text, (j, k, text)
                    seen_keep += 1
            if family == "discrete":
                hist = Counter(a for m, a in answers.items() if m != j)
                for a, c in hist.items():
                    assert f"{md.quoted(a, 300)}: {c}" in text
    assert seen_drop > 100 and seen_keep > 100  # both sides of the property were exercised


def test_live_mediator_view_reclusters_without_the_excluded_member() -> None:
    """Numeric: the excluded member's estimate cannot move the near/far split of the others (median recomputed)."""
    ctx = md.Ctx(family="numeric")

    class _Led:
        def write(self, *a: Any, **k: Any) -> None:
            return None

    lm = md.LiveMediator(_Led(), md.FactChecker(None, ""), ctx, {})  # type: ignore[arg-type]
    for m, v in enumerate([1, 1, 8, 8, 8], start=1):
        lm.claim(m, 0, v, [])
    shared = lm.summary(5)  # median 8: the three 8s near, the two 1s far
    assert "within a factor 2 of the median: 3" in shared and "beyond a factor 2 of the median: 2" in shared
    view = lm.summary(5, exclude=5)
    assert "Estimates (sorted): 1, 1, 8, 8; geometric median: 2.82843" in view
    # without member 5 the median is sqrt(8) and every estimate is beyond a factor 2 of it: the shared split
    # (8s near) would have leaked member 5's pull on the median
    assert "beyond a factor 2 of the median: 4" in view and "within" not in view
    assert lm.summary(5, exclude=None) == shared


# ---- loo_exclude ---------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("n", range(2, 10))
def test_rotation_excludes_e_r_i_and_each_member_once_per_round(n: int) -> None:
    for r in range(1, n):
        es = [md.loo_exclude("rotation", i, r, n, seed=0) for i in range(1, n + 1)]
        assert es == [(i - 1 + r) % n + 1 for i in range(1, n + 1)]  # e_r(i) = (p + r) mod N on 0-based p = i - 1
        assert sorted(es) == list(range(1, n + 1))  # each member excluded from exactly one view
        assert all(e != i for i, e in zip(range(1, n + 1), es, strict=True))
    for i in range(1, n + 1):  # over R <= N - 1 rounds member i misses R distinct members
        assert len({md.loo_exclude("rotation", i, r, n, seed=0) for r in range(1, n)}) == n - 1


def test_loo_exclude_edges() -> None:
    for v in md.LOO_VARIANTS:
        assert md.loo_exclude(v, 1, 0, 5, seed=1, top=[1, 2]) is None  # round 0 is blind
        assert md.loo_exclude(v, 1, 3, 1, seed=1, top=[1]) is None  # nobody else
    assert md.loo_exclude("none", 2, 1, 5, seed=1) is None
    assert md.loo_exclude("rotation", 2, 5, 5, seed=1) is None  # r = N would pick i itself
    for bad in ((0, 1, 3), (4, 1, 3), (1, 1, 0)):
        with pytest.raises(ValueError):
            md.loo_exclude("rotation", *bad, seed=1)
    with pytest.raises(ValueError):
        md.loo_exclude("leader-conf", 1, 1, 3, seed=1)
    assert (md.SEED_LOO, md.SEED_LOO_LEADER) == (568287631, 1446025924)


def test_random_is_reproducible_by_seed_and_uniform_over_the_others() -> None:
    n = 5
    for seed in ("run-a", 17):
        for r in (1, 2):
            for i in range(1, n + 1):
                e = md.loo_exclude("random", i, r, n, seed=seed)
                assert e is not None and e != i and 1 <= e <= n
                assert md.loo_exclude("random", i, r, n, seed=seed) == e
    draws = Counter(md.loo_exclude("random", 1, 1, n, seed=s) for s in range(4000))
    assert set(draws) == {2, 3, 4, 5} and min(draws.values()) > 850  # ~1000 each
    a = [md.loo_exclude("random", i, 1, n, seed="x") for i in range(1, n + 1)]
    b = [md.loo_exclude("random", i, 1, n, seed="y") for i in range(1, n + 1)]
    assert a != b or [md.loo_exclude("random", i, 1, n, seed="z") for i in range(1, n + 1)] != a


def test_leader_picks_a_top_cluster_member_and_the_leader_rotates() -> None:
    n = 6
    leaders = Counter()
    for seed in range(300):
        top = sorted(random.Random(seed).sample(range(1, n + 1), 3))
        es = {i: md.loo_exclude("leader", i, 1, n, seed=seed, top=top) for i in range(1, n + 1)}
        led = {e for i, e in es.items() if e != md.loo_exclude("rotation", i, 1, n, seed=seed)}
        lead = Counter(es.values()).most_common(1)[0][0]
        assert lead in top
        for i, e in es.items():
            if i == lead:
                assert e == md.loo_exclude("rotation", i, 1, n, seed=seed)
            else:
                assert e == lead
        assert led <= {lead}
        leaders[top.index(lead)] += 1
    assert set(leaders) == {0, 1, 2} and min(leaders.values()) > 60  # any top member, not always the smallest
    assert md.loo_exclude("leader", 2, 1, 4, seed=3, top=[]) == md.loo_exclude("rotation", 2, 1, 4, seed=3)
    assert md.loo_exclude("leader", 2, 1, 4, seed=3, top=[0, 9]) == md.loo_exclude("rotation", 2, 1, 4, seed=3)


# ---- round_loo -----------------------------------------------------------------------------------------------------


def disc(**kw: Any) -> md.Ctx:
    return md.Ctx(family="discrete", key=RS_KEY, **kw)


def keyed_first(keys: Any, seed: int) -> str:
    return min(set(keys), key=lambda k: (hashlib.sha256(f"{seed}|{k}".encode()).hexdigest(), k))


def test_removing_a_member_never_reorders_the_remaining_tied_answers() -> None:
    """Every subset reduction picks, among its tied answers, the one first in the round's answer-keyed order."""
    rng = random.Random(7)
    hits = 0
    for _ in range(600):
        answers = [rng.choice(["A", "B", "C", "D"]) for _ in range(rng.randint(2, 7))]
        seed = rng.randrange(2**32)
        res = md.round_loo(outs_of(answers), disc(), seed)
        for i, r in res["loo"].items():
            rest = Counter(a for m, a in enumerate(answers, start=1) if m != i)
            top = max(rest.values())
            tied = [RS_KEY(a) for a, c in rest.items() if c == top]  # the answer keys ("a", "b", ...)
            assert RS_KEY(r["answer"]) == keyed_first(tied, seed), (answers, seed, i)
            hits += len(tied) > 2
    assert hits > 200


def test_tied_checkable_and_long_form_follow_the_candidate_keys() -> None:
    rng = random.Random(8)
    for _ in range(300):
        n = rng.randint(2, 6)
        answers = [f"patch-{rng.randint(0, 9)}" for _ in range(n)]
        seed = rng.randrange(2**32)
        verdicts = {m: rng.choice(["pass", "fail", "unverifiable"]) for m in range(1, n + 1)}
        res = md.round_loo(outs_of(answers), md.Ctx(family="checkable"), seed, opts=md.LooOpts(verdicts=verdicts))
        for i, r in res["loo"].items():
            passers = [m for m in range(1, n + 1) if m != i and verdicts[m] == "pass"]
            want = min(passers, key=lambda m: (hashlib.sha256(f"{seed}|{answers[m - 1]}".encode()).hexdigest(), m)) \
                if passers else None
            assert r["selected"] == want
        lf = md.round_loo(outs_of(answers), md.Ctx(family="long_form"), seed)  # no rankings: every candidate ties
        for i, r in lf["loo"].items():
            assert r["answer"] == keyed_first([a for m, a in enumerate(answers, start=1) if m != i], seed)


def test_lambda_discrete() -> None:
    res = md.round_loo(outs_of(["A", "A", "A", "B", "C"]), disc(), 1)
    assert (res["lambda"], res["pivotal"]) == (1.0, [])
    for seed in range(20):
        res = md.round_loo(outs_of(["A", "A", "B", "B", "C"]), disc(), seed)
        win = keyed_first(["a", "b"], seed)  # the normalised keys
        piv = [1, 2] if win == "a" else [3, 4]
        assert res["pivotal"] == piv and res["lambda"] == 3 / 5
        assert all(res["loo"][i]["same"] == (i not in piv) == res["loo"][i]["stable"] for i in range(1, 6))
    rs = [{"label": "REFUTED", "value": "1", "rationale": "p"}, {"label": "REFUTED", "value": "1", "rationale": "q"},
          {"label": "REFUTED", "value": "2", "rationale": "p"}]
    res = md.round_loo(outs_of(rs), disc(), 3)  # RS keys on label + value: the rationale never splits
    assert res["pivotal"] == [] and res["lambda"] == 1.0
    assert res["loo"][3]["answer"] == rs[0]


def test_lambda_numeric_uses_the_ln_1_1_band() -> None:
    res = md.round_loo(outs_of([1, 10, 100]), md.Ctx(family="numeric"), 0)
    assert res["pivotal"] == [1, 3] and res["lambda"] == pytest.approx(1 / 3)
    assert res["loo"][2]["answer"] == pytest.approx(10.0)
    res = md.round_loo(outs_of([10, 10.4, 10.9, 11.4]), md.Ctx(family="numeric"), 0)
    assert res["pivotal"] == [] and res["lambda"] == 1.0  # every S \ i median within a factor 1.1
    res = md.round_loo(outs_of([None, 5]), md.Ctx(family="numeric"), 0)
    assert res["pivotal"] == [2] and res["loo"][2]["answer"] is None


def test_lambda_checkable_counts_remaining_passers() -> None:
    ctx = md.Ctx(family="checkable")
    one = md.round_loo(outs_of(["p1", "p2", "p3", "p4"]), ctx, 5,
                       opts=md.LooOpts(verdicts={1: "fail", 2: "pass", 3: "unverifiable", 4: "fail"}))
    assert one["lambda"] == 3 / 4 and one["pivotal"] == [2] and one["loo"][2]["selected"] is None
    two = md.round_loo(outs_of(["p1", "p2", "p3", "p4"]), ctx, 5,
                       opts=md.LooOpts(verdicts={1: "pass", 2: "pass", 3: "fail", 4: "fail"}))
    assert two["lambda"] == 1.0 and len(two["pivotal"]) == 1  # the selected passer is pivotal, yet a passer remains
    none = md.round_loo(outs_of(["p1", "p2", None]), ctx, 5, opts=md.LooOpts(verdicts={3: "pass"}))
    assert none["lambda"] == 0 and none["pivotal"] == []


def test_lambda_finding_sets_identical_accepted_set() -> None:
    f = [{"file": "a.py", "line": 3, "claim": "x"}]
    g = [{"file": "b.py", "line": 9, "claim": "y"}]
    ctx = md.Ctx(family="finding_set", t=2)
    res = md.round_loo(outs_of([f, f, f, g, g]), ctx, 0)  # a.py support 3 (stable), b.py support 2 = t (not)
    assert res["pivotal"] == [4, 5] and res["lambda"] == 3 / 5
    assert res["loo"][4]["answer"] == f
    near = [{"file": "a.py", "line": 5, "claim": "x"}]  # same cluster within the tolerance: still "identical"
    res = md.round_loo(outs_of([f, f, near]), ctx, 0)
    assert res["pivotal"] == [] and res["lambda"] == 1.0
    res = md.round_loo(outs_of([None, None]), ctx, 0)
    assert res["pivotal"] == [] and res["loo"][1]["answer"] is None


def test_lambda_long_form_borda_without_i() -> None:
    ctx = md.Ctx(family="long_form")
    rank = [[1, 2, 3], [1, 3, 2]]
    res = md.round_loo(outs_of(["d1", "d2", "d3"]), ctx, 0, opts=md.LooOpts(rankings=rank))
    assert res["loo"][2]["selected"] == 1 and res["loo"][3]["selected"] == 1
    assert res["pivotal"] == [1] and res["lambda"] == 2 / 3
    assert res["loo"][1]["selected"] in (2, 3)


def test_round_loo_rejects_bad_input() -> None:
    with pytest.raises(ValueError):
        md.round_loo([], disc(), 0)
    with pytest.raises(ValueError):
        md.round_loo([md.MemberOut(0, "A")], disc(), 0)
    with pytest.raises(ValueError):
        md.round_loo([md.MemberOut(1, "A"), md.MemberOut(1, "B")], disc(), 0)
    with pytest.raises(ValueError):
        md.round_loo(outs_of(["A"]), md.Ctx(family="poll"), 0)


def test_round_loo_is_order_free() -> None:
    """The order of `outs` never matters, even where two members hold the same candidate (long-form duplicates tie
    on the key; the selected member is then the smaller number, never the earlier position)."""
    rng = random.Random(11)
    for _ in range(300):
        family = rng.choice(["discrete", "long_form", "checkable"])
        outs = outs_of([rng.choice(["A", "B", None, "C"]) for _ in range(rng.randint(1, 6))])
        seed = rng.randrange(2**32)
        opts = md.LooOpts(verdicts={o.member: "pass" for o in outs})
        shuffled = outs[:]
        rng.shuffle(shuffled)
        ctx = disc() if family == "discrete" else md.Ctx(family=family)
        assert md.round_loo(outs, ctx, seed, opts=opts) == md.round_loo(shuffled, ctx, seed, opts=opts)
