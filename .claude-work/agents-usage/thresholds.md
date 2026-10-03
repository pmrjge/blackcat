# Soft token limits and maxTurns, derived from transcripts

Generated 2026-10-02 20:27 UTC by `thresholds.py` (recompute: `uv run --script .claude-work/agents-usage/thresholds.py`). Raw tables: `segments.csv`, `runs.csv`, `prompts.csv`, `sessions.csv`. Read-only over transcripts; no prompt text beyond the first 70 characters of each human prompt.

## Data

| session | project | subagents | of a stack type | ctx (hook unit) | fresh | cache-read share | API calls | state |
|---|---|---|---|---|---|---|---|---|
| 4e2da3ce | Worktree-for-Claude-claude-agent-stack-a | 48 | 48 | 421.4M | 14.3M | 96.6% | 2685 | ended |
| cc39b6a0 | study-plan-and-resources-v2 | 30 | 30 | 304.3M | 11.2M | 96.4% | 1829 | ended |

Included: every session transcript under `~/.claude/projects/` (2). Both ran this stack's agents (every subagent's `.meta.json` `agentType` is a stack type; the stack's state folder `~/.local/state/claude-agent-stack/<session>/` exists with `budget.json` and `delegations.md` for both). `~/.claude/projects/-Users-pmrj-ZDone-claude-agent-stack/` holds only `memory/` (no transcript). Two more stack state folders (17b4b227, 67b92311) hold only lock files and no transcript exists: not usable.

Segments: 165 (163 finished, 2 still running and excluded), from 78 subagents. Problem segments (compacted or turn-limited): 9; continuations after a turn limit: 2. Healthy: 152.

## Current hook budgets (agent_guard.py, settings.json)

- Unit: context tokens = `input + cache_creation + cache_read` of every API call (output excluded), counted cumulatively over the whole session tree (main transcript + every `subagents/agent-*.jsonl`), incrementally via `budget.json` offsets; calls deduplicated by `(message.id, requestId)`.
- `STACK_PROMPT_CTX_BUDGET=100000000` (100M): tokens since the last prompt boundary. The boundary is set at UserPromptSubmit and also whenever a main-thread tool call carries a `prompt_id` not seen before (`budget_note_prompt`); task notifications carry their own promptId in the transcript, so the effective window can restart on a notification turn (inferred from code + transcripts; unverified against a live hook log).
- `STACK_SESSION_CTX_BUDGET=666000000` (666M): whole session.
- Both are HARD: once spent, every tool call of every agent is denied except reporting/stopping tools (SubagentHandback, TaskStop, AskUserQuestion) and Write/Edit under `.claude-work/` or the scratchpad. They fail open (unreadable transcript = allowed). `0` disables. Both are OWNED_ENV in install.sh: a value raised in `~/.claude/settings.json` holds until the next install.
- No per-agent token budget exists. Per agent there is only `STACK_MAX_MCP_CALLS=64` MCP calls per spawn/resume (min with the type's maxTurns), hard, and Claude Code's own `maxTurns` (frontmatter, hard: the run stops).

## Which unit separates healthy from runaway

| unit | AUC per segment, raw | AUC per segment, / type median | AUC per run (all segments), / type median |
|---|---|---|---|
| ctx | 0.954 | 0.895 | 0.822 |
| fresh | 0.964 | 0.855 | 0.833 |
| api_calls | 0.947 | 0.903 | 0.831 |
| tool_calls | 0.953 | 0.891 | 0.844 |
| peak | 0.993 | 0.861 | 0.814 |
| rereads | 0.902 | 0.823 | 0.776 |

AUC = P(a problem segment's value > a healthy one's); problem = compacted or turn-limited (9 segments), markers that do not depend on the token units. Within a type (the `/ type median` column, which removes the scale difference between a scout and a builder), cumulative context (`ctx`) and API calls separate best; fresh tokens and peak context separate worse because cache creation saturates (a long run re-reads a context of ~200-400k, it does not create much more). Per segment beats per run: the orchestrator and resumed builders accumulate many healthy segments, and a per-run count would trip them for being long-lived, not for running away. Chosen unit: **`ctx` per segment** (spawn or resume), which is also the hook's existing unit and the reset rule of the MCP cap, so the builder needs per-file counters only.

Re-reads (cache_read / peak context): healthy medians per type code-reviewer 27x, claude-code-engineer 26x, verifier 24x, researcher 18x, planner 15x, main-coder 11x, browser-operator 10x, coder 10x, writer 6x, explore 4x, claude-code-guide 3x, scout 3x, orchestrator 2x; problem segments a1950e4/1 Q10 contin 14x, a739e53/1 P5 S1 skil 27x, aa1cdc5/0 Set up bef 95x, aa3cecb/1 P7 S3 skil 40x, abf6145/1 P4 A1 budg 72x, a445a17/0 Write Prog 40x, ac2563a/0 T4a genera 110x, ac2563a/3 T4a genera 164x, ae5e7c7/0 T8 write C 35x. A runaway is a long context re-read 90-160 times; cache reads are cheap per token but are 96-97% of all tokens here, so they are what a cumulative limit actually limits.

## Per-agent soft limit (ctx per segment)

Rule: soft = p90(healthy) x m, m the smallest of 1.25..1.5 (step 0.05) with false trips <= 5% (else the lowest), floor 2 x median, rounded up to 2 significant figures. A type is derived from its own runs when it has >= 5 healthy segments from >= 3 distinct agents; otherwise from its comparable-type pool (TIER in the script). `catch`: soft / healthy median; <= 3 means every segment above 3x the median trips. Problem segments caught = problem segments of that type above the soft limit. p90 CI = bootstrap 90% (4,000 resamples).

| type | derived from | n healthy seg / agents | median | p90 | p90 CI | soft | m | false trips | tripped (healthy) | max / soft | catch (soft/median) | problem segs caught | support |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| browser-operator | pool:artifact | 4 / 3 | 1.3M | 2.5M | (see pool row) | **3.1M** | 1.25 floor | 0% | none | 0.93x (2.9M) | 2.4x | - | provisional (pooled) |
| claude-code-engineer | own | 36 / 17 | 5.6M | 14.8M | 10.3M-18.3M | **19.0M** | 1.25 | 3% | a1950e4/0 Q10 contingency fix kit | 1.67x (31.7M) | 3.4x | 1/4 | well |
| claude-code-guide | own | 7 / 6 | 163k | 447k | 217k-650k | **680k** | 1.50 | 0% | none | 0.96x (650k) | 4.2x | - | provisional |
| code-reviewer | own | 5 / 5 | 4.3M | 5.9M | 4.2M-6.1M | **8.7M** | 1.25 floor | 0% | none | 0.70x (6.1M) | 2.0x | - | provisional |
| coder | pool:builder (own 28.0M rejected: 14% false trips) | 7 / 5 | 929k | 21.8M | (see pool row) | **19.0M** | 1.30 | 14% | aecd774/0 Write Computing track data | 2.17x (41.2M) | 20.4x | 0/2 | provisional (pooled) |
| explore | pool:lookup | 3 / 2 | 318k | 356k | (see pool row) | **450k** | 1.25 | 0% | none | 0.81x (365k) | 1.4x | - | provisional (pooled) |
| main-coder | pool:builder | 6 / 1 | 3.0M | 10.5M | (see pool row) | **19.0M** | 1.30 | 0% | none | 3.22x (61.1M) | 6.2x | 2/3 | provisional (pooled) |
| planner | pool:analyst | 2 / 2 | 3.2M | 4.2M | (see pool row) | **8.7M** | 1.25 floor | 0% | none | 0.52x (4.5M) | 2.7x | - | provisional (pooled) |
| researcher | pool:analyst | 4 / 4 | 3.8M | 5.9M | (see pool row) | **8.7M** | 1.25 floor | 0% | none | 0.73x (6.4M) | 2.3x | - | provisional (pooled) |
| scout | own | 24 / 21 | 140k | 310k | 192k-411k | **390k** | 1.25 | 4% | a8a7864/0 Verify algorithms URLs batch1 | 1.10x (427k) | 2.8x | - | well |
| verifier | own | 6 / 5 | 2.2M | 17.5M | 2.7M-24.7M | **26.0M** | 1.45 | 0% | none | 1.14x (29.7M) | 11.8x | 1/2 | provisional |
| writer | pool:artifact | 2 / 1 | 1.6M | 1.8M | (see pool row) | **3.1M** | 1.25 floor | 0% | none | 0.61x (1.9M) | 2.0x | - | provisional (pooled) |
| *lookup pool* (unobserved types) | pool | 34 / 29 | 147k | 352k | 308k-427k | **450k** | 1.25 | 3% | acdd781/0 Agent SDK doc facts | 1.44x | 3.1x | - | provisional |
| *analyst pool* (unobserved types) | pool | 11 / 11 | 4.3M | 6.1M | 4.5M-6.4M | **8.7M** | 1.25 | 0% | none | 0.73x | 2.0x | - | provisional |
| *verifier pool* (unobserved types) | pool | 6 / 5 | 2.2M | 17.5M | 2.7M-24.7M | **26.0M** | 1.45 | 0% | none | 0.95x | 11.8x | - | provisional |
| *artifact pool* (unobserved types) | pool | 6 / 4 | 1.5M | 2.4M | 1.6M-2.9M | **3.1M** | 1.25 | 0% | none | 0.93x | 2.1x | - | provisional |
| *builder pool* (unobserved types) | pool | 49 / 23 | 4.1M | 14.5M | 10.6M-19.3M | **19.0M** | 1.30 | 4% | a1950e4/0 Q10 contingency fix kit; aecd774/0 Write Computing track data | 2.17x | 4.6x | - | provisional |

`max / soft` > 1 means the observed maximum of that type (problem segments included) is above the limit, i.e. the limit would have fired on it; the headroom of healthy runs is `1 / (max healthy / soft)`. Unobserved types inherit their pool (TIER): lookup: oracle, mcp-broker; analyst: plan-reviewer, security-auditor, proof-checker; artifact: doc-specialist, designer, image-director, localizer, motion-designer, cg-artist; builder: ninja-coder, god-coder, build-fixer, test-engineer, data-scientist, data-engineer, db-engineer, devops-engineer, frontend-engineer, python-engineer, rust-engineer, go-engineer, node-engineer, jvm-engineer, julia-engineer, haskell-engineer, mobile-engineer, game-engineer, embedded-engineer, hpc-engineer, cuda-engineer, mlx-engineer, dl-engineer, ml-engineer, llm-engineer, robotics-engineer, quantum-engineer, biochem-engineer, security-engineer, vfx-td, mathematician. Types with no usable data (fewer than 5 healthy segments from 3 agents, and no pool) stay uncapped: orchestrator (blackcat is the main thread, covered by the per-prompt limit).

Uncapped (observed, but too few distinct agents and no comparable pool):

| type | n healthy seg / agents | median | p90 | max |
|---|---|---|---|---|
| orchestrator | 46 / 2 | 303k | 766k | 1.8M |

The orchestrator's segments are short relays (1-14 API calls); its cost is in its children, which their own limits cover. Its two runs differ by ~2x (leave-one-session-out below), so a limit from them would be a guess.

Note on coder: 14% false trips = 1 of 7 healthy segments; with n = 7 one trip is already 14%, and any limit below the type's maximum (41.2M) trips it. The tripped segment (aecd774/0 Write Computing track data [cc39b6a0]) also exceeds the worktree maxTurns (150) in API calls, so the hard cap would stop it anyway; the pooled value is kept rather than a limit at the maximum that would catch nothing.

Per type, all finished segments (problem ones included): n, then median / p90 / max:

| type | segments | agents | fresh | ctx (cumulative) | API calls (turns) | tool calls | rereads median / max |
|---|---|---|---|---|---|---|---|
| browser-operator | 4 | 3 | 89k / 154k / 164k | 1.3M / 2.5M / 2.9M | 17 / 37 / 43 | 29 / 45 / 46 | 10 / 27 |
| claude-code-engineer | 40 | 17 | 240k / 478k / 765k | 6.5M / 16.4M / 31.7M | 42 / 83 / 147 | 47 / 95 / 165 | 27 / 90 |
| claude-code-guide | 7 | 6 | 43k / 124k / 158k | 163k / 447k / 650k | 5 / 9 / 11 | 7 / 16 / 21 | 3 / 5 |
| code-reviewer | 5 | 5 | 170k / 191k / 200k | 4.3M / 5.9M / 6.1M | 41 / 60 / 66 | 44 / 60 / 66 | 27 / 44 |
| coder | 9 | 7 | 142k / 916k / 1.6M | 1.2M / 20.1M / 41.2M | 18 / 107 / 169 | 17 / 154 / 210 | 12 / 117 |
| explore | 3 | 2 | 63k / 72k / 74k | 318k / 356k / 365k | 7 / 8 / 8 | 20 / 21 / 21 | 4 / 4 |
| main-coder | 9 | 1 | 80k / 1.4M / 1.6M | 6.9M / 45.4M / 61.1M | 44 / 228 / 300 | 44 / 260 / 320 | 36 / 164 |
| orchestrator | 46 | 2 | 6k / 63k / 203k | 303k / 766k / 1.8M | 2 / 4 / 14 | 2 / 6 / 21 | 2 / 8 |
| planner | 2 | 2 | 295k / 329k / 337k | 3.2M / 4.2M / 4.5M | 27 / 33 / 35 | 52 / 67 / 71 | 15 / 18 |
| researcher | 4 | 4 | 259k / 282k / 283k | 3.8M / 5.9M / 6.4M | 32 / 48 / 52 | 48 / 62 / 65 | 18 / 34 |
| scout | 24 | 21 | 36k / 77k / 97k | 140k / 310k / 427k | 5 / 7 / 7 | 14 / 25 / 34 | 3 / 4 |
| verifier | 8 | 6 | 108k / 420k / 502k | 2.2M / 26.2M / 29.7M | 37 / 109 / 150 | 38 / 131 / 182 | 24 / 95 |
| writer | 2 | 1 | 280k / 302k / 308k | 1.6M / 1.8M / 1.9M | 9 / 10 / 10 | 23 / 27 / 28 | 6 / 6 |

Problem and after-limit segments vs their limit:

| segment | type | API calls | ctx | compactions | turn limit | ctx / soft | ctx / healthy median |
|---|---|---|---|---|---|---|---|
| ac2563a/3 T4a generators 30h six tracks [cc39b6a0] | main-coder | 300 | 61.1M | 3 | yes | 3.2x | 20.1x |
| ac2563a/0 T4a generators 30h six tracks [cc39b6a0] | main-coder | 210 | 41.5M | 2 |  | 2.2x | 13.6x |
| aa1cdc5/0 Set up before/after benchmark harn [4e2da3ce] | verifier | 150 | 29.7M | 0 | yes | 1.1x | 13.5x |
| abf6145/1 P4 A1 budget tooling overrides [4e2da3ce] | claude-code-engineer | 110 | 26.8M | 1 |  | 1.4x | 4.8x |
| aa3cecb/1 P7 S3 skills cross-cutting [4e2da3ce] | claude-code-engineer | 73 | 14.9M | 1 |  | 0.8x | 2.7x |
| a445a17/0 Write Programming track data [cc39b6a0] | coder | 77 | 14.8M | 1 |  | 0.8x | 15.9x |
| ae5e7c7/0 T8 write CS track data [cc39b6a0] | coder | 80 | 12.0M | 1 |  | 0.6x | 12.9x |
| a739e53/1 P5 S1 skills languages infra [4e2da3ce] | claude-code-engineer | 62 | 10.5M | 1 |  | 0.6x | 1.9x |
| ac2563a/4 T4a generators 30h six tracks [cc39b6a0] | main-coder | 46 | 10.1M | 0 |  | 0.5x | 3.3x |
| a1950e4/1 Q10 contingency fix kit [4e2da3ce] | claude-code-engineer | 45 | 5.1M | 1 |  | 0.3x | 0.9x |
| aa1cdc5/1 Set up before/after benchmark harn [4e2da3ce] | verifier | 2 | 622k | 0 |  | 0.0x | 0.3x |

### Robustness: leave one session out

| type | derived on session | n | soft (that session) | soft (pooled, table) | n other session | false trips in other session |
|---|---|---|---|---|---|---|
| code-reviewer | 4e2da3ce | 3 | 6.7M | 8.7M | 2 | 0% |
| coder | cc39b6a0 | 5 | 43.0M | 19.0M | 2 | 0% |
| orchestrator | 4e2da3ce | 26 | 1.4M | - | 20 | 0% |
| orchestrator | cc39b6a0 | 20 | 460k | - | 26 | 58% |
| researcher | cc39b6a0 | 3 | 5.7M | 8.7M | 1 | 100% |
| scout | 4e2da3ce | 10 | 280k | 390k | 14 | 29% |
| scout | cc39b6a0 | 14 | 450k | 390k | 10 | 0% |
| verifier | 4e2da3ce | 4 | 3.0M | 26.0M | 2 | 100% |

Where the two sessions disagree the pooled table value is the better estimate; the spread is the honest uncertainty of the per-type limits.

## Whole-prompt and session soft limits (ctx, whole session tree)

| scope | n | median | p90 | p90 CI | soft | m | false trips | max / soft | support |
|---|---|---|---|---|---|---|---|---|---|
| per human prompt (UserPromptSubmit to next) | 78 prompts / 2 sessions | 3.1M | 21.5M | 12.8M-31.2M | **33.0M** | 1.50 | 5.1% | 2.77x (91.3M) | provisional (2 sessions) |
| per hook window (as the hook counts today) | 89 | 2.6M | 18.3M | 11.6M-27.3M | 27.0M | 1.45 | 5.6% | 3.38x | reference only |
| per session | 2 (one live) | 362.9M | 409.7M | n too small | **520.0M** (provisional) | 1.25 | 0% | 0.81x (421.4M) | insufficient (n=2) |

Prompts above the per-prompt soft limit (all are legitimate multi-agent jobs, so every one is a false trip by construction; the soft limit's job there is to ask before continuing), with the moment it would have fired:

| session | # | start UTC | prompt | ctx | fresh | would warn at | share done at warning |
|---|---|---|---|---|---|---|---|
| 4e2da3ce | 3 | 15:23 | Can you broaden and optimize for as many agents  | 91.3M | 3.9M | 15:52 UTC | 36% |
| cc39b6a0 | 22 | 14:37 | make a WHOLE_PLAN.md that says 1. folder/book1.p | 80.5M | 1.9M | 15:04 UTC | 41% |
| cc39b6a0 | 7 | 10:09 | yes | 78.7M | 2.6M | 10:55 UTC | 42% |
| 4e2da3ce | 1 | 12:55 | it can have round trips but justified, not just  | 57.7M | 2.1M | 13:25 UTC | 57% |

The prompt distribution is a mixture: short questions (median 3.1M) and dispatched jobs. `3 x median` (9.4M) is therefore not a runaway marker for prompts; the soft limit sits at 11x the median and fires only on the multi-phase jobs above. The session row has n = 2 (one session still running): p90 x 1.25 of two values is not a distribution estimate. Keep the hard 666M as is and treat the session soft value as provisional until >= 5 sessions exist; the per-prompt and per-segment limits do the real work.

### What this session would have tripped

| segment | type | ctx | soft | class |
|---|---|---|---|---|
| a1950e4/0 Q10 contingency fix kit | claude-code-engineer | 31.7M | 19.0M | healthy |
| aa1cdc5/0 Set up before/after benchmark harn | verifier | 29.7M | 26.0M | problem |
| abf6145/1 P4 A1 budget tooling overrides | claude-code-engineer | 26.8M | 19.0M | problem |

Prompts: see the table above (session 4e2da3ce rows). Session total so far 421.4M vs the provisional session soft 520.0M and hard 666M. Phase totals from `report.md` (subagents by label, cumulative incl. output): Phase 1 61.9M, Phase 2 159.5M, Phase 3 108.6M; each phase spans several prompts, so the per-prompt limit fires on the prompt that dispatched the phase (#1 Phase 1, #3 Phase 2), while Phase 3 was spread over many smaller prompts and the per-segment limits are what flag it.

## Benchmark runs

The planned full run is ~51.1M tokens (estimate in `agents-bench/dry-run-output.txt`, range x0.5-x2), spread over 102 separate `claude -p` sessions (17 tasks x 3 reps x 2 arms), each with its own `CLAUDE_CONFIG_DIR` and `XDG_STATE_HOME` (`run_bench.py`). Per session that is ~0.5M (<= 1M at x2), far below every prompt or session limit, so the aggregate cannot trip them. What can interfere is the per-segment soft limit inside a run: a non-interactive `claude -p` cannot answer the ask, so a soft trip becomes a STATUS: partial and a quality loss in one arm only (the old arm, 75dfdfc, has no soft limits). Scope it per run: `run_bench.py` builds each run's env (lines 142-143); add the soft-limit switch there (e.g. `STACK_SOFT_LIMIT_SCALE=0` to turn soft limits off, or a factor such as 2) so both arms run under the same rules, and record it in the result JSON. Hard caps stay on in both arms. Whether a process env var overrides the installed `settings.json` env block is unverified: the builder should test it with one `claude -p` run, or the harness can write the value into each arm's `config/settings.json` env after install.

## Verifier maxTurns

| segment | session | job | API calls | tool calls | ctx | turn limit |
|---|---|---|---|---|---|---|
| aa1cdc5/1 Set up before/after benchmark harn | 4e2da3ce | build | 2 | 1 | 622k |  |
| a58fc76/0 Q9 final verify before merge | 4e2da3ce | verify | 9 | 13 | 330k |  |
| afd0a60/0 T8 verify integrated stack tree | 4e2da3ce | verify | 19 | 21 | 734k |  |
| af77a05/0 Q5 verify phase-3 tree d2bc994 | 4e2da3ce | verify | 32 | 32 | 1.7M |  |
| ab11df1/0 P9b verify phase-2 full tree | 4e2da3ce | verify | 42 | 45 | 2.7M |  |
| ae08514/0 T5 verify plan and library | cc39b6a0 | verify | 90 | 109 | 10.3M |  |
| ae08514/1 T5 verify plan and library | cc39b6a0 | verify | 91 | 99 | 24.7M |  |
| aa1cdc5/0 Set up before/after benchmark harn | 4e2da3ce | build | 150 | 182 | 29.7M | yes |

| type | unit | n | median | p90 | p90 CI | maxTurns from data | m | false trips | headroom | runaway | support |
|---|---|---|---|---|---|---|---|---|---|---|---|
| verifier (verification jobs) | API calls per segment | 6 | 37 | 90.5 | 42-91 | 136 | 1.50 (hard cap: top of band) | 0% | 1.49x over max 91 | build job 152 = 4.1x median | provisional (n=6) |

The maxTurns count is exact: the harness segment stopped at 150 API calls = the installed maxTurns 150, then needed 2 more after a resume. Verification jobs run 9-91 calls (median 37); the harness build (152 calls) is 4.1x that median and 1.67x the longest verification, a different job. Data-derived cap: p90 90.5 x 1.5 = 136. The current worktree value 140 is 1.55x p90, within 3% of the derived value, which is below the resolution of n = 6 (p90 CI above): **keep 140**; do not raise it for the build job. Prompt note for the verifier (and for dispatchers): *a verifier verifies; building a harness, fixture or tool is a builder's job (coder / claude-code-engineer), or split it into separate dispatches (set up, dry run, verify) of <= ~90 calls each.*

maxTurns vs observed API calls per segment (worktree frontmatter; data were produced under the installed, partly higher values):

| type | maxTurns (worktree) | max observed | p90 observed | segments above | which |
|---|---|---|---|---|---|
| browser-operator | 120 | 43 | 37 | 0 | - |
| claude-code-engineer | 120 | 147 | 83 | 1 | a1950e4/0 Q10 contingency fix kit |
| claude-code-guide | 30 | 11 | 9 | 0 | - |
| code-reviewer | 80 | 66 | 60 | 0 | - |
| coder | 150 | 169 | 107 | 1 | aecd774/0 Write Computing track data |
| explore | 40 | 8 | 8 | 0 | - |
| main-coder | 240 | 300 | 228 | 1 | ac2563a/3 T4a generators 30h six tracks |
| orchestrator | 200 | 14 | 4 | 0 | - |
| planner | 60 | 35 | 33 | 0 | - |
| researcher | 130 | 52 | 48 | 0 | - |
| scout | 11 | 7 | 7 | 0 | - |
| verifier | 140 | 150 | 109 | 1 | aa1cdc5/0 Set up before/after benchmark harn |
| writer | 80 | 10 | 10 | 0 | - |

## Soft semantics for the builder

- At the threshold: inject a warning (PreToolUse `additionalContext` or a deny of the next non-reporting call with a reason) telling the agent to wrap up: finish the current step, return `STATUS: partial` with what is done and what remains, and ASK its caller (subagent) or the user (main thread) before continuing. Fire once per segment (per prompt for the prompt limit); a resume or an explicit go-ahead starts a new allowance.
- Counters: per-agent = `ctx` of that agent's transcript since its current run's `started` stamp (same reset rule as `mcp-calls/<agent_id>.json`); per-prompt = since UserPromptSubmit only (human prompts), not on task-notification prompt_ids.
- One documented env var raises them all: `STACK_SOFT_LIMIT_SCALE` (float, default 1; 2 = double every soft limit; 0 = soft limits off). Optional per-type override in the style of STACK_MAX_FANOUT_BY_TYPE.
- Hard caps are unchanged and never weakened: STACK_PROMPT_CTX_BUDGET 100M, STACK_SESSION_CTX_BUDGET 666M, STACK_MAX_MCP_CALLS 64, maxTurns. Every soft value in this file is below its hard counterpart.
- Fail open like the existing budgets.

## Refresh and revisit

`uv run --script /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0/.claude-work/agents-usage/thresholds.py` regenerates every number here. Re-derive when the healthy segment count of a type, or the number of sessions, doubles, and after any major stack change (agent prompts, skills loading, models, maxTurns). Today's counts: orchestrator 46, claude-code-engineer 36, scout 24, claude-code-guide 7, coder 7, verifier 6, main-coder 6, code-reviewer 5, researcher 4, browser-operator 4, explore 3, planner 2, writer 2; sessions 2.

## Limitations

- Two sessions, one day, one user: per-type values are provisional except where marked well; the session limit is not estimable.
- `healthy` = not compacted and not turn-limited; a long but legitimate segment without compaction counts as healthy, so false-trip rates are upper bounds on harm.
- Live session: the running agents (including this analysis) are excluded; totals of the live session grow.
- Thresholds are in-sample; the leave-one-session-out table is the only out-of-sample check.

