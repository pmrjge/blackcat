"""Perm views (Latin-square balance), exact k-cover counts, lens assignment, view seeds."""

from __future__ import annotations

import hashlib
from collections import Counter
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import HARNESS, ITEMS


def test_perm_latin_square_when_n_equals_s() -> None:
    for s in range(2, 13):
        rows = [eh.perm_order(s, s, i) for i in range(s)]
        for r in rows:
            assert sorted(r) == list(range(s))  # each view is a permutation
        for p in range(s):
            assert sorted(r[p] for r in rows) == list(range(s))  # each position holds every segment once


@pytest.mark.parametrize("s", list(range(5, 41)))
def test_perm_balance_n5_default_rule(s: int) -> None:
    """N = 5, default rule (flags.json and the function default): every segment sits at 5 distinct positions."""
    rule = eh.DEFAULT_FLAGS["perm_shift_rule"]
    for rows in ([eh.perm_order(s, 5, i, rule) for i in range(5)], [eh.perm_order(s, 5, i) for i in range(5)]):
        assert len({tuple(r) for r in rows}) == 5
        for seg in range(s):
            assert len({r.index(seg) for r in rows}) == 5
    assert not eh.perm_collisions(s, 5, rule) and not eh.perm_collisions(s, 5)


@pytest.mark.parametrize("s", [6, 8, 12, 16])
def test_perm_no_collision_where_ceil_collided(s: int) -> None:
    """The S values where the drafts' i*ceil(S/N) gave two members one order: the adopted rule separates them."""
    rule = eh.DEFAULT_FLAGS["perm_shift_rule"]
    assert rule == "floor"
    shifts = [eh.perm_shift(i, s, 5, rule) for i in range(5)]
    assert shifts == [i * s // 5 for i in range(5)] and len(set(shifts)) == 5
    item = eh.Item("CR-X", "CR", True, "finding_set", "p", tuple(eh.Segment(f"s{k}", None, "t") for k in range(s)),
                   None, None, None, (), Path("."))
    views = [eh.member_view(item, "perm", 5, i, f"m{i + 1}", [], None, rule) for i in range(5)]
    assert len({v.order for v in views}) == 5 and not any("collision" in v.note for v in views)


def test_perm_ceil_rule_collides_where_documented() -> None:
    """The drafts' i*ceil(S/N) collides for some S >= N (why it was replaced); floor never does for N <= S."""
    assert [s for s in range(5, 41) if eh.perm_collisions(s, 5, "ceil")] == [6, 8, 12, 16]
    assert not any(eh.perm_collisions(s, n, "floor") for n in range(2, 9) for s in range(1, 41))
    assert all(len({eh.perm_shift(i, s, n) for i in range(n)}) == min(s, n) for n in (3, 5) for s in range(1, 41))


@pytest.mark.parametrize("s", list(range(4, 41)))
def test_kcover_exact_counts(s: int) -> None:
    """Every segment is seen by exactly k = 2 partial members plus the full member (member 5)."""
    seen: Counter[int] = Counter()
    for i in range(4):
        order, blocks = eh.kcover_order(s, i)
        assert blocks is not None and len(blocks) == 2 and order
        assert len(order) == len(set(order))
        seen.update(order)
    assert all(seen[g] == 2 for g in range(s)) and set(seen) == set(range(s))
    full, b = eh.kcover_order(s, 4)
    assert b is None and full == list(range(s))
    sizes = [len(x) for x in eh.kcover_blocks(s)]
    assert sum(sizes) == s and max(sizes) - min(sizes) <= 1


def test_kcover_requires_n5() -> None:
    with pytest.raises(ValueError):
        eh.kcover_order(8, 0, n=3)


def test_view_seed_formula() -> None:
    for item, m in [("CR-0001", "m1"), ("PF-DEV2", "n3|m2"), ("ES-0100", "plan|m2")]:
        want = 2742449181 ^ int(hashlib.sha256(f"{item}|{m}".encode()).hexdigest()[:8], 16)
        assert eh.view_seed(item, m) == want


def test_lens_assignment_is_a_permutation_and_seeded() -> None:
    keys = [f"m{i}" for i in range(1, 6)]
    for item in ("PF-0001", "PF-0002", "RS-DEV1"):
        la = eh.lens_assignment(item, keys)
        assert sorted(la.values()) == [0, 1, 2, 3, 4]
        assert la == eh.lens_assignment(item, list(reversed(keys)))
    assert len({tuple(eh.lens_assignment(f"PF-{k:04d}", keys)[m] for m in keys) for k in range(30)}) > 5


def test_member_views_on_fixture_item() -> None:
    item = next(it for it in eh.load_pool(ITEMS, "CR") if it.id == "CR-DEV1")
    lenses = [f"lens {i}" for i in range(5)]
    keys = [f"m{i + 1}" for i in range(5)]
    la = eh.lens_assignment(item.id, keys)
    views = [eh.member_view(item, "kcover", 5, i, keys[i], lenses, la[keys[i]]) for i in range(5)]
    assert [v.full for v in views] == [False, False, False, False, True]
    assert sorted(v.lens_index for v in views if v.lens_index is not None) == [0, 1, 2, 3, 4]
    assert all(v.seed == eh.view_seed(item.id, v.member_key) for v in views)
    pviews = [eh.member_view(item, "perm", 5, i, keys[i], lenses, la[keys[i]]) for i in range(5)]
    for p in range(5):  # S = N = 5: Latin square over the real item
        assert sorted(v.order[p] for v in pviews) == list(range(5))


def test_kcover_member_copies_hide_unseen_files(full_run: Path) -> None:
    item = next(it for it in eh.load_pool(ITEMS, "CR") if it.id == "CR-DEV1")
    (work,) = (full_run / "raw" / "d" / "CR-DEV1" / "p3").glob("*/work/E")
    present: Counter[str] = Counter()
    for i in range(1, 6):
        files = {p.name for p in (work / f"m{i}").glob("f*.py")}
        if i == 5:
            assert files == {sg.path for sg in item.segments}
        present.update(files)
    pinned = {q for k in item.pinned_segments if (q := item.segments[k].path) is not None}
    assert pinned and all(present[q] == 5 for q in pinned)  # pinned source modules: in every copy
    assert all(present[sg.path] == 3 for sg in item.segments if sg.path and sg.path not in pinned)  # 2 + full


@pytest.mark.parametrize(("s", "pinned"), [(4, (0, 1)), (4, (1, 3)), (4, (2, 0)), (5, (0, 1)), (6, (3,)),
                                           (9, (0, 4, 8)), (3, (1,)), (2, (0,))])
def test_kcover_pinned_in_every_view(s: int, pinned: tuple[int, ...]) -> None:
    """CR: the pinned source segments are in every partial view; only the others are split (k = 2 + full)."""
    seen: Counter[int] = Counter()
    for i in range(4):
        order, blocks = eh.kcover_order(s, i, pinned=pinned)
        assert set(pinned) <= set(order) and blocks is not None and order == sorted(order)
        seen.update(order)
    free = [k for k in range(s) if k not in pinned]
    assert all(seen[k] == 4 for k in pinned) and all(seen[k] == 2 for k in free)
    assert eh.kcover_order(s, 4, pinned=pinned) == (list(range(s)), None)
    with pytest.raises(ValueError):
        eh.kcover_order(s, 0, pinned=(s,))


def test_real_cr_pool_views_keep_both_sources() -> None:
    """On the CR pool's own manifests (when present): every member view holds both source modules."""
    pool = HARNESS.parent / "items" / "CR" / "manifest.jsonl"
    if not pool.exists():
        pytest.skip("CR pool not present")
    items = eh.load_pool(pool.parent.parent, "CR")
    assert items and all(len(it.pinned_segments) == 2 for it in items)
    for it in items[:40]:
        assert [it.segment_roles[k] for k in it.pinned_segments] == ["source", "source"]
        for i in range(5):
            v = eh.member_view(it, "kcover", 5, i, f"m{i + 1}", [], None)
            assert v.kind == "kcover" and set(it.pinned_segments) <= set(v.order)


def test_parse_item_rejects_bad_pins() -> None:
    base = {"id": "CR-X", "class": "CR", "answer_kind": "finding_set", "prompt": "p",
            "segments": [{"id": "a", "text": "x"}, {"id": "b", "text": "y"}]}
    assert eh.parse_item({**base, "pinned_segments": [1], "segment_roles": ["test", "source"]}, Path(".")) \
        .pinned_segments == (1,)
    for bad in ({"pinned_segments": [2]}, {"segment_roles": ["source"]},
                {"pinned_segments": [0], "segment_roles": ["test", "source"]}):
        with pytest.raises(ValueError):
            eh.parse_item({**base, **bad}, Path("."))
