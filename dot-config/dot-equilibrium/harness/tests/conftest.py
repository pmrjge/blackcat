"""Shared fixtures. Run from STAGE:
uv run --no-project --with pytest --with-requirements harness/eq_harness.py pytest -q harness/tests
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

HARNESS = Path(__file__).resolve().parent.parent
STAGE = HARNESS.parent
FIXT = Path(__file__).resolve().parent / "fixtures"
ITEMS = FIXT / "items"
sys.path.insert(0, str(HARNESS))

import eq_harness as eh  # noqa: E402

FIXT_FLAGS = eh.flags_from_pools(ITEMS)  # the fake pool's tool lists; the real ones live in harness/flags.json
FIXT_FLAGS["isolation"] = "off"  # an agent sandbox cannot reach the container services; the backend has a fake CLI
FAKE_CONTAINER_KNOBS = ("EQ_FAKE_CONTAINER_DOWN", "EQ_FAKE_CONTAINER_MISSING", "EQ_FAKE_CONTAINER_DIGEST",
                        "EQ_FAKE_CONTAINER_DIGESTS", "EQ_FAKE_CONTAINER_INSPECT", "EQ_FAKE_CONTAINER_SAVE_DIR",
                        "EQ_FAKE_CONTAINER_BUILD_RC", "EQ_FAKE_CONTAINER_LABELLED", "EQ_FAKE_CONTAINER_LIST_JSON",
                        "EQ_FAKE_CONTAINER_RUN_RC", "EQ_FAKE_CONTAINER_DIE_ON_RUN", "EQ_FAKE_CONTAINER_FAIL_TARGETS",
                        "EQ_FAKE_CONTAINER_FAIL_RC", "EQ_FAKE_CONTAINER_REPORT", "EQ_FAKE_CONTAINER_REPORT_ERR")


def container_dir() -> Path | None:
    """The repo's lib/eq-container (probe.sh, lib.sh, probe.d/50-tunnel.sh, eqc_json.py): $EQ_CONTAINER_DIR, else
    the stack repo's <repo>/lib/eq-container (eq_harness.repo_lib_dirs: the git top level, then STAGE/../..: STAGE is
    <repo>/dot-config/dot-equilibrium), then the staging layout beside the harness (STAGE/lib). None in a staging copy
    without it (the tests that need it skip)."""
    for d in ([Path(os.environ["EQ_CONTAINER_DIR"])] if os.environ.get("EQ_CONTAINER_DIR") else []) + \
            [*eh.repo_lib_dirs("eq-container", STAGE / "harness"), STAGE / "lib" / "eq-container"]:
        if (d / "lib.sh").is_file():
            return d
    return None


@pytest.fixture(scope="session")
def harness() -> Path:
    return HARNESS


@pytest.fixture(scope="session")
def stub_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A PATH directory whose `claude` is the stub and whose `pgrep` reports no claude process."""
    d = tmp_path_factory.mktemp("bin")
    (d / "claude").symlink_to(HARNESS / "stub_claude")
    pg = d / "pgrep"
    pg.write_text("#!/bin/sh\ncat \"${EQ_FAKE_PGREP:-/dev/null}\"\n")
    pg.chmod(0o755)
    return d


@pytest.fixture
def clog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The fake container CLI's argv log (tests/fake_container); clears every failure-injection switch."""
    log = tmp_path / "container.log"
    monkeypatch.setenv("EQ_FAKE_CONTAINER_LOG", str(log))
    for k in FAKE_CONTAINER_KNOBS:
        monkeypatch.delenv(k, raising=False)
    return log


def stub_env(stub_bin: Path, tmp: Path, **extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = f"{stub_bin}:{env['PATH']}"
    env["EQ_STUB_STATE"] = str(tmp / "stub_state")
    env["EQ_STUB_LOG"] = str(tmp / "stub_log.jsonl")
    env.update(extra)
    return env


def run_harness(args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", "run", "--script", "--quiet", str(HARNESS / "eq_harness.py"), *args], env=env,
                          capture_output=True, text=True, check=False)


def dry_run(stub_bin: Path, tmp: Path, script: dict[str, Any] | None = None, only: list[str] | None = None) -> Path:
    """Dev-stage run of the fake pool with the stub; returns the tmp dir (eq/, raw/, stub_log.jsonl)."""
    sched = tmp / "schedule.tsv"
    extra: dict[str, str] = {}
    if script is not None:
        (tmp / "script.json").write_text(json.dumps(script))
        extra["EQ_STUB_SCRIPT"] = str(tmp / "script.json")
    env = stub_env(stub_bin, tmp, **extra)
    cp = run_harness(["schedule", "--items", str(ITEMS), "--stage", "d", "--out", str(sched)], env)
    assert cp.returncode == 0, cp.stderr
    (tmp / "flags.json").write_text(json.dumps(FIXT_FLAGS))
    args = ["run", "--stage", "d", "--eq-root", str(tmp / "eq"), "--raw-root", str(tmp / "raw"), "--items", str(ITEMS),
            "--flags", str(tmp / "flags.json"), "--schedule", str(sched), "--no-check"]
    if only:
        args += ["--only", *only]
    cp = run_harness(args, env)
    assert cp.returncode == 0, cp.stderr
    return tmp


@pytest.fixture(scope="session")
def full_run(stub_bin: Path, tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    yield dry_run(stub_bin, tmp_path_factory.mktemp("full"))


def ledger(tmp: Path) -> list[dict[str, Any]]:
    return eh.read_ledger(tmp / "eq" / "runs" / "d" / "ledger.jsonl")
