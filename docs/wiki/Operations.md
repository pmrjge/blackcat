<!-- markdownlint-disable MD013 MD060 -->
# Operations and user steps

Some steps only you can take. Agents never push, never run `install.sh` (beyond `--help`, `--dry-run`, `--diff`,
`--print-managed-settings` and scratch installs), never remove worktrees, never approve their own installs and
never make paid calls without your consent. This page collects those steps. The exact, session-specific sequence
of the latest hand-off is in `hand_off/HANDOFF_STATE.md` §5; read it before acting on a hand-off.

## Reinstall after a merge

A change on `main` reaches your sessions only when you reinstall. Quit every Claude Code session first: a running
session keeps the agent files it started with.

```bash
git -C <your checkout> log --oneline -3      # the commit you are about to install
cd <your checkout>
./install.sh --dry-run                       # read the plan
./install.sh                                 # asks before applying a changed stack (--yes skips the question)
```

Then start `claude` and run `/stack-doctor`. To undo: `./install.sh --restore` (the latest backup, in
`~/.local/state/claude-agent-stack-backups`). Details: [Getting started](Getting-Started.md).

## Live checks of the sandbox

The sandbox is configured, not live-verified. The README's "Live checks" list is yours to run: the install with
its change question, `/sandbox` showing the `denyWrite` entries, the sandbox cache variables reaching a subagent's
Bash, whether the keychain helper answers inside the sandbox, routing a near-impossible problem to ninja-coder,
ask rules prompting under `bypassPermissions`, the credential section of `doctor.sh`, and toolsmith's executor
running unsandboxed in each permission mode. The permission-mode probe (`STACK_MODE_PROBE=1`, CONFIG §5
"Permission modes") is a related check: it needs your interactive session and Shift+Tab, so no agent can run it.

## Paid probe (A4)

`hand_off/A4_FOLD.md` describes one paid call (consent given: one call, hard cap $0.25) that checks how
`claude -p --agent writer` combines an agent's frontmatter tools with `--tools`, `--allowedTools` and
`--json-schema`. It is yours to run from a normal logged-in terminal (agent sandboxes have no `claude` login), with
the stack as installed now and not in the middle of the c0 arm. Then:

1. Fold the output with `hand_off/a4_fold.py` (read-only; it strips credentials, tokens, session ids, emails and
   home paths, and prints one verdict per open question: `confirmed`, `refuted`, `consistent` or `unknown`).
2. Hand the fold to a fresh python-engineer with the brief in `A4_FOLD.md` §3; it edits only the A4 item of the
   harness's `COMPARE_eq.md`, after archiving it.

Do not paste the raw probe output anywhere: it can hold session ids and paths.

## The c0 runbook

`hand_off/RUNBOOK_c0.md` collects c0, the pre-registered baseline arm of the context-diet campaign: the installed
stack at commit `a22c5b4`, 17 prompts in a fixed order, one fresh session, then frozen. Every command is yours and
the run is paid (17 real prompts through BlackCat and its children).

| Section | What happens |
|---|---|
| 0. Read first | the fixed order; the recovered inputs in `hand_off/c0_support/` and their pins; the C2 digest risk of installing from a clone |
| 1. Preflight | rebuild the c0 input tree |
| A | reinstall `a22c5b4` from a throwaway clone (a downgrade; the clone keeps your checkout and worktrees untouched) |
| B | verify before the first dispatch (`c0_check.sh`) |
| Collect | the 17 prompts in one session used for c0 only, then `freeze.sh --arm c0` |
| C | back to `main`: the same reinstall as above |
| 12 | the dated re-pin of the manifest digest for the clone install (decided 2026-10-05) |

Do not install `main` between A and C: the comparison protocol (`COMPARE_c0.md` §1 and §7) treats any install or
`stack.env` edit during the arm as an arm stop. Quit every other Claude Code session before A3.

## Worktrees and branches

- **Nobody but you removes worktrees** (user decision, `HANDOFF_STATE.md` §6 item 13): an integrator fast-forwards
  `main`, then lists the worktree and branch for you instead of removing them.
- Hand-made worktrees go under `<main checkout>/.claude-work/worktrees/<name>`; Claude Code's
  `isolation: "worktree"` worktrees stay in `<main checkout>/.claude/worktrees` (decision 14).
- **See what can go:** `just -f tools/instructor/justfile worktree-audit` reports every worktree (main, bare,
  prunable, busy, dirty, merged-clean, unmerged, detached) and every branch without a worktree, and changes
  nothing.
- **Remove what is merged and clean**, from your terminal: `git worktree remove <path>`, then `git branch -d
  <branch>` (`-d` refuses an unmerged branch). Anything dirty or unmerged: archive it first, or use
  `RESET_TO_MAIN.sh` below.

## `RESET_TO_MAIN.sh`: back to "only main", safely

`hand_off/RESET_TO_MAIN.sh` (macOS `/bin/bash` 3.2) resets the repository to its `main` branch after archiving
everything unique. It has three modes:

| Mode | Does | Writes |
|---|---|---|
| (none) | dry run: inspects, classifies and prints every command stages 1 and 2 would run | nothing (git runs with `GIT_OPTIONAL_LOCKS=0`, no temp files) |
| `--archive [DIR]` | stage 1: a full bundle of `main`; a bundle per branch and per detached HEAD with commits not in `main`; a pack of commits only reflogs reach; per worktree its status, HEAD, diffs and a tarball of untracked and ignored files; named tarballs; `MANIFEST.tsv` and its sha256; then verifies it | only DIR (0700, files 0600); refuses a non-empty DIR unless `--resume` |
| `--apply [DIR]` | stage 2, only if DIR's manifest, sizes, sha256s and bundles verify (else exit 4, nothing changes): `git worktree remove` for each worktree whose state still matches the archive (`--force` only for a dirty one), `git branch -d` for merged branches, `git branch -D` only for a branch whose verified bundle holds its tip | the repository |

> **Warnings.** `--apply` removes worktrees and deletes branches; `--clean` (with `--apply`) runs
> `git clean -fdx` in the main checkout after showing `git clean -ndx`; `--gc` (with `--apply`) expires every
> reflog and prunes. Past the archive these are not reversible. Run the dry run, read it, run `--archive`, check
> the manifest, and only then `--apply`. The script's `DEFAULT_DIR` and `DEFAULT_LAST` are paths on the author's
> machine: pass `--dir` and `--last` on yours. The archive directory lies outside the agents' sandbox, and
> `--apply` is your step, never an agent's (decision 10).

Blockers, listed and never touched: the main checkout itself, the worktree the caller runs from, locked
worktrees, `--session-wt` worktrees, an operation in progress (rebase, merge, cherry-pick, revert, bisect), an
`index.lock`, a file modified in the last 60 minutes (`--live-minutes`). Exit codes: 0 success, 1 unexpected internal
error, 2 usage, 3 precondition failed, 4 archive verification failed, 5 something left undone, 6 an archive item or git command
failed. Tests: `hand_off/tests/test_reset_to_main.py` (throwaway repositories).

## Side effect of the instructor deny rule

The deny rule `Edit(//**/tools/instructor/**)` is anchored at the filesystem root, so it covers every
`tools/instructor` directory on your machine, including those of unrelated projects (accepted by you on
2026-10-06). On macOS, Claude Code also adds `Edit` rule paths to the Bash sandbox's `denyWrite`, so after the
rule is installed **a sandboxed command cannot create or change any file under any `tools/instructor`**:

- `git merge`, `git checkout`, `git worktree add` or a clone of this repository from an agent's Bash, and
  `ff-merge`'s `read-tree` of a commit that touches the instructor, fail with `Operation not permitted` or
  `unable to unlink old`;
- with `allowUnsandboxedCommands: false` there is no unsandboxed retry, so you run that git command yourself from
  a terminal.

This behaviour comes from the Claude Code docs (sandbox path prefixes, read 2026-10-06), not from an observed
run. Source: CONFIG §5 "Instructor", "Not agent-writable".

## Keeping the toolchains current

`install.sh` never upgrades a tool it finds. Updating them is yours, in your terminal, per tool (`brew upgrade`,
`rustup update`, `uv self update`, `uv python upgrade 3.13` followed by `./install.sh`, …); the full table is the
README's "Updating the toolchains". Pinned tools (Gradle, Playwright's browsers, the stack's venvs) move when a
newer `install.sh` pins newer versions.

Sources: `hand_off/HANDOFF_STATE.md` (§5 user steps, §6 decisions), `hand_off/A4_FOLD.md`,
`hand_off/RUNBOOK_c0.md` (§0, section list), `hand_off/RESET_TO_MAIN.sh` (usage header), `README.md` ("Live
checks", "Updating the toolchains"), `CONFIG.md` §5 ("Instructor", "Permission modes").
