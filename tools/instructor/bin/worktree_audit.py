# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""worktree-audit: report every worktree and local branch of a repository against main. Report only.

Per worktree: branch, ahead/behind main, tracked changes, an operation in progress (merge, rebase,
cherry-pick, revert, bisect), locked, prunable, and a verdict: main, prunable, busy, dirty,
merged-clean (fully in main and clean: removal is a user step), unmerged, detached. Per branch
without a worktree: merged into main or not. Every git call is read-only (--no-optional-locks);
the table goes to the log, the counts to the status line."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from instr_common import GIT, Parser, Run, abort, abs_path, git_out, toplevel

MAIN = "refs/heads/main"
OPS = ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG")


def q(args: list[str], cwd: Path) -> tuple[int, str]:
    return git_out(["--no-optional-locks", *args], cwd)


def worktrees(repo: Path) -> list[dict]:
    """`git worktree list --porcelain -z` as dicts (path, head, branch, detached, locked, prunable, bare)."""
    out, cur = [], None
    for field in q(["worktree", "list", "--porcelain", "-z"], repo)[1].split("\0"):
        if not field:
            cur = None
            continue
        key, _, val = field.partition(" ")
        if key == "worktree":
            cur = {"path": val}
            out.append(cur)
        elif cur is not None:
            cur[key] = val or True
    return out


def inspect(w: dict, main_sha: str, repo: Path) -> dict:
    head, branch = w.get("HEAD", ""), str(w.get("branch", "")).removeprefix("refs/heads/")
    row = {"path": w["path"], "branch": branch or "(detached)", "head": head[:12], "ahead": "-",
           "behind": "-", "dirty": "-", "op": "-", "locked": "locked" in w, "prunable": "prunable" in w}
    if "bare" in w:
        return {**row, "verdict": "bare"}
    if row["prunable"] or not Path(w["path"]).is_dir():
        return {**row, "verdict": "prunable"}
    wt = Path(w["path"])
    rc, lr = q(["rev-list", "--left-right", "--count", f"{main_sha}...{head}", "--"], repo)
    if rc == 0 and len(lr.split()) == 2:
        row["behind"], row["ahead"] = lr.split()
    paths = q(["rev-parse", "--path-format=absolute", *[x for o in OPS for x in ("--git-path", o)]], wt)[1]
    found = paths.splitlines()
    ops = [o for o, p in zip(OPS, found, strict=True) if Path(p).exists()] if len(found) == len(OPS) else ["?"]
    row["op"] = ",".join(ops) or "-"
    rc, st = q(["status", "--porcelain", "--untracked-files=no"], wt)
    row["dirty"] = "?" if rc != 0 else len(st.splitlines())
    merged = q(["merge-base", "--is-ancestor", "--end-of-options", head, main_sha], repo)[0] == 0
    if branch == "main":
        verdict = "main"
    elif ops:
        verdict = "busy"
    elif row["dirty"] != 0:
        verdict = "dirty"
    elif not branch:
        verdict = "detached"
    else:
        verdict = "merged-clean" if merged else "unmerged"
    return {**row, "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    ap = Parser("worktree-audit", description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=abs_path, help="any checkout of the repository (default: the current one)")
    ap.add_argument("--dry-run", action="store_true", help="log the queries it would run, run nothing")
    a = ap.parse_args(argv)
    repo = toplevel(a.repo) or abort("worktree-audit", "not-a-checkout")
    run =Run("worktree-audit", repo)
    if a.dry_run:
        run.plan([("list", [*GIT, "--no-optional-locks", "worktree", "list", "--porcelain", "-z"], repo),
                  ("per-worktree", [*GIT, "--no-optional-locks", "status", "--porcelain",
                                    "--untracked-files=no"], Path("<each worktree>")),
                  ("branches", [*GIT, "for-each-ref", "--format=%(refname)", "refs/heads/"], repo)])
        return run.finish("OK", dry_run=1, steps=3)
    rc, main_sha = q(["rev-parse", "--verify", "-q", "--end-of-options", MAIN + "^{commit}"], repo)
    if rc != 0:
        return run.finish("FAIL", reason="no-main")
    rows = [inspect(w, main_sha, repo) for w in worktrees(repo)]
    cols = ("verdict", "branch", "ahead", "behind", "dirty", "op", "locked", "prunable", "head", "path")
    run.note("\n# worktrees\n" + "\t".join(cols))
    for r in rows:
        run.note("\t".join(str(r[c]) for c in cols))
    used = {"refs/heads/" + r["branch"] for r in rows}
    refs = q(["for-each-ref", "--format=%(refname)", "refs/heads/"], repo)[1].splitlines()
    free = [r for r in refs if r not in used]
    free_merged = [r for r in free if q(["merge-base", "--is-ancestor", "--end-of-options", r, MAIN], repo)[0] == 0]
    run.note("\n# branches without a worktree\nmerged\tbranch")
    for r in free:
        run.note(f"{int(r in free_merged)}\t{r.removeprefix('refs/heads/')}")
    n = Counter(r["verdict"] for r in rows)
    return run.finish("OK", worktrees=len(rows), merged_clean=n["merged-clean"], unmerged=n["unmerged"],
                      dirty=n["dirty"], busy=n["busy"], prunable=n["prunable"], detached=n["detached"],
                      locked=sum(r["locked"] for r in rows), branches_no_wt=len(free),
                      branches_no_wt_merged=len(free_merged))


if __name__ == "__main__":
    sys.exit(main())
