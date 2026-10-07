"""Evidence gate: an unverifiable change is rejected (conformity), a verifiable one is accepted."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

import eq_harness as eh
import eq_mediator as md
from conftest import dry_run, ledger


@pytest.fixture
def copy(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f(x):\n    return x + 1  # off by one\n")
    (tmp_path / "corpus.txt").write_text("The capital of X is Y1.\nOther text.\n")
    (tmp_path / "check.sh").write_text("#!/bin/sh\necho all 3 tests passed\nexit 0\n")
    (tmp_path.parent / "secret.txt").write_text("outside\n")
    return tmp_path


def ev(kind: str, ref: str, detail: str) -> dict[str, str]:
    return {"kind": kind, "ref": ref, "detail": detail}


def vf(fixture: Path, pc: list[str] | None = None,
       checker: Callable[[Mapping[str, Any]], bool | None] | None = None) -> Callable[[Mapping[str, Any]], bool]:
    """The gate's verify: a fact counts iff the mediator's verify() calls it verified (pristine fixture)."""
    return lambda e: md.verify(e, fixture, public_check=pc, checker=checker)[0] == md.VERIFIED


def test_verifier_kinds(copy: Path) -> None:
    v = vf(copy, ["sh", "check.sh"])
    assert v(ev("file_line", "src/a.py:2", "return x + 1"))
    assert v(ev("file_line", "src/a.py:1", "return x + 1"))  # window l-1..l+1 (MEDIATOR §1)
    assert not v(ev("file_line", "src/a.py:99", "x"))
    assert not v(ev("file_line", "src/a.py", "return x + 1"))  # file_line needs a line
    assert v(ev("quote", "corpus.txt", "capital of   X is Y1"))
    assert not v(ev("quote", "corpus.txt", "capital of X is Y2"))
    assert not v(ev("quote", "../secret.txt", "outside"))  # escapes the fixture
    assert not v(ev("quote", str(copy.parent / "secret.txt"), "outside"))
    assert v(ev("command", "sh check.sh", "exit 0"))
    assert v(ev("test", "sh check.sh", "all 3 tests passed"))
    assert not v(ev("command", "sh check.sh", "exit 1"))
    assert not v(ev("command", "rm -rf src", "exit 0"))  # not the public check: never run
    assert (copy / "src" / "a.py").exists()
    assert not v(ev("counterexample", "x", "y"))  # no checker configured
    assert vf(copy, checker=lambda e: e["ref"] == "n=7")(ev("counterexample", "n=7", ""))
    assert not v(ev("vibes", "x", "y"))


def test_gate_decisions(copy: Path) -> None:
    v = vf(copy, ["sh", "check.sh"])
    old = [ev("quote", "corpus.txt", "Other text.")]
    d = eh.evidence_gate("Y2", old, "Y2", [], v)
    assert not d.changed and d.final_answer == "Y2"
    d = eh.evidence_gate("Y2", old, "Y1", [], v)
    assert d.changed and not d.accepted and d.final_answer == "Y2" and d.reason.startswith("conformity")
    d = eh.evidence_gate("Y2", old, "Y1", old, v)  # re-cited old evidence is not new
    assert not d.accepted and d.final_answer == "Y2"
    d = eh.evidence_gate("Y2", old, "Y1", [ev("quote", "corpus.txt", "capital of X is Y9")], v)
    assert not d.accepted and d.final_answer == "Y2" and d.reason == "conformity: new evidence not verifiable"
    d = eh.evidence_gate("Y2", old, "Y1", [ev("quote", "corpus.txt", "The capital of X is Y1.")], v)
    assert d.accepted and d.final_answer == "Y1" and len(d.verified) == 1
    d = eh.evidence_gate(100.0, [], 100.0 * (1 + 1e-12), [ev("quote", "corpus.txt", "Y1")], v,
                         eh.same_numeric)
    assert not d.changed
    d = eh.evidence_gate(None, [], "Y1", [ev("quote", "corpus.txt", "Y1")], v)
    assert d.accepted


def _rs_script() -> dict[str, dict]:
    def so(a: str, evs: list[dict[str, str]] | None = None) -> dict:
        return {"structured_output": {"answer": a, "evidence": evs or [], "confidence": 0.5}}

    q1 = ev("quote", "doc1.txt", "the capital of X is Y1")
    s = {f"RS-DEV1|p3|m{i}/5": so(a, [q1] if i == 3 else None)
         for i, a in zip(range(1, 6), ["Y1", "Y1", "Y2", "Y2", "Y3"], strict=True)}
    s.update({
        "RS-DEV1|p3|m1/5>r1": so("Y1"),
        "RS-DEV1|p3|m2/5>r1": so("Y1"),
        "RS-DEV1|p3|m3/5>r1": so("Y1", [q1]),  # same evidence as round 0: not new
        "RS-DEV1|p3|m4/5>r1": so("Y1", [ev("quote", "doc1.txt", "the capital of X is Y7")]),  # false quote
        "RS-DEV1|p3|m5/5>r1": so("Y1", [ev("file_line", "doc1.txt:2", "the capital of X is Y1")]),
    })
    return s


def test_reconcile_end_to_end(stub_bin: Path, tmp_path: Path) -> None:
    run = dry_run(stub_bin, tmp_path, _rs_script(), only=["RS-DEV1"])
    recs = [r for r in ledger(run) if r.get("label") == "p3"]
    red = [r for r in recs if r["record"] == "reduce" and r["reducer"] == "plurality"]
    assert red[0]["round"] == 0 and red[0]["top"] == 2 and red[0]["stop"] is False and red[0]["quorum"] == 3
    rec = {r["member"]: r for r in recs if r["record"] == "reconcile"}
    assert set(rec) == {1, 2, 3, 4, 5}
    assert not rec[1]["changed"] and not rec[2]["changed"]
    assert rec[3]["conformity"] and rec[3]["reason"] == "conformity: no new evidence"
    assert rec[4]["conformity"] and rec[4]["reason"] == "conformity: new evidence not verifiable"
    assert rec[5]["accepted"] and rec[5]["verified_evidence"]
    assert red[-1]["round"] == 1 and red[-1]["answer"] == "Y1" and red[-1]["top"] == 3
    arm = next(r for r in recs if r["record"] == "item_arm")
    assert arm["answer"] == "Y1" and arm["rounds"] == 1 and arm["kappa0"] == 0.4
    calls = [r for r in recs if r["record"] == "call" and r["role"] == "r1"]
    assert len(calls) == 5 and all(c["resume"] for c in calls)
    first = {r["member"]: r["cwd"] for r in recs if r["record"] == "call" and r["role"].startswith("m")}
    assert all(c["cwd"] == first[c["member"]] for c in calls)  # resume runs in the member's own copy
    # A0.2: one equivalence call (role ver, cap 0.05B from the reconcile reserve) since round 0 left 3 clusters
    eqc = [r for r in recs if r["record"] == "call" and r["role"] == "ver"]
    assert len(eqc) == 1 and eqc[0]["cap_usd"] == "0.100000" and eqc[0]["agent"] == "verifier"
    assert {c["cap_usd"] for c in calls} == {"0.080000"}  # (0.25 - 0.05) B / 5 at B = 2
    # mediator ledger (MEDIATOR §1)
    (mp,) = (run / "raw" / "d" / "RS-DEV1" / "p3").glob("mediator.jsonl")
    m = [json.loads(x) for x in mp.read_text().splitlines()]
    kinds = [r["record"] for r in m]
    assert kinds.count("claim") == 10 and kinds.count("result") == 1
    att = [r for r in m if r["record"] == "attribution"]  # spec §4.1: one per round (0, 1) + the end-of-node one
    assert [r.get("round") for r in att] == [0, 1, None] and att[-1] == [r for r in m if r["record"] in (
        "result", "attribution")][-1]
    facts = {r["fact_key"]: r for r in m if r["record"] == "fact"}
    assert len(facts) == 3 and sorted(f["status"] for f in facts.values()) == ["refuted", "verified", "verified"]
    ch = {r["member"]: r for r in m if r["record"] == "change"}
    assert ch["m3"]["gate"] == "conformity" and ch["m4"]["gate"] == "conformity" and ch["m5"]["gate"] == "evidence"
    res = next(r for r in m if r["record"] == "result")
    assert res["answer"] == "Y1" and res["kappa"]["label"] == "agreement, not probability"
    assert res["reducers"]["R3"] == "Y2" and res["reducers"]["R1"] == res["reducers"]["R0"]  # m3's verified quote
    att = next(r for r in m if r["record"] == "attribution")
    tot = sum(v["num"] / v["den"] for v in att["shapley"].values())
    assert abs(tot - 1.0) < 1e-12  # v(N) - v(empty) = 1 - 0
