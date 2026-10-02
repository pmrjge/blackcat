---
name: git-worktrees
description: Use for parallel work in git worktrees — one branch per task, shared repo state, fast-forward merging back and cleanup.
---
# Worktrees for parallel agents

Part of `git-workflows` (safety rules, integration strategy, commit hygiene). Conflicts while merging back: `git-history-edit`.

One task = one worktree = one branch, created from an explicit base. Git refuses to check out a branch
that another worktree has (tested), which is the point.
```bash
git worktree add -b agent/<task> ../<repo>-<task> main   # from local main: origin/main is stale (no pushes)
git worktree list --porcelain                       # machine-readable
git worktree lock --reason "agent running" ../<repo>-<task>
git worktree remove ../<repo>-<task>                # refuses if dirty; --force discards changes
git worktree prune -v                               # after a directory was deleted by hand
git branch -d agent/<task>                          # after merge (-D only when abandoning)
```
- Shared between worktrees: objects, all `refs/` (branches, tags, **stash** — tested), config. Per worktree:
  `HEAD`, index, `refs/bisect`, `refs/worktree`, `refs/rewritten`. Per-worktree config needs
  `git config extensions.worktreeConfig true` then `git config --worktree ...`.
- Each worktree needs its own environment (`uv sync`, `npm ci`); gitignored files such as `.env` are absent.
- Claude Code (`isolation: worktree`, `--worktree <name>`): worktrees live under `.claude/worktrees/` (branch
  `worktree-<name>` for named ones), based on the remote default branch, not the parent's HEAD (unpushed commits
  are invisible) unless the `worktree.baseRef` setting is `"head"` (the stack sets it). Clean worktrees are removed when the agent ends; changed ones stay
  (locked while running) until the periodic sweep. `.worktreeinclude` (gitignore syntax) copies ignored files
  like `.env` into new worktrees. Keep `.claude/worktrees/` out of `git status` (`.git/info/exclude`).
- Integrate one branch at a time into local `main`, fast-forward first (`git -C <main checkout> merge --ff-only
  <branch>`), running tests after each; remove worktree and branch after. A fast-forward that fails (diverged,
  conflicts, a dirty main checkout) goes to main-coder: rebase the branch onto `main` (or merge `main` into it),
  resolve (see Conflicts in `git-history-edit`), test, then fast-forward.
- Avoid multiple checkouts of a superproject with submodules (support is incomplete). `git worktree add --orphan`
  exists for an unborn branch; `--relative-paths` (2.48+) keeps links valid if the tree moves.

## Verify
- `git worktree list` has no stale or prunable entries you created; merged agent branches deleted.
