"""Ratio underflow (A6 implementation note): |ln(a / b)| with a / b underflowing to 0 (1e-300 against 1e300) made
math.log raise ValueError and stopped a run or a calibration on a valid (positive, finite) numeric answer. Every such
site now uses |ln a - ln b| where the ratio leaves the float range: eq_harness.abs_ln_ratio (kappa_numeric,
numeric_top, same_numeric), eq_mediator.cluster (numeric near/far), eq_calibrate.abs_ln_ratio (es_error, the numeric
LOO lambda, grade_answer for ES)."""

from __future__ import annotations

import math
from types import SimpleNamespace

import eq_calibrate as cal
import eq_harness as eh
import eq_mediator as med

TINY, HUGE = 1e-300, 1e300
GAP = math.log(HUGE) - math.log(TINY)  # about 1381.55


def test_harness_numeric_helpers_survive_underflow() -> None:
    assert TINY / HUGE == 0.0  # the premise: the ratio underflows
    assert math.isclose(eh.abs_ln_ratio(TINY, HUGE), GAP) and math.isclose(eh.abs_ln_ratio(2.0, 1.0), math.log(2))
    vals = [TINY, HUGE, HUGE]
    assert eh.median_ln(vals) == HUGE and eh.numeric_top(vals) == 2 and eh.kappa_numeric(vals) == 2 / 3
    assert eh.same_numeric(TINY, HUGE) is False and eh.same_numeric(TINY, TINY) is True


def test_mediator_numeric_clusters_survive_underflow() -> None:
    ctx = med.Ctx(family="numeric")
    outs = [med.MemberOut(1, TINY), med.MemberOut(2, HUGE), med.MemberOut(3, HUGE)]
    assert med.cluster(outs, ctx) == {1: "far", 2: "near", 3: "near"}
    assert med.cluster(outs, ctx, final=TINY) == {1: "near", 2: "far", 3: "far"}


def test_calibrate_ratio_sites_survive_underflow_and_overflow() -> None:
    assert math.isclose(cal.abs_ln_ratio(TINY, HUGE), GAP) and math.isclose(cal.abs_ln_ratio(HUGE, TINY), GAP)
    assert HUGE / TINY == math.inf  # overflow: exact here too (a score, not a threshold)
    assert math.isclose(cal.abs_ln_ratio(3.0, 1.5), math.log(2))
    assert math.isclose(cal.es_error(eh, [TINY], HUGE), GAP)
    me = SimpleNamespace(eh=eh)
    assert cal.Cal.loo_lambda_numeric(me, [TINY, HUGE, HUGE]) == 1 / 3  # only dropping TINY keeps the median
    me = SimpleNamespace(eh=eh, st=SimpleNamespace(truth={"ES-1": HUGE}))
    assert math.isclose(cal.Cal.grade_answer(me, "ES", "ES-1", "p3", TINY), GAP)
    assert cal.Cal.grade_answer(me, "ES", "ES-1", "p3", "nan") == math.inf  # not a positive number: abstention
