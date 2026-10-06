"""Throwaway-repo tests for hand_off/RESET_TO_MAIN.sh.

Run: uv run --with pytest pytest -q hand_off/tests

Each test builds its own repository under pytest's tmp_path: main, a merged branch, unmerged
branches, a clean, a dirty, a locked, a live, a rebase-in-progress, a session and a caller
worktree, nested worktrees (one parent holding a locked child) and an H worktree processed last.
The script runs with /bin/bash (3.2 on macOS) and never sees the real repository.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import tarfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# RESET_TO_MAIN_SCRIPT points the suite at a mutated copy (to check that the suite catches bugs)
SCRIPT = Path(os.environ.get("RESET_TO_MAIN_SCRIPT") or Path(__file__).resolve().parents[1] / "RESET_TO_MAIN.sh")
BASH = "/bin/bash"
OLD = time.time() - 3 * 3600  # older than the 60-minute live window


def _env(base: Path, tmpdir: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@example.invalid",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@example.invalid",
        GIT_CEILING_DIRECTORIES=str(base),
        HOME=str(base / "home"),
        TMPDIR=str(tmpdir),
        LC_ALL="C",
    )
    return env


def backdate(*paths: Path) -> None:
    """Set mtime/atime of every entry under each path (and the path itself) to OLD."""
    for top in paths:
        if not top.exists() and not top.is_symlink():
            continue
        os.utime(top, (OLD, OLD), follow_symlinks=False)
        if top.is_dir() and not top.is_symlink():
            for dirpath, dirnames, filenames in os.walk(top):
                for name in dirnames + filenames:
                    os.utime(os.path.join(dirpath, name), (OLD, OLD), follow_symlinks=False)


def snapshot(root: Path) -> dict[str, tuple]:
    """Type, mode, size, mtime and content hash of every entry under root."""
    out: dict[str, tuple] = {}
    for dirpath, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames, ""]:
            p = os.path.join(dirpath, name) if name else dirpath
            st = os.lstat(p)
            entry: tuple = (stat.S_IFMT(st.st_mode), st.st_mode, st.st_size, st.st_mtime_ns)
            if stat.S_ISREG(st.st_mode):
                entry += (hashlib.sha256(Path(p).read_bytes()).hexdigest(),)
            out[p] = entry
    return out


def parse_summary(out: str) -> dict[tuple[str, str], tuple[str, str, str]]:
    """(kind, name) -> (class, action, reason) from the fixed-width summary table."""
    lines = out.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("== Summary"))
    header = lines[start + 1]
    cols = [header.index(h) for h in ("KIND", "NAME", "CLASS", "ACTION", "REASON")]
    rows = {}
    for line in lines[start + 2 :]:
        if not line.strip() or line.startswith(("Dry run", "Archive", "Apply")):
            break
        cells = [line[a:b].strip() for a, b in zip(cols, [*cols[1:], len(line) + 1])]
        rows[(cells[0], cells[1])] = (cells[2], cells[3], cells[4])
    return rows


@dataclass
class World:
    base: Path
    tmpdir: Path
    m: Path
    archive: Path
    wt: dict[str, Path] = field(default_factory=dict)

    @property
    def env(self) -> dict[str, str]:
        return _env(self.base, self.tmpdir)

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
        p = subprocess.run(["git", *args], cwd=cwd or self.m, env=self.env, capture_output=True, text=True)
        if check and p.returncode != 0:
            raise AssertionError(f"git {args} failed: {p.stderr}")
        return p

    def run(self, *args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [BASH, str(SCRIPT), *args], cwd=cwd or self.m, env=env or self.env, capture_output=True, text=True
        )

    def common(self) -> list[str]:
        """Options every run uses: the throwaway named items, the session, H and the archive dir."""
        return [
            "--no-default-items",
            "--item", f"eqt={self.m / '.claude-work/eqt'}",
            "--secret-item", f"transcripts={self.m / '.claude-work/ctx/transcripts'}",
            "--session-wt", str(self.wt["sess"]),
            "--last", str(self.wt["H"]),
            "--dir", str(self.archive),
        ]

    def worktrees(self) -> list[str]:
        out = self.git("worktree", "list", "--porcelain").stdout
        return [line.split(" ", 1)[1] for line in out.splitlines() if line.startswith("worktree ")]

    def branches(self) -> set[str]:
        out = self.git("for-each-ref", "--format=%(refname:short)", "refs/heads").stdout
        return set(out.split())


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


@pytest.fixture
def world(tmp_path: Path) -> World:
    base = Path(os.path.realpath(tmp_path)) / "w"
    base.mkdir()
    tmpdir = Path(os.path.realpath(tmp_path)) / "script-tmp"
    tmpdir.mkdir()
    (base / "home").mkdir()
    m = base / "M"
    m.mkdir()
    w = World(base=base, tmpdir=tmpdir, m=m, archive=base / "archive")
    g = w.git
    g("init", "-q", "-b", "main", str(m), cwd=base)
    _write(m / ".gitignore", ".claude-work/\n.claude/worktrees/\n__pycache__/\n")
    _write(m / "a.txt", "one\n")
    _write(m / "b.txt", "bee\n")
    g("add", ".")
    g("commit", "-q", "-m", "init")
    g("branch", "rebase-br")  # forks before main changes a.txt: its rebase will conflict
    g("branch", "merged")
    _write(m / "a.txt", "main two\n")
    g("commit", "-q", "-am", "main: a.txt")
    wts = m / ".claude/worktrees"

    # unmerged branch feat with its own clean worktree
    g("worktree", "add", "-q", "-b", "feat", str(wts / "feat-wt"))
    _write(wts / "feat-wt/f.txt", "feature\n")
    g("add", "f.txt", cwd=wts / "feat-wt")
    g("commit", "-q", "-m", "feat work", cwd=wts / "feat-wt")
    w.wt["feat"] = wts / "feat-wt"

    # clean merged worktree with ignored scratch and a cache
    g("worktree", "add", "-q", "-b", "clean-br", str(wts / "clean-wt"))
    _write(wts / "clean-wt/.claude-work/notes.txt", "scratch notes\n")
    _write(wts / "clean-wt/__pycache__/x.pyc", "cache\n")
    w.wt["clean"] = wts / "clean-wt"

    # dirty worktree: tracked change, untracked file, ignored scratch
    g("worktree", "add", "-q", "-b", "dirty-br", str(wts / "dirty-wt"))
    _write(wts / "dirty-wt/a.txt", "dirty edit\n")
    _write(wts / "dirty-wt/new.txt", "untracked\n")
    _write(wts / "dirty-wt/.claude-work/d.txt", "dirty scratch\n")
    w.wt["dirty"] = wts / "dirty-wt"

    # locked worktree
    g("worktree", "add", "-q", "-b", "locked-br", str(wts / "locked-wt"))
    g("worktree", "lock", "--reason", "claude agent test (pid 1)", str(wts / "locked-wt"))
    w.wt["locked"] = wts / "locked-wt"

    # live worktree (its marker is touched after the backdate below)
    g("worktree", "add", "-q", "-b", "live-br", str(wts / "live-wt"))
    w.wt["live"] = wts / "live-wt"

    # rebase in progress, stopped on a conflict
    g("worktree", "add", "-q", str(wts / "rebase-wt"), "rebase-br")
    _write(wts / "rebase-wt/a.txt", "rebase side\n")
    g("commit", "-q", "-am", "rebase-br: a.txt", cwd=wts / "rebase-wt")
    p = g("rebase", "main", cwd=wts / "rebase-wt", check=False)
    assert p.returncode != 0, "the rebase was meant to stop on a conflict"
    w.wt["rebase"] = wts / "rebase-wt"

    # caller and session worktrees (clean, merged)
    g("worktree", "add", "-q", "-b", "caller-br", str(wts / "caller-wt"))
    w.wt["caller"] = wts / "caller-wt"
    g("worktree", "add", "-q", "-b", "sess-br", str(wts / "sess-wt"))
    w.wt["sess"] = wts / "sess-wt"

    # W outside M (detached, merged) holding a nested worktree with an unmerged branch
    g("worktree", "add", "-q", "--detach", str(base / "W"), "main")
    g("worktree", "add", "-q", "-b", "nested-br", str(base / "W/.claude/worktrees/nested"))
    _write(base / "W/.claude/worktrees/nested/n.txt", "nested\n")
    g("add", "n.txt", cwd=base / "W/.claude/worktrees/nested")
    g("commit", "-q", "-m", "nested work", cwd=base / "W/.claude/worktrees/nested")
    w.wt["W"] = base / "W"
    w.wt["nested"] = base / "W/.claude/worktrees/nested"

    # W2 holding a locked nested worktree: W2 must be kept too
    g("worktree", "add", "-q", "--detach", str(base / "W2"), "main")
    g("worktree", "add", "-q", "-b", "lk-br", str(base / "W2/.claude/worktrees/lk"))
    g("worktree", "lock", str(base / "W2/.claude/worktrees/lk"))
    w.wt["W2"] = base / "W2"
    w.wt["lk"] = base / "W2/.claude/worktrees/lk"

    # H, processed last
    g("worktree", "add", "-q", "-b", "h-br", str(base / "H"))
    w.wt["H"] = base / "H"

    # a branch with a unique commit and no worktree
    tree = g("rev-parse", "main^{tree}").stdout.strip()
    sha = g("commit-tree", tree, "-p", "main", "-m", "side work").stdout.strip()
    g("update-ref", "refs/heads/side", sha)

    # ignored data in M: named items (one secret) and a stray file
    _write(m / ".claude-work/eqt/state.json", '{"eq": "t"}\n')
    _write(m / ".claude-work/ctx/transcripts/t1.jsonl", '{"secret": "maybe"}\n')
    _write(m / ".claude-work/other/log.txt", "log\n")
    _write(m / "stray.txt", "stray\n")

    backdate(base)
    _write(wts / "live-wt/live.txt", "being written now\n")  # the live marker: fresh mtime
    return w


def manifest_rows(archive: Path) -> list[list[str]]:
    lines = (archive / "MANIFEST.tsv").read_text().splitlines()
    return [line.split("\t") for line in lines if line and not line.startswith("#")]


# ------------------------------------------------------------------ static checks


def test_bash_syntax() -> None:
    p = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_shellcheck_clean() -> None:
    sc = shutil.which("shellcheck")
    if sc is None:
        pytest.skip("shellcheck not installed")
    p = subprocess.run([sc, "-x", "-s", "bash", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


def test_help_documents_modes_and_exit_codes(world: World) -> None:
    p = world.run("--help")
    assert p.returncode == 0
    for text in ("--archive", "--apply", "--clean", "--gc", "Exit codes", "never rm -rf"):
        assert text in p.stdout
    for code in range(7):
        assert f"\n  {code}  " in p.stdout


@pytest.mark.parametrize(
    "args",
    [["--bogus"], ["--archive", "--apply"], ["--resume"], ["--archive", "--clean"], ["--live-minutes", "x"]],
)
def test_usage_errors_exit_2(world: World, args: list[str]) -> None:
    p = world.run(*args)
    assert p.returncode == 2, p.stdout + p.stderr


# ------------------------------------------------------------------ dry run


def test_dry_run_writes_nothing_and_classifies(world: World) -> None:
    before = snapshot(world.base)
    p = world.run(*world.common(), "--clean", "--gc")
    after = snapshot(world.base)
    assert p.returncode == 0, p.stdout + p.stderr
    assert before == after, "the dry run changed files under the throwaway tree"
    assert not world.archive.exists()
    assert list(world.tmpdir.iterdir()) == [], "the dry run wrote temp files"

    rows = parse_summary(p.stdout)
    wt = {k: rows[("worktree", n)] for k, n in {
        "M": "M",
        "clean": "M/.claude/worktrees/clean-wt",
        "dirty": "M/.claude/worktrees/dirty-wt",
        "feat": "M/.claude/worktrees/feat-wt",
        "locked": "M/.claude/worktrees/locked-wt",
        "live": "M/.claude/worktrees/live-wt",
        "rebase": "M/.claude/worktrees/rebase-wt",
        "sess": "M/.claude/worktrees/sess-wt",
        "W": str(world.wt["W"]),
        "nested": str(world.wt["nested"]),
        "W2": str(world.wt["W2"]),
        "lk": str(world.wt["lk"]),
        "H": str(world.wt["H"]),
    }.items()}
    assert wt["M"][0] == "MAIN"
    assert wt["clean"][:2] == ("CLEAN", "remove")
    assert wt["dirty"][:2] == ("DIRTY", "remove --force")
    assert wt["feat"][0] == "CLEAN"
    assert wt["locked"][0] == "LOCKED" and "claude agent test" in wt["locked"][2]
    assert wt["live"][0] == "LIVE" and "live.txt" in wt["live"][2]
    assert wt["rebase"][0] == "IN-PROGRESS" and "rebase" in wt["rebase"][2]
    assert wt["sess"][0] == "SESSION"
    assert wt["nested"][0] == "CLEAN" and wt["W"][0] == "CLEAN"
    assert wt["lk"][0] == "LOCKED"
    assert wt["W2"][0] == "NESTED" and "W2/.claude/worktrees/lk" in wt["W2"][2]
    br = {name: rows[("branch", name)] for name in ("main", "merged", "feat", "side", "rebase-br", "locked-br", "clean-br")}
    assert br["main"][:2] == ("MAIN", "keep")
    assert br["merged"][:2] == ("MERGED", "branch -d")
    assert br["feat"][:2] == ("UNIQUE", "branch -D")
    assert br["side"][:2] == ("UNIQUE", "branch -D")
    assert br["rebase-br"][:2] == ("KEPT", "skip")
    assert br["locked-br"][:2] == ("KEPT", "skip")
    assert br["clean-br"][:2] == ("MERGED", "branch -d")

    # every planned command is printed: bundles, tarballs, removals in order, branch deletions
    out = p.stdout
    assert "bundle create -q" in out and "refs/heads/feat ^refs/heads/main" in out
    assert "refs/heads/merged ^refs/heads/main" not in out
    assert f"worktree remove --force {world.wt['dirty']}" in out
    assert "branch -D side" in out and "branch -d merged" in out
    assert "clean -ndx" in out and "clean -fdx" in out
    assert "gc would be refused now" in out
    removes = [line for line in out.splitlines() if "worktree remove" in line]
    assert str(world.wt["H"]) in removes[-1], "H must come last"
    order = [i for i, line in enumerate(removes) if str(world.wt["nested"]) in line or line.endswith(str(world.wt["W"]) + "    # CLEAN")]
    assert len(order) == 2 and str(world.wt["nested"]) in removes[order[0]], "nested before its parent"
    assert "claude_info/:   not tracked on main" in out
    assert "[secret: tarball mode 0600]" in out


def test_dry_run_from_a_worktree_marks_it_caller(world: World) -> None:
    p = world.run(*world.common(), cwd=world.wt["caller"])
    assert p.returncode == 0, p.stderr
    rows = parse_summary(p.stdout)
    assert rows[("worktree", "M/.claude/worktrees/caller-wt")][:2] == ("CALLER", "keep")
    assert rows[("branch", "caller-br")][:2] == ("KEPT", "skip")


# ------------------------------------------------------------------ stage 1


def test_archive_creates_verified_bundles_tarballs_manifest(world: World) -> None:
    p = world.run(*world.common(), "--archive")
    assert p.returncode == 0, p.stdout + p.stderr
    a = world.archive
    assert stat.S_IMODE(a.stat().st_mode) == 0o700
    sha_line = (a / "MANIFEST.tsv.sha256").read_text().split()
    assert sha_line[0] == hashlib.sha256((a / "MANIFEST.tsv").read_bytes()).hexdigest()
    rows = manifest_rows(a)
    assert rows, "empty manifest"
    for kind, source, rel, sha, size, state in rows:
        f = a / rel
        assert f.is_file(), rel
        assert hashlib.sha256(f.read_bytes()).hexdigest() == sha, rel
        assert str(f.stat().st_size) == size, rel
        assert stat.S_IMODE(f.stat().st_mode) == 0o600, rel
        if kind.startswith("bundle"):
            assert world.git("bundle", "verify", "-q", str(f), check=False).returncode == 0, rel
    kinds = {(r[0], r[1]) for r in rows}
    assert ("bundle-main", "refs/heads/main") in kinds
    assert ("bundle", "refs/heads/feat") in kinds and ("bundle", "refs/heads/side") in kinds
    assert ("bundle", "refs/heads/nested-br") in kinds and ("bundle", "refs/heads/rebase-br") in kinds
    assert ("bundle", "refs/heads/merged") not in kinds, "merged branches need no bundle"
    for key in ("clean", "dirty", "locked", "live", "W", "nested", "H"):
        for kind in ("wt-status", "wt-diff", "wt-files", "wt-data"):
            assert (kind, str(world.wt[key])) in kinds, (kind, key)
    assert ("wt-data", str(world.m)) in kinds
    assert ("data", str(world.m / ".claude-work/eqt")) in kinds
    assert ("secret-data", str(world.m / ".claude-work/ctx/transcripts")) in kinds
    assert "0600" in p.stdout and "secrets" in p.stdout

    by = {(r[0], r[1]): r for r in rows}
    data = a / by[("wt-data", str(world.wt["dirty"]))][2]
    with tarfile.open(data) as t:
        names = set(t.getnames())
    assert {"new.txt", ".claude-work/d.txt"} <= names
    diff = (a / by[("wt-diff", str(world.wt["dirty"]))][2]).read_text()
    assert diff.startswith("HEAD ") and "+dirty edit" in diff
    with tarfile.open(a / by[("wt-data", str(world.wt["clean"]))][2]) as t:
        names = set(t.getnames())
    assert ".claude-work/notes.txt" in names and not any("__pycache__" in n for n in names)
    with tarfile.open(a / by[("wt-data", str(world.wt["W"]))][2]) as t:
        assert not any(n.startswith(".claude/worktrees/nested") for n in t.getnames()), "nested worktree leaked into its parent's tarball"
    heads = world.git("bundle", "list-heads", str(a / by[("bundle", "refs/heads/feat")][2])).stdout
    assert world.git("rev-parse", "feat").stdout.strip() in heads


def test_archive_refuses_non_empty_dir_unless_resume(world: World) -> None:
    world.archive.mkdir()
    (world.archive / "someone-else.txt").write_text("keep me\n")
    p = world.run(*world.common(), "--archive")
    assert p.returncode == 3, p.stdout + p.stderr
    assert "not empty" in p.stderr
    assert sorted(x.name for x in world.archive.iterdir()) == ["someone-else.txt"]
    p = world.run(*world.common(), "--archive", "--resume")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (world.archive / "someone-else.txt").read_text() == "keep me\n"
    p = world.run(*world.common(), "--archive", "--resume")
    assert p.returncode == 0 and "keep " in p.stdout, "a second resume keeps the rows that still match"


def test_archive_refuses_dir_inside_a_worktree(world: World) -> None:
    args = [a for a in world.common()]
    args[args.index("--dir") + 1] = str(world.m / ".claude-work/archive")
    p = world.run(*args, "--archive")
    assert p.returncode == 3, p.stdout + p.stderr
    assert not (world.m / ".claude-work/archive").exists()


# ------------------------------------------------------------------ stage 2 refusals


def _state(world: World) -> tuple:
    return (world.worktrees(), sorted(world.branches()))


def test_apply_refuses_without_a_manifest(world: World) -> None:
    before = _state(world)
    p = world.run(*world.common(), "--apply")
    assert p.returncode == 4, p.stdout + p.stderr  # no DIR at all
    world.archive.mkdir()
    p = world.run(*world.common(), "--apply")
    assert p.returncode == 4, p.stdout + p.stderr  # DIR without MANIFEST.tsv
    assert _state(world) == before
    assert world.wt["clean"].is_dir()


def test_apply_refuses_after_a_tampered_tarball(world: World) -> None:
    assert world.run(*world.common(), "--archive").returncode == 0
    before = _state(world)
    rows = manifest_rows(world.archive)
    tgz = world.archive / next(r[2] for r in rows if r[0] == "wt-data" and r[1] == str(world.wt["clean"]))
    data = bytearray(tgz.read_bytes())
    data[len(data) // 2] ^= 0xFF
    tgz.write_bytes(bytes(data))
    p = world.run(*world.common(), "--apply")
    assert p.returncode == 4, p.stdout + p.stderr
    assert "nothing was changed" in p.stderr
    assert _state(world) == before
    assert world.wt["clean"].is_dir() and world.wt["dirty"].is_dir()


def test_apply_refuses_a_tampered_manifest(world: World) -> None:
    assert world.run(*world.common(), "--archive").returncode == 0
    before = _state(world)
    man = world.archive / "MANIFEST.tsv"
    man.write_text(man.read_text().replace("wt-data", "wt-data ", 1))
    p = world.run(*world.common(), "--apply")
    assert p.returncode == 4, p.stdout + p.stderr
    assert _state(world) == before


# ------------------------------------------------------------------ stage 2


def test_apply_removes_only_what_is_archived(world: World) -> None:
    assert world.run(*world.common(), "--archive").returncode == 0
    g = world.git
    # after the archive: a new worktree, a new file in an archived one, a new and a moved unmerged branch
    g("worktree", "add", "-q", "-b", "late-br", str(world.m / ".claude/worktrees/late-wt"))
    late_gitdir = Path(g("rev-parse", "--absolute-git-dir", cwd=world.m / ".claude/worktrees/late-wt").stdout.strip())
    backdate(world.m / ".claude/worktrees/late-wt", late_gitdir)
    _write(world.wt["clean"] / ".claude-work/after.txt", "written after the archive\n")
    backdate(world.wt["clean"])
    _write(world.wt["feat"] / "f.txt", "tracked edit after the archive\n")
    backdate(world.wt["feat"])
    tree = g("rev-parse", "main^{tree}").stdout.strip()
    late = g("commit-tree", tree, "-p", "main", "-m", "late unmerged").stdout.strip()
    g("update-ref", "refs/heads/late-unmerged", late)
    moved = g("commit-tree", tree, "-p", "side", "-m", "side moved on").stdout.strip()
    g("update-ref", "refs/heads/side", moved)

    p = world.run(*world.common(), "--apply", "--gc", cwd=world.wt["caller"])
    out = p.stdout
    assert p.returncode == 5, out + p.stderr  # blockers remain by design

    # removed: archived, unchanged, not blocked
    for key in ("dirty", "nested", "W", "H"):
        assert not world.wt[key].exists(), key
    assert f"worktree remove --force {world.wt['dirty']}" in out
    assert f"worktree remove {world.wt['nested']}" in out
    assert f"worktree remove --force {world.wt['nested']}" not in out, "--force only for dirty worktrees"
    # kept: changed since the archive (untracked or tracked), not in the archive, blockers, the caller
    rows = parse_summary(out)
    assert world.wt["clean"].is_dir() and (world.wt["clean"] / ".claude-work/notes.txt").is_file()
    assert "changed since the archive" in rows[("worktree", "M/.claude/worktrees/clean-wt")][2]
    assert (world.wt["feat"] / "f.txt").read_text() == "tracked edit after the archive\n"
    assert "tracked changes differ" in rows[("worktree", "M/.claude/worktrees/feat-wt")][2]
    assert (world.m / ".claude/worktrees/late-wt").is_dir()
    assert "not in the archive" in rows[("worktree", "M/.claude/worktrees/late-wt")][2]
    for key in ("locked", "live", "rebase", "sess", "caller", "W2", "lk"):
        assert world.wt[key].is_dir(), key
        assert str(world.wt[key]) in world.worktrees(), key
    assert rows[("worktree", "M/.claude/worktrees/caller-wt")][0] == "CALLER"
    assert (world.wt["rebase"] / "a.txt").exists()
    assert "rebase-merge" in os.listdir(Path(g("rev-parse", "--absolute-git-dir", cwd=world.wt["rebase"]).stdout.strip()))

    # branches: -D only where a verified bundle holds the current tip
    branches = world.branches()
    assert "nested-br" not in branches
    assert "merged" not in branches and "dirty-br" not in branches and "h-br" not in branches
    assert {"feat", "side", "late-unmerged", "late-br", "clean-br", "rebase-br", "locked-br", "caller-br", "main"} <= branches
    assert "branch -D nested-br" in out and "branch -D side" not in out and "branch -D late-unmerged" not in out
    assert "branch -D feat" not in out, "feat is still checked out in the kept feat-wt"
    assert "branch -d merged" in out
    assert g("rev-parse", "side").stdout.strip() == moved

    # order: nested before its parent, H last
    removes = [line for line in out.splitlines() if "worktree remove" in line]
    assert str(world.wt["H"]) in removes[-1]
    idx_nested = next(i for i, line in enumerate(removes) if str(world.wt["nested"]) in line)
    idx_w = next(i for i, line in enumerate(removes) if line.rstrip().endswith(str(world.wt["W"])))
    assert idx_nested < idx_w

    # gc refused while live/locked worktrees remain; M untouched without --clean
    assert "live or locked worktrees remain" in rows[("step", "gc")][2]
    assert (world.m / "stray.txt").is_file() and (world.m / ".claude-work/eqt/state.json").is_file()


def test_apply_never_removes_the_cwd_worktree(world: World) -> None:
    assert world.run(*world.common(), "--archive").returncode == 0
    p = world.run(*world.common(), "--apply", cwd=world.wt["caller"])
    assert p.returncode == 5, p.stdout + p.stderr
    assert world.wt["caller"].is_dir()
    assert str(world.wt["caller"]) in world.worktrees()
    assert "caller-br" in world.branches()


ODD_NAME = '.claude-work/scratch/we"ird\tname é\\x.txt'  # quote, tab, non-ASCII, backslash


def small_world(tmp_path: Path) -> tuple[World, dict[str, str]]:
    """M plus one worktree `topic` (unmerged commit, uncommitted wip), scratch in M, a reflog-only commit."""
    base = Path(os.path.realpath(tmp_path)) / "w"
    base.mkdir()
    tmpdir = Path(os.path.realpath(tmp_path)) / "script-tmp"
    tmpdir.mkdir()
    (base / "home").mkdir()
    m = base / "M"
    m.mkdir()
    w = World(base=base, tmpdir=tmpdir, m=m, archive=base / "archive")
    g = w.git
    g("init", "-q", "-b", "main", str(m), cwd=base)
    _write(m / ".gitignore", ".claude-work/\n.claude/worktrees/\n")
    _write(m / "a.txt", "one\n")
    g("add", ".")
    g("commit", "-q", "-m", "init")
    topic = m / ".claude/worktrees/topic"
    g("worktree", "add", "-q", "-b", "topic", str(topic))
    _write(topic / "t.txt", "topic\n")
    g("add", "t.txt", cwd=topic)
    g("commit", "-q", "-m", "topic work", cwd=topic)
    _write(topic / "wip.txt", "uncommitted wip\n")
    _write(m / ".claude-work/scratch/s.txt", "scratch\n")
    _write(m / ODD_NAME, "odd name\n")
    g("commit", "-q", "--allow-empty", "-m", "dropped later")  # a commit only a reflog reaches
    dropped = g("rev-parse", "HEAD").stdout.strip()
    g("reset", "-q", "--hard", "HEAD~1")
    w.wt["topic"] = topic
    backdate(base)
    return w, {"topic": g("rev-parse", "topic").stdout.strip(), "dropped": dropped}


def small_args(w: World) -> list[str]:
    return ["--no-default-items", "--last", str(w.base / "none"), "--dir", str(w.archive)]


def test_full_reset_clean_gc_and_restore(tmp_path: Path) -> None:
    """No blockers: --apply --clean --gc leaves only main; the archive restores what was removed."""
    w, sha = small_world(tmp_path)
    g, m, base = w.git, w.m, w.base
    p = w.run(*small_args(w), "--archive")
    assert p.returncode == 0, p.stdout + p.stderr
    p = w.run(*small_args(w), "--apply", "--clean", "--gc")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.worktrees() == [str(m)]
    assert w.branches() == {"main"}
    assert not (m / ".claude-work").exists() and not w.wt["topic"].exists()
    cleans = [line for line in p.stdout.splitlines() if line.startswith("  $ git") and " clean -" in line]
    assert [c.rsplit(" ", 1)[1] for c in cleans] == ["-ndx", "-fdx"], "git clean -ndx is shown before -fdx"
    assert f"worktree remove --force {w.wt['topic']}" in p.stdout
    assert g("cat-file", "-e", sha["dropped"], check=False).returncode != 0, "gc should have dropped it"

    # restore everything from the archive into a fresh clone
    rows = manifest_rows(w.archive)
    by = {(r[0], r[1]): w.archive / r[2] for r in rows}
    clone = base / "restored"
    g("clone", "-q", str(by[("bundle-main", "refs/heads/main")]), str(clone), cwd=base)
    g("fetch", "-q", str(by[("bundle", "refs/heads/topic")]), "refs/heads/*:refs/heads/*", cwd=clone)
    assert g("rev-parse", "topic", cwd=clone).stdout.strip() == sha["topic"]
    pack = next(f for (k, _), f in by.items() if k == "pack")
    with pack.open("rb") as fh:
        subprocess.run(["git", "index-pack", "--stdin"], cwd=clone, env=w.env, stdin=fh, check=True, capture_output=True)
    assert g("cat-file", "-e", sha["dropped"], cwd=clone, check=False).returncode == 0
    g("worktree", "add", "-q", str(base / "topic-restored"), "topic", cwd=clone)
    with tarfile.open(by[("wt-data", str(w.wt["topic"]))]) as t:
        t.extractall(base / "topic-restored", filter="data")
    assert (base / "topic-restored/wip.txt").read_text() == "uncommitted wip\n"
    with tarfile.open(by[("wt-data", str(m))]) as t:
        names = t.getnames()
    assert ".claude-work/scratch/s.txt" in names
    assert ODD_NAME in names, "odd but legal file names are archived"


def test_newline_and_backslash_names_are_archived(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    odd = ".claude-work/old\nnew\\nline.txt"  # a real newline and a literal backslash-n
    _write(w.wt["topic"] / odd, "x\n")
    nested_repo = w.wt["topic"] / ".claude-work/own-repo"  # a nested repository that is not a worktree
    nested_repo.mkdir(parents=True)
    w.git("init", "-q", str(nested_repo), cwd=w.base)
    _write(nested_repo / "inner\nfile.txt", "inner\n")
    backdate(w.base)
    p = w.run(*small_args(w), "--archive")
    assert p.returncode == 0, p.stdout + p.stderr
    p = w.run(*small_args(w), "--apply")
    assert p.returncode == 0, p.stdout + p.stderr
    assert not w.wt["topic"].exists()
    rows = manifest_rows(w.archive)
    tgz = w.archive / next(r[2] for r in rows if r[0] == "wt-data" and r[1] == str(w.wt["topic"]))
    with tarfile.open(tgz) as t:
        names = set(t.getnames())
    assert {odd, ".claude-work/own-repo/inner\nfile.txt", "wip.txt"} <= names
    assert any(n.startswith(".claude-work/own-repo/.git/") for n in names), "the nested repo's .git is archived"


def test_skip_venvs_leaves_venvs_out(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    venv = w.m / ".claude-work/venv-x"
    _write(venv / "pyvenv.cfg", "home = /usr/bin\n")
    _write(venv / "lib/site.py", "x = 1\n")
    backdate(w.base)
    p = w.run(*small_args(w), "--archive", "--skip-venvs")
    assert p.returncode == 0, p.stdout + p.stderr
    rows = manifest_rows(w.archive)
    tgz = w.archive / next(r[2] for r in rows if r[0] == "wt-data" and r[1] == str(w.m))
    with tarfile.open(tgz) as t:
        names = t.getnames()
    assert ".claude-work/scratch/s.txt" in names
    assert not any(n.startswith(".claude-work/venv-x") for n in names)


def test_apply_restores_tracked_changes_with_git_apply(world: World) -> None:
    assert world.run(*world.common(), "--archive").returncode == 0
    rows = manifest_rows(world.archive)
    diff = world.archive / next(r[2] for r in rows if r[0] == "wt-diff" and r[1] == str(world.wt["dirty"]))
    target = world.base / "dirty-restored"
    world.git("worktree", "add", "-q", "--detach", str(target), "dirty-br")
    world.git("apply", "--binary", str(diff), cwd=target)
    assert (target / "a.txt").read_text() == "dirty edit\n"


# ------------------------------------------------------------------ review round 1: gates that must hold


def _row_file(w: World, kind: str, source: Path) -> Path:
    return w.archive / next(r[2] for r in manifest_rows(w.archive) if r[0] == kind and r[1] == str(source))


def test_unborn_branch_and_partly_staged_changes_are_archived(tmp_path: Path) -> None:
    """Staged content of an unborn branch, and the index version of a partly staged file, survive --force."""
    w, _ = small_world(tmp_path)
    orph = w.base / "orph"
    w.git("worktree", "add", "-q", "--orphan", "-b", "orph", str(orph))
    _write(orph / "precious.txt", "PRECIOUS\n")
    w.git("add", "precious.txt", cwd=orph)
    topic = w.wt["topic"]
    _write(topic / "t.txt", "staged version\n")
    w.git("add", "t.txt", cwd=topic)
    _write(topic / "t.txt", "working version\n")  # MM: index and working tree differ
    backdate(w.base)
    p = w.run(*small_args(w), "--archive")
    assert p.returncode == 0, p.stdout + p.stderr
    orph_staged = _row_file(w, "wt-staged", orph)
    orph_diff = _row_file(w, "wt-diff", orph)
    topic_staged = _row_file(w, "wt-staged", topic)
    topic_diff = _row_file(w, "wt-diff", topic)
    assert "+PRECIOUS" in orph_staged.read_text() and "+PRECIOUS" in orph_diff.read_text()
    assert "+staged version" in topic_staged.read_text() and "+working version" in topic_diff.read_text()
    p = w.run(*small_args(w), "--apply")
    assert p.returncode == 0, p.stdout + p.stderr
    assert f"worktree remove --force {orph}" in p.stdout and not orph.exists()
    # both versions come back with git apply
    back = w.base / "orph-back"
    w.git("worktree", "add", "-q", "--orphan", "-b", "orph-back", str(back))
    w.git("apply", "--binary", str(orph_diff), cwd=back)
    w.git("apply", "--cached", "--binary", str(orph_staged), cwd=back)
    assert (back / "precious.txt").read_text() == "PRECIOUS\n"
    assert w.git("show", ":precious.txt", cwd=back).stdout == "PRECIOUS\n"
    back2 = w.base / "topic-back"
    w.git("worktree", "add", "-q", "--detach", str(back2), _sha_of_topic(w))
    w.git("apply", "--binary", str(topic_diff), cwd=back2)
    w.git("apply", "--cached", "--binary", str(topic_staged), cwd=back2)
    assert (back2 / "t.txt").read_text() == "working version\n"
    assert w.git("show", ":t.txt", cwd=back2).stdout == "staged version\n"


def _sha_of_topic(w: World) -> str:
    """Tip of the topic bundle (the branch itself is gone after --apply)."""
    row = next(r for r in manifest_rows(w.archive) if r[0] == "bundle" and r[1] == "refs/heads/topic")
    return row[5]


def test_gc_refused_while_a_stash_exists(tmp_path: Path) -> None:
    w, sha = small_world(tmp_path)
    _write(w.m / "a.txt", "stashed edit\n")
    w.git("stash", "push", "-q", "-m", "keep me")
    backdate(w.base)
    assert w.run(*small_args(w), "--archive").returncode == 0
    p = w.run(*small_args(w), "--apply", "--gc")
    assert p.returncode == 5, p.stdout + p.stderr
    assert "refs/stash exists" in parse_summary(p.stdout)[("step", "gc")][2]
    assert "gc --prune=now" not in p.stdout
    assert w.git("stash", "list").stdout.count("keep me") == 1
    assert w.git("cat-file", "-e", sha["dropped"], check=False).returncode == 0


def test_gc_refused_when_a_droppable_commit_is_not_archived(tmp_path: Path) -> None:
    w, sha = small_world(tmp_path)
    assert w.run(*small_args(w), "--archive").returncode == 0
    tree = w.git("rev-parse", "main^{tree}").stdout.strip()
    late = w.git("commit-tree", tree, "-p", "main", "-m", "dangling after the archive").stdout.strip()
    p = w.run(*small_args(w), "--apply", "--gc")
    assert p.returncode == 5, p.stdout + p.stderr
    assert "in no archived pack or bundle" in parse_summary(p.stdout)[("step", "gc")][2]
    assert "gc --prune=now" not in p.stdout
    assert w.git("cat-file", "-e", late, check=False).returncode == 0
    assert w.git("cat-file", "-e", sha["dropped"], check=False).returncode == 0


def test_clean_and_gc_refused_while_m_is_live(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    assert w.run(*small_args(w), "--archive").returncode == 0
    _write(w.m / ".claude-work/live.txt", "written now\n")  # fresh mtime: M is live
    p = w.run(*small_args(w), "--apply", "--clean", "--gc")
    assert p.returncode == 5, p.stdout + p.stderr
    rows = parse_summary(p.stdout)
    assert "M modified in the last" in rows[("step", "clean")][2]
    assert "M(" in rows[("step", "gc")][2]
    commands = [line for line in p.stdout.splitlines() if line.startswith("  $ git")]
    assert not any("clean -fdx" in c or "gc --prune=now" in c for c in commands)
    assert (w.m / ".claude-work/scratch/s.txt").is_file()


def test_session_wt_m_blocks_clean_and_gc(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    args = [*small_args(w), "--live-minutes", "0"]
    assert w.run(*args, "--archive").returncode == 0
    p = w.run(*args, "--apply", "--clean", "--gc", "--session-wt", str(w.m))
    assert p.returncode == 5, p.stdout + p.stderr
    rows = parse_summary(p.stdout)
    assert "running session" in rows[("step", "clean")][2] and "running session" in rows[("step", "gc")][2]
    assert "gc --prune=now" not in p.stdout and (w.m / ".claude-work/scratch/s.txt").is_file()


def test_clean_refused_when_m_changed_since_the_archive(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    assert w.run(*small_args(w), "--archive").returncode == 0
    _write(w.m / ".claude-work/scratch/after.txt", "not archived\n")
    backdate(w.m / ".claude-work/scratch/after.txt", w.m / ".claude-work/scratch")
    p = w.run(*small_args(w), "--apply", "--clean")
    assert p.returncode == 5, p.stdout + p.stderr
    assert "new or changed since the archive" in parse_summary(p.stdout)[("step", "clean")][2]
    assert (w.m / ".claude-work/scratch/after.txt").is_file() and (w.m / ".claude-work/scratch/s.txt").is_file()


def test_worktree_turning_live_during_apply_is_skipped_and_blocks_gc(tmp_path: Path) -> None:
    """A rebase starts in a worktree after the classification: fresh_ok skips it, gc re-checks and refuses."""
    w, _ = small_world(tmp_path)
    other = w.base / "other"
    w.git("worktree", "add", "-q", "-b", "other-br", str(other))
    backdate(w.base)
    assert w.run(*small_args(w), "--archive").returncode == 0
    gitdir = w.git("rev-parse", "--absolute-git-dir", cwd=other).stdout.strip()
    real = shutil.which("git")
    assert real
    shim_dir = w.base / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    # the first `git bundle verify` (archive verification, after the classification) starts the "rebase"
    shim.write_text(f'#!/bin/bash\ncase " $* " in *" bundle verify "*) mkdir -p "{gitdir}/rebase-merge" ;; esac\nexec "{real}" "$@"\n')
    shim.chmod(0o755)
    env = dict(w.env, PATH=f"{shim_dir}:{w.env['PATH']}")
    p = w.run(*small_args(w), "--apply", "--gc", env=env)
    assert p.returncode == 5, p.stdout + p.stderr
    assert other.is_dir() and "other-br" in w.branches()
    rows = parse_summary(p.stdout)
    assert "rebase in progress" in rows[("worktree", str(other))][2]
    assert "rebase in progress" in rows[("step", "gc")][2]
    assert "gc --prune=now" not in p.stdout
    assert not w.wt["topic"].exists(), "the unaffected worktree is still removed"


def test_a_worktree_git_cannot_read_is_an_error_not_a_match(tmp_path: Path) -> None:
    """A corrupt index makes status/diff fail: archive reports the item failed (rc 6), apply keeps the worktree."""
    w, _ = small_world(tmp_path)
    gitdir = Path(w.git("rev-parse", "--absolute-git-dir", cwd=w.wt["topic"]).stdout.strip())
    (gitdir / "index").write_bytes(b"not an index")
    backdate(w.base)
    p = w.run(*small_args(w), "--archive")
    assert p.returncode == 6, p.stdout + p.stderr
    assert "FAILED" in p.stdout
    p = w.run(*small_args(w), "--apply")
    assert p.returncode == 5, p.stdout + p.stderr
    assert w.wt["topic"].is_dir()
    assert parse_summary(p.stdout)[("worktree", "M/.claude/worktrees/topic")][0] == "ERROR"


def test_skipped_prune_is_not_reported_as_success(tmp_path: Path) -> None:
    w, _ = small_world(tmp_path)
    gone = w.base / "gone"
    w.git("worktree", "add", "-q", "--detach", str(gone), "main")
    w.git("commit", "-q", "--allow-empty", "-m", "unique on a detached HEAD", cwd=gone)
    shutil.rmtree(gone)  # the directory vanishes: the entry turns prunable
    backdate(w.base)
    assert w.run(*small_args(w), "--archive").returncode == 0
    p = w.run(*small_args(w), "--apply")
    assert p.returncode == 5, p.stdout + p.stderr
    assert "prunable" in w.git("worktree", "list", "--porcelain").stdout
    assert parse_summary(p.stdout)[("step", "prune")][2].startswith("skipped")
