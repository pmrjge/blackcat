# Next session: opening prompt for BlackCat (paste everything below the line)

---
You are BlackCat resuming the claude-agent-stack work after a session stop (2026-10-05, the weekly usage ran out).
Resume from files only: every agent id from earlier sessions is gone.

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout; the repo of record)
- T = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f (job files under T/.claude-work/, git-ignored)
- S = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agent-stack-resume-9caddf (previous session's worktree; S/.claude-work/ holds r3/, s4-*/, wrapup/)
- EQ-T = T/.claude-work/equilibrium · WT = M/.claude/worktrees

## Read first (in this order; stop when you have what the step needs)
1. M/claude_info/HANDOFF_FULL.md: state, held branches, decisions, ASK USER list, future plan (authoritative).
2. T/.claude-work/next-steps/plan.md: the last sections (the "2026-10-05 09:13 RESUME" table and later checkpoints).
3. S/.claude-work/r3/STATE.md (R3 installer: what is done, the spec deviations, what remains).
4. T/.claude-work/next-steps/R5_MAP.md and T/.claude-work/one-tree/AUDIT.tsv (Stage 3 and worktree audit), only when you reach them.

## State (verify, do not trust)
- main = the commit HANDOFF_FULL §0 names; installed manifest = 7d12c58. c0 not collected; Docker runbook not run; install HELD.
- R1, R2 (incl. R2d) done in EQ-T (not in git). X7 POSITIVE for the default-deny WALL policy. no_verdict_policy = "zero" (F1 fixed).
- R3 installer: uncommitted work in WT/agent-ac1227df5c0315a8a (branch worktree-agent-ac1227df5c0315a8a). Do not discard or rewrite it.
- Held branches (need security-auditor + code-reviewer before merge): L2 s4-l2-output b6e05d6 (+3 patches), instructor
  s4-instructor-build deea4d5 (plumbing commit: re-commit from its own worktree), L5 s4-l5-budget 2ebc26f (+2 patches).
  L7/L10 s4-l7-l10 d246778 is not shipped. L1 d955bef is merged (one MEDIUM + two LOW review follow-ups open, HANDOFF_FULL §4).

## Standing constraints
Never push, no forge writes · no ./install.sh by agents (install HELD) · no paid runs without consent · NO HAIKU anywhere
(sonnet/opus only) · every security surface (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh)
gets security-auditor + code-reviewer before merge · own worktree only: builders in M are spawned with
isolation: "worktree" and commit there; no scratch clones, plumbing commits or writes into another worktree · serialize
agent_guard.py / settings.json / install.sh / blackcat.md · uv for Python · measure before tuning · C10 on main after
every merge (HANDOFF_FULL §1 item 10) · user-only gates go to ASK USER, never skipped · checkpoint plan.md and
HANDOFF_FULL after each stage (usage is tight).

## Decisions already made (do not re-ask)
HANDOFF_FULL §5. In short: tau 0.6 / t = 2; no Haiku; Phases 2-3 deferred; Docker Desktop default; leanest Lean image by
comparison; A3 (a) WALL + sandboxed member Bash; no paid A/B (incl. no L7 A/B); output style Default (user); installer-managed
CLAUDE.md block; instructor = just + uv; levers L1 L2 L5 L6 L7 L9 L10, L8 audit only; X4/X8 image rules; ONE_TREE run by the
user; no_verdict_policy zero; own-worktree-only commits; L7 = mechanisms not prompts (MECHANISMS.md); L5 observe now,
warn when DESIGN.md §7 criteria are met (security review of the switch); c0 + Docker not done -> installer held.

## Scope, in order (serialized merges)
1. R3 installer: finish in its worktree, full C10, commit there; security-auditor + code-reviewer; fixes; ff-merge; C10 on main.
2. L2 (+install-wiring), then L1 follow-ups + the CLAUDE.md managed block, then instructor (+3 patches), then L5 (+2 patches);
   each: own worktree, commit, two reviews, ff-merge, C10 on main.
3. L7 mechanisms B1-B3 (serialized, security review); L10 trims only if the user wants the -26 tokens/spawn side commit.
4. Stage 3 quality pass from R5_MAP.md (behaviour-neutral; behaviour changes listed for approval).
5. ONE_TREE.sh: code-reviewer + verifier dry run, re-take AUDIT.tsv; the user runs it.

## First action
Spawn one verifier (read-only): main SHA and log -5; `git -C M worktree list`; `git -C M status --short`; R3b worktree
status unchanged (24 lines: 13 modified + 11 untracked, nothing newer than 12:29); manifest commit in ~/.claude/.stack-manifest.json; whether
M/claude_next_steps/work_carried/context-diet/arms/c0 exists. Then dispatch, in one message, the orchestrator (or a
main-coder for R3 alone) with HANDOFF_FULL §7 as its plan, and ask the user the questions below in one AskUserQuestion round.

## Questions for the user (one round; HANDOFF_FULL §6 has the detail)
1. Have you run c0 (RUNBOOK_c0.md) and the Docker runbook (RUNBOOK_MINIMAL.md)? If not, when?
2. Oracle residuals: two-container PF judge and moving CP in-process tests: yes or no?
3. Images: Debian packages vs pinned static binaries; Scala 3 tarball vs scala-cli/sbt; MongoDB (SSPL-1.0) in or out; cc linker for Rust/Haskell.
4. Plugin pinning / autoUpdate for claude-plugins-official.
5. Stage 4 threshold 3% / 2% / 4 of 5: keep?
6. SendMessage-resume rule; subagent cache TTL 1 h (measured -5.4%); omitClaudeMd: adopt each or not?
7. ONE_TREE: per unique-commit row merge / archive (git bundle) / discard; the 5 dirty worktrees; protocol-p1 rebase (continue / abort / archive).
