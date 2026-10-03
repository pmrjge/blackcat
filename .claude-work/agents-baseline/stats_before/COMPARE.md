# COMPARE: recomputing after the Bayesian design, like for like

This is the fixed procedure for comparing the frozen pre-Bayesian baseline (`stats_before/`, schema 1.0.0, inputs manifest
`inputs/MANIFEST.sha256`) with runs made after the B1 hierarchical fit and B2 Pareto profiles are applied. Every definition
below is the one in `stats_before.json → definitions`. If a definition has to change, bump `schema_version`,
recompute BEFORE with the new definition from the same frozen inputs, and report both versions.

## 0. What BEFORE can and cannot support

| BEFORE cell | n runs | graded | usable as the quality baseline | usable as the token/latency baseline |
|---|---|---|---|---|
| old_install v1 (session 4e2da3ce) | 40 | 40 | yes, but different install and agents (13 fallbacks) | only for a cross-install contrast |
| new_install v2 (session fae82d02, 13 re-runs on dedicated agents) | 13 | 0 | **not yet**: ungraded | yes (stack 44c9fd5, limits snapshot 7cf4e734399eef33) |
| new_install v1 (session fae82d02, wave M P40–P71) | 24 | 0 | **not yet**: ungraded | yes |

The like-for-like BEFORE for the Bayesian change is the **new_install** population (37 runs): same install, same agent
set, limits from the pre-Bayesian snapshot. Its quality is missing. Step 1 fixes that before any AFTER run is graded.

## 1. Before running anything AFTER

1. **Grade the 37 new_install BEFORE runs** (outputs `run/<id>/` and `run/<id>.v2/`, reports in
   `inputs/collected_fae82d02/run/<id>/final_*.txt`) with the T8a/T8b grader: agent type `verifier`, the `check` column of
   `inputs/baseline/prompts.csv` as the rubric, vocabulary `pass|partial|fail|tool-absent`, CSV `id,check_result,why`.
   Write `grades_b0v2.csv` with an extra `variant` column (`v1`/`v2`). Then copy it into a new frozen input set
   (`stats_before_v1.1/inputs/`, never by editing `stats_before/inputs/`), rerun `compute_stats.py` there with that grade
   file added to `GRADE_FILES` and the grade join keyed by `(prompt_id, variant, install)` instead of old_install v1 only, and
   bump `schema_version` to 1.1.0.
2. **Blind the grader where possible.** Best: grade BEFORE (new_install) and AFTER outputs in one batch, randomised order,
   with run dirs relabelled so the grader cannot tell which is which. If BEFORE is graded first (step 1), AFTER must use the
   same grader brief, word for word (save it as `grader_brief.md` next to the grades).
3. **Optional, for within-prompt variance:** batch X (r2 replicates of P03 P04 P07 P08 P10 P13 P15 P17 P18 P20 P21 P30 P41
   P42) on the pre-Bayesian config. Without it, BEFORE has no replicates and no variance comparison is possible; AFTER
   replicates can then only describe AFTER variance.
4. Record the AFTER configuration: stack commit, limits snapshot id (`runs3.csv` columns `stack_commit` and `snap`), the
   active `STACK_SCHED_POLICY` / profile, and the models per agent type.

## 2. AFTER runs

- Same prompts: every prompt id in the BEFORE comparison cell, prompt text unchanged (check that the `prompt` and `check`
  columns of `prompts.csv` hash the same as in `inputs/baseline/prompts.csv`).
- Same agent type per prompt as the BEFORE cell (new_install: the dedicated agent; P12 v2 ran on data-engineer and P14 v2
  on writer because db-engineer and localizer were not loadable; use the same or record the change).
- Same dispatch label format so the collector tags runs: `<PID> <variant> run <agent>`, variant `a1` for AFTER
  (a replicate becomes `a2`, ...). Do not reuse `v2`/`r2`.
- Same environment constraints: no new network allowances, no newly installed toolchains (otherwise tool-absent changes
  meaning). If the environment changes, record it and report those prompts separately.
- One run per prompt for the primary analysis (the first, `a1`); further replicates only feed variance.

## 3. Freezing AFTER data

1. Collect with the same collector: `uv run --script stats_before/tools/collect_b0v2.py --session <AFTER sid>
   --campaign-since <ISO of the first AFTER dispatch> --repo <worktree> --out stats_after/inputs/collected_<sid8>`
   (copy `prompts.csv` and a header-only `grades.csv` into `--out` first, as done for fae82d02).
2. Copy the live usage tables (`~/.local/state/claude-agent-stack/usage/runs3.csv`) and the AFTER grades into
   `stats_after/inputs/`, write `FROZEN_AT.txt`, run `tools/manifest.py` (copy it alongside).
3. Copy `compute_stats.py` to `stats_after/`, change ONLY `SESSIONS`, `USAGE`, `GRADE_FILES`, `CAMPAIGN_SINCE` and the
   grade-join rule. Keep `SEED`, `B`, `MIN_N_CI`, `Z`, `METRICS`, the regexes and `DEFINITIONS` byte-identical
   (diff them and keep the diff with the outputs).
4. Run it, then the second route (`tools/verify_second_route.py`, adapted to the AFTER session names); both must pass
   before any comparison number is reported.

## 4. Denominators and exclusions (identical on both sides)

- Run = (session, prompt_id, variant); all segments with that prompt tag (root, resumes, descendants).
- Excluded from run statistics: overhead dispatches (description `T<n>[letter] ...` inside the campaign window), all
  collector kind `other` rows, runs with an open segment at freeze time (list them), held prompts (P01 P02 P22 P87 P89 P97).
- Grade rates: n = graded runs in the cell **including tool-absent**; also report `pass_rate_excl_tool_absent`. Ungraded
  runs are never in a grade denominator; report their count.
- Comparison set = the intersection of prompt ids present and graded on both sides (state its size). Prompts present on
  only one side are reported separately, never pooled into the paired comparison.
- Censoring: runs with `hit_max_turns = 1` or `soft_limit_hits > 0` are kept in every count, but their tokens/turns are
  lower bounds. Report how many such runs each side has and repeat the token comparison without them as a sensitivity check.

## 5. Metrics to report (pre-specified)

Primary (one table, BEFORE = new_install cell graded per step 1, AFTER = a1):

| # | metric | estimator | interval |
|---|---|---|---|
| P1 | tokens_total per run | median over prompts of log2(after/before), paired | percentile bootstrap over prompts, B=10000, seed = SEED ^ sha256("paired_after|tokens_total")[:8] |
| P2 | pass rate | k/n per side (Wilson); paired pass/non-pass table | exact McNemar test on discordant pairs; report the counts b (pass→non-pass) and c (non-pass→pass) |
| P3 | cap-hit rate (hit_max_turns or soft_limit_hits > 0) | k/n per side | Wilson; discordant pairs as in P2 |
| P4 | duration_s per run | median paired log2(after/before) | bootstrap as in P1 |

Secondary: tokens_fresh, tool_calls, turns (as in P1); quality_score mean (paired difference, bootstrap);
STATUS-format compliance under the current rule, clean-finish rate, overclaim and underclaim rates (Wilson);
sandbox-block and tool-denied run rates; per agent type and per family cells (descriptive, n shown, no tests).

Also report the cross-install contrast old_install v1 vs AFTER on the 40 graded ids, labelled as confounded (install,
agent set, models and limits all differ).

Cost: still missing unless a price table with a source URL and date is added; if one is added, apply it to BEFORE and
AFTER token columns identically and report it as a derived value.

## 6. Reading the result

- A difference counts as measured only when its 95 % interval excludes 0 (P1, P4) or McNemar p < 0.05 (P2, P3), with n
  stated. Otherwise report "no measured difference at this n".
- Cost-quality points: recompute `pareto_points` on the AFTER population with the same objectives and list
  non-dominated points for BEFORE and AFTER side by side. That is still descriptive; the B2 design decision is made
  elsewhere.
- Keep every BEFORE caveat in `stats_before.md` §11 next to the comparison; add any new AFTER-side confound (model
  change, environment change, grader change).
