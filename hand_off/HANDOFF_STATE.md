# HANDOFF_STATE: claude-agent-stack, state as of 2026-10-10 05:20 (main `c1ded439`; step 10b; step 11 next)

One coherent state; it replaces every earlier version of this file and folds in the session record of 2026-10-09
(`W/.claude-work/HANDOFF-2026-10-09.md`) and the hand-off queue of 2026-10-10 (`W/.claude-work/hand-off-queue.md`), both
git-ignored. Older decisions, R1/R2, the Stage-4 lever table and the L1 review findings stay in `claude_info/HANDOFF_FULL.md`,
removed from the tree in `7e47dfbb` (read it with `git -C M show 2aff512d:claude_info/HANDOFF_FULL.md`). The next session
starts with `hand_off/NEXT_SESSION_PROMPT.md`.

Key: **[v]** read in a file or git when this was written · **[r]** from a report, a commit message or a plan, not re-run ·
**[unverified]** nobody checked it.

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout, repo of record; layout `dot-config/{dot-claude,dot-equilibrium}`)
· **H** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb` (git-ignored `.claude-work/`:
the C10 scripts `c10/`, the program plans `work-order-1008/`, `bayes/`, `sdk/`; agent Bash sandboxes cannot write it, the Write
and Edit tools can) · **W** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544` (branch
`golden/work-order-continuation-b06255`, merged; its git-ignored `.claude-work/` holds this work order's job folders and the
branch worktrees under `W/.claude-work/worktrees/`) · **R** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728`
(older worktrees; the wiki clone the C10 checks).

## 1. State

- **main = `c1ded439`** [v `git -C M log`, reflog, 2026-10-10 05:06]. Merged by the user since the last hand-off (`9b5554b2`,
  2026-10-08 23:14), all ff-only except `sdk/probes-e` (merge commit `4b47a08d`): fix/turn-limited,
  bayes/3b-rr, bayes/4-r, fix/guard-agent-r, remove-codex-r, relock-tools, sdk/2 (with SDK-1), bayes/3c, bayes/hardening,
  fix/magg-cooldown, sdk/probes-e, sdk/3, fix/magg-1.3.0, bayes/5 (WP5 5a, docs), sdk/plan-gate-fork-backstop. One line each in §8.
  The four C10s since `b4bed8b8` (sdk/3, magg 1.3.0, bayes/5, fork backstop) all read `NEW vs known: []`, install_smoke
  283 passed / 1 failed (openpty) and eq_mutations 38/39 killed with 1 problem (§7 item 1) [v `H/.claude-work/c10/*.summary`].
- **C10 running** (user terminal, since 04:55): `sdk/plan-bash-gate` `7446f631`, which carries `sdk/env-channel` `ab06172a`.
  Partial summary at 05:06 [v]: lint_agents, prompt_budget, the guard and progress self-tests, `bash -n` (306 `*.sh`), instructor
  77, image_studio 125, sdk_integration 17, eq-wall 102, equilibrium_paths, moved_paths 100, pool_sha, wiki_check and hand_off 40
  all rc 0; eq_mutations 38/39 + 1 problem (as above); the pytest chunks and install_smoke still running. main must not move
  until it ends.
- **Installed stack = `b4bed8b8`** (sdk/3) [v `commit` in `~/.claude/.stack-manifest.json`, written 2026-10-09 22:59]. It
  contains the collector fix (`3975e35a`, `210eaeca`), so sessions started since then are collected correctly (docs/BAYES.md
  §A.11.5). Not installed yet: magg 1.3.0 (`MAGG_BACKEND_INIT_TIMEOUT=300`, `NETRC=/dev/null` for magg) and the fork backstop
  (`3f481922`, `0f40b9d0`). The Bayes packages are absent from the tools venv [v `importlib.metadata`: pymc, pytensor, nutpie,
  arviz, scipy missing; numpy 2.5.3]; the live fit record `~/.local/state/claude-agent-stack/usage/bayes.json.rec` holds 4 rows,
  the newest `skipped:no-pymc` at 2026-10-10 04:12 [v]. The installed `stack_limits.py` has `BAYES_LIVE = frozenset()` [v].
  Doctor after the `b4bed8b8` install: not seen [unverified].
- **Bayes**: on main: WP0-WP4, WP3c (`./install.sh --with-bayes`, the hashed `requirements/tools-bayes.txt`, doctor's `bayes:`
  line, `STACK_BAYES` a guard knob), hardening (the fit holds `accel.lock`; an orphaned fit ends itself at 930 s; a hardlinked
  `accel.lock` is refused) and WP5 5a (docs/BAYES.md §A.9-§A.12: informativeness I1-I3, production and any-regime strata, fold
  protocol, data route, drift spec, A.3 row 5 option (c)). Every family is shadow-only. Built and reviewed, not merged: 5c
  (`bayes/5-drift`) and 5b (`bayes/5b`). Waiting: 5d rehearsal and 5f binding verdict (§4). Until 5c is merged and installed,
  the fitter writes `drift` as `{}`; until 5b is, A.3 row 5 still censors clean finishes (BAYES.md, open items) [r].
- **WP5 data** [r `W/.claude-work/bayes-wp5/route.md`, `hybrid/README.md`]: the 5-0 route is "partly yes" (hybrid); the hybrid
  backfill copy `W/.claude-work/bayes-wp5/hybrid/` (evidence_id `09f70d3e…78c7`; turns censored 451/975, ctx 460/975 per
  `hybrid/verify/verify.json` and BAYES.md, route.md's 461 did not reproduce) feeds the
  any-regime stratum and the 5d rehearsal only. The binding production verdict (5f) needs post-install sessions (BAYES.md §A.11.5).
- **SDK**: on main: SDK-1 (`tests/sdk_probes.py`, pinned `claude-agent-sdk==0.2.163`), SDK-2 (`stack_sdk.py` v2: Session, hosts,
  load check, exit codes 0-5), SDK-3 (the plan gate in agent_guard, the `entrypoint` usage column, doctor's sdk line, the
  `stack_sdk.py.lock` staged) and the fork backstop (a forked skill's child is judged by a `plan/skill-<tool_use_id>` marker,
  probe E3c1). Built and reviewed, awaiting C10/merge: `sdk/plan-bash-gate` (+ `sdk/env-channel`), `sdk/probes-e2`. In progress:
  `sdk/probes-e3`. Waiting: SDK-4 (docs), the `Session` keychain fix.
- **Paid probes** [v reports and ledgers in `M/.claude-work/sdk/probes/`]: four E runs (2026-10-09 `-e`, `-e-2`, `-e-3`;
  2026-10-10 `-e`). The 2026-10-09 envelope ($2.00) is used up: $1.9188 counted conservatively (the 2026-10-10 ledger's
  envelope event gives prior use 1.404122, sessions without a reported cost at their cap; that run spent 0.5147). Answers:
  E2a yes (environment permission channel: fixed on `sdk/env-channel`); E3a yes; E3b yes; E3c1 a fork child's `meta.json` has
  no `toolUseId` (fixed: the fork backstop on main); E3c2a yes and E3e yes (2026-10-10); E2b no; E2c1/E2c2 no; E3d unknown; E1
  unknown in every run (2026-10-10: the control ran under plan, nothing calibrated). From that run [r commit `3ba2f39b`]: an
  unruled file-writing Bash command ran under plan in an unattended Session, 2 of 2 times; fixed on `sdk/plan-bash-gate`,
  unverified against the real CLI. Analysis: `W/.claude-work/sdk/probes-e-analysis/analysis.md`.
- **Wiki** (`M/github-wiki`, its own repository): the 2026-10-09 removals pushed; `master` = `origin/master` = `wiki/main` =
  `01af81a` locally [v]. Whether the stray remote `main` (`4a2c236`) is gone: unverified (Q-W).

Environment notes: agent Bash sandboxes write their own worktree, M and `$TMPDIR`, not H; the Write/Edit tools of a session
running in W refuse paths in M, so job worktrees live under `W/.claude-work/worktrees/`. The sandbox cannot create
`tools/instructor`: make a worktree with `git worktree add --no-checkout`, `git read-tree HEAD`, `git checkout -- .
':(exclude)tools/instructor'`; it then shows 12 ` D tools/instructor/*` entries that are never staged (explicit `git add`
paths only). A full C10 runs only from the user's terminal (`cd ~`; clones `/tmp/c10s` and `/tmp/c10s-p`; never two at once;
about 1 h). The shared uv cache is corrupt (`uv run --no-cache`). Read-only reviewers cannot run code under `.claude-work`;
about 130 tests fail on paths there (compare against the known ids). Agents cannot read `<state>/**/*.lock` or
`~/.claude/stack.env`, so `doctor.sh` FAILs inside a sandbox; the user runs it. The stack rules file is at its prompt_budget
gate (`rules` 11588 chars = base 12198 − 5.0% [v the running C10's prompt_budget log]): any rules text needs a trim or a gate
decision.

## 2. Decisions that stand (USER; do not re-ask)

1. Isolation backend: Apple `container` 1.5.0; Docker dropped. c0 runbook: `hand_off/RUNBOOK_c0.md` (whether c0 ran: unverified).
2. Images: distroless (2026-10-06, `lib/eq-container/DESIGN_DISTROLESS.md`): static GNU bash 5.3 + patches 001-020 from the
   GPG-signed source in a pinned Alpine builder (key `7C0135FB088AAF6C66C650B9BB5869F064EA74AB`); no perl; CP/CR on distroless
   cc + glibc python-build-standalone; no Debian `full` image; Rust and Haskell deferred (exit 10); node, julia, jvm on
   distroless cc, go on scratch; jq 1.8.2 static, busybox musl, uv musl 0.12.22; MongoDB and PostgreSQL out. Every final image is
   FROM the digest-pinned `gcr.io/distroless/cc-debian13` or scratch.
3. Oracle residuals and HANDOFF_FULL 6.10 deferred; Stage 3 D1-D5 need the user's approval.
4. `mcp-server-craft` stays retired (`e045482`). 5. Plugin autoUpdate for claude-plugins-official: on.
6. Stage 4 build threshold: 3% pooled, 2% per class, 4 of 5 sessions.
7. SendMessage-resume rule: restrict. Subagent cache TTL: default. `omitClaudeMd`: measure offline first.
8. ONE_TREE default: archive unique-commit rows as git bundles; dry-run only; `--apply` never by an agent.
9. A4 paid probe approved (one call, ≤ $0.25), user-run (`hand_off/A4_FOLD.md`).
10. Nobody but the user removes worktrees, branches or rescue refs (agents list them). Harness `isolation: "worktree"` worktrees
    stay in `M/.claude/worktrees`.
11. 2026-10-07: H5 leaves the pre-registration (COMPARE_eq §12 A7); `eq_check.sh` E7 cell-pass rule (A8). COMPARE_eq §12 A9 is the
    repository-move record, so the calibration run plan's A9/A10 ids need re-checking [unverified].
12. 2026-10-08: orchestrator soft prompt 140M, `hard.prompt` 300M, exact pins; F2 yes (env can only lower `hard.*`).
13. 2026-10-08 (`shrink-on`): no masker means no log; explicit `on` keeps the success gate.
14. 2026-10-09: the stack is Claude-only (`2b6050fe`); that backlog is dropped.
15. 2026-10-09, WP5 (`W/.claude-work/bayes-wp5/plan.md`): Q-A scope = 5-0, 5a, 5b, 5c (drift producer), 5d, 5f; Q-C backfill
    first, else ≥ 5 post-install sessions; Q-D the user runs every fit from a terminal with no C10, eq run or other fit active;
    A.3 row 5 = option (c) (clean finishes exempt). Q-B (5a-5c before 10b) is superseded by decision 16.
16. **2026-10-10, new order:** step 10b (this redo) comes before step 11 and records the current state, so step 11 can start
    gathering data in shadow; 5c, 5b and everything else move after step 11; the FINAL docs and wiki rewrite stays last (§4).
17. Merges: a C10 on the tip, then `git merge --ff-only` (one at a time; main still during a C10). Docs-only
    `docs/handoff-10b`: `git merge --no-ff`, no C10 (2026-10-10).
18. Probe envelopes: 2026-10-09 $2.00 (used up, §1). 2026-10-10 `e3-2026-10-10`: $0.45 beyond it, E1 only, run cap and
    `SDK_PROBES_E_CONSENT` 0.38 [r commit `c8b6a431`]; the paid run still needs the user's fresh go-ahead (§4 step 11).
19. Bayes pilots pass `permission_mode="acceptEdits"` explicitly and log `gate_waived=true` (sdk/plan.md D3, decision (d)).
    WP5 never edits `BAYES_LIVE` and spends no API money.
20. sdk/3's plan gate stopped after 4 security rounds; its residual gaps are CONFIG.md "Known gaps of the plan gate". Reopen
    only with new evidence.

Standing constraints: never push, no forge writes (the user publishes the repo and the wiki); agents never run `install.sh`
and never merge into main; paid runs only inside a consented envelope and only by the user; no Haiku outside a consented
probe; security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, stack_sdk.py, agent tool
lists) get security-auditor + code-reviewer before merge; serialize agent_guard.py / settings.json / install.sh / blackcat.md;
`lib/eq-wall` and `tools/instructor` are protected; the shared git stash is off-limits (WIP commits); merge problems go to
main-coder (no force, reset or stash); do not delete H or its branch `golden/handoff-plan-continuation-c09473` (H holds
`c10-ref.sh`).

## 3. Not merged / awaiting the user

Tips [v `git -C M rev-parse`, 05:06]; worktrees under `W/.claude-work/`. Rescue refs `refs/rescue/<branch>-pre-main-merge` hold
each branch's tip before main `c1ded439` was merged in (`W/.claude-work/main-merge-c1ded439/plan.md`: clean merges, tests green).

| branch | tip | content | reviews | next |
|---|---|---|---|---|
| `sdk/plan-bash-gate` (worktree `worktrees/plan-bash-gate`) | `7446f631` | host none passes a `--settings` overlay (`PLAN_GATE`: `useAutoModeDuringPlan` false, sandbox `autoAllowBashIfSandboxed` false) under plan and a waived gate; a caller's overlay naming those keys is refused; 125/125 mutants; `stack_sdk.py` at 1000 lines (its cap). Carries `sdk/env-channel` `ab06172a`: Session refuses `CLAUDE_BG_*`, `CLAUDE_CODE_SESSION_KIND`, `CLAUDE_CODE_SANDBOXED` (env and `os.environ`) and passes the kind as `""`; `with-stack-env` skips them; agent_guard denies a Bash command that assigns or exports one; CONFIG.md Known gaps, agent-sdk.md; mutants 10/10 and 20/20 | security-auditor (fixes `a0454d3d`, `47eeaeaf`; `b99b1187`, `898a5f01`) [r] | C10 running; then ff-only (§5 step 1) |
| `docs/handoff-10b` (worktree `worktrees/handoff-10b`) | this commit | this hand_off redo | — | `merge --no-ff` (§5 step 2) |
| `bayes/5-drift` (`worktrees/bayes-5-drift`) | `095eddc8` | 5c: `stack_bayes.py fit` writes `drift.<family>` (last 5 sessions, ≥ 20 rows / 10 uncensored / 3 sessions, randomized PIT, session-clustered KS p, sticky breach) and `fit --regime HEX16`; 10/10 mutants; drift step about 0.9 s on the WP2 copy | security-auditor + code-reviewer (fixes `b02246c8`) [r] | after step 11: main merged in, C10, ff-only |
| `bayes/5b` (`worktrees/bayes-5b`) | `44aa3b71` | 5b: `tests/b1_backtest.py` informativeness I1-I3, strata, fold gates, power; `tests/b1_folds.py` fold driver (refuses the live state, takes `accel.lock`); `censor_flags` row 5 option (c); 26/26 mutants (`W/.claude-work/bayes-5b/mutants.out`). Based on `9a46184b`, 4 commits behind main; `git merge-tree` against `bayes/5-drift`: clean | code-reviewer, security-auditor (S1-S5 `194a297d`, `44aa3b71`) [r] | after step 11, after `bayes/5-drift` (its driver needs 5c's `fit --regime`): main merged in, C10, ff-only |
| `sdk/probes-e2` (`wt-probes-e2`) | `373be35f` | E1′ (verifier main thread), E3P, the cross-run ledger gate; 81/81 mutants. Its paid run was the 2026-10-10 `-e` run | code-reviewer (`ed37cc88`, `9129585f`) [r] | lands with `sdk/probes-e3`, which contains it |
| `sdk/probes-e3` (`worktrees/probes-e3`) | `dcf99a08`, **in progress** | the corrected E1 rerun under envelope `e3-2026-10-10`; spend-review fixes `f42e24f7`; contains `sdk/probes-e2` and `sdk/plan-bash-gate`. Open (queue): the E1d leg strips `PLAN_GATE` (`settings=None`), overlay legs keep the gate keys, one leg tests the gate; refresh the two `test_sdk_probes_e_fake` expectations and the probes-e mutation baseline | spend review done [r]; final review after the open items | §4 step 11 |
| `golden/handoff-plan-continuation-c09473` (H) | `c4bbedc7` | superseded hand-off | — | keep while H holds `c10-ref.sh` |
| older side branches | — | `s4-l7-l10` `d2467782` ("Minimum first" + A/B test), `worktree-agent-a06763fbda9c482d4` `2130bc0f` (cache-stable prefix), `worktree-agent-a08001452f6ef3994` `ce17278b` (installer skips existing CLI tools), `worktree-agent-ae67658dcd0599872` `b7d3ba97` (drop host-app content) | — | the user decides; cleanup §4 step 19 |

## 4. Left to do, in order (2026-10-10)

Each code branch: review by trigger, the user's C10 on its tip, the user's `merge --ff-only`; a reinstall when the change should go
live. Exact commands in §5.

| # | step | owner | done-when |
|---|---|---|---|
| 1 | Finish the C10 of `sdk/plan-bash-gate` `7446f631`; ff-merge it (lands `sdk/env-channel` too) | user | summary `NEW vs known: []`, install_smoke 1 failed (openpty); main = `7446f631` |
| 2 | Merge `docs/handoff-10b` with `--no-ff` (step 10b; docs only, no C10) | user | main has the merge commit |
| 3 | **Step 11:** `./install.sh --with-bayes` on that main: shadow mode, `BAYES_LIVE` empty; Q-E default: the current pin (pytensor 3.3.2). Then work normally: the collector gathers rows and starts shadow fits | user | exit 0; manifest commit = main; doctor 0 FAIL and `bayes: venv ok (…; STACK_BAYES=shadow; …)` |
| 4 | `bayes/5-drift`: merge main in (merge commit, rescue ref, tests), C10, ff-only | python-engineer or main-coder; user | main contains `095eddc8`'s work; C10 green |
| 5 | `bayes/5b`: the same, after step 4 | same | same. Reinstall afterwards (plain `./install.sh`, the Bayes packages stay) so the drift producer and the row 5 rule run live; that run also checks that a plain run leaves the shared pins unchanged |
| 6 | 5d rehearsal (non-binding): the fold driver and the backtest on the fixture, the WP2 copy and the hybrid copy, on the installed lock; fold times at 8 × 4000, gates, verdict | data-scientist; the user runs the fits | `M/.claude-work/bayes/wp5/rehearsal.md` |
| 7 | 5f binding verdict: corrected copy of the live state, fold hyperparameters from the shipped fitter, `tests/b1_backtest.py` with ≥ 3 eligible folds on the production stratum, a second-route recount; result in docs/BAYES.md §A.10b, handed to WP6; no `BAYES_LIVE` edit. Needs step 3 and enough post-install sessions (no count promised: BAYES.md §A.11.5) | data-scientist, verifier; the user runs the fits | ACCEPT, REJECT or `blocked:gate` per family with informativeness met, or `informative: false` reported as such |
| 8 | 5g (only if the corrected-data fits still diverge at `z_s`): reparameterize, documented first; the gates are never loosened | data-scientist, plan-reviewer, python-engineer | per the WP5 plan |
| 9 | Q-E: re-lock `requirements/tools-bayes.txt` to pytensor 3.3.3 (published 2026-10-02T14:13Z, eligible from 2026-10-10). Default: step 3 installs the current pin first; a re-lock is its own branch (lock tests, review, C10, ff), then `./install.sh --with-bayes` again | user decides; claude-code-engineer builds | lock header and pins agree; a fit on the new pin recorded |
| 10 | Q-F: what flips `BAYES_LIVE`. Default: a WP5 PASS is evidence for promotion item 2 only (BAYES.md promotion list: 3 gated refits, B1-T14, ≥ 5 shadow sessions with the would-vs-§4 report, the user's approval in CONFIG.md §9, drift `breach: false`); the flip is a WP6 reviewed commit with the user's yes per family, soft.agent first; FINAL documents "shadow, WP5 pending" unless the user says otherwise | user | answer recorded in the Bayes plan |
| 11 | Paid E1 probe: finish `sdk/probes-e3` (the open items in §3), its review, C10, ff-only; then the user's fresh go-ahead for envelope `e3-2026-10-10` ($0.45, run cap 0.38); dry run, then the paid run from M; then the analysis and the doc follow-ups | python-engineer, code-reviewer; user | a report in `M/.claude-work/sdk/probes/` with E1 calibrated (the control denied) or a stated reason |
| 12 | Guard backlog step 6: `RecursionError` in `readonly_violation` on `timeout 1 ` × ≥ 1000 (repro `W/.claude-work/guard-timeout-r4/rec.py`, plan :27): deny by rule, not by exception | claude-code-engineer on `fix/guard-backlog`; security-auditor + code-reviewer | a 1000+ chain test denies without the exception path; a mutant; suites green |
| 13 | Step 7: holes P1-P5 (`W/.claude-work/sec-r5/report.md:166-188`, repros `sec-r5/p1..p5.txt`) | same branch | each repro denied; a failing-before test and a mutant per hole; fuzz parity green |
| 14 | Step 8: `xargs`/wrapper chain speed (`W/.claude-work/sec-r6/report.md:70-95`) | same branch | a timing bound from the measurement; diff_fuzz verdicts unchanged |
| 15 | SDK-4: rewrite `dot-config/dot-claude/skills/claude-code-extensions/references/agent-sdk.md` with the probe outcomes, README "Your own Agent SDK app", CONFIG.md §9, `requirements/README.md:23`; then SDK-4v | claude-code-engineer, verifier | lint_agents, prompt_budget, wiki_check green; verifier PASS |
| 16 | `stack_sdk.Session` and `CLAUDE_CONFIG_DIR`: the CLI derives its keychain entry name from the config dir (traced in the 2.1.287 binary [unverified], no written report): fix (Q-K) | python-engineer; security-auditor | a reproducer and a fix with a test, or a documented gap |
| 17 | 10c, token economy (user request 2026-10-10): `bin/stack-run` writes a condensed result file (exit code, duration, pass/fail counts, last lines) beside its full log and prints only its path and one line; one rule: long commands run once through stack-run, wait, read the result file, open the full log only on failure, never tail intermediate output. Needs the user's go-ahead on the branch plan; the rule needs prompt_budget headroom (§1) | claude-code-engineer on `fix/stack-run-result`; code-reviewer | tests; C10; ff-only; reinstall |
| 18 | Parked findings (§7 items 1-5) | per item | each fixed with a test, or recorded as a known gap |
| 19 | **FINAL:** rewrite README.md, CONFIG.md, docs/*, requirements/README.md and the wiki to the final state (Claude-only, the Bayes pipeline, stack_sdk, the locks); re-check hand_off for drift; then the cleanup of finished worktrees, branches and rescue refs (§5 step 9) | claude-code-engineer or writer, verifier; the user pushes the wiki and removes refs | docs match code; wiki_check, redundancy, prompt_budget green; C10 + ff-only |

## 5. User steps (exact commands)

C10 (about 1 h; main must not move meanwhile; launch from `cd ~`):

```bash
cd ~ && bash /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb/.claude-work/c10/c10-ref.sh <branch>
```

Read its verdict (pass = `NEW vs known: []` and install_smoke `1 failed`, the openpty check; the script's text "expected 282
passed" is stale, 283 since sdk/3; eq_mutations reads `killed: 38, problems: 1` until §7 item 1 is fixed):

```bash
grep -E 'NEW vs known|install_smoke counts|eq_mutations|^end' /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb/.claude-work/c10/c10-<branch, / as ->-<sha8>.summary
```

1. **sdk/plan-bash-gate** (its C10 is running):

   ```bash
   grep -E 'NEW vs known|install_smoke counts|eq_mutations|^end' /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb/.claude-work/c10/c10-sdk-plan-bash-gate-7446f631.summary
   git -C /Users/pmrj/ZDone/claude-agent-stack merge --ff-only sdk/plan-bash-gate
   ```

   New failed ids: an agent fixes them on the branch, then a new C10.
2. **docs/handoff-10b** (no C10):

   ```bash
   git -C /Users/pmrj/ZDone/claude-agent-stack merge --no-ff docs/handoff-10b -m "Merge docs/handoff-10b: hand_off redo (step 10b)"
   git -C /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544/.claude-work/worktrees/handoff-10b status --short
   git -C /Users/pmrj/ZDone/claude-agent-stack worktree remove --force /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544/.claude-work/worktrees/handoff-10b
   git -C /Users/pmrj/ZDone/claude-agent-stack branch -d docs/handoff-10b
   ```

   The `status` line must list only the 12 ` D tools/instructor/*` entries before the `--force` removal.

3. **Step 11.** Quit every Claude Code session first. Add the flags you normally install with (`--with-lsp`, ...).

   ```bash
   cd /Users/pmrj/ZDone/claude-agent-stack && ./install.sh --dry-run --with-bayes
   cd /Users/pmrj/ZDone/claude-agent-stack && ./install.sh --with-bayes
   grep -o '"commit": *"[0-9a-f]*"' ~/.claude/.stack-manifest.json; git -C /Users/pmrj/ZDone/claude-agent-stack rev-parse main
   bash ~/.claude/bin/doctor.sh
   grep -n '^BAYES_LIVE' ~/.claude/hooks/stack_limits.py; grep -n 'STACK_BAYES' ~/.claude/stack.env
   ```

   Expect: the two commits equal; doctor ends with `done.`, 0 FAIL, and prints `bayes: venv ok (pymc 6.3.2, pytensor 3.3.2,
   nutpie 0.16.11, arviz 1.3.0, scipy 1.18.1, numpy 2.5.3; STACK_BAYES=shadow; last fit: …)` (the pins of
   `requirements/tools-bayes.txt`); `BAYES_LIVE = frozenset()`; no
   `STACK_BAYES` line, or `shadow`. In a session, `/stack-doctor` runs the same check. The fits then run in shadow on their own
   (`usage/bayes.json.rec` records each; `STACK_BAYES=off` in stack.env stops them). Undo: `./install.sh --restore`.
4. **bayes/5-drift**, then **bayes/5b** (after an agent merges main into each): the C10 above with `bayes/5-drift`, then
   `git -C /Users/pmrj/ZDone/claude-agent-stack merge --ff-only bayes/5-drift`; the same for `bayes/5b`. Then the plain
   reinstall, with the shared-pin check around it (quit every Claude Code session first):

   ```bash
   uv pip freeze --python ~/.claude/venvs/tools/bin/python > "$TMPDIR/tools-before.txt"
   cd /Users/pmrj/ZDone/claude-agent-stack && ./install.sh
   uv pip freeze --python ~/.claude/venvs/tools/bin/python > "$TMPDIR/tools-after.txt"; diff "$TMPDIR/tools-before.txt" "$TMPDIR/tools-after.txt" && echo pins-unchanged
   ```
5. **WP5 fits (5d, 5f)**: only from your terminal, with no C10, eq run or other fit active; the data-scientist hands you the
   exact driver lines. If the sandbox denies the live-state copy:
   `cp -Rp ~/.local/state/claude-agent-stack/{usage,limits} /Users/pmrj/ZDone/claude-agent-stack/.claude-work/bayes/wp5/data/`.
6. **Paid E1 rerun** (after `sdk/probes-e3` is merged, and only with your go-ahead; commands as of `dcf99a08`, re-read the
   script's docstring first; run from M):

   ```bash
   cd /Users/pmrj/ZDone/claude-agent-stack && uv run --locked --script tests/sdk_probes_e.py --envelope e3-2026-10-10 --only E1
   cd /Users/pmrj/ZDone/claude-agent-stack && SDK_PROBES_E_CONSENT=0.38 uv run --locked --script tests/sdk_probes_e.py --paid --envelope e3-2026-10-10 --only E1
   ```

7. **Wiki** (Q-W, read-only): `git -C /Users/pmrj/ZDone/claude-agent-stack/github-wiki ls-remote origin`; push the FINAL
   rewrite yourself.
8. Carried over: Runtime Equilibrium live checks (README "Live checks" 9; `hand_off/R3_CONTAINER_CHECKLIST.md` C14-C23, D1-D9);
   the paid calibration plan `hand_off/EQ_CALIBRATION_RUN_PLAN.md`; the A4 probe (`hand_off/A4_FOLD.md`, not run: no output
   under `dot-config/dot-equilibrium/runs/probes/`); stop an orphan `disc3.py` if `pgrep -fl disc3.py` finds one.
9. **Cleanup** (after FINAL; yours, with each removal confirmed). A worktree made in the sandbox shows only the 12
   ` D tools/instructor/*` entries, so check `git -C <worktree> status --short` first; `remove --force` discards exactly those.

   ```bash
   git -C /Users/pmrj/ZDone/claude-agent-stack worktree remove --force <worktree path>
   git -C /Users/pmrj/ZDone/claude-agent-stack branch -d <merged branch>
   git -C /Users/pmrj/ZDone/claude-agent-stack update-ref -d refs/rescue/<name>
   ```

   Candidates [v 05:06]: worktrees `W/.claude-work/wt-turn-limited`, `wt-remove-codex`, `wt-guard-timeout`, `wt-probes-e2` and
   `W/.claude-work/worktrees/*` once merged, H's `c10-af`, `c10-base`, `c10-er2`, `eqr-*`, `hs-1007`, `post-merge`, and about
   30 `M/.claude/worktrees/agent-*`; merged branches `fix/turn-limited`, `bayes/4-r`, `fix/guard-agent-r`, `remove-codex-r`,
   `handoff-docs`, `handoff-docs-2`, `golden/*` except H's; superseded unmerged ones (need `branch -D`, your call):
   `bayes/3b`, `bayes/3b-r`, `bayes/4`, `fix/guard-agent`, `fix/guard-timeout`, `-r`, `-r-ff`, `-r-on-main`, `remove-codex`;
   rescue refs `refs/rescue/{shrink-on-51dcd288, handoff-bf6dd63, sdk-3-pre-merge-main-82248763}`, and the five
   `*-pre-main-merge` refs plus `probes-e3-pre-plan-bash-gate` once their branches are merged. `RESET_TO_MAIN.sh --archive` /
   `--apply` stay yours (dry run first).

## 6. Verification facts that matter

- C10 pass criteria: `NEW vs known: []` (7 known environment ids, all passing outside the sandbox), install_smoke exactly 1
  failure (the openpty pty check; 283 passed since sdk/3, 282 before), every other gate rc 0 except eq_mutations (§7 item 1).
  A targeted-test pass is not a C10 (Bayes 3a was merged on one and broke 12 tests).
- `container` 1.5.0 flags, from the user's `container run --help`: present `--rm --read-only --cap-drop --init --user --uid --gid
  -m -c --ulimit --tmpfs <path> --mount ...,readonly -w --name --network`; absent `--pids-limit`, `--security-opt` (`--ulimit
  nproc=512` substitutes); `--network none` works per the user's spike. Unverified: `--tmpfs` `size=`/`mode=`, the image digest
  field path, whether the fake-container tests match the real CLI.
- A4 item 4 needs the paid probe (`--json-schema` under `--tools`; `--agent` tools ∩ `--tools` under `-p`; `--settings` cannot
  widen; `Skill` under `--strict-mcp-config`).
- Probe facts for the docs (CLI 2.1.287): a subagent's PreToolUse `permission_mode` is its own (E3b); a forked skill into an
  `acceptEdits` agent writes under a plan-mode main thread (E3a); agents created mid-session are not loaded (E2b); no agents
  load from above `.git` or from an add-dir's subdirectory (E2c1, E2c2); an Agent child's `toolUseId` survives a SendMessage
  resume (E3c2a) and its `meta.json` exists at its first tool call (E3e).
- Bayes fit cost [r BAYES.md]: a full fit at 8 × 4000 takes 348 s wall and 1248 MiB; one verdict round is about one full fit
  plus 6 fold fits (30-40 min of 8-core CPU, an estimate).

## 7. Open items

1. **eq_mutations `callerpolicy` is not applied since sdk/3** [v]: `tests/eq_mutations.py:73` anchors on `if type_why:` /
   `deny(type_why)` / `# the equilibrium`, but sdk/3 put `why = plan_gate_violation(...)` between them
   (`agent_guard.py:2124-2126` on main), so the mutant ERRORs ("anchor occurs [0] times") and the caller-policy deny is
   untested by the mutation step. Fix: re-anchor the mutant (test-only branch, its own C10). Before the guard backlog (steps
   12-14), which edits agent_guard.py.
2. `c10-ref.sh` still prints "expected 282 passed" (283 since sdk/3): cosmetic, in H.
3. SDK, before any patch [r queue]: a host-none Session's env or `os.environ` can set `CLAUDE_CODE_MANAGED_SETTINGS_PATH`,
   `CLAUDE_CODE_REMOTE_SETTINGS_PATH`, `CLAUDE_CODE_DISABLE_ADMIN_ENV_UNION` (`ENV_REFUSED` does not match them; a managed or
   policy setting would outrank `PLAN_GATE`); `s.extra["settings"]` set after `__init__` adds a second `--settings` flag (the
   same trust level as `options()`). Probe first.
4. Bayes fold driver (`tests/b1_folds.py`, low, pre-existing) [r queue]: a SIGINT and a SIGTERM pending together can still skip
   the fit's `killpg`; a signal between `Popen()` and the `try` in `run_fit` leaves the fit running up to 930 s.
5. Equilibrium broker TOCTOU: `load_wall_module` vs `Wall.start` in `eq_harness` (latent, MEDIUM, pre-existing).
6. Unverified: doctor's output after the `b4bed8b8` install; transcript retention (`cleanupPeriodDays` unset; the 30-day default
   bounds any later backfill; the oldest window session is from 2026-10-03); a live install's collector holding `accel.lock`;
   whether nutpie starts a process that would outlive the 930 s cap; the wiki's stray remote `main`; the keychain finding
   (step 16).
7. `output_shrink.py report` with no argument, run from a linked worktree, reads that worktree's empty log: pass M.
8. Two cosmetic `limits-raise` points left: `Limits.where` wording when the seed is None; `bin/stack-budget` shows raw seeds on
   a fallback.

## 8. What is merged (one line each; all ancestors of main)

| item | note |
|---|---|
| orch-bash `f5de4f6` | orchestrator holds `Bash` with the web check and git-guard gaps closed |
| handoff-docs `a3653dd`, wiki | RUNBOOK_c0, A4_FOLD, a4_fold.py, c0_support; the wiki is GitHub's wiki, `docs/wiki/` untracked, `tests/wiki_check.py` |
| l2-final `7c7137d` | `output_shrink` PostToolUse hook |
| r3-ready `84ba493`, eq-pins, eq-cli-install `321f037`, eq-distroless `fd0a2a3` | the Apple `container` port: `lib/eq-container`, `lib/eq-wall`, `install.sh --with-eq-container`, distroless images |
| 3d-agents `41e2aae` | rigger-animator, sculptor-painter, procedural-3d-ui + 7 skills |
| l5-land `6d9713a` | `stack_progress.py` observe-only early stop |
| claude-md-block `485b855` | installer-managed `~/.claude/CLAUDE.md` block, byte-exact restore |
| s4-instructor `cf8cf68` | deterministic instructor `tools/instructor` (`check-suite`, `ff-merge`, `worktree-audit`) |
| toolsmith `2ec6e2c` | `toolsmith` agent + `bin/stack-install` |
| reset-to-main `76e1cd4` | `hand_off/RESET_TO_MAIN.sh` (dry run by default) |
| l7-mech `a05d508`, s3-integ `b1a0703` | B1 hand-back check, B3 `first_write`, L10 trims; Stage 3 quality pass |
| eq-track `c0b2d8d`, eq-runtime-2 `258d3a35` | the harness tracked as `dot-config/dot-equilibrium`; p6/p7/CLI/E_rt, A6-A8, 183 harness mutants |
| audit-fixes `ad10c9ba` | no-push git gaps in agent_guard, web check, STACK_HOOK_RE |
| docs-reorg `f20c7a89`, hs-update-1007b, hs-next, dot-config `b0ddf192` | layout, requirements; A9 move under `dot-config/`, single installer |
| limits-raise `52c1abcc`, hand_off `d6046693` | orchestrator soft prompt 140M, `hard.prompt` 300M, F2 |
| bayes/3a `91fd17d2`, shrink-on `a0791669`, bayes-3a-fixes `47dce9f4` | WP0a fixture, BAYES.md v3, WP3a shadow tier + grid; output_shrink cuts Bash results over 8000 chars by default, `bin/stack-run`; staging and lint fixes |
| hand_off `9b5554b2` | the 2026-10-08 record |
| fix/turn-limited `210eaeca` | collector: a SubagentHandback ending is the run's report, not a turn-limit cut (`3975e35a`); a delivered hand-back keeps its STATUS |
| bayes/3b-rr `c57da0ab` | WP3b detached fitter `stack_bayes.py`, `stack_usage.bayes_fit` |
| bayes/4-r `3ba069ee` | WP4 scheduler reads the sched block of bayes.json (`load_bayes_sched`) |
| fix/guard-agent-r `4a027a0d` | guard: the command position kept past wrapper arguments, `env -S`, zsh clobber and leading redirections; long wrapper value chains bounded (fail closed) |
| remove-codex-r `2b6050fe` | the Codex implementation removed; Claude-only (decision 14) |
| relock-tools `bbfc1b01` | tools, sci and ml locks re-locked, hashed, 7-day cooldown (cutoff 2026-10-02) |
| sdk/2 `a9250016` | SDK-1 probes `tests/sdk_probes.py`; `stack_sdk.py` v2; SDK-2r rounds 1-4; 92 mutants killed |
| bayes/3c `6b563cd1` | `--with-bayes`, the hashed `tools-bayes.txt`, doctor's bayes line, `STACK_BAYES` a guard knob |
| bayes/hardening `c4f29e30` | the fit holds `accel.lock`; orphaned fit ends at 930 s; hardlinked `accel.lock` refused (work order steps 9, 10) |
| fix/magg-cooldown `82248763` | `MAGG_EXCLUDE_NEWER` 2026-09-22 → 2026-10-02 (step 5) |
| sdk/probes-e `4b47a08d` | paid probe set E1-E3, dry-run default, $0 fake suite (a merge commit) |
| sdk/3 `b4bed8b8` | plan gate (builders, Workflow, forked skills, resumes), host-stop release, `entrypoint` column, doctor sdk line, `stack_sdk.py.lock` staged; 4 security rounds; CONFIG.md "Known gaps of the plan gate" |
| fix/magg-1.3.0 `d119def2` | magg 1.2.1 → 1.3.0; mcp-broker `MAGG_BACKEND_INIT_TIMEOUT=300`; `NETRC=/dev/null` for magg (step 13) |
| bayes/5 `9a46184b` | WP5 5a design text in docs/BAYES.md (§A.9-§A.12), 2 review rounds |
| sdk/plan-gate-fork-backstop `c1ded439` | the fork backstop joins on a `skill-` marker (probe E3c1); review fixes `0f40b9d0` |

## 9. Plans and pointers

- Work order: `H/.claude-work/work-order-1008/plan.md` (steps 1-14, 10b, FINAL; its end-game line predates decision 16).
- WP5: `W/.claude-work/bayes-wp5/plan.md`, `route.md`, `hybrid/README.md`, `hybrid/MANIFEST.json`, `hybrid/verify/verify.json`,
  `power/`. Bayes program: `H/.claude-work/bayes/plan.md`; `M/docs/BAYES.md` (promotion items, §A.9-§A.12, open items at the end).
- SDK: `H/.claude-work/sdk/plan.md` (SDK-4 row, D3), `H/.claude-work/sdk/sdk2-design.md`; probe analysis
  `W/.claude-work/sdk/probes-e-analysis/analysis.md`; reports and ledgers `M/.claude-work/sdk/probes/2026-10-0{9,10}*`.
- Plan gate: CONFIG.md "Known gaps of the plan gate". Code: `dot-config/dot-claude/hooks/agent_guard.py`,
  `hooks/stack_bayes.py`, `hooks/stack_limits.py`, `bin/stack_sdk.py` (+ `.lock`), `bin/doctor.sh`.
- Guard backlog evidence: `W/.claude-work/guard-timeout-r4/` (`plan.md:27`, `rec.py`), `W/.claude-work/sec-r5/`, `sec-r6/report.md`.
- C10: `H/.claude-work/c10/c10-ref.sh` and its summaries. Merge-main record: `W/.claude-work/main-merge-c1ded439/plan.md`.
- Data: frozen WP2 copy `M/.claude-work/bayes/data/`, WP2 logs `M/.claude-work/bayes/wp2/`; live state
  `~/.local/state/claude-agent-stack/` (guard per-session dirs pruned after 3 idle days; snapshots kept 30 days).
