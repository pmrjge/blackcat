# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""ff-merge: fast-forward local main to a branch, then run the C10 suite on main's checkout.

Race-safe: one merge at a time per repository (flock(2) on <git-common-dir>/instr-ff-merge.lock, the
lock /usr/bin/lockf takes; no flag skips it) and a compare-and-swap ref move (`git update-ref
refs/heads/main <new> <old>`). main's checkout is moved with `git read-tree -m -u <old> <new>` after a
dry run of the same; if that fails the ref is moved back (CAS again). Refuses a non-fast-forward, a
dirty, busy or missing main checkout and an overwritten untracked file; already merged is NOOP.
Never stashes, resets or discards anything."""
from __future__ import annotations

import argparse
import fcntl
import os
import sys
import time
from pathlib import Path

import check_suite
from instr_common import GIT, Parser, Run, abort, abs_path, bounded_int, branch_name, git_out, toplevel

MAIN = "refs/heads/main"
BUSY = ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")


def rev(ref: str, cwd: Path) -> str | None:
    rc, out = git_out(["rev-parse", "--verify", "-q", "--end-of-options", ref + "^{commit}"], cwd)
    return out if rc == 0 else None


def is_ancestor(a: str, b: str, cwd: Path) -> bool:
    return git_out(["merge-base", "--is-ancestor", "--end-of-options", a, b], cwd)[0] == 0


def main_checkout(cwd: Path) -> Path | None:
    _, out = git_out(["worktree", "list", "--porcelain", "-z"], cwd)
    path = None
    for field in out.split("\0"):
        if field.startswith("worktree "):
            path = Path(field[len("worktree "):])
        elif field == "branch " + MAIN:
            return path
    return None


def acquire(lock: Path, wait: int) -> int | None:
    """The flock(2) lock on `lock` (never through a symlink), polled for `wait` seconds: its fd, or
    None when another holder keeps it. Released when the fd closes or this process ends."""
    fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o644)
    deadline = time.monotonic() + wait
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            if time.monotonic() >= deadline:
                os.close(fd)
                return None
            time.sleep(0.2)


def merge(a: argparse.Namespace, run: Run, repo: Path) -> int:
    """The procedure itself; runs under the lock unless it is a dry run."""
    kv: dict = {"branch": a.branch}
    old, new = rev(MAIN, repo), rev("refs/heads/" + a.branch, repo)
    if old is None or new is None:
        return run.finish("FAIL", reason="no-main" if old is None else "no-branch", **kv)
    kv.update(old=old[:12], new=new[:12])
    if a.branch == "main" or new == old or is_ancestor(new, old, repo):
        return run.finish("NOOP", reason="already-merged", **kv)
    if not is_ancestor(old, new, repo):
        return run.finish("FAIL", reason="not-fast-forward", **kv)
    wt = main_checkout(repo)
    if wt is not None and not wt.is_dir():
        return run.finish("FAIL", reason="main-checkout-missing", main=wt, **kv)
    if wt is None and a.suite != "none":
        return run.finish("FAIL", reason="main-not-checked-out", **kv)
    if wt is not None:
        q = ["rev-parse", "--path-format=absolute"] + [x for b in BUSY for x in ("--git-path", b)]
        rc, paths = git_out(q, wt)
        if rc != 0 or any(Path(p).exists() for p in paths.splitlines()):
            return run.finish("FAIL", reason="main-busy", main=wt, **kv)
        rc, dirty = git_out(["--no-optional-locks", "status", "--porcelain", "--untracked-files=no"], wt)
        if rc != 0 or dirty:
            return run.finish("FAIL", reason="main-dirty", main=wt, **kv)
        check = [*GIT, "read-tree", "-n", "-m", "-u", "--end-of-options", old, new]
        if run.step("read-tree-check", check, wt)[0] != 0:
            return run.finish("FAIL", reason="main-would-overwrite", main=wt, **kv)
    msg = f"instr ff-merge: {a.branch}"
    move = [*GIT, "update-ref", "-m", msg, "--end-of-options", MAIN, new, old]
    sync = [*GIT, "read-tree", "-m", "-u", "--end-of-options", old, new]
    run.plan([("update-ref", move, repo)] + ([("read-tree", sync, wt)] if wt else []))
    if a.dry_run:
        if a.suite != "none":
            check_suite.run_suite(run, wt, check_suite.STEPS, False, a.timeout, True)
        return run.finish("OK", dry_run=1, main=wt or "-", suite=a.suite, **kv)
    if run.step("update-ref", move, repo)[0] != 0:
        return run.finish("FAIL", reason="main-moved", **kv)
    if wt is not None and run.step("read-tree", sync, wt)[0] != 0:
        back = [*GIT, "update-ref", "-m", msg + " (rolled back)", "--end-of-options", MAIN, old, new]
        rc = run.step("rollback", back, repo)[0]
        return run.finish("FAIL", reason="checkout-update", rollback="ok" if rc == 0 else "FAILED", **kv)
    kv.update(merged=1, main=wt or "-")
    if a.suite == "none":
        return run.finish("OK", suite="skipped", **kv)
    ok, skv = check_suite.run_suite(run, wt, check_suite.STEPS, False, a.timeout, False)
    kv.update(suite="passed" if ok else "failed", **{k: v for k, v in skv.items() if k != "steps"})
    return run.finish("OK" if ok else "FAIL", **kv)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    ap = Parser("ff-merge", description=__doc__.split("\n")[0])
    ap.add_argument("--branch", type=branch_name, required=True, help="local branch to fast-forward main to")
    ap.add_argument("--repo", type=abs_path, help="any checkout of the repository (default: the current one)")
    ap.add_argument("--suite", choices=("c10", "none"), default="c10", help="suite to run on main afterwards")
    ap.add_argument("--wait", type=bounded_int(0, 600), default=5, help="seconds to wait for the lock")
    ap.add_argument("--timeout", type=bounded_int(1, 7200), default=3600, help="seconds per suite step")
    ap.add_argument("--dry-run", action="store_true", help="check and log the plan, change nothing")
    a = ap.parse_args(argv)
    repo = toplevel(a.repo) or abort("ff-merge", "not-a-checkout")
    if a.dry_run:
        return merge(a, Run("ff-merge", repo), repo)
    lock = Path(git_out(["rev-parse", "--path-format=absolute", "--git-common-dir"], repo)[1]) / "instr-ff-merge.lock"
    try:
        fd = acquire(lock, a.wait)
    except OSError:  # a symlink or something else that is not a plain lock file
        abort("ff-merge", "lock-unavailable")
    if fd is None:
        abort("ff-merge", "locked")
    try:
        return merge(a, Run("ff-merge", repo), repo)
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
