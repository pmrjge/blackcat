# Opening prompt for BlackCat (paste everything below the line into a new session)

Before pasting: quit every Claude Code session. Installing is the user's step (HANDOFF_STATE §5); no agent runs `install.sh`.

---
You are BlackCat resuming the claude-agent-stack work (previous sessions 2026-10-08 to 2026-10-10). Every agent id from them
is gone. Resume from files only.

## Goal
Carry on the 2026-10-10 order in hand_off/HANDOFF_STATE.md §4: (1) the user's C10 and ff-merge of `sdk/plan-bash-gate`,
(2) the `--no-ff` merge of `docs/handoff-10b` (this hand-off), (3) step 11, `./install.sh --with-bayes`, which starts gathering
data in shadow; after step 11: `bayes/5-drift` and `bayes/5b` (each: main merged in, C10, ff-only), the 5d rehearsal, the 5f
binding verdict, Q-E, Q-F, the paid E1 rerun (`sdk/probes-e3`), guard backlog steps 6-8, SDK-4, the `stack_sdk.Session`
keychain fix, 10c (token economy), the parked findings, and last the FINAL docs and wiki rewrite and the cleanup.
HANDOFF_STATE.md is authoritative: §1 state, §2 decisions, §3 branches, §4 order, §5 user commands, §7 open items.

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, repo of record; main was `c1ded439` at this hand-off: verify)
- H = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb (git-ignored `.claude-work/`:
  `c10/c10-ref.sh` and its summaries, plans `work-order-1008/`, `bayes/`, `sdk/`). Agent Bash sandboxes cannot write H; Write
  and Edit can. Do not delete H or its branch.
- W = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544 (git-ignored `.claude-work/`:
  `bayes-wp5/` (WP5 plan, route, hybrid copy), `sdk/probes-e-analysis/analysis.md`, `guard-timeout-r4/`, `sec-r5/`, `sec-r6/`,
  `main-merge-c1ded439/plan.md`, branch worktrees under `worktrees/` and `wt-probes-e2`)
- Probe reports and ledgers: M/.claude-work/sdk/probes/. Bayes data: M/.claude-work/bayes/{data,wp2}/.

## Read first
1. M/hand_off/HANDOFF_STATE.md (all of it; it is the 2026-10-10 state).
2. The plan of a workstream only when you start it: W/.claude-work/bayes-wp5/plan.md and M/docs/BAYES.md §A.9-§A.12 (WP5);
   H/.claude-work/sdk/plan.md (SDK-4); W/.claude-work/sdk/probes-e-analysis/analysis.md (probes); H/.claude-work/work-order-1008/plan.md.

## First actions
1. One verifier (read-only) for a state report: `git -C M log --oneline -12 main`; whether `sdk/plan-bash-gate` and
   `docs/handoff-10b` are merged (`git -C M merge-base --is-ancestor <b> main`); the tips of `bayes/5-drift`, `bayes/5b`,
   `sdk/probes-e2`, `sdk/probes-e3` and `git -C M rev-list --count <b>..main` for each; the installed manifest commit
   (`~/.claude/.stack-manifest.json`) against main; the newest `c10-*.summary` in H/.claude-work/c10/; the last rows of
   `~/.local/state/claude-agent-stack/usage/bayes.json.rec` (did step 11 happen: a status other than `skipped:no-pymc`?).
2. If steps 1-3 are not all done, hand the user the exact commands from HANDOFF_STATE §5 and wait; do not start the
   after-11 work before step 11 unless the user says so.
3. After step 11, in the §4 order: an agent merges main into `bayes/5-drift` (a merge commit; `refs/rescue/<branch>-pre-main-merge`
   first; tests green), the user runs its C10 and the ff; then `bayes/5b` the same way. Meanwhile, $0 work that touches
   neither main nor those files can proceed in worktrees: finishing `sdk/probes-e3` (its open items in HANDOFF_STATE §3), the
   eq_mutations anchor fix (§7 item 1), the guard backlog branch `fix/guard-backlog` (after that fix), SDK-4 drafting.
4. Ask the user only what blocks the next item: Q-E and Q-F (defaults in §4 rows 9 and 10), the go-ahead for the paid E1
   rerun (envelope `e3-2026-10-10`), the go-ahead for 10c's branch plan, and every removal in the cleanup.

## Constraints
- Never push, no forge writes. Never run `./install.sh` (dry run included); never merge into main or move it (the user runs
  every merge; main stays still during a C10).
- Paid runs only inside a consented envelope and only by the user; agents make no API calls. Bayes fits only from the user's
  terminal, never during a C10, an eq run or another fit; WP5 never edits `BAYES_LIVE`.
- Python through uv (`uv run --no-cache`: the shared cache is corrupt).
- Worktrees: make them under W/.claude-work/worktrees/ with `git worktree add --no-checkout`, `git read-tree HEAD`,
  `git checkout -- . ':(exclude)tools/instructor'`; never stage the 12 ` D tools/instructor/*` entries; explicit `git add` paths.
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, stack_sdk.py, agent tool
  lists) get security-auditor + code-reviewer before merge; serialize agent_guard.py, settings.json, install.sh, blackcat.md;
  do not edit tools/instructor or lib/eq-wall.
- A full C10 runs only from the user's terminal (`cd ~ && bash H/.claude-work/c10/c10-ref.sh <branch>`); a targeted-test pass
  is not a C10. Pass = `NEW vs known: []`, install_smoke 1 failed (openpty); eq_mutations reads 38/39 + 1 problem until the
  `callerpolicy` anchor is fixed.
- The stack rules file is at its prompt_budget gate: any rules text (10c) needs a trim or a gate decision from the user.
- Nobody but the user removes worktrees, branches or rescue refs; agents list them (HANDOFF_STATE §5 step 9).
