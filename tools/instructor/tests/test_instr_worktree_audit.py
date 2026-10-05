"""worktree-audit: verdicts and counts on a scratch repository, and it changes nothing.

Run: uv run --with pytest pytest -q tools/instructor/tests/"""
from __future__ import annotations

import shutil
from pathlib import Path

from instr_testlib import commit, git, run_script, scratch, status


def snapshot(m: Path) -> tuple:
    refs = git("for-each-ref", "--format=%(refname) %(objectname)", cwd=m)
    common = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir", cwd=m))
    files = sorted((str(p), p.stat().st_mtime_ns) for p in common.rglob("*") if p.is_file())
    return refs, files


def test_verdicts_and_counts(tmp_path):
    m, feat = scratch(tmp_path)                                  # feat: one commit ahead, unmerged
    git("worktree", "add", "-q", "-b", "done", str(tmp_path / "done"), "main", cwd=m)   # merged-clean
    git("worktree", "add", "-q", "-b", "edit", str(tmp_path / "edit"), "main", cwd=m)
    (tmp_path / "edit" / "a.txt").write_text("changed\n")                               # dirty
    git("worktree", "add", "-q", "-b", "reb", str(tmp_path / "reb"), "main", cwd=m)
    gitdir = Path(git("rev-parse", "--path-format=absolute", "--git-dir", cwd=tmp_path / "reb"))
    (gitdir / "rebase-merge").mkdir()                                                   # busy
    git("worktree", "add", "-q", "--detach", str(tmp_path / "det"), "main", cwd=m)      # detached
    git("worktree", "add", "-q", "-b", "gone", str(tmp_path / "gone"), "main", cwd=m)
    shutil.rmtree(tmp_path / "gone")                                                    # prunable
    git("worktree", "add", "-q", "--lock", "-b", "lk", str(tmp_path / "lk"), "main", cwd=m)
    git("branch", "loose-merged", "main", cwd=m)
    git("branch", "loose-ahead", "feat", cwd=m)
    commit(feat, "c.txt")
    before = snapshot(m)
    cp = run_script("worktree_audit.py", "--repo", str(m), cwd=tmp_path)
    st, verb, kv, log = status(cp.stdout)
    assert (cp.returncode, st, verb) == (0, "OK", "worktree-audit")
    want = {"worktrees": "8", "merged_clean": "2", "unmerged": "1", "dirty": "1", "busy": "1",
            "prunable": "1", "detached": "1", "locked": "1", "branches_no_wt": "2", "branches_no_wt_merged": "1"}
    assert {k: kv[k] for k in want} == want
    assert snapshot(m) == before                                 # refs and every file under .git untouched
    table = Path(log).read_text()
    assert "unmerged\tfeat\t2\t0" in table and "busy\treb" in table and "1\tloose-merged" in table


def test_dry_run_and_bad_args(tmp_path):
    m, _ = scratch(tmp_path)
    cp = run_script("worktree_audit.py", "--dry-run", cwd=m)
    st, _, kv, log = status(cp.stdout)
    assert (cp.returncode, st, kv["dry_run"]) == (0, "OK", "1") and "# plan" in Path(log).read_text()
    for bad in (["--repo", "x"], ["--delete"], ["--repo", "/tmp/$(id)"]):
        cp = run_script("worktree_audit.py", *bad, cwd=m)
        assert cp.returncode == 2 and status(cp.stdout)[2]["reason"] == "bad-arg"


def test_a_linked_log_dir_is_refused(tmp_path):
    m, _ = scratch(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (m / ".claude-work").mkdir()
    (m / ".claude-work" / "instr").symlink_to(elsewhere)
    cp = run_script("worktree_audit.py", cwd=m)
    assert (cp.returncode, status(cp.stdout)[2]["reason"]) == (1, "log-dir-is-a-link")
    assert not list(elsewhere.iterdir())


def test_a_linked_claude_work_dir_is_refused_before_any_mkdir(tmp_path):
    m, _ = scratch(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (m / ".claude-work").symlink_to(elsewhere)
    cp = run_script("worktree_audit.py", cwd=m)
    assert (cp.returncode, status(cp.stdout)[2]["reason"]) == (1, "log-dir-is-a-link")
    assert not list(elsewhere.iterdir())                   # no instr/ made through the link
