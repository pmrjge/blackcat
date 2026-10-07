"""The stack repo's layout: <repo>/dot-config/dot-equilibrium/harness, with <repo>/lib/eq-container and
<repo>/lib/eq-wall (COMPARE_eq.md §12 A9, 2026-10-07: the tree moved from <repo>/equilibrium; lib/ did not move).

The harness (probe_script_candidates) and the tests (conftest.container_dir) find lib/eq-container there without
EQ_CONTAINER_DIR (eq_harness.repo_lib_dirs: the git top level, then three levels up); EQ_CONTAINER_DIR, when set,
still comes first; the staging layout (../lib beside the harness) comes after the repo's copy. A copy outside the repo
(C10 runs this suite from a $TMPDIR copy) needs EQ_CONTAINER_DIR. The WALL lookup (wall_dir_candidates) takes the
REVIEW-pinned <repo>/lib/eq-wall before the staging copy dot-config/dot-equilibrium/wall.
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

EQ_REL = Path("dot-config") / "dot-equilibrium"  # the tree's place in the stack repo (A9)


def _container(root: Path) -> Path:
    d = root / "lib" / "eq-container"
    d.mkdir(parents=True)
    for f in ("probe.sh", "lib.sh"):
        (d / f).write_text("exit 0\n")
    return d


def test_probe_script_found_in_the_repo_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_lib = _container(tmp_path / "repo")
    monkeypatch.setattr(eh, "HERE", tmp_path / "repo" / EQ_REL / "harness")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [repo_lib / "probe.sh"]  # by depth
    (tmp_path / "repo" / ".git").mkdir()
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [repo_lib / "probe.sh"]  # the git top level
    env_lib = _container(tmp_path / "env")
    monkeypatch.setenv("EQ_CONTAINER_DIR", str(env_lib))
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [env_lib / "probe.sh", repo_lib / "probe.sh"]


def test_probe_script_repo_layout_comes_before_the_staging_layout(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    """A9: the repo's lib/eq-container first, a lib/ beside the harness (the old staging layout) only after it."""
    repo_lib = _container(tmp_path)
    stage_lib = _container(tmp_path / EQ_REL)
    monkeypatch.setattr(eh, "HERE", tmp_path / EQ_REL / "harness")
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert [c for c in eh.probe_script_candidates() if c.is_file()] == [repo_lib / "probe.sh", stage_lib / "probe.sh"]


def test_container_dir_found_in_the_repo_layout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo_lib = _container(tmp_path / "repo")
    monkeypatch.setattr(conftest, "STAGE", tmp_path / "repo" / EQ_REL)
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert conftest.container_dir() == repo_lib
    env_lib = _container(tmp_path / "env")
    monkeypatch.setenv("EQ_CONTAINER_DIR", str(env_lib))
    assert conftest.container_dir() == env_lib
    monkeypatch.setattr(conftest, "STAGE", tmp_path / "nowhere" / EQ_REL)
    monkeypatch.delenv("EQ_CONTAINER_DIR")
    assert conftest.container_dir() is None


def test_wall_dir_prefers_the_repos_reviewed_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """In the repo layout the REVIEW-pinned <repo>/lib/eq-wall comes before the staging copy
    dot-config/dot-equilibrium/wall."""
    repo_wall, stage_wall = tmp_path / "lib" / "eq-wall", tmp_path / EQ_REL / "wall"
    for d in (repo_wall, stage_wall):
        d.mkdir(parents=True)
        (d / "eq_wall.py").write_text("")
    monkeypatch.setattr(eh, "HERE", tmp_path / EQ_REL / "harness")
    monkeypatch.delenv("EQ_WALL_DIR", raising=False)
    assert [d for d in eh.wall_dir_candidates() if (d / "eq_wall.py").is_file()] == [repo_wall, stage_wall]
    monkeypatch.setenv("EQ_WALL_DIR", str(stage_wall))
    assert eh.wall_dir_candidates()[0] == stage_wall


def _repo_with_staging_copies(root: Path) -> tuple[Path, Path, Path]:
    """A stack checkout after the move (A9): <root>/.git, lib/eq-wall + lib/eq-container, and the harness at
    dot-config/dot-equilibrium/harness beside the staging copies dot-equilibrium/wall and dot-equilibrium/lib."""
    (root / ".git").mkdir(parents=True)
    harness = root / EQ_REL / "harness"
    harness.mkdir(parents=True)
    shutil.copy(HARNESS / "eq_harness.py", harness / "eq_harness.py")
    for d in (root / "lib" / "eq-wall", root / EQ_REL / "wall", root / EQ_REL / "lib" / "eq-wall"):
        d.mkdir(parents=True)
        (d / "eq_wall.py").write_text("")
    _container(root)
    _container(root / EQ_REL)
    return harness, root / "lib" / "eq-wall", root / "lib" / "eq-container"


def test_the_real_lookups_resolve_lib_never_the_staging_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A9: eq_harness.py (its own bytes, loaded from the repo layout) resolves eq_wall.py to <repo>/lib/eq-wall and
    probe.sh to <repo>/lib/eq-container while staging copies exist beside the harness."""
    monkeypatch.delenv("EQ_WALL_DIR", raising=False)
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    harness, wall, container = _repo_with_staging_copies(tmp_path / "repo")
    mod = _load(harness / "eq_harness.py", "eq_harness_repo_layout")
    found = next(d for d in mod.wall_dir_candidates() if (d / "eq_wall.py").is_file())
    assert found / "eq_wall.py" == (wall / "eq_wall.py").resolve()  # the loaded module's HERE is resolved
    assert next(c for c in mod.probe_script_candidates() if c.is_file()) == (container / "probe.sh").resolve()


def test_in_place_run_inside_the_repo_finds_its_lib(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run in place in a checkout (not a $TMPDIR copy), the real lookups land on <repo>/lib/eq-container and
    <repo>/lib/eq-wall/eq_wall.py, never the staging copy dot-config/dot-equilibrium/wall (A9)."""
    repo = conftest.STAGE.parents[1]
    repo_lib, repo_wall = repo / "lib" / "eq-container", repo / "lib" / "eq-wall"
    if conftest.STAGE.relative_to(repo) != EQ_REL or not (repo_lib / "lib.sh").is_file():
        pytest.skip("not run in place in the stack repo (a staging or $TMPDIR copy)")
    monkeypatch.delenv("EQ_WALL_DIR", raising=False)
    monkeypatch.delenv("EQ_CONTAINER_DIR", raising=False)
    assert repo_lib / "probe.sh" in eh.probe_script_candidates()
    assert next(c for c in eh.probe_script_candidates() if c.is_file()) == repo_lib / "probe.sh"
    assert conftest.container_dir() == repo_lib
    found = next(d for d in eh.wall_dir_candidates() if (d / "eq_wall.py").is_file())
    assert found / "eq_wall.py" == repo_wall / "eq_wall.py" != conftest.STAGE / "wall" / "eq_wall.py"


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
    ../../.. (A9: <repo>/dot-config/dot-equilibrium/harness; the frozen copy's three up is <repo> too); EQ_M still
    wins."""
    line, repo, plain = _line(script, "M"), tmp_path / "repo", tmp_path / "plain"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    assert _echo(repo / EQ_REL / "harness", line, "M") == repo.resolve()
    assert _echo(repo / "claude_next_steps" / "work_carried" / "equilibrium", line, "M") == repo.resolve()
    assert _echo(plain / EQ_REL / "harness", line, "M") == plain.resolve()
    assert _echo(plain / "claude_next_steps" / "work_carried" / "equilibrium", line, "M") == plain.resolve()
    assert _echo(repo / EQ_REL / "harness", line, "M", EQ_M=str(tmp_path / "m")) == (tmp_path / "m").resolve()


def test_freeze_stage_is_the_package_holding_the_script(tmp_path: Path) -> None:
    line = _line("eq_freeze.sh", "STAGE")
    pkg = tmp_path / "r" / EQ_REL
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
    file), so the frozen copy under claude_next_steps/ finds M too; else parents[3] (A9: the repo layout's root)."""
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    (tmp_path / "wt").mkdir()
    (tmp_path / "wt" / ".git").write_text("gitdir: /elsewhere/.git/worktrees/wt\n")
    cases = {tmp_path / "repo" / EQ_REL / "harness": tmp_path / "repo",
             tmp_path / "repo" / "claude_next_steps" / "work_carried" / "equilibrium": tmp_path / "repo",
             tmp_path / "wt" / EQ_REL / "harness": tmp_path / "wt",
             tmp_path / "plain" / EQ_REL / "harness": tmp_path / "plain"}
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
    gen = tmp_path / "repo" / EQ_REL / "items" / "RS" / "gen"  # A9: the campaign is five levels up again
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
