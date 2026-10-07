"""N24#5: an adversarial failing PF/CP answer can suppress the oracle's authenticated verdict (`kill -9 -1` from
compile-time code, or flooding the shared stream after the verdict), and `score` then wrote score null: the item-arm
dropped out of both analysis routes (selection on outcome). flags.json `no_verdict_policy` chooses the treatment:
"zero" (the default since the USER's decision of 2026-10-05, COMPARE_eq §12 amendment) re-runs once with healthy
isolation and then scores 0, also for an authenticated verdict whose score is null (R2c F1); "unscored" keeps the
originally pre-registered behaviour. Fake container CLI, fake Isolation.run: no container services, no oracle runs."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_isolation import dflags, eqv1

import eq_harness as eh
from conftest import ITEMS

Out = Callable[[eh.IsoCall], tuple[int | None, str]]


@pytest.fixture
def fake_run(monkeypatch: pytest.MonkeyPatch, clog: Path) -> tuple[list[eh.IsoCall], list[Out]]:
    """Isolation.run replaced: each call pops the next scripted output, else (137, "") = killed, no verdict line."""
    calls: list[eh.IsoCall] = []
    outs: list[Out] = []

    def run(self: eh.Isolation, call: eh.IsoCall, timeout_s: float) -> tuple[int | None, str]:
        calls.append(call)
        return outs.pop(0)(call) if outs else (137, "")

    monkeypatch.setattr(eh.Isolation, "run", run)
    return calls, outs


def score(tmp_path: Path, **over: Any) -> tuple[int, list[dict[str, Any]]]:
    eq = tmp_path / "eq"
    runs = eq / "runs" / "d"
    runs.mkdir(parents=True, exist_ok=True)
    led = runs / "ledger.jsonl"
    if not led.exists():
        eh.Ledger(led).append("item_arm", cls="PF", item="PF-DEV1", label="p1", status="ok",
                              answer="theorem t : True := trivial")
    fp = tmp_path / "flags.json"
    fp.write_text(json.dumps(dflags(**over)))
    rc = eh.cmd_score(argparse.Namespace(stage="d", cls="PF", eq_root=str(eq), items=str(ITEMS), flags=str(fp)))
    res = runs / "grading_results" / "PF.jsonl"
    return rc, [json.loads(ln) for ln in res.read_text().splitlines()] if res.exists() else []


def test_default_policy_is_zero(tmp_path: Path, fake_run: Any) -> None:
    """USER decision 2026-10-05 (COMPARE_eq §12 amendment): 'zero' is the default in both places."""
    assert eh.DEFAULT_FLAGS["no_verdict_policy"] == "zero"
    assert json.loads((eh.HERE / "flags.json").read_text())["no_verdict_policy"] == "zero"
    calls, _ = fake_run
    rc, recs = score(tmp_path)
    assert rc == 1 and len(calls) == 2 and len(recs) == 1
    assert (recs[0]["score"], recs[0]["detail"]) == (0, "no authenticated verdict (scored 0)")


def test_unscored_policy_keeps_the_pre_registered_behaviour(tmp_path: Path, fake_run: Any) -> None:
    calls, _ = fake_run
    rc, recs = score(tmp_path, no_verdict_policy="unscored")
    assert rc == 1 and len(calls) == 1 and len(recs) == 1
    r = recs[0]
    assert r["score"] is None and r["score_num"] is None and r["score_inf"] is False and r["exit"] == 1
    assert r["detail"].startswith("oracle error: 0 authenticated verdict lines (exit 137)")


def test_zero_policy_reruns_once_then_scores_zero(tmp_path: Path, fake_run: Any) -> None:
    calls, _ = fake_run
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 1 and len(calls) == 2 and len(recs) == 1  # one re-run, still an oracle failure (n_bad, exit kept)
    r = recs[0]
    assert (r["score"], r["score_num"], r["score_inf"], r["exit"]) == (0, 0.0, False, 1)
    assert r["detail"] == "no authenticated verdict (scored 0)"


def test_zero_policy_keeps_a_verdict_the_rerun_produces(tmp_path: Path, fake_run: Any) -> None:
    calls, outs = fake_run
    outs += [lambda c: (137, ""), lambda c: (0, eqv1(c, {"score": 1, "detail": "proof checks"}))]
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 0 and len(calls) == 2
    assert (recs[0]["score"], recs[0]["exit"], recs[0]["detail"]) == (1, 0, "proof checks")


def null_verdict(c: eh.IsoCall) -> tuple[int, str]:
    """PF answer code killed check_lean.sh (or the concurrent statement build): the oracle still prints ONE
    authenticated line, score null, exit 3 ('checker error'; oracle.py)."""
    return 3, eqv1(c, {"item": "PF-DEV1", "score": None, "detail": "checker error rc=-9: "})


def test_zero_policy_scores_an_authenticated_null_verdict_zero(tmp_path: Path, fake_run: Any) -> None:
    """R2c F1: under 'zero' an authenticated verdict whose score parses to None must not leave the unit unscored:
    re-run once (isolation healthy), then score 0."""
    calls, outs = fake_run
    outs += [null_verdict, null_verdict]
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 1 and len(calls) == 2 and len(recs) == 1
    r = recs[0]
    assert (r["score"], r["score_num"], r["score_inf"], r["exit"]) == (0, 0.0, False, 3), r
    assert r["detail"] == "authenticated verdict without a score (scored 0)"


def test_zero_policy_keeps_a_verdict_the_rerun_of_a_null_verdict_produces(tmp_path: Path, fake_run: Any) -> None:
    calls, outs = fake_run
    outs += [null_verdict, lambda c: (0, eqv1(c, {"score": 1, "detail": "proof checks"}))]
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 0 and len(calls) == 2
    assert (recs[0]["score"], recs[0]["exit"], recs[0]["detail"]) == (1, 0, "proof checks")


def test_unscored_policy_keeps_an_authenticated_null_verdict_null(tmp_path: Path, fake_run: Any) -> None:
    calls, outs = fake_run
    outs += [null_verdict]
    rc, recs = score(tmp_path, no_verdict_policy="unscored")
    assert rc == 1 and len(calls) == 1
    assert (recs[0]["score"], recs[0]["score_num"], recs[0]["detail"]) == (None, None, "checker error rc=-9: ")


def test_zero_policy_never_zeroes_a_host_side_oracle_error(tmp_path: Path, fake_run: Any,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """Only a missing or score-less AUTHENTICATED verdict is the answer's doing; a host OSError is not."""
    monkeypatch.setattr(eh, "run_oracle", lambda *a, **k: (1, "oracle error: OSError"))
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 1 and len(recs) == 1
    assert (recs[0]["score"], recs[0]["detail"]) == (None, "oracle error: OSError")


def test_zero_policy_never_scores_when_isolation_is_unhealthy(tmp_path: Path, fake_run: Any,
                                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing verdict caused by lost container services is not the answer's doing: re-check isolation first,
    stop on error."""
    calls, _ = fake_run
    real = eh.Isolation.preflight
    n = {"k": 0}

    def preflight(self: eh.Isolation, classes: Any) -> None:
        n["k"] += 1
        if n["k"] > 1:
            raise eh.IsolationError("the container services are not reachable (fake)")
        real(self, classes)

    monkeypatch.setattr(eh.Isolation, "preflight", preflight)
    rc, recs = score(tmp_path, no_verdict_policy="zero")
    assert rc == 2 and len(calls) == 1 and recs == []


def test_unknown_no_verdict_policy_is_refused(tmp_path: Path, fake_run: Any) -> None:
    calls, _ = fake_run
    rc, recs = score(tmp_path, no_verdict_policy="maybe")
    assert rc == 2 and calls == [] and recs == []
