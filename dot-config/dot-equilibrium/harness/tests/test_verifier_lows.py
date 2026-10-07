"""Verifier LOW observations (2026-10-04): scoring copies keep owned paths, every checkable test dir is owned, overlay
keeps the pristine exec bit (never setuid/setgid/sticky)."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

import eq_harness as eh
from conftest import HARNESS, ITEMS, ledger, run_harness, stub_env


def _cp_pool(tmp: Path) -> eh.Item:
    pool = tmp / "pool"
    (pool / "fx" / "tests").mkdir(parents=True)
    (pool / "fx" / "m.py").write_text("x = 1\n")
    (pool / "fx" / "tests" / "test_m.py").write_text("assert True\n")
    (pool / "fx" / "run.sh").write_text("#!/bin/sh\nexit 0\n")
    os.chmod(pool / "fx" / "run.sh", 0o6755)  # noqa: S103  setuid/setgid in the pool: must never reach a copy
    return eh.Item("CP-X", "CP", False, "checkable", "p", (), None, "fx", ("sh", "check.sh"), (), pool)


def test_low1_owned_paths_module_function_matches_runner(tmp_path: Path) -> None:
    item = _cp_pool(tmp_path)
    assert eh.owned_paths(item, eh.DEFAULT_FLAGS) == ["tests"]
    r = eh.Runner.__new__(eh.Runner)
    r.flags = eh.DEFAULT_FLAGS
    assert r.owned_paths(item) == eh.owned_paths(item, eh.DEFAULT_FLAGS)


def test_low1_score_copy_keeps_tests_pristine(full_run: Path, stub_bin: Path, tmp_path: Path) -> None:
    """cmd_score builds the CP scoring copy with the owned paths: a member's tests/ edits never reach the oracle."""
    arms = [r for r in ledger(full_run) if r["record"] == "item_arm" and r["cls"] == "CP" and r.get("answer_workdir")]
    assert arms
    wd = Path(arms[0]["answer_workdir"])
    (wd / "f1.py").write_text("PATCHED\n")  # a pristine file outside tests: taken over
    tdir = wd / "tests"
    tdir.mkdir(exist_ok=True)
    pristine_tests = ITEMS / "CP" / "fixtures" / "base" / "tests"
    pristine_tests.mkdir(exist_ok=True)
    (pristine_tests / "test_x.py").write_text("ORIGINAL\n")
    try:
        (tdir / "test_x.py").write_text("TAMPERED\n")
        eq = full_run / "eq"
        cp = run_harness(["score", "--stage", "d", "--cls", "CP", "--eq-root", str(eq), "--items", str(ITEMS),
                          "--flags", str(full_run / "flags.json")],
                         stub_env(stub_bin, tmp_path))
        assert cp.returncode in (0, 1), cp.stderr
        units = eq / "runs" / "d" / "grading_keys" / "CP_units"
        copies = sorted(units.glob("u*.wd"))
        assert copies
        texts = {(c / "tests" / "test_x.py").read_text() for c in copies if (c / "tests" / "test_x.py").exists()}
        assert texts == {"ORIGINAL\n"}
        assert any((c / "f1.py").read_text() == "PATCHED\n" for c in copies)
    finally:
        (pristine_tests / "test_x.py").unlink()
        pristine_tests.rmdir()


def _pools() -> list[Path]:
    out = [ITEMS]
    real = HARNESS.parent / "items"
    if (real / "CP" / "manifest.jsonl").exists():
        out.append(real)
    return out


@pytest.mark.parametrize("pool", _pools(), ids=lambda p: p.parent.name)
def test_low2_every_checkable_test_dir_is_owned(pool: Path) -> None:
    flags = eh.DEFAULT_FLAGS
    for cls in eh.CLASSES:
        if not (pool / cls / "manifest.jsonl").exists():
            continue
        for it in eh.load_pool(pool, cls)[:20]:
            if it.public_check is None or cls in flags["answer_file"]:
                continue  # no check, or overlay disabled
            pc = list(it.public_check)
            dirs = [pc[k + 1] for k, a in enumerate(pc[:-1]) if a == "-s"]
            own = eh.owned_paths(it, flags)
            assert all(d.strip("/") in own for d in dirs), (it.id, dirs, own)
    assert "tests" in flags["check_owned_paths"]["CR"]


def test_low3_overlay_keeps_pristine_exec_bit_but_no_special_bits(tmp_path: Path) -> None:
    item = _cp_pool(tmp_path)
    wd = tmp_path / "member"
    eh.copy_fixture(item, wd)
    (wd / "run.sh").write_text("#!/bin/sh\necho patched\n")
    out = eh.check_copy(item, wd, tmp_path / "cdir", overlay=True, owned=["tests"])
    mode = stat.S_IMODE(os.lstat(out / "run.sh").st_mode)
    assert (out / "run.sh").read_text().endswith("patched\n")
    assert mode & stat.S_IXUSR and not mode & (stat.S_ISUID | stat.S_ISGID | stat.S_ISVTX)
    plain = stat.S_IMODE(os.lstat(out / "m.py").st_mode)
    assert not plain & stat.S_IXUSR and plain & stat.S_IWUSR
    assert json.dumps(eh.DEFAULT_FLAGS["check_owned_paths"])


def test_low3_overlay_mode_pure() -> None:
    """The sandbox may strip setuid on chmod, so the bit arithmetic is pinned directly."""
    assert eh.overlay_mode(stat.S_IFREG | 0o6755) == 0o755
    assert eh.overlay_mode(stat.S_IFREG | 0o1777) == 0o755
    assert eh.overlay_mode(stat.S_IFREG | 0o444) == 0o644
    assert eh.overlay_mode(stat.S_IFREG | 0o500) == 0o700
