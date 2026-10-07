"""The tracked Equilibrium experiment (equilibrium/, README there): its layout stays whole and its run outputs stay out.

The file set is git's view of what is or would be tracked (`ls-files --cached --others --exclude-standard`), so the
checks hold before and after a commit and follow .gitignore. The suite fails when
- a top-level entry, a pool (items/<CLS>/ for PF, CP, CR, RS, ES, DS, OE) or a key harness file is missing;
- a pool file differs from its pool.sha256 entry, or a pool holds a file its pool.sha256 does not list (README.md and
  proof_report.txt aside);
- a file is over 1 MiB, except items/RS/manifest.jsonl (2.8 MB, pinned by RS/pool.sha256; git stores it compressed);
- run outputs, logs or caches would be tracked (any runs/ but the RS corpus fixture, *.log, __pycache__,
  .ruff_cache, .pytest_cache, .eq_deps), or a fixture .gitignore would drop (the PF oracle's build/ records, the RS
  corpus runs/ fixture);
- a script lost its executable bit.
The harness's own suite (equilibrium/harness/tests, 452 tests) runs as a separate C10 step (CONFIG.md, C10).

Run: uv run --no-project --with pytest pytest -q tests/test_equilibrium_layout.py
"""
import hashlib
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
EQ = "equilibrium"
POOLS = ("PF", "CP", "CR", "RS", "ES", "DS", "OE")
MIB = 1 << 20
BIG = {"equilibrium/items/RS/manifest.jsonl": 3 * MIB}  # the one file over 1 MiB, with its own cap
TOP = {
    "README.md", "CONTRACT.md", "COMPARE_eq.md", "ISOLATION.md", "MEDIATOR.md", "PROPOSAL.md",
    "derive_numbers.py", "derive_numbers.out", "mediator_numbers.py", "mediator_numbers.out", "r3_check.py",
    "r3_check.out", "refute_check.py", "refute_check.out", "seeds.out", "shift_check.py", "shift_check.out",
    "analysis-r1", "analysis-r2", "calibration", "harness", "isolation", "items", "proof-check", "wall",
    "PATH_RELATIVISATION.md", "PATH_RELATIVISATION.json",  # COMPARE_eq.md A5 (tests/equilibrium_paths.py)
}
HARNESS = (
    "eq_harness.py", "eq_mediator.py", "eq_analyse.py", "eq_route2.py", "eq_route2.sql", "eq_check.sh",
    "eq_freeze.sh", "flags.json", "schedule.tsv", "stub_claude", "README.md", "LEDGER_SCHEMA.md", "ruff.toml",
    "tests/conftest.py", "tests/fake_container", "tests/test_skill_tools_argv.py", "tests/test_repo_layout.py",
    "tests/test_isolation.py", "tests/test_wall_integration.py",
)
POOL_UNLISTED = {"README.md", "pool.sha256", "proof_report.txt"}  # pool files outside pool.sha256
EXECUTABLE = (
    "harness/eq_check.sh", "harness/eq_freeze.sh", "harness/stub_claude", "harness/tests/fake_container",
    "isolation/probe.sh", "isolation/build.sh", "isolation/lib.sh",
    *(f"items/{c}/selftest.sh" for c in ("CP", "CR", "RS", "DS", "OE")),
)
RS_RUNS = f"{EQ}/items/RS/fixtures/corpus/runs/"  # a tracked fixture, not run output
NEVER = ("/__pycache__/", "/.ruff_cache/", "/.pytest_cache/", "/.eq_deps/", "/.DS_Store")


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True).stdout.decode(
        "utf-8", "surrogateescape")


@pytest.fixture(scope="module")
def files() -> list[str]:
    out = git("ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", EQ)
    found = sorted({p for p in out.split("\0") if p and (ROOT / p).is_file()})
    assert found, "equilibrium/ is missing from this checkout (tracked since bd3a182)"
    return found


def rel(paths: list[str], prefix: str) -> set[str]:
    return {p[len(prefix):] for p in paths if p.startswith(prefix)}


def test_top_level_entries(files: list[str]) -> None:
    top = {p.split("/")[1] for p in files}
    assert top == TOP, f"missing {sorted(TOP - top)}, unexpected {sorted(top - TOP)}"


def test_harness_files_present(files: list[str]) -> None:
    have = rel(files, f"{EQ}/harness/")
    assert not [h for h in HARNESS if h not in have]


@pytest.mark.parametrize("cls", POOLS)
def test_pool_matches_its_sha256(files: list[str], cls: str) -> None:
    base = f"{EQ}/items/{cls}/"
    have = rel(files, base)
    listed = {}
    for line in (ROOT / base / "pool.sha256").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        listed[name.removeprefix("./")] = digest
    assert {"README.md", "manifest.jsonl", "oracle.py", "schema.json", "pool.sha256"} <= have
    assert not sorted(set(listed) - have), "listed in pool.sha256 but not tracked"
    assert not sorted(have - set(listed) - POOL_UNLISTED), "tracked but not in pool.sha256"
    bad = [n for n, d in listed.items() if hashlib.sha256((ROOT / base / n).read_bytes()).hexdigest() != d]
    assert not bad, f"{cls}: {len(bad)} files differ from pool.sha256, e.g. {bad[:3]}"


def test_graders_present(files: list[str]) -> None:
    assert rel(files, f"{EQ}/items/graders/") == {f"grader_brief_{c}.md" for c in ("CR", "DS", "OE", "RS")}


def test_size_cap(files: list[str]) -> None:
    over = {p: (ROOT / p).stat().st_size for p in files if (ROOT / p).stat().st_size > BIG.get(p, MIB)}
    assert not over, f"over the cap (1 MiB; {BIG}): {over}"


def test_no_run_outputs_logs_or_caches(files: list[str]) -> None:
    bad = [p for p in files if ("/runs/" in p and not p.startswith(RS_RUNS)) or p.endswith(".log")
           or any(n in f"/{p}" for n in NEVER)]
    assert not bad


def test_fixtures_the_blanket_ignores_would_drop_are_tracked(files: list[str]) -> None:
    assert {"final_check.tsv", "selftest.out", "verify_results.jsonl"} <= rel(files, f"{EQ}/items/PF/oracle/build/")
    assert len(rel(files, RS_RUNS)) == 40


def test_run_outputs_are_ignored() -> None:
    for p in (f"{EQ}/runs/p/ledger.jsonl", f"{EQ}/harness/runs/d/ledger.jsonl", f"{EQ}/x/raw/runs/p/a.json",
              f"{EQ}/harness/.eq_deps/n1.json", f"{EQ}/isolation/build.log"):
        assert subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", p]).returncode == 0, p
    for p in (f"{EQ}/items/PF/oracle/build/selftest.out", f"{EQ}/items/RS/fixtures/corpus/runs/P03.md"):
        assert subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", p]).returncode == 1, p


def test_scripts_keep_their_executable_bit(files: list[str]) -> None:
    have = set(files)
    for p in EXECUTABLE:
        assert f"{EQ}/{p}" in have, p
        assert (ROOT / EQ / p).stat().st_mode & 0o111, p
