"""lib/source_snapshot.py: the private source snapshot (DESIGN.md §7.2; install.sh's block ported).

Each test builds its own scratch git repository (copies of this checkout's dot-config/dot-codex_config/lib
and the engine files), so the real repository is only read.
"""
from __future__ import annotations

import os
import shutil
import stat

import pytest

from conftest import LIB, load_lib
from _foundation_helpers import git, make_repo, run_py

ss = load_lib("source_snapshot")
SS_PY = LIB / "source_snapshot.py"
CODEX_STATE = "dot-config/dot-codex_config/lib/codex_state.py"


@pytest.fixture
def repo(tmp_path):
    return make_repo(tmp_path / "repo")


def snap(repo, dest, *extra):
    return run_py(SS_PY, repo, dest, *extra)


def test_clean_snapshot_copies_head_files(repo, tmp_path):
    dest = tmp_path / "src"
    r = snap(repo, dest)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == git(repo, "rev-parse", "HEAD").stdout.strip()
    assert stat.S_IMODE(dest.stat().st_mode) == 0o700
    for rel in ("lib/install_state.py", "lib/claude_md_block.py", "lib/stack.env.example",
                "dot-config/dot-claude/hooks/stack_io.py", "dot-config/dot-codex_config/lib/codex_state.py"):
        assert (dest / rel).read_bytes() == (repo / rel).read_bytes(), rel
        assert not (dest / rel).is_symlink()


def test_edit_after_snapshot_is_never_executed(repo, tmp_path, scratch_home):
    """The proof: lib/install_state.py edited after the snapshot point never runs."""
    dest = tmp_path / "src"
    assert snap(repo, dest).returncode == 0
    sentinel = tmp_path / "tampered"
    with open(repo / "lib" / "install_state.py", "a") as f:
        f.write("\nopen(os.environ['TAMPER_SENTINEL'], 'w').write('ran')\n")
    env = dict(os.environ, TAMPER_SENTINEL=str(sentinel))
    ch = scratch_home["codex_home"]
    r = run_py(dest / CODEX_STATE, "stage", ch, tmp_path / "stage", env=env)
    assert r.returncode == 0, r.stderr
    assert not sentinel.exists()
    # control: the same edit does run from the repository, so the check above can fail
    r = run_py(repo / CODEX_STATE, "stage", ch, tmp_path / "stage2", env=env)
    assert sentinel.read_text() == "ran"


def test_dirty_file_stops_unless_allowed(repo, tmp_path):
    with open(repo / "lib" / "claude_md_block.py", "a") as f:
        f.write("# edited\n")
    r = snap(repo, tmp_path / "a")
    assert r.returncode == 1 and " M lib/claude_md_block.py" in r.stderr
    assert not (tmp_path / "a").exists()
    r = snap(repo, tmp_path / "b", "--allow-dirty")
    assert r.returncode == 0 and " M lib/claude_md_block.py" in r.stderr
    assert (tmp_path / "b" / "lib" / "claude_md_block.py").read_text().endswith("# edited\n")


def test_deleted_file_is_dirty(repo, tmp_path):
    os.unlink(repo / "lib" / "stack.env.example")
    r = snap(repo, tmp_path / "a")
    assert r.returncode == 1 and " D lib/stack.env.example" in r.stderr


def test_untracked_and_staged_files_never_copied(repo, tmp_path):
    (repo / "dot-config" / "dot-codex_config" / "lib" / "extra.py").write_text("x = 1\n")
    (repo / "dot-config" / "dot-codex_config" / "lib" / "staged.py").write_text("y = 1\n")
    git(repo, "add", "dot-config/dot-codex_config/lib/staged.py")
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 0, r.stderr
    assert "?? dot-config/dot-codex_config/lib/extra.py" in r.stderr
    assert "A  dot-config/dot-codex_config/lib/staged.py" in r.stderr
    assert not (tmp_path / "s" / "dot-config" / "dot-codex_config" / "lib" / "extra.py").exists()
    assert not (tmp_path / "s" / "dot-config" / "dot-codex_config" / "lib" / "staged.py").exists()


def test_symlink_under_shipped_tree_refused(repo, tmp_path):
    (repo / "dot-config" / "dot-claude" / "hooks" / "notes.log").symlink_to(tmp_path)
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 1 and "symlink" in r.stderr and not (tmp_path / "s").exists()


@pytest.mark.parametrize("top", ["dot-config", "dot-config/dot-claude", "dot-config/dot-codex_config"])
def test_a_shipped_directory_swapped_for_a_symlink_is_refused(repo, tmp_path, top):
    """Same bytes behind a directory link (dot-config/ itself or one of the shipped trees): named and refused."""
    real = tmp_path / "elsewhere"
    shutil.move(str(repo / top), str(real))
    (repo / top).symlink_to(real, target_is_directory=True)
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 1 and "%s is a symlink" % top in r.stderr, r.stderr
    assert not (tmp_path / "s").exists()


def test_tracked_file_swapped_for_symlink_refused(repo, tmp_path):
    """Same bytes behind a link: the O_NOFOLLOW open on the last component refuses it."""
    p = repo / "lib" / "stack.env.example"
    copy = tmp_path / "copy.example"
    copy.write_bytes(p.read_bytes())
    p.unlink()
    p.symlink_to(copy)
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 1 and "symlink" in r.stderr


def test_assume_unchanged_refused(repo, tmp_path):
    with open(repo / "lib" / "install_state.py", "a") as f:
        f.write("# hidden\n")
    git(repo, "update-index", "--assume-unchanged", "lib/install_state.py")
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 1 and "assume-unchanged" in r.stderr


def test_fsck_config_keys_refused(repo, tmp_path):
    git(repo, "config", "fsck.skipList", str(tmp_path / "skip"))
    r = snap(repo, tmp_path / "s")
    assert r.returncode == 1 and "fsck.skiplist" in r.stderr.lower()


def test_dest_must_be_new_and_outside_repo(repo, tmp_path):
    (tmp_path / "exists").mkdir()
    assert snap(repo, tmp_path / "exists").returncode == 1
    assert snap(repo, repo / "snap").returncode == 1 and not (repo / "snap").exists()


def test_git_env_variables_ignored(repo, tmp_path):
    other = make_repo(tmp_path / "other")
    with open(other / "lib" / "install_state.py", "a") as f:
        f.write("# another history\n")
    git(other, "commit", "-q", "-am", "other")
    env = dict(os.environ, GIT_DIR=str(other / ".git"), GIT_WORK_TREE=str(other))
    r = run_py(SS_PY, repo, tmp_path / "s", env=env)
    assert r.returncode == 0 and r.stdout.strip() == git(repo, "rev-parse", "HEAD").stdout.strip()


def test_changes_since(repo):
    first = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert ss.changes_since(str(repo), first, first) == ""
    with open(repo / "lib" / "install_state.py", "a") as f:
        f.write("# v2\n")
    git(repo, "commit", "-q", "-am", "v2")
    second = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert "lib/install_state.py" in ss.changes_since(str(repo), first, second)
    assert ss.changes_since(str(repo), "0" * 40, second) is None
    assert ss.changes_since(str(repo), first, "0" * 40) is None
    assert ss.changes_since(str(repo), "HEAD; rm -rf /", second) is None
    assert ss.changes_since(str(repo), first, "HEAD") is None


def test_changes_since_a_pre_move_commit_covers_the_old_paths(repo):
    """An install made before the move under dot-config/ recorded a commit whose files live at codex_config/
    and dot-claude/: the review covers both layouts and shows the move as renames, not as every file added."""
    moved = git(repo, "rev-parse", "HEAD").stdout.strip()
    git(repo, "mv", "dot-config/dot-codex_config", "codex_config")
    git(repo, "mv", "dot-config/dot-claude", "dot-claude")
    git(repo, "commit", "-q", "-m", "the layout before the move")
    old = git(repo, "rev-parse", "HEAD").stdout.strip()
    (repo / "dot-config").mkdir(exist_ok=True)
    git(repo, "mv", "codex_config", "dot-config/dot-codex_config")
    git(repo, "mv", "dot-claude", "dot-config/dot-claude")
    with open(repo / "dot-config" / "dot-codex_config" / "lib" / "codex_state.py", "a") as f:
        f.write("# moved and edited\n")
    git(repo, "commit", "-q", "-am", "the move, one edit")
    new = git(repo, "rev-parse", "HEAD").stdout.strip()
    assert ss.review_paths(str(repo), old) == ss.SNAPSHOT_PATHS + ss.LEGACY_PATHS
    assert ss.review_paths(str(repo), moved) == ss.SNAPSHOT_PATHS
    assert ss.review_paths(str(repo), "not a sha") == ss.SNAPSHOT_PATHS
    stat = ss.changes_since(str(repo), old, new)
    assert "=>" in stat and stat.rstrip().endswith("1 insertion(+)"), stat
    assert "=>" not in ss.changes_since(str(repo), moved, new)


def test_changes_since_ignores_commits_after_the_snapshot(repo):
    """The review lists what the snapshot installs: a commit made after it (HEAD moved) is not in it."""
    first = git(repo, "rev-parse", "HEAD").stdout.strip()
    with open(repo / "lib" / "claude_md_block.py", "a") as f:
        f.write("# later\n")
    git(repo, "commit", "-q", "-am", "later")
    assert ss.changes_since(str(repo), first, first) == ""


def test_usage():
    assert run_py(SS_PY, "only-one").returncode == 2
