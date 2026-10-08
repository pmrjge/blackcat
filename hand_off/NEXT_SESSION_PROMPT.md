# Opening prompt for BlackCat (paste everything below the line into a new session)

Before pasting: quit every Claude Code session. Do not reinstall from an agent (that is the user's step, see HANDOFF_STATE).

---
You are BlackCat resuming the claude-agent-stack work (previous session 2026-10-08). Every agent id from it is gone.
Resume from files only.

## Goal
Get the user's reinstall done and verified (C10 on main), then run the planned programs (SDK optimization, Bayesian tuning)
in the saved merge order. hand_off/HANDOFF_STATE.md is authoritative (sections 1 state, 2 decisions, 5 user steps, 9 programs).

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, repo of record; main was `b0ddf192`: verify; layout dot-config/{dot-claude,dot-codex_config,dot-equilibrium})
- H = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb (git-ignored `.claude-work/` holds job files)
- Branches: `post-merge` (worktree H/.claude-work/post-merge: test_moved_paths fixes + the hand-off rewrite) and `limits-raise` (worktree H/.claude-work/limits-raise: orchestrator soft prompt 80M -> 140M, hard.prompt 100M -> 300M; may be unfinished: read its branch and the coder's report)
- Reinstall notes: H/.claude-work/dot-config/REINSTALL.md (it says 13 shipped files; 15 is correct)
- C10 logs: H/.claude-work/c10/ (c10-main-b0ddf192.summary is the latest; c10-eqcli-321f037.failed_ids under resume-770728/.claude-work/c10/ = the 7 known environment failures)
- Plans: H/.claude-work/sdk/plan.md, H/.claude-work/bayes/plan.md; rescue: H/.claude-work/lost-features/rescue/MANIFEST.md

## Read first
1. M/hand_off/HANDOFF_STATE.md: sections 1, 2, 5, 9.
2. H/.claude-work/dot-config/REINSTALL.md and the latest C10 summary.
3. The plan.md of a program only when you start it.

## First actions
1. Spawn one verifier (read-only) for a state report: `git -C M log --oneline -8 main`; `git -C M branch --no-merged main`
   (head); whether `post-merge` and `limits-raise` are ancestors of main (`merge-base --is-ancestor`) and their tips; the
   installed manifest commit (`~/.claude/.stack-manifest.json`) against main's tip; `grep '^tools:' ~/.claude/agents/orchestrator.md`
   (Bash present?); the latest C10 summary (DONE/FAILED, the failed ids against the 7 known ones). The verifier's hook refuses
   harness, stack_progress and install runs: use a coder for those.
2. The user has NOT reinstalled (manifest still `73eec41` or behind main): ask the user to merge `post-merge`
   (and `limits-raise` after its review) and reinstall (`./install.sh`, then `./install.sh --codex`, per REINSTALL.md), and wait.
   Meanwhile a coder may review and finish `limits-raise` (security surface: limits/settings: security-auditor + code-reviewer).
3. Reinstalled: a coder runs the full C10 on main (HANDOFF_FULL section 1 item 10; harness from a copy with `EQ_AGENTS_DIR` and
   `EQ_CONTAINER_DIR`; tests run from a `$TMPDIR` clone; expect only the 7 known environment ids and install_smoke 280/2 openpty)
   and records the result in HANDOFF_STATE on an own branch.
4. Then the programs in this merge order: Bayes 3a -> SDK-2 -> Bayes 3b -> Bayes 3c -> SDK-3 -> Bayes 4 -> SDK-4, each from
   its plan.md, each through review and a C10 on main.
5. Paid steps are consented but USER-run: `sdk_smoke.py` <= $3.00, `sdk_probes.py` <= $10.50, Bayes P1 <= $40, P2 <= $200,
   A4 probe <= $0.25. Unattended runs stop at the plan with STATUS blocked; hand the user the exact command and wait.
6. Ask the user only what blocks the next item; do not re-ask the settled decisions in HANDOFF_STATE section 2 and the plans.

## Constraints
- Never push, no forge writes. Never run `./install.sh` (dry run included); never merge into main (the user runs ff merges).
- No paid calls without consent; only the consented ones above, and the USER runs them. No Haiku. Python through uv
  (`uv run --no-cache`: the shared cache is corrupt).
- Nobody but the user removes worktrees or branches; list them (`just worktree-audit`). Copy H/.claude-work/lost-features/rescue/ outside the worktree before any removal.
- Own worktree only: builders commit in their own worktree under H/.claude-work; serialize agent_guard.py, settings.json, install.sh, blackcat.md. Do not edit tools/instructor or lib/eq-wall (protected).
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent tool lists) get security-auditor + code-reviewer before merge.
- C10 on main after every merge. Tests under `.claude-work` show about 130 known path failures; compare against the known ids.
- Limits: 24 tool calls per BlackCat prompt and the orchestrator soft token limit (80M until `limits-raise` is merged and installed): checkpoint plan.md files.
- Open items to carry (HANDOFF_STATE section 7): broker TOCTOU in `load_wall_module` vs `Wall.start` (MEDIUM, latent); `STACK_CODEX_VIA_TOP=1` bypass (LOW); A4 fold after the user's paid probe; side branches awaiting the user (section 3); model-display question for coder (check project-level `.claude/agents` shadowing).
