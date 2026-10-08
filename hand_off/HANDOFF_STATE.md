# HANDOFF_STATE: claude-agent-stack, session 8ad965da (2026-10-05, written ~16:30, updated ~16:45 after the stop)

**Current state (2026-10-08, written 01:35): main is `63ab4f04`** (= `be11f4c8` + the 2026-10-07 hand-off text; read with
`git -C M log --oneline -8 main` [v]). Merged and done (the user ran the ff merges): audit-fixes, eq-runtime-2 (A7: H5 removed;
A8: E7 cell pass), docs-reorg, the jsonschema fix, hs-update-1007b. C10 on `be11f4c8` is DONE: the 7 known environment failures
only, install_smoke 280 passed / 2 failed (openpty) (`H/.claude-work/c10/c10-main-be11f4c8.summary`) [v].

**Pending: branch `dot-config`** (tip `9a8ec3db` at 01:34 [v: `git rev-parse`]; 15 commits ahead of main; not merged [v:
`merge-base --is-ancestor`]; worktree `H/.claude-work/dc-main`). It moves the repo to `dot-config/{dot-claude,dot-codex_config,
dot-equilibrium}` with a single installer (`./install.sh`, then `./install.sh --codex`), adds COMPARE_eq A9 ("repository
move"), re-pins `extract_src` `parents[5]`. Reviews done (security-auditor + code-reviewer), fix round applied (incl. the WALL
lookup layout rule). Baseline pre/post equal modulo path prose (`H/.claude-work/dot-config/baseline/DIFF.md`; allowed: 15
Claude files incl. `derive_sched_model.py`, `derive_thresholds.py`, comments in `eq_core`/`eq_isolation`/`eq_policy`, a comment
in `eq_schemas.json`; the stack-budget and stack_sched_refresh repo-layout checks). Full C10 on `02208781` (a coder; `9a8ec3db`
is one commit later, the WALL-lookup fix): `H/.claude-work/c10/c10-dc-02208781.summary` says DONE for the non-pytest steps
[v]; install_smoke 280 / 2 failed (as on main), image_studio 125, instructor 77 (patched copy ok), eq-wall 100 + 2 skipped,
hand_off 40, codex_config 2184 + 1 skipped, harness 638 + 2 skipped, eq_mutations 39/39, moved_paths 108; **`pool_sha` rc=1:
`FAIL dot-config/dot-equilibrium/items/graders/` (PF, RS ok) [v: log]; the cause is unverified and the be11f4c8 summary has no
such step**. The pytest chunks (`c10-dc-02208781.chunks.summary`): aa 2164 passed, ab 1073 passed, ac started 01:30, ad
pending, so the pytest part **was running** at 01:34 (process list unreadable from the sandbox, [unverified]). The first
`pytest.*` lines in the main summary (rc=1, 0 s) look like a runner artefact superseded by the chunk run [unverified].
User steps for it, in order: (1) apply `H/.claude-work/dot-config/check_suite/instructor-dot-config.patch` (3 lines in
`tools/instructor`, a protected path); (2) merge `dot-config` (`git -C M merge --ff-only dot-config`; check the tip first);
(3) reinstall per `H/.claude-work/dot-config/REINSTALL.md` (`./install.sh`, then `./install.sh --codex`); (4) a coder runs C10
on main and adds its HANDOFF_STATE row (§8). Left for the agents until then: the `pool_sha` cause.

Programs (plans saved, §9): SDK optimization, Bayesian tuning, lost-work rescue, side branches awaiting the user (§9).
Environment notes: the sandbox writes only in M and H; agents cannot merge into main (user-run ff merges); the shared uv cache
`/tmp/claude-501/uvcache` is corrupt (`uv run --no-cache`); harness runs need `EQ_AGENTS_DIR` and `EQ_CONTAINER_DIR`; about 132
tests fail on paths when run under `.claude-work`; the 7 known environment ids are in `c10-eqcli-321f037.failed_ids`; the
verifier's hook refuses harness, stack_progress and install runs (use a coder); BlackCat has a 24-tool-call cap per prompt and
the orchestrator a soft token limit near 80M, so checkpoint the `plan.md` files. The stopped-state paragraph below is the
2026-10-05 history; §1-§3 and §8 rows keep their older "as of" dates unless a row says otherwise.

**STOPPED STATE.** At ~16:37 the user ordered every running task stopped except the commit of `hand_off/` to main.
Stopped: the orchestrator (aeb982e2417df4dd0), R3 (main-coder a5a3114a94bceb867), the L1 INTEG (main-coder
a7fae00afc61465ac, mid-C10), `orch-bash` (claude-code-engineer a7ed898c01c4f5a2d) and the reset-script writer (main-coder
acddf3f1fa0c498d5). None should still run (the C10 log stopped growing at 16:37:22; the process list was not readable
from the agent sandbox, so [unverified]). Their branches and worktrees hold unmerged WIP and stay as they are (§2); only the
user removes worktrees. The L1 fixes did reach main, but **C10 on main was interrupted and is not confirmed** (§1).

Supersedes `claude_info/HANDOFF_FULL.md` §0, §6 and §7 where they differ. HANDOFF_FULL remains the reference for R1/R2,
the Stage-4 lever table (§2 R4), the L1 review findings (§4) and older decisions (§5).

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout, repo of record; `hand_off/` is committed on main,
so `M/hand_off/` is the copy to read) · **H** the handoff worktree
`/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb` (branch
`golden/claude-info-handoff-setup-05c3bb`; its git-ignored `.claude-work/` holds the job files) · **WT** `M/.claude/worktrees` · **EQ-T** (new)
`WT/eq-t-1005/.claude-work/equilibrium` · job plan `H/.claude-work/resume-1005/plan.md` · ledger
`/Users/pmrj/.local/state/claude-agent-stack/8ad965da-ee69-47f6-8e8b-40a9d258455f/delegations.md`.
**T** (`next-steps-7c1c7f`) and **S** (`agent-stack-resume-9caddf`) no longer exist.

Key: **[v]** read in a file or git this session · **[r]** from an agent's report or the job plan, not re-run ·
**[unverified]** nobody checked it.

## 1. DONE / merged

State as of 2026-10-07 (main `be11f4c8`; the table cells below were verified at `9852e87`, and everything they call merged is still an ancestor) [v]. Everything below that this section calls merged is an
ancestor of main.

| item | state |
|---|---|
| `main` | `be11f4c8` (was `9852e87` when this table was written; later merges: audit-fixes, eq-runtime-2, docs-reorg, jsonschema fix). `hand_off/` is committed on it; the session-stop commits `7ea9590`, `2aff512`, `69067f6`, `743a7e2`, `ff48d70`, `d955bef` are all below it [v] |
| Installed manifest | commit `73eec41`, an ancestor of main and far behind it (172 commits at `9852e87`, more now). The installed `~/.claude/agents/orchestrator.md` `tools:` line has no `Bash`; M's has `Bash` [v]. Install stays held until the user reinstalls (§5) |
| `orch-bash` | **Merged.** Tip `f5de4f6` is an ancestor of main (§8 lists the older `d534cd4`, also an ancestor). The old WIP state (branch @ `743a7e2`, no commits, main without Bash) is obsolete [v] |
| Other merged branches (all ancestors of main) | `worktree-agent-afb29c2edb383d1dc` @ `2aff512` (L1 follow-ups), `wiki-main-fixes` @ `5be6ab7`, `eq-pins` @ `0781a15`, `eq-track` @ `c0b2d8d` (EQ-T tracked; now `dot-config/dot-equilibrium/`), `eq-cli-install` @ `321f037`, `eq-distroless` @ `fd0a2a3`, `handoff-docs-2` @ `a3653dd`, `l2-final` @ `7c7137d`; R3 is merged as `r3-ready` @ `84ba493`. All 16 SHAs in §8 are ancestors of main [v] |
| R3 old branch | `worktree-agent-a5a3114a94bceb867` @ `60dd3ad` (2 dirty lines) is merged and superseded by `r3-ready` @ `84ba493`; its `STATE.md` "Remaining" list is obsolete [v] |
| C10 on main | **Not confirmed.** The earlier run on `fd0a2a3` is incomplete. Passed there: lint_agents, prompt_budget, guard self-test, stack_progress self-test, bash -n 311/311, image_studio 125, instructor 77, eq-wall 100. Not finished: full pytest (stalled under load), install_smoke, hand_off tests, codex_config, the harness suite. A full C10 on main HEAD is §4 item 0 [r: `NEXT_SESSION_PROMPT.md`] |
| EQ-T | Now at `M/.claude-work/worktrees/eq-t-1005`; main tracks it as `dot-config/dot-equilibrium/` (`eq-track`; moved 2026-10-07). The user-side move command is done [v] |
| T0 isolation backend | Apple `container` 1.5.0 replaces Docker; R3 and the distroless images are merged (§8). Seatbelt/`sandbox-exec` and App Sandbox rejected (researcher aa86e636efb18156d; scout a30dd79402430c2dc) [r] |
| T1g docs check / T1b A4 | `--agent` tools apply to the main thread (`-p` unverified); `--tools` restricts built-ins, `--allowedTools` only auto-approves; only `Read()`/`Edit()` path rules are consulted. A4 amendment in COMPARE_eq (`common_tools = ["Skill"]`, `harness/tests/test_skill_tools_argv.py`) [r] |
| Reset directory | `M/.claude-work/resume-1005/reset` is absent; the reset script was built instead as `hand_off/RESET_TO_MAIN.sh` (§8 item 10) [v] |
| Audit files | `R/.claude-work/resume-1005/worktree-cleanup.md`, `t-loss.md`, `unused-folders.md` (read-only inventories; their T and S rows are obsolete) [v: R = `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728`] |

## 2. NOT merged / still open (the 2026-10-05 stop is over; the old agent ids are dead)

State read 2026-10-07 with git [v]. R = `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728`. Nobody resumes
old agents; the next builders get fresh briefs from the files named here.

| branch | tip | ahead of main | state |
|---|---|---|---|
| `eq-runtime` | `b595c3c` | 24 | settings hooks, decisions b-e; not merged, not finished (§4 item 11) |
| `eqr-hdocs` | `7c1702d` | 28 | schema v0, docs; not merged |
| `eqr-harness` | `61f82b4` | 28 | not green: p6/p7, E_rt and LOO wiring untested; not merged |
| `eqr-mut` | `b4df8df` | 23 | dirty: untracked `tests/test_eq_gaps.py` (plus scratch `.claude-work/mut/`: gen.py, runner_head.py, runner_tail.py, disc*.jsonl) |

The worktrees `eq-runtime`, `eqr-harness`, `eqr-hdocs`, `eqr-mut` live under R, with `smokegc-fix`, `eqcli-integ` and
`wiki-main-fixes/github-wiki`. Known product bugs, unfixed: `eq_guard.py:978` (`VALUE_OPTS` holds upper-case options but
`command_words` compares the lower-cased word, so `env -C . git commit -m x` and `xargs -I X git commit ...` pass for an eq
member; a strict xfail test sits in `test_eq_gaps.py`) and `eq_policy.py` `resolve` (`over_cap` is always False, so the
over-cap confirm mode never fires). Settled decisions: `hand_off/NEXT_SESSION_PROMPT.md`.

Gone from the first write of this file (obsolete): the stopped agents (orchestrator, R3, L1 INTEG, `orch-bash`, reset-script
writer), R3's WIP list, and EQ-T's pre-move location. Their results are in §1 and §8.

## 3. MISSING / LOST

Worktrees T and S were removed at ~16:12 on 2026-10-05, including their git-ignored `.claude-work/`. Cause unknown; no
copy in the Trash was checkable (sandbox) and none found on disk. **User decision: re-derive, no recovery.** Details per
item: `H/.claude-work/resume-1005/t-loss.md`.

| lost | re-derive from |
|---|---|
| one-tree `AUDIT.tsv` (112 rows) + `ONE_TREE.sh` draft | live git; `worktree-cleanup.md`, `wtlist.txt`, `rows1.txt` in `H/.claude-work/resume-1005/` |
| `context-diet/RUNBOOK_c0.md` | HANDOFF_FULL §8 outline (A reinstall a22c5b4 in a throwaway clone, B verify, collect c0 17 prompts with `freeze.sh --arm c0`, C back to main); `M/claude_next_steps/work_carried/context-diet/` (COMPARE_c0, freeze.sh, c0_check.sh); template `work_carried/compact-protocol/measurement/RUNBOOK_A_ARM.md` |
| next-steps `plan.md` ledger, `STAGE4.md` (L1-L10 specs), `R5_MAP.md`, `staged/` (NEXT_STEPS, DECISIONS, CHANGES) | HANDOFF_FULL; commits d955bef b6e05d6 2ebc26f deea4d5; `claude_info/s4_outputs/`; R5 maps by re-running explore |
| `s4-l5/` DESIGN.md + `agent_guard.patch` + `install.patch` | branch `s4-l5-budget` @ `2ebc26f` (code survives); patches re-written by the L5 builder |
| `s4-l7-l10/MECHANISMS.md` | HANDOFF_FULL lines 80 and 126 (B1/B2/B3 outline); if insufficient, ASK USER before building |
| S `r3/` patches + STATE.md, `wrapup/c10.sh` | R3 builder's own STATE.md/plan.md; C10 command line in HANDOFF_FULL §1 item 10 |

Survivors: EQ-T (snapshot + restored `WT/eq-t-1005`), `claude_info/s4_outputs/` (s4-instructor, s4-l2, s4-l7-l10 without
MECHANISMS, s4-l9), `M/claude_next_steps/work_carried/context-diet/`, git commits `2ebc26f`, `deea4d5`, `b6e05d6`, `d955bef`.

`skill-removals.md` is at `M/.claude-work/resume-1005/skill-removals.md` (15:18), not under H [v]. Not found:
`H/.claude-work/resume-1005/orch-bash.md`; the reset-script files (§2). New since the first write:
`H/.claude-work/resume-1005/unused-folders.md` (verifier a1838258f061311ce, read-only inventory of clutter folders in M).

## 4. LEFT TO DO (in order; serialized merges, C10 on main after each; one INTEG at a time)

| # | task | state / owner |
|---|---|---|
| 0 | Full C10 on main HEAD (`9852e87` or later). The run on `fd0a2a3` was incomplete (§1) | **done** on `8912496` (2026-10-07): pytest failures = the 7 known environment ids only, install_smoke 280 passed 2 failed (the known openpty pair), image_studio 125, instructor 77, eq-wall 100 + 2 skipped, hand_off 40, codex_config 2068 + 1 skipped, equilibrium harness 451 + 1 skipped (`H/.claude-work/c10/c10-main-8912496.summary`) [v] |
| 1 | `orch-bash` post-merge audit | folded into item 15 (user's choice) |
| 2 | L1 follow-ups | done: `worktree-agent-afb29c2edb383d1dc`@`2aff512` (§1) |
| 3 | R3 `container` port | done: `r3-ready`@`84ba493` via r3-merge (§8) |
| 4 | L2 output | done: `l2-final`@`7c7137d` (§8) |
| 5 | Installer-managed CLAUDE.md block | done: `claude-md-block`@`485b855` via cmb-integ (§8) |
| 6 | Instructor | done: `s4-instructor`@`cf8cf68` via instr-integ (§8) |
| 7 | L5 observe-only | done: `l5-land`@`6d9713a` via l5-integ (§8) |
| 8 | L7 B1 + B3, L10 | done: `l7-mech`@`a05d508` via l7-integ (§8) |
| 9 | Stage 3 quality pass | done: `s3-integ`@`b1a0703` via s3-ff; deferred D1-D5 need the user's approval (§8) |
| 10 | `RESET_TO_MAIN.sh` | built: `reset-to-main`@`76e1cd4` via rtm-integ (§8); only a dry run is left (item 16) |
| 11 | Finish `eq-runtime` per `M/hand_off/NEXT_SESSION_PROMPT.md` step 2: harness tests for p6/p7 and the CLI, grade files, E_rt with `bundle_mismatch` and `candidate`, wiring tests; `eq_calibrate` `read_stage` skips records with a branch; merge `eqr-hdocs` into `eqr-harness`, `test_calibrate`, `equilibrium_paths.py amend --amendment A6`; finish the mutation runner on `eqr-mut` (keep only gap tests that kill something); fix the two product bugs (`eq_guard.py:978`, `eq_policy.py` `over_cap`), each with a test; security-auditor + code-reviewer on `main...eq-runtime`, one fix round; merge main into `eq-runtime`; report READY. Private `UV_CACHE_DIR` (the shared one is corrupt) | **done and merged:** `eq-runtime-2` is in main at `258d3a35` (A7 H5 removed, A8 E7 cell pass; harness mutations regenerated: 183 mutants, all killed); C10 on `be11f4c8` is done (`H/.claude-work/c10/c10-main-be11f4c8.summary`). History: `eq-runtime-2`@`1876a6b` (base main `8912496`; built from `eq-runtime` `b595c3c` with `eqr-harness-2`@`1d99b44` and `eqr-mut-2`@`6880fc7`): harness p6/p7/CLI/E_rt/wiring tests, both product bugs fixed with tests, the 792-mutant runner, A6 (`64e2c44`), run plan (`3a85b08`); security-auditor PASS, code-reviewer pass-with-fixes, fixed in `9c870d7`; phase B: harness 622 passed 2 skipped, harness mutants 168/168, calibrate mutants 56/56, `tests/eq_mutations.py` 792/792 killed. Its full C10 is pending. Blocked on your merges (§5); `audit-fixes` is not merged into it [v: git; r: resume-1007 plan]. §7 questions 1-2 answered 2026-10-07 (§6 items 16-17): A7 and A8 are on `eq-runtime-2` after `7c8a8397` |
| 12 | `eq-runtime` INTEG: `git -C M merge --ff-only eq-runtime`, then full C10 on main | **done** (merged by the user; full C10 on `be11f4c8` done). Was: **pending, yours** (§5 step 2, branch `eq-runtime-2`): agents' merges are refused by the auto-mode classifier ("Modify Shared Resources"); then a full C10 on main |
| 13 | Codex pages into `R/wiki-main-fixes/github-wiki` (nested repo; the user pushes): re-measure counts, run the wiki checker, review | **pushed** to `pmrjge/blackcat.wiki`; a wiki `docs-reorg` branch is pending the user's merge (§5 step 3). Earlier: **staged for you** (R is read-only to agents): 21 pages, `wiki.patch` 14 files (12 changed, 2 new), counts re-measured on main `8912496`, `wiki_check` 0 problems, code-reviewer accuracy pass-with-fixes (fixed); `H/.claude-work/resume-1005/resume-1007/T13` with `APPLY.md` (§5 step 3) [r] |
| 14 | Final handoff update (A4_FOLD.md §3 path; `H/.claude-work/resume-1005/FINAL_REPORT.md`) | **done**: this update (2026-10-07, main `be11f4c8`). Earlier: on `audit-fixes` (the commit after `962b4b5c`): §4, §5, §7; A4_FOLD.md §3 now points at the tracked `dot-config/dot-equilibrium/COMPARE_eq.md` |
| 15 | Main-only audit `73eec41..main`: security-auditor + code-reviewer, includes the `orch-bash` Bash/git-guard gaps; then full C10; one fix round | **done and merged** (`ad10c9ba` is in main). Was: `audit-fixes`@`962b4b5c` (base `8912496`; fixes `1416bcb`..`a10ef8e4`, §8 row 15): no-push git gaps in both guards (`ext::`, command-running option values, `--shallow-file`, bundled short options, clone `-c`), web check, STACK_HOOK_RE, deferred profile, dead code, option case; three review rounds (security-auditor + code-reviewer), the last round's findings fixed with proofs. C10 on the tip in a detached worktree: every suite as on main (codex_config 2171 + 1 skipped, harness 451 + 1 skipped), pytest 139 failed = the 7 known + 132 attributed to the `.claude-work` path (129 `test_readonly_agents`, 3 `test_agent_guard` lake_env); the same-path check on `8912496` was still running at this write. [v: git; r: C10 logs `H/.claude-work/c10/`] |
| 16 | `RESET_TO_MAIN.sh` dry run only (`--archive` and `--apply` are the user's) | **dry run done** on main `8912496` (by a coder: the verifier's read-only hook refused the script): rc 0, worktrees, branches, stash and status identical before and after; plan 114 worktrees (108 remove, 5 skip, 1 keep), 147 branches (142 delete), bundles for the unmerged ones; `H/.claude-work/resume-1005/resume-1007/T16/dryrun.txt`. Run it again before `--archive`/`--apply` (the user's) [r] |
| 17 | Closing report; the reinstall notice goes here only (the user runs `install.sh`) | **final** at `H/.claude-work/resume-1005/FINAL_REPORT.md` (2026-10-07, main `be11f4c8`); the reinstall notice is there and in §5 |
| 18 | A4 fold into COMPARE_eq A4 item 4, after the user's paid probe (§5) | python-engineer |

Deferred: oracle residuals (HANDOFF_FULL §6.1), §6.10 items, Stage 3 D1-D5.

## 5. USER STEPS

### Merges and closing steps (job resume-1007, 2026-10-07; status at `be11f4c8`)

Steps 1-2 below are DONE (the user ran the ff merges of `audit-fixes` and `eq-runtime-2`; main is `be11f4c8`, C10 done). Still open: step 3 (wiki), step 4 (`disc3.py`), step 5 (reset dry run) and the reinstall. The text of steps 1-2 is kept as history.

Every `git merge` an agent tried this job (the ff of main, and a merge inside a `.claude-work` worktree) was refused by
the auto-mode classifier ("Modify Shared Resources"), so the merges are yours. main is `8912496`; M must be clean.
Agents can still commit, test and review between your steps.

1. Fast-forward main to the audit fix round (§4 item 15). Its C10 ran on `962b4b5c` (§4); the one commit after it
   changes `hand_off/` docs only.

```bash
git -C /Users/pmrj/ZDone/claude-agent-stack merge --ff-only audit-fixes
```

2. eq-runtime (§4 items 11-12), after you answer §7 questions 1-2 (if E7 is fixed now, the fix lands on `eq-runtime-2`
   first). Bring the new main into the branch:

```bash
git -C /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb/.claude-work/eq-runtime-2 merge main
```

   Since `8912496` both branches change `dot-config/dot-claude/hooks/agent_guard.py`, `install.sh`, `hand_off/HANDOFF_STATE.md`,
   `tests/test_install_state.py` and `tests/test_toolsmith.py`, so the merge may conflict [unverified: nobody attempted
   it]. On a conflict run the same command with `merge --abort`, or let a main-coder resolve it; a conflict resolved in
   `agent_guard.py` or `install.sh` is a security-surface change (security-auditor + code-reviewer before the ff). Then a
   main-coder runs the targeted tests and commits the item 11 row in §8 on the branch, and a coder runs its full C10.
   Then:

```bash
git -C /Users/pmrj/ZDone/claude-agent-stack merge --ff-only eq-runtime-2
```

   A full C10 on main follows (a coder; template `H/.claude-work/c10/c10-af-962b4b5.sh`).

3. Wiki (§4 item 13): the pages are pushed to `pmrjge/blackcat.wiki`; merge the wiki `docs-reorg` branch and push it (yours). The older staged-pages route was: apply as `H/.claude-work/resume-1005/resume-1007/T13/APPLY.md` says (check,
   copy, check, commit in the nested wiki repository under R; pushing is yours).

4. Stop the orphan `disc3.py` from the old `eqr-mut` mutation run (agent sandboxes cannot run `pgrep` or `pkill`):

```bash
pgrep -fl disc3.py
```

```bash
pkill -f disc3.py
```

5. After the merges, run the `hand_off/RESET_TO_MAIN.sh` dry run again (§4 item 16); `--archive` and `--apply` stay
   yours. The worktrees and branches this job created are listed in `H/.claude-work/resume-1005/FINAL_REPORT.md`.

### Earlier steps (2026-10-05/06)

Reinstall (ends the install hold; the installed manifest `73eec41` is far behind main `be11f4c8` and its orchestrator has no
`Bash`). Conditions are met: C10 passed on `be11f4c8` and the closing report (§4 item 17) says so. You reinstall `./install.sh` at the very end, after the other user steps; after the dot-config merge follow `H/.claude-work/dot-config/REINSTALL.md` (`./install.sh`, then `./install.sh --codex`) (single installer). The venv sync of `./install.sh` also clears the `jsonschema` venv mismatch. `orch-bash` is
already merged. `eq-runtime` adds settings hooks, so after it merges a **second reinstall** follows. The `tools/instructor`
deny rule (`Edit(//**/tools/instructor/**)`, also joined to the sandbox denyWrite on macOS) makes sandboxed git writes to a
`tools/instructor` path fail after a reinstall. Agents never run `install.sh`. Quit every Claude Code session first.

```bash
git -C /Users/pmrj/ZDone/claude-agent-stack log --oneline -3
```

```bash
grep -n '^tools:' /Users/pmrj/ZDone/claude-agent-stack/dot-config/dot-claude/agents/orchestrator.md
```

```bash
cd /Users/pmrj/ZDone/claude-agent-stack
```

```bash
./install.sh --dry-run
```

```bash
./install.sh --yes
```

```bash
grep -n '^tools:' ~/.claude/agents/orchestrator.md
```

Undo (backups in `~/.local/state/claude-agent-stack-backups`):

```bash
./install.sh --restore
```

Paid probe for A4 (consent given: one call, hard cap $0.25). Run it yourself from a normal logged-in terminal (agent
sandboxes have no `claude` login). Not run yet. Afterwards brief a fresh python-engineer with the output file path and
COMPARE_eq A4; it strips credentials and folds the result into A4 item 4 (§4 item 18). EQ-T is at
`M/.claude-work/worktrees/eq-t-1005`.

```bash
P=/Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium/probes; mkdir -p "$P"; TS=$(date -u +%Y%m%dT%H%M%SZ); cd "$(mktemp -d)" && printf 'List the exact names of every tool you can call, then return them.\n' | claude -p --agent writer --model sonnet --max-budget-usd 0.25 --json-schema '{"type":"object","properties":{"tools":{"type":"array","items":{"type":"string"}}},"required":["tools"],"additionalProperties":false}' --output-format stream-json --verbose --permission-mode acceptEdits --disallowedTools Agent WebSearch WebFetch --strict-mcp-config --tools Read,Skill,StructuredOutput --allowedTools Read Skill > "$P/a4-probe-$TS.json" 2> "$P/a4-probe-$TS.err"; echo "exit=$?" >> "$P/a4-probe-$TS.err"
```

Container steps (C14-C23, D1-D9) are in `hand_off/R3_CONTAINER_CHECKLIST.md`; the default `core` set still stops at exit 13
until the placeholder pins are filled.

Worktrees: agents create theirs directly under R (`/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728`)
or H's `.claude-work`; worktrees under `M/.claude-work` are refused by the Edit hook (`R/.claude-work/resume-1005/COMMON.md:15`).
Cleanup commands: `R/.claude-work/resume-1005/worktree-cleanup.md` (its T and S rows are obsolete). Keep the four unmerged
`eq*` worktrees (§2), EQ-T and H until their work is merged or archived (§4 item 16); the merged `afb29c2…` and `a5a3114…`
worktrees are safe to remove, by you. Nobody but you removes worktrees.

`protocol-p1` worktree (in W, rebase stopped on a CONFIG.md conflict): continue, abort or archive: your call (HANDOFF_FULL §2 R5).

### Runtime Equilibrium: your checks (eq-runtime; nothing here is live-verified)

After the integrator merges eq-runtime and C10 passes on main (quit every Claude Code session first):

```bash
./install.sh --dry-run
```

```bash
./install.sh --yes
```

```bash
bash ~/.claude/bin/doctor.sh
```

Read the section "Equilibrium runtime": files installed (10), params pin matches the manifest, no class validated yet, knobs, W3 level `sandbox`. Then the live checks, one row each in README "Live checks" 9 (how to run it, what you should see, and what happens if it fails: every one fails closed):

| # | check (spec §13) | if it fails |
|---|---|---|
| 1 | the sandbox runs `stack-eq` unsandboxed (`/sandbox` lists `stack-eq *`) | the store write fails at `plan`: no run, no spend |
| 2 | Bash exit status is in PostToolUse `tool_response` (`exit_source` in `check-c<i>.json`) | Level 1 verdicts become `unverifiable`: no candidate marked passing |
| 3 | the AskUserQuestion result shape on the main thread (`consent/<run8>.json`, `source: ask`) | the relay and `stack-eq start` are refused: the run does not start |
| 4 | a resumed member keeps its worktree cwd (`members.json`) | reconcile and repair rounds refused: round-0 answers only |
| 5 | a full model id passes through the spawn gate (`r0/m<i>.json` `model`, `model_drift`) | the alias is used and `model_drift` recorded: labelled, never validated |
| 6 | the leader's transcript token (`eq <run8> m1/N` or the substituted text) | no behaviour change; decides which copy a reviewer reads |
| 7 | the member worktree path in SubagentStop (`members.json` `cwd`) | the member reports `pwd`, cross-checked against `.claude/worktrees/` |
| 8 | headless leader (background resumes, hooks, `--fork-session`, `--max-budget-usd`) | paid smoke in `EQ_CALIBRATION_RUN_PLAN.md`; headless mode stays unused |
| 9 | Level 2: `R3_CONTAINER_CHECKLIST.md` C14-C17 | `STACK_EQ_WALL=auto` stays at Level 1; `required` refuses runs with a check |

Paid calibration (not started; needs your approval of every step and a hard ceiling): `hand_off/EQ_CALIBRATION_RUN_PLAN.md`. A class turns `validated` only when the committed `eq_params.json` carries it and you reinstall.

Undo: `./install.sh --restore` (the manifest's `eq_runtime` and the staged files go back together).

## 6. DECISIONS made this session (USER; do not re-ask)

1. Isolation backend: Apple `container` 1.5.0; Docker dropped. c0 and the Docker runbook: the user runs c0 (stated
   this session; whether it was run: unverified, `RUNBOOK_c0.md` is lost, item 11); the Docker part is dropped.
2. Image choices. SUPERSEDED 2026-10-06 by the distroless decisions below: ~~Debian packages for bash/perl/jq/busybox; Scala 3
   release tarball; MongoDB out (PostgreSQL profile also dropped by R3: its only runner was compose); `cc` linker in the
   Rust/Haskell images.~~ (Scala 3 from the release tarball and MongoDB/PostgreSQL out still stand.)
   2026-10-06 (USER; implemented on branch `eq-distroless`, `lib/eq-container/DESIGN_DISTROLESS.md`): (1) bash: static GNU bash
   5.3 + patches 001-020 built from the GPG-signed source in a pinned Alpine builder stage (`tc/build-bash.sh`, key
   7C0135FB088AAF6C66C650B9BB5869F064EA74AB enforced), output pinned. (2) perl: none; the in-repo `minimal/perl-shim` answers only
   `check_lean.sh`'s timeout wrapper (`check_lean.sh` and the PF pool unchanged). (3) CP/CR: distroless cc + the glibc
   python-build-standalone Python. (4) The Debian `full` image and `STACK_EQ_CONTAINER_SET=full`: removed. (5) Rust and Haskell
   deferred (profiles exit 10 with a reason); node, julia, jvm on distroless cc, go on scratch. (6) jq: the official static jq
   1.8.2; busybox: docker-library's musl build; uv: static musl 0.12.22. No Debian, apt or dpkg in any final image or in the
   build path; every final image is FROM the digest-pinned `gcr.io/distroless/cc-debian13` or scratch.
3. Oracle residuals (§6.1) deferred; §6.10 deferred.
4. `mcp-server-craft` stays retired (`e045482`); do not restore.
5. Plugin autoUpdate for claude-plugins-official: keep on.
6. Stage 4 build threshold confirmed: 3% pooled, 2% per class, 4 of 5 sessions.
7. SendMessage-resume rule: restrict. Subagent cache TTL: keep the default. `omitClaudeMd`: measure offline first.
8. R3 merges after its reviews with the install still held; the user reinstalls next session.
9. L10 side commit: yes.
10. ONE_TREE default: archive unique-commit rows as git bundles; dry-run only; never `--apply` by an agent.
11. A4 paid probe approved (one call, ≤ $0.25); logged-in or paid `claude` steps are user steps.
12. T/S loss: re-derive, no recovery.
13. Nobody but the user removes worktrees (INTEG step "remove worktree" becomes "list for the user").
14. Hand-made worktrees go under `M/.claude-work/worktrees/<name>`; harness `isolation: "worktree"` worktrees stay in `M/.claude/worktrees`.
15. Orchestrator gets `Bash` (branch `orch-bash`), effective after review, merge and the user's reinstall.
16. 2026-10-07: H5 leaves the pre-registration (`dot-config/dot-equilibrium/COMPARE_eq.md` §12 A7; no other hypothesis changes).
17. 2026-10-07: `eq_check.sh` E7 gets a cell-pass rule now, on `eq-runtime-2` (`COMPARE_eq.md` §12 A8; no hypothesis
    changes). The run plan's later calibration amendments become A9 (pilot) and A10 (confirmation).

Standing constraints (unchanged, HANDOFF_FULL §1): never push, no forge writes; agents never run `install.sh`; no paid
runs without consent; no Haiku; security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*,
doctor.sh, agent definitions' tool lists) get security-auditor + code-reviewer before merge; own worktree only; serialize
agent_guard.py / settings.json / install.sh / blackcat.md; uv for Python; C10 on main after every merge. Agent Bash
sandboxes write only their own worktree, `$TMPDIR` and M; no `claude` login inside them.

## 7. OPEN questions / unverified

Open for you (job resume-1007, 2026-10-07; details `H/.claude-work/resume-1005/resume-1007/plan.md`, "Session 2"):

1. **Answered 2026-10-07: (a), H5 removed** (§6 item 16; `COMPARE_eq.md` §12 A7 on `eq-runtime-2`). The question was:
   **H5's forked `none` branch at stage q.** Your decision (a) was: replace it with the correct branch, else ask. No
   correct branch exists: E_rt has no fork code, p7 is the only `none` fork and is refused at q, and reusing stage-p data
   is ruled out by `dot-config/dot-equilibrium/COMPARE_eq.md` §12 A6 item 7 on `eq-runtime-2` (every q claim is tested on items
   disjoint from p). q is blocked until this is settled
   (`hand_off/EQ_CALIBRATION_RUN_PLAN.md` on `eq-runtime-2`, "Open, blocks q"). Options: (a) remove H5's `none` branch from
   the pre-registration by a new dated §12 amendment (agents never remove it on their own); (b) keep H5 and have a q
   `none` fork built first (new harness and E_rt work, its own review).
2. **Answered 2026-10-07: (a), fixed now** (§6 item 17; `COMPARE_eq.md` §12 A8 on `eq-runtime-2`). The question was:
   **`eq_check.sh` E7 refuses every stage-p cell pass** (`run --stage p --cells p6,p7`): it blocks run plan steps 3, 5
   and 6 (proof: `H/.claude-work/resume-1005/resume-1007/S2a/test_s2a_probe.py`). The fix is scoped: an optional `cells`
   argument passed from `eq_harness.py` (its `eq_check.sh` call, line 4618 on `eq-runtime-2`), the started-calls test counting only
   calls with no cell, `test_shell` cases, a new mutant, path-pin regeneration, and a new dated §12 amendment because the
   frozen §5 wording of E7 changes (`COMPARE_eq.md` line 135; the run plan reserves A7 and A8 for pilot and
   confirmation, so the id is yours to set). Options: (a) fix it now on `eq-runtime-2`, before step 2 of §5; (b) merge
   `eq-runtime-2` as it is and fix it later (steps 3, 5 and 6 stay blocked; nothing paid runs before them).
3. **The merges** (§5 steps 1-2): (a) you run the commands; (b) you let an agent run them in a session whose
   permissions allow it.
4. **`disc3.py`** (§5 step 4): (a) `pkill -f disc3.py`; (b) leave it running (it adds load to every C10).

- `container` flags: VERIFIED by the user's `container run --help` output (relayed to R3). Present: `--rm --read-only
  --cap-drop --init --user --uid --gid -m -c --ulimit --tmpfs <path> --mount ...,readonly -w --name --network`. Absent:
  `--pids-limit`, `--security-opt` (`--ulimit nproc=512` is the substitute). `--network none` is not in the help but works
  per the user's spike.
- Still unverified: `--tmpfs` `size=`/`mode=` sub-options; the digest field path (`image inspect` top-level keys are
  `configuration`, `id`, `variants`, with no `digest` key); whether R3's fake-container tests match the real CLI.
- Paid probe: not yet run (command in §5).
- Answered at the stop (§1, §2): the L1 fixes are merged; `orch-bash` has no commit and no review; R3 committed two WIP
  commits and left `lib.sh` + the fake CLI uncommitted; no reset-script files exist.
- C10 on main: the run on `2aff512` was interrupted at ~8 % of pytest, so the L1 follow-up code (`69067f6`, test
  tooling only) has no confirmed C10 on main.
- EQ-T snapshot completeness: no original T listing to diff against; any `runs/` dirs in T are not in the snapshot.
- A4 item 4: `--json-schema` answer under `--tools`; `--agent` frontmatter tools ∩ `--tools` under `-p`; `--settings`
  cannot widen the list; `Skill` loads under `--strict-mcp-config`. All need the paid probe.
- Cause of the T/S removal (some other session or a cleanup run): unknown.
- The `explore` user-command list (aff29c92b53acef18) was not found in a file.

## 8. Progress, session resume-770728

Live plan: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728/.claude-work/resume-1005/plan.md

Status 2026-10-07 [v: git]: all 16 branch@sha cells below are ancestors of main `9852e87`; tips newer than the SHA first listed are named in the cell. "C10 on main: see plan.md" and "READY" are the state at each merge; the full C10 on main HEAD is still pending (§4 item 0). Not merged: `eq-runtime` `b595c3c`, `eqr-hdocs` `7c1702d`, `eqr-harness` `61f82b4`, `eqr-mut` `b4df8df` (§2).

| item | result | branch@sha | C10 |
|---|---|---|---|
| 1 orch-bash | orchestrator holds Bash with the T1 web check (bash -c/eval/find -exec unwrapped, stdin-fed shells refused, linear -c regex); 1571 targeted tests pass | orch-bash@f5de4f6 (merged; d534cd4 is an older ancestor) | C10 on main: see plan.md |
| 11+12 handoff-docs | RUNBOOK_c0 (+§12 re-pin for clone install), A4_FOLD.md, a4_fold.py (8 tests pass), c0_support/ merged; reviewer not run (no spawn tool) | handoff-docs-2@a3653dd (merged; dd8ceb6 is an older ancestor) | C10 on main: see plan.md |
| 4 L2 output | output_shrink PostToolUse `Bash\|Read` hook in shadow mode (logs only; `STACK_OUTPUT_SHRINK=on` cuts), 3 patches unchanged + install/doctor wiring, docs, read_family, review fixes (persisted Bash skipped, Read note line numbers only, ranged-Read paging); 114 tests, 63/63 mutants; security-auditor + code-reviewer applied | l2-final@7c7137d (merged; 0b87cbd is an older ancestor) | C10 on main: see plan.md |
| 3 R3 container | Apple `container` 1.5.0 port: `lib/eq-container` (driver, builds, probes, `eqc_json.py`) + `lib/eq-wall`; `install.sh --with-eq-container` (steps 10b/10c, opt-in, never fatal); WALL deny rules and protected paths on every install; docs; `R3_CONTAINER_CHECKLIST` (C1-C13, user-run); security-auditor (S1-S3) + code-reviewer (R1-R6) fixes applied in `84ba493`. After merging main `7c7137d` (conflict: CONFIG.md §9 changelog, both entries kept): 7 targeted test files 939 passed, `lib/eq-wall/tests` 100 passed 2 skipped, EQ-T harness from a `$TMPDIR` copy 435 passed 4 skipped and 439 passed with `EQ_CONTAINER_DIR` (EQ-T unchanged) | r3-ready@84ba493 via r3-merge | C10 on main: see plan.md |
| 3D agents/skills | rigger-animator, sculptor-painter, procedural-3d-ui (cg-artist's tools; not in `READ_GATE_EXEMPT_VISUAL`) + 7 skills (hub `3d-animation`; modules `character-rigging`, `organic-sculpting`, `udim-texture-painting`, `procedural-3d-workflows`, `3d-ux-design`, `3d-interface-engineering`); guard rosters; prompt_budget gates agent_listing 0.98, blackcat_listing 1.03 (re-measured after merging main 55ab160: 14,740 chars = 0.9615 / 1.0131 of base, gates kept). code-reviewer (5 fixes) + security-auditor (static PASS). After merging main (conflict: CONFIG.md §9 changelog, both entries kept): lint_agents ok, prompt_budget --check ok, guard self-test ok, 6 targeted test files 365 passed, 11 roster-adjacent files 1340 passed, ruff E9,F clean on the changed files bar a pre-existing F841 in `tests/derive_thresholds.py:413` (also on main) | 3d-agents@41e2aae via 3d-merge | C10 on main: see plan.md |
| 7 L5 observe-only | `hooks/stack_progress.py` (port of `2ebc26f`): a subagent brief's `budget:` line and its run shape give signals budget, stall, stop, recovered in `<session>/early-stop.jsonl`; `STACK_EARLY_STOP=observe` (default) \| warn \| off; never a refusal. The 2 lost patches re-derived: `agent_guard.py` `progress_check()` at the end of `budget_gate()` for subagent calls after every hard gate (soft limit as the default budget; errors fail open), `install.sh` stages/tracks/precompiles it, `doctor.sh` checks its bytecode. security-auditor: CRITICAL ReDoS (TOKENS_RE, CALLS_RE, STATUS_RE, 17-39 s per line) fixed by linear parsing and bounded digit runs, 7 linearity proofs; code-reviewer fixes applied (`d4d391a`). After merging main `2750bca` (conflict: CONFIG.md §9 changelog, both entries kept): `tests/test_stack_progress.py` 104 passed, `stack_progress.py --self-test` ok | l5-land@6d9713a via l5-integ | C10 on main: see plan.md |
| 5 CLAUDE.md block | Installer-managed block in `~/.claude/CLAUDE.md` (USER: keep the one-line pointer template `dot-claude/CLAUDE.block.md`): `lib/claude_md_block.py` creates, appends, updates in place or retracts only the lines between its begin/end markers; every byte outside them kept (CRLF, BOM, no final newline); a symlinked, non-regular, read-only, non-UTF-8 or malformed-marker file is skipped with a note; manifest key `claude_md_block`; `--diff` area `CLAUDE.md block`; `--restore` byte-exact; prompt_budget counts it per spawn. security-auditor + code-reviewer fixes in `de758d6` (a directory named CLAUDE.md, plan reason, `--diff` non-UTF-8). Re-review of `b367f0b..485b855` (code-reviewer): pass with 2 fixes in `5f37ed0` (read-only file aborted install: MEDIUM; `--restore` rmtree'd a directory named CLAUDE.md: LOW), 3 proof tests failed before and pass after. After merging main `1e678ec` (conflict: CONFIG.md §9 changelog, both entries kept): 7 install test files 177 passed, lint_agents, prompt_budget --check, guard and stack_progress self-tests ok, bash -n 21 ok | claude-md-block@485b855 via cmb-integ | C10 on main: see plan.md |
| 6 instructor | Deterministic instructor: `tools/instructor/justfile` (dispatcher only: positional `"$@"`, no backticks, variables or dependencies) + PEP 723 scripts under `tools/instructor/bin/` run by `uv run --no-config`: `check-suite` (C10, one pytest per directory: the conftest collision), `ff-merge` (in-process flock, update-ref CAS, read-tree sync, then C10), `worktree-audit` (report only); one stdout status line, exit 0/1/2/3. Wiring: one Bash allow rule per recipe + exact `--list`; guard protect spec `tools/instructor` (any depth); `just` in the DEPS batch. USER: absolute deny `Edit(//**/tools/instructor/**)` (every tools/instructor on the machine; on macOS it also joins the sandbox denyWrite, so after the reinstall a sandboxed git command that writes a tools/instructor path fails). security-auditor HIGH (`.python-version` picked the recipes' interpreter) fixed by `--no-config` (`7ae94f1`); code-reviewer F1-F4 (`d05c154`); code-reviewer PASS on `c89bf07`. After merging main `71a43ef`: `tools/instructor/tests` 77 passed (own run), 7 wiring/settings/permission/protected-path/guard files 1013 passed 1 skipped, lint_agents, prompt_budget --check, guard and stack_progress self-tests ok, bash -n 21 ok, ruff E9,F clean on the changed files bar a pre-existing F401 (`tempfile`) in `tests/test_protected_paths.py:18` (also on main) | s4-instructor@cf8cf68 via instr-integ | C10 on main: see plan.md |
| toolsmith | New agent `toolsmith` (Sonnet leaf, Read/Bash/Skill, acceptEdits, 60 turns, lookup pool) and its executor `bin/stack-install` with `hooks/toolsmith_policy.py`: brew formulae, uv tools, npm/pnpm globals, cargo and go installs within the vetting (min age `STACK_TOOLSMITH_MIN_AGE_DAYS`=7), anything else waits for the user's typed `stack-install approve`; ledger with the uninstall command. `settings.json`: `sandbox.excludedCommands` = the executor only, allow `Bash(__CLAUDE_DIR__/bin/stack-install *)`; guard `toolsmith_gate` (one-use tickets, `INSTALLER_TYPES`); spawned by BlackCat, orchestrator, main-coder, ninja-coder, devops-engineer. security-auditor (FAIL, all findings fixed with proofs) + code-reviewer (pass-with-fixes) in `7bdd370`; branch suite from a fresh clone 5073 passed 2 skipped. After merging main `84bdf0f` (conflicts: CONFIG.md §9 changelog, README commands table, settings.json allow list: both sides kept): the two sides' tests each pinned the Bash allow list to their own rules (3 failed), now both pin the union (`81cdd7b`); 6 toolsmith/permission/instructor/protected-path/devtools/README files 961 passed 1 skipped, guard + install-state/hardening/config-dir 404 passed, `tools/instructor/tests` 77 passed, lint_agents, prompt_budget --check (agent_listing 0.972, blackcat_listing 1.024 of base: gates kept), guard and stack_progress self-tests ok, bash -n 21 ok, ruff E9,F clean bar the pre-existing F841 in `tests/derive_thresholds.py:413` | toolsmith@2ec6e2c via ts-integ | C10 on main: see plan.md |
| 10 RESET_TO_MAIN.sh (built; the dry run and `--archive`/`--apply` are the user's) | `hand_off/RESET_TO_MAIN.sh` (bash 3.2): dry run by default; `--archive` first (a bundle per branch, tarballs for dirty worktrees and named untracked items, manifest + sha256, `--resume`), then `--apply` (worktrees removed only after their archive verifies, `branch -D` only for a bundled branch, live/locked/session worktrees and operations in progress are blockers, H last), `--clean` (`git clean -fdx` after the `-ndx` listing) and `--gc` behind their own flags; `hand_off/tests/test_reset_to_main.py`: 31 throwaway-repo tests, 21/21 seeded bugs caught. code-reviewer (1 blocker, 2 major, 3 minor) fixed in `76e1cd4` (no fail-open signature, staged diff archived, gc re-checks). A real dry run wrote nothing (`resume-1005/T10/dryrun-1.txt`). After merging main `ac9e350` (no conflicts): `hand_off/tests` 40 passed (31 + a4_fold 9), bash -n (and /bin/bash 3.2) ok, shellcheck -x clean, lint_agents, prompt_budget --check, guard self-test ok | reset-to-main@76e1cd4 via rtm-integ | reduced C10 (hand_off/ only; full C10 stands on ac9e350): see plan.md |
| 8 L7 B1 + B3, L10 | B1 (`stack_report.py` + `agent_guard.py`): a run whose newest assistant record calls SubagentHandback is checked on that call's `message` (parse, check, registry report, reports/ copy, usage row field `via`), never blocked in any mode; an unreadable message keeps the old common row; reader `transcript_handback` (bounded 4 MiB tail `HANDBACK_TAIL_MAX`, O_NOFOLLOW, S_ISREG first). B3 (`stack_progress.py`): once-per-run log-only `first_write` signal (`at_call` of the first Edit/Write/NotebookEdit/MultiEdit/Agent/Task/SendMessage call), `report` n/median/p90 per hand-back status, `derive_early_stop` counts it. L10 (`f09d8c6`, user-approved side commit): behaviour-neutral trims of rules, game-engineer, orchestrator; prompt_budget per_spawn_mean 28,961 → 28,882 chars. 18/18 seeded mutants killed; security-auditor + code-reviewer MEDIUM (a long hand-back passed the 256 KiB tail and was blocked in compact mode) fixed with a proof test (`b6696c2`). Branch already held main `878b18d` (no merge needed): `test_stack_report`, `test_stack_progress`, `test_agent_guard`, `test_prompt_budget` 490 passed, lint_agents, prompt_budget --check, guard and stack_progress self-tests, redundancy_lint ok, bash -n 22 ok, ruff E9,F clean on the changed files | l7-mech@a05d508 via l7-integ | C10 on main: see plan.md |
| wiki | The wiki is GitHub's wiki (USER decision 2026-10-06; it reverses the same-day `docs/wiki/` tracking): 19 pages (Home, `_Sidebar`, `_Footer`, Getting-Started, Architecture, Agent-Roster, Skills, Hooks-and-Guard, Security-Model, Toolsmith, Instructor, CLAUDE-md-Block, Container-Backend, Testing-and-C10, Operations, Contributing, Changelog, FAQ, Glossary) from the accuracy-reviewed wiki-docs@8606c8b, converted to GitHub-wiki links (`[text](Page-Name)` in pages, `[[text\|Page-Name]]` in sidebar and footer), assets byte-identical to `assets/` with `SHA256SUMS`, committed in a nested repository (branch `master`, no remote: the user pushes) at `resume-770728/wiki-main-fixes/github-wiki/`; publish steps in `resume-770728/.claude-work/github-wiki-publish.md`. wiki-docs had landed on main via wiki-integ (`c575843`, `8606c8b`, `6860572`); wiki-main-fixes reverses the tracking as a forward commit: `docs/wiki/` removed and ignored again (with `github-wiki/`), `tests/test_moved_paths.py` as at `6ecb003`, `tests/test_wiki_links.py` replaced by `tests/wiki_check.py` (GitHub-wiki rules, takes the folder, skips when absent) and `tests/test_wiki_check.py` (fixture wiki, seeded breakage), README pointer to the Wiki tab, CONFIG §9 entry replaced; the README/CONFIG accuracy fixes stay (re-measured on `6860572`: 182 references, 56 `Agent(...)` types, 46 acceptEdits, Role agents 19) | wiki-main-fixes (READY) | reduced C10 (docs and tests only); the integrator runs full C10 |
| 9 Stage 3 | Quality pass, 22 behaviour-neutral edits in 18 files (+14/-67): set A (`22cdae7`) dead code in hooks, bin and the libdocs MCP (unused import in stack-who; dead constants in stack_usage, stack_limits, toolsmith_policy, agent_guard; libdocs `_fetch_pages`' unused `via_note`; guard `--self-test` and `--print-policy` output identical to main); set B (`eb06bb7`) test hygiene (unused imports and locals, a duplicate `two_windows()`, unused guard_harness helpers; collected test ids identical) and two dangling skill references fixed, so their 2 redundancy-allowlist entries go (12 → 10). code-reviewer PASS ×2, security-auditor PASS; branch suite on `afc3116` 5118 passed 2 skipped, 7 failed = the known environment ids. Deferred for the user's approval (D1-D5: eq_wall dead constant vs `BROKER_SHA256`, B904 chaining, shared helpers, SIM115, PLW1510): `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728/.claude-work/stage3/DEFERRED.md`. Branch already held main `6860572`: lint_agents, prompt_budget --check, guard and stack_progress self-tests ok, redundancy_lint --strict 0 new 10 allowlisted 0 stale, ruff E9,F clean on all 127 tracked .py, bash -n 22 ok, 14 test files touching the changed code 1836 passed, 3 failed (test_stack_usage ×3, in the known environment set) | s3-integ@b1a0703 via s3-ff | C10 on main: see plan.md |
| Codex installer (codex_config/) | `codex_config/`: a Codex profile installer for this stack (`codex_config/install.sh`: snapshot of HEAD, staged render of the profile, agents, rules, skills (216 SKILL.md frontmatters converted), hooks and the codex guard, `--dry-run`, `--diff`, `--doctor`, `--ide-default`, `--restore`; installing is the user's step). The Claude installer and its tests are untouched (`git diff main...codex-build -- install.sh lib dot-claude tests requirements` empty); README/CONFIG get a pointer and a §9 entry. Early audit, final security-auditor and code-reviewer fixes in the branch; the last auditor MEDIUM (CWE-116: a SKILL.md description with a line break or control character emitted as a plain YAML scalar) fixed in `cab4daf` with `test_skill_md_description_stays_one_yaml_line` (6 cases failed before, pass after), the real corpus converting byte-identically (393 staged files, `diff -r` empty) and 2 mutation rows (convert_skills.json 10/10 caught). Branch already held main `5d3ecad`: `codex_config/tests` 2068 passed 1 skipped (own process; the two conftests collide with tests/), `codex_config/tests/smoke.sh` all checks passed (real ~/.codex, ~/.agents unchanged), lint_agents, prompt_budget --check, guard and stack_progress self-tests ok, bash -n 27 ok, shellcheck codex_config/install.sh clean, ruff E9,F clean on all 194 tracked .py, doc-gate tests 167 passed | codex-build@cfad7fa via codex-integ | C10 on main: see plan.md |
| eq-container pins | `lib/eq-container/TOOLS.toml` pins bash `5.2.37-2+b10` and perl (perl-base) `5.40.1-6+deb13u1`. The builder takes both from the base image, so each sha256 is of the file in BASE_IMAGE's arm64 layer `sha256:bd36565c…`, downloaded from debuerreotype docker-debian-artifacts `ca011a8b`; the layer and manifest hashes were recomputed and the md5 equals the layer's dpkg md5sums. busybox (`BUSYBOX_SHA256`) and jq stay PLACEHOLDER: snapshot.debian.org is outside the agent sandbox. So the default `core` still exits 13 and the WALL is still skipped until the user runs `hand_off/R3_CONTAINER_CHECKLIST.md` C14 (`bash lib/eq-container/distro-pins.sh`) and its values are pinned (C15-C17 then build and verify). Also new: `distro-pins.sh` (host-side derivation with every link checked; prints only, never edits) and the PINS keys `BASE_LAYER_URL` and `BASE_LAYER_SHA256`. `build.sh` refuses a malformed pin (exit 2; BASE_IMAGE needs its digest); `verify-tools.sh` counts a PLACEHOLDER `checksum_source` as pending. Format checks use literal character lists (`tools.sh` `tm_only`): bash 3.2's collation ranges let uppercase hex through under a UTF-8 locale. security-auditor PASS (optional hardening, not done: pin the snapshot InRelease sha256 in the Dockerfiles, so jq's libraries libjq1 and libonig5 are pinned too). code-reviewer pass-with-fixes: the MEDIUM (locale) and the LOW (a malformed BUSYBOX_SHA256 in distro-pins.sh) were fixed in `6adc499`; 10 of the 12 new proofs fail on `0da7eaf`. Tests: `tests/test_eq_container_pins.py` 60 passed, 23/23 seeded mutants killed (`.claude-work/eq-pins/mutants.py`); `test_eq_container` + `test_install_eq_container` 121 passed; repo suite from a clean detached worktree on `ebe4985`: tests/ 5224 passed 2 skipped, 7 failed (the known environment set: test_limits_guard T10, test_stack_tree ×3, test_stack_usage ×3), tools/instructor/tests 77 passed, lib/eq-wall/tests 100 passed 2 skipped; lint_agents, prompt_budget --check, guard self-test, bash -n, shellcheck, ruff E9,F ok | eq-pins (READY; `core` still waits on C14) | C10 on main: the integrator |
| Equilibrium harness tracked | EQ-T is tracked as `equilibrium/` with all features (USER: top level, not archived). The source was `.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium`, untracked. The tree holds the pre-registration (COMPARE_eq A4, plus the new **A5**), CONTRACT, the harness with the `container` backend and the A4 Skill edits, the pools PF/CP/CR/RS/ES/DS/OE with oracles and `pool.sha256`, the WALL and Docker staging copies, and the derivations: 3,860 files. Excluded: `isolation/build.log` and caches, which stay in EQ-T. **A5 (USER)**: path relativisation, 236 files and 504 substitutions, so no `/Users/...` path remains. Scripts derive M, STAGE and `DEFAULT_M` from their own location, Lean is `$HOME/lean/stack_mathlib`, and `vcs:source` is `blackcat.git`. The pins were re-derived: PF `pool.sha256` (220 entries) and RS (2). `tests/test_equilibrium_paths.py` proves only path text changed (record: `equilibrium/PATH_RELATIVISATION.json`). The security-auditor's 3 fixes are in: the `--collect` destination check, the WALL lookup preferring `lib/eq-wall`, and `runs/` ignored at any depth. So is the code-reviewer's fix: the layout test fails when the tree is missing. Harness suite: 451 passed + 1 skip with `EQ_CONTAINER_DIR`, 447 + 5 skips without it, 452 in place; selftests all pass (PF 39 with Lean). Also new: `tests/test_equilibrium_layout.py`, `lint_agents` `MODEL_ID_DIRS`, the `.gitignore` rules, and the harness suite as a by-hand C10 step (CONFIG §5 Instructor). | eq-track (see the merge report) | C10 on main after the ff-merge (integrator) |
| eq-runtime (part F: installer, doctor, docs) | `install.sh` stages the 8 `hooks/eq_*` files and `bin/stack-eq`, `stack-eq-check` (modes 644/755), tracks them in the manifest, byte-compiles the 5 modules and writes the manifest key `eq_runtime` = `{params_sha256, validated}` (what `eq_policy.load_params` reads; a different params file means every class `not_run`). `doctor.sh` section "Equilibrium runtime" (files, params pin, validated classes, drift, `excludedCommands`/allow entries, knobs, store modes, W3 level); its toolsmith check accepts `bin/stack-eq *`. Settings merge and retraction proven for the eq entries. `tests/test_install_eq_runtime.py`; README, CONFIG §5/§7/§9. The shipped `eq_params.json` is the `version 0` all-`not_run` placeholder, accepted by `validate_params` and `params.schema.json` (any other v0 is refused; validator in b595c3c, schema rule in eqr-hdocs 7c1702d; RESUME 2 (c)). Open: Guard rules (part D) and every spec §13 check are not live-verified. **The user runs:** `./install.sh --dry-run` then `./install.sh` after the integrator merges eq-runtime into main, then the README live checks 9 (spec §13) and, much later, `hand_off/EQ_CALIBRATION_RUN_PLAN.md` (paid) | eqr-install (see the report) | C10 on main: the integrator |
| eq-cli-install | `install.sh --with-eq-container` sets up Apple `container` end to end, asking permission (USER decision). Step 10b runs `lib/eq-container/setup.sh`, 3 steps, each skipped when done: (1) the CLI from Apple's signed .pkg (GitHub release hosts only, no automatic redirects, size cap; size, sha256 and signer pinned in `PINS` `CONTAINER_PKG_*`, a self-contained block at the END of PINS; `/usr/bin/sudo /usr/sbin/installer -pkg <file> -target /` in the foreground; version and receipt checked), (2) `container system start --enable-kernel-install`, (3) `eq-container.sh install` (`--yes` only with build consent, else `--no-build`; build.sh unchanged). Consent: typed `all` / `step` (+ `yes`) / `no` on a terminal, or `--install-container`, `--start-container-service`, `--build-container-images`, `--setup-container`; `--no-install-container`; `--yes`/`--no-prompt` are never consent; steps 1-2 refused under CLAUDECODE. Exits: 13 CLI pin placeholder (`CONTAINER_PKG_SIGNER=UNSET` until checklist C18), 2 malformed, 14 package check, 17 download/install, 18 service. `cli.env`/`setup.env`, manifest `eq_container.cli`, doctor (version vs pin, service), `--restore` and uninstall print Apple's removal commands (the CLI is never removed). Merged main 35b2377 (fb8e10b: CONFIG §9 keeps both entries). security-auditor PASS WITH FIXES (MEDIUM CWE-755: a failed upgrade left the service it stopped down; LOW CWE-59: `setup.env` written through a refused symlinked state dir); code-reviewer PASS WITH FIXES (the same MEDIUM; MEDIUM: a driver's own skip relabelled as the step-1 code 13; LOW: C21 text). All fixed in b0c59d9; the 3 new proofs fail on fb8e10b and pass after. Found by the suite: git 2.54's detached auto maintenance packed the scratch repos' ~4,265 loose objects (equilibrium/) while install.sh's `git fsck` read them ("unable to mmap"), failing full installs in tests/; the scratch repos now set `gc.auto 0`/`maintenance.auto false` (76b6952; main's C10 needs it too). Tests: test_eq_setup 90 passed; on e2519d4 test_eq_container 84 and test_install_eq_container 47 passed; suite on 76b6952 from a clean detached worktree: tests/ 5346 passed 2 skipped, 7 failed (the known xcrun_db set: test_limits_guard T10, test_stack_tree ×3, test_stack_usage ×3), tools/instructor/tests 77 passed, lib/eq-wall/tests 100 passed 2 skipped, codex_config/tests 2068 passed 1 skipped, equilibrium harness 451 passed 1 skipped; lint_agents, prompt_budget --check, guard self-test, bash -n, shellcheck (no new findings), ruff E9,F ok. Not run: `tests/install_smoke.sh` (your terminal). Your steps: `hand_off/R3_CONTAINER_CHECKLIST.md` C18-C23 (C18 derives `CONTAINER_PKG_SIGNER`). | eq-cli-install@321f037 (merged; 76b6952 is an older ancestor) + this row (READY; rescue ref eq-cli-install-pre-merge = e2519d4) | C10 on main after the ff-merge (integrator) |
| eq-container distroless | Every final image is FROM the digest-pinned `gcr.io/distroless/cc-debian13:nonroot` (index e792ab3d, arm64 manifest 2f0295ce; the bytes kept in `lib/eq-container/base/`, base-verify 21 layers) or `scratch` (tc-go): one COPY, no RUN, USER 10001:10001, a `check-<target>` stage built first (failure: 12). Static GNU bash 5.3 + patches 001-020 from the GPG-signed source (`tc/build-bash.sh`, keyring = exactly `7C0135FB…`, VALIDSIG), the perl shim, jq 1.8.2 static, busybox musl, uv musl 0.12.22; no Debian, apt or dpkg; `Dockerfile`, `distro-pins.sh`, `tc/apt-closure.sh` deleted; `base-pins.sh` (cosign identity and issuer) new. `--set full` and `STACK_EQ_CONTAINER_SET=full` refused, rust and haskell deferred (10). PLACEHOLDER until D2: `BASH_SRC_SHA256`, `BASH_PATCHES_SHA256`, `BASH_BIN_SHA256` (core stops at 13). Reviews: security-auditor and code-reviewer pass with fixes, fixed in 99fad19; `untar.py` refuses absolute names (253d3f6). Merged main twice: 321f037 (eq-cli-install) in ac53e32, where PINS keeps the `CONTAINER_PKG_*` block last, 10b refuses `SET=full` before setup.sh asks anything and then runs setup.sh's consent flow (`--yes` is never consent: the driver gets `--yes` only with build consent, else `--no-build`), and eq-container.sh takes the union (`build-due`, `--no-build`, `--set min` only); expectations changed by the merge: the `SET=min` driver argv is `install --set min --no-build --no-prompt`, and the PINS/Dockerfile ARG test leaves out the `CONTAINER_*` block and requires it last; then b99516f in 870b80e (clean). Tests after the merge: pins 402 passed 1 skipped, dockerfiles 120, test_eq_container 192, test_install_eq_container 51, test_eq_setup 90, lib/eq-wall 100 passed 2 skipped (no eq-wall file edited); seeds: install-full-accepted and both eq-container.sh seeds KILLED again (35/35); equilibrium harness from a copy with EQ_CONTAINER_DIR 451 passed 1 skipped (fake CLI byte-identical); codex_config 2068 passed 1 skipped; suite on 870b80e from a clean detached worktree: tests/ 5930 collected in four parts (the 2 h background limit and a load average near 31: the full run was stopped after 2103 results, all files up to test_install_diff and 38 of test_install_eq_container, 2101 passed 2 skipped; then the other 13 of that file 13 passed, the install files up to test_installer_config_dir 172 passed, and the tail from test_instructor_wiring 3634 passed 1 skipped 7 failed): 5920 passed, 3 skipped, 7 failed, the 7 known env failures only (xcrun_db stderr: test_limits_guard T10, test_stack_tree ×3, test_stack_usage ×3; the 5 git-fsck races are gone), instructor 77, bash -n 311 ok, guard self-test ok, lint_agents ok, prompt_budget --check ok; shellcheck no new findings, ruff E9,F clean. Not run: `tests/install_smoke.sh` (your terminal). Unverified without the real CLI and network: your steps are `hand_off/R3_CONTAINER_CHECKLIST.md` D1-D9 (with C18-C23 from eq-cli-install). | eq-distroless@fd0a2a3 (merged; 870b80e is an older ancestor) + this row (READY; rescue refs rescue/eq-distroless-7f4b50b, rescue/eq-distroless-8297a8e) | C10 on main after the ff-merge (integrator) |
| 15 | audit fix round: git no-push gaps both guards, web check, STACK_HOOK_RE, deferred profile, dead code, option case | audit-fixes@a10ef8e4 | C10 on main: see resume-1007 plan |
| audit-fixes (merged) | Item 15 plus the item 14 docs commit; merged by the user's ff, in main as `ad10c9ba` (tip). Three review rounds, last findings fixed with proofs | audit-fixes@ad10c9ba (merged) | C10 on `be11f4c8` done |
| eq-runtime-2 (merged) | Item 11 as in §4, plus A7 (H5 removed) and A8 (`eq_check.sh` E7 cell pass; `run --cells` passes its cells to `eq_check.sh`); harness mutations regenerated at `806d6dc4`: 183 mutants, all killed | eq-runtime-2@258d3a35 (merged) | C10 on `be11f4c8` done: harness 636 + 2 skipped, eq_mutations 39/39 |
| docs-reorg | Layout: diagram to `assets/diagrams/`, Equilibrium spec to `docs/`, `PREVIOUS_GIT_COMMITS.md` removed; `tests/test_moved_paths.py` exempts only the `docs/wiki/` prefix; merged with main `3081ce59` | docs-reorg@f20c7a89 (merged) | C10 on `be11f4c8` done (moved_paths 31 passed) |
| fix jsonschema | `VENV_PACKAGES['tools']` in codex translate gains `jsonschema` (`requirements/tools.in` since `b595c3c7`); clears the `test_venv_packages_match_requirements` failure seen on `eq-runtime-2` | main@be11f4c8 | C10 on `be11f4c8` done: codex_config 2171 + 1 skipped |

## 9. NEXT PROGRAMS (plans saved, not started; state 2026-10-08)

Every plan file is under `H` (git-ignored `.claude-work/`). Sequencing: after the dot-config merge and a green C10 on main;
merge order Bayes 3a -> SDK-2 -> Bayes 3b -> Bayes 3c -> SDK-3 -> Bayes 4 -> SDK-4.

1. **dot-config restructure**: see "Pending" at the top (built, reviewed, waiting on the user's steps).
2. **SDK optimization.** `H/.claude-work/sdk/plan.md`. Decisions: unattended runs stop at the plan with STATUS blocked; the
   installed `claude` via `cli_path`; Python only. Consent (USER): paid `sdk_smoke.py` <= $3.00 and `sdk_probes.py` <= $10.50,
   both run by the user.
3. **Bayesian tuning.** `H/.claude-work/bayes/plan.md`. Decisions: Q1 the empirical stage keeps deny-type values; Q2 advice only
   for width; Q3 consent to P1 <= $40 and P2 <= $200, run by the user; Q4 amend the equilibrium before p data; Q5 default keep
   sched/fanout.
4. **Lost-work rescue.** `H/.claude-work/lost-features/rescue/` (`MANIFEST.md`; git-ignored: copy it outside the worktree
   before any worktree removal; `campaign-restored/`; decision quotes in `bayesian-decision.md` (2026-10-03, sessions
   13998b29/fae82d02) and `sdk-request.md` (2026-10-02, session 4e2da3ce)).
5. **Unmerged side branches awaiting the user's decision** (patches saved in the rescue folder): `s4-l7-l10` ("Minimum first"
   + A/B test); `worktree-agent-a06763fbda9c482d4` (cache-stable prefix + an untracked test); `worktree-agent-a08001452f6ef3994`
   (installer skips existing CLI tools); `worktree-agent-ae67658dcd0599872` (drop Conductor/Nimbalyst/Zed/JetBrains host content).
6. **Open items.** Broker TOCTOU in `eq_harness` `load_wall_module` vs `Wall.start` (latent, MEDIUM, pre-existing);
   `STACK_CODEX_VIA_TOP=1` inner-installer bypass of agent_guard (LOW, `~/.codex` unguarded); H5 is removed (A7); the A4 fold
   waits for the user's paid probe (§5); `RESET_TO_MAIN.sh --archive`/`--apply` are the user's; `disc3.py` orphan (§5 step 4);
   user cleanups of worktrees (c10/wt-7c8a839, c10/wt-be11f4c8, dc-*, eq-runtime-2, ...: list in
   `H/.claude-work/resume-1005/FINAL_REPORT.md`).

User steps still open: the dot-config steps (top); merge and push the wiki `docs-reorg` branch; remove worktrees; kill
`disc3.py` (§5 step 4); the reinstall (§5, now per `dot-config/REINSTALL.md`).
