"""Cap arithmetic: Σ caps <= B by construction, for every arm, family, N, R_max and plan shape."""

from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import ledger

FLAGS = eh.DEFAULT_FLAGS
BS = ["0.01", "0.50", "1.00", "2.00", "2.37", "3.333333", "4.00", "9.99"]


@pytest.mark.parametrize("b_usd", BS)
def test_e_caps_sum_le_b(b_usd: str) -> None:
    b = eh.usd_to_micro(b_usd)
    for fam in FLAGS["families"]:
        for n in (3, 5, 7):
            for r_max in (1, 2):
                plan = eh.caps_enode(b, fam, n, r_max, FLAGS)
                assert plan.total() <= b, (fam, n, r_max)
                assert all(c >= 0 for v in plan.calls.values() for c in v)


def test_e_caps_match_proposal_table() -> None:
    b = eh.usd_to_micro("2.00")
    want = {"discrete": (0.14, "reconcile", 0.05), "numeric": (0.14, "reconcile", 0.05),
            "checkable": (0.16, "repair", 0.04), "finding_set": (0.14, "verifier", 0.05),
            "long_form": (0.15, "selection", 0.10)}
    for fam, (m, kind, r) in want.items():
        plan = eh.caps_enode(b, fam, 5, 1, FLAGS)
        assert plan.calls["member"] == [round(m * b)] * 5
        assert set(plan.calls[kind]) == {round(r * b)}
    assert eh.caps_enode(b, "finding_set", 5, 1, FLAGS).calls["verifier"] == [100_000] * 5
    assert eh.caps_enode(b, "long_form", 5, 1, FLAGS).calls["selection"] == [200_000] * 2


@pytest.mark.parametrize("b_usd", BS)
def test_g_and_eg_caps_sum_le_b(b_usd: str) -> None:
    b = eh.usd_to_micro(b_usd)
    rng = random.Random(b)
    for _ in range(300):
        k = rng.randint(1, 8)
        w = [rng.choice([rng.random() * 10, 1e-9, 1e9, 0.0, float("nan")]) for _ in range(k)]
        g = eh.caps_g(b, w, FLAGS)
        assert g.total() <= b
        assert all(c >= eh.frac_of(b, "0.05") for c in g.calls["node"])
        eg = eh.caps_eg(b, w, FLAGS)
        assert eg.total() <= b
        assert all(c >= eh.frac_of(b, "0.05") for c in eg.calls["node"])
        # an E-node inside EG splits its own node cap
        for c in eg.calls["node"]:
            for fam in ("checkable", "finding_set"):
                assert eh.caps_enode(c, fam, 3, 1, FLAGS).total() <= c


def test_micro_formatting_never_rounds_up() -> None:
    assert eh.micro_to_str(1) == "0.000001" and eh.micro_to_str(2_000_000) == "2.000000"
    assert eh.usd_to_micro("0.0000019") == 1
    assert eh.frac_of(eh.usd_to_micro("2.37"), "0.15") == 355500


def test_ledger_caps_per_item_arm_le_b(full_run: Path) -> None:
    recs = ledger(full_run)
    tot: dict[tuple[str, str], int] = defaultdict(int)
    for r in (x for x in recs if x["record"] == "call"):
        cap = eh.usd_to_micro(r["cap_usd"])
        argv_cap = r["argv"][r["argv"].index("--max-budget-usd") + 1]
        assert argv_cap == r["cap_usd"]
        for lab in r["charged_to"]:
            tot[(r["item"], lab)] += cap
    arms = {(r["item"], r["label"]) for r in recs if r["record"] == "item_arm"}
    assert arms and set(tot) <= arms
    for k, v in tot.items():
        assert v <= eh.usd_to_micro(eh.DEFAULT_FLAGS["B_usd"][k[0][:2]]), k
