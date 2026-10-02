---
name: git-recovery-bisect
description: Use to recover lost git work (reflog, fsck) or find a regression with git bisect.
---
# Recovery and bisect

Part of `git-workflows` (safety rules: rescue ref before anything destructive).

## Recovery
- Reflog keeps every position of HEAD/branches (90 days reachable, 30 unreachable by default):
  `git reflog`, `git reflog show <branch>`; restore with `git branch rescue <sha>` (safe) or `git reset --hard <sha>`
  (discards uncommitted work: check `git status` first).
- Undo the last rebase/merge/reset: `ORIG_HEAD` holds the previous tip: `git branch rescue ORIG_HEAD`.
- Deleted branch: sha from `Deleted branch x (was <sha>)` or the reflog, then `git branch x <sha>`.
- Lost stash or never-referenced commits: `git fsck --lost-found` (writes `.git/lost-found/`) or
  `git fsck --unreachable --no-reflogs | grep commit`, inspect with `git show <sha>`.
- Work never staged and wiped by `reset --hard` or `checkout --` is gone; staged content survives as dangling blobs.
- Remote branch overwritten: `git reflog show origin/<branch>` has the old remote-tracking values.

## Bisect
```bash
git bisect start <bad> <good>            # add --first-parent for merge-heavy histories
git bisect run ./bisect-check.sh         # keep the script outside the repo or untracked
git bisect log > bisect.log; git bisect reset
```
Exit codes of the script: 0 good; 1-127 except 125 bad; 125 skip (cannot test, e.g. build broke); >= 128 aborts.
```bash
#!/usr/bin/env bash
make -s build >/dev/null 2>&1 || exit 125
./repro.sh && exit 0 || exit 1
```
Performance regressions: `git bisect start --term-old=fast --term-new=slow`. Bisect in a detached worktree
(`git worktree add --detach ../bisect <bad>`) so work in progress is untouched.

## Verify
- After recovery: `git fsck --no-dangling` passes and the rescued branch has the expected tip.
- After bisect: `git bisect log` saved, `git bisect reset` done, the first bad commit reproduces the failure and its parent does not.
