# Opening prompt for BlackCat (paste everything below the line into a new session)

Before pasting: quit every Claude Code session. Do not reinstall from an agent (that is the user's step, see HANDOFF_STATE).

---
You are BlackCat resuming the claude-agent-stack work (previous session 2026-10-08). Every agent id from it is gone.
Resume from files only.

## Goal
Finish the remaining plan on top of main `47dce9f4` (shrink-on and bayes-3a-fixes merged, C10 on main green,
reinstalled): the guard fix T-guard-timeout, SDK-1, Bayes WP2/WP4/3b/3c, then the later SDK and Bayes steps, each landed in the
saved merge order. hand_off/HANDOFF_STATE.md is authoritative (sections 1 state, 2 decisions, 4 left to do, 5 user steps,
9 programs).

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, repo of record; main was `47dce9f4` at the hand-off: verify; layout dot-config/{dot-claude,dot-equilibrium})
- H = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb (git-ignored `.claude-work/` holds job files; its branch `golden/handoff-plan-continuation-c09473` is superseded, do not merge it). Agent Bash sandboxes cannot write H; the Write and Edit tools can.
- Hand-off branch: `golden/work-order-continuation-b06255` (worktree /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544, on `47dce9f4`), awaiting the user's ff
- Merged by the user: `limits-raise` (soft prompt orchestrator 140M, hard.prompt 300M, live), `bayes/3a` (`91fd17d2`), `shrink-on` (`a0791669`), `bayes-3a-fixes` (`47dce9f4`)
- Program branches (created 2026-10-08 23:04 at `47dce9f4`): `fix/guard-timeout`, `sdk/1`, `bayes/3b`, `bayes/4`; worktrees under M/.claude-work/ and the hand-off worktree's .claude-work/ (`git -C M worktree list`)
- Work-order tracker: H/.claude-work/work-order-1008/plan.md
- Reinstall notes: H/.claude-work/dot-config/REINSTALL.md
- C10: H/.claude-work/c10/ (latest on main: c10-bayes-3a-fixes-47dce9f4.summary, green; from now on `c10-ref.sh <ref>`, user terminal only; c10-eqcli-321f037.failed_ids under resume-770728/.claude-work/c10/ = the 7 known environment ids, which pass outside the sandbox)
- Plans: H/.claude-work/sdk/plan.md, H/.claude-work/bayes/plan.md (section "STAGE 3b-4 EXECUTION"), H/.claude-work/shrink-on/plan.md (T-guard-timeout ticket); measurements: H/.claude-work/output-shrink-on/A_numbers.md, H/.claude-work/deterministic-offload/; rescue: H/.claude-work/lost-features/rescue/MANIFEST.md

## Read first
1. M/hand_off/HANDOFF_STATE.md (on main once the user ff-merges `golden/work-order-continuation-b06255`; until then read it in that worktree): sections 1, 2, 4, 5, 9.
2. H/.claude-work/work-order-1008/plan.md and the plan.md of a program only when you start it.

## First actions
1. Spawn one verifier (read-only) for a state report: main tip (`git -C M log --oneline -8 main`); whether
   `golden/work-order-continuation-b06255` is merged; the tips of `fix/guard-timeout`, `sdk/1`, `sdk/2`, `bayes/3b`, `bayes/3c`,
   `bayes/4` against main (`git -C M log --oneline main..<b>`); the installed manifest commit (`~/.claude/.stack-manifest.json`)
   against main; the newest `c10-*.summary` in H/.claude-work/c10/. The verifier's hook refuses
   harness, stack_progress and install runs: use a coder for those.
2. Guard fix T-guard-timeout on `fix/guard-timeout`: `timeout 5 cp x <cfg>/hooks/f` passes agent_guard's protected-path scan
   because in `_Scan.scan_words` the duration operand ends the command position; keep the command position over the
   `_duration()` word after `timeout`/`gtimeout` (and their `-s`/`-k` values), as RO_WRAPPERS' `wrapper()` already does; its own
   proof test and mutant (H/.claude-work/shrink-on/plan.md). Security surface: security-auditor + code-reviewer before the merge. First in the merge order.
3. SDK-1 on `sdk/1` (H/.claude-work/sdk/plan.md): `tests/sdk_probes.py` (PEP 723 plus lock, run by the user, never by pytest),
   pinned `claude-agent-sdk==0.2.163`; code-reviewer. Then the user runs the consented paid probes
   (`uv run --script tests/sdk_smoke.py` <= $3.00, `uv run --script tests/sdk_probes.py` <= $10.50); freeze the SDK-2 design on
   their results.
4. Bayes (H/.claude-work/bayes/plan.md): WP2 refit v3 on a live copy (data-scientist; output M/.claude-work/bayes/wp2/); WP4
   scheduler `load_bayes_sched` on `bayes/4`; WP3b detached fitter on `bayes/3b` (needs WP2's fit time); WP3c remainder on
   `bayes/3c`, only after the guard merge (agent_guard.py edits are serialized).
5. Merge order: guard (`fix/guard-timeout`) -> `sdk/2` -> `bayes/3b` -> `bayes/3c` -> `sdk/3` -> `bayes/4` -> `sdk/4`. For each:
   review, then a full C10 on its tip run by the user (`cd ~ && bash H/.claude-work/c10/c10-ref.sh <branch>`; agents cannot: the
   sandbox refuses the `tools/instructor` directories; never two C10 scripts at once), then the user's
   `git -C M merge --ff-only <branch>` (main then equals the tested tip). New failed ids: fix on the branch before the merge.
   Where `sdk/1` lands (alone before `sdk/2` or folded into it) is not settled: ask the user when SDK-1 is ready.
6. Paid steps are consented but USER-run: `sdk_smoke.py` <= $3.00, `sdk_probes.py` <= $10.50, Bayes P1 <= $40, P2 <= $200,
   A4 probe <= $0.25. Unattended runs stop at the plan with STATUS blocked; hand the user the exact command and wait.
7. Ask the user only what blocks the next item; do not re-ask the settled decisions in HANDOFF_STATE section 2 and the plans.

## Constraints
- Never push, no forge writes. Never run `./install.sh` (dry run included); never merge into main (the user runs ff merges).
- No paid calls without consent; only the consented ones above, and the USER runs them. No Haiku. Python through uv
  (`uv run --no-cache`: the shared cache is corrupt).
- Nobody but the user removes worktrees or branches; list them (`just worktree-audit`). Copy H/.claude-work/lost-features/rescue/ outside the worktree before any removal.
- Own worktree only: builders commit in their own worktree under H/.claude-work; serialize agent_guard.py, settings.json, install.sh, blackcat.md. Do not edit tools/instructor or lib/eq-wall (protected).
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent tool lists) get security-auditor + code-reviewer before merge.
- C10 on main after every merge, and a full C10 on a branch tip before calling it merge-ready (a targeted-test pass is not a C10: Bayes 3a was merged on one and broke 12 tests); with an ff-only merge the tip C10 is the C10 on main, unless main moved in between. Full C10s run only from the user's terminal (`c10-ref.sh <ref>` in H/.claude-work/c10/, short clone /tmp/c10s, `UV_CACHE_DIR` set; launch from `cd ~`). Tests under `.claude-work` show about 130 known path failures; compare against the known ids.
- Limits: 24 tool calls per BlackCat prompt and the orchestrator soft token limit (140M, live): checkpoint plan.md files. The rules file is exactly at the prompt_budget gate: any rules text needs a gate or trim decision from the user.
- Open items to carry (HANDOFF_STATE sections 4 and 7): T-guard-timeout (agent_guard, fix direction in H/.claude-work/shrink-on/plan.md); `output_shrink.py report` needs M as its argument when run from a linked worktree; doctor.sh needs the user's terminal (sandbox-only FAILs); broker TOCTOU in `load_wall_module` vs `Wall.start` (MEDIUM, latent); A4 fold after the user's paid probe; optional `UV_CACHE_DIR` default in `_run_install` and the smoke harness (main-coder); side branches, scratch worktrees and `refs/rescue/shrink-on-51dcd288` for the user (section 3); model display: check project-level `.claude/agents` shadowing in that other session.
