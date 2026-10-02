---
name: git-history-edit
description: Use to rewrite or repair unpushed git history — fixup/autosquash, rebase --onto, conflict resolution, removing secrets with filter-repo.
---
# Editing history, conflicts and secret removal

Part of `git-workflows` (safety rules: never rewrite published history unless asked; rescue ref first; no editor).

## Non-interactive history editing (unpushed or private branches)
- Last commit: `git commit --amend --no-edit` (content) or `--amend -m "..."` (message).
- Fix an older commit: `git commit --fixup=<sha>`, then `git rebase --autosquash <base>`. Git >= 2.44 applies
  autosquash without `-i`; older Git: `GIT_SEQUENCE_EDITOR=: git rebase -i --autosquash <base>` (tested).
- Reword an older commit without an editor (`--fixup=amend:`/`reword:` open one and reject `-m`/`-F`):
  `git commit --allow-empty -m "amend! <exact subject of target>" -m "<complete new message>"`, then autosquash.
  The new message replaces the old one (tested).
- Drop or edit a commit: rewrite the todo with sed (tested). The todo uses the same abbreviation as
  `S=$(git rev-parse --short <sha>)` (not always 7 chars): `GIT_SEQUENCE_EDITOR="sed -i.bak 's/^pick $S /drop $S /'" git rebase -i <base>` (`-i.bak` works with BSD and GNU sed; macOS `sed -i 's/…/'` fails — tested on macOS 27);
  use `edit` to stop there, then `git reset HEAD~`, commit the pieces, `git rebase --continue` (splits a commit).
- Transplant: `git rebase --onto <newbase> <oldbase> <branch>`. Branch cut from `feature-a` moved onto main:
  `git rebase --onto origin/main feature-a my-branch`. Remove F and G from E-F-G-H-I-J (J = `topic`): `git rebase --onto topic~5 topic~3 topic`.
- Clean up without moving the base: `git rebase --keep-base origin/main`. Test every commit: `git rebase -x "make test" <base>`.
- Compare before/after: `git range-diff <base> ORIG_HEAD HEAD` (patch-level diff of the two series).
- Git 2.54's `git history reword|split` is experimental and interactive: not for agents.

## Conflicts
1. `git status`, `git diff --name-only --diff-filter=U`. Versions: `git show :1:path` base, `:2:` ours, `:3:` theirs;
   `git log --merge -p -- path` shows the commits on both sides that touched it.
2. Resolve to the intended combined behaviour, not a side. Whole-file sides: `git checkout --ours|--theirs -- path`.
   During a rebase the sides flip: "ours" is the upstream being rebased onto, "theirs" is your commit.
3. Generated files: regenerate, don't hand-merge (`uv lock`, `npm install --package-lock-only`, `cargo update -w`).
   Notebooks: nbdime (`nbdime config-git --enable`) gives cell-aware diff/merge.
4. Verify: `git diff --check` (reports "leftover conflict marker"; tested), build and tests pass, then `git add`
   and `git rebase --continue` / `git commit --no-edit`. Bail out: `git merge|rebase|cherry-pick --abort`.
5. rerere replays recorded resolutions (`.git/rr-cache`); `git rerere diff` shows them, `git rerere forget <path>`
   drops a wrong one. Review auto-resolved files anyway.

## Secrets and history rewriting (only with the user's consent through ASK USER)
1. Revoke/rotate the credential now; a rotated key may make the rewrite optional for a private repo.
2. Work in a fresh clone: `git clone --no-local <url> repo-clean` (filter-repo refuses a non-fresh clone).
3. Rewrite (git-filter-repo >= 2.47; `uv tool install git-filter-repo`; all three tested):
   `git filter-repo --sensitive-data-removal --invert-paths --path path/to/file`, or
   `git filter-repo --sensitive-data-removal --replace-text repl.txt` (lines `literal==>***REMOVED***`, or
   `regex:<pattern>==>...`). Large blobs: `git filter-repo --analyze` (reports in `.git/filter-repo/analysis/`),
   then `--strip-blobs-bigger-than 10M`. `--sensitive-data-removal` fetches every ref from origin first.
4. Verify the value is gone from all refs: `git log --all -p -S '<old value>' --oneline` prints nothing.
5. Publishing the rewrite (`git push --force --mirror origin`) is the user's step: give them the command; then
   forge-side cleanup (GitHub support for PR refs and caches, per the "First Changed Commit(s)" filter-repo
   prints) and have collaborators reclone.
6. Prevent recurrence: `.gitignore`, gitleaks hook (`git-workflows` `references/signing-hooks.md`), secrets in env files outside the repo.

## Verify
- After any rewrite: `git range-diff`, tests at the tip (or `git rebase -x` per commit), `gitleaks git --log-opts=...`.
