"""Quorum rules (pre-registered tau and the ceil(2N/3) option), seeds vs COMPARE_eq §8.4 / seeds.out, schedule."""

from __future__ import annotations

import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

import eq_harness as eh
from conftest import HARNESS, STAGE, run_harness, stub_env


@pytest.mark.parametrize("n", list(range(1, 16)))
def test_quorum_tau_is_ceil_tau_n(n: int) -> None:
    assert eh.quorum(n, "tau", "0.6") == math.ceil(Fraction(3, 5) * n)


def test_quorum_values() -> None:
    assert eh.quorum(5, "tau", "0.6") == 3 and eh.quorum(3, "tau", "0.6") == 2
    assert [eh.quorum(n, "two_thirds") for n in (1, 2, 3, 4, 5, 6, 7, 9)] == [1, 2, 2, 3, 4, 4, 5, 6]
    assert all(eh.quorum(n, "two_thirds") == math.ceil(2 * n / 3) for n in range(1, 50))
    assert eh.quorum(5, "fixed_t", t=2) == 2
    for bad in (("tau", "0"), ("tau", "1.5")):
        with pytest.raises(ValueError):
            eh.quorum(5, bad[0], bad[1])
    with pytest.raises(ValueError):
        eh.quorum(5, "majority")


def test_flags_defaults_are_preregistered() -> None:
    disk = json.loads((HARNESS / "flags.json").read_text())
    strip = lambda f: {k: v for k, v in f.items() if k != "allowed_tools"}  # noqa: E731  (pool-owned, `flags --items`)
    assert strip(disk) == strip(eh.DEFAULT_FLAGS) and set(disk["allowed_tools"]) == set(eh.CLASSES)
    assert disk["stop_quorum_rule"] == "tau" and disk["tau"] == "0.6" and disk["finding_t"] == 2
    assert eh.stop_quorum(5, disk) == 3 and eh.finding_quorum(5, disk) == 2 and eh.finding_quorum(3, disk) == 2
    alt = dict(disk, stop_quorum_rule="two_thirds", finding_quorum_rule="two_thirds")
    assert eh.stop_quorum(5, alt) == 4 and eh.finding_quorum(5, alt) == 4


def test_seeds_match_seeds_out_and_formula() -> None:
    rows = [ln.split("\t") for ln in (STAGE / "seeds.out").read_text().splitlines() if ln.strip()]
    assert len(rows) == 17
    for tag, val in rows:
        indep = 20261004 ^ int(hashlib.sha256(tag.encode()).hexdigest()[:8], 16)
        assert eh.seed_for(tag) == int(val) == indep
    assert (eh.SEED_ORDER, eh.SEED_ITEMS, eh.SEED_VIEWS, eh.SEED_TIES) == (3167602700, 3725927731, 2742449181,
                                                                         366605965)
    assert (eh.SEED_GRADER, eh.SEED_REGRADE, eh.SEED_RECONCILE) == (3808915453, 779827486, 3724266183)


def test_seeds_subcommand_prints_seeds_out(stub_bin: Path, tmp_path: Path) -> None:
    cp = run_harness(["seeds"], stub_env(stub_bin, tmp_path))
    assert cp.returncode == 0
    assert set(cp.stdout.splitlines()) == set((STAGE / "seeds.out").read_text().splitlines())


def _pool(cls: str, n: int, dev: int = 3) -> list[eh.Item]:
    mk = lambda i, d: eh.Item(i, cls, d, "discrete", "p", (), None, None, None, (), Path("."))  # noqa: E731
    return [mk(f"{cls}-{k:04d}", False) for k in range(1, n + 1)] + [mk(f"{cls}-DEV{k}", True) for k in
                                                                        range(1, dev + 1)]


def test_draw_order_and_schedule_reproducible() -> None:
    ids = [f"PF-{k:04d}" for k in range(180, 0, -1)]
    perm = np.random.default_rng(3725927731).permutation(180)
    assert eh.draw_order(ids) == [sorted(ids)[int(k)] for k in perm]
    pools = {c: _pool(c, 12) for c in eh.CLASSES}
    items = eh.stage_items(pools, "p")
    assert len(items) == 60 and sum(i.startswith(("CP", "CR")) for i in items) == 10
    rows = eh.build_schedule(items, "p")
    assert rows == eh.build_schedule(items, "p") and len(rows) == 240
    rng = np.random.default_rng(3167602700)
    order = [items[int(k)] for k in rng.permutation(len(items))]
    arms0 = [eh.ARMS[int(a)] for a in rng.permutation(4)]
    assert [r.item for r in rows[::4]] == order and [r.arm for r in rows[:4]] == arms0
    for k in range(60):
        blk = rows[4 * k: 4 * k + 4]
        assert sorted(r.label for r in blk) == ["p1", "p2", "p3", "p4"] and len({r.item for r in blk}) == 1
    with pytest.raises(ValueError):
        eh.stage_items({c: _pool(c, 4) for c in eh.CLASSES}, "p")


def test_schedule_tsv_roundtrip(tmp_path: Path) -> None:
    rows = eh.build_schedule(eh.stage_items({c: _pool(c, 0) for c in eh.CLASSES}, "d"), "d")
    eh.write_schedule(rows, tmp_path / "s.tsv")
    assert eh.read_schedule(tmp_path / "s.tsv") == rows and len(rows) == 84
