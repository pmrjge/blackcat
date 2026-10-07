# Opening prompt for BlackCat (paste everything below the line into a new session)

Before pasting: quit every Claude Code session and raise `hard.session` (`stack_limits.py show`) if needed. Do not reinstall.

---
You are BlackCat resuming the claude-agent-stack work (previous session e78878a2, stopped 2026-10-07 at the hard token budget). Every agent id from that session is gone. Resume from files only.

## Goal
Finish every remaining step of hand_off/HANDOFF_STATE.md, then report once. Only relay to the user after everything is finished. The user's sole questions are about plan guidance.

## Paths
- M = /Users/pmrj/ZDone/claude-agent-stack (main checkout, main at fd0a2a3 or later)
- WT = /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728 (worktrees: eq-runtime, eqr-harness, eqr-hdocs, eqr-mut, smokegc-fix, eqcli-integ, wiki-main-fixes/github-wiki)
- Logs: WT/.claude-work/c10/ (c10-eqcli-321f037.failed_ids = the 7 known environment failures)
- Design: M/docs/RUNTIME_EQUILIBRIUM.md; plan checkpoint: WT/eqr-harness/.claude-work/eqr-harness/plan.md
- Delegation ledger of the old session: /Users/pmrj/.local/state/claude-agent-stack/e78878a2-2ab1-4e57-9b93-1bc5dcfe521a/delegations.md

## Read first
1. M/hand_off/HANDOFF_STATE.md (§4 plan, §6 decisions, §8 live rows).
2. The plan.md checkpoint above.
3. The old session's transcript only if a detail is missing: /Users/pmrj/.claude/projects/-Users-pmrj-ZDone-Worktree-for-Claude-claude-agent-stack-resume-770728/e78878a2-2ab1-4e57-9b93-1bc5dcfe521a.jsonl

## State at the stop
- Merged to main: codex-build, eq-cli-install (321f037), the install_smoke gc fix (b99516f), eq-distroless (fd0a2a3).
- C10 on fd0a2a3 is incomplete. Passed: lint_agents, prompt_budget, guard self-test, stack_progress self-test, bash -n 311/311, image_studio 125, instructor 77, eq-wall 100. Not finished: full pytest (stalled under load ~90), install_smoke, hand_off tests, codex_config, harness suite.
- eq-runtime is NOT merged. Tips (verify them): eq-runtime b595c3c (settings hooks, decisions b–e); eqr-hdocs 7c1702d (schema v0, docs, not merged); eqr-harness 61f82b4 (not merged, not green: p6/p7, E_rt and LOO wiring untested); eqr-mut b4df8df (nothing committed; untracked tests/test_eq_gaps.py and scratch .claude-work/mut/ with gen.py, runner_head.py, runner_tail.py, disc*.jsonl).
- Known product bugs, unfixed:
  1. eq_guard.py:978. VALUE_OPTS holds upper-case options, but command_words compares the lower-cased word, so `env -C . git commit -m x`, `xargs -I X git commit …` and `xargs -E eof git commit …` are allowed for an eq member. A strict xfail test exists in test_eq_gaps.py.
  2. eq_policy.py resolve: `over_cap` is always False (estimate sets tokens_worst = caps.run_tokens), so the over-cap confirm mode never fires.
- User decision made: E_rt bundle policy = a params class status `candidate` carrying the p-selected bundle. It is honoured only in manual mode, labelled unvalidated, and auto stays refused.
- Other settled decisions: reconcile round k forks the member's latest session (round 0 stays pristine); trailer-only pass is kept, labelled exit_source: trailer, with checks.trailer_only in the result; params version 0 is accepted only for the all-not_run placeholder.

## Steps, in order (dispatch by the routing rules; one INTEG at a time)
1. Finish C10 on main at HEAD (fd0a2a3 or later). Run pytest in 4 chunks as separate background processes: `xargs env -u STACK_LIMITS_SNAPSHOT -u CLAUDE_SESSION_ID ~/.claude/venvs/tools/bin/python -m pytest -q < chunkfile`. Then run install_smoke, the hand_off tests, the codex_config suite, and the equilibrium harness from a copy with EQ_CONTAINER_DIR in its own pytest process. Expect only the 7 known environment failures and the 2 known openpty failures in install_smoke.
2. Finish eq-runtime with one main-coder lead, delegating the heavy work:
   - harness tests for p6/p7 and the CLI, the grade files, E_rt with bundle_mismatch and the `candidate` status, and wiring tests;
   - eq_calibrate read_stage skips records that have a branch;
   - merge eqr-hdocs into eqr-harness, run test_calibrate, run `tests/equilibrium_paths.py amend --amendment A6` and get test_equilibrium_paths green;
   - finish the mutation runner on eqr-mut (gen.py, then `tests/eq_mutations.py -j 16`; keep only the gap tests that kill something; ruff; commit; merge), plus mutants for the version-0 rule and the trailer label;
   - fix the two product bugs, each with a test;
   - security-auditor and code-reviewer on main...eq-runtime, then one evidence-gated fix round;
   - merge main into eq-runtime, run the full checks, report READY.
   Use a private UV_CACHE_DIR, because the shared one is corrupt.
3. INTEG: send the integrator `git -C M merge --ff-only eq-runtime`, then a full C10 on main.
4. Codex pages into the GitHub wiki nested repo (WT/wiki-main-fixes/github-wiki, git-ignored github-wiki/ on main). Re-measure the counts, run the wiki checker, review. The user pushes.
5. Final handoff update: rewrite the old sections of HANDOFF_STATE.md (stopped state, §4, §5 user steps) as the current state, fix hand_off/A4_FOLD.md §3 (stale COMPARE_eq.md path), and write WT/.claude-work/resume-1005/FINAL_REPORT.md.
6. Main-only audit: full C10, plus security-auditor and code-reviewer over everything main gained since 73eec41. One fix round.
7. A verifier does a read-only dry run of hand_off/RESET_TO_MAIN.sh (archive list and removals). Nobody runs --archive or --apply.
8. One closing consolidated report with the user's commands.

## Constraints
- Never push; no forge writes. Never run install.sh. No paid `claude` calls. Nobody but the user removes worktrees or branches; list them.
- Agents work in worktrees directly under WT, outside M/.claude/worktrees and outside .claude-work. Merges are fast-forward only through the integrator, one at a time, with a full C10 after each.
- Security surfaces (agent_guard.py, settings.json, install.sh, hooks, eq-wall, lib/eq-*, doctor.sh, agent tool lists) get security-auditor + code-reviewer before merge. Never edit lib/eq-wall files. Never edit /Users/pmrj/.claude.
- mcp-server-craft stays retired. Agents have a soft limit of about 33M tokens per prompt: dispatch fresh leads from plan.md checkpoints rather than long-running ones.

## Carry into the closing report
- Unreviewed one-line COMPARE_c0.md lint exemption.
- The older installer's STACK_HOOK_RE matches script names anywhere in a hook command.
- Unreviewed CLAUDE.md-block fixes (de758d6, 5f37ed0).
- Claude guard git gaps (--upload-pack, filter-branch, difftool -x, ext::).
- A deferred profile (rust or haskell) passed through `--eq-container-profiles` still goes through setup.sh's CLI and service questions before it is skipped.
- A newly added shellcheck SC2015 note in install_smoke.sh.
- Unverified live-session assumptions:
  - the toolsmith excludedCommands and allow-rule behaviour (README live check 8);
  - the instructor deny rule under the sandbox;
  - the Apple pkg signature output;
  - the runtime-eq §13 items, including whether --max-budget-usd on the E_rt leader covers its subagents;
  - the Codex probes in PROBES.md;
  - the distroless rows D1–D9;
  - GitHub rendering of the wiki Home images and Mermaid.

## User-only steps for the closing report
- The reinstall (note the macOS sandbox point about tools/instructor).
- The A4 paid probe and the calibration runs (EQ_CALIBRATION_RUN_PLAN.md; about $740 pilot plus calibration, about $2,448 for the two-class confirmation).
- The container checklist rows C1–C13, C18–C23 and D1–D9. Fill the BASH_* pins with `build.sh --resolve-tools`, and pin CONTAINER_PKG_SIGNER (C18). Core stops at exit 13 until the pins are filled.
- Regenerate the tools lock (network): `uv pip compile requirements/tools.in -o requirements/tools.txt --generate-hashes --python-version 3.13 --python-platform aarch64-apple-darwin --only-binary :all: --exclude-newer 2026-09-22T00:00:00Z`
- The c0 runbook (§12 re-pin), the Codex probes and the optional requirements file, and the wiki push (github-wiki-publish.md).
- Approval or rejection of Stage 3 deferred D1–D5.
- The xcrun cache refresh outside the sandbox (unverified).
- Worktree and branch removal: smokegc-fix, eqcli-integ, the rescue/* branches (including rescue/eq-distroless-8297a8e and rescue/eq-distroless-7f4b50b), and the builders' extra worktrees.
- `RESET_TO_MAIN.sh --archive`, then `--apply` (note --session-wt for orch-bash worktrees).
- The live checks: README "Live checks" and HANDOFF_STATE §5.
