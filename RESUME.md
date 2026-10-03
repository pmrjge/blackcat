# RESUME — S6 learned limits, budget CLI, scheduler, Python 3.13 (state at local main 0a04a59)

Main: /Users/pmrj/ZDone/claude-agent-stack (local main 0a04a59, verified). Worktree of this job: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728 (branch golden/resume-770728). Nothing pushed by agents. Hashes below checked with `git log -1`; anything else is marked unverified.

## Exact next step
1. User: run `./install.sh` from /Users/pmrj/ZDone/claude-agent-stack, restart Claude Code, run `/stack-doctor`.
2. User-side checks the sandbox blocked (section B2).
3. Then dispatch ONE orchestrator (spawn cap ~32 after install) with the job in section B3 (B0 baseline data, B1 Bayesian inference, B2 Pareto + verification, B3 README).

## A. State on main
| Area | Commits |
|---|---|
| Read gate | 3934aa9, 2d13551 |
| S6 learned limits | W1+W3 1412edd; W2 cbdb1db; W4 38d2a22; step 4 6a3612c; security fixes 152fd82; turn gate `calls > turns` 18b8411; batch-2 fixes S1-S4 + V1 d28e2ff; V2a/V2b tests 25137fb |
| Model column (schema 3) | f1831df; collector hand-off d779dfe; fix b5b0dfe |
| `stack budget` CLI | a56c649, 5a8a23b |
| Guard fixes | e810a87 |
| Limits and caps | orchestrator prompt soft limit 80M 5dc2a74 (`SOFT_PROMPT_CTX_BY_TYPE`); orchestrator spawn cap ~32 d63dc4e; fan-out 32 2c15cf8; CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=33 e0d0540 |
| Python | target 3.13: 2b9eb70 (to 3.14) then 4b44ffd (to 3.13) |
| Tools venv | installer d8038a3: pytest numpy pandas httpx mcp pillow neural-memory; claude-agent-sdk left out by the cooldown date (one test skipped) |
| Spider | anti-bot defaults restored 4f8f6f2 (polite mode opt-in with SPIDER_ANTIBOT=0; Spider's server-side stealth accepted) |
| Override | f235e7a, 1987381, 6a736c6 |
| Scheduler | default policy `report` (advice-only) 14af4ef (`fresh_fixer` opt-in); wave clustering cd34b33; review fixes 0a04a59 |
| Lint | lint_agents skips .claude-work a1bcb2d |

Override details: `/override-agent <agent> <model>`, `/override-agent list`, `/override-agent reset <agent|all>`. Effort table dot-claude/hooks/agent_effort.json is display-only ("recorded, not applied"). Model override is enforced by the guard's UserPromptExpansion hook plus Agent updatedInput; only the user's typed command can set it.

Scheduler replay (0a04a59): 18/19 in-session max 2.96%; 16/19 held-out max 4.18%; 2 of 12 multi-wave groups within 2% on closed sessions; 25/35 all groups. 2% everywhere needs stagger >= 13.5 s while medians are <= 9.0 s: not claimed reachable. Fixture tests/fixtures/sched/4e2da3ce keeps desc as node id or "-".

Decisions by the user this session:
- Budget keys leave settings.json env (38d2a22 kept).
- Turn gate allows the last turn.
- Effort is display-only.
- Reset is a subcommand.
- Scheduler is advice-only.
- Bayesian inference for ALL learned values (scope 1 limits/scheduler, scope 2 routing/quality), then Pareto optimization, then README last.
- MCP cap is a fixed guard (verified, test T1b).
- "or" support rule matches design §4 (test T6b).

Lint check, this session: `uv run --python 3.12 tests/lint_agents.py` prints "lint_agents: ok", exit 0 (verified; it prints no error count, so "0 errors" is read from the ok line).

## B. Next session
### B1. After install
`/stack-doctor` first.

### B2. User-side checks the sandbox blocked
- `bash tests/install_smoke.sh`
- doctor.sh on the real install
- both `agent_guard.py --self-test` forms
- `tests/test_web_caps.py::test_stack_env_overrides` (KeyError 'proxy_enabled', unexplained)
- live `/override-agent list`: block-message rendering and the model rewrite in a live session are unverified
- live checks L1/L2/L4 and compaction from the old RESUME
- `tests/sdk_smoke.py` (billed)
- the Workflow probe
- Already verified on 3.13 by the user (ml_extra.py): "mps True 2.14.0", "mlx 12.0".

### B3. Orchestrator job (one orchestrator, cap ~32 spawns)
Order: B0 baseline data -> B1 Bayesian inference -> B2 Pareto + verification -> B3 README (last). Never push; installed ~/.claude is not edited in place; install.sh is the user's step; one accelerator job (MLX) at a time; rebase, never force. Serialize builders on the shared scheduler/limits files.

Lesson: long-running builders hit the 33M prompt soft limit. Brief one fresh fixer per batch; soft-limit stops are censored observations.

Carry-over (do first):
- Security review of `stack budget` (dot-claude/bin/stack-budget, a56c649 + 5a8a23b): never reviewed (auditor hit its soft limit). Check the read-only claim (never writes live.json/snapshots) and hostile-file handling.
- requirements/tools.txt: pyjwt 2.14.0 has PYSEC-2026-4141 (fixed in 2.15.0; not reachable per audit). Bump at the next re-lock and add claude-agent-sdk then.

**B0 Baseline data** (section C).

**B1 Bayesian inference of every learned value** (scope 1 + 2).
- Scope 1: limits and scheduler estimates: turns.<type> (maxTurns), soft/hard token caps (agent, prompt, session), token/latency/turns estimates in stack_limits.py, stack_sched.py, stack_sched_refresh.py / derive_sched_model.py.
- Scope 2: routing and quality from the graded baseline runs: which agent/profile to pick; accuracy per agent type x task class.
- Hierarchical model with partial pooling across agent types (shrink toward class/tier/model priors) so sparse types get stable values.
- Likelihoods: log-normal or gamma for tokens and duration; negative binomial for turns and tool calls; binomial/ordinal for grades.
- Cap hits, turn-limited and truncated segments are censored (hit_*, turn_limited, compacted, status_code), never measured values.
- A limit = a chosen posterior-predictive quantile with an explicit cap-hit risk target per variable; §1 floors/ceilings become prior bounds.
- Posterior updates as rows append, but values swap ONLY once at session start from the frozen snapshot (U4 unchanged; apply_and_snapshot stays the single swap point).
- Reproducible fits: fixed seeds, pinned versions, data hash (evidence_id) recorded. Diagnostics (R-hat, ESS, divergences) gate the swap; fall back to the empirical-quantile estimator (stack_limits §4) when a fit fails or is under-supported.
- Closed-form/conjugate where adequate (stdlib, no sampler in hooks). PyMC/NumPyro/Stan only inside the stack venvs (/Users/pmrj/.claude/venvs/...), macOS arm64, Python 3.13, in the detached proposer, never in a hook's hot path.
- Provenance and uncertainty intervals stored with each value (live.json / snapshot / proposals).
- User-pinned values are hard floors the learner never lowers: soft.prompt.orchestrator 80M (SOFT_PROMPT_CTX_BY_TYPE), fan-out 32 (fixed guard, not learnable), any env override.
- Specialists: data-scientist (design + fit; skill bayesian-modeling) -> plan-reviewer on the design -> python-engineer/ml-engineer (integration into the stack_limits.py proposer + stack_sched refresh, tests) -> verifier: rolling-origin held-out calibration backtest (do posterior quantiles hit their target cap-hit rate? interval coverage) plus the full suite.

**B2 Pareto optimization** (consumes B1 posteriors), then verification.
- Objectives: tokens (in/out/cache, cost), wall-clock latency, throughput (agents/jobs per hour), result quality (graded runs), general performance (turns, tool calls, retries, hook overhead, failures).
- Decision variables: routing/agent-choice rules, agent prompt sizes, model/effort per agent, maxTurns and soft/hard caps (session-start swap only), spawn caps/depth/topology, orchestrator-vs-specialist thresholds, MCP/skill listing scope, compaction/context settings, scheduler policy (STACK_SCHED_POLICY).
- Measured data only (mark unverified). Compute the non-dominated front, state trade-offs, pick a default operating point plus named profiles (cheap / fast / accurate) selectable via stack.env. Apply only changes with measured benefit: minimal diffs, tests, rollback with documented before-values.
- Verifier: re-run the before/after benchmark (same prompts, graders, seeds/repeats), per-metric deltas with uncertainty, regression checks (full suite, guard self-test, install smoke where runnable), explicit dominates-or-trades-off verdict; failures back to the builder with evidence, max two rounds.
- Fold results into README content (measured table, Pareto table/chart, profiles, how limits and the CSV tables work incl. session-start-only swap, install/rollback).

**B3 README rewrite** (writer, LAST). Todo, verified against README.md in this worktree:
- README.md:251 still says "the stack's venvs pin 3.12" and "uv python install 3.14 ... pin --global 3.14"; change to "the stack's venvs pin 3.13; uv's default stays 3.14".
- No `--python 3.13` appears anywhere in README.md (`grep -- --python README.md` found nothing); add it where the test/venv commands are shown (README.md:321 is the `/override-agent` table row, not a Python line; the earlier brief's line number is unverified).
- Also cover: T7d content, the read gate, learned limits (stack_limits.py show/freeze/rollback), the `stack budget` CLI, `/override-agent` forms.

## C. Baseline campaign (B0)
Source: /Users/pmrj/ZDone/claude-agent-stack/.claude-work/agents-baseline/RESUME.md (plan.md, grades.csv, runs.csv, collect.py under the old worktree .../agents-workflow-token-optimization-573fd0/.claude-work/agents-baseline/).
- Re-run the starred fallback runs on the new install: P10 P11 P12 P14 P25 P30-P36 P39.
- Grade the 18 ungraded M ids.
- Then wave M (P40...P86) and wave L (P88, P91-P100; P89 MLX alone).
- Held, need the user: P01/P02 (blackcat, fresh main session); P22 (consent: third-party MCP); P87 (consent: paid image-studio); P97 (git init blocked under .claude-work); P89 alone on the Mac.
- Rows land in runs3.csv (schema 3) via the collector; old runs*.csv / runs2*.csv are read-only history. Live data: ~/.local/state/claude-agent-stack/usage/.

## D. Open items / known issues
- Test `f4` (`cd /tmp && git checkout main` in tests/test_protected_paths.py) fails only because pytest's tmp_path sits under /tmp/claude-501 in the sandbox.
- Python 3.13 could not be installed inside the sandbox: tests ran on 3.12 and /usr/bin/python3 (3.9.6).
- Hooks run on /usr/bin/python3 3.9.6: keep hook code 3.9-compatible.
- pyjwt 2.14.0 (PYSEC-2026-4141): see B3 carry-over.
- `stack budget` CLI security review never done.
- The 1987381 rename/effort-table commit got no separate review (unverified).
- The `fable` override sits above god-coder's model without god-coder's rules (by design).

## E. User cleanup (sandbox blocks it)
Read-only `git worktree list` and `git branch --list` on main, verified this session:

| Ref | State | Recommendation |
|---|---|---|
| worktree-agent-a850e479080e75c19 (worktree .claude/worktrees/agent-a850e479080e75c19, a0aafbd) | 1 commit not in main: a0aafbd "S6 W3: usage collector v2 (runs2.csv schema 2 ...)" | superseded by merged W1+W3 1412edd (unverified that nothing else is unique); remove worktree, then `git branch -D` only after you agree |
| worktree-agent-ac6eb61d0c4133090 (1412edd, prunable) | merged into main | prune and delete |
| rescue/fanout-caps-8-6-pre-rebase, rescue/model-column-58bbd74, rescue/model-column-eee6cae, rescue/model-column-handoff-639e1a0, rescue/session-budget-666m-pre-rebase, rescue/w1-pre-rebase, rescue/w1-pre-w3 (7 refs) | hold commits main cannot reach | keep until you say |
| golden/agents-workflow-token-optimization-573fd0 (+ detached worktree 910275c), golden/blackcat-agent-delegation-enum-dd3b3a | older job branches | keep until you review |
| golden/resume-770728 | this job; at 0a04a59 plus the RESUME.md commit | remove after copying the files below |

```
cd /Users/pmrj/ZDone/claude-agent-stack
git worktree prune
git branch -d worktree-agent-ac6eb61d0c4133090
git worktree remove .claude/worktrees/agent-a850e479080e75c19   # then decide on the branch
# before removing the resume-770728 worktree:
mkdir -p .claude-work/resume
W=/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728/.claude-work/resume
cp $W/plan.md $W/next-job.md $W/s6-design-v2.md $W/s6r-review.md .claude-work/resume/
git worktree remove /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728
git branch -d golden/resume-770728
```
- Scratch .claude-work/py314-audit can be deleted after install.
- `git push` is the user's step.
