"""Route 1 (eq_analyse.py) on a tiny hand-built run dir: one hand-computed value per quantity family, Holm, the
statistics helpers, results.csv sort/format, determinism, and clean failure on empty/partial/missing input.

Run from STAGE (duckdb for the cross-route tests, which run route 2 on the same fixtures; they skip without it):
uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py pytest -q \
    -p no:cacheprovider harness/tests/test_eq_analyse.py
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))

import eq_analyse as ea  # noqa: E402

LABEL = {"S*": "p1", "G": "p2", "E": "p3", "EG": "p4"}

# ---------------------------------------------------------------------------------------------------------------------
# the tiny run dir
#   PF-1..PF-5 (binary) and ES-1, ES-2; ES-3 E is interrupted (calls, no item_arm)
#   scores:  PF  E  = 1 1 1 1 0   S* = 0 0 1 1 0   G = 0 0 0 0 0   EG = 1 1 1 1 1
#            ES  E  = 0.05 inf    S* = 0.5 0.2     G = 0.1 inf     EG = 0.3 0.15
#   tokens:  S* 100 per item; E: PF 200 400 800 100 50, ES 300 25 (two calls each); G and EG share a 60-token planner
#   wall:    S* 10 s, E 20 s, G 5 s, EG 5 s.   USD: S* 0.1, E 0.2 (ES S*: 2.3 and 2.2, both caps 2.000000)
# ---------------------------------------------------------------------------------------------------------------------

PF_SCORES = {"E": [1, 1, 1, 1, 0], "S*": [0, 0, 1, 1, 0], "G": [0, 0, 0, 0, 0], "EG": [1, 1, 1, 1, 1]}
ES_SCORES = {"E": [0.05, math.inf], "S*": [0.5, 0.2], "G": [0.1, math.inf], "EG": [0.3, 0.15]}
E_TOKENS = {"PF-1": 200, "PF-2": 400, "PF-3": 800, "PF-4": 100, "PF-5": 50, "ES-1": 300, "ES-2": 25}
E_KAPPA0 = {"PF-1": 1.0, "PF-2": 0.8, "PF-3": 0.6, "PF-4": 0.6, "PF-5": 0.6, "ES-1": 0.4, "ES-2": 1.0}
WALL = {"S*": 10, "E": 20, "G": 5, "EG": 5}


class Ledger:
    def __init__(self) -> None:
        self.recs: list[dict[str, Any]] = []
        self.n_calls = 0

    def add(self, record: str, **kw: Any) -> dict[str, Any]:
        r = {"schema_version": 1, "seq": len(self.recs) + 1, "ts_utc": "2026-10-05T12:00:00.000000Z",
             "record": record, "stage": "d", **kw}
        self.recs.append(r)
        return r

    def call(self, item: str, arm: str, role: str, tokens: int, cost: float | None = 0.01, cap: str = "2.000000",
             charged: list[str] | None = None, cap_stop: bool = False, member: int | None = None,
             label: str | None = None) -> str:
        self.n_calls += 1
        cid = f"{self.n_calls:05d}_{role.replace('/', 'of')}"
        lab = label or LABEL[arm]
        self.add("call", call_id=cid, run_tag="t", item=item, cls=item.split("-")[0], label=lab, arm=arm,
                 charged_to=charged or [lab], role=role, member=member, node=None, round=0, cap_usd=cap,
                 total_cost_usd=cost, cap_stop=cap_stop, is_error=False, subtype="success",
                 usage={"input_tokens": tokens // 2, "cache_creation_input_tokens": tokens // 4,
                        "cache_read_input_tokens": tokens // 8,
                        "output_tokens": tokens - tokens // 2 - tokens // 4 - tokens // 8})
        return cid

    def item_arm(self, item: str, arm: str, status: str = "ok", kappa0: float | None = None) -> None:
        self.add("item_arm", item=item, cls=item.split("-")[0], label=LABEL[arm], arm=arm, run_tag="t",
                 status=status, answer=None, B_usd="2.00", started_utc="2026-10-05T12:00:00.000000Z",
                 ended_utc=f"2026-10-05T12:00:{WALL[arm]:02d}.000000Z", calls=[], kappa0=kappa0)


def build(root: Path) -> Path:
    run = root / "run"
    (run / "grading_results").mkdir(parents=True)
    led = Ledger()
    led.add("run_start", stub=True)
    items = [f"PF-{i}" for i in range(1, 6)] + ["ES-1", "ES-2"]
    for it in items:
        es_cost = {"ES-1": 2.3, "ES-2": 2.2}
        led.call(it, "S*", "s", 100, cost=es_cost.get(it, 0.1), cap_stop=(it == "PF-5"))
        led.item_arm(it, "S*")
        led.call(it, "EG", "plan", 60, charged=["p2", "p4"])  # shared planner: arm EG, charged to both
        led.call(it, "G", "n1", 40)
        led.item_arm(it, "G")
        led.call(it, "EG", "n1", 40)
        led.item_arm(it, "EG")
        half = E_TOKENS[it] // 2
        led.call(it, "E", "m1/5", half, cost=0.1, member=1)
        led.call(it, "E", "m2/5", E_TOKENS[it] - half, cost=0.1, member=2)
        if it == "ES-1":
            r1 = [led.call(it, "E", "r1", 1, cost=None, member=m) for m in (1, 2, 3)]
            for cid, (ch, acc, conf) in zip(r1, [(True, True, False), (True, False, True), (False, False, False)],
                                            strict=True):
                led.add("reconcile", round=1, member=1, call_id=cid, changed=ch, accepted=acc, conformity=conf)
            ver = led.call(it, "E", "ver", 1, cost=0.05)
            led.add("reduce", reducer="equivalence", item=it, label="p3", arm="E", node=None, call_id=ver,
                    keys=["a", "b"], groups=[[0, 1]], valid=True)
        led.item_arm(it, "E", kappa0=E_KAPPA0[it])
    led.call("ES-3", "E", "m1/5", 10)  # interrupted: no item_arm
    (run / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in led.recs))
    with (run / "grading_results" / "PF.jsonl").open("w") as f:
        f.write(json.dumps({"item": "PF-1", "label": "p3", "score": 0, "score_num": 0.0}) + "\n")  # superseded
        for arm, sc in PF_SCORES.items():
            for i, s in enumerate(sc, 1):
                f.write(json.dumps({"ts_utc": "x", "item": f"PF-{i}", "label": LABEL[arm], "exit": 0, "score": s,
                                    "score_num": float(s), "score_inf": False}) + "\n")
    with (run / "grading_results" / "ES.jsonl").open("w") as f:
        for arm, sc in ES_SCORES.items():
            for i, s in enumerate(sc, 1):
                inf = math.isinf(s)
                f.write(json.dumps({"item": f"ES-{i}", "label": LABEL[arm], "score": "inf" if inf else s,
                                    "score_num": None if inf else s, "score_inf": inf}) + "\n")
    med = run / "inputs" / "mediator"

    def fr(n: int, d: int) -> dict[str, Any]:
        return {"num": n, "den": d, "float": n / d}

    m1 = [
        {"record": "fact", "fact_key": "k1", "status": "verified"},
        {"record": "fact", "fact_key": "k1", "status": "verified"},  # duplicate key: counted once
        {"record": "fact", "fact_key": "k2", "status": "refuted"},
        {"record": "fact", "fact_key": "k3", "status": "unverifiable"},
        {"record": "change", "member": "m1", "round": 1, "gate": "evidence"},
        {"record": "change", "member": "m2", "round": 1, "gate": "conformity"},
        {"record": "result", "answer": 100.0, "reducers": {"R0": 100.0, "R0_final": 100.0, "R1": 100.0000000001,
                                                           "R2": 100.0, "R3": 120.0, "ENS": 100.0}},
        {"record": "attribution", "shapley": {"m1": fr(1, 3), "m2": fr(1, 3), "m3": fr(1, 3), "m4": fr(0, 1),
                                              "m5": fr(0, 1)}, "hhi": fr(1, 3), "cpu_s": 0.5,
         "decisive_facts": {"reconcile": ["k1"], "R1": [], "R3": []},
         "loo_round0": {str(i): 100.0 for i in range(1, 6)}, "loo_final": {"1": 90.0, "2": 100.0}},
    ]
    m2 = [
        {"record": "result", "answer": 50.0, "reducers": {"R0": 50.0, "R1": 50.0, "R2": 50.0, "R3": 50.0,
                                                          "ENS": 50.0}},
        {"record": "attribution", "shapley": {"m1": fr(3, 5), **{f"m{i}": fr(1, 10) for i in range(2, 6)}},
         "hhi": fr(2, 5), "cpu_s": 1.5, "decisive_facts": {"reconcile": [], "R1": [], "R3": []},
         "loo_round0": {str(i): 50.0 for i in range(1, 6)}, "loo_final": {str(i): 50.0 for i in range(1, 6)}},
    ]
    for it, recs in (("ES-1", m1), ("ES-2", m2)):
        p = med / it / "p3" / "mediator.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text("".join(json.dumps({"schema_version": 1, "seq": i + 1, "stage": "d", "item": it, "label": "p3",
                                         "arm": "E", "node": None, **r}) + "\n" for i, r in enumerate(recs)))
    return run


@pytest.fixture(scope="module")
def out(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r1")
    run = build(root)
    assert ea.main(["--ledger", str(run), "--out", str(root / "out")]) == 0
    return root / "out"


def rows(out: Path) -> dict[tuple[str, str, str, str], str]:
    with (out / "results.csv").open() as f:
        return {(r["quantity"], r["class"], r["arm"], r["stat"]): r["value"] for r in csv.DictReader(f)}


def val(out: Path, q: str, cls: str, arm: str, stat: str) -> float:
    return float(rows(out)[(q, cls, arm, stat)])


# --- helpers ---------------------------------------------------------------------------------------------------------


def test_seeds_match_preregistration() -> None:
    want = {"E-S*": (943313030, 1803240717, 646548904), "E-G": (391859146, 1866285162, 1744006119),
            "EG-G": (594628461, 1599796053, 4118203276)}
    for c, seeds in want.items():
        assert tuple(ea.seed_of(f"eq|{c}|{q}") for q in ("P1", "P4", "P5")) == seeds
    assert ea.seed_of("eq|auroc") == 3066176665


def test_sign_test_matches_section_8_1() -> None:
    assert ea.sign_test_p(6, 0) == 0.03125
    assert ea.sign_test_p(0, 8) == 0.0078125
    assert ea.sign_test_p(5, 0) == 0.0625
    assert ea.sign_test_p(2, 1) == 1.0
    assert ea.sign_test_p(0, 0) == 1.0
    assert ea.sign_test_p(9, 1) == pytest.approx(22 / 1024)  # 2 * (1 + 10) / 2^10


def test_clopper_pearson() -> None:
    assert ea.clopper_pearson(0, 1) == (0.0, pytest.approx(0.975))
    lo, hi = ea.clopper_pearson(2, 2)
    assert lo == pytest.approx(0.025**0.5, abs=1e-12) and hi == 1.0
    lo, hi = ea.clopper_pearson(5, 10)
    # scipy 1.18.1 beta.ppf(0.025, 5, 6), beta.ppf(0.975, 6, 5)
    assert lo == pytest.approx(0.18708602844739855, abs=1e-12) and hi == pytest.approx(0.8129139715526015, abs=1e-12)


def test_wilson() -> None:
    lo, hi = ea.wilson(1, 5)
    assert lo == pytest.approx(0.0362241, abs=1e-6) and hi == pytest.approx(0.6244654, abs=1e-6)
    assert ea.wilson(0, 21)[0] == 0.0 and ea.wilson(5, 5)[1] == 1.0


def test_holm() -> None:
    # sorted 0.005*4 = 0.02, 0.01*3 = 0.03, 0.03*2 = 0.06, 0.04*1 -> cummax 0.06
    assert ea.holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])
    assert ea.holm([0.5, 1.0, 0.125, 1.0]) == [1.0, 1.0, 0.5, 1.0]
    assert ea.holm([]) == []


def test_es_outcome_rule() -> None:
    b = 0.2
    assert ea.outcome("ES", b + ea.LN_1_1, b) == 0  # within ln 1.1: tie (inclusive)
    assert ea.outcome("ES", b - 0.1, b) == 1 and ea.outcome("ES", b + 0.1, b) == -1
    assert ea.outcome("ES", math.inf, math.inf) == 0
    assert ea.outcome("ES", math.inf, 5.0) == -1 and ea.outcome("ES", 5.0, math.inf) == 1
    assert ea.outcome("CR", 0.5, 0.25) == 1 and ea.outcome("PF", 0.0, 1.0) == -1


def test_auroc_and_bins() -> None:
    assert ea.auroc([0.4], [0.0, 0.2, 0.4, 0.4]) == 0.75
    assert [ea.kappa_bin(k) for k in (0.0, 0.2, 1 / 3, 0.6, 2 / 3, 1.0)] == [0.2, 0.2, 0.4, 0.6, 0.8, 1.0]


def test_answers_equal() -> None:
    assert ea.answers_equal(200.0, 199.99999999999991)
    assert not ea.answers_equal(100.0, 120.0)
    assert ea.answers_equal([{"f": 1}, {"f": 2}], [{"f": 2}, {"f": 1}])
    assert not ea.answers_equal("a", "b") and ea.answers_equal(None, None)


# --- one hand-computed value per family ------------------------------------------------------------------------------


def test_h_family_win_tie_loss(out: Path) -> None:
    # H1 PF: E 1 1 1 1 0 vs S* 0 0 1 1 0 -> 2 wins, 0 losses, 3 ties; p = 2 * 1/4; CP(2, 2) = [sqrt(0.025), 1]
    assert [val(out, "H1", "PF", "E-S*", s) for s in ("wins", "losses", "ties", "n", "discordant")] == [2, 0, 3, 5, 2]
    assert val(out, "H1", "PF", "E-S*", "p") == 0.5
    assert val(out, "H1", "PF", "E-S*", "delta") == pytest.approx(0.4)
    assert val(out, "H1", "PF", "E-S*", "pi") == 1.0
    assert val(out, "H1", "PF", "E-S*", "ci_lo") == pytest.approx(0.158113883, abs=1e-9)
    # H1 ES: 0.05 vs 0.5 win; inf vs 0.2 loss.  H2 ES: 0.05 vs 0.1 within ln 1.1, inf vs inf: 2 ties, no pi row
    assert [val(out, "H1", "ES", "E-S*", s) for s in ("wins", "losses", "ties")] == [1, 1, 0]
    assert [val(out, "H2", "ES", "E-G", s) for s in ("wins", "losses", "ties", "p")] == [0, 0, 2, 1]
    assert ("H2", "ES", "E-G", "pi") not in rows(out)
    # H3 ES: 0.3 vs 0.1 loss; 0.15 vs inf win.  Descriptive EG-S*: PF 3 wins 2 ties
    assert [val(out, "H3", "ES", "EG-G", s) for s in ("wins", "losses")] == [1, 1]
    assert [val(out, "win/tie/loss", "PF", "EG-S*", s) for s in ("wins", "ties")] == [3, 2]
    assert ("win/tie/loss", "PF", "EG-S*", "p_holm") not in rows(out)


def test_holm_families_in_results(out: Path) -> None:
    # primary family {H1, H2} x {ES, PF}: p = H1 PF 0.5, H1 ES 1, H2 PF 2/16 = 0.125, H2 ES 1 -> Holm 1, 1, 0.5, 1
    assert val(out, "H2", "PF", "E-G", "p") == 0.125
    assert val(out, "H2", "PF", "E-G", "p_holm") == 0.5
    assert val(out, "H1", "PF", "E-S*", "p_holm") == 1.0
    # H3 family {ES, PF}: H3 PF = 5/0 -> 0.0625, H3 ES 1 -> Holm 0.125, 1
    assert val(out, "H3", "PF", "EG-G", "p") == 0.0625
    assert val(out, "H3", "PF", "EG-G", "p_holm") == 0.125
    assert val(out, "H3", "ES", "EG-G", "p_holm") == 1.0


def test_holm_primary_restriction(tmp_path: Path) -> None:
    run = build(tmp_path)
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o"), "--primary", "PF"]) == 0
    r = rows(tmp_path / "o")
    assert float(r[("H2", "PF", "E-G", "p_holm")]) == 0.25  # 2 tests: sorted 0.125*2, 0.5*1 -> 0.25, 0.5
    assert float(r[("H1", "PF", "E-S*", "p_holm")]) == 0.5
    assert ("H1", "ES", "E-S*", "p_holm") not in r


def test_p1_tokens_and_censoring(out: Path) -> None:
    # PF log2(E/S*) = 1 2 3 0 -1 -> median 1; pooled with ES log2 3, -2 -> sorted -2 -1 0 1 1.58 2 3 -> 1
    assert val(out, "P1", "PF", "E-S*", "estimate") == 1.0
    assert val(out, "P1", "all", "E-S*", "estimate") == 1.0
    assert val(out, "P1", "all", "E-S*", "n") == 7
    lo, hi = val(out, "P1", "PF", "E-S*", "ci_lo"), val(out, "P1", "PF", "E-S*", "ci_hi")
    assert -1 <= lo <= 1 <= hi <= 3
    # PF-5's S* call hit its cap: sensitivity drops it -> 1 2 3 0 -> median 1.5
    assert val(out, "P1", "PF", "E-S*", "sens_n") == 4
    assert val(out, "P1", "PF", "E-S*", "sens_estimate") == 1.5
    # G and EG both carry the shared 60-token planner: G = 60 + 40, EG = 60 + 40 -> EG-G log2 = 0
    assert val(out, "P1", "all", "EG-G", "estimate") == 0.0


def test_p1_bootstrap_independent_recompute(out: Path) -> None:
    import numpy as np

    r = np.array([1.0, 2.0, 3.0, 0.0, -1.0])  # items PF-1..PF-5 in sorted order
    rng = np.random.default_rng(943313030)
    meds = np.median(r[rng.integers(0, 5, size=(10000, 5))], axis=1)
    lo, hi = np.percentile(meds, [2.5, 97.5])
    assert val(out, "P1", "PF", "E-S*", "ci_lo") == pytest.approx(lo, rel=1e-8)
    assert val(out, "P1", "PF", "E-S*", "ci_hi") == pytest.approx(hi, rel=1e-8)


def test_p4_p5_constant_ratio(out: Path) -> None:
    # wall E 20 s vs S* 10 s on every item: estimate 1, degenerate interval [1, 1]
    assert [val(out, "P4", "all", "E-S*", s) for s in ("estimate", "ci_lo", "ci_hi", "n")] == [1, 1, 1, 7]
    # USD on PF: E 0.2 vs S* 0.1 -> 1
    assert val(out, "P5", "PF", "E-S*", "estimate") == 1.0


def test_p2_p3_rates(out: Path) -> None:
    assert [val(out, "P2", "PF", "E", s) for s in ("k", "n", "estimate")] == [4, 5, 0.8]
    assert val(out, "P2", "ES", "S*", "estimate") == pytest.approx(0.35)  # median of 0.5, 0.2
    assert val(out, "P2", "ES", "E", "estimate") == math.inf and val(out, "P2", "ES", "E", "n_inf") == 1
    assert rows(out)[("P2", "ES", "E", "estimate")] == "inf"
    # P3: S* PF has one cap stop in 5 -> Wilson(1, 5)
    assert val(out, "P3", "PF", "S*", "estimate") == 0.2
    assert val(out, "P3", "PF", "S*", "ci_lo") == pytest.approx(0.0362241, abs=1e-6)
    assert val(out, "P3", "all", "S*", "k") == 1 and val(out, "P3", "all", "S*", "n") == 7


def test_section4_overcap_and_excluded(out: Path) -> None:
    # ES S*: 2.3 > 1.1 * 2.00 counts, 2.2 does not (strictly greater)
    assert val(out, "Over-cap", "ES", "S*", "k") == 1 and val(out, "Over-cap", "ES", "S*", "n") == 2
    assert val(out, "Excluded", "ES", "E", "n_interrupted") == 1
    meta = json.loads((out / "meta.json").read_text())
    assert meta["lists"]["interrupted"] == [{"arm": "E", "cls": "ES", "item": "ES-3", "label": "p3"}]
    assert meta["lists"]["over_cap"][0]["item"] == "ES-1"


def test_mechanistic_ledger(out: Path) -> None:
    # M4: 2 changed (1 accepted, 1 conformity) of 3 -> conformity rate 1/2
    assert [val(out, "M4", "ES", "E", s) for s in ("n", "k_changed", "k_conformity", "conformity_rate")] == [
        3, 2, 1, 0.5]
    # M5: errors {PF-5: 1 - 0.6}, ok {0, 0.2, 0.4, 0.4} -> (1 + 1 + 0.5 + 0.5) / 4
    assert val(out, "M5", "PF", "E", "estimate") == 0.75
    # M8: kappa0 1.0 0.8 0.6 0.6 0.6 with scores 1 1 1 1 0 -> bin 0.6: 2 / 3
    assert val(out, "M8", "PF", "E", "n[0.6]") == 3
    assert val(out, "M8", "PF", "E", "estimate[0.6]") == pytest.approx(2 / 3)
    # M10: ES S* calls 2.3 / 2 and 2.2 / 2 -> median 1.125, max 1.15
    assert val(out, "M10", "ES", "S*", "median") == pytest.approx(1.125)
    assert val(out, "M10", "ES", "S*", "max") == pytest.approx(1.15)


def test_mediator_family(out: Path) -> None:
    # M11: HHI 1/3 and 2/5 -> mean 11/30; dictator only ES-2 (max phi 3/5 >= 1/2)
    assert val(out, "M11", "ES", "E", "hhi_mean") == pytest.approx(11 / 30)
    assert [val(out, "M11", "ES", "E", s) for s in ("n", "k_dictator", "share_dictator")] == [2, 1, 0.5]
    # M12: 3 distinct facts (one duplicate record) over 2 E item-arms
    assert [val(out, "M12", "ES", "E", s) for s in ("n_facts", "k_verified", "facts_per_answer")] == [3, 1, 1.5]
    # M13: round-0 LOO all equal R0 in both; final: ES-1 has 90 != 100 -> 1 of 2 stable
    assert val(out, "M13", "ES", "E", "k_stable_round0") == 2
    assert val(out, "M13", "ES", "E", "share_stable_final") == 0.5
    # M14: decisive facts in ES-1 only; one evidence and one conformity change
    assert [val(out, "M14", "ES", "E", s) for s in ("k_decisive", "k_change_evidence", "k_change_conformity")] == [
        1, 1, 1]
    # M15: ES-1 R3 = 120 != 100 (R1 within 1e-9 counts as equal); ES-2 all equal
    assert [val(out, "M15", "ES", "E", s) for s in ("n", "k_disagree")] == [2, 1]
    # M18: cpu 0.5, 1.5; equivalence call 0.05 USD
    assert [val(out, "M18", "ES", "E", s) for s in ("cpu_s_median", "cpu_s_max", "cpu_s_sum")] == [1, 1.5, 2]
    assert val(out, "M18", "ES", "E", "equivalence_usd") == 0.05


def test_superseded_grade_line(out: Path) -> None:
    with (out / "item_arms.csv").open() as f:
        ia = {(r["item"], r["arm"]): r for r in csv.DictReader(f)}
    assert ia[("PF-1", "E")]["score"] == "1"  # the earlier 0 line for PF-1 p3 is superseded
    assert ia[("PF-1", "G")]["tokens"] == "100" and ia[("PF-1", "EG")]["tokens"] == "100"


# --- format, sort, determinism, failure modes ------------------------------------------------------------------------


def test_results_csv_sorted_and_formatted(out: Path) -> None:
    lines = (out / "results.csv").read_text().splitlines()
    assert lines[0] == "quantity,class,arm,stat,value"
    body = list(csv.reader(lines[1:]))
    assert body == sorted(body)
    for q, _c, _a, _s, v in body:
        assert v == "%.9g" % float(v), (q, v)  # noqa: UP031
    assert ea.fmt(1 / 3) == "0.333333333" and ea.fmt(1e10) == "1e+10" and ea.fmt(7) == "7"
    assert ea.fmt(math.inf) == "inf"
    assert all("nan" not in ln for ln in lines)
    q = (out / "quantities.txt").read_text().splitlines()
    assert "H1\t§6" in q and "Over-cap\t§4" in q and "M11\t§6 (§12 A0.5, MEDIATOR.md §6)" in q
    assert [x.split("\t")[0] for x in q] == sorted({r[0] for r in body})


def test_deterministic(tmp_path: Path, out: Path) -> None:
    run = build(tmp_path)
    assert ea.main(["--ledger", str(run / "ledger.jsonl"), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "results.csv").read_bytes() == (out / "results.csv").read_bytes()
    m1 = json.loads((tmp_path / "o" / "meta.json").read_text())
    m2 = json.loads((out / "meta.json").read_text())
    assert m1["ledger_sha256"] == m2["ledger_sha256"] and m1["seeds"] == m2["seeds"]
    assert m1["seeds"]["eq|E-S*|P1"] == 943313030


def test_empty_ledger(tmp_path: Path) -> None:
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "ledger.jsonl").write_text("")
    assert ea.main(["--ledger", str(tmp_path / "run"), "--out", str(tmp_path / "o")]) == 0
    assert (tmp_path / "o" / "results.csv").read_text() == "quantity,class,arm,stat,value\n"
    assert any("empty ledger" in w for w in json.loads((tmp_path / "o" / "meta.json").read_text())["warnings"])


def test_partial_ledger_torn_line(tmp_path: Path) -> None:
    run = build(tmp_path)
    lines = (run / "ledger.jsonl").read_text().splitlines(keepends=True)
    cut = next(i for i, ln in enumerate(lines) if '"item_arm"' in ln and '"PF-3"' in ln)
    (run / "ledger.jsonl").write_text("".join(lines[:cut]) + lines[cut][:40])
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    r = rows(tmp_path / "o")
    assert float(r[("Excluded", "PF", "S*", "n_interrupted")]) == 1
    meta = json.loads((tmp_path / "o" / "meta.json").read_text())
    assert any("torn last line" in w for w in meta["warnings"])


def test_torn_middle_line_is_a_hard_error(tmp_path: Path) -> None:
    run = build(tmp_path)
    lines = (run / "ledger.jsonl").read_text().splitlines(keepends=True)
    mid = len(lines) // 2
    (run / "ledger.jsonl").write_text("".join(lines[:mid]) + lines[mid][:30] + "\n" + "".join(lines[mid + 1:]))
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 2


# --- grading semantics shared with route 2 (N24#4) and the route contract rows (N24#8, DRYRUN) ----------------------


def read_ledger(run: Path) -> list[dict[str, Any]]:
    return [json.loads(ln) for ln in (run / "ledger.jsonl").read_text().splitlines() if ln.strip()]


def write_ledger(run: Path, recs: list[dict[str, Any]]) -> None:
    (run / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))


def append_ledger(run: Path, *new: dict[str, Any]) -> None:
    recs = read_ledger(run)
    seq = max(int(r["seq"]) for r in recs)
    for i, r in enumerate(new, 1):
        recs.append({"schema_version": 1, "seq": seq + i, "ts_utc": "2026-10-05T13:00:00.000000Z", "stage": "d", **r})
    write_ledger(run, recs)


def item_arm_rec(item: str, arm: str, label: str | None = None, **kw: Any) -> dict[str, Any]:
    return {"record": "item_arm", "item": item, "cls": item.split("-")[0], "label": label or LABEL[arm], "arm": arm,
            "run_tag": "t", "status": "ok", "answer": None, "B_usd": "2.00",
            "started_utc": "2026-10-05T12:00:00.000000Z", "ended_utc": "2026-10-05T12:00:10.000000Z", "calls": [],
            **kw}


def append_grading(run: Path, cls: str, *lines: dict[str, Any], first: bool = False) -> None:
    p = run / "grading_results" / f"{cls}.jsonl"
    old = p.read_text() if p.exists() else ""
    new = "".join(json.dumps(r) + "\n" for r in lines)
    p.write_text(new + old if first else old + new)


def set_item_arm(run: Path, item: str, arm: str, **kw: Any) -> None:
    recs = read_ledger(run)
    for r in recs:
        if r["record"] == "item_arm" and r["item"] == item and r["arm"] == arm:
            r.update(kw)
    write_ledger(run, recs)


def item_arms(out: Path) -> dict[tuple[str, str], dict[str, str]]:
    with (out / "item_arms.csv").open() as f:
        return {(r["item"], r["arm"]): r for r in csv.DictReader(f)}


# the N24#4 row: an ES oracle failure (eq_harness cmd_score writes score null, score_num null, score_inf false)
ES_ORACLE_FAILURE = {"exit": 1, "score": None, "score_num": None, "score_inf": False,
                     "detail": "oracle error: 0 authenticated verdict lines (exit 1)"}


def test_es_oracle_failure_is_unscored_not_inf(tmp_path: Path) -> None:
    run = build(tmp_path)
    append_grading(run, "ES", {"ts_utc": "2026-10-05T14:00:00.000000Z", "item": "ES-1", "label": "p3",
                               **ES_ORACLE_FAILURE})
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    r = rows(tmp_path / "o")
    # ES-1 E (0.05 before) is now unscored: H1 ES keeps only ES-2 (inf vs 0.2: a loss), never a second loss
    assert [float(r[("H1", "ES", "E-S*", s)]) for s in ("n", "wins", "losses", "n_missing")] == [1, 0, 1, 1]
    assert float(r[("n_unscored", "ES", "E", "n")]) == 1 and float(r[("n_unscored", "ES", "S*", "n")]) == 0
    assert float(r[("n_missing", "ES", "E", "n")]) == 0  # it has a grading line: unscored, not missing
    assert item_arms(tmp_path / "o")[("ES-1", "E")]["score"] == ""
    meta = json.loads((tmp_path / "o" / "meta.json").read_text())
    assert any("ES-1" in w and "unscored" in w for w in meta["warnings"])


def test_es_inf_only_on_score_inf_or_string_inf(tmp_path: Path) -> None:
    run = build(tmp_path)
    t = "2026-10-05T14:00:00.000000Z"
    append_grading(run, "ES",
                   {"ts_utc": t, "item": "ES-1", "label": "p1", "score": "inf", "score_num": None, "score_inf": False},
                   {"ts_utc": t, "item": "ES-2", "label": "p1", "score": None, "score_num": None, "score_inf": True},
                   # an infinite score_num without score_inf / "inf" is not an ES e = inf: unscored
                   {"ts_utc": t, "item": "ES-1", "label": "p2", "score": 5, "score_num": math.inf,
                    "score_inf": False})
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    ia = item_arms(tmp_path / "o")
    assert ia[("ES-1", "S*")]["score"] == "inf" and ia[("ES-2", "S*")]["score"] == "inf"
    assert ia[("ES-1", "G")]["score"] == ""


def pf_line(item: str, ts: str, score: int) -> dict[str, Any]:
    return {"ts_utc": ts, "item": item, "label": "p3", "exit": 0, "score": score, "score_num": float(score),
            "score_inf": False}


def test_latest_grading_line_by_ts_then_line_number(tmp_path: Path) -> None:
    run = build(tmp_path)  # the base PF lines carry the unparseable ts "x": any real timestamp beats them
    # PF-2: first in the file, a real ts -> wins over the later "x" line
    append_grading(run, "PF", pf_line("PF-2", "2026-10-05T15:00:00.000000Z", 0), first=True)
    # PF-3: the later ts wins although an earlier ts comes after it in the file
    append_grading(run, "PF", pf_line("PF-3", "2026-10-05T16:00:00.000000Z", 0),
                   pf_line("PF-3", "2026-10-05T15:30:00.000000Z", 1))
    # PF-4: equal ts -> the later line wins
    append_grading(run, "PF", pf_line("PF-4", "2026-10-05T15:00:00.000000Z", 1),
                   pf_line("PF-4", "2026-10-05T15:00:00.000000Z", 0))
    # PF-5: time order, not string order: 15:30+01:00 = 14:30Z is earlier than 15:00Z
    append_grading(run, "PF", pf_line("PF-5", "2026-10-05T15:00:00Z", 1),
                   pf_line("PF-5", "2026-10-05T15:30:00+01:00", 0))
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    ia = item_arms(tmp_path / "o")
    assert [ia[(f"PF-{i}", "E")]["score"] for i in (2, 3, 4, 5)] == ["0", "0", "0", "1"]


def test_non_numeric_latest_line_leaves_the_unit_unscored(tmp_path: Path) -> None:
    run = build(tmp_path)
    append_grading(run, "PF", {"ts_utc": "z", "item": "PF-3", "label": "p3", "exit": 1, "score": None,
                               "score_num": None, "score_inf": False, "detail": "oracle error"})
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    assert item_arms(tmp_path / "o")[("PF-3", "E")]["score"] == ""  # the earlier 1 is not kept
    r = rows(tmp_path / "o")
    assert float(r[("P2", "PF", "E", "n")]) == 4 and float(r[("n_unscored", "PF", "E", "n")]) == 1
    assert float(r[("H1", "PF", "E-S*", "n")]) == 4


def test_partial_item_arm_scores_zero_whatever_its_line(tmp_path: Path) -> None:
    run = build(tmp_path)
    set_item_arm(run, "PF-1", "E", status="partial")  # its grading line says 1
    set_item_arm(run, "ES-1", "E", status="partial")  # its grading line says 0.05
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    ia = item_arms(tmp_path / "o")
    assert ia[("PF-1", "E")]["score"] == "0" and ia[("ES-1", "E")]["score"] == "inf"


def test_missing_run_end_warns(tmp_path: Path, out: Path) -> None:
    assert any("no run_end" in w for w in json.loads((out / "meta.json").read_text())["warnings"])
    run = build(tmp_path)
    append_ledger(run, {"record": "run_end"})
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    assert not any("no run_end" in w for w in json.loads((tmp_path / "o" / "meta.json").read_text())["warnings"])


def contract_fixture(root: Path) -> Path:
    """The tiny run dir plus: PF-6 with an S* item-arm only (no grading line), a duplicated PF-1 E item_arm, PF-2 E
    with wall_used true, a p5 screening cell (arm S*) that is not an analysed arm, and a declared p9 re-run of PF-4 G
    (not graded; a re-run beside the original is not a duplicate)."""
    run = build(root)
    set_item_arm(run, "PF-2", "E", wall_used=True, wall_requests=2, wall_approved=1)
    append_ledger(run, item_arm_rec("PF-6", "S*"), item_arm_rec("PF-1", "E", kappa0=1.0),
                  item_arm_rec("PF-3", "S*", label="p5"), item_arm_rec("PF-4", "G", label="p9"), {"record": "run_end"})
    return run


def test_contract_count_rows(tmp_path: Path) -> None:
    run = contract_fixture(tmp_path)
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o")]) == 0
    r = rows(tmp_path / "o")

    def n(q: str, cls: str, arm: str) -> float:
        return float(r[(q, cls, arm, "n")])

    # PF-6 S* and the PF-4 G re-run p9 have no grading line: unscored and missing
    assert [n("n_unscored", "PF", a) for a in ("S*", "G", "E", "EG")] == [1, 1, 0, 0]
    assert [n("n_missing", "PF", a) for a in ("S*", "G", "E", "EG")] == [1, 1, 0, 0]
    # PF-1 E (p3 twice) only: p5 is not analysed, p9 beside p2 is a re-run
    assert [n("n_dup_item_arm", "PF", a) for a in ("S*", "G", "E", "EG")] == [0, 0, 1, 0]
    assert [n("n_wall_used", "PF", a) for a in ("S*", "G", "E", "EG")] == [0, 0, 1, 0]
    assert [n(q, "ES", "E") for q in ("n_missing", "n_unscored", "n_dup_item_arm", "n_wall_used")] == [0, 0, 0, 0]
    ia = item_arms(tmp_path / "o")
    assert ia[("PF-2", "E")]["wall_used"] == "1" and ia[("PF-1", "E")]["wall_used"] == "0"
    assert ia[("PF-3", "S*")]["label"] == "p1" and ia[("PF-4", "G")]["label"] == "p9"
    meta = json.loads((tmp_path / "o" / "meta.json").read_text())
    assert any("p5" in w for w in meta["warnings"])
    assert meta["exclude_wall_used"] is False


def test_exclude_wall_used_recomputes_everything(tmp_path: Path) -> None:
    run = contract_fixture(tmp_path)
    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "o"), "--exclude-wall-used"]) == 0
    r = rows(tmp_path / "o")
    # PF-2 E is gone: H1 PF E-S* loses the PF-2 pair (a win: 1 vs 0), P2 PF E counts 4 units, P1 pairs 4
    assert [float(r[("H1", "PF", "E-S*", s)]) for s in ("n", "wins", "n_missing")] == [4, 1, 1]
    assert float(r[("P2", "PF", "E", "n")]) == 4 and float(r[("P3", "PF", "E", "n")]) == 4
    assert float(r[("P1", "PF", "E-S*", "n")]) == 4
    assert float(r[("n_wall_used", "PF", "E", "n")]) == 0 and float(r[("n_unscored", "PF", "E", "n")]) == 0
    ia = item_arms(tmp_path / "o")
    assert ("PF-2", "E") not in ia and ("PF-2", "S*") in ia
    meta = json.loads((tmp_path / "o" / "meta.json").read_text())
    assert meta["exclude_wall_used"] is True
    assert meta["lists"]["excluded_wall_used"] == [{"arm": "E", "item": "PF-2", "label": "p3"}]


# --- cross-route: route 2 (eq_route2.py, read-only here) on the same fixture ---------------------------------------

H_NAME = {"H1": "H1", "H2": "H2", "H3": "H3", "win/tie/loss": "H_desc"}  # route 1 quantity -> route 2


def n_comparison_diffs(r1: dict[tuple[str, str, str, str], str], r2: dict[tuple[str, str, str, str], str],
                       tag: str = "") -> list[str]:
    """Route 1 H rows `n` vs route 2 `n_comparison`; route 1 writes n = 0 when an item is scored in one arm only,
    route 2 writes no row for an empty comparison set: both mean 0."""
    diffs = []
    for (q, cls, arm, stat), v in sorted(r1.items()):
        if q in H_NAME and stat == "n":
            v2 = r2.get((H_NAME[q], cls, arm, "n_comparison"))
            if v2 != v and not (v == "0" and v2 is None):
                diffs.append(f"{tag}{q} {cls} {arm}: route 1 n = {v}, route 2 n_comparison = {v2}")
    return diffs


def cross_fixture(root: Path) -> Path:
    """The tiny run dir plus ES-4: S* finite (0.3), E the N24#4 oracle-failure row (route 1 used to call it e = inf)."""
    run = build(root)
    append_ledger(run, item_arm_rec("ES-4", "S*"), item_arm_rec("ES-4", "E", kappa0=1.0), {"record": "run_end"})
    t = "2026-10-05T14:00:00.000000Z"
    append_grading(run, "ES", {"ts_utc": t, "item": "ES-4", "label": "p1", "exit": 0, "score": 0.3,
                               "score_num": 0.3, "score_inf": False},
                   {"ts_utc": t, "item": "ES-4", "label": "p3", **ES_ORACLE_FAILURE})
    return run


def run_both(tmp_path: Path, run: Path, *flags: str) -> tuple[dict[tuple[str, str, str, str], str],
                                                             dict[tuple[str, str, str, str], str]]:
    pytest.importorskip("duckdb", reason="route 2 needs duckdb: run with --with duckdb")
    import eq_route2 as r2

    assert ea.main(["--ledger", str(run), "--out", str(tmp_path / "r1"), *flags]) == 0
    rc2 = r2.main(["--ledger", str(run), "--out", str(tmp_path / "r2"), "--boot-b", "200", *flags])
    assert rc2 == 0, f"route 2 exited {rc2} on {flags}"
    return rows(tmp_path / "r1"), rows(tmp_path / "r2")


def test_cross_route_n_comparison_with_the_es_oracle_failure(tmp_path: Path) -> None:
    r1, r2 = run_both(tmp_path, cross_fixture(tmp_path))
    assert r1[("H1", "ES", "E-S*", "n")] == "2"  # ES-1, ES-2; ES-4 E is unscored
    diffs = n_comparison_diffs(r1, r2)
    assert not diffs, "routes disagree on n_comparison:\n" + "\n".join(diffs)


def test_cross_route_contract_rows(tmp_path: Path) -> None:
    run = contract_fixture(tmp_path)
    for flags in ((), ("--exclude-wall-used",)):
        r1, r2 = run_both(tmp_path / ("x" if flags else "a"), run, *flags)
        diffs = []
        for q in ("n_unscored", "n_missing", "n_dup_item_arm", "n_wall_used"):
            keys = {k for k in (*r1, *r2) if k[0] == q and k[3] == "n" and k[1] != "all"}
            for k in sorted(keys):
                if r1.get(k) != r2.get(k):
                    diffs.append(f"{flags} {k}: route 1 {r1.get(k)}, route 2 {r2.get(k)}")
        diffs += n_comparison_diffs(r1, r2, f"{flags} ")
        assert not diffs, "routes disagree on the contract rows:\n" + "\n".join(diffs)


def test_cli_errors_are_clean(tmp_path: Path) -> None:
    cmd = ["uv", "run", "--script", "--quiet", str(HARNESS / "eq_analyse.py")]
    cp = subprocess.run([*cmd, "--ledger", str(tmp_path / "nope"), "--out", str(tmp_path / "o")],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 2 and "no ledger.jsonl" in cp.stderr and "Traceback" not in cp.stderr
    (tmp_path / "bad").mkdir()
    (tmp_path / "bad" / "ledger.jsonl").write_text('{"schema_version": 1}\nnot json\n{"schema_version": 1}\n')
    cp = subprocess.run([*cmd, "--ledger", str(tmp_path / "bad"), "--out", str(tmp_path / "o")],
                        capture_output=True, text=True, check=False)
    assert cp.returncode == 2 and "line 2 is not JSON" in cp.stderr and "Traceback" not in cp.stderr
