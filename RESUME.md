# RESUME — B0-B3 campaign stopped 2026-10-03: deploy, data, next steps

- Main checkout M = `/Users/pmrj/ZDone/claude-agent-stack`. Local main = 19bcd56 plus the commit that adds this file.
- Campaign worktree W = `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0` (branch `golden/stack-doctor-a3c277` at 0b3e022).
- Agents pushed nothing.
- "Verified" = checked against git or the files on 2026-10-03 between 13:09 and 13:12. Everything else is marked "unverified".
- The previous RESUME (state 0a04a59) is still available: `git show 44c9fd5:RESUME.md`. Its §A commit table and its full B1/B2 specification are cited from there and not repeated here.

## 1. Deploy (user steps, in order)
| # | Step | State |
|---|---|---|
| 1 | Confirm that main contains 0b3e022 and 19bcd56: `git -C M merge-base --is-ancestor 0b3e022 main; git -C M merge-base --is-ancestor 19bcd56 main`. 0b3e022 = stack-doctor runs doctor.sh from a UserPromptExpansion hook. 19bcd56 = stack-budget security fix. | Verified: both exit 0. 0b3e022 is the parent of 19bcd56, so no fast-forward was needed. The reported "48 pass on main, 196 in related suites" for 19bcd56 is unverified. Its commit message says the 20 proofs in tests/test_stack_budget_security.py all fail on 44c9fd5. |
| 2 | Run `./install.sh` in M | User's step |
| 3 | Restart Claude Code in a new session | User's step |
| 4 | Type `/stack-doctor` | It runs `doctor.sh --hook` outside the sandbox, limited to 150 s (0b3e022 commit message) |
| 5 | Optional: `bash tests/install_smoke.sh` outside the sandbox | User's step |

### Cleanup the sandbox blocked
`git worktree list` (verified) shows two prunable worktrees: `agent-ac6eb61d0c4133090` (1412edd) and `stack-budget-audit` (19bcd56, branch fix/stack-budget-audit).
```
git -C /Users/pmrj/ZDone/claude-agent-stack worktree prune
git -C /Users/pmrj/ZDone/claude-agent-stack branch -d fix/stack-budget-audit
git -C /Users/pmrj/ZDone/claude-agent-stack branch -d worktree-agent-ac6eb61d0c4133090
git -C /Users/pmrj/ZDone/claude-agent-stack branch -D rescue/stack-budget-audit-4b4e4a3   # optional
```
Still present and still your decision (verified, as in the old §E):
- worktree `.claude/worktrees/agent-a850e479080e75c19`: a0aafbd is not on main;
- 7 `rescue/*` refs;
- `golden/agents-workflow-token-optimization-573fd0`;
- `golden/blackcat-agent-delegation-enum-dd3b3a`;
- worktree `resume-770728` at 44c9fd5: copy its `.claude-work/resume/` files first (commands in the old §E).

### Known test failures
- 2 cases of `test_three_way_verdict_on_the_soft_limit` fail when STACK_LIMITS_SNAPSHOT is set. They pass under `env -u STACK_LIMITS_SNAPSHOT -u CLAUDE_SESSION_ID`. Reported, unverified.
- The stack-doctor report reportedly names 3 failures on clean HEAD. I did not find that report: unverified.
- `f4` in tests/test_protected_paths.py fails only because the sandbox's pytest tmp_path sits under /tmp/claude-501 (old §D).
- `tests/test_web_caps.py::test_stack_env_overrides` raises KeyError 'proxy_enabled', cause unknown (old §B2).

## 2. Where the data is
**`.claude-work/` is git-ignored (.gitignore:5).** All campaign data lives in **W/.claude-work/**:
- agents-baseline/: runs, grades, run trees;
- agents-b0b3/: plan, B1;
- older jobs.

**Do not remove W or delete its branch until that directory is copied.**

### Frozen pre-Bayesian baseline
- Tracked copy (this commit): `.claude-work/agents-baseline/stats_before/`. It is force-added, the same convention as 910275c.
- Original: `W/.claude-work/agents-baseline/stats_before/`.
- Contents: stats_before.json, stats_before.md, runs_before.csv, compute_stats.py, COMPARE.md, tools/, and inputs/ (MANIFEST.sha256, FROZEN_AT.txt, run_tree_manifest.tsv, the frozen CSVs and the final reports).
- Excluded: `.ruff_cache/` and the run tree `agents-baseline/run/` (1.3 GB per FROZEN_AT.txt). The run tree is indexed only, by inputs/run_tree_manifest.tsv (37,442 rows of path, bytes, sha256).
- Schema 1.0.0, frozen 2026-10-03 12:57:49 +0100. 77 runs, 40 graded.
- **Status partial:** the 37 new-install runs are ungraded, there are no replicates, and there is no cost field.

### Checks after the copy (verified)
- inputs/MANIFEST.sha256: 96/96 OK.
- Every file's sha256 is identical to the original.
- In a scratch copy at another path:
  - `tools/manifest.py --check`: 0 mismatches;
  - `compute_stats.py --check`: stats_before.json, stats_before.md and runs_before.csv rewritten byte-identical;
  - `tools/verify_second_route.py`: 122 checks, 0 mismatches.

### Path notes (files unedited)
- compute_stats.py and verify_second_route.py read only `./inputs`, so they work from any location.
- `tools/manifest.py` without `--check` re-hashes `../run/`. Here that is `.claude-work/agents-baseline/run/`, which exists only in W. A plain run in M would overwrite run_tree_manifest.tsv from an empty tree, so use `--check` only in M.
- `tools/collect_b0v2.py` defaults `--repo` to `agents-baseline/`, which is wrong. Always pass `--repo <checkout>`, as COMPARE.md §3 does.
- COMPARE.md's `run/<id>/` and `run/<id>.v2/` are W paths.

## 3. Job state: B0 baseline -> B1 Bayesian -> B2 Pareto -> B3 README (stopped by the user 2026-10-03)
Checkpoint: `W/.claude-work/agents-b0b3/plan.md`. Session fae82d02, new install.

### Finished
| Item | Where | State |
|---|---|---|
| 13 v2 re-runs on dedicated agents: P10 P11 P12 P14 P25 P30 P31 P32 P33 P34 P35 P36 P39 | W/.claude-work/agents-baseline/run/<id>.v2/ | Ungraded. P12 v2 ran on data-engineer and P14 v2 on writer: db-engineer and localizer are in ~/.claude/agents (verified), but the session refused them with "Agent type not found". Recheck after the restart. |
| 24 wave M runs: P40 P43 P44 P45 P48 P49 P51 P54-P68 P70 P71 | W/.claude-work/agents-baseline/run/<id>/ | Ungraded |
| Final reports of the 37 runs | stats_before/inputs/collected_fae82d02/run/<id>/final_*.txt | 37 dirs (verified) |
| T8b grades for the 18 old-install M ids P23 P25-P29 P31-P39 P41 P42 P46 | W/.claude-work/agents-baseline/grades_T8b.csv (copy in stats_before/inputs/baseline/) | 12 pass, 2 partial, 4 tool-absent (verified) |
| stats_before | §2 | Frozen, partial |
| C1 security audit of `stack budget` | Fix 19bcd56 | On main (verified) |
| B1a Bayesian design and prototype fit (data-scientist) | W/.claude-work/agents-b0b3/b1/: design.md, fit_prototype.py (+ .lock), fit_report.md, bayes_grid.py, data/, out/, out_run.log (all present, verified 13:11) | See the B1a findings below |

**B1a findings.**
- STATUS partial (BlackCat relay). Never reviewed.
- The fit exited 0 at 13:10 after 844 s.
- Divergence gates (fit_report.md §2, verified): turns fails (1 divergence), ctx(n) a/b fails (21), tool_calls fails (34). ctx, sec_per_call, static_cc, resume_ctx and the scope-2 ordinal pass.
- Soft limits run hot on held-out data: 10.3 % cap-hit rate against a 5 % target (§1).
- Collector fields hit_*, window_ctx and the session row are empty (§8).
- Scope 2 is provisional, on 22 graded ids.

**Inventory of the 37 run dirs** (verified, file counts): 36 present, 1 missing.
- **Missing: P14.v2.** The writer answered inline; its output is the collected final report only.
- P40 holds 18 files, all 0 bytes. They are the fixture tree of the find/rm task; the verdict is in its final report.
- v2 runs: P10 2, P11 4, P12 3, P25 2, P30 6021 (64 MB), P31 158 (57 MB), P32 5, P33 12, P34 4, P35 45 (39 MB), P36 10, P39 15.
- Wave M runs: P43 2694 (92 MB), P44 685 (32 MB), P45 11, P48 7, P49 4, P51 3, P54 2, P55 12, P56 16, P57 2, P58 10, P59 5, P60 5, P61 1, P62 16, P63 2, P64 4, P65 6, P66 3, P67 7, P68 13, P70 1106 (19 MB), P71 11.

### Settled decisions on design.md §10
These are the user's answers as relayed word for word by BlackCat (not checked against a user message):
- Q1 risk targets: "Looser 10% / 2% / 1%" (soft / turns / hard).
- Q2 env overrides: "Keep exact (Recommended)".
- Q3 stdlib grid tier: "Soft limits only (Recommended)".
- Q4 collector fix: "Yes, fix it (Recommended)".

### Remaining steps (do in this order)
1. **Fix the collector.**
   - Fill hit_*, window_ctx and the session row.
   - Fix the collect.py bug: the `<agentType>: ` description prefix breaks prompt-id tagging. The patch exists only in the copy stats_before/tools/collect_b0v2.py (FROZEN_AT.txt).
   - This is a stack code change: worktree, tests, ff to main. install.sh stays the user's step.
2. **Grade the 37 new-install runs** (COMPARE.md §1.1).
   - Grader: verifier with the T8b brief.
   - Rubric: the `check` column of prompts.csv. Vocabulary: `pass|partial|fail|tool-absent`.
   - Output: `grades_b0v2.csv` with a `variant` column (v1/v2). Save the brief word for word as `grader_brief.md`.
   - Then make frozen set v1.1:
     1. Copy the inputs into a new `stats_before_v1.1/inputs/`. Never edit `stats_before/inputs/`.
     2. Add the grade file to `GRADE_FILES`.
     3. Key the grade join by (prompt_id, variant, install).
     4. Set the schema to 1.1.0.
3. **B1a reruns.**
   - Reparameterize the turns, ctx(n) and tool_calls models with the Q1 risk targets, until they pass the gates.
   - Once step 2's grades land, copy grades_b0v2.csv and grades_T8b.csv into b1/data/ and run `fit_prototype.py --scope2-only`.
4. **plan-reviewer on design.md** (with fit_report.md).
   - Assumption: the original brief's python-engineer integration (stack_limits.py proposer + stack_sched refresh, tests) and verifier calibration backtest follow the review. BlackCat's revised order does not list them.
   - Spec: `git show 44c9fd5:RESUME.md`, §B3 "B1".
5. **B2 Pareto**, then verification (spec: old §B3 "B2"). Before and after runs follow the COMPARE.md procedure:
   1. Blind the grader, or reuse its brief word for word.
   2. Record the AFTER configuration: stack_commit, snap, STACK_SCHED_POLICY/profile, and the model per agent type.
   3. Run AFTER with the same prompts, agents and environment. Label `<PID> a1 run <agent>`, one primary run per prompt.
   4. Collect: `stats_before/tools/collect_b0v2.py --session <sid> --campaign-since <ISO> --repo <checkout> --out stats_after/inputs/collected_<sid8>`.
   5. Freeze: copy runs3.csv and the AFTER grades, write FROZEN_AT.txt, run `tools/manifest.py`.
   6. Copy compute_stats.py and change only SESSIONS, USAGE, GRADE_FILES, CAMPAIGN_SINCE and the join. SEED, B, MIN_N_CI, Z, METRICS, the regexes and DEFINITIONS stay byte-identical.
   7. Run it, then the second route. Both must pass before any number is reported. Metrics P1-P4 and the reading rules: COMPARE.md §4-§6.
6. **B3 README**, writer, last. Old todo items, not checked against current main:
   - README.md:251 says "venvs pin 3.12" / "pin --global 3.14". It should say "venvs pin 3.13; uv default stays 3.14".
   - Add `--python 3.13` to the test and venv commands.
   - Cover T7d, the read gate, learned limits (show/freeze/rollback), the `stack budget` CLI and the `/override-agent` forms.

**Optional extra data** (after step 3, when a lane is free):
- Batch X, for within-prompt variance: P07 r2, P20 r2, and r2 of P03 P04 P08 P10 P13 P15 P17 P18 P21 P30 P41 P42. Description key: `P03 r2 run <agent>`.
- Remaining wave M: P47 P50 P52 P53 P69 P72 P73 P74 P75 P76 P77 P78 P79 P80 P81 P82.
  - Network prompts: P83 P84 P85 P86.
  - Heavy lane, one run at a time: P47 P50 P52 P53 P69 P72 P79.
- Wave L:
  - P88 to ninja-coder;
  - P89 (MLX) alone on the Mac;
  - P91-P96 and P99 orchestrated;
  - P98 and P100.
- Held for the user:
  - P01/P02: blackcat, needs a fresh main session;
  - P22: consent, third-party MCP;
  - P87: consent, paid image-studio;
  - P97: `git init` is blocked under .claude-work.

### Run layout and keys
- Description format: `P10 v2 run <agent>`. collect.py's PID_RE is `^\s*(P\d{2,3})\b`, so a word boundary must follow the id.
- Overhead tasks are labelled `T<n>...`. Non-baseline tasks are C*, B1*, B2*, B3*.
- The old runs.csv and grades.csv are read-only history.
- Live rows go to `~/.local/state/claude-agent-stack/usage/runs3.csv`.

### Findings to carry (plan.md and run reports)
- The session-wide limit is 33 concurrent subagents, grandchildren included (P73 was refused; e0d0540).
- The verifier hook blocks `find -exec rm` (P40 report).
- The sandbox blocks uvx (`~/.local/share/uv/tools`).
- For P31 v2, rust-engineer probed `cargo +nightly`, which attempts a toolchain fetch; the sandbox stopped it. This is a grading note.
- Spawn budget: B0 as specified is about 90 spawns, far above the orchestrator's soft cap of about 32. Split the work or budget for it.
- Soft-limit stops are censored observations. Brief one fresh fixer per batch.
- Hooks run on /usr/bin/python3 3.9.6. Keep hook code 3.9-compatible.

### Still-valid user decisions (old §A)
- Bayesian inference for all learned values, then Pareto, then the README last.
- Scheduler advice-only.
- Effort display-only.
- Budget keys out of settings.json env.
- The turn gate allows the last turn.
- MCP cap as a fixed guard.
- Pinned floors: soft.prompt.orchestrator 80M, fan-out 32.

## 4. Open user decisions
| Item | Context |
|---|---|
| Install hlint/ormolu? | P35 v2 |
| Install gitleaks/pre-commit? | P71 |
| pnpm store vs sandbox | P33 v2 |
| Gradle on JDK 27 | P34 |
| Nightly Rust toolchain for Miri | P31 v2 |
| Playwright CLI run | P43 |
| Blender run outside the sandbox | P57 |
| Houdini | P59 |
| Renders | P64, P65 |
| Keep or delete the agent memory in `~/.claude/agent-memory/` | Verified listing, nothing deleted. With files: rust-engineer (MEMORY.md, toolchain_mac_sandbox.md), haskell-engineer (MEMORY.md, toolchain_macos_sandbox.md), julia-engineer (MEMORY.md, toolchain_julia_sandbox.md), node-engineer (MEMORY.md, sandbox_pnpm_quirks.md). Empty dirs: cuda, go, jvm, llm, python, security-engineer. |
| Consent items | P22, P87 |
| pyjwt 2.14.0, PYSEC-2026-4141 (requirements/tools.txt:616, verified) | Bump at the next re-lock, together with adding claude-agent-sdk |
| Old user-side checks, still open as far as known (old §B2) | install_smoke; doctor on the real install; both `agent_guard.py --self-test` forms; test_stack_env_overrides; live `/override-agent list`; live L1/L2/L4 and compaction; `tests/sdk_smoke.py` (billed); the Workflow probe |
| Old unreviewed items (old §D) | 1987381 got no separate review. The `fable` override sits above god-coder by design. |
| Remove W and branch golden/stack-doctor-a3c277 | Only after W/.claude-work has been copied |

## 5. Initial prompt for the new session
```
Read /Users/pmrj/ZDone/claude-agent-stack/RESUME.md. Run /stack-doctor first and report FAIL/WARN.
Then dispatch ONE orchestrator for RESUME §3 "Remaining steps", in this order:
(1) fix the collector (hit_*, window_ctx, session row; the collect.py agentType-prefix bug) in a worktree, tests, ff main
-> (2) grade the 37 new-install runs (grades_b0v2.csv, frozen set stats_before_v1.1 per COMPARE.md §1)
-> (3) B1a reruns: reparameterize turns, ctx(n), tool_calls with the new risk targets; --scope2-only once grades land
-> (4) plan-reviewer on design.md (+ fit_report.md), then integration and calibration backtest
-> (5) B2 Pareto + verification per COMPARE.md -> (6) B3 README last.
Optional extra data after step 3: batch X <DECISION: yes/no>; remaining wave M/network/wave L <DECISION: yes/no>.
Settled (design.md §10): risk targets soft 10% / turns 2% / hard 1%; env overrides kept exact;
stdlib grid tier for soft limits only; collector fix yes.
Data: campaign worktree /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0
(.claude-work/ is git-ignored there; never remove that worktree or its branch). B1 files: its .claude-work/agents-b0b3/b1/.
Frozen baseline (tracked): /Users/pmrj/ZDone/claude-agent-stack/.claude-work/agents-baseline/stats_before/ (COMPARE.md = protocol).
Budget: B0 is ~90 spawns vs the orchestrator's ~32 soft cap; 33 concurrent subagents session-wide.
User decisions:
- install hlint/ormolu (P35 v2): <DECISION: yes/no>
- install gitleaks/pre-commit (P71): <DECISION: yes/no>
- pnpm store vs sandbox (P33 v2): <DECISION: allow store path / skip>
- Gradle on JDK 27 (P34): <DECISION: install / skip>
- nightly Rust for Miri (P31 v2): <DECISION: install / skip>
- P43 Playwright CLI run: <DECISION: run / skip>
- P57 Blender outside the sandbox: <DECISION: I run it / skip>
- P59 Houdini: <DECISION: run / skip>
- P64/P65 renders: <DECISION: run / skip>
- agent-memory files under ~/.claude/agent-memory/: <DECISION: keep / delete>
- P22 third-party MCP: <DECISION: consent yes/no>
- P87 paid image-studio: <DECISION: consent yes/no>
- P01/P02 blackcat runs: <DECISION: run in a fresh main session / skip>
- P97 git init outside .claude-work: <DECISION: allowed dir / skip>
Rules: never push; never edit ~/.claude in place (stack changes go to the repo; install.sh is my step);
one accelerator job at a time; rebase, never force; db-engineer/localizer: check they load, else record the fallback.
```
