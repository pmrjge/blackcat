---
name: git-workflows
description: Load before git work beyond a plain commit — worktrees per task, rebase/merge/squash, history edits, conflicts, bisect, reflog recovery, filter-repo, LFS, signing, gh/tea.
---
# Git workflows (solo and multi-agent)

Checked against Git 2.54 docs, git-filter-repo 2.47, gitleaks 8.30, pre-commit 4.6, gh 2.100, tea 0.16 (Sep 2026).
Commands marked (tested) were run on Git 2.43; newer-only features name their minimum version.

## Scope
- Covers: local git practice, parallel work in worktrees, integration, repair, history cleanup, repo hygiene, forge CLIs.
- Not here: running a forge (the `self-hosting-ops` skill has Forgejo), model downloads (the `hf-hub` skill).

## Safety rules (always)
1. Never push (the stack's global Git rule, hook-enforced, also inside `bash -c`/`eval`/`$(...)`): no `git push` in
   any form, no `send-pack`, `lfs push` or `subtree push`, no `gh`/`tea`/`fj` command that writes to a forge.
   Work lands in local `main`; the user publishes.
2. Never rewrite published history (amend/rebase/filter-repo of pushed commits) unless the user asked for it.
3. Never commit secrets. If one lands: rotate it first, then clean (below).
4. Before anything destructive, leave a rescue ref: `git branch rescue/$(date +%s)` (or note `git rev-parse HEAD`).
5. No TTY for agents: never `git add -p`, `git mergetool`, bare `git rebase -i`, or commands that open an editor.
   Use `--no-edit`, `-m`, `GIT_EDITOR=true`, and `GIT_SEQUENCE_EDITOR` (below).
6. Don't change the user's global git config silently; propose settings or set them per repo.

## Orient first (read-only)
```bash
git status -sb && git stash list && git worktree list
git log --oneline --graph --decorate -20 --all
git rev-parse --abbrev-ref @{u}; git log --oneline @{u}..   # upstream; unpushed commits
git log --oneline ..@{u}                                    # commits you are behind
```

## Worktrees for parallel agents
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
  resolve (see Conflicts), test, then fast-forward.
- Avoid multiple checkouts of a superproject with submodules (support is incomplete). `git worktree add --orphan`
  exists for an unborn branch; `--relative-paths` (2.48+) keeps links valid if the tree moves.

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
6. Prevent recurrence: `.gitignore`, gitleaks hook (below), secrets in env files outside the repo.

## Large files and model weights
| Content | Where |
|---|---|
| Model weights, checkpoints, datasets | Not in git. Hugging Face Hub (Xet storage; `hf upload`) or object storage; pin repo revision + sha256 in config |
| Binary assets that must version with code (design sources, fixtures) | Git LFS: `git lfs install`, `git lfs track "*.psd"`, commit `.gitattributes` |
| Build outputs, caches | not versioned; `.gitignore` |
- Existing binaries: `git lfs migrate info --everything --top=20`, then `git lfs migrate import --include="*.psd"
  --everything` (rewrites history: needs consent; publishing it is the user's step). Guard with `check-added-large-files`.
- Hub repos: prefer `hf download`/`hf upload`; plain git + git-lfs still works through the Hub's LFS bridge, and
  git-xet (`git xet install`) adds Xet-native transfers.

## Signing with SSH keys
```bash
git config gpg.format ssh
git config user.signingkey ~/.ssh/id_ed25519.pub
git config commit.gpgsign true; git config tag.gpgsign true
git config gpg.ssh.allowedSignersFile ~/.config/git/allowed_signers
# allowed_signers line: you@example.com namespaces="git" ssh-ed25519 AAAA...
git log --show-signature -1; git verify-commit HEAD; git log --format='%h %G? %GS'
```
Upload the public key to the forge as a signing key. Never create keys or turn signing on for the user; if a
signature needs an agent or passphrase that is unavailable, stop and report instead of committing unsigned.

## Hooks: pre-commit and gitleaks
```yaml
# .pre-commit-config.yaml  (bump with `pre-commit autoupdate --freeze`, which pins commit SHAs)
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v6.0.0
    hooks:
      - {id: check-added-large-files, args: ["--maxkb=1024"]}
      - {id: check-merge-conflict}
      - {id: detect-private-key}
      - {id: end-of-file-fixer}
      - {id: trailing-whitespace}
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.30.1
    hooks:
      - {id: gitleaks}        # runs: gitleaks git --pre-commit --redact --staged --verbose
```
- `uv tool install pre-commit`; `pre-commit install` (add `--hook-type pre-push` for push hooks);
  `pre-commit run --all-files` once after adding. `SKIP=<id>` or `--no-verify` only on the user's instruction.
- gitleaks: `gitleaks git --redact -v` scans history; `--log-opts="origin/main..HEAD"` limits the range;
  `gitleaks dir <path>` scans files. False positives: `.gitleaksignore` fingerprints or a `gitleaks:allow` comment.
  (`detect`/`protect` are deprecated since 8.19.)
- Git 2.54 can also define hooks in config (`hook.<name>.event`, `hook.<name>.command`, `git hook list <event>`).

## Forge CLIs
Agents use these read-only (`gh pr view|checks`, `gh run view|watch`, `tea pulls list`); creating, merging,
reviewing or commenting on a PR/MR, releases and `gh api` writes go to the remote, so they are the user's step,
like a push (the no-push hook refuses them); the write commands below are for the user's reference.
- GitHub (`gh`): `gh pr create --fill --base main --head <branch> [--draft]`; `gh pr checks --watch --fail-fast`;
  `gh pr view --json state,mergeable,reviewDecision`; `gh pr merge --squash --delete-branch [--auto]
  [--match-head-commit <sha>]`; `gh run view <id> --log-failed`; `gh run watch <id> --exit-status`; `gh api ...`.
- Gitea/Forgejo (`tea` 0.16): `tea login add --name <n> --url <url> --token <t>`; `tea pulls create --head <b>
  --base main --title ... --description ...`; `tea pulls checkout <n>`; `tea pulls merge --style squash <n>`
  (merge|rebase|squash|rebase-merge); `tea pulls clean <n>`; `tea issues create --title ...`; `-o json`;
  `tea api` and `tea actions` exist since 0.12. Forgejo-native alternative: `fj` (forgejo-cli):
  `fj auth login`, `fj pr create "<title>" --body ...`, `fj pr merge --method <m> --delete`.
- Tokens come from the CLI's own login store or env; never paste them into commands that end up in logs.

## Big repositories
- Blobless clone for development: `git clone --filter=blob:none <url>` (blobs fetched on demand).
  Treeless (`--filter=tree:0`) only for one-shot builds; shallow (`--depth 1`) breaks bisect and merge-base.
- Sparse checkout (cone mode is the default; tested): `git clone --filter=blob:none --sparse <url>`, then
  `git sparse-checkout set src/pkg docs`, `add <dir>`, `list`, `disable`.
- `git maintenance start` schedules background prefetch and repacks; `git backfill` (experimental) batch-fetches
  missing blobs of a blobless clone.

## Submodules vs subtrees
| | Submodule | Subtree |
|---|---|---|
| Stores | a pointer to a commit of another repo | the other repo's content (optionally squashed) |
| Clone/update | `git clone --recurse-submodules`; `git submodule update --init --recursive`; bump with `git submodule update --remote <path>` and commit the pointer | nothing extra; `git subtree pull --prefix=<dir> <repo> <ref> --squash` |
| Use for | large or independently released deps | small vendored code; consumers never see it |
- Prefer a package manager when the dependency is published. Submodule pitfalls: detached HEAD inside it,
  forgetting to commit the new pointer, CI clones without `--recurse-submodules`.

## .gitattributes
```gitattributes
* text=auto eol=lf
*.bat text eol=crlf
*.png binary
*.safetensors binary
*.py diff=python
*.json diff=json
uv.lock -diff linguist-generated
vendor/** linguist-vendored
docs/** linguist-documentation
.github/** export-ignore
```
- `diff=json` needs a driver: `git config diff.json.textconv "python3 -m json.tool --sort-keys"` (tested);
  built-in hunk-header drivers include python, rust, golang, markdown, tex, cpp. No brace globs (`*.{a,b}`).
- `linguist-*` shape language stats and collapse generated diffs on GitHub; `export-ignore` affects `git archive`.
- After adding eol rules to an existing repo: `git add --renormalize .` and commit. Inspect: `git check-attr -a <file>`.

## Verify
- `git status` clean; before merging, `git log --oneline --graph main..<branch>` shows exactly the intended commits.
- After any rewrite: `git range-diff`, tests at the tip (or `git rebase -x` per commit), `gitleaks git --log-opts=...`.
- After recovery: `git fsck --no-dangling` passes and the rescued branch has the expected tip.
- Worktrees: `git worktree list` has no stale or prunable entries you created; merged agent branches deleted.

## Report
- Branches and commits (sha, subject), the commit local `main` now points at, merge method; nothing pushed.
- Conflicts: files, how each was resolved, the test command and result afterwards.
- Destructive steps (rewrite, branch deletion): the exact command and the user instruction behind it;
  rescue refs left in place.
- Anything left undone: stale worktrees, secrets that still need rotation, forge-side cleanup pending.
