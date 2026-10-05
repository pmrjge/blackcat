# Next session: opening prompt for BlackCat (paste everything below the line)

Before pasting: quit every Claude Code session. Do not reinstall yet: `orch-bash` is not merged (its edits are still
uncommitted in its worktree), so start the session without reinstalling; step 3 below covers it. All agents of the
previous session were stopped by the user at ~16:37 (`hand_off/HANDOFF_STATE.md`, STOPPED STATE).

---
You are BlackCat resuming the claude-agent-stack work (previous session 8ad965da, 2026-10-05). Every agent id from that
session is gone: resume from files only.

## Goal
Finish the resume-1005 plan: C10 on main (the run after the L1 follow-ups merge was interrupted), land `orch-bash`
(orchestrator gets Bash) and the R3 `container` port, then L2, the CLAUDE.md block, instructor, L5, L7 B1/B3 + L10,
Stage 3, ONE_TREE/RESET_TO_MAIN (dry run; `--apply` is the user's) and the c0 runbook, each merged in order through
review and C10 on main.

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, repo of record; hand_off/ is committed on main); WT = M/.claude/worktrees
- H = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb (git-ignored .claude-work/resume-1005/, .claude-work/t1b/)
- orch-bash = M/.claude-work/worktrees/orch-bash (branch orch-bash, no commits, edits uncommitted)
- EQ-T = WT/eq-t-1005/.claude-work/equilibrium (not in git; snapshot H/.claude-work/t1b/equilibrium-snapshot-1611/), unless the user moved it to M/.claude-work/worktrees/eq-t-1005
- R3 = WT/agent-a5a3114a94bceb867 (branch worktree-agent-a5a3114a94bceb867; notes in its .claude-work/r3/STATE.md, plan.md)
- The old worktrees T (next-steps-7c1c7f) and S (agent-stack-resume-9caddf) no longer exist; ignore paths into them.

## Read first
1. M/hand_off/HANDOFF_STATE.md (authoritative: done, stopped, lost, the ordered plan with owners, user steps, decisions, open items).
2. H/claude_info/HANDOFF_FULL.md only for what HANDOFF_STATE points to (§1 constraints and the C10 command, §2 R4 lever table, §4 L1 findings, §5 older decisions).
3. H/.claude-work/resume-1005/t-loss.md and worktree-cleanup.md only when a step needs them.

## First actions
1. Spawn one verifier (read-only) to report: `git -C M log --oneline -8`; `git -C M worktree list`; `git -C M status --short`;
   the manifest commit in ~/.claude/.stack-manifest.json; `grep '^tools:' ~/.claude/agents/orchestrator.md` and the same
   line in M/dot-claude/agents/orchestrator.md; for branches `orch-bash`, `worktree-agent-a5a3114a94bceb867`,
   `worktree-agent-afb29c2edb383d1dc`: tip SHA, commits ahead of main, merged or not, worktree dirty or clean (at the stop:
   orch-bash and R3 had uncommitted edits; L1 was merged, clean); R3's STATE.md "Remaining" list as it stands now; EQ-T
   location and `diff -rq` against the snapshot; whether `M/.claude-work/resume-1005/reset/` exists (it did not at the stop).
   Then a full C10 on main at its HEAD (HANDOFF_STATE §4 item 0; the run on 2aff512 was interrupted).
2. With the verifier's report, update HANDOFF_STATE §2/§4 (which items are done; it is tracked on main, so the update is
   a commit in an own worktree, fast-forwarded), then dispatch the orchestrator with HANDOFF_STATE §4 as its plan,
   starting at the first item not done. If the orchestrator's installed tool line has no
   Bash yet, it still coordinates; builders run the commands.
3. If `orch-bash` is unmerged: security-auditor review, fixes, INTEG through its builder; then tell the user the
   reinstall in HANDOFF_STATE §5 is ready (a user step: you never run install.sh).
4. Ask the user only what is still open in HANDOFF_STATE §7 that blocks the next item; decisions in §6 are settled.

## Constraints
- Never push, no forge writes. Never run `./install.sh` (dry run included); the reinstall is the user's step.
- No paid calls (`claude -p`, pilots, A/B) without explicit consent; logged-in `claude` steps are user steps.
- Nobody but the user removes worktrees or branches; INTEG lists them for the user instead.
- Own worktree only: builders commit in their own worktree, `git -C M merge --ff-only <branch>`; hand-made worktrees go
  under M/.claude-work/worktrees/<name>. One INTEG at a time; serialize agent_guard.py, settings.json, install.sh, blackcat.md.
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent tool lists) get
  security-auditor + code-reviewer before merge. Deny rules on paths are Read()+Edit(); Write() rules are never consulted.
- C10 on main after every merge (HANDOFF_FULL §1 item 10). No Haiku. Python through uv. Measure before tuning.
- Do not re-ask decisions in HANDOFF_STATE §6. Lost files are re-derived, not recovered.
- Checkpoint H/.claude-work/resume-1005/plan.md and HANDOFF_STATE after each merged item.
