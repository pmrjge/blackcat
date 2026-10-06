"""CR grading: oracle grader records relabelled per (item, arm, node, member), verdicts routed back, scored."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from test_blinding import LEAK

import eq_harness as eh
from conftest import ITEMS, ledger, run_harness, stub_env


def recs(n: int, match_first: bool = True) -> list[dict]:
    return [{"rid": f"f{i}", "type": "match" if (i == 0 and match_first) else "unmatched",
             "finding": {"file": "a.py", "line": i + 1, "claim": f"claim {i} (p3 m2/5 said so)"},
             **({"seeded_bug": {"file": "a.py", "line": 1, "description": "d"}} if i == 0 and match_first else {}),
             "code_excerpt": "   1  x = 1"} for i in range(n)]


UNITS = [({"item": "CR-0001", "label": "p1", "node": None, "member": None}, recs(2)),
         ({"item": "CR-0001", "label": "p3", "node": None, "member": None}, recs(2)),
         ({"item": "CR-0001", "label": "p3", "node": None, "member": 2}, recs(3, False)),
         ({"item": "CR-0002", "label": "p4", "node": "b", "member": 1}, recs(1))]


def test_relabel_unique_blind_and_order_free() -> None:
    batch, key = eh.cr_relabel(UNITS, "p")
    toks = [b["rid"] for b in batch]
    assert len(toks) == 8 == len(set(toks)) == len(key["tokens"])  # f0/f1 repeat across answers; tokens do not
    assert all(t.startswith("g") and not t.startswith("f") for t in toks)
    assert not LEAK.search(json.dumps(batch))
    assert all(set(b) <= {"rid", "type", "finding", "seeded_bug", "code_excerpt"} for b in batch)
    assert sum(b["type"] == "match" for b in batch) == 3 and all("seeded_bug" in b for b in batch
                                                                  if b["type"] == "match")
    back = {(json.loads(v["unit"])[1], json.loads(v["unit"])[3], v["rid"]) for v in key["tokens"].values()}
    assert ("p3", 2, "f2") in back and ("p1", None, "f0") in back and len(back) == 8
    shuffled = list(UNITS)
    random.Random(1).shuffle(shuffled)
    assert eh.cr_relabel(shuffled, "p") == (batch, key)
    assert len(key["regrade"]) == 2


def test_split_verdicts_routes_and_validates() -> None:
    batch, key = eh.cr_relabel(UNITS, "p")
    vs = [{"rid": b["rid"], "verdict": "true" if b["type"] == "match" else "false", "note": "n"} for b in batch]
    per, problems = eh.cr_split_verdicts(vs, key)
    assert problems == [] and sum(len(v) for v in per.values()) == 8
    u = eh.cr_unit_key(UNITS[2][0])
    assert [x["rid"] for x in per[u]] == ["f0", "f1", "f2"] and {x["verdict"] for x in per[u]} == {"false"}
    old = {"verdicts": [{"id": v["rid"], "verdict": v["verdict"]} for v in vs]}
    assert eh.cr_split_verdicts(old, key)[1] == []
    _, p2 = eh.cr_split_verdicts([*vs[1:], vs[1], {"rid": "f0", "verdict": "true"}, {"rid": vs[0]["rid"],
                                                                                      "verdict": "maybe"}], key)
    assert any("duplicate" in x for x in p2) and any("unknown rid 'f0'" in x for x in p2)
    assert any("bad verdict" in x for x in p2) and any("missing verdict" in x for x in p2)
    assert eh.cr_split_verdicts("x", key)[1]


def test_cr_grading_end_to_end(full_run: Path, stub_bin: Path, tmp_path: Path) -> None:
    env = stub_env(stub_bin, tmp_path)
    eq = full_run / "eq"
    cp = run_harness(["cr-grader-input", "--stage", "d", "--eq-root", str(eq), "--items", str(ITEMS),
                      "--with-members"], env)
    assert cp.returncode == 0, cp.stderr
    batch = json.loads((eq / "runs" / "d" / "grading" / "CR" / "batch.json").read_text())
    assert batch and len({b["rid"] for b in batch}) == len(batch)
    verdicts = [{"rid": b["rid"], "verdict": "true" if b["type"] == "match" else "false", "note": ""} for b in batch]
    vp = tmp_path / "verdicts.json"
    vp.write_text(json.dumps(verdicts))
    cp = run_harness(["cr-grade", "--stage", "d", "--verdicts", str(vp), "--eq-root", str(eq), "--items", str(ITEMS)],
                     env)
    assert cp.returncode == 0, cp.stderr
    res = [json.loads(x) for x in (eq / "runs" / "d" / "grading_results" / "CR.jsonl").read_text().splitlines()]
    units = eh.cr_units(ledger(full_run), True)
    assert len(res) >= len(units) and any(r["member"] is not None for r in res)

    def expected(ans: object) -> int:  # the fake oracle's rule: matched (f1.py, line <= 5) findings marked true
        return sum(1 for f in (ans if isinstance(ans, list) else []) if f["file"] == "f1.py" and f["line"] <= 5)

    last = {(r["item"], r["label"], r["node"], r["member"]): r for r in res}
    for u in units:
        r = last[(u["item"], u["label"], u["node"], u["member"])]
        assert r["exit"] == 0 and r["score"] == expected(u["answer"]), (u, r)
    assert sum(r["score"] for r in last.values()) > 0  # the routing was exercised on real matches
    vp.write_text(json.dumps(verdicts[1:]))  # one verdict missing: refused before any scoring
    cp = run_harness(["cr-grade", "--stage", "d", "--verdicts", str(vp), "--eq-root", str(eq), "--items", str(ITEMS)],
                     env)
    assert cp.returncode == 2 and "missing verdict" in cp.stderr


def test_parse_score_handles_inf() -> None:
    assert eh.parse_score("inf") == eh.parse_score("Infinity") == eh.parse_score("+inf") == float("inf")
    assert eh.parse_score(0.25) == 0.25 and eh.parse_score(1) == 1.0
    assert eh.parse_score(None) is None and eh.parse_score("x") is None and eh.parse_score(True) is None


def test_mechanical_score_es_with_inf(full_run: Path, stub_bin: Path, tmp_path: Path) -> None:
    env = stub_env(stub_bin, tmp_path)
    eq = full_run / "eq"
    cp = run_harness(["score", "--stage", "d", "--cls", "ES", "--eq-root", str(eq), "--items", str(ITEMS)], env)
    assert cp.returncode == 0, cp.stderr
    res = [json.loads(x) for x in (eq / "runs" / "d" / "grading_results" / "ES.jsonl").read_text().splitlines()]
    arms = {(r["item"], r["label"]): r for r in ledger(full_run) if r["record"] == "item_arm" and r["cls"] == "ES"}
    assert {(r["item"], r["label"]) for r in res} == set(arms)
    for r in res:
        a = arms[(r["item"], r["label"])]["answer"]
        if isinstance(a, int | float) and a > 0:
            assert r["score_inf"] is False and abs(r["score_num"] - abs(__import__("math").log(a / 100))) < 1e-9
        else:
            assert r["score"] == "inf" and r["score_inf"] is True and r["score_num"] is None
    unit_files = list((eq / "runs" / "d" / "grading_keys" / "ES_units").glob("*.json"))
    assert unit_files and not any(LEAK.search(p.name) for p in unit_files)  # neutral names, no arm labels


def test_parse_score_inf_routes_to_flag() -> None:
    sc = eh.parse_score("inf")
    assert sc is not None and sc > 1e308


def test_run_oracle_with_relative_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`--items items` is relative in the documented commands; the oracle runs with cwd = the pool."""
    (tmp_path / "a.json").write_text(json.dumps({"answer": 100.0}))
    monkeypatch.chdir(ITEMS.parent)
    rc, out = eh.run_oracle(Path("items") / "ES", "ES-DEV1", tmp_path / "a.json")
    assert rc == 0 and json.loads(out)["score"] == 0.0


def test_score_partial_without_oracle(stub_bin: Path, tmp_path: Path) -> None:
    runs = tmp_path / "eq" / "runs" / "d"
    runs.mkdir(parents=True)
    led = eh.Ledger(runs / "ledger.jsonl")
    led.append("item_arm", stage="d", item="ES-DEV1", cls="ES", label="p3", arm="E", status="partial", answer=None)
    led.append("item_arm", stage="d", item="ES-DEV2", cls="ES", label="p1", arm="S*", status="ok", answer=100.0)
    cp = run_harness(["score", "--stage", "d", "--cls", "ES", "--eq-root", str(tmp_path / "eq"), "--items",
                      str(ITEMS)], stub_env(stub_bin, tmp_path))
    assert cp.returncode == 0, cp.stderr
    res = {r["item"]: r for r in map(json.loads, (runs / "grading_results" / "ES.jsonl").read_text().splitlines())}
    assert res["ES-DEV1"]["exit"] is None and res["ES-DEV1"]["score"] == "inf" and res["ES-DEV1"]["score_inf"]
    assert res["ES-DEV2"]["exit"] == 0 and res["ES-DEV2"]["score_num"] == 0.0
