"""Regression tests for the code-review findings of 2026-10-04 (real pool shapes, isolation, workdir answers)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import ITEMS, ledger

RS_SPEC = eh.DEFAULT_FLAGS["answer_key"]["RS"]


def rs(label: str, value: str = "", why: str = "") -> dict[str, str]:
    return {"label": label, "value": value, "rationale": why}


def test_rs_key_ignores_rationale_and_splits_refuted_values() -> None:
    key = eh.make_answer_key(RS_SPEC)
    answers = [rs("SUPPORTED", why=f"because {i}") for i in range(3)] + [rs("REFUTED", "42", "x"),
                                                                          rs("REFUTED", "43", "y")]
    pr = eh.plurality(answers, 1, key)
    assert pr.top == 3 and pr.kappa == 0.6 and len(pr.counts) == 3
    assert key(rs("refuted", " 42 ", "a")) == key(rs("REFUTED", "42", "b")) != key(rs("REFUTED", "41"))
    assert key(rs("SUPPORTED", "junk")) == key(rs("SUPPORTED"))
    assert eh.representative(answers, pr.winner or "", key)["label"] == "SUPPORTED"
    assert eh.make_answer_key(None) is eh.normalise_answer


def test_rs_gate_rewording_is_not_a_change(tmp_path: Path) -> None:
    key = eh.make_answer_key(RS_SPEC)
    d = eh.evidence_gate(rs("SUPPORTED", why="a"), [], rs("SUPPORTED", why="b"), [], lambda e: True,
                         lambda a, b: key(a) == key(b))
    assert not d.changed


def test_findings_without_claim_class() -> None:
    fields = {"file": "file", "line": "line", "claim_class": None}
    a = [{"file": "m.py", "line": 10, "claim": "off by one"}, {"file": "m.py", "line": 12, "claim": "wrong bound"}]
    fs = eh.parse_findings(a, 1, fields) + eh.parse_findings([{"file": "m.py", "line": 11, "claim": "x"}], 2, fields)
    assert len(fs) == 3 and {f.claim_class for f in fs} == {""}
    cl = eh.cluster_findings(fs)
    assert len(cl) == 1 and cl[0].support == 2


def test_tool_lists_compare_as_sets_and_empty_counts() -> None:
    item = eh.load_pool(ITEMS, "RS")[0]
    flags = json.loads(json.dumps(eh.DEFAULT_FLAGS))
    assert eh.check_item_flags(eh.dataclasses.replace(item, allowed_tools=("Grep", "Read", "Glob")), flags) == []
    assert eh.check_item_flags(eh.dataclasses.replace(item, allowed_tools=()), flags)
    ds = eh.load_pool(ITEMS, "DS")[0]
    assert ds.allowed_tools == () and eh.check_item_flags(ds, flags) == []
    assert "--allowedTools" not in eh.build_argv("c", "verifier", 1, {}, [], flags)


def test_copy_from_read_only_pool_is_writable(tmp_path: Path) -> None:
    pool = tmp_path / "pool"
    (pool / "fx" / "sub").mkdir(parents=True)
    (pool / "fx" / "sub" / "a.py").write_text("x = 1\n")
    for p in [pool / "fx" / "sub" / "a.py", pool / "fx" / "sub", pool / "fx"]:
        p.chmod(p.stat().st_mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    item = eh.Item("CP-X", "CP", False, "checkable", "p", (), None, "fx", None, (), pool)
    try:
        eh.copy_fixture(item, tmp_path / "w")
        (tmp_path / "w" / "sub" / "a.py").write_text("x = 2\n")
        (tmp_path / "w" / "sub" / "new.py").write_text("")
        eh.copy_fixture(item, tmp_path / "w2", source=tmp_path / "w")  # chained copy keeps the edit
        assert (tmp_path / "w2" / "sub" / "a.py").read_text() == "x = 2\n"
    finally:
        for p in [pool / "fx", pool / "fx" / "sub", pool / "fx" / "sub" / "a.py"]:
            p.chmod(p.stat().st_mode | stat.S_IWUSR)


def test_file_evidence_reads_pristine_fixture(tmp_path: Path) -> None:
    """Facts are checked against the pristine fixture: a file a member wrote in its copy is never evidence."""
    import eq_mediator as md

    pristine = tmp_path / "pristine"
    pristine.mkdir()
    (pristine / "doc1.txt").write_text("the capital of X is Y1\n")
    ck = md.FactChecker(pristine, "fx")
    assert ck.check({"kind": "quote", "ref": "doc1.txt", "detail": "capital of X is Y1"}).status == md.VERIFIED
    assert ck.check({"kind": "quote", "ref": "mine.txt", "detail": "I wrote this"}).status == md.REFUTED
    assert md.FactChecker(None, "").check({"kind": "quote", "ref": "mine.txt", "detail": "x"}).status == md.REFUTED


def test_check_copy_cp_overlay_keeps_tests_and_ignores_planted_files(tmp_path: Path) -> None:
    """H2 (CP): the check runs on pristine tests + the member's versions of pristine source files only."""
    pool = tmp_path / "pool"
    (pool / "fx" / "tests").mkdir(parents=True)
    (pool / "fx" / "m.py").write_text("x = 1\n")
    (pool / "fx" / "tests" / "test_m.py").write_text("assert True\n")
    (pool / "fx" / "check.sh").write_text("exit 1\n")
    item = eh.Item("CP-X", "CP", False, "checkable", "p", (), None, "fx", ("sh", "check.sh"), (), pool)
    wd = tmp_path / "member"
    eh.copy_fixture(item, wd)
    (wd / "m.py").write_text("x = 2\n")  # the patch: taken over
    (wd / "tests" / "test_m.py").write_text("pass\n")  # tampered tests: ignored (owned)
    (wd / "check.sh").write_text("exit 0\n")  # tampered check script: ignored (owned automatically)
    (wd / "unittest.py").write_text("planted\n")  # a new file: never taken over
    (wd / "victim").symlink_to(tmp_path)
    r = eh.Runner.__new__(eh.Runner)
    r.flags = eh.DEFAULT_FLAGS
    own = r.owned_paths(item)
    assert own == ["tests", "check.sh"]
    out = eh.check_copy(item, wd, tmp_path / "cdir", overlay=True, owned=own)
    assert (out / "m.py").read_text() == "x = 2\n" and (out / "tests" / "test_m.py").read_text() == "assert True\n"
    assert (out / "check.sh").read_text() == "exit 1\n" and not (out / "unittest.py").exists()
    assert not (out / "victim").exists()
    (wd / "m.py").unlink()
    (wd / "m.py").symlink_to(tmp_path / "pool" / "fx" / "tests" / "test_m.py")  # a link is never followed
    out2 = eh.check_copy(item, wd, tmp_path / "cdir2", overlay=True, owned=own)
    assert (out2 / "m.py").read_text() == "x = 1\n"


def test_check_never_writes_into_the_copy_and_gets_a_minimal_env(full_run: Path) -> None:
    recs = ledger(full_run)
    checks = [r for r in recs if r["record"] == "check"]
    assert checks
    work_files = [p for p in (full_run / "raw").rglob(".eq_answer.json")]
    assert work_files == []
    inputs = list((full_run / "raw").rglob("check_inputs/*.json"))
    assert inputs and all("/work/" not in str(p) for p in inputs)
    env = eh.minimal_env(EQ_ANSWER="x")
    assert set(env) <= {"PATH", "HOME", "LANG", "TMPDIR", "UV_CACHE_DIR", "EQ_ANSWER"}
    os.environ["EQ_TEST_SECRET"] = "s"  # noqa: S105
    try:
        assert "EQ_TEST_SECRET" not in eh.minimal_env()
    finally:
        del os.environ["EQ_TEST_SECRET"]


def test_answer_workdir_logged_and_cp_nodes_chain(full_run: Path) -> None:
    arms = [r for r in ledger(full_run) if r["record"] == "item_arm"]
    assert all("answer_workdir" in r for r in arms)
    for r in arms:
        if r["cls"] == "CP" and r["arm"] in ("S*", "G"):
            assert r["answer_workdir"] and Path(r["answer_workdir"]).is_dir()
    calls = [r for r in ledger(full_run) if r["record"] == "call" and r["cls"] == "CP" and r["arm"] == "G"]
    assert any(c["cwd"].endswith("/work/node/b") for c in calls)


def test_chain_source_only_for_workdir_classes(tmp_path: Path) -> None:
    r = eh.Runner.__new__(eh.Runner)
    r.flags = eh.DEFAULT_FLAGS
    cp = eh.load_pool(ITEMS, "CP")[0]
    rs_item = eh.load_pool(ITEMS, "RS")[0]
    wds: dict[str, Path | None] = {"a": tmp_path / "a", "b": None, "c": tmp_path / "c", "d": tmp_path / "d"}
    assert r.chain_source(cp, ["a", "b"], wds) == ("a", tmp_path / "a")
    assert r.chain_source(rs_item, ["a"], wds) == (None, None)
    assert r.chain_source(cp, [], wds) == (None, None)
    # A1.2: the dependency latest in topological order (level), ties by node id; listing order is irrelevant
    lv = {"a": 0, "c": 1, "d": 1}
    assert r.chain_source(cp, ["d", "c", "a"], wds, lv) == ("d", tmp_path / "d")
    assert r.chain_source(cp, ["c", "a"], wds, {"a": 2, "c": 1}) == ("a", tmp_path / "a")


def test_answer_file_never_follows_a_planted_symlink(tmp_path: Path) -> None:
    work, outside = tmp_path / "work", tmp_path / "victim.txt"
    work.mkdir()
    outside.write_text("keep me\n")
    (work / "Answer.lean").symlink_to(outside)
    p = eh.write_answer_file(work, "Answer.lean", "theorem t : True := trivial\n")
    assert outside.read_text() == "keep me\n" and not p.is_symlink()
    assert p.read_text() == "theorem t : True := trivial\n"
    for bad in ("../x", "a/b", "..", ""):
        with pytest.raises(ValueError):
            eh.write_answer_file(work, bad, "x")
    assert eh.DEFAULT_FLAGS["answer_file"] == {"PF": "Answer.lean"}
