# Recovery (reflog, ORIG_HEAD, fsck)

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

Bisect (`git bisect run`, exit codes, detached worktree): the `debug-bisect-minimize` skill.

## Verify
- After recovery: `git fsck --no-dangling` passes and the rescued branch has the expected tip.
