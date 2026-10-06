"""The stack repo's layout: <repo>/equilibrium/harness beside <repo>/lib/eq-container.

The harness (probe_script_candidates) and the tests (conftest.container_dir) find lib/eq-container there without
EQ_CONTAINER_DIR; EQ_CONTAINER_DIR, when set, still comes first; the staging layout (../lib beside the harness) still
works. A copy outside the repo (C10 runs this suite from a $TMPDIR copy) needs EQ_CONTAINER_DIR.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import conftest
import eq_harness as eh


def _container(root: Path) -> Path:
    d = root / "lib" / "eq-container"
    d.mkdir(parents=True)
    for f in ("probe.sh", "lib.sh"):
        (d / f).write_text("exit 0\n")
    return d


def test_probe_script_found_in_the_repo_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_lib = _container(tmp_path / "repo")
    monkeypatch.setattr(eh, "HERE", tmp_path / "repo" / "equilibrium" / "harness")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [repo_lib / "probe.sh"]
    env_lib = _container(tmp_path / "env")
    monkeypatch.setenv("EQ_CONTAINER_DIR", str(env_lib))
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [env_lib / "probe.sh", repo_lib / "probe.sh"]


def test_probe_script_staging_layout_comes_before_the_repo_layout(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    repo_lib = _container(tmp_path)
    stage_lib = _container(tmp_path / "equilibrium")
    monkeypatch.setattr(eh, "HERE", tmp_path / "equilibrium" / "harness")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [stage_lib / "probe.sh", repo_lib / "probe.sh"]


def test_container_dir_found_in_the_repo_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_lib = _container(tmp_path / "repo")
    monkeypatch.setattr(conftest, "STAGE", tmp_path / "repo" / "equilibrium")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert conftest.container_dir() == repo_lib
    env_lib = _container(tmp_path / "env")
    monkeypatch.setenv("EQ_CONTAINER_DIR", str(env_lib))
    assert conftest.container_dir() == env_lib
    monkeypatch.setattr(conftest, "STAGE", tmp_path / "nowhere" / "equilibrium")
    monkeypatch.delenv("EQ_CONTAINER_DIR")
    assert conftest.container_dir() is None


def test_in_place_run_inside_the_repo_finds_its_lib() -> None:
    """Run in place in a checkout (not a $TMPDIR copy), the real lookup lands on <repo>/lib/eq-container."""
    repo_lib = conftest.STAGE.parent / "lib" / "eq-container"
    if conftest.STAGE.name != "equilibrium" or not (repo_lib / "lib.sh").is_file():
        pytest.skip("not run in place in the stack repo (a staging or $TMPDIR copy)")
    assert repo_lib / "probe.sh" in eh.probe_script_candidates()
    assert conftest.container_dir() is not None
