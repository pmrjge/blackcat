# L9 candidates: skills/scripts for recurring workflows and a plan cache

2026-10-05, claude-code-engineer. Read-only analysis of the 5 frozen sessions (4e2da3ce, fae82d02, e4fe4e24, a59eca09,
68541e7b). Shares are of the pooled list $ ($1,282, MEASURE.md section 0). No paid runs.

**Bar:** MEASURE.md section 6, as proposed there: pooled ≥ 3% and session median ≥ 2%, in ≥ 4 of 5 sessions. **Out of
scope:** check_suite, merge_check (ff-merge + C10), worktree_audit and bookkeeping. The instructor builds those.

**Decision: build nothing.** No candidate below clears the bar, and neither does any sum of related candidates. The
largest one, unanchored git-inspect chains, is 1.1%. All of them together come to about 2.6% before overlap, and the
strict-spawn row overlaps the chain rows.

| # | Candidate | Measured share | n (sessions) | Source | Build? |
|---|---|---|---|---|---|
| 1 | Commit recipe (stage + commit chain) | 0.59% | 51 (4) | MEASURE 2.2, `h4_hdet_chains.csv` | skip: under the bar |
| 2 | Install-run recipe | 0.10% | 11 (4) | same | skip: under the bar, and running install.sh is the user's step |
| 3 | Fixed-procedure spawns turned into a script (strict class) | 0.43% [0.01, 1.29] | 5 (4) | `h4_hdet_spawns.csv` | skip: under the bar and overlaps #1, #2 and the instructor's recipes. The loose class (6.1%) was mostly judgement work (MEASURE 2.2). |
| 4 | Campaign-run spawns | 2.09% | 76 (2) | `h4_hdet_spawns.csv` | skip: only 2 of 5 sessions, and these were one-off measurement campaigns |
| 5 | Repo-state snapshot: unanchored chains of `git status/log/diff/show` | 1.12% (requests 2..n only, no carry) | 183 (5) | `l9_unanchored.py` | skip: under the bar, and git diff/show reads feed review judgement. The instructor's worktree-audit already covers the state half. |
| 6 | `date` stamp chains (alone or with git-inspect) | 0.41% + 0.28% | 31 (4), 22 (3) | same | skip: trivial |
| 7 | Stack-tool chains (`stack-*`, `stack_report`) | 0.11% | 17 (4) | same | skip |
| 8 | **Plan cache** (templates for repeated plan shapes in `.claude-work/<job>/plan.md`) | Plan Writes: 0.095% of $ (22 Writes, 21 paths, 5 sessions). Shape recurrence: median pairwise Jaccard of H2/H3 headings 0.00, p90 0.14; 3% of pairs ≥ 0.5. The only 2 clusters each sit within one session (revisions of one plan). | 12 distinct shaped plans | `l9_measure.py` §A | skip: no plan shape repeats across sessions |
| 8b | Plan cache replacing planner spawns | Planner runs 3.63% ($46.5, 13 runs, 4 sessions). Every planner brief is a distinct design question (15 briefs, no shared first line beyond 2). | | `l9_measure.py` §B | skip: a cache needs repeated shapes, and none was measured. The cost is design work, not a template. |
| 9 | Brief template (boilerplate lines in Agent prompts) | 0.011% (lines recurring in ≥ 5 briefs: 1.8% of brief characters; all brief output 0.46%) | 395 briefs | `l9_measure.py` §C | skip |

Notes:
- Orchestrator does 71 of the 81 plan tool calls, and 59 of those 81 are Edits. Those are plan bookkeeping, which the
  instructor already covers.
- Exploration Bash families (`sed`, `rg`, `grep`; `h4_bash_families.csv`) are judgement work, not recipes. Their cost
  belongs to L2 (offload/caps) and to read discipline.
- Unverified: #5 uses recorded `output_tokens` ($1,250.7 total, against $1,282 with the out_lb correction), so its share
  is a slight underestimate. The bound is small enough that the decision does not change.

Reproduce:
`uv run --script l9_measure.py > l9_out.txt` (transcripts at
`/Users/pmrj/ZDone/claude-agent-stack/.claude-work/context-diet/data/transcripts/projects`), then
`uv run --script l9_unanchored.py [$TMPDIR/h4-work]` (the work dir comes from `h4_extract.py`).

Revisit when later sessions, measured with `h4_hdet.py` and `l9_measure.py`, show either of these:
- a non-instructor chain at ≥ 3% pooled;
- a plan-shape cluster spanning ≥ 3 sessions.
