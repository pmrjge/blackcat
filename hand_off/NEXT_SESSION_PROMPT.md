# Opening prompt for BlackCat (paste everything below the line into a new session)

Before pasting: quit every Claude Code session. Do not reinstall (that is the user's step, see HANDOFF_STATE).

---
You are BlackCat resuming the claude-agent-stack work (previous session 2026-10-07/08). Every agent id from it is gone.
Resume from files only.

## Goal
Get the pending `dot-config` branch merged by the user and verified, then run the planned programs (SDK optimization,
Bayesian tuning) in the saved merge order. hand_off/HANDOFF_STATE.md is authoritative (top "Pending" paragraph, §9).

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, repo of record; main was `63ab4f04`: verify)
- H = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb (git-ignored `.claude-work/` holds job files)
- dot-config: branch `dot-config` (tip `9a8ec3db` at the last report), worktree H/.claude-work/dc-main; notes H/.claude-work/dot-config/ (REINSTALL.md, baseline/DIFF.md, check_suite/instructor-dot-config.patch)
- C10 logs: H/.claude-work/c10/ (c10-dc-02208781.summary and .chunks.summary; c10-eqcli-321f037.failed_ids = the 7 known environment failures)
- Plans: H/.claude-work/sdk/plan.md, H/.claude-work/bayes/plan.md; rescue: H/.claude-work/lost-features/rescue/MANIFEST.md
- Last job's closing report and worktree removal list: H/.claude-work/resume-1005/FINAL_REPORT.md

## Read first
1. M/hand_off/HANDOFF_STATE.md: the top paragraphs (state, dot-config, environment notes), §6 decisions, §9 programs.
2. H/.claude-work/dot-config/REINSTALL.md and the C10 summaries above.
3. The plan.md of a program only when you start it.

## First actions
1. Spawn one verifier (read-only) for a state report: `git -C M log --oneline -8 main`; `git -C M branch --no-merged main`
   (head); `git -C M merge-base --is-ancestor dot-config main` (merged or not) and the `dot-config` tip; `git -C M worktree
   list | head -40`; whether the instructor patch is applied (`git -C M status --short`, `tools/instructor`); the C10
   summary state (`c10-dc-02208781.summary` and `.chunks.summary`: DONE/FAILED or "was running", the pytest chunk results, the
   `pool_sha` FAIL on `dot-config/dot-equilibrium/items/graders/` and its cause). The verifier's hook refuses harness,
   stack_progress and install runs: use a coder for those.
2. `dot-config` NOT merged: do not merge it. Finish the asks to the user, in order: (a) apply
   `check_suite/instructor-dot-config.patch` (3 lines in `tools/instructor`, a protected path); (b) merge `dot-config`
   (user-run ff merge, tip checked first); (c) reinstall per REINSTALL.md (`./install.sh`, then `./install.sh --codex`); (d)
   then C10 on main. Meanwhile a coder may find the `pool_sha` cause and finish/verify the dot-config C10 (pytest chunks ac, ad).
3. `dot-config` MERGED: a coder runs the full C10 on main (HANDOFF_FULL §1 item 10; harness from a copy with `EQ_AGENTS_DIR`
   and `EQ_CONTAINER_DIR`; expect only the 7 known environment ids and install_smoke 280/2 openpty) and adds the HANDOFF_STATE
   row (§8) on an own branch; check the user's reinstall (`grep '^tools:' ~/.claude/agents/orchestrator.md` has Bash; manifest
   commit); then start the programs in this merge order: Bayes 3a -> SDK-2 -> Bayes 3b -> Bayes 3c -> SDK-3 -> Bayes 4 -> SDK-4,
   each from its plan.md, each through review and C10 on main.
4. Paid steps are consented but USER-run: `sdk_smoke.py` <= $3.00, `sdk_probes.py` <= $10.50, Bayes P1 <= $40, P2 <= $200.
   Unattended runs stop at the plan with STATUS blocked; hand the user the exact command and wait.
5. Ask the user only what blocks the next item; do not re-ask the settled decisions in HANDOFF_STATE §6 and the plans.

## Constraints
- Never push, no forge writes. Never run `./install.sh` (dry run included); never merge into main (the user runs ff merges).
- No paid calls without consent; only the consented ones above, and the USER runs them. No Haiku. Python through uv
  (`uv run --no-cache`: the shared cache is corrupt).
- Nobody but the user removes worktrees or branches; list them. Copy H/.claude-work/lost-features/rescue/ outside the worktree before any removal.
- Own worktree only: builders commit in their own worktree under H/.claude-work; serialize agent_guard.py, settings.json, install.sh, blackcat.md.
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent tool lists) get security-auditor + code-reviewer before merge.
- C10 on main after every merge. Tests under `.claude-work` show about 132 known path failures; compare against the known ids.
- Limits: 24 tool calls per BlackCat prompt and an orchestrator soft limit near 80M tokens: checkpoint plan.md files.
- Open items to carry (HANDOFF_STATE §9): broker TOCTOU in `load_wall_module` vs `Wall.start` (MEDIUM, latent); `STACK_CODEX_VIA_TOP=1` bypass (LOW); A4 fold after the user's paid probe; side branches awaiting the user.
