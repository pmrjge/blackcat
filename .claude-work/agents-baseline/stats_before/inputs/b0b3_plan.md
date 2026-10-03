# B0-B3 job (RESUME.md §B3) — orchestrator plan / checkpoint

Started 2026-10-03 12:05. Session fae82d02-7bf7-4439-9024-17b07cace5cc (new install live: python-engineer etc. in the agent list; collector schema 3 running).
Worktree: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0, branch golden/stack-doctor-a3c277 = main = 44c9fd5 at start.
Concurrent: a claude-code-engineer edits dot-claude/skills/stack-doctor/SKILL.md and files mentioning stack-doctor (README.md, CONFIG.md, install.sh, stack.env.example, dot-claude/bin/doctor.sh, tests/derive_thresholds.py, ...) in this checkout. Our builders: isolation worktree, `git commit -- <own paths>`, rebase before ff; never touch that skill.
State sources: RESUME.md (current, 0a04a59); .claude-work/agents-baseline/{RESUME,plan}.md (B0 data); .claude-work/agents-opt/RESUME.md is superseded (state 1dea215).

## Spawn budget (soft cap ~32 exceeded on purpose)
B0 as specified is one spawn per prompt run (13 re-runs + ~44 wave M + ~11 wave L incl. 7 orchestrated at ~4 each) ≈ 90 spawns; runs cannot be merged without destroying the per-run measurement. B1-B3 ≈ 12. Justification: the user asked for the RESUME job as written; each run is one data point for the B1 hierarchical fit and B2 front.

## Lanes
- Heavy lane (one at a time on this Mac): P47 P52 P53 P72 P79 P69, B2 benchmark re-runs; P89 (MLX) alone with nothing else running.
- GUI-capable agents (designer, motion-designer, cg-artist, vfx-td, game-engineer, doc-specialist, verifier): briefed "no computer use / screen control" so none does GUI work.
- Held (user): P01/P02 (blackcat main session), P22 (consent: 3rd-party MCP), P87 (consent: paid image-studio), P97 (git init blocked under .claude-work).
- P88 goes to ninja-coder (god-coder only if ninja fails; not planned).

## Description keys
Baseline runs: "P10 v2 run proof-checker" (collect.py PID_RE needs `P\d+` then a word boundary). Overhead counted by collect.py: "T..." (grading, collection). Non-baseline tasks: C*, B1*, B2*, B3* (not counted as baseline overhead).

## Tasks
| id | task | owner | inputs | depends-on | status | output |
|---|---|---|---|---|---|---|
| C1 | security review of stack budget CLI | security-auditor | dot-claude/bin/stack-budget | - | todo | report |
| T8b | grade 18 ungraded M ids | verifier | run/P23..P46, prompts.csv | - | todo | grades.csv append |
| R | re-run fallback ids on new agents (13) | target agents | prompts.csv | - | todo | run/<id>.v2/ |
| Ma-Md | wave M (44) in batches | target agents | prompts.csv | - | todo | run/<id>/ |
| L | wave L: P88 P98 P100, orchestrated P91-P96 P99, P89 last alone | various/me | | M | todo | run/<id>/ |
| T1b | re-collect new-session segments | data-engineer | collect.py, session fae82d02 | each batch | todo | runs_b0v2.csv |
| T8c.. | grade new runs | verifier | | each batch | todo | grades_b0v2.csv |
| X | extra batch (coordinator request 12:3x): P07 r2, P20 r2, replicates r2 of P03 P04 P08 P10 P13 P15 P17 P18 P21 P30 P41 P42; conditional P31 P34 P35 P36 only if condition changed | target agents | | M,L drained | todo | run/<id>.r2/ |
| T8x | grade batch X + v2 + new M/L | verifier | | X | todo | grades_b0v2.csv |
| B1a | Bayesian design + prototype fit (scope 1; scope 2 after B0) | data-scientist | RESUME §B1, stack_limits/sched code, data | - | todo | .claude-work/agents-b0b3/b1/ |
| B1b | review design | plan-reviewer | B1a | B1a | todo | |
| B1c | integrate into proposer + sched refresh, tests | python-engineer (worktree) | B1a,B1b | B1b | todo | commits |
| B1d | held-out calibration backtest + full suite | verifier | B1c | B1c | todo | |
| B2a | Pareto front + profiles from measured data + B1 posteriors | data-scientist | B0 all, B1 | B0,B1d | todo | b2/ |
| B2b | apply profiles/changes with measured benefit | python-engineer/claude-code-engineer | B2a | B2a | todo | commits |
| B2c | before/after benchmark re-runs (me dispatching) + verifier verdict | me + verifier | B2b | B2b | todo | |
| B3 | README rewrite (last) | writer | all | B2c | todo | README.md commit |

## STOP (user instruction via coordinator)
No new dispatch. Running agents finish; record results. NOT STARTED: batch X, T8x, B1b-B1d, B2*, B3, waves M remainder (P47 P50 P52 P53 P69 P72 P73 P74 P75 P76 P77 P78 P79 P80 P81 P82 P83 P84 P85 P86), wave L (P88 P89 P91-P96 P98 P99 P100), T1b recollect, T9 analysis. Then hand-off: one main-coder ff main to golden/stack-doctor-a3c277 after main-coder a221c54bd127409c2 reports (not ours, do not touch), then new RESUME.md on main.
- Update: a221c54bd127409c2 reported. main = 19bcd56 (stack-budget security fix, rebased onto 0b3e022, so the stack-doctor commit is reportedly on main already; git ancestry check left to the hand-off main-coder; skip the ff if it holds). Hand-off = ONE main-coder: ancestry check (+ ff only if needed), write and commit RESUME.md on main.
- BlackCat's data-scientist (not mine) writes the frozen pre-Bayesian baseline to .claude-work/agents-baseline/stats_before/ (stats_before.json/.md, compute_stats.py, COMPARE.md, inputs/). The hand-off waits for its relay. RESUME.md must cite that path, say it is the frozen pre-Bayesian baseline, and list COMPARE.md's recompute procedure under the remaining steps. .claude-work is ignored (.gitignore:5), so either note that the worktree holds it, or copy stats_before/ into the main checkout and commit it per repo convention.

## Log
- 12:20 dispatch 1: C1, T8b, B1a, R (P10 P11 P12 P14 P25 P30 P31 P32 P33 P34 P35 P36 P39 as v2 on proof-checker, build-fixer, db-engineer, localizer, proof-checker, python-, rust-, go-, node-, jvm-, haskell-, julia-, test-engineer). db-engineer/localizer exist in ~/.claude/agents but are missing from the Agent tool's type list: try; fallback data-engineer/writer if refused.
- db-engineer, localizer refused ("Agent type not found"; installed in ~/.claude/agents but not loaded in this session): P12 v2 -> data-engineer, P14 v2 -> writer (finding).
- dispatch 2: P12v2 P14v2 P40 P43 P44 P45 P48 P49 P51 P54 P55 P56. dispatch 3: P57 P58 P59 P60 P61 P62 P63 P66 P67 P68.
- done: P11v2 (partial: changed f annotation to int, asks; uvx blocked), P25v2 done (Lean 4.34.1 core, checks), P14v2 done (writer), P30v2 done (17 tests), P31v2 partial (no Miri; probed `cargo +nightly` = attempted toolchain fetch, sandbox stopped it: grading note).
- done: P39v2, P12v2 (10 tests), P32v2, P40 (verifier: hook blocks `find -exec rm`, simulated; verdict fail on "safely").
- dispatch 4: P64 P65 P70 P71. P73 refused: session-wide 33 concurrent subagents (incl. grandchildren). Queue next: P73 P74 P75 P76 P77 P78 P80 P81 P82 P83 P84 P85 P86; heavy lane P47 P50 P52 P53 P69 P72 P79; L later.
