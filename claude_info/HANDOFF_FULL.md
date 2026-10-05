# HANDOFF_FULL: claude-agent-stack, session 5f94892d (stopped 2026-10-05: the user's weekly usage was exhausted)

Written by main-coder (wrap-up). Supersedes `T/.claude-work/claude_blackcat_next_steps/HANDOFF.md` §11 and the plan
checkpoints where they differ. The next session's opening prompt: `NEXT_SESSION_PROMPT.md` (same folder).

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout) · **T** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f`
· **S** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agent-stack-resume-9caddf` (this session's worktree; its `.claude-work/` is git-ignored)
· **W** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0` · **EQ-T** `T/.claude-work/equilibrium`
· **WT** `M/.claude/worktrees` · plan `T/.claude-work/next-steps/plan.md` · ledger `/Users/pmrj/.local/state/claude-agent-stack/5f94892d-c18f-4d04-9870-73fb864af562/delegations.md`

Key: **[v]** checked against git or a file during the wrap-up (2026-10-05 13:00-14:00) · **[r]** from an agent's report as
recorded in plan.md, not re-run · **[unverified]** nobody checked it.

## 0. State at stop
| item | value |
|---|---|
| local `main` | the commit that adds this folder ("Session-stop handoff"), parent `d955bef` (L1); C10 on that main: `T/.claude-work/next-steps/plan.md` STOP checkpoint |
| installed `~/.claude` manifest | `7d12c58` [v] (install HELD: c0 and Docker not done) |
| merged in the wrap-up | L1 `d955bef` (fast-forward 7d12c58 -> d955bef) + this handoff commit. Before the merge: code-reviewer aa9eba703b28f7feb PASS-WITH-FIXES (§4 note) and C10 on d955bef's tree in its worktree: bash -n 4/4, guard self-test, lint_agents, prompt_budget --check, test_image_studio_mcp 125 passed, pytest 4407 passed / 2 skipped, install_smoke 279 passed / 2 failed (the known openpty pair: supply-chain confirmation, controlling-terminal confirmation) [v] |
| held (security-auditor + code-reviewer before merge) | R3 installer, L2, instructor, L5 (§2, §4) |
| not shipped | L7/L10 `d246778` (prompt text; net +17 tokens/spawn) |
| R3b leftover | uncommitted R3 work in `WT/agent-ac1227df5c0315a8a` (branch `worktree-agent-ac1227df5c0315a8a` @ 7d12c58), last file write 12:29; left untouched (§2 R3) |
| c0 | NOT collected (`M/claude_next_steps/work_carried/context-diet/arms/` absent [v]) |
| Docker | NOT done by the user (no spike/probe/reverify; image IDs not frozen in `flags.json`) [r] |

## 1. Standing constraints (user; all binding)
1. Never push; no forge writes. Publishing is the user's step.
2. No `./install.sh` by agents; install is HELD until c0 and Docker are done.
3. No paid runs (`claude -p`, pilot, A/B) without explicit consent; stub_claude only.
4. NO HAIKU: sonnet/opus latest only, in every spawn and every config.
5. Every security surface gets independent review (security-auditor + code-reviewer) before merge: agent_guard.py,
   settings.json, install.sh, hooks, the WALL, lib/eq-*, doctor.sh.
6. **Own worktree only** (USER, 11:15): every commit is made in the committing agent's own worktree; no scratch-clone
   fetches, no plumbing commits, no writes into another worktree. Builders in M are spawned with `isolation: "worktree"`.
   The Edit/Write guard refuses the base checkout M from a session worktree: land changes by committing in your own
   worktree, then `git -C M merge --ff-only <branch>`.
7. Serialize work touching agent_guard.py / settings.json / install.sh / blackcat.md (one owner at a time).
8. Python through uv; measure before tuning; never claim an unmeasured saving.
9. User-only gates are ASK USER items, never skipped.
10. C10 at every merge, on main: `env -u STACK_LIMITS_SNAPSHOT -u CLAUDE_SESSION_ID /Users/pmrj/.claude/venvs/tools/bin/python -m pytest -q tests/`
    (on M always `tests/`: bare pytest collects worktrees), `tests/lint_agents.py`, `tests/prompt_budget.py --check`,
    `dot-claude/hooks/agent_guard.py --self-test`, `bash -n` on tracked *.sh, `tests/install_smoke.sh` (2 known openpty
    failures under the sandbox), `tests/test_image_studio_mcp.py`. Wrap-up runner: `S/.claude-work/wrapup/c10.sh <repo> <log>`.

## 2. Stages R1-R5
### R1 review fixes (EQ-T files, not in git): DONE [r]
| part | owner (id, gone) | result |
|---|---|---|
| R1a WALL + harness (W1 W2 W5, N24 #1-#3 #6 #9, check_probe rows, eq_check ledger integrity, eqbox `uv --no-config`) | security-engineer aed82c5175a0eed38 | fixed with proof tests; wall 98/2 skipped, wall mutants 50/50 |
| R1b isolation (W3 W4 N24 #10) | devops-engineer a1b7d867a09a0db87 | 65 passed (run from cwd /tmp/claude-501 with TMPDIR=/tmp/claude: bash 3.2 heredocs fail under T) |
| R1c route 1 `harness/eq_analyse.py` (N24 #4 #8 + contract rows) | data-scientist af18350b7683eca50 | 35 passed, cross-route equal |
| R1d route 2 `harness/eq_route2.*` | data-engineer a1e88b52ef0a3e6fa | 30 passed |
Input: `T/.claude-work/next-steps/REVIEW_N23_N24.md`.

### R2 independent run + reviews: DONE [r]
- R2a test-engineer a18aebecdeee9b8e7: `EQ-T/harness/R2_RUN.md`: harness 395/0 in a /tmp copy (2 location-only failures under T), harness mutants 130/130, wall 98 + 2 skipped, wall mutants 50/50, repo-stage 260/1 skipped, routes 0 disagreements in 1204 cells.
- R2b code-reviewer a348180276c7a4f89: pass-with-fixes (2 LOW). R2c security-auditor a5c0126bf1914acb0: pass-with-fixes (F1 MED, F2 LOW).
- R2d security-engineer a379497803f07e6dd: check_probe host rows, F1 `no_score` helper, F2 `S_ISREG`, eq_check comment, WALL_DESIGN §13 numbers; default `no_verdict_policy = "zero"`. Wall 100/2 skipped, harness 401/0, mutants 52/52 + 136/136.
- **F1 fixed [v]**: `EQ-T/harness/eq_harness.py:3873` `def no_score`, used at :3980 and :3986; `harness/flags.json:295` `"no_verdict_policy": "zero"`; proof test file `harness/tests/test_no_verdict_policy.py` exists; `COMPARE_eq.md:408-410` amendment A3 states it CHANGES THE PRE-REGISTERED SCORING (USER's choice).
- Caveat [r]: a flags file WITHOUT the key falls back to "unscored" (documented, untested).
- X7 = POSITIVE for the default-deny WALL policy only (a non-empty policy stays blocked by N23 2g, unkeyed chain).

### R3 installer integration (eq-docker + WALL default-on + keep-list): HELD, not committed
| piece | where | state |
|---|---|---|
| R3 first attempt (main-coder a5eddeda6c21de9c3) | `S/.claude-work/r3/{STATE.md, r3-full-over-main-7d12c58.patch, r3-edits-over-staged.patch}` | PARTIAL, nothing committed (the guard refused writes outside S). `git apply --check` of the full patch on main 7d12c58: clean [v]. Exec bits are not carried (STATE.md). |
| leftover worktree | `WT/r3-installer` (branch `r3-installer` @ 7d12c58) | untracked copies only [v]; the user may remove it |
| R3b (main-coder, isolation worktree, launched 11:51; no id in the ledger) | `WT/agent-ac1227df5c0315a8a`, branch `worktree-agent-ac1227df5c0315a8a` @ 7d12c58 | **uncommitted** [v]: 13 modified tracked files (.gitignore, CONFIG.md, README.md, dot-claude/bin/doctor.sh, dot-claude/hooks/agent_guard.py, dot-claude/settings.json, install.sh, lib/stack.env.example, lib/stack_diff.py, tests/install_smoke.sh, tests/test_install_state.py, tests/test_protected_paths.py, tests/test_stack_usage.py) + 11 untracked entries (lib/eq-docker/, lib/eq-wall/, tests/conftest.py, tests/fake-brew/, tests/fake-docker/, tests/test_eq_docker{,_compose,_isolation,_toolchains}.py, tests/test_install_eq_docker.py, tests/test_install_eq_wall.py): 24 status lines, no file newer than 12:29 at 14:01. Its logs in `.claude-work/r3/`: smoke.log 12:29 "290 passed, 2 failed" (failures not inspected) [v]; mutations.log 12:18 wall 52/52 [v]; c10-pytest.log EMPTY (full pytest not run or not finished) [v]. The orchestrator was killed; whether the R3b process still runs is unknown (`ps` is sandbox-denied; last write 12:29). Left exactly as found. |
Touches install.sh, settings.json, agent_guard.py (prune keep-list eq-docker, eq-wall), doctor.sh, lib/eq-docker, lib/eq-wall. Open security finding [r]: the tunnel root `~/.cache/claude-agent-stack/eq-tunnel` is under no agent deny rule. Spec deviations to confirm in review: STATE.md "Deviations".

### R4 Stage 4 token levers
| lever | commit / branch / worktree | provenance | state |
|---|---|---|---|
| L1 cache stability (lint, early-hook probe, cache monitor; tests/ only) | `d955bef`, branch `worktree-agent-ad350b89c11c5e2e1`, `WT/agent-ad350b89c11c5e2e1` | normal `commit:` in its own worktree [v reflog] | MERGED in the wrap-up (reviewed; follow-ups in §4 note) |
| L1 CLAUDE.md managed block (installer) | none | none | NOT BUILT (spec: STAGE4.md L1; install.sh, serialized) |
| L2 output_shrink PostToolUse hook | `b6e05d6`, branch `s4-l2-output`, `WT/agent-aba18d58c1624f927` | normal commit [v reflog]; draft only | HELD (hooks + settings.json). Fixes + tests are patches: `S/.claude-work/s4-l2/{output_shrink-fixes.patch,test_output_shrink.patch}` (103 passed, 54/54 mutants [r]; 5 defects fixed incl. a secret leak in the log's command-family field), `T/.claude-work/s4-l2/{install-wiring.patch,L6_GAP.md}`. All three apply cleanly on b6e05d6 (`git apply --check`) [v]. Helper worktree `S/.claude/worktrees/s4-l2-work` (detached b6e05d6). |
| Instructor (just + uv scripts: check-suite, ff-merge, worktree-audit) | `deea4d5`, branch `s4-instructor-build` (no worktree); `WT/s4-instructor` (branch `s4-instructor` @ 7d12c58, clean) | **plumbing commit** [v reflog: "plumbing commit; s4-instructor worktree not writable from this session"] | HELD: breaks the own-worktree rule; ff_merge.py writes git refs; needs a re-commit from its own worktree plus reviews. `S/.claude-work/s4-instructor/{VERIFY.md,patches/{install-brew-just,settings-instructor,guard-instructor-writedeny}.patch}`. `just` not installed. VERIFY: one allow rule per recipe (a `*` rule is unsafe: `just --command/--shell/--set`). |
| L5 budget tracking / early-stop signals | `2ebc26f`, branch `s4-l5-budget`, `WT/s4-l5-budget` | ff into its branch [v reflog] | HELD (new hook `dot-claude/hooks/stack_progress.py`, observe only). `T/.claude-work/s4-l5/{DESIGN.md,agent_guard.patch,install.patch}`. Replay: budget rule fired once, 0.09% [r]. |
| L7 + L10 prompt wording/trims | `d246778`, branch `s4-l7-l10` (worktree `WT/s4-l7-l10` detached @ 7d12c58) | **scratch-clone fetch** [v reflog] | NOT SHIPPED (USER: L7 = mechanisms, not prompts; net +17 tokens/spawn). L10 trims alone: -26 tokens/spawn [r]. |
| L7 mechanisms (design) | `T/.claude-work/s4-l7-l10/MECHANISMS.md` | none | design done; build later: B1 log the SubagentHandback message (stack_report.py + agent_guard.py, serialized, security review), B2 = L5 patches, B3 log calls-before-first-write. 64% of hand-backs exceed the role cap but restating nets -0.81% -> observe only [r]. |
| L8 effort audit | `S/.claude-work/s4-l7-l10/L8_EFFORT_AUDIT.md` | none | no calibration possible (confounded); no change without a paid A/B |
| L9 workflow skills | `S/.claude-work/s4-l9/CANDIDATES.md` | none | nothing built (no candidate clears pooled >= 3%); empty worktree `WT/s4-l9` |
| L6 | `T/.claude-work/s4-l2/L6_GAP.md` | none | gap note only |
| measurement | `T/.claude-work/stage4-measure/MEASURE.md` | none | ceilings: Opus->Sonnet 27.0%, compaction 200K 13.4%, tool-output offload 10.0%, recipes 6.1%; clearing old outputs and the 1 h TTL lose money [r] |
Copies of S's Stage-4 outputs: `claude_info/s4_outputs/` (this folder; caches excluded; `s4-instructor/src/` is byte-identical to deea4d5's
`tools/instructor/` [v]). In the copies of `AB_PROPOSAL.md` and `L8_EFFORT_AUDIT.md` the doc slugs `prompting-claude-<family>-5-5` read
`prompting-claude-<family> 5.5` so the repo's model-ID lint passes; the originals are in `S/.claude-work/s4-l7-l10/`.

### R5 Stage 3 quality + ONE_TREE: NOT STARTED beyond maps
- Maps (explore x2, partial; unverified candidates): `T/.claude-work/next-steps/R5_MAP.md` (Area A hooks/lib/install, Area B agents/docs/tests; no confirmed bugs).
- Worktree audit + script draft: `T/.claude-work/one-tree/{AUDIT.tsv,ONE_TREE.sh}`: 112 rows (65 contained-ancestor, 12 contained-cherry, 11 in-use, 23 unique, 1 main) [v]; the snapshot predates the Stage-4 commits and this wrap-up: re-take it. ONE_TREE.sh never executed, unreviewed.
- `protocol-p1` worktree (`W/.claude/worktrees/protocol-p1`, detached 201e645): interactive rebase onto a29cd29 stopped with a conflict in CONFIG.md [v]; branches `protocol-p1` and `protocol-p1-rescue-1` at d9c1e89.

## 3. Verified vs unverified
- Verified in the wrap-up [v]: main and manifest SHAs; worktree list; reflog provenance of d955bef, b6e05d6, deea4d5, 2ebc26f, d246778; R3b's uncommitted file list and log tails; patch applicability (R3 on main, L2's three on b6e05d6); F1 / no_verdict_policy code, flags and amendment text; c0 `arms/` absent; AUDIT.tsv class counts; protocol-p1 conflict file; the C10 runs in §0 and §4.
- From reports only [r]: every count in §2 not marked [v]; MEASURE.md numbers; L8/L9 conclusions; R3 spec deviations.
- Unverified: whether R3b's process is still alive; which 2 smoke cases failed in R3b (probably the known openpty pair); whether a flags file without `no_verdict_policy` should fail closed; the 2 location-only harness failures under T.

## 4. Held / unreviewed (merge only after security-auditor + code-reviewer, then C10 on main)
| item | why held |
|---|---|
| R3 installer (R3b worktree, uncommitted) | install.sh, settings.json, agent_guard.py, doctor.sh, WALL, lib/eq-*; not committed; full pytest not run |
| L2 `s4-l2-output` b6e05d6 (+3 patches) | new hook + settings.json + stack_hook.py |
| Instructor `s4-instructor-build` deea4d5 (+3 patches) | plumbing commit (own-worktree rule); git-writing ff_merge; install/settings/guard patches |
| L5 `s4-l5-budget` 2ebc26f (+2 patches) | new hook stack_progress.py; agent_guard + install patches; the observe->warn switch needs its own security review |
| L7/L10 `s4-l7-l10` d246778 | not shipped by USER decision; scratch-clone commit |
| ONE_TREE.sh | deletes worktrees/branches: code-reviewer + verifier dry run before the user runs it |
| EQ-T harness/wall/isolation (not in git) | reviewed through R2c/R2d; the repo-stage copy enters git only with R3 |

L1 review (code-reviewer aa9eba703b28f7feb, PASS-WITH-FIXES, merged as reviewed). **The three follow-ups below are APPLIED
in `69067f6`** (2026-10-05, python-engineer, own worktree): cache_monitor.py skips non-dict `message` and non-str request
keys (no merge under None), reads non-dict usage/cache_creation/attachment/clientChange as `{}`, token counts as ints only
(bool excluded), a non-str model as None and non-list `kinds` as `[]`; the lint's date pattern adds "Oct 2026",
"October 2026", "Sept. 2026", "2026-10" (shipped prompt files still clean, 267 files); the stack_usage SubagentStart
probe sends `SubagentStart`. Proof tests (`MALFORMED` fixture next to "not json", `test_malformed_record_*` x10,
`test_non_string_model_reads_as_none`, `test_token_counts_are_ints_only`, the month-level `test_volatile_patterns_hit`
rows, `test_silent_probes_send_their_own_event`) fail on 743a7e2's code and pass on 69067f6 [v]. Original findings:
- MEDIUM `tests/cache_monitor.py:120-148`: field types inside a JSON line are not checked, so one malformed line aborts the
  report (`"message":"x"` -> AttributeError at :121; list `id` -> TypeError at :125; `"input_tokens":"5"` -> TypeError at
  :132; non-dict attachment/clientChange/cache_creation likewise; records without id/requestId/uuid merge under `None`).
  Traced, not reproduced. Fix: skip non-dict `m` and non-str `mid`; treat non-dict usage/cache_creation/attachment/clientChange
  as `{}`; read token values as ints only. Proof: add those two lines next to the "not json" fixture (tests/test_cache_monitor.py:66).
- LOW `tests/cache_stability_lint.py:43-47`: the date pattern misses month-level dates ("Oct 2026", "2026-10").
- LOW `tests/test_cache_stability.py:210`: the SubagentStart probe sends `hook_event_name: "SessionStart"`.
- Note: lint_agents.py does not call the new lint (it only exempts test_cache_stability.py from the model-ID check); the
  cache lint is enforced through the test `test_shipped_prompt_files_are_clean`.

## 5. Decisions (do not re-ask)
Earlier sessions: A1 tau = 0.6 (3 of 5), finding-set t = 2, no ceil(2N/3) switch · NO HAIKU · Phase 1B = no built-in swap, the stack's explore/claude-code-guide on sonnet · Phases 2 and 3 deferred (P2/P4/P8, Q3, D2/D4/D5/D7/D8 stay open) · default Homebrew offer = Docker Desktop · Lean 4 + Mathlib image: the leanest that works, by comparison (the user runs the measurements) · Step R done, wiki unchanged · A3 approved as (a): WALL + sandboxed member Bash, default-on only if re-audit + code review pass · no paid A/B · output style Default (the user applies it) · installer-managed `~/.claude/CLAUDE.md` block (STAGE4.md L1 spec) · instructor = just + uv · Stage 4 levers L1 L2 L5 L6 L7 L9 L10, L8 audit only · image rules X4 (binary-only final images) and X8 (Stage 3 scope + ONE_TREE as the final step) · ONE-tree end state via the user-run ONE_TREE.sh.
This session (USER, 2026-10-05):
1. `no_verdict_policy = "zero"` (re-check isolation, re-run once, then score 0); F1 fixed first in R2d [v]; recorded as COMPARE_eq §12 A3 (changes the pre-registered scoring).
2. Own worktree only: no cross-worktree commits; reviewers inspect the bypassed commits before any merge.
3. L7 = mechanisms, not prompts (`MECHANISMS.md`); d246778's prompt text is not merged.
4. L5: observe now; switch to warn when DESIGN.md §7 criteria are met (measured on observe data, security review of the switch); early stop = a later ASK USER.
5. No L7 A/B.
6. c0 and Docker NOT done -> installer HELD; R3 only in a worktree; WALL default only per audit (X7 POSITIVE, default-deny policy).
7. Wrap-up rule: merge only branches that touch no security surface, pass C10 on main and were committed in their own worktree.

## 6. Open ASK USER
1. Oracle residuals: PF compile-time code -> split into a two-container PF judge (needs a frozen-judge change); move CP's in-process tests out of the answer container.
2. Image choices: Debian-packaged bash/perl/jq/busybox vs pinned static binaries (provenance); Scala 3 release tarball vs scala-cli / sbt; MongoDB (SSPL-1.0) in or out; a `cc` linker in the Rust/Haskell images (rustc/ghc need it, conflict C6).
3. Plugin pinning / autoUpdate for claude-plugins-official (supply chain).
4. Stage 4 build threshold: 3% pooled saving / 2% per class / 4 of 5 sessions: confirm or change.
5. SendMessage-resume rule (26 of 31 cache misses = Claude Code's thinking drop on warm resumes): restrict resumes?
6. Subagent prompt-cache TTL 1 h measured -5.4% (loses money): keep the default?
7. `omitClaudeMd` for subagents: adopt or not.
8. ONE_TREE: 23 rows with unique commits (merge / archive as a git bundle under T/.claude-work / discard), 5 dirty worktrees, the protocol-p1 rebase conflict in CONFIG.md (continue / abort / archive).
9. c0 and Docker: when will the user run them (RUNBOOK_c0.md A, B, collect, C; RUNBOOK_MINIMAL.md)?
10. Still open from earlier: probes P2/P4/P8 and which Q3; D2 keep/remove list, D4/D5/D7/D8; pilot spend (B per item, S*, m, max items) and paid smoke 5a; copy the staged NEXT_STEPS/DECISIONS/CHANGES (`T/.claude-work/next-steps/staged/`) into `M/claude_next_steps`.

## 7. Future plan (in order; serialized merges, C10 on main after each)
1. Verifier: re-check §0 (main SHA, worktrees, the R3b worktree untouched, manifest).
2. R3: finish in `WT/agent-ac1227df5c0315a8a` (compare with `S/.claude-work/r3/r3-full-over-main-7d12c58.patch`; exec bits; test_install_eq_wall.py; install_smoke eq-docker/eq-wall cases; README/CONFIG), full C10, commit in that worktree; security-auditor + code-reviewer; fixes; ff-merge; C10 on main. Add a deny rule for the tunnel root.
3. L2: apply its 3 patches in an own worktree (off b6e05d6, or rebased on main), commit; reviews; merge after R3 (settings.json serialized).
4. L1 follow-ups: the LOW review findings (§4 note); the installer-managed CLAUDE.md block (unbuilt; install.sh, after L2).
5. Instructor: re-commit deea4d5's tree from its own worktree, apply its 3 patches there; reviews; merge.
6. L5: reviews + merge (observe only); later the warn switch per DESIGN.md §7 with a security review.
7. L7 mechanisms B1-B3 (agent_guard.py, serialized) + security review; L10 trims as a side commit only if wanted (-26 tokens/spawn).
8. Stage 3 builders from R5_MAP.md (behaviour-neutral, disjoint worktrees; behaviour changes listed for approval).
9. ONE_TREE.sh: code-reviewer + verifier dry run; re-take AUDIT.tsv after all merges; the user runs it.

## 8. The user's own commands
- Copy S's outputs to T before removing S: `cp -R /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agent-stack-resume-9caddf/.claude-work/s4-* /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/` (also `.claude-work/r3` and `.claude-work/wrapup`; the s4-* files are also in `claude_info/s4_outputs/`).
- Remove once merged or archived (each is a user step):
  `git -C /Users/pmrj/ZDone/claude-agent-stack worktree remove /Users/pmrj/ZDone/claude-agent-stack/.claude/worktrees/s4-l9` ·
  `git -C /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agent-stack-resume-9caddf worktree remove /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agent-stack-resume-9caddf/.claude/worktrees/s4-l2-work` ·
  `git -C /Users/pmrj/ZDone/claude-agent-stack worktree remove /Users/pmrj/ZDone/claude-agent-stack/.claude/worktrees/agent-ad350b89c11c5e2e1 && git -C /Users/pmrj/ZDone/claude-agent-stack branch -d worktree-agent-ad350b89c11c5e2e1` (L1, merged) ·
  `.../.claude/worktrees/r3-installer` (untracked copies only) once R3 lands.
- c0: `T/.claude-work/context-diet/RUNBOOK_c0.md` sections A (reinstall a22c5b4 in a throwaway clone), B (verify), "Collect c0" (17 prompts, `freeze.sh --arm c0`), C (back to main: install the current main).
- Docker: `EQ-T/isolation/RUNBOOK_MINIMAL.md` §0-§17 (cd into `EQ-T/isolation` first), then `flags --docker-image` + `isolation-probe` (§10).
- Output style -> Default (the user's own setting).
