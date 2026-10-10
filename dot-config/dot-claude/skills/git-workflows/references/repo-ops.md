# Repository operations: layout, pre-flight, landing order, verification

Part of `git-workflows` (safety rules, integration strategy, commit hygiene). Worktree mechanics:
`references/worktrees.md`; reflog and lost commits: `references/recovery.md`; conflicts: `references/history-edit.md`.
Every command below is read-only unless it says otherwise; record each sha you rely on (`git rev-parse --short <ref>`).

## Worktree layout
- One writable place per repository: `<repo>/.claude-work/worktrees/<purpose>` (`.claude-work/` listed in
  `$(git rev-parse --git-path info/exclude)`), the branch named by purpose (`feat/<what>`, `fix/<what>`).
  No second ad-hoc location: `git worktree list` shows what exists; reuse it.
- Probe before creating: `mkdir -p <root> && touch <root>/.probe && rm <root>/.probe`. A sandbox can deny
  paths inside a checkout too; when `git worktree add` fails on one (`cannot create directory`):
  ```bash
  git worktree add --no-checkout <wt> <branch>
  git -C <wt> restore --source=HEAD --staged -- .
  git -C <wt> restore --source=HEAD --worktree -- . ':(exclude)<denied/dir>'
  ```
  The denied files then show as ` D <path>` in `git status`: not deletions, never staged (Selective
  staging below). Sparse checkout, `--skip-worktree` and `--assume-unchanged` hide edits: not an option.
- A worktree this session cannot write: detach it, then recreate the branch where you can write. Only when
  it is clean (`git -C <old> status --porcelain` empty) and not locked (`git worktree list --porcelain`):
  `git -C <old> switch --detach` (its HEAD lives in the shared `.git`), then
  `git worktree add <repo>/.claude-work/worktrees/<purpose> <branch>`. Dirty or locked: someone's work; ask.

## Pre-flight (before any merge, fast-forward or user check run)
Run every step, write the results to the plan file, stop at the first that fails.
1. Tips: `git rev-parse --short main <branch>`; `git log --oneline main..<branch>` lists exactly the
   intended commits, `git log --oneline <branch>..main` what the branch lacks.
2. Ancestry: `git merge-base --is-ancestor main <branch>` (exit 0: fast-forward possible; 1: diverged).
3. Conflict preview: `git merge-tree --write-tree --name-only main <branch>` (exit 1 = conflicts, files listed).
4. Main checkout: `git -C <main> status --porcelain=v1`. Uncommitted files there are someone else's (pins,
   local edits). `--ff-only` refuses only when the incoming change touches them: overlap =
   `git diff --name-only --no-renames main <branch>` ∩ the dirty paths (`--no-renames`: a rename's source path counts too). Overlap → blocked, ask; never stash.
5. Branch worktree: ` D` entries from a denied path, untracked files, an operation in progress
   (`git -C <wt> status` names a merge, rebase or cherry-pick).
6. Movement: `git reflog show --date=iso -5 main`; `main` moved since the plan → redo steps 1–3.
7. `git worktree list`: a branch checked out in another worktree cannot be switched to here.

## Landing order for stacked branches
1. List candidates and tips; build the ancestry matrix with `git merge-base --is-ancestor A B` for each
   pair. A branch whose tip is an ancestor of another lands when that other one lands.
2. Order: bottom of each stack first, then upward; independent stacks smallest diff first.
3. Simulate the whole sequence before touching `main`: `git merge-tree --write-tree <cur> <next>`, `<cur>`
   being the result of the previous step; every step clean, else it is a conflict job (below).
4. A private stack behind `main`: one `git -C <top-wt> rebase --update-refs main` moves every branch of
   the stack in one pass, instead of a "merge main again" round trip per branch. A lower branch checked
   out in its own worktree is skipped silently: detach that worktree first (Worktree layout) or rebase
   each branch in its own worktree, bottom first. A branch others build on: merge `main` into it
   instead. Both write commits: rescue refs first.
5. Execute one step at a time: `git rev-parse main` still equals the plan's sha, `git -C <main> merge
   --ff-only <branch>`, the tests the brief names, then the next step.

## Rescue refs
Before any rebase, history edit, branch deletion or `--update-refs`, one per moved branch:
`git branch rescue/<purpose>-$(date +%Y%m%d-%H%M) <sha>`. Report them; never delete them.

## Conflicts
- None is resolved by hand here. A step that previews conflicts is aborted (`git merge --abort`,
  `git rebase --abort`) and handed to the code owner with branch, base sha, the `merge-tree` output, the
  files, and what each side intended (`git log --oneline main..<branch> -- <file>` and the reverse).
- `rerere` (`rerere.enabled true`, repo config) replays a recorded resolution; review its result.

## Selective staging
- `git add -- <path> …` with exact paths; never `commit -a`, `add -A` or `add .`.
- Before committing: `git diff --cached --name-status` equals the intended list, `git diff --cached --check`
  is clean, no ` D` entry from a denied path is staged.

## Verifying a claim ("merged", "landed", "done")
A claim counts only with its evidence:
- Merged: `git merge-base --is-ancestor <branch tip sha> main` exits 0 (the sha, not the name: a branch
  moves). Squash- or cherry-pick-landed: `git merge-tree --write-tree main <branch>` prints
  `git rev-parse main^{tree}` (merging adds nothing), or `git cherry main <branch>` shows only `-` lines.
- Committed: `git log -1 --format='%h %s' <branch>`; clean: `git status --porcelain` empty.
- An ambiguous "done" from anyone is not evidence: run the check, report the sha and the exit code.

## Hand-back: the user's commands
End with the commands only the user runs (outside the sandbox, or needing consent): numbered, in order,
one per line, absolute paths, no `cd` (`git -C /abs/repo …`), each with what it should print:
```
1. bash /abs/path/check.sh feat/x                  # expect: PASS
2. git -C /abs/repo merge --ff-only feat/x          # expect: Fast-forward, main at <sha>
3. /abs/repo/install.sh                             # expect: install complete
```
