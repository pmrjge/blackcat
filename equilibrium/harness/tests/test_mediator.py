"""eq_mediator (MEDIATOR.md §7 tests): order-free R0-R3/ENS/Shapley, efficiency, the A,A,A,B,C and Borda IIA examples,
verify() safety (allow-list, fresh copies, timeout, minimal env), fact dedupe and budget, decisive facts."""

from __future__ import annotations

import ast
import inspect
import itertools
import os
import random
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

import eq_harness as eh
import eq_mediator as md
from conftest import HARNESS

V, R, U = md.VERIFIED, md.REFUTED, md.UNVERIFIABLE


def disc(seed: int = 0) -> md.Ctx:
    return md.Ctx(family="discrete", tie_seed=seed)


def outs_of(answers: list, facts: list[tuple[str, ...]] | None = None, lens: list[int] | None = None,
            kinds: str = "quote") -> list[md.MemberOut]:
    facts = facts or [()] * len(answers)
    return [md.MemberOut(i + 1, a, f, (kinds,) * len(f), None if lens is None else lens[i])
            for i, (a, f) in enumerate(zip(answers, facts, strict=True))]


# ---- Shapley ----------


def lexicographic_seed() -> int:
    """A tie seed whose 2- and 3-way choice is the first sorted candidate (= the lexicographic rule of MEDIATOR §2)."""
    for s in range(1000):
        if all(int(np.random.default_rng(s).integers(k)) == 0 for k in (2, 3)):
            return s
    raise AssertionError


def test_shapley_aaabc_example() -> None:
    ctx = disc(lexicographic_seed())
    outs = outs_of(["A", "A", "A", "B", "C"])
    final = md.reduce_r0(outs, ctx)
    assert final == "A"
    phi = md.shapley([o.member for o in outs], md.agreement_game(outs, ctx, final))
    assert [phi[m] for m in range(1, 6)] == [Fraction(1, 3)] * 3 + [Fraction(0)] * 2
    assert md.hhi(phi) == Fraction(1, 3)


@pytest.mark.parametrize("seed", range(20))
def test_shapley_efficiency_symmetry_any_tie_seed(seed: int) -> None:
    ctx = disc(seed)
    outs = outs_of(["A", "A", "A", "B", "C"])
    final = md.reduce_r0(outs, ctx)
    phi = md.shapley([1, 2, 3, 4, 5], md.agreement_game(outs, ctx, final))
    assert sum(phi.values()) == 1 and phi[1] == phi[2] == phi[3]


def test_shapley_sums_to_v_full_minus_v_empty() -> None:
    rng = random.Random(3)
    for n in (1, 2, 3, 5):
        table = {frozenset(c): Fraction(rng.randint(-5, 9), rng.randint(1, 4))
                 for r in range(n + 1) for c in itertools.combinations(range(1, n + 1), r)}
        phi = md.shapley(list(range(1, n + 1)), lambda s, t=table: t[s])
        assert sum(phi.values()) == table[frozenset(range(1, n + 1))] - table[frozenset()]


def test_borda_iia_example() -> None:
    x, y, z = 0, 1, 2
    rankings = [[x, y, z], [y, z, x]]
    w, scores = eh.borda(rankings, 3, 0)
    assert w == y and scores == [2, 3, 1]
    _, scores2 = eh.borda([[c for c in r if c != z] for r in rankings], 2, 0)
    assert scores2 == [1, 1]  # removing the non-winner z leaves x and y tied (IIA fails)


# ---- reducers ----------


def _random_case(rng: random.Random, family: str) -> tuple[list[md.MemberOut], dict[str, str]]:
    keys = [f"f{k}" for k in range(6)]
    status = {k: rng.choice([V, R, U]) for k in keys}
    outs = []
    for m in range(1, 6):
        if family == "numeric":
            a: object = rng.choice([10.0, 20.0, 40.0, 400.0, None])
        elif family == "finding_set":
            a = [{"file": rng.choice(["a.py", "b.py"]), "line": rng.randint(1, 12), "claim": "x"}
                 for _ in range(rng.randint(0, 3))]
        else:
            a = rng.choice(["Y1", "Y2", "Y3", None])
        f = tuple(rng.sample(keys, rng.randint(0, 4)))
        if family == "finding_set":
            f = tuple(f"file_line|{rng.choice(['a.py', 'b.py'])}|{rng.randint(1, 12)}|{k}" for k in f)
            status.update({k: rng.choice([V, R]) for k in f})
        outs.append(md.MemberOut(m, a, f, ("file_line",) * len(f), rng.randint(0, 4)))
    return outs, status


@pytest.mark.parametrize("family", ["discrete", "numeric", "finding_set"])
def test_reducers_and_shapley_order_free(family: str) -> None:
    rng = random.Random(11)
    for case in range(40):
        outs, status = _random_case(rng, family)
        ctx = md.Ctx(family=family, tie_seed=case)
        weights = {lens: rng.choice([0.0, 1.0, 1.0, 2.0]) for lens in range(5)}
        ref = md.all_reducers(outs, ctx, status, weights)
        final = ref["R0"]
        phi = md.shapley([o.member for o in outs], md.agreement_game(outs, ctx, final))
        for _ in range(6):
            sh = list(outs)
            rng.shuffle(sh)
            assert md.all_reducers(sh, ctx, status, weights) == ref
            assert md.shapley([o.member for o in sh], md.agreement_game(sh, ctx, final)) == phi


def test_r1_veto() -> None:
    ctx = disc(0)
    outs = outs_of(["Y1", "Y1", "Y2", "Y2", "Y2"], [("bad",), ("bad",), (), (), ()])
    assert md.reduce_r0(outs, ctx) == "Y2"
    outs2 = outs_of(["Y1", "Y1", "Y1", "Y2", "Y2"], [("bad",), ("bad",), (), (), ()])
    assert md.reduce_r1(outs2, ctx, {"bad": R}) == "Y2"  # Y1 voters 1-2 vetoed: Y2 (2) beats Y1 (1)
    assert md.reduce_r1(outs2, ctx, {"bad": V}) == md.reduce_r0(outs2, ctx) == "Y1"
    everyone = outs_of(["Y1", "Y2"], [("bad",), ("bad",)])
    assert md.reduce_r1(everyone, ctx, {"bad": R}) == md.reduce_r0(everyone, ctx)


def test_r3_facts_only_cap_and_kinds() -> None:
    ctx = md.Ctx(family="discrete", fact_kinds=frozenset({"quote"}))
    st = {f"k{i}": V for i in range(10)}
    # R3 scores a cluster by its MEMBERS with >= 1 verified fact (security review M9: padding counts once)
    outs = outs_of(["Y1", "Y1", "Y1", "Y2", "Y2"], [(), (), (), ("k1",), ("k2",)])
    assert md.reduce_r0(outs, ctx) == "Y1" and md.reduce_r3(outs, ctx, st) == "Y2"
    pad = outs_of(["Y1", "Y2", "Y2", "Y3", "Y1"], [(), ("k1",), ("k1",), ("k2", "k3", "k4"), ()])
    assert md.reduce_r3(pad, ctx, st) == "Y2"  # 2 members beat 1 member with 3 facts
    tie = outs_of(["Y1", "Y1", "Y1", "Y2", "Y3"], [(), (), (), ("k1",), ("k3", "k4")])
    assert md.reduce_r3(tie, ctx, st) == "Y1"  # 1 member each in Y2 and Y3 -> R0
    assert md.reduce_r3(outs_of(["Y1", "Y2"]), ctx, st) == md.reduce_r0(outs_of(["Y1", "Y2"]), ctx)  # zero facts
    spam = outs_of(["Y1", "Y1", "Y2", "Y3", "Y1"], [(), (), ("x1", "x2", "x3", "k4"), ("k5",), ()])
    st2 = {**st, "x1": R, "x2": R, "x3": R}
    assert md.reduce_r3(spam, ctx, st2) == "Y3"  # Y2's only verified fact is 4th: over the cap of 3 (uncapped: tie)
    wrong_kind = outs_of(["Y1", "Y1", "Y2"], [(), (), ("k1", "k2")], kinds="command")
    assert md.reduce_r3(wrong_kind, ctx, st) == "Y1"


def test_r2_and_ens() -> None:
    ctx = disc(0)
    outs = outs_of(["Y1", "Y1", "Y1", "Y2", "Y2"], lens=[0, 1, 2, 3, 4])
    assert md.reduce_r2(outs, ctx, None) == md.reduce_r0(outs, ctx) == "Y1"
    assert md.reduce_r2(outs, ctx, {0: 0.1, 1: 0.1, 2: 0.1, 3: 2.0, 4: 2.0}) == "Y2"
    assert md.reduce_r2(outs, ctx, {k: -1.0 for k in range(5)}) == "Y1"  # all clipped to 0 -> R0
    assert md.ens("A", "R1", "B", "A", ctx) == "A"
    assert md.ens("A", "R1", "B", "C", ctx) == "R1"
    num = md.Ctx(family="numeric")
    assert md.ens(10.0, 1.0, 1000.0, 20.0, num) == 20.0
    assert md.lens_log_odds(9, 10) == pytest.approx(np.log(10 / 2))


def test_ens_findings_two_of_three() -> None:
    ctx = md.Ctx(family="finding_set")
    a = md.FindingRef("a.py", "", 10, 10, '{"x": 1}')
    b = md.FindingRef("b.py", "", 3, 3, '{"x": 2}')
    a2 = md.FindingRef("a.py", "", 12, 12, '{"x": 3}')
    assert md.ens((a,), (), (a2, b), (b,), ctx) == (a, b)


def test_loo_and_decisive_facts() -> None:
    ctx = disc(0)
    r0 = outs_of(["Y2", "Y2", "Y1", "Y1", "Y1"], [("k1",), (), (), (), ()])
    final = outs_of(["Y2", "Y2", "Y2", "Y1", "Y1"], [("k1",), (), (), (), ()])
    lo = md.loo([1, 2, 3, 4, 5], lambda s: md.reduce_r0([final[m - 1] for m in s], ctx))
    assert set(lo) == {1, 2, 3, 4, 5} and lo[4] == lo[5] == "Y2"
    changes = [{"member": 3, "gate": "evidence", "new_fact_keys": ["k1"], "prev_answer": "Y1"},
               {"member": 2, "gate": "conformity", "new_fact_keys": ["k1"], "prev_answer": "Y1"}]
    dec = md.decisive_facts(r0, final, ctx, {"k1": V}, changes)
    assert dec["reconcile"] == ["k1"]  # reverting m3's evidence-gated change turns Y2 (3:2) into Y1 (3:2)
    assert dec["R3"] == ["k1"] and dec["R1"] == []  # R3 at round 0 is Y2 only because of k1
    assert md.decisive_facts(r0, final, ctx, {"k1": V}, changes[1:])["reconcile"] == []  # conformity: not counted


# ---- facts and verify() ----------


@pytest.fixture
def fx(tmp_path: Path) -> Path:
    d = tmp_path / "fixture"
    d.mkdir()
    (d / "a.py").write_text("line one\nline two\nline three\n")
    (d / "count.sh").write_text("n=$(cat n 2>/dev/null || echo 0); n=$((n+1)); echo $n > n; echo count=$n\n")
    (d / "env.sh").write_text('echo "secret=${EQ_TEST_SECRET:-none}"\n')
    (d / "slow.sh").write_text("sleep 5\n")
    return d


def ev(kind: str, ref: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref, "detail": detail}


def test_verify_files_and_urls(fx: Path) -> None:
    assert md.verify(ev("file_line", "a.py:2", "line three"), fx)[0] == V  # window l-1..l+1
    assert md.verify(ev("file_line", "a.py:1", "line three"), fx)[0] == R
    assert md.verify(ev("file_line", "a.py:9", "x"), fx)[0] == R
    assert md.verify(ev("file_line", "../x.py:1", "x"), fx)[0] == R
    assert md.verify(ev("quote", "a.py", "line   two"), fx)[0] == V
    assert md.verify(ev("quote", "nope.txt", "x"), fx)[0] == R
    assert md.verify(ev("quote", "https://example.org/a", "x"), fx)[0] == U
    assert md.verify(ev("counterexample", "n=7", ""), fx)[0] == U
    assert md.verify(ev("counterexample", "n=7", ""), fx, checker=lambda e: True)[0] == V

    def boom(e: object) -> bool:
        raise RuntimeError

    assert md.verify(ev("counterexample", "n=7", ""), fx, checker=boom)[0] == U


def test_verify_refuses_non_allow_listed(fx: Path, tmp_path: Path) -> None:
    marker = tmp_path / "ran"
    st, method, _ = md.verify(ev("command", f"touch {marker}", "exit 0"), fx, public_check=["sh", "count.sh"])
    assert (st, method) == (U, "not allow-listed") and not marker.exists()
    st, _, _ = md.verify(ev("command", f"sh count.sh; touch {marker}", "exit 0"), fx, public_check=["sh", "count.sh"])
    assert st == U and not marker.exists()


def test_verify_runs_twice_in_fresh_copies(fx: Path, tmp_path: Path) -> None:
    st, method, out = md.verify(ev("command", "sh count.sh", "count=1"), fx, public_check=["sh", "count.sh"],
                                scratch=tmp_path)
    assert st == V and out is not None and method.startswith("re-run twice")
    assert not (fx / "n").exists()  # the pristine fixture is untouched
    assert md.verify(ev("command", "sh count.sh", "exit 3"), fx, public_check=["sh", "count.sh"])[0] == R
    assert list(tmp_path.glob("eqfact*")) == []  # copies removed


def test_verify_minimal_env_and_timeout(fx: Path) -> None:
    os.environ["EQ_TEST_SECRET"] = "leak"  # noqa: S105
    try:
        st, _, _ = md.verify(ev("command", "sh env.sh", "secret=none"), fx, allowed_prefixes=[["sh", "env.sh"]])
        assert st == V
    finally:
        del os.environ["EQ_TEST_SECRET"]
    assert inspect.signature(md.verify).parameters["timeout_s"].default == 60.0
    assert inspect.signature(md.FactChecker).parameters["timeout_s"].default == 60.0
    st, method, _ = md.verify(ev("command", "sh slow.sh", "exit 0"), fx, public_check=["sh", "slow.sh"],
                              timeout_s=0.3)
    assert st == U and method.startswith("timeout")


def test_fact_checker_dedupe_and_budget(fx: Path) -> None:
    calls = []

    def chk(e: object) -> bool:
        calls.append(e)
        return True

    ck = md.FactChecker(fx, "fx", checker=chk)
    f1 = ck.check(ev("counterexample", "n = 7", "x"))
    f2 = ck.check(ev("counterexample", "n =   7", " x "))
    assert f1 is f2 and len(calls) == 1
    t = [0.0]

    def slow(e: object) -> bool:  # 6 s of checking per counterexample (fake clock)
        t[0] += 6.0
        return True

    ck2 = md.FactChecker(fx, "fx", budget_s=10, clock=lambda: t[0], checker=slow)
    assert ck2.check(ev("counterexample", "a", "")).status == V
    t[0] += 1000.0  # model calls between checks: not counted (security review H3)
    assert ck2.check(ev("counterexample", "b", "")).status == V and ck2.spent == 12.0
    late = ck2.check(ev("quote", "a.py", "line two"))
    assert late.status == U and late.method == "wall-time budget exhausted"


def test_mediator_has_no_shell() -> None:
    tree = ast.parse((HARNESS / "eq_mediator.py").read_text())
    n_run = 0
    for c in (x for x in ast.walk(tree) if isinstance(x, ast.Call)):
        name = c.func.attr if isinstance(c.func, ast.Attribute) else getattr(c.func, "id", "")
        assert name not in {"system", "popen", "getoutput", "getstatusoutput"}
        for kw in c.keywords:
            if kw.arg == "shell":
                assert isinstance(kw.value, ast.Constant) and kw.value.value is False
        assert not (isinstance(c.func, ast.Attribute) and getattr(c.func.value, "id", "") == "subprocess")
        if name == "run_bounded":  # the only process launch: argv, own session, bounded output, group kill
            n_run += 1
    assert n_run == 1


def test_equivalence_mapping() -> None:
    keys = ['{"label":"REFUTED","value":"paris"}', '{"label":"REFUTED","value":"paris, france"}',
            '{"label":"SUPPORTED"}']
    m = eh.equivalence_mapping(keys, [[0, 1], [2]], ["label"])
    assert m == {keys[0]: keys[0], keys[1]: keys[0], keys[2]: keys[2]}
    assert eh.equivalence_mapping(keys, [[0, 2], [1]], ["label"]) is None  # mixes labels
    assert eh.equivalence_mapping(keys, [[0, 1]], ["label"]) is None  # not a partition
    assert eh.equivalence_mapping(keys, [[0, 1], [1, 2]], []) is None
    assert eh.equivalence_mapping(keys, "x", []) is None
    plan = eh.caps_enode(eh.usd_to_micro("2.00"), "discrete", 5, 1, eh.DEFAULT_FLAGS, "0.05")
    assert plan.calls["equivalence"] == [100_000] and plan.calls["reconcile"] == [80_000] * 5
    assert plan.total() <= eh.usd_to_micro("2.00")
