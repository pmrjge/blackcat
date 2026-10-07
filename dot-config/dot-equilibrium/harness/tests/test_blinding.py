"""Grader-input blinding: no arm label, arm name, member id or session id in any grader file."""

from __future__ import annotations

import json
import re
from pathlib import Path

import eq_harness as eh
from conftest import ITEMS, run_harness, stub_env

LEAK = re.compile(r"\b[pq][1-59]\b|\bm\d+/\d+\b|S\*|(?<![A-Za-z0-9])EG(?![A-Za-z0-9])|"
                  r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\"label\"|\"arm\"|\"member\"")


def test_blind_text_scrubs() -> None:
    raw = "RS-0001 p3 m2/5\nAnswer: Y1 (as S* and EG said; session 0f8fad5b-d9cb-469f-a165-70867728950e, q1)"
    out = eh.blind_text(raw)
    assert not LEAK.search(out) and "Y1" in out and "\n" not in out


def test_grader_batch_blind_and_seeded() -> None:
    entries = [{"item": f"RS-{k:04d}", "label": f"p{a}", "answer": f"RS-{k:04d} p{a} m1/5 answer {k}"}
               for k in range(1, 6) for a in range(1, 5)]
    batch, key = eh.grader_batch(entries, "p", "RS")
    assert len(batch) == 20 and len({b["token"] for b in batch}) == 20
    assert all(set(b) == {"token", "item", "answer"} for b in batch)
    assert not LEAK.search(json.dumps(batch))
    assert {(v["item"], v["label"]) for v in key["tokens"].values()} == {(e["item"], e["label"]) for e in entries}
    assert len(key["regrade"]) == 4
    assert eh.grader_batch(list(reversed(entries)), "p", "RS") == (batch, key)


def test_pairwise_inputs_blind() -> None:
    entries = [{"item": "DS-0001", "label": f"p{a}", "answer": f"design {a} by p{a}"} for a in range(1, 5)]
    out, key = eh.pairwise_inputs(entries, "p", "DS", [("E", "S*"), ("E", "G"), ("EG", "G")])
    assert len(out) == 6 and not LEAK.search(json.dumps(out))
    orders = {(v["contrast"], v["A"], v["B"]) for v in key["pairs"].values()}
    assert ("E-S*", "p3", "p1") in orders and ("E-S*", "p1", "p3") in orders


def test_grader_files_from_a_run_are_blind(full_run: Path, stub_bin: Path, tmp_path: Path) -> None:
    env = stub_env(stub_bin, tmp_path)
    eq_root = full_run / "eq"
    for cls in eh.CLASSES:
        if cls == "CR":
            args = ["cr-grader-input", "--stage", "d", "--eq-root", str(eq_root), "--items", str(ITEMS),
                    "--with-members"]
        else:
            args = ["grader-input", "--stage", "d", "--cls", cls, "--eq-root", str(eq_root)]
        cp = run_harness(args, env)
        assert cp.returncode == 0, cp.stderr
    assert run_harness(["grader-input", "--stage", "d", "--cls", "CR", "--eq-root", str(eq_root)], env).returncode == 2
    gdir = eq_root / "runs" / "d" / "grading"
    files = list(gdir.rglob("*"))
    assert len([f for f in files if f.is_file()]) == len(eh.CLASSES)
    for f in files:
        if f.is_file():
            text = f.read_text()
            assert text.strip(), f
            assert not LEAK.search(text), (f, LEAK.search(text))
    keys = eq_root / "runs" / "d" / "grading_keys"
    assert gdir not in keys.parents and len(list(keys.glob("*.key.json"))) == len(eh.CLASSES)
