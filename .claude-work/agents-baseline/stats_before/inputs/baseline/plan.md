# agents-baseline campaign — plan (orchestrator checkpoint)

Root: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0/.claude-work/agents-baseline
Run dirs: run/<id>/ (agents create them). Ledger key: Agent description starts with the prompt id ("P03 run coder").
Grades: grades.csv (id, agent, check_result pass|fail|partial|pending|tool-absent, why). Data: runs.csv (collector), analysis.md (data-scientist).

## Key facts found at start
- The INSTALLED stack (~/.claude) lacks 19 agents that exist in this worktree (python-, rust-, go-, node-, jvm-, haskell-, julia-, test-, security-, embedded-, mobile-, game-, hpc-, biochem-engineer, proof-checker, build-fixer, db-engineer, localizer, vfx-td) and all hidden skill modules (e.g. dot-claude/skills/py-testing/ exists only in the repo). This campaign measures the INSTALLED stack; missing targets run via the fallback below and are flagged.
- orchestrator is not in my spawn list: "orchestrated" prompts (P90-P97, P99) are run by me as orchestrator.
- blackcat-target prompts P01, P02 need a fresh main session: pending (not dispatchable).
- Routing traps: I dispatch the corpus target directly, so BlackCat-level routing is NOT tested; only agent-level handling.

## Fallback map (missing target -> installed agent)
proof-checker->mathematician (P10,P25); build-fixer->coder (P11); db-engineer->data-engineer (P12); localizer->writer (P14);
python/rust/go/node/jvm/haskell/julia/test/embedded/mobile/game/hpc-engineer->coder (P30-P36,P39,P73-P77);
vfx-td->cg-artist (P59); security-engineer->main-coder (P70), devops-engineer (P71); biochem-engineer->data-engineer (P78), quantum-engineer (P79).

## Consent / not runnable
P22 (mounts third-party MCP), P87 (paid image-studio): pending consent. P01, P02: need main session. Any missing toolchain: report absence, never install.

## Tasks
| id | task | owner | inputs | depends-on | status | output |
|---|---|---|---|---|---|---|
| T1 | collector: transcripts+ledger -> runs.csv, final msgs -> run/<id>/final.txt | data-engineer | agents-usage/usage.py, ledger | - | dispatched | collect.py, runs.csv |
| T2 | pilot P19 P03 P30 P24 + P90 (me orchestrating) | scout, coder, coder, mathematician, coder/writer/code-reviewer | prompts.csv | - | dispatched | run/<id>/ |
| T3 | pilot grading + recalibration | verifier + me | T1,T2 | T1,T2 | todo | grades.csv |
| T4 | wave S (rest of S) | various | prompts.csv | T3 | todo | |
| T5 | wave M no-net | various | | T4 | todo | |
| T6 | wave M net | various | | T5 | todo | |
| T7 | wave L (P88, P89 alone, P91-P100) | various/me | | T6 | todo | |
| T8 | per-wave grading | verifier | run dirs | each wave | todo | grades.csv |
| T9 | analysis | data-scientist | runs.csv, grades.csv | T7,T8 | todo | analysis.md |

## Token log (cumulative, from task notifications)
- T1 collector done: `uv run --script .claude-work/agents-baseline/collect.py` (default session 4e2da3ce). Pilot totals incl. cache read: P30 0.31M, P24 0.63M; P03/P19 tiny. Corpus estimates are ~5-10x high.
- Pilot: P19 done, P03 done (built slugify, 7 tests), P30 done (all pass), P24 done (compiled), P90 T1 coder partial: sandbox blocks `git init` under .claude-work (=> P97 at risk; note in findings).
- Batch S1 dispatched: P90 T2 writer pt-PT guide, P90 T3 code-reviewer, P04 P05 P06 P07 P08 P09 P10 P17.
- S1 done. P90 review: pass-with-fixes (1 HIGH, 3 MED). Read-only guard blocked code-reviewer (pytest) and security-auditor (PoC timing, P07 -> partial) from running scripts under .claude-work: finding.
- Batch S2 dispatched: P90 T4 coder fix round (SendMessage a418c46b5091ed47f), P11 P12 P13 P14 P15 P16 P18 P20 P21.
- S2 done; P90 done (1 review round trip, 27 tests). S wave complete except P01/P02 (main session) and P22 (consent).
- GUI lane rule: at most one of designer/motion-designer/cg-artist/doc-specialist/verifier running at a time.
- Batch M1 dispatched: collector re-run (SendMessage a0f4d149989dbc3c7), P23 P25 P26 P27 P29 P31 P32 P38 P41.
- M1 done (P31 partial: Miri blocked by sandbox ~/.rustup). Wave S totals: 2.60M (0.70M fresh). Summary sent to main.
- Batch M2 dispatched: T8a verifier grading S+pilot (GUI lane), P28 P33 P34 P35 P36 P37 P39 P42 P46.
- M2 done; grades.csv written (22 ids). PAUSED by user at 40 ids / 26.42M. Resume from RESUME.md.
