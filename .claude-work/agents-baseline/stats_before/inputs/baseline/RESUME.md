# agents-baseline — RESUME (paused 2026-10-03 on the user's instruction)

Root: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0/.claude-work/agents-baseline
Data: runs.csv (per segment, from collect.py), grades.csv (graded ids), run/<id>/ (artifacts + final_<agent>.txt), plan.md (dispatch log, fallback map).
Re-collect: `uv run --script .claude-work/agents-baseline/collect.py` from the worktree root (default session 4e2da3ce; use --session/--since for a new session).

## Config used: OLD installed stack (all runs so far)
Every run below ran against the installed ~/.claude, which lacks 19 corpus agents (python-, rust-, go-, node-, jvm-, haskell-, julia-, test-, security-, embedded-, mobile-, game-, hpc-, biochem-engineer, proof-checker, build-fixer, db-engineer, localizer, vfx-td) and every hidden skill module (e.g. py-testing). Fallback targets were used (plan.md). After install, re-run at least the fallback runs: P10 P11 P12 P14 P25 P30-P36 P39 (marked * below); all other ids can also be re-run to compare old vs new.

## Done (status from report; check = grades.csv; tokens = tokens_total incl. cache read, from collector)
| id | agent (fallback*) | status | check | tokens M |
|---|---|---|---|---|
| P03 | coder | done | pass | 0.10 |
| P04 | oracle | done | pass | 0.02 |
| P05 | oracle | done | pass | 0.02 |
| P06 | writer | done | partial | 0.04 |
| P07 | security-auditor | partial (PoC blocked by read-only guard) | pass | 0.39 |
| P08 | explore | done | pass | 0.04 |
| P09 | explore | done | pass | 0.10 |
| P10 | mathematician* | done | pass | 0.08 |
| P11 | coder* | done | partial | 0.19 |
| P12 | data-engineer* | done | pass | 0.27 |
| P13 | designer | done | pass | 0.24 |
| P14 | writer* | done | partial | 0.04 |
| P15 | coder | done | pass | 0.08 |
| P16 | coder | done | pass | 0.07 |
| P17 | scout | done | pass | 0.05 |
| P18 | claude-code-guide | done | pass | 0.12 |
| P19 | scout | done | pass | 0.21 |
| P20 | cuda-engineer | done | partial | 0.47 |
| P21 | claude-code-guide | done | pass | 0.10 |
| P24 | mathematician | done | pass | 0.63 |
| P30 | coder* | done | pass | 0.31 |
| P90 | orchestrated (coder, writer, code-reviewer, coder fix) | done | pass | 2.31 |
| P23 | claude-code-engineer | done | ungraded | 0.45 |
| P25 | mathematician* | done | ungraded | 0.53 |
| P26 | mathematician | done | ungraded | 0.76 |
| P27 | quantum-engineer | done | ungraded | 0.56 |
| P28 | quantum-engineer | done | ungraded | 0.45 |
| P29 | ninja-coder (spawned code-reviewer + verifier) | done | ungraded | 8.52 |
| P31 | coder* | partial (Miri: sandbox blocks ~/.rustup) | ungraded | 0.13 |
| P32 | coder* | done | ungraded | 0.15 |
| P33 | coder* | done | ungraded | 1.00 |
| P34 | coder* | partial (no Gradle/kotlinc; Maven Central blocked) | ungraded | 0.39 |
| P35 | coder* | partial (Hackage blocked; hlint absent) | ungraded | 0.25 |
| P36 | coder* | partial (Julia pkg server blocked) | ungraded | 0.64 |
| P37 | coder | done | ungraded | 0.61 |
| P38 | main-coder | done | ungraded | 3.54 |
| P39 | coder* | done | ungraded | 0.49 |
| P41 | planner | done | ungraded | 0.16 |
| P42 | plan-reviewer | done | ungraded | 0.22 |
| P46 | ml-engineer | done | ungraded | 1.71 |

Totals (tokens_total / fresh): S 19 ids 2.60M / 0.70M; M 20 ids 21.51M / 1.74M; L 1 id 2.31M / 0.29M; total 26.42M / 2.72M for 40 ids. Overhead outside these totals: collector and grader, about 2-3M. The corpus estimates were 2-10x high for S; M is close to its 2M assumption only because P29 (8.5M) and P38 (3.5M) skew it, and the M median is about 0.5M.
Git: .claude-work/ is ignored (.gitignore:5) and nothing under agents-baseline is tracked, so nothing was committed.

## In flight / unfinished
None in flight at pause. Grading pending for the 18 M ids above (P23 ... P46).

## Pending by wave (not started)
- Wave M, no network: P40 P43 P44 P45 P47 P48 P49 P50 P51 P52 P53 P54 P55 P56 P57 P58 P59 P60 P61 P62 P63 P64 P65 P66 P67 P68 P69 P70 P71 P72 P73 P74 P75 P76 P77 P78 P79 P80 P81 P82
- Wave M, network: P83 P84 P85 P86
- Wave L: P88, P89 (alone), P91 P92 P93 P94 P95 P96 P97 P98 P99 P100 (orchestrated ones run by the orchestrator itself)

## Held
- P01, P02: target blackcat; need a fresh main session (not dispatchable from a subagent).
- P22: needs user consent (mounts a third-party MCP server and runs external code).
- P87: needs user consent (paid image-studio).
- P89: MLX benchmark; run alone on the Mac, no other accelerator job.
- P97: the sandbox blocks `git init` under .claude-work; it will fail unless run in a dir where git writes are allowed (user decision).

## Exact next step
1. After install: decide whether to re-run the fallback runs (*) on the new config. Then resume wave M from P40 using the fallback map in plan.md, updated to the new agents if installed.
2. One grader (verifier) for the 18 ungraded M ids above, then append its CSV to grades.csv.
3. Re-run collect.py after each batch. At the end, dispatch the data-scientist analysis (brief in plan.md T9) -> analysis.md.

## Findings so far (for the analysis)
- Skills are seldom loaded: 13/19 S runs loaded none, and expected hubs were missed (python-engineering, portuguese-pt-writing, web-research, claude-code-extensions).
- Sandbox: git init under .claude-work is blocked, and so are ~/.rustup, the uv tool dir, ~/.cabal, ~/.julia/compiled and the pnpm store lock. Package registries are blocked (Maven Central, Hackage, Julia pkg, figshare).
- The read-only guard blocks verifier, code-reviewer and security-auditor from running project tests or scripts under .claude-work, including false positives on `uv run pytest`. The verifier listed 10 blocked commands (grader report, P30/P90).
- The memory hook refuses nmem_remember for agents whose prompts "may carry web content", even for local-only results (P25-P28, P46).
- Long runs: P29 ninja-coder ran 24 min (45 tools, self-review rounds); P38 main-coder 14 min; P46 ml-engineer 16 min (HGB thread oversubscription found).
