"""Member-level grade files (COMPARE_eq §12 A6.3): `score --members` (PF, CP), cr-grade's members/CR_findings.jsonl,
`rs-grader-input` / `rs-grade --verdicts` (members/RS.jsonl). PF/CP/CR run in-process with a fake run_oracle (the
harness's selection, file names and routing are under test, not the oracles); RS runs the REAL items/RS oracle on
RS-DEV1 (rid, mechanical settlement and --grade are the oracle's)."""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from test_blinding import LEAK

import eq_harness as eh
from conftest import FIXT_FLAGS, ITEMS, STAGE

RS_KEY_ANSWER = {"label": "SUPPORTED", "value": "pass", "rationale": "grades/b0v2/P61-v1.md says check_result pass"}


def call(**kw: Any) -> dict[str, Any]:
    base = {"cls": "PF", "item": "PF-DEV1", "label": "p3", "node": None, "member": 1, "role": "m1/5", "round": 0,
            "branch": None, "branch_workdir": None, "cwd": "/w", "answer": "a", "call_id": "c"}
    return {"record": "call", **{**base, **kw}}


def write_ledger(eq: Path, recs: list[dict[str, Any]]) -> Path:
    runs = eq / "runs" / "d"
    runs.mkdir(parents=True, exist_ok=True)
    led = eh.Ledger(runs / "ledger.jsonl")
    for r in recs:
        led.append(r["record"], **{k: v for k, v in r.items() if k != "record"})
    return runs


def jl(p: Path) -> list[dict[str, Any]]:
    return [json.loads(x) for x in p.read_text().splitlines()]


# ---- pure parts -------------------------------------------------------------------------------------------------

def test_member_units_selects_member_calls_latest_wins() -> None:
    recs = [call(call_id="c1", answer="old"), call(call_id="c1b", answer="new"),
            call(member=2, role="m2/5", call_id="c2", cwd="/w2", branch_workdir="/bw2"),
            call(member=2, role="r1", round=1, call_id="c2r", answer="rep"),
            call(member=1, role="r2", round=2, branch="none", call_id="c7", cwd="/w7"),
            call(member=3, role="m3/5", node="b", call_id="eg"),            # an EG E-node member: never
            call(member=None, role="solo", call_id="solo"),                  # no member number
            call(member=True, role="m1/5", call_id="bool"),                  # a bool is not a member number
            call(member=4, role="verifier", call_id="ver"),                  # not a member role
            call(member=4, role="m4/5x", call_id="badrole"),
            call(cls="CP", call_id="cp"),                                     # another class
            {"record": "item_arm", "cls": "PF", "item": "PF-DEV1", "label": "p3", "member": 1, "role": "m1/5"}]
    units = eh.member_units(recs, "PF")
    got = {(u["member"], u["round"], u["branch"]): (u["call_id"], u["answer"], u["workdir"]) for u in units}
    assert got == {(1, 0, None): ("c1b", "new", "/w"), (2, 0, None): ("c2", "a", "/bw2"),
                   (2, 1, None): ("c2r", "rep", "/w"), (1, 2, "none"): ("c7", "a", "/w7")}
    keys = [[u["item"], u["label"], u["member"], u["round"], u["branch"]] for u in units]
    assert keys == sorted(keys, key=json.dumps)
    assert eh.member_units(list(reversed(recs)), "PF")[0]["answer"] == "old"  # the LATEST call (ledger order) wins


def test_cr_finding_rows_take_the_kept_index_grade() -> None:
    answer = [{"file": "./a.py", "line": 3, "claim": " X bug "}, {"file": "b.py", "line": 9, "claim": "y"},
              {"file": "a.py", "line": 3, "claim": "x BUG"},  # the oracle's duplicate of finding 0
              "junk", {"file": "c.py", "line": 1, "claim": "z"}]
    detail = {"n_seeded": 2, "per_finding": [{"id": 0, "bug": 1, "verdict": "true"},
                                             {"id": 1, "bug": None, "verdict": "false"}, "x", {"id": "4"}]}
    rows = eh.cr_finding_rows(answer, detail)
    assert rows == [{"finding": answer[0], "bug": 1, "verdict": "true", "n_seeded": 2},
                    {"finding": answer[1], "bug": None, "verdict": "false", "n_seeded": 2},
                    {"finding": answer[2], "bug": 1, "verdict": "true", "n_seeded": 2}]
    assert eh.cr_dedupe_key({"file": ".\\a.py", "line": 3, "claim": "X"}) == ("a.py", 3, "x")
    assert eh.cr_finding_rows(answer, "scored") == [] and eh.cr_finding_rows(answer, {"per_finding": {}}) == []


def test_rs_member_units_add_each_p7_branch_as_member_0() -> None:
    recs = [call(cls="RS", item="RS-DEV1", answer={"label": "SUPPORTED"}),
            {"record": "item_arm", "cls": "RS", "item": "RS-DEV1", "label": "p3", "cell": "p7",
             "branches": {"rotation": {"rounds": 2, "answer": {"label": "REFUTED"}}, "none": {"rounds": 2,
                                                                                          "answer": None}}},
            {"record": "item_arm", "cls": "RS", "item": "RS-DEV2", "label": "p3", "cell": None,
             "branches": {"none": {"rounds": 1, "answer": "x"}}}]
    units = eh.rs_member_units(recs)
    assert [(u["member"], u["round"], u["branch"], u["answer"]) for u in units] == [
        (1, 0, None, {"label": "SUPPORTED"}), (0, 2, "none", None), (0, 2, "rotation", {"label": "REFUTED"})]


def test_rs_split_verdicts_validates() -> None:
    key = {"rids": {"r1": {"needs_grade": True}, "r2": {"needs_grade": True}, "r3": {"needs_grade": False}}}
    assert eh.rs_split_verdicts([{"rid": "r1", "verdict": "pass"}, {"rid": "r2", "verdict": "fail"}], key) == (
        {"r1": "pass", "r2": "fail"}, [])
    assert eh.rs_split_verdicts({"grades": [{"rid": "r1", "verdict": "pass"}, {"rid": "r2", "verdict": "fail"}]},
                                key)[1] == []
    _, p = eh.rs_split_verdicts([{"rid": "r1", "verdict": "pass"}, {"rid": "r1", "verdict": "pass"},
                                 {"rid": "r3", "verdict": "pass"}, {"rid": "r2", "verdict": "maybe"}, "x"], key)
    assert "duplicate rid r1" in p and "unknown rid 'r3'" in p and "bad verdict for r2" in p
    assert "missing verdict for r2" in p and "unknown rid ''" in p
    assert eh.rs_split_verdicts("x", key) == ({}, ["grader output is not a list"])


# ---- score --members (PF, CP) ---------------------------------------------------------------------------------

Oracle = Callable[..., tuple[int, str]]


@pytest.fixture
def fake_oracle(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """eh.run_oracle replaced: logs (item, answer, extra, workdir files) and scores 1 iff the answer says 'good'."""
    seen: list[dict[str, Any]] = []

    def run(pool: Path, item: str, answer_path: Path, *extra: str, **kw: Any) -> tuple[int, str]:
        ans = json.loads(answer_path.read_text())["answer"]
        wd = Path(extra[1]) if extra[:1] == ("--workdir",) else None
        seen.append({"item": item, "answer": ans, "answer_path": answer_path, "workdir": wd,
                     "files": None if wd is None else {p.name: p.read_text() for p in wd.iterdir() if p.is_file()}})
        return 0, json.dumps({"item": item, "score": int(ans == "good"), "detail": "fake"})

    monkeypatch.setattr(eh, "run_oracle", run)
    return seen


def score_members(tmp_path: Path, cls: str, recs: list[dict[str, Any]], members: bool = True) -> tuple[int, Path]:
    eq = tmp_path / "eq"
    runs = write_ledger(eq, recs)
    fp = tmp_path / "flags.json"
    fp.write_text(json.dumps(FIXT_FLAGS))
    rc = eh.cmd_score(argparse.Namespace(stage="d", cls=cls, eq_root=str(eq), items=str(ITEMS), flags=str(fp),
                                         members=members))
    return rc, runs


def test_score_members_pf_writes_member_rows_only(tmp_path: Path, fake_oracle: list[dict[str, Any]]) -> None:
    recs = [{"record": "item_arm", "cls": "PF", "item": "PF-DEV1", "label": "p3", "status": "ok", "answer": "good"},
            call(member=1, role="m1/5", answer="good", call_id="k1"),
            call(member=2, role="m2/5", answer="bad", call_id="k2"),
            call(member=3, role="m3/5", answer=None, call_id="k3"),               # no answer: 0, oracle not run
            call(member=2, role="r1", round=1, answer="good", call_id="k2r"),     # the repair round
            call(member=1, role="m1/5", node="a", answer="good", call_id="eg")]   # an EG node member: not graded
    rc, runs = score_members(tmp_path, "PF", recs)
    assert rc == 0
    assert not (runs / "grading_results" / "PF.jsonl").exists()  # the item-level file is not touched
    rows = {(r["member"], r["round"]): r for r in jl(runs / "grading_results" / "members" / "PF.jsonl")}
    assert set(rows) == {(1, 0), (2, 0), (3, 0), (2, 1)}
    assert {k: (r["score"], r["call_id"], r["branch"], r["item"], r["label"]) for k, r in rows.items()} == {
        (1, 0): (1, "k1", None, "PF-DEV1", "p3"), (2, 0): (0, "k2", None, "PF-DEV1", "p3"),
        (3, 0): (0, "k3", None, "PF-DEV1", "p3"), (2, 1): (1, "k2r", None, "PF-DEV1", "p3")}
    assert rows[(3, 0)]["exit"] is None and rows[(3, 0)]["detail"].startswith("partial: no answer")
    assert len(fake_oracle) == 3 and all(s["workdir"] is None for s in fake_oracle)  # PF: no workdir
    assert {s["answer_path"].parent.name for s in fake_oracle} == {"PF_member_units"}
    assert all(s["answer_path"].name.startswith("m") and not LEAK.search(s["answer_path"].name) for s in fake_oracle)


def test_score_members_cp_grades_a_check_copy_of_the_member_dir(tmp_path: Path,
                                                                fake_oracle: list[dict[str, Any]]) -> None:
    pristine = ITEMS / "CP" / "fixtures" / "base"
    own, fork = tmp_path / "own", tmp_path / "fork"
    for d, tag in ((own, "own"), (fork, "fork")):
        d.mkdir()
        (d / "f1.py").write_text(f"# {tag} edit\n")
        (d / "check.sh").write_text("exit 0\n")  # an owned path: never taken over
        (d / "planted.py").write_text("x\n")     # a member-added file: never taken over
    recs = [call(cls="CP", item="CP-DEV1", member=1, role="m1/5", cwd=str(own), answer="good", call_id="o"),
            call(cls="CP", item="CP-DEV1", member=1, role="r1", round=1, cwd=str(own), branch_workdir=str(fork),
                 answer="good", call_id="f")]
    rc, runs = score_members(tmp_path, "CP", recs)
    assert rc == 0
    by_call = {s["answer_path"].name: s for s in fake_oracle}
    assert len(by_call) == 2
    for s in by_call.values():
        assert s["workdir"] is not None and s["workdir"].parent == runs / "grading_keys" / "CP_member_units"
        assert s["files"]["check.sh"] == (pristine / "check.sh").read_text() and "planted.py" not in s["files"]
        assert s["files"]["f2.py"] == (pristine / "f2.py").read_text()
    edits = sorted(s["files"]["f1.py"] for s in by_call.values())
    assert edits == ["# fork edit\n", "# own edit\n"]  # round 0 graded on cwd, the forked repair on its branch dir
    rows = jl(runs / "grading_results" / "members" / "CP.jsonl")
    assert sorted((r["round"], r["call_id"], r["score"]) for r in rows) == [(0, "o", 1), (1, "f", 1)]


@pytest.mark.parametrize("cls", ["RS", "ES", "CR"])
def test_score_members_refuses_other_classes(tmp_path: Path, fake_oracle: list[dict[str, Any]], cls: str,
                                             capsys: pytest.CaptureFixture[str]) -> None:
    rc, runs = score_members(tmp_path, cls, [call(cls=cls)])
    assert rc == 2 and "--members grades" in capsys.readouterr().err
    assert fake_oracle == [] and not (runs / "grading_results").exists()


# ---- cr-grade: members/CR_findings.jsonl ---------------------------------------------------------------------

@pytest.fixture
def fake_cr_oracle(monkeypatch: pytest.MonkeyPatch) -> None:
    """A CR oracle with the real one's dedupe and detail.per_finding: a finding on line <= 5 matches bug 0; the
    grade is the grader's verdict per kept index. Item CR-DEV2 fails --grade (rc 1)."""

    def run(pool: Path, item: str, answer_path: Path, *extra: str, **kw: Any) -> tuple[int, str]:
        fs = json.loads(answer_path.read_text())["answer"]
        keep: dict[tuple[Any, ...], int] = {}
        for i, f in enumerate(fs):
            keep.setdefault(eh.cr_dedupe_key(f), i)
        kept = sorted(keep.values())
        if extra[0] == "--grader-input":
            Path(extra[1]).write_text(json.dumps([{"rid": f"f{i}", "type": "match" if fs[i]["line"] <= 5
                                                   else "unmatched", "finding": fs[i], "code_excerpt": ""}
                                                  for i in kept]))
            return 0, json.dumps({"item": item, "score": None, "detail": "grader input written"})
        if item == "CR-DEV2":
            return 1, "oracle error: boom"
        got = {g["rid"]: g["verdict"] for g in json.loads(Path(extra[1]).read_text())}
        per = [{"id": i, "bug": 0 if fs[i]["line"] <= 5 else None, "verdict": got[f"f{i}"]} for i in kept]
        return 0, json.dumps({"item": item, "score": 0.5, "detail": {"n_seeded": 1, "per_finding": per}})

    monkeypatch.setattr(eh, "run_oracle", run)


def test_cr_grade_writes_member_findings(tmp_path: Path, fake_cr_oracle: None) -> None:
    f_hit, f_miss = {"file": "f1.py", "line": 3, "claim": "off by one"}, {"file": "f2.py", "line": 40, "claim": "n"}
    dup = {"file": "./f1.py", "line": 3, "claim": "OFF BY ONE "}
    recs = [{"record": "item_arm", "cls": "CR", "item": "CR-DEV1", "label": "p3", "answer": [f_hit]},
            call(cls="CR", item="CR-DEV1", member=1, role="m1/5", answer=[f_hit, f_miss, dup]),
            call(cls="CR", item="CR-DEV1", member=2, role="m2/5", node="b", answer=[f_hit]),  # EG node: CR.jsonl only
            call(cls="CR", item="CR-DEV2", member=1, role="m1/5", answer=[f_hit])]             # oracle fails
    eq = tmp_path / "eq"
    runs = write_ledger(eq, recs)
    assert eh.cmd_cr_grader_input(argparse.Namespace(stage="d", eq_root=str(eq), items=str(ITEMS),
                                                     with_members=True)) == 0
    batch = json.loads((runs / "grading" / "CR" / "batch.json").read_text())
    verdicts = [{"rid": b["rid"], "verdict": "true" if b["type"] == "match" else "false", "note": ""} for b in batch]
    vp = tmp_path / "v.json"
    vp.write_text(json.dumps(verdicts))
    rc = eh.cmd_cr_grade(argparse.Namespace(stage="d", verdicts=str(vp), eq_root=str(eq), items=str(ITEMS)))
    assert rc == 1  # CR-DEV2's oracle failure is counted
    cr = jl(runs / "grading_results" / "CR.jsonl")
    assert len(cr) == 4 and {(r["item"], r["node"], r["member"], r["exit"]) for r in cr} >= {
        ("CR-DEV1", "b", 2, 0), ("CR-DEV2", None, 1, 1)}
    rows = jl(runs / "grading_results" / "members" / "CR_findings.jsonl")
    assert [(r["item"], r["label"], r["member"], r["round"], r["finding"], r["bug"], r["verdict"], r["n_seeded"])
            for r in rows] == [("CR-DEV1", "p3", 1, 0, f_hit, 0, "true", 1),
                               ("CR-DEV1", "p3", 1, 0, f_miss, None, "false", 1),
                               ("CR-DEV1", "p3", 1, 0, dup, 0, "true", 1)]


# ---- rs-grader-input / rs-grade (the real RS oracle) -------------------------------------------------------

def rs_cmd(fn: Callable[[argparse.Namespace], int], eq: Path, **kw: Any) -> int:
    return fn(argparse.Namespace(stage="d", eq_root=str(eq), items=str(STAGE / "items"), **kw))


def test_rs_members_end_to_end_with_the_real_oracle(tmp_path: Path) -> None:
    other = {**RS_KEY_ANSWER, "rationale": "the P61 v1 grade record for batch b0v2 shows pass"}
    recs = [call(cls="RS", item="RS-DEV1", member=1, role="m1/5", answer=RS_KEY_ANSWER, call_id="a"),
            call(cls="RS", item="RS-DEV1", member=2, role="m2/5", answer=RS_KEY_ANSWER, call_id="b"),  # same rid
            call(cls="RS", item="RS-DEV1", member=3, role="m3/5", answer={**RS_KEY_ANSWER, "label": "REFUTED"},
                 call_id="c"),                                                     # wrong label: settled, 0
            call(cls="RS", item="RS-DEV1", member=4, role="m4/5", answer=None, call_id="d"),  # settled, 0
            {"record": "item_arm", "cls": "RS", "item": "RS-DEV1", "label": "p3", "cell": "p7",
             "branches": {"none": {"rounds": 2, "answer": other}}}]
    eq = tmp_path / "eq"
    runs = write_ledger(eq, recs)
    assert rs_cmd(eh.cmd_rs_grader_input, eq) == 0
    bp = runs / "grading" / "RS_members" / "batch.jsonl"
    batch = jl(bp)
    key = json.loads((runs / "grading_keys" / "RS_members.key.json").read_text())
    assert len(batch) == 2 and all(set(b) == {"rid", "item", "class", "claim", "answer", "key", "rubric",
                                              "reference_excerpt", "vocabulary"} for b in batch)
    assert not re.search(r"\bp[37]\b|\bm\d+/\d+\b|call_id|\"member\"|\"branch\"", bp.read_text())  # blinded
    assert {b["rid"] for b in batch} == {r for r, e in key["rids"].items() if e["needs_grade"]}
    units = {r: sorted(map(tuple, e["units"])) for r, e in key["rids"].items()}
    shared = next(r for r, u in units.items() if len(u) == 2)
    assert units[shared] == [("RS-DEV1", "p3", 1, 0, None), ("RS-DEV1", "p3", 2, 0, None)]
    assert sum(not e["needs_grade"] for e in key["rids"].values()) == 2  # REFUTED and null
    first = bp.read_bytes()
    assert rs_cmd(eh.cmd_rs_grader_input, eq) == 0 and bp.read_bytes() == first  # seeded batch order

    vp = tmp_path / "v.json"
    vp.write_text(json.dumps([{"rid": shared, "verdict": "pass"}]))  # one verdict missing: refused, nothing written
    assert rs_cmd(eh.cmd_rs_grade, eq, verdicts=str(vp)) == 2
    assert not (runs / "grading_results" / "members" / "RS.jsonl").exists()
    vp.write_text(json.dumps([{"rid": b["rid"], "verdict": "pass" if b["rid"] == shared else "fail"} for b in batch]))
    assert rs_cmd(eh.cmd_rs_grade, eq, verdicts=str(vp)) == 0
    rows = {(r["member"], r["round"], r["branch"]): r for r in jl(runs / "grading_results" / "members" / "RS.jsonl")}
    assert {k: (r["score"], r["exit"]) for k, r in rows.items()} == {
        (1, 0, None): (1, 0), (2, 0, None): (1, 0), (3, 0, None): (0, None), (4, 0, None): (0, None),
        (0, 2, "none"): (0, 0)}
    assert rows[(1, 0, None)]["rid"] == shared and rows[(1, 0, None)]["detail"]["grader_verdict"] == "pass"
    assert rows[(3, 0, None)]["detail"]["note"] == "settled mechanically, no grader"
