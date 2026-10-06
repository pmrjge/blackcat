"""Tests of analysis route 2 (eq_route2.py + eq_route2.sql). Every expected number is computed by hand (or with
math.comb in the test), never by calling the code under test.

Run from STAGE (the harness conftest needs numpy and jsonschema, hence the requirements of eq_harness.py):
  uv run --no-project --with pytest --with duckdb --with-requirements harness/eq_harness.py \
    pytest -q harness/tests/test_eq_route2.py
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HARNESS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS))
import eq_route2 as r2  # noqa: E402

LABEL = {"S*": "p1", "G": "p2", "E": "p3", "EG": "p4"}
Z = 1.959963984540054


# ----------------------------------------------------------------------------------------------- ledger builders
class Ledger:
    def __init__(self) -> None:
        self.recs: list[dict[str, Any]] = []
        self.n = 0

    def add(self, record: str, **kw: Any) -> None:
        self.n += 1
        self.recs.append({"schema_version": 1, "seq": self.n, "ts_utc": f"2026-10-05T12:00:{self.n % 60:02d}.000000Z",
                          "record": record, "stage": "p", **kw})

    def start(self) -> None:
        self.add("run_start", stub=True, harness_sha256="h" * 64)

    def end(self) -> None:
        self.add("run_end", items_run=0)

    def item_arm(self, item: str, cls: str, arm: str, status: str = "ok", label: str | None = None, **kw: Any) -> None:
        self.add("item_arm", item=item, cls=cls, arm=arm, label=label or LABEL[arm], status=status, B_usd="2.00",
                 started_utc="2026-10-05T12:00:00.000000Z", ended_utc="2026-10-05T12:00:10.000000Z", **kw)

    def call(self, item: str, cls: str, arm: str, tokens: int = 100, cost: float | None = 0.05, cap: str = "0.200000",
             cap_stop: bool = False, label: str | None = None, charged_to: list[str] | None = None,
             call_id: str | None = None, role: str = "s", **kw: Any) -> str:
        label = label or LABEL[arm]
        cid = call_id or f"{len(self.recs) + 1:05d}_x"
        usage = {"input_tokens": tokens - 40, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 20,
                 "output_tokens": 10}
        self.add("call", call_id=cid, item=item, cls=cls, arm=arm, label=label, charged_to=charged_to or [label],
                 cap_usd=cap, total_cost_usd=cost, usage=usage, cap_stop=cap_stop, role=role, **kw)
        return cid

    def write(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "ledger.jsonl").write_text("".join(json.dumps(x) + "\n" for x in self.recs))


def grade(d: Path, cls: str, rows: list[dict[str, Any]]) -> None:
    g = d / "grading_results"
    g.mkdir(exist_ok=True)
    with (g / f"{cls}.jsonl").open("a") as f:
        for x in rows:
            f.write(json.dumps({"ts_utc": "2026-10-05T13:00:00.000000Z", "exit": 0, "detail": {}, **x}) + "\n")


def analyse(tmp: Path, led: Ledger, name: str = "run", mediator: list[dict[str, Any]] | None = None,
            grading: dict[str, list[dict[str, Any]]] | None = None,
            boot_b: int = 400) -> dict[tuple[str, str, str, str], str]:
    d = tmp / name
    led.write(d)
    for cls, rows in (grading or {}).items():
        grade(d, cls, rows)
    args = ["--ledger", str(d), "--out", str(tmp / (name + "_out")), "--boot-b", str(boot_b)]
    if mediator is not None:
        m = tmp / (name + "_med") / "p" / "PF-1" / "p3"
        m.mkdir(parents=True)
        (m / "mediator.jsonl").write_text("".join(json.dumps(x) + "\n" for x in mediator))
        args += ["--mediator-root", str(tmp / (name + "_med"))]
    assert r2.main(args) == 0
    return read_results(tmp / (name + "_out"))


def read_results(out: Path) -> dict[tuple[str, str, str, str], str]:
    with (out / "results.csv").open() as f:
        return {(r["quantity"], r["class"], r["arm"], r["stat"]): r["value"] for r in csv.DictReader(f)}


def val(res: dict[tuple[str, str, str, str], str], q: str, c: str, a: str, s: str) -> float:
    return float(res[(q, c, a, s)])


def binom_sf(k: int, n: int, p: float) -> float:
    return sum(math.comb(n, j) * p**j * (1 - p) ** (n - j) for j in range(k, n + 1))


def wilson(k: int, n: int) -> tuple[float, float]:
    ph = k / n
    c = (ph + Z * Z / (2 * n)) / (1 + Z * Z / n)
    h = Z * math.sqrt(ph * (1 - ph) / n + Z * Z / (4 * n * n)) / (1 + Z * Z / n)
    return c - h, c + h


# ----------------------------------------------------------------------------------------------- the main scenario
# PF, items PF-1..PF-10, arms S* (p1) and E (p3).
#   scores   E: 1 on items 1-8 and 10, 0 on item 9      S*: 0 on items 1-8, 1 on items 9 and 10
#   => E vs S*: 8 wins, 1 loss, 1 tie.  Hand: d = 9, p = 2 * (C(9,0) + C(9,1)) / 2^9 = 20/512 = 0.0390625.
#   tokens   S* = 100 per item-arm (usage 60+10+20+10: all four fields count). E = 100 * 2^k, k = 1 1 2 2 3 4 4 5 5 5
#   => log2 ratios sorted 1 1 2 2 3 4 4 5 5 5, median (3+4)/2 = 3.5, ratio 2^3.5.
#   cap stop on E item 1 only (k = 1): P3 E 1/10. P1_sens drops item 1: 1 2 2 3 4 4 5 5 5, median 4.
#   USD: S* 0.05, E 0.10 except E item 1 0.30 => log2 ratios 1 (items 2-10) and log2(6) (item 1): median 1.
#   cap 0.2 per call: ratios E 0.5 (item 1: 1.5), S* 0.25 => M10 E median 0.5, max 1.5.
KS = [1, 1, 2, 2, 3, 4, 4, 5, 5, 5]
KAPPA0 = [1.0, 1.0, 1.0, 0.6, 0.6, 0.4, 0.4, 0.2, 0.2, 0.6]
PASSED = [5, 5, 0, 0, 5, 5, 0, 0, 5, 5]  # members passing the round-0 public check per E item


def main_ledger() -> tuple[Ledger, dict[str, list[dict[str, Any]]]]:
    led = Ledger()
    led.start()
    grades_pf = []
    for j in range(1, 11):
        item = f"PF-{j}"
        s_score = 0 if j <= 8 else 1
        e_score = 0 if j == 9 else 1
        led.call(item, "PF", "S*", tokens=100, cost=0.05)
        led.item_arm(item, "PF", "S*", answer="a")
        led.call(item, "PF", "E", tokens=100 * 2 ** KS[j - 1], cost=0.30 if j == 1 else 0.10, cap_stop=(j == 1))
        led.item_arm(item, "PF", "E", answer="a", kappa0=KAPPA0[j - 1], kappa=KAPPA0[j - 1], rounds=0)
        for m in range(1, 6):
            led.add("check", item=item, arm="E", label="p3", member=m, round=0, node=None, passed=m <= PASSED[j - 1],
                    isolation="off", image=None, output_tail="")
        grades_pf.append({"item": item, "label": "p1", "score": str(s_score), "score_num": float(s_score)})
        grades_pf.append({"item": item, "label": "p3", "score": str(e_score), "score_num": float(e_score)})
    # reconcile records of E item PF-1 (no item/label on the record: joined through call_id)
    cid = led.call("PF-1", "PF", "E", tokens=0, cost=None, role="r1", call_id="99999_rec")
    for ch, ac, co in [(True, True, False), (True, False, True), (True, False, True), (False, False, False)]:
        led.add("reconcile", round=1, member=1, call_id=cid, changed=ch, accepted=ac, conformity=co)
    led.end()
    return led, {"PF": grades_pf}


@pytest.fixture(scope="module")
def main_res(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str, str, str], str]:
    led, grading = main_ledger()
    return analyse(tmp_path_factory.mktemp("main"), led, grading=grading)


def test_h1_counts_sign_test_and_clopper_pearson(main_res: dict) -> None:
    g = lambda s: val(main_res, "H1", "PF", "E-S*", s)  # noqa: E731
    assert (g("wins"), g("losses"), g("ties"), g("n_comparison"), g("n_discordant")) == (8, 1, 1, 10, 9)
    assert g("delta_hat") == pytest.approx(0.9)
    assert g("pi_hat") == pytest.approx(8 / 9)
    assert g("p") == pytest.approx(20 / 512, abs=1e-12)  # hand: 2 * (1 + 9) / 512
    # CP bounds defined by the exact binomial tails: P(X >= 8 | lo) = 0.025 and P(X <= 8 | hi) = 0.025, n = 9
    lo, hi = g("ci_lo"), g("ci_hi")
    # (tolerance 1e-8: the CSV carries 9 significant digits and the tail slope at hi is 9 * hi^8 = 8.6)
    assert binom_sf(8, 9, lo) == pytest.approx(0.025, abs=1e-8)
    assert 1 - binom_sf(9, 9, hi) == pytest.approx(0.025, abs=1e-8)
    # scipy binomtest(8, 9).proportion_ci('exact')
    assert (lo, hi) == pytest.approx((0.517503485, 0.997190863), abs=1e-8)
    # pooled row exists and agrees with the single class here
    assert val(main_res, "H1", "all", "E-S*", "wins") == 8
    # one class only: Holm over a family of one test leaves p unchanged
    assert val(main_res, "H1", "PF", "E-S*", "p_holm") == pytest.approx(20 / 512, abs=1e-12)
    assert ("H1", "all", "E-S*", "p_holm") not in main_res  # no Holm on the pooled row


def test_p1_median_log2_ratio_and_sensitivity(main_res: dict) -> None:
    assert val(main_res, "P1", "PF", "E-S*", "n") == 10
    assert val(main_res, "P1", "PF", "E-S*", "estimate") == pytest.approx(3.5)
    assert val(main_res, "P1", "PF", "E-S*", "ratio") == pytest.approx(2**3.5)
    assert val(main_res, "P1", "all", "E-S*", "estimate") == pytest.approx(3.5)
    assert val(main_res, "P1_sens", "PF", "E-S*", "n") == 9
    assert val(main_res, "P1_sens", "PF", "E-S*", "estimate") == pytest.approx(4.0)  # item 1 (cap stop) dropped


def test_p1_bootstrap_ci_is_inside_the_data_and_flags_exclusion_of_zero(main_res: dict) -> None:
    lo, hi = val(main_res, "P1", "PF", "E-S*", "ci_lo"), val(main_res, "P1", "PF", "E-S*", "ci_hi")
    assert 1.0 <= lo <= 3.5 <= hi <= 5.0
    assert val(main_res, "P1", "PF", "E-S*", "measured") == 1.0  # every ratio > 1: the interval excludes 0


def test_p3_p5_cap_hit_usd_and_m10(main_res: dict) -> None:
    assert (val(main_res, "P3", "PF", "E", "n"), val(main_res, "P3", "PF", "E", "k")) == (10, 1)
    lo, hi = wilson(1, 10)
    assert val(main_res, "P3", "PF", "E", "ci_lo") == pytest.approx(lo, abs=1e-9)
    assert val(main_res, "P3", "PF", "E", "ci_hi") == pytest.approx(hi, abs=1e-9)
    assert val(main_res, "P3", "PF", "S*", "k") == 0
    assert val(main_res, "P5", "PF", "E-S*", "estimate") == pytest.approx(1.0)  # nine items at 2.0, one at 6.0
    assert val(main_res, "P5_sens", "PF", "E-S*", "estimate") == pytest.approx(1.0)
    assert val(main_res, "M10", "PF", "E", "median") == pytest.approx(0.5)
    assert val(main_res, "M10", "PF", "E", "max") == pytest.approx(1.5)  # 0.30 / 0.20
    assert val(main_res, "over_cap", "PF", "E", "k") == 0  # 0.30 < 1.1 * 2.00


def test_p2_wilson_rate(main_res: dict) -> None:
    assert (val(main_res, "P2", "PF", "E", "k"), val(main_res, "P2", "PF", "E", "n")) == (9, 10)
    lo = wilson(9, 10)[0]
    assert val(main_res, "P2", "PF", "E", "estimate") == pytest.approx(0.9)
    assert val(main_res, "P2", "PF", "E", "ci_lo") == pytest.approx(lo, abs=1e-9)
    assert val(main_res, "P2", "PF", "S*", "estimate") == pytest.approx(0.2)


def test_m5_auroc_and_m8_bins_by_hand(main_res: dict) -> None:
    # error item: PF-9 (kappa0 0.2, 1 - kappa0 = 0.8). Correct items have 1 - kappa0 = 0,0,0,.4,.4,.6,.6,.8,.4.
    # AUROC = (8 items below + 1 tie * 0.5) / 9 = 8.5 / 9. Using kappa0 itself would give 0.5 / 9.
    assert val(main_res, "M5", "PF", "E", "auroc") == pytest.approx(8.5 / 9)
    assert (val(main_res, "M5", "PF", "E", "n_error"), val(main_res, "M5", "PF", "E", "n_ok")) == (1, 9)
    # the bootstrap CI exists (n_error is 1: some resamples have no error item and are dropped)
    assert 0 <= val(main_res, "M5", "PF", "E", "ci_lo") <= 1
    g = lambda s: val(main_res, "M8", "PF", "E", s)  # noqa: E731
    assert (g("n_bin_0.2"), g("k_bin_0.2"), g("rate_bin_0.2")) == (2, 1, 0.5)  # items 8, 9
    assert (g("n_bin_0.4"), g("k_bin_0.4")) == (2, 2)  # items 6, 7
    assert (g("n_bin_0.6"), g("k_bin_0.6")) == (3, 3)  # items 4, 5, 10
    assert (g("n_bin_1.0"), g("k_bin_1.0")) == (3, 3)  # items 1, 2, 3
    assert ("M8", "PF", "E", "n_bin_0.8") not in main_res


def test_m2_m3_public_check_proxy(main_res: dict) -> None:
    # Y = 5 on six items and 0 on four, N = 5: p = 0.6, mean (Y - 3)^2 = (6*4 + 4*9)/10 = 6,
    # 6 / (5 * 0.24) = 5, rho = (5 - 1) / 4 = 1
    assert val(main_res, "M2", "PF", "E", "rho_hat") == pytest.approx(1.0)
    assert val(main_res, "M2", "PF", "E", "n_eff") == pytest.approx(1.0)
    assert val(main_res, "M2", "PF", "E", "p_hat") == pytest.approx(0.6)
    assert val(main_res, "M3", "PF", "E", "public_check_at_N") == pytest.approx(0.6)
    assert val(main_res, "M3", "PF", "E", "reducer_score") == pytest.approx(0.9)
    assert val(main_res, "M3", "PF", "E", "selection_loss") == pytest.approx(-0.3)


def test_m4_reconcile_conformity_rate_through_call_id(main_res: dict) -> None:
    g = lambda s: val(main_res, "M4", "PF", "E", s)  # noqa: E731
    assert (g("n_reconciles"), g("changed"), g("accepted"), g("conformity")) == (4, 3, 1, 2)
    assert g("conformity_rate") == pytest.approx(2 / 3)


# ----------------------------------------------------------------------------------------------- ES and the odd cases
def test_latest_grading_line_wins_by_ts_utc(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for arm in ("S*", "E"):
        led.call("PF-1", "PF", arm)
        led.item_arm("PF-1", "PF", arm)
    led.end()
    d = tmp_path / "run"
    led.write(d)
    g = d / "grading_results"
    g.mkdir()
    lines = [  # p3: the stale line comes last in the file. p1: the stale line comes first. Only ts_utc decides.
        {"ts_utc": "2026-10-01T00:00:00.000000Z", "item": "PF-1", "label": "p1", "score": "1", "score_num": 1.0},
        {"ts_utc": "2026-10-05T13:00:00.000000Z", "item": "PF-1", "label": "p3", "score": "1", "score_num": 1.0},
        {"ts_utc": "2026-10-05T13:00:00.000000Z", "item": "PF-1", "label": "p1", "score": "0", "score_num": 0.0},
        {"ts_utc": "2026-10-01T00:00:00.000000Z", "item": "PF-1", "label": "p3", "score": "0", "score_num": 0.0},
    ]
    (g / "PF.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert r2.main(["--ledger", str(d), "--out", str(tmp_path / "o"), "--boot-b", "50"]) == 0
    res = read_results(tmp_path / "o")
    assert val(res, "H1", "PF", "E-S*", "wins") == 1  # E = 1 (latest) beats S* = 0


def test_es_rules_in_isolation(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    plan = [("a", 0.5, 1.0), ("b", 1.0, 1.05), ("c", 2.0, 1.0), ("d", "inf", 3.0), ("e", 1.0, "inf"),
            ("f", None, "inf"), ("g", "nograde", 1.0), ("h", 1.05, 1.0)]
    rows = []
    for k, ee, se in plan:
        item = f"ES-{k}"
        for arm in ("S*", "E"):
            led.call(item, "ES", arm)
        led.item_arm(item, "ES", "S*")
        led.item_arm(item, "ES", "E", status="partial" if ee is None else "ok")
        for lab, x in (("p1", se), ("p3", ee)):
            if x is None or x == "nograde":
                continue
            rows.append({"item": item, "label": lab, "score": str(x), "score_num": None if x == "inf" else x,
                         "score_inf": x == "inf"})
    led.end()
    res = analyse(tmp_path, led, grading={"ES": rows})
    g = lambda s: val(res, "H1", "ES", "E-S*", s)  # noqa: E731
    # a: 0.5 < 1.0 - ln 1.1 win | b: |1.0 - 1.05| < ln 1.1 tie | c: 2.0 > 1.0 + ln 1.1 loss | d: inf vs 3 loss
    # e: 1 vs inf win | f: partial E = inf vs inf tie | g: ungraded: out of the comparison set
    # h: 1.05 vs 1.0 is within ln 1.1 = 0.0953: tie
    assert (g("wins"), g("losses"), g("ties"), g("n_comparison")) == (2, 2, 3, 7)
    assert g("p") == pytest.approx(1.0)  # 2 wins 2 losses: min(1, 2 * 11/16)
    # P2 median e of E: values 0.5, 1.0, 2.0, inf, 1.0, inf, 1.05 (item g has no grade): sorted .5 1 1 1.05 2 inf inf
    assert val(res, "P2", "ES", "E", "n") == 7
    assert val(res, "P2", "ES", "E", "estimate") == pytest.approx(1.05)


def test_labels_p5_excluded_p9_replaces_and_partial_scores_zero(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    # S* p1 and a p5 screening cell for the same item: p5 is not an analysed arm
    led.call("PF-1", "PF", "S*", tokens=100)
    led.item_arm("PF-1", "PF", "S*")
    led.call("PF-1", "PF", "S*", tokens=900, label="p5")
    led.item_arm("PF-1", "PF", "S*", label="p5")
    # E: p3 present (failed, partial) and its declared re-run p9 (ok): p9 replaces p3
    led.call("PF-1", "PF", "E", tokens=400)
    led.item_arm("PF-1", "PF", "E", status="partial")
    led.call("PF-1", "PF", "E", tokens=200, label="p9")
    led.item_arm("PF-1", "PF", "E", label="p9")
    # item 2: E partial (no answer, no grading line) against a graded S* of 1: a loss for E; S* scored 1
    for arm in ("S*", "E"):
        led.call("PF-2", "PF", arm)
    led.item_arm("PF-2", "PF", "S*")
    led.item_arm("PF-2", "PF", "E", status="partial")
    led.end()
    res = analyse(tmp_path, led, grading={"PF": [
        {"item": "PF-1", "label": "p1", "score": "0", "score_num": 0.0},
        {"item": "PF-1", "label": "p9", "score": "1", "score_num": 1.0},
        {"item": "PF-2", "label": "p1", "score": True}]})  # a JSON boolean score and no score_num still counts as 1
    assert val(res, "H1", "PF", "E-S*", "wins") == 1  # PF-1: p9 (1) vs S* p1 (0)
    assert val(res, "H1", "PF", "E-S*", "losses") == 1  # PF-2: partial E scores 0 vs S* 1
    assert val(res, "P1", "PF", "E-S*", "n") == 2
    assert val(res, "P1", "all", "E-S*", "n") == 2
    # PF-1 tokens: E (p9) = 200, S* (p1) = 100, p5's 900 tokens are not S*'s: log2(2) = 1
    # PF-2: both arms 100 tokens: 0. median (0 + 1) / 2
    assert val(res, "P1", "PF", "E-S*", "estimate") == pytest.approx(0.5)


def test_over_cap_counts_item_arms_above_1_1_b(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    led.call("PF-1", "PF", "S*", cost=2.0)  # B = 2.00: exactly B is not over
    led.item_arm("PF-1", "PF", "S*")
    led.call("PF-1", "PF", "E", cost=1.5)
    led.call("PF-1", "PF", "E", cost=1.0)  # 2.5 > 2.2: over
    led.item_arm("PF-1", "PF", "E")
    led.end()
    res = analyse(tmp_path, led)
    assert (val(res, "over_cap", "PF", "E", "k"), val(res, "over_cap", "PF", "E", "n")) == (1, 1)
    assert val(res, "over_cap", "PF", "S*", "k") == 0
    assert val(res, "P5", "PF", "E-S*", "estimate") == pytest.approx(math.log2(2.5 / 2.0))


def test_shared_planner_call_is_charged_to_both_g_and_eg(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    led.call("ES-1", "ES", "EG", tokens=100, cost=0.02, charged_to=["p2", "p4"], role="plan")
    led.call("ES-1", "ES", "G", tokens=50, cost=0.01)
    led.call("ES-1", "ES", "EG", tokens=200, cost=0.03)
    led.item_arm("ES-1", "ES", "G")
    led.item_arm("ES-1", "ES", "EG")
    led.end()
    res = analyse(tmp_path, led)
    # G = 100 + 50 = 150 tokens, EG = 100 + 200 = 300: log2(2) = 1. USD: G 0.03, EG 0.05
    assert val(res, "P1", "ES", "EG-G", "estimate") == pytest.approx(1.0)
    assert val(res, "P5", "ES", "EG-G", "estimate") == pytest.approx(math.log2(0.05 / 0.03))


# ----------------------------------------------------------------------------------------------- Holm
def test_holm_correction_with_cumulative_max(tmp_path: Path) -> None:
    # H1 over PF (8 wins, 0 losses), CP (8-0) and CR (3-0): p = 2/256, 2/256, 2/8 = 0.0078125, 0.0078125, 0.25.
    # Holm, m = 3: sorted p1 <= p2 <= p3: 3*p1 = 0.0234375, 2*p2 = 0.015625 -> cummax 0.0234375, 1*p3 = 0.25.
    led = Ledger()
    led.start()
    grading: dict[str, list[dict[str, Any]]] = {"PF": [], "CP": [], "CR": []}
    for cls, n in (("PF", 8), ("CP", 8), ("CR", 3)):
        for j in range(1, n + 1):
            item = f"{cls}-{j}"
            for arm in ("S*", "E"):
                led.call(item, cls, arm)
                led.item_arm(item, cls, arm)
            for lab, s in (("p1", 0.0), ("p3", 1.0 if cls != "CR" else 0.75)):
                grading[cls].append({"item": item, "label": lab, "score": str(s), "score_num": s})
    led.end()
    res = analyse(tmp_path, led, grading=grading)
    assert val(res, "H1", "PF", "E-S*", "p") == pytest.approx(2 / 256, abs=1e-12)
    assert val(res, "H1", "CR", "E-S*", "p") == pytest.approx(0.25, abs=1e-12)
    assert val(res, "H1", "PF", "E-S*", "p_holm") == pytest.approx(0.0234375, abs=1e-12)
    assert val(res, "H1", "CP", "E-S*", "p_holm") == pytest.approx(0.0234375, abs=1e-12)
    assert val(res, "H1", "CR", "E-S*", "p_holm") == pytest.approx(0.25, abs=1e-12)
    # 8 wins of 8 discordant: the upper CP bound is exactly 1 and the lower solves pi^8 = 0.025
    assert val(res, "H1", "PF", "E-S*", "ci_hi") == 1.0
    assert val(res, "H1", "PF", "E-S*", "ci_lo") == pytest.approx(0.025 ** (1 / 8), abs=1e-8)
    # CR: any positive score difference is a win (recall-based score, higher is better)
    assert val(res, "H1", "CR", "E-S*", "wins") == 3


# ----------------------------------------------------------------------------------------------- mediator ledger
def test_mediator_m11_m12_m13(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for j in (1, 2):
        led.call(f"PF-{j}", "PF", "E")
        led.item_arm(f"PF-{j}", "PF", "E", answer="a")
    led.end()

    def m(rec: str, **kw: Any) -> dict[str, Any]:
        return {"schema_version": 1, "seq": 1, "ts_utc": "2026-10-05T12:00:01.000000Z", "record": rec, "stage": "p",
                "item": "PF-1", "label": "p3", "arm": "E", "node": None, **kw}

    third = {"num": 1, "den": 3, "float": 1 / 3}
    recs = [
        m("fact", fact_key="k1", status="refuted", ts_utc="2026-10-05T12:00:01.000000Z"),
        m("fact", fact_key="k1", status="verified", ts_utc="2026-10-05T12:00:05.000000Z"),  # later line wins
        m("fact", fact_key="k2", status="refuted"),
        m("fact", fact_key="k3", status="unverifiable"),
        m("attribution", hhi=third, shapley={"m1": third, "m2": third, "m3": third}, loo_final={"1": 3, "2": 3, "3": 3},
          decisive_facts={"reconcile": ["k1"], "R1": [], "R3": []}, cpu_s=0.5),
        m("result", answer=3, reducers={"R0": 3, "R1": 3, "R2": 3, "R3": 2, "ENS": 3}),
        m("change", gate="evidence"), m("change", gate="conformity"), m("change", gate="conformity"),
        m("attribution", item="PF-2", hhi=1.0, shapley={"m1": 1.0, "m2": 0.0}, loo_final={"1": 3, "2": 2},
          decisive_facts={"reconcile": [], "R1": [], "R3": []}, cpu_s=1.5),
        m("result", item="PF-2", answer=3, reducers={"R0": 3}),
    ]
    res = analyse(tmp_path, led, mediator=recs)
    g12 = lambda s: val(res, "M12", "PF", "E", s)  # noqa: E731
    assert (g12("n_facts"), g12("verified"), g12("refuted"), g12("unverifiable")) == (3, 1, 1, 1)
    assert g12("refuted_rate") == pytest.approx(1 / 3)
    assert g12("facts_per_item_arm") == pytest.approx(1.5)  # 3 facts over the 2 E item-arms that have a mediator ledger
    # M11: mean of HHI 1/3 and 1.0, one "dictator" (max share 1.0 >= 0.5) of two
    assert val(res, "M11", "PF", "E", "mean_hhi") == pytest.approx((1 / 3 + 1) / 2)
    assert val(res, "M11", "PF", "E", "dictator_share") == pytest.approx(0.5)
    # M13: PF-1 loo results all equal the end answer 3, PF-2 has one that differs
    assert val(res, "M13", "PF", "E", "estimate") == pytest.approx(0.5)
    # M14: one of two nodes has a decisive fact; flips 1 evidence, 2 conformity
    assert val(res, "M14", "PF", "E", "decisive_share") == pytest.approx(0.5)
    assert val(res, "M14", "PF", "E", "conformity_share") == pytest.approx(2 / 3)
    # M15: PF-1's reducers disagree (R3 = 2), PF-2 has only R0 (no comparison possible: excluded)
    assert (val(res, "M15", "PF", "E", "n"), val(res, "M15", "PF", "E", "n_disagree")) == (1, 1)
    assert val(res, "M18", "PF", "E", "cpu_s_median") == pytest.approx(1.0)


# ----------------------------------------------------------------------------------------------- bootstrap, seeds
def test_seeds_match_the_published_ones() -> None:
    for tag, published in r2.PUBLISHED_SEEDS.items():
        assert r2.seed_for(tag) == published, tag
    assert r2.AUROC_SEED == 3066176665


def test_bootstrap_constant_data_has_degenerate_interval_and_is_deterministic(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for j in range(1, 6):
        item = f"PF-{j}"
        led.call(item, "PF", "S*", tokens=100)
        led.item_arm(item, "PF", "S*")
        led.call(item, "PF", "E", tokens=400)  # log2(4) = 2 on every item
        led.item_arm(item, "PF", "E")
    led.end()
    res = analyse(tmp_path, led)
    assert val(res, "P1", "PF", "E-S*", "estimate") == 2.0
    assert val(res, "P1", "PF", "E-S*", "ci_lo") == 2.0 and val(res, "P1", "PF", "E-S*", "ci_hi") == 2.0
    a = r2.bootstrap_median([1.0, 2.0, 5.0, 7.0], 200, 12345)
    assert a == r2.bootstrap_median([1.0, 2.0, 5.0, 7.0], 200, 12345)
    assert a != r2.bootstrap_median([1.0, 2.0, 5.0, 7.0], 200, 12346)
    assert r2.percentile([0.0, 10.0], 0.025) == pytest.approx(0.25)  # linear interpolation


def test_auroc_function_with_ties() -> None:
    # positives x = 0.8; negatives 0, 0.4, 0.8 -> (1 + 1 + 0.5) / 3
    assert r2.auroc([0.8, 0.0, 0.4, 0.8], [1, 0, 0, 0]) == pytest.approx(2.5 / 3)
    assert r2.auroc([1.0, 2.0], [1, 1]) is None


# ------------------------------------------------------------------------------------- format, sort, robustness
def test_csv_format_sort_header_and_determinism(tmp_path: Path) -> None:
    led, grading = main_ledger()
    d = tmp_path / "run"
    led.write(d)
    grade(d, "PF", grading["PF"])
    outs = []
    for k in (1, 2):
        o = tmp_path / f"o{k}"
        assert r2.main(["--ledger", str(d), "--out", str(o), "--boot-b", "300"]) == 0
        outs.append(o)
    a, b = ((o / "results.csv").read_bytes() for o in outs)
    assert a == b  # deterministic
    lines = a.decode().splitlines()
    assert lines[0] == "quantity,class,arm,stat,value"
    rows = [tuple(x) for x in csv.reader(lines[1:])]
    assert rows == sorted(rows)  # sorted by all columns, as strings
    assert len(rows) == len(set(rows))
    for q, _c, _a, s, v in rows:
        assert v == format(float(v), ".9g")  # value formatted %.9g
        assert s and q
    meta = json.loads((outs[0] / "meta.json").read_text())
    assert meta["ledger_sha256"] == hashlib.sha256((d / "ledger.jsonl").read_bytes()).hexdigest()
    assert meta["bootstrap"]["seeds"]["eq|E-S*|P1"] == 943313030
    assert meta["bootstrap"]["seeds"]["eq|auroc"] == 3066176665
    cat = (outs[0] / "quantities.txt").read_text().splitlines()
    assert "H1\tCOMPARE_eq.md section 6 Primary (E vs S*)" in cat
    assert all("\t" in x for x in cat)
    assert {q for q, *_ in rows} <= {x.split("\t")[0] for x in cat}


def test_format_of_special_values() -> None:
    assert r2.fmt(8.0) == "8"
    assert r2.fmt(1 / 3) == "0.333333333"
    assert r2.fmt(float("inf")) == "inf"
    assert r2.fmt(1234567890.0) == "1.23456789e+09"


def _run(tmp: Path, content: bytes | None, name: str = "run") -> tuple[int, str, Path]:
    d = tmp / name
    d.mkdir()
    if content is not None:
        (d / "ledger.jsonl").write_bytes(content)
    cp = subprocess.run([sys.executable, str(HARNESS / "eq_route2.py"), "--ledger", str(d), "--out",
                         str(tmp / (name + "_o"))], capture_output=True, text=True, check=False)
    return cp.returncode, cp.stderr, tmp / (name + "_o")


def test_empty_partial_truncated_garbage_missing_never_traceback(tmp_path: Path) -> None:
    led, _grading = main_ledger()
    full = "".join(json.dumps(x) + "\n" for x in led.recs)
    cases = {
        "empty": b"",
        "start_only": (json.dumps(led.recs[0]) + "\n").encode(),
        "truncated": (full[: len(full) // 2] + '{"record": "call", "tru').encode(),
        "item_arms_only": "".join(json.dumps(x) + "\n" for x in led.recs if x["record"] == "item_arm").encode(),
    }
    for name, content in cases.items():
        rc, err, out = _run(tmp_path, content, name)
        assert rc == 0, (name, err)
        assert "Traceback" not in err, (name, err)
        assert (out / "results.csv").read_text().startswith("quantity,class,arm,stat,value\n")
        assert (out / "meta.json").is_file() and (out / "quantities.txt").is_file()
    assert "torn last line" in _run(tmp_path, cases["truncated"], "t2")[1]
    # binary garbage has bad lines in the middle: a hard error (exit 2), not a skip and not a traceback
    rc, err, _ = _run(tmp_path, bytes(range(256)) * 20, "garbage")
    assert rc == 2 and "not valid JSON" in err and "Traceback" not in err
    assert len((_run(tmp_path, cases["empty"], "e2")[2] / "results.csv").read_text().splitlines()) == 1
    # no ledger file at all, and no directory at all: a clean error (exit 2), not a traceback
    rc, err, _ = _run(tmp_path, None, "nofile")
    assert rc == 2 and "no ledger.jsonl" in err and "Traceback" not in err
    cp = subprocess.run([sys.executable, str(HARNESS / "eq_route2.py"), "--ledger", str(tmp_path / "nope"), "--out",
                         str(tmp_path / "x")], capture_output=True, text=True, check=False)
    assert cp.returncode == 2 and "Traceback" not in cp.stderr


# ------------------------------------------------------------------------- shared contract rows (routes 1 and 2)
def _simple(led: Ledger, item: str, cls: str, arms: tuple[str, ...] = ("S*", "E"), **kw: Any) -> None:
    for arm in arms:
        led.call(item, cls, arm)
        led.item_arm(item, cls, arm, **kw.get(arm, {}))


def _cli(tmp: Path, led: Ledger, grading: dict[str, str] | None = None, name: str = "run",
         extra: list[str] | None = None) -> tuple[int, str, Path]:
    """r2.main on a written ledger; grading maps a class to the raw text of its file (so a test can tear a line)."""
    d = tmp / name
    led.write(d)
    if grading:
        (d / "grading_results").mkdir()
        for cls, text in grading.items():
            (d / "grading_results" / f"{cls}.jsonl").write_text(text)
    rc = r2.main(["--ledger", str(d), "--out", str(tmp / (name + "_out")), "--boot-b", "50", *(extra or [])])
    return rc, "", tmp / (name + "_out")


def _gl(*rows: dict[str, Any]) -> str:
    base = {"ts_utc": "2026-10-05T13:00:00.000000Z", "exit": 0, "detail": {}}
    return "".join(json.dumps({**base, **x}) + "\n" for x in rows)


def _meta(out: Path) -> dict[str, Any]:
    return json.loads((out / "meta.json").read_text())


def test_wall_used_counts_and_exclude_flag(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for j in range(1, 5):
        _simple(led, f"PF-{j}", "PF", E={"wall_used": j == 2}, **{"S*": {"wall_used": j == 3}})
    led.end()
    grading = {"PF": _gl(*[{"item": f"PF-{j}", "label": lab, "score": str(s), "score_num": float(s)}
                           for j in range(1, 5) for lab, s in (("p1", 0), ("p3", 1))])}
    rc, _, out = _cli(tmp_path, led, grading, "all")
    assert rc == 0
    res = read_results(out)
    assert (val(res, "n_wall_used", "PF", "E", "n"), val(res, "n_wall_used", "PF", "S*", "n")) == (1, 1)
    assert val(res, "H1", "PF", "E-S*", "n_comparison") == 4
    assert val(res, "P3", "PF", "E", "n") == 4
    assert val(res, "M10", "PF", "E", "n") == 4
    assert _meta(out)["exclude_wall_used"] is False
    # the flag: every output is recomputed on the item-arms with wall_used false (items 2 and 3 lose a side)
    rc, _, out = _cli(tmp_path, led, grading, "ex", ["--exclude-wall-used"])
    assert rc == 0
    res = read_results(out)
    assert val(res, "H1", "PF", "E-S*", "n_comparison") == 2 and val(res, "H1", "PF", "E-S*", "wins") == 2
    assert val(res, "P1", "PF", "E-S*", "n") == 2
    assert val(res, "P2", "PF", "E", "n") == 3 and val(res, "P2", "PF", "S*", "n") == 3
    assert val(res, "P3", "PF", "E", "n") == 3 and val(res, "P3", "PF", "S*", "n") == 3
    # the calls of the excluded item-arms leave too
    assert val(res, "M10", "PF", "E", "n") == 3 and val(res, "M10", "PF", "S*", "n") == 3
    assert (val(res, "n_wall_used", "PF", "E", "n"), val(res, "n_wall_used", "PF", "S*", "n")) == (0, 0)
    meta = _meta(out)
    assert meta["exclude_wall_used"] is True and meta["wall_used_excluded"] == 2


def test_wall_used_absent_or_not_boolean_counts_as_false(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    _simple(led, "PF-1", "PF", E={"wall_used": "maybe"})  # not a boolean: false
    _simple(led, "PF-2", "PF", E={"wall_used": True})
    led.end()
    rc, _, out = _cli(tmp_path, led, None, "r", ["--exclude-wall-used"])
    assert rc == 0
    res = read_results(out)
    assert val(res, "P3", "PF", "E", "n") == 1
    assert val(res, "n_wall_used", "PF", "E", "n") == 0


def test_duplicate_item_arm_is_counted_and_warned(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    led.call("PF-1", "PF", "S*")
    led.item_arm("PF-1", "PF", "S*")
    # the same (item, arm, label) written twice: the later seq is used
    led.item_arm("PF-1", "PF", "S*", status="partial")
    _simple(led, "PF-2", "PF")
    # a declared re-run (p3 then p9) is not a duplicate
    led.call("PF-3", "PF", "E")
    led.item_arm("PF-3", "PF", "E", status="partial")
    led.item_arm("PF-3", "PF", "E", label="p9")
    led.end()
    rc, _, out = _cli(tmp_path, led, None, "r")
    assert rc == 0
    res = read_results(out)
    assert val(res, "n_dup_item_arm", "PF", "S*", "n") == 1
    assert val(res, "n_dup_item_arm", "PF", "E", "n") == 0  # explicit zero row
    w = [x for x in _meta(out)["warnings"] if "duplicate" in x]
    assert len(w) == 1 and "PF-1" in w[0] and "S*" in w[0] and "PF-3" not in w[0]
    # the later record is the one used: S* of PF-1 is a partial item-arm and scores 0 although it has no grading line
    assert val(res, "P2", "PF", "S*", "n") == 1  # PF-2 S* has no grading line


def test_unscored_and_missing_counts_by_class_and_arm(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for j in range(1, 5):
        _simple(led, f"PF-{j}", "PF")
    _simple(led, "DS-1", "DS")  # DS has no per-item-arm score by contract: not counted as unscored
    led.end()
    rows = [{"item": f"PF-{j}", "label": "p1", "score": "0", "score_num": 0.0} for j in range(1, 5)]
    rows += [{"item": "PF-1", "label": "p3", "score": "1", "score_num": 1.0},
             # PF-2 E: no grading line at all (missing)
             {"item": "PF-3", "label": "p3", "score": None, "score_num": None, "score_inf": False, "exit": 1},
             {"item": "PF-4", "label": "p3", "score": "1", "score_num": 1.0, "ts_utc": "2026-10-05T13:00:00.000000Z"},
             {"item": "PF-4", "label": "p3", "score": None, "score_num": None, "ts_utc": "2026-10-05T14:00:00.000000Z"}]
    rc, _, out = _cli(tmp_path, led, {"PF": _gl(*rows)}, "r")
    assert rc == 0
    res = read_results(out)
    # PF-2 (no line), PF-3 (null), PF-4 (the latest line is non-numeric)
    assert val(res, "n_unscored", "PF", "E", "n") == 3
    assert val(res, "n_missing", "PF", "E", "n") == 1  # only PF-2 has no line at all
    assert val(res, "n_unscored", "PF", "S*", "n") == 0 and val(res, "n_missing", "PF", "S*", "n") == 0
    assert ("n_unscored", "DS", "E", "n") not in res
    assert val(res, "H1", "PF", "E-S*", "n_comparison") == 1  # PF-1 only
    assert val(res, "P2", "PF", "E", "n") == 1
    assert any("unscored" in w for w in _meta(out)["warnings"])


def test_es_inf_only_on_score_inf_or_the_string_inf(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    for k in "abcdefg":
        _simple(led, f"ES-{k}", "ES")
    _simple(led, "PF-1", "PF")
    led.end()
    base = {"score_num": None, "score_inf": False}
    rows = [{"item": f"ES-{k}", "label": "p1", "score": "1.0", "score_num": 1.0, "score_inf": False} for k in "abcdefg"]
    rows += [
        {"item": "ES-a", "label": "p3", "score": None, **base},  # oracle failure: unscored, NOT a loss
        {"item": "ES-b", "label": "p3", "score": "inf", **base},  # the string inf: infinite, a loss
        {"item": "ES-c", "label": "p3", "score": "inf", "score_num": None, "score_inf": True},  # a loss
        {"item": "ES-d", "label": "p3", "score": "Infinity", **base},  # not the string inf: unscored
        {"item": "ES-e", "label": "p3", "score": "nan", **base},  # unscored
        {"item": "ES-f", "label": "p3", "score": "0.5", "score_num": 0.5, "score_inf": False},  # a win
        # g: no line at all
        {"item": "PF-1", "label": "p1", "score": "1", "score_num": 1.0},
        # score_inf outside ES: unscored
        {"item": "PF-1", "label": "p3", "score": None, "score_num": None, "score_inf": True},
    ]
    rc, _, out = _cli(tmp_path, led, {"ES": _gl(*[r for r in rows if r["item"].startswith("ES")]),
                                      "PF": _gl(*[r for r in rows if r["item"].startswith("PF")])}, "r")
    assert rc == 0
    res = read_results(out)
    g = lambda s: val(res, "H1", "ES", "E-S*", s)  # noqa: E731
    assert (g("wins"), g("losses"), g("ties"), g("n_comparison")) == (1, 2, 0, 3)
    assert val(res, "n_unscored", "ES", "E", "n") == 4 and val(res, "n_missing", "ES", "E", "n") == 1  # a d e g; g
    assert val(res, "P2", "ES", "E", "n") == 3
    assert val(res, "n_unscored", "PF", "E", "n") == 1
    assert ("H1", "PF", "E-S*", "n_comparison") not in res


def test_latest_line_ties_on_ts_utc_break_by_line_number(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    _simple(led, "PF-1", "PF")
    _simple(led, "PF-2", "PF")
    led.end()
    t = "2026-10-05T13:00:00.000000Z"
    rows = [
        {"ts_utc": t, "item": "PF-1", "label": "p3", "score": "0", "score_num": 0.0},
        {"ts_utc": t, "item": "PF-1", "label": "p3", "score": "1", "score_num": 1.0},  # same ts_utc, later line: wins
        {"ts_utc": t, "item": "PF-1", "label": "p1", "score": "1", "score_num": 1.0},
        {"ts_utc": t, "item": "PF-1", "label": "p1", "score": "0", "score_num": 0.0},  # later line: S* = 0
        # PF-2 E: the numeric line is newer by ts_utc although it comes first in the file: the older null line loses
        {"ts_utc": "2026-10-05T15:00:00.000000Z", "item": "PF-2", "label": "p3", "score": "1", "score_num": 1.0},
        {"ts_utc": "2026-10-05T12:00:00.000000Z", "item": "PF-2", "label": "p3", "score": None, "score_num": None},
        {"ts_utc": t, "item": "PF-2", "label": "p1", "score": "0", "score_num": 0.0},
    ]
    rc, _, out = _cli(tmp_path, led, {"PF": _gl(*rows)}, "r")
    assert rc == 0
    res = read_results(out)
    assert (val(res, "H1", "PF", "E-S*", "wins"), val(res, "H1", "PF", "E-S*", "n_comparison")) == (2, 2)
    assert val(res, "n_unscored", "PF", "E", "n") == 0


def test_torn_mid_ledger_line_is_a_hard_error_but_a_torn_last_line_is_a_warning(
        tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    led, _g = main_ledger()
    lines = [json.dumps(x) + "\n" for x in led.recs]
    mid = "".join(lines[:7]) + lines[7][:30] + "\n" + "".join(lines[8:])
    rc, err, _ = _run(tmp_path, mid.encode(), "mid")
    assert rc == 2 and "line 8 is not valid JSON" in err and "Traceback" not in err
    assert not (tmp_path / "mid_o" / "results.csv").exists()
    # a bad last line that ends with a newline was not a torn append: also an error
    rc, err, _ = _run(tmp_path, ("".join(lines) + "{bad\n").encode(), "nl")
    assert rc == 2 and "not valid JSON" in err
    # only the final fragment without a newline is a torn append: skipped with a warning
    rc, err, out = _run(tmp_path, ("".join(lines) + lines[3][:25]).encode(), "last")
    assert rc == 0 and "torn last line" in err
    assert any("torn last line" in w for w in _meta(out)["warnings"])
    # a line that is JSON but not an object is an error wherever it is
    rc, err, _ = _run(tmp_path, ("".join(lines[:3]) + "[1, 2]\n" + "".join(lines[3:])).encode(), "arr")
    assert rc == 2 and "not a JSON object" in err
    # grading files follow the same rule
    led2, _ = main_ledger()
    good = _gl({"item": "PF-1", "label": "p1", "score": "0", "score_num": 0.0})
    capsys.readouterr()
    rc, _, _ = _cli(tmp_path, led2, {"PF": good + "{torn\n" + good}, "g1")
    assert rc == 2
    assert "PF.jsonl" in capsys.readouterr().err
    rc, _, out = _cli(tmp_path, led2, {"PF": good + '{"item": "PF-2", "la'}, "g2")
    assert rc == 0 and any("torn last line" in w for w in _meta(out)["warnings"])


def test_missing_run_end_is_a_warning(tmp_path: Path) -> None:
    led = Ledger()
    led.start()
    _simple(led, "PF-1", "PF")
    rc, _, out = _cli(tmp_path, led, None, "r")
    assert rc == 0
    assert any("no run_end" in w for w in _meta(out)["warnings"])


def test_uv_script_entry_point_runs(tmp_path: Path) -> None:
    led, grading = main_ledger()
    d = tmp_path / "run"
    led.write(d)
    grade(d, "PF", grading["PF"])
    cp = subprocess.run(["uv", "run", "--script", "--quiet", str(HARNESS / "eq_route2.py"), "--ledger", str(d), "--out",
                         str(tmp_path / "o"), "--boot-b", "100"], capture_output=True, text=True, check=False)
    assert cp.returncode == 0, cp.stderr
    assert (tmp_path / "o" / "results.csv").read_text().startswith("quantity,class,arm,stat,value\n")
