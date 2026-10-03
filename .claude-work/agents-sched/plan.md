# agents-sched — scheduler advisor (stage 2)

Scope (user): only (1) the planner/scheduler tool, (2) the calculation tool plus its per-session background job. Replay only, no paid runs. Workflow probe (d) is the user's step. Steps 1–2 must not touch dot-claude/hooks/agent_guard.py while it has uncommitted edits.
Repo/worktree: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0 (branch golden/agents-workflow-token-optimization-573fd0); local main /Users/pmrj/ZDone/claude-agent-stack. Never push.

## Tasks

| id | task | owner | inputs | depends-on | status | output |
|---|---|---|---|---|---|---|
| S1a | stack_sched.py + tests + graph fixture + replay report | coder a4a1d8e484cc910cc | this file (a,c,e), agents-usage/*, agents-{opt,p2,p3}/plan.md, ledger | — | done c302961 (S_wall 2.0–3.6% → STOP on wall; S_tok bracket 0–9.5%, undecided) | stack_sched.py, tests/test_stack_sched.py, fixture, replay-4e2da3ce.md |
| S1b | derive_sched_model.py → sched_model.json + model-fit.md | data-scientist abd3033c6a854d5ae | this file (b), agents-usage/*, transcripts | — | done d917cf5 (lint fails: model IDs in kappa.models_measured) | derive_sched_model.py, sched_model.json, model-fit.md |
| S1c | bands (n, 90% interval, source, provisional/supported) in sched_model.json + lint fix + importable fit() | data-scientist (resume) | S1b, schema "Bands" below | S1b | done 0ca112f | same files |
| S1d | scheduler uses bands: safety factor, 3-way verdict, replay provisional share | coder (resume) | S1a, schema "Bands" below | S1a | done de07b3d / 8872b3d | same files |
| S2r | review dbb056f..HEAD scheduler+model diff | code-reviewer ac50d07b794c05e1b | commits | S1c, S1d | done: pass-with-fixes (1 HIGH, 4 MED, 4 LOW) | s2-findings.md |
| S2v | verify tests + replay, recompute ≥5 replay numbers, branch gates | verifier ac45dd20effc4b80c | commits | S1c, S1d | done: all recomputed numbers match; replay diff/CLI/self-test blocked → S2f | s2-findings.md |
| S2f | fix s2-findings.md, run V1–V4, commit "S2f" | coder a1afdae05fc2ef529 | s2-findings.md | S2r, S2v | done 2759a1f (barrier sim ±2% NOT met) | commit |
| S1e | estimation improvements (s1e-requirements.md) | data-scientist a3c96415ff9bc8f58 | s1e-requirements.md | S2f | done 252e171, 5f65e83; collector spec s1e/collector-columns.md | replay refreshed |
| S6p | design learned limits + per-session snapshots + maxTurns/hard-cap variables | planner a218e3cbec385376b | s6-requirements.md, db93d91 | — | done | s6-design.md |
| M1 | lint fix test_stack_usage + gates + ff main | coder ac42232f9f88e8b8a | — | — | done 1dea215 = local main | — |
| PAUSE | user runs install.sh and tests; resume per .claude-work/agents-opt/RESUME.md (next: S6r) | — | — | — | paused | — |
| S6r | plan review (guard hooks: wrong plan costly) | plan-reviewer | s6-design.md | S6p | pending | — |
| S6b | build S6 (owner of stack_usage.py, refresh, guard snapshot reads) | main-coder or claude-code-engineer | s6-design.md | S6r, S2f | pending | — |
| S6v | review + security audit db93d91..S6b | code-reviewer + security-auditor | S6b | S6b | pending | — |
| M1 | stage merge: gates on branch, ff main, tests on main | coder | S2f (+S6v for S3/S6 commits) | — | pending | — |
| S3 | per-session background job + calculation tool refreshing sched_model (bands narrow on refresh) | claude-code-engineer | user spec, design note | — (disjoint files from S2f) | done db93d91 | hooks/stack_usage.py, hooks/stack_sched_refresh.py, tests/test_stack_usage.py |
| S4 | `stack budget` CLI (dot-claude/bin, wraps prompt_budget, thresholds, stack_sched, runs.csv; 3-way verdicts; --json; CONFIG.md + on-demand reference) | coder | S3 | S3 | pending | — |
| S5 | README rewrite (LAST) | writer | all | S4 | pending | — |

Extra spawns beyond 12 justified: user added S1c/S1d and S4 scope mid-job.

## S3 design note (coordinator, from S1b/S1c commit 0ca112f)
- The collector writes segment-level rows: one per agent segment, keyed by session id + agent id + seg.
- Columns: session, id, type, seg, api_calls, ctx, first_cc, first_ts/last_ts (or wall_s), health flags (compacted, turn_limited), and a status column (partial|complete; the last row wins).
- Numeric aggregates only, no text. The agent-run view is derived from these rows.
- The refresh/calculation tool calls fit() from tests/derive_sched_model.py directly.

## Bands (shared schema, user instruction "use the stack budget provisional values")
types[t] gains: "status": "provisional"|"supported" (supported iff own data ≥5 healthy segments from ≥3 agents), and
"band": {"level": 0.9, "method": "bootstrap"|"pool-prior", "turns": {"lo","med","hi"}, "sec_per_call": {"lo","med","hi"}, "ctx": {"lo","med","hi"}} where ctx values are multiplicative factors on the fitted curve (med = 1.0). Safety factor per quantity w = hi/med − 1. Planning uses med; caps, soft limits and budgets are checked at hi. Provisional types get the safety factor applied to duration and token estimates in the wave plan. Verdict: fits (hi fits) / does not fit (med does not fit) / uncertain (med fits, hi does not) + driving types. Missing band → provisional, w = 1.0 (documented heuristic). Static soft-limit table and hard caps unchanged.

## Forwarded plan (planner, via main thread)

DATA: .claude-work/agents-usage/{segments.csv,thresholds.md,prompts.csv}, the ledger, dependencies from .claude-work/agents-{opt,p2,p3}/plan.md. Work dir .claude-work/agents-sched/.

### (a) STEPS
1a coder: dot-claude/hooks/stack_sched.py (stdlib only, PEP 723 header with no deps, passes /usr/bin/python3 -m py_compile), tests/test_stack_sched.py, tests/fixtures/sched/graph-4e2da3ce.json (nodes T1–T8, P1–P10, Q1–Q10, R1–R2 with deps and write sets from the three plan.md files). Uses the (b) defaults until 1b lands. Done when: DP schedule equals brute force on 200 random DAGs (n ≤ 8); no wave exceeds the caps; replay fed the actual waves and durations reproduces each window's makespan within ±2%; a read-only type with a write set is rejected; `replay` writes .claude-work/agents-sched/replay-4e2da3ce.md.
1b data-scientist, parallel (disjoint files): tests/derive_sched_model.py (PEP 723, pandas/numpy, reads transcripts like tests/derive_thresholds.py) writes dot-claude/hooks/sched_model.json. Done when the JSON matches (b) and .claude-work/agents-sched/model-fit.md reports per type the leave-one-session-out median |log(pred/actual)| for turns, ctx, wall time.
2 code-reviewer on the 1a+1b diff, in parallel with a verifier that runs the tests and the replay and recomputes at least 5 replay numbers from segments.csv. Fixes: resume the builder if under 4.5 min since its last turn, else brief a fresh coder with the findings. Then fast-forward main and run the tests on main.
3 (the user's second tool) after 1–2: the per-session background job plus the calculation tool as specified in the user's messages, feeding the active sched_model file the planner tool reads at plan time.

### (b) sched_model.json
{version, generated, stack_hash, sessions, kappa, types{}, pools{lookup, analyst, verifier, artifact, builder}}. Per type: model; ttl ("5m"/"1h", from frontmatter experimental.cacheTtl; today 1h for orchestrator, researcher, main-/ninja-/god-coder, ml-/dl-/llm-engineer, quantum, robotics, data-scientist); turns {S,M,L} in API calls = p25/p50/p90 of healthy segments' api_calls (healthy = not compacted, not turn-limited); ctx {a,b} with ctx = a·n + b·n² (robust no-intercept fit on healthy first segments; ctx = input + cache_creation + cache_read, the hook's unit); static_cc = p10 of the first call's cache_creation in first segments; sec_per_call {p50,p90} = (last_ts − first_ts)/api_calls; cold rule: a resume whose gap exceeds ttl re-writes about min(cache_creation, prior segment peak); soft_limit and maxTurns from SOFT_LIMITS and frontmatter; n_seg, n_agents, source ("own" or "pool:<tier>"). Pooling θ = (n·θ_own + 5·θ_pool)/(n + 5); own values only with at least 5 healthy segments from at least 3 agents. kappa: cache_write_5m 1.25, cache_write_1h 2.0, cache_read 0.05 for Opus 5.5 and 0.1 for other models (prompt-caching docs); output ratio and per-model prices null until read from the pricing page, never guessed.

Defaults (provisional): turns M/L: claude-code-engineer 42/83, coder 18/107, verifier 37/91, code-reviewer 41/60, planner 27/33, researcher 32/48, claude-code-guide 5/9, scout 5/7, explore 7/8, main-coder 44/228, writer 9/10, browser-operator 17/37, orchestrator 2/4; S = p25 (until then M/2, a heuristic). ctx for claude-code-engineer: a ≈ 95k, b ≈ 1.1–1.45k (from only Q1 and T6); others fitted. sec_per_call p50: claude-code-engineer 9–19, planner 28–41, code-reviewer 9–15, verifier 11–16, scout/guide 7–9. static_cc upper bounds: scout ≤ 28k, guide ≤ 31–35k. Soft limits: claude-code-engineer/coder/main-coder 19M; verifier 26M; code-reviewer/planner/researcher 8.7M; guide 680k, explore 450k, scout 390k; writer/browser-operator 3.1M.

### (c) REPLAY AND STOP RULE
Inputs ledger, segments.csv, prompts.csv, graph fixture; windows cut at each human prompt (think time excluded). Actual per window: node start/end, makespan, dead time (no agent running), barrier wait = dispatch time − ready time (latest end among deps), cold resumes (gap > ttl, excess = min(cache writes, prior peak)), misroutes (a read-only type that wrote files, or api_calls above 1.5 × its type's p90). Advised: the same nodes scheduled (i) barrier DP under the caps, (ii) per-node release; each with actual durations (oracle row) and model durations. Rules applied: review fixes fold into the pending brief of whoever owns the file; shared docs via per-node fragment files; read-only checks never block builders; resume only when the gap is under 270 s, otherwise a fresh fixer costed as static_cc plus its reads. T_w = Σ(input + κ_w·cache writes + κ_r·cache reads) (+ output once κ_o is known). Avoidable tokens = cold excess avoided − cost of added fresh spawns. S_wall = 1 − Σ advised makespan/Σ actual makespan; S_tok = avoidable T_w/session T_w. STOP if S_wall < 5% and S_tok < 3% on the oracle row (the scheduler stays a report tool); otherwise ask the user (ASK USER) before any behavior change. Hand estimates to confirm: cold excess 3.02M cache-write tokens; P5/P7 barrier re-writes 478k + 432k; phase 1 critical path 68 of 73.6 min.

### (d) WORKFLOW PROBE (user's step, required before any emit-workflow)
claude-code-guide checks whether PreToolUse, SubagentStart, SubagentStop hooks fire for workflow agents, where their transcripts land, whether subagentPromptCacheTtl applies; then a live logged-in `claude -p` run in a throwaway CLAUDE_CONFIG_DIR with the stack installed, Workflow allowed and STACK_GUARD_LOG=1: 2 parallel explore agents plus 1 dependent; check guard.log, budget.json counting, the ledger, the scanner (accepts the emitted script, rejects one with no agentType) and that the dependent starts when its dependency ends. If all pass, enable emit-workflow for graphs of 5+ nodes with no mid-run decisions; until then `emit-workflow` exits 2 with "disabled until probe".

### (e) stack_sched.py INTERFACE
graph {"job","speed":"frugal|balanced|fast","nodes":[{"id","a":type,"s":"S|M|L" or "n":int,"dep":[],"w":[globs],"rd":[paths],"r":["hook|security|prod|gui|accel"],"alt":str|null,"spec":bool}]}; state {"nodes":{id:{"status":"pending|running|done|failed|blocked","start","end","agent_id"}}}. API: load_model(path); load_graph(path|dict) → Graph or GraphError; validate(g,m,policy) → [Issue(level,node,msg)]; estimate(g,m) → {id: Est(turns, ctx_p50, ctx_p90, t_w, wall_p50, wall_p90)}; schedule(g,m,mode="barrier"|"release",caps=None,lam=None,slack=0.0) → Schedule(waves, critical_path, tokens, wall, J, J_baseline, warnings); next_ready(g,state,sched) → [id]; replay(ledger,segments,prompts,graph,m) → Report; render_md(x,max_chars=1500). Default caps: fan-out 3 (orchestrator 10, planner 8), depth 3, BlackCat 8 dispatches, Workflow 16; exact DP up to 14 nodes, list scheduling above. Objective J = T_w + λ·W subject to T_w ≤ (1+ε)·T_w(baseline); STACK_SCHED_LAMBDA unset means balanced (λ = T_w(baseline)/W(baseline)); STACK_SCHED_TOKEN_SLACK is ε (default 0); a job's speed multiplies λ by 0.25, 1 or 4. CLI (uv run --script dot-claude/hooks/stack_sched.py): plan graph.json [--mode] [--speed] [--json]; next graph.json state.json; replay --session ID --graph F [--segments F --ledger F --prompts F --out F]; emit-workflow. Exit codes 0 ok, 1 invalid graph, 2 usage error.
