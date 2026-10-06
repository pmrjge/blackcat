"""The stack repo's layout: <repo>/equilibrium/harness beside <repo>/lib/eq-container.

The harness (probe_script_candidates) and the tests (conftest.container_dir) find lib/eq-container there without
EQ_CONTAINER_DIR; EQ_CONTAINER_DIR, when set, still comes first; the staging layout (../lib beside the harness) still
works. A copy outside the repo (C10 runs this suite from a $TMPDIR copy) needs EQ_CONTAINER_DIR. The WALL lookup
(wall_dir_candidates) takes the REVIEW-pinned <repo>/lib/eq-wall before the staging copy equilibrium/wall.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

import conftest
import eq_harness as eh
from conftest import HARNESS, STAGE


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


def test_wall_dir_prefers_the_repos_reviewed_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In the repo layout the REVIEW-pinned <repo>/lib/eq-wall comes before the staging copy equilibrium/wall."""
    repo_wall, stage_wall = tmp_path / "lib" / "eq-wall", tmp_path / "equilibrium" / "wall"
    for d in (repo_wall, stage_wall):
        d.mkdir(parents=True)
        (d / "eq_wall.py").write_text("")
    monkeypatch.setattr(eh, "HERE", tmp_path / "equilibrium" / "harness")
    monkeypatch.delenv("EQ_WALL_DIR", raising=False)
    assert [d for d in eh.wall_dir_candidates() if (d / "eq_wall.py").is_file()] == [repo_wall, stage_wall]
    monkeypatch.setenv("EQ_WALL_DIR", str(stage_wall))
    assert eh.wall_dir_candidates()[0] == stage_wall


def test_in_place_run_inside_the_repo_finds_its_lib() -> None:
    """Run in place in a checkout (not a $TMPDIR copy), the real lookup lands on <repo>/lib/eq-container."""
    repo_lib = conftest.STAGE.parent / "lib" / "eq-container"
    if conftest.STAGE.name != "equilibrium" or not (repo_lib / "lib.sh").is_file():
        pytest.skip("not run in place in the stack repo (a staging or $TMPDIR copy)")
    assert repo_lib / "probe.sh" in eh.probe_script_candidates()
    assert conftest.container_dir() is not None


# ---- A5 (2026-10-06): paths derived from the script's own location, no home directory -------------------------------


def _line(script: str, var: str) -> str:
    m = re.search(rf"^{var}=.*$", (HARNESS / script).read_text(), re.M)
    assert m, (script, var)
    return m.group(0)


def _echo(d: Path, line: str, var: str, **env_extra: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    (d / "x.sh").write_text(f'{line}\necho "${var}"\n')
    env = {k: v for k, v in os.environ.items() if k not in ("EQ_M", "EQ_STAGE_DIR")} | env_extra
    out = subprocess.run(["bash", str(d / "x.sh")], capture_output=True, text=True, env=env, check=True).stdout
    return Path(out.strip()).resolve()


@pytest.mark.parametrize("script", ["eq_check.sh", "eq_freeze.sh"])
def test_shell_m_is_the_checkout_holding_the_script(tmp_path: Path, script: str) -> None:
    """M: the git checkout holding the script (repo layout and the frozen copy under claude_next_steps/ alike), else
    ../..; EQ_M still wins."""
    line, repo = _line(script, "M"), tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert _echo(repo / "equilibrium" / "harness", line, "M") == repo.resolve()
    assert _echo(repo / "claude_next_steps" / "work_carried" / "equilibrium", line, "M") == repo.resolve()
    assert _echo(tmp_path / "plain" / "equilibrium" / "harness", line, "M") == (tmp_path / "plain").resolve()
    assert _echo(repo / "equilibrium" / "harness", line, "M", EQ_M=str(tmp_path / "m")) == (tmp_path / "m").resolve()


def test_freeze_stage_is_the_package_holding_the_script(tmp_path: Path) -> None:
    line = _line("eq_freeze.sh", "STAGE")
    pkg = tmp_path / "r" / "equilibrium"
    assert _echo(pkg / "harness", line, "STAGE") == pkg.resolve()


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclasses look their module up
    try:
        spec.loader.exec_module(mod)
    finally:
        del sys.modules[name]
    return mod


def test_default_m_is_the_checkout_holding_the_harness(tmp_path: Path) -> None:
    """DEFAULT_M (the default EQ_ROOT / EQ_RAW base): the nearest ancestor holding .git (a directory or a worktree's
    file), so the frozen copy under claude_next_steps/ finds M too; else parents[2]."""
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    cases = {tmp_path / "repo" / "equilibrium" / "harness": tmp_path / "repo",
             tmp_path / "repo" / "claude_next_steps" / "work_carried" / "equilibrium": tmp_path / "repo",
             tmp_path / "wt" / "equilibrium" / "harness": tmp_path / "wt",
             tmp_path / "plain" / "equilibrium" / "harness": tmp_path / "plain"}
    for i, (d, want) in enumerate(cases.items()):
        d.mkdir(parents=True)
        shutil.copy(HARNESS / "eq_harness.py", d / "eq_harness.py")
        got = _load(d / "eq_harness.py", f"eq_harness_copy{i}").DEFAULT_M
        assert want.resolve() == got, d


def test_check_lean_default_project_is_home_relative(tmp_path: Path) -> None:
    """No EQ_LEAN_PROJECT: $HOME/lean/stack_mathlib; missing (or HOME unset under set -u) is the environment error,
    exit 2, as before."""
    fx = tmp_path / "fx"
    shutil.copytree(STAGE / "items" / "PF" / "fixtures" / "PF-DEV1", fx)
    base = {k: v for k, v in os.environ.items() if k not in ("EQ_LEAN_PROJECT", "HOME")}
    for env in ({**base, "HOME": str(tmp_path / "home")}, base):
        cp = subprocess.run(["bash", str(fx / "check_lean.sh"), str(fx / "Problem.lean")], capture_output=True,
                            text=True, env=env, check=False)
        assert cp.returncode == 2 and "Lean project missing" in cp.stderr, cp.stderr


def test_extract_src_reads_the_repo_root_and_writes_relative_sources(tmp_path: Path) -> None:
    gen = tmp_path / "repo" / "equilibrium" / "items" / "RS" / "gen"
    gen.mkdir(parents=True)
    shutil.copy(STAGE / "items" / "RS" / "gen" / "extract_src.py", gen / "extract_src.py")
    camp = tmp_path / "repo" / "claude-local-work" / "campaign" / "agents-baseline"
    camp.mkdir(parents=True)
    (camp / "prompts.csv").write_text("id,family,target_agent,expected_skills,cost_class,prompt,check,notes\n"
                                      "P01,f,coder,,s,do it,ok,\n")
    for f in ("grades.csv", "grades_T8b.csv", "grades_b0v2.csv"):
        (camp / f).write_text("id,variant,check_result,why\nP01,v1,pass,fine\n")
    (camp / "runs.csv").write_text("kind,prompt_id,is_root,depth,agent_type,model,turns,tool_calls,spawn_count,"
                                   "child_types,tokens_total,final_status,wall_s\nprompt,P01,1,0,coder,sonnet,1,1,0,,9,ok,1\n")
    mod = _load(gen / "extract_src.py", "extract_src_copy")
    assert camp.resolve() == mod.CAMPAIGN
    mod.main()
    lines = (gen / "src" / "SOURCES.sha256").read_text().splitlines()
    assert [ln.split("  ", 1)[1] for ln in lines] == [
        f"claude-local-work/campaign/agents-baseline/{n}"
        for n in ("prompts.csv", "grades.csv", "grades_T8b.csv", "grades_b0v2.csv", "runs.csv")]
