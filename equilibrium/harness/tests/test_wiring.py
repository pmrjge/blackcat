"""Stage-2 wiring of the LOO views and the per-round attribution in the live E arm (RUNTIME_EQUILIBRIUM §4.1-§4.2,
COMPARE_eq §12 A6.2): flags `loo_view` none / rotation / random / leader on a stage-d run with scripted members
(RS-DEV1 answers A A B B C, ES-DEV1 estimates 1 .. 1e8: no quorum, one reconcile round, nobody changes). Checks the
reconcile calls' `loo_view`/`loo_exclude`, the view each member was shown (none: one shared summary, byte-identical
across members; else the histogram without the excluded member's answer) and the mediator's per-round `attribution`
lines (λ and pivotal members by hand)."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

import eq_harness as eh
import eq_mediator as em
from conftest import FIXT_FLAGS, ITEMS, run_harness, stub_env

N = 5
RS = dict(enumerate(("label A", "label A", "label B", "label B", "label C"), start=1))
ES = dict(enumerate((1.0, 100.0, 1e4, 1e6, 1e8), start=1))


def script() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item, answers in (("RS-DEV1", RS), ("ES-DEV1", ES)):
        for m, v in answers.items():
            so = {"structured_output": {"answer": v, "evidence": [], "confidence": 0.5}}
            out[f"{item}|p3|m{m}/{N}"] = so
            out[f"{item}|p3|m{m}/{N}>r1"] = so  # the reconcile re-ask keeps the answer (no new evidence)
    return out


@pytest.fixture(scope="module", params=["none", "rotation", "random", "leader"])
def wired(request: pytest.FixtureRequest, stub_bin: Path, tmp_path_factory: pytest.TempPathFactory
          ) -> Iterator[dict[str, Any]]:
    v = str(request.param)
    tmp = tmp_path_factory.mktemp(f"wire-{v}")
    (tmp / "script.json").write_text(json.dumps(script()))
    env = stub_env(stub_bin, tmp, EQ_STUB_SCRIPT=str(tmp / "script.json"))
    sched = tmp / "s.tsv"
    assert run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(sched)], env).returncode == 0
    (tmp / "flags.json").write_text(json.dumps({**FIXT_FLAGS, "loo_view": v}))
    cp = run_harness(["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items",
                      str(ITEMS), "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--no-check",
                      "--only", "RS-DEV1", "ES-DEV1"], env)
    assert cp.returncode == 0, cp.stderr
    yield {"variant": v, "tmp": tmp, "recs": eh.read_ledger(tmp / "eq" / "runs" / "d" / "ledger.jsonl")}


def r1_calls(w: dict[str, Any], item: str) -> dict[int, dict[str, Any]]:
    out = {r["member"]: r for r in w["recs"] if r["record"] == "call" and r["item"] == item and r["label"] == "p3"
           and r["role"] == "r1"}
    assert sorted(out) == list(range(1, N + 1))
    return out


def histogram(prompt: str) -> Counter[str]:
    return Counter({m.group(1): int(m.group(2)) for m in re.finditer(r'^- "([^"]*)": (\d+)$', prompt, re.M)})


def test_reconcile_calls_record_the_variant_and_its_exclusion(wired: dict[str, Any]) -> None:
    v = wired["variant"]
    for item in ("RS-DEV1", "ES-DEV1"):
        calls = r1_calls(wired, item)
        ex = {m: c["loo_exclude"] for m, c in calls.items()}
        assert {c["loo_view"] for c in calls.values()} == {v} and all(c["round"] == 1 for c in calls.values())
        seed = f"{item}|p3|E"
        if v == "none":
            assert set(ex.values()) == {None}
        elif v == "rotation":
            assert ex == {m: (m - 1 + 1) % N + 1 for m in calls}
        elif v == "random":
            assert ex == {m: em.loo_exclude("random", m, 1, N, seed=seed) for m in calls}
        else:  # leader L (a top-cluster member): every other member leaves L out, L leaves out its rotation
            rot = {m: m % N + 1 for m in calls}
            leaders = {e for m, e in ex.items() if e != rot[m]}
            assert len(leaders) == 1, ex
            lead = leaders.pop()
            assert ex[lead] == rot[lead] and all(e == lead for m, e in ex.items() if m != lead)
            tops = [[m for m, a in RS.items() if a == lab] for lab in ("label A", "label B")] if item == "RS-DEV1" \
                else [[3]]  # ES: the near cluster of 1 .. 1e8 is the median member alone
            assert any(ex == {m: em.loo_exclude("leader", m, 1, N, seed=seed, top=t) for m in calls} for t in tops)
        assert all(e is None or (e != m and 1 <= e <= N) for m, e in ex.items())


def test_views_shown_match_the_exclusion(wired: dict[str, Any]) -> None:
    calls = r1_calls(wired, "RS-DEV1")
    prompts = {m: Path(c["prompt_path"]).read_text() for m, c in calls.items()}
    full = Counter(RS.values())
    for m, c in calls.items():
        e = c["loo_exclude"]
        assert prompts[m].startswith("RS-DEV1 p3 r1\nReconcile round 1. ")
        assert histogram(prompts[m]) == (full if e is None else full - Counter([RS[e]]))
    by_e: dict[Any, set[str]] = {}
    for m, c in calls.items():
        by_e.setdefault(c["loo_exclude"], set()).add(prompts[m])
    assert all(len(s) == 1 for s in by_e.values())  # one rendering per distinct exclusion
    if wired["variant"] == "none":  # the pre-registered shared summary: byte-identical for every member
        assert len(set(prompts.values())) == 1
        es = {Path(c["prompt_path"]).read_text() for c in r1_calls(wired, "ES-DEV1").values()}
        assert len(es) == 1 and "Estimates (sorted): 1, 100, 10000, 1e+06, 1e+08" in es.pop()


def attribution(w: dict[str, Any], item: str) -> list[dict[str, Any]]:
    p = w["tmp"] / "raw" / "d" / item / "p3" / "mediator.jsonl"
    return [o for o in map(json.loads, p.read_text().splitlines()) if o.get("record") == "attribution"]


def test_per_round_attribution_lambda_by_hand(wired: dict[str, Any]) -> None:
    for item, lam in (("ES-DEV1", 0.2), ("RS-DEV1", 0.6)):
        att = attribution(wired, item)
        per_round = [a for a in att if a.get("round") is not None]
        assert [a["round"] for a in per_round] == [0, 1]  # nobody changed: a fixed point after round 1
        assert len(att) == len(per_round) + 1 and "round" not in att[-1]  # finish(): the end-of-node line, last
        for a in per_round:
            assert a["lambda"] == pytest.approx(lam) and set(a["loo"]) == {f"m{i}" for i in range(1, N + 1)}
            if item == "ES-DEV1":
                # median 1e4; leaving out m3 keeps it (median of 100 and 1e6), any other member moves it 10x
                assert a["pivotal"] == ["m1", "m2", "m4", "m5"] and a["loo"]["m3"]["stable"] is True
            else:
                win = next(r["answer"] for r in wired["recs"] if r["record"] == "reduce" and r["item"] == item
                           and r["label"] == "p3" and r.get("round") == a["round"] and r.get("reducer") == "plurality")
                assert win in ("label A", "label B")  # the A/B tie, broken by the seeded order
                assert a["pivotal"] == [f"m{m}" for m, x in RS.items() if x == win]  # only the winners pivot
            assert a["seed"] == eh.derive_seed(eh.SEED_TIES, f"{item}|p3|E|loo|r{a['round']}")
