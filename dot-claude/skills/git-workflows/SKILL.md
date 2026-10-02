---
name: git-workflows
description: Load before git work beyond a plain commit — worktrees per task, rebase/merge/squash, history edits, conflicts, bisect, reflog recovery, filter-repo, LFS, signing, gh/tea.
---
# Git workflows (solo and multi-agent)

Checked against Git 2.54 docs, git-filter-repo 2.47, gitleaks 8.30, pre-commit 4.6, gh 2.100, tea 0.16 (Sep 2026).
Latest releases: Git 2.56.0, gh 2.102.0, gitleaks 8.30.1 (Verified 2026-10-02 `git ls-remote --tags` of github.com/git/git, cli/cli, gitleaks/gitleaks); git-filter-repo 2.47.0, pre-commit 4.6.2 (Verified 2026-10-02 https://pypi.org/pypi/<pkg>/json); tea 0.16: unverified (gitea.com unreachable).
Commands marked (tested) were run on Git 2.43; newer-only features name their minimum version.

## Scope
- Covers: local git practice, parallel work in worktrees, integration, repair, history cleanup, repo hygiene, forge CLIs.
- Not here: running a forge (the `self-hosting-ops` skill has Forgejo), model downloads (the `hf-hub` skill).

## Modules and references (load the one the task touches)
| Module | Load for |
|---|---|
| `git-worktrees` | one worktree per task, shared vs per-worktree state, Claude Code worktrees, merging back |
| `git-history-edit` | amend/fixup/autosquash without an editor, `--onto`, conflicts, filter-repo secret removal |
| `git-recovery-bisect` | reflog, ORIG_HEAD, lost commits and stashes, `git bisect run` |
| `git-large-repos` | LFS and model weights, blobless/sparse clones, submodules vs subtrees, `.gitattributes` |

- Read `references/signing-hooks.md` when setting up SSH signing, pre-commit or gitleaks; `references/forge-clis.md` when using `gh`, `tea` or `fj`.

## Safety rules (always)
1. Never push (the stack's global Git rule, hook-enforced, also inside `bash -c`/`eval`/`$(...)`): no `git push` in
   any form, no `send-pack`, `lfs push` or `subtree push`, no `gh`/`tea`/`fj` command that writes to a forge.
   Work lands in local `main`; the user publishes.
2. Never rewrite published history (amend/rebase/filter-repo of pushed commits) unless the user asked for it.
3. Never commit secrets. If one lands: rotate it first, then clean (`git-history-edit`).
4. Before anything destructive, leave a rescue ref: `git branch rescue/$(date +%s)` (or note `git rev-parse HEAD`).
5. No TTY for agents: never `git add -p`, `git mergetool`, bare `git rebase -i`, or commands that open an editor.
   Use `--no-edit`, `-m`, `GIT_EDITOR=true`, and `GIT_SEQUENCE_EDITOR` (`git-history-edit`).
6. Don't change the user's global git config silently; propose settings or set them per repo.

## Orient first (read-only)
```bash
git status -sb && git stash list && git worktree list
git log --oneline --graph --decorate -20 --all
git rev-parse --abbrev-ref @{u}; git log --oneline @{u}..   # upstream; unpushed commits
git log --oneline ..@{u}                                    # commits you are behind
```

## Integration strategy
| Situation | Do |
|---|---|
| Private topic branch behind `main` | `git rebase main` |
| Branch others build on | `git merge main` into it; never rebase it |
| Topic with WIP/fixup noise | autosquash before merging, or squash-merge (`git merge --squash <branch>` on `main`, then commit) |
| Topic with meaningful atomic commits | rebase-merge, or `git merge --no-ff` to keep the topic boundary |
| Fix needed on a release branch | `git cherry-pick -x <sha>` (records the source) |
| Stack of dependent branches | `git rebase --update-refs main` (moves every branch in the stack) |
- Preview conflicts without touching the tree: `git merge-tree --write-tree --name-only main HEAD`
  (exit 1 = conflicts, prints the files; tested).
- Useful repo config: `rerere.enabled true`, `rerere.autoUpdate true`, `merge.conflictStyle zdiff3`,
  `rebase.autoStash true`, `diff.algorithm histogram`, `push.autoSetupRemote true`, `fetch.prune true`.

## Commit hygiene
- Atomic: one logical change per commit, each commit builds and passes tests (keeps bisect usable).
- Stage exactly: `git add <paths>`; partial file without `-p`: `git diff -- f > p.patch`, edit the patch,
  `git apply --cached p.patch`. Check before committing: `git diff --cached --stat` and `git diff --cached --check`.
- Message: imperative subject (~50, hard max 72 chars), blank line, body says why and what it affects.
- Conventional Commits only if the repo uses them (look at `git log --oneline -30`, commitlint/release-please
  config): `type(scope)!: subject`, types feat, fix, docs, refactor, perf, test, build, ci, chore, revert;
  `BREAKING CHANGE:` footer. Trailers: `git commit --trailer "Co-authored-by: Name <mail>"` (tested).

## Verify
- `git status` clean; before merging, `git log --oneline --graph main..<branch>` shows exactly the intended commits.
- Plus the Verify block of every module used (rewrites, recovery, worktrees, large files).

## Report
- Branches and commits (sha, subject), the commit local `main` now points at, merge method; nothing pushed.
- Conflicts: files, how each was resolved, the test command and result afterwards.
- Destructive steps (rewrite, branch deletion): the exact command and the user instruction behind it;
  rescue refs left in place.
- Anything left undone: stale worktrees, secrets that still need rotation, forge-side cleanup pending.
