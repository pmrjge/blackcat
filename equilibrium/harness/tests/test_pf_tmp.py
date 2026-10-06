"""PF checker review (2026-10-04): a check, oracle or fact run gets a private TMPDIR that is removed afterwards, so a
SIGKILL'd check (whose own cleanup trap never runs) leaks no work dir and its verdict is only the harness's own."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from test_eqsec_proofs import item_, pool_, runner_

import eq_harness as eh
import eq_mediator as md

LEAK = ('d=$(mktemp -d "$TMPDIR/eqlean.XXXXXX"); echo PASS > "$d/verdict"; trap \'rm -rf "$d"\' EXIT; '
        'echo "$d"; sleep 30\n')


def test_killed_check_leaks_no_workdir_and_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "systmp").mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp_path / "systmp"))  # a mutant's leak lands here, not in the real TMPDIR
    item = item_(pool_(tmp_path, {"check.sh": LEAK}), "PF", ("bash", "check.sh", "Answer.lean"))
    r, wd = runner_(tmp_path), tmp_path / "work" / "m1"
    eh.copy_fixture(item, wd)
    r.flags["check_timeout_s"] = 1
    ok, out = r.run_check(item, "p3", wd, "x")
    assert ok is False and out.startswith("check timeout")
    leaked = Path(out.splitlines()[1])
    assert leaked.resolve().parent.parent == (r.arm_dir(item, "p3") / "check_runs").resolve()
    assert not leaked.parent.exists()  # the private TMPDIR (and the trap-less work dir in it) is gone
    assert list((r.arm_dir(item, "p3") / "check_runs").iterdir()) == []
    assert list((tmp_path / "systmp").iterdir()) == []


def _capture(monkeypatch: pytest.MonkeyPatch, seen: list[tuple[Path, bool]]) -> None:
    def fake(argv: Any, cwd: Path, env: dict[str, str], timeout_s: float, keep: int = 65536,
             stdin_data: bytes | None = None) -> tuple[int, str]:
        t = Path(env["TMPDIR"])
        seen.append((t, t.is_dir() and t.stat().st_mode & 0o077 == 0))
        return 0, "{}"
    monkeypatch.setattr(eh, "run_bounded", fake)


def test_oracle_gets_private_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Path, bool]] = []
    _capture(monkeypatch, seen)
    (tmp_path / "a.json").write_text("{}")
    eh.run_oracle(tmp_path, "PF-0001", tmp_path / "a.json")
    assert len(seen) == 1 and seen[0][1] and os.environ.get("TMPDIR") != str(seen[0][0])
    assert not seen[0][0].exists()


def test_fact_runs_get_private_tmpdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[tuple[Path, bool]] = []
    _capture(monkeypatch, seen)
    (tmp_path / "fx").mkdir()
    (tmp_path / "fx" / "t.sh").write_text("exit 0\n")
    md.verify({"kind": "command", "ref": "bash t.sh", "detail": "exit 0"}, tmp_path / "fx",
              public_check=["bash", "t.sh"], timeout_s=5)
    assert len(seen) == 2 and all(ok for _, ok in seen) and seen[0][0] != seen[1][0]
    assert not any(t.exists() for t, _ in seen)
