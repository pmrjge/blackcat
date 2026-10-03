# RESUME — agents workflow / token optimization (state at local main 1dea215)

Worktree: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/agents-workflow-token-optimization-573fd0 (branch golden/agents-workflow-token-optimization-573fd0)
Main: /Users/pmrj/ZDone/claude-agent-stack. Local main is fast-forwarded to 1dea215. Nothing pushed. Job plan: .claude-work/agents-sched/plan.md.

## Committed (all in local main)
- Phases 1–3: merged earlier (1a38c77, ad22962, 6622116).
- Stage 1 follow-ups:
  - soft limits: d7e3b81;
  - maxTurns from data;
  - model env vars, agents use aliases: b76adf9, dbb056f;
  - prompt-window fix: 61e0c4f;
  - guard self-test: fb0b9e9;
  - docs: 35fae66.
- Scheduler advisor (stack_sched.py, sched_model.json, derive_sched_model.py):
  - built: c302961, d917cf5, 0ca112f, de07b3d, 8872b3d;
  - review fixes S2f: 2759a1f (1 HIGH, 4 MEDIUM, 4 LOW);
  - S1e estimate improvements: 252e171, 5f65e83.
- S3, per-session usage collector + refresh (stack_usage.py, stack_sched_refresh.py): db93d91, lint fix 1dea215. Not yet code-reviewed or security-audited; that is scheduled with S6.
- Web-caps work (someone else's): 77f5638, 6a8b022.

## Queued, in order (exact next step first)
1. **S6 learned limits with per-session immutable snapshots.**
   - Covers the living soft-limit table, per-agent maxTurns and hard-cap variables, the evidence job and the analysis at the next SessionStart.
   - Design: .claude-work/agents-sched/s6-design.md. Requirements: s6-requirements.md.
   - Next step: plan-reviewer on s6-design.md.
   - Then build:
     - W1 core stack_limits.py (main-coder);
     - W2 guard (claude-code-engineer);
     - W3 collector v2, including .claude-work/agents-sched/s1e/collector-columns.md (coder);
     - W4 install/config (claude-code-engineer);
     - then step 4, scheduler snapshot model (coder).
   - Then code-reviewer plus security-auditor over db93d91..HEAD (S3 included), the CONFIG.md docs, a verifier, and the ff to main.
2. **S4 `stack budget` CLI.** Wraps prompt_budget, thresholds/live limits, stack_sched and runs.csv. Provisional values carry an interval and a three-way verdict (fits / does not fit / uncertain).
3. **S5 README rewrite, LAST.**

## Open items for the user
- **Scheduler replay decision (ASK USER).**
  - Wall-time saving 2.0–2.3% (95% CI up to 3.8%): below 5%, so STOP.
  - Token saving, measured: 3.7–4.9%, with the CI reaching about 1.3–2.7%, below the 3% bar.
  - Options: (a) keep the scheduler a report tool; (b) allow "fresh fixer instead of cold resume" as a behaviour change.
- **Barrier simulation.** The replay's ±2% makespan claim is not met (window 2 is −37%, windows 3 and 18 also exceed 2%). Options: improve the 120 s wave clustering, or drop the claim.
- **S6 assumptions to confirm or override:**
  - the floors and ceilings per variable (s6-design §1);
  - STACK_PROMPT_CTX_BUDGET and STACK_SESSION_CTX_BUDGET leaving settings.json env;
  - the MCP cap staying a fixed guard;
  - the "or" support rule.
- **Not ours, not committed:** uncommitted serial-mcp edits in the worktree (install.sh cargo build step, doctor.sh hint, magg/config.json notes). Keep or discard? Owner unknown.
- **User steps:**
  - run ./install.sh from main and restart Claude Code;
  - run install_smoke outside the sandbox;
  - run doctor in Desktop;
  - live checks L1/L2/L4 and compaction;
  - tests/sdk_smoke.py (billed);
  - the Workflow probe (plan.md (d));
  - pushing.

## Verify after install
- doctor.sh: model alias lines resolve (opus/sonnet → claude-opus-5-5 / claude-sonnet-5-5); the usage collector status line; sched_model.json is installed under ~/.claude/hooks.
- New session: a collector process starts once per session (lock and pid under ~/.local/state/claude-agent-stack/usage/), and ~/.local/state/claude-agent-stack/usage/runs.csv gains segment rows (numbers and ids only). The collector exits after SessionEnd. Kill switch: STACK_USAGE_COLLECT=0.
- After a session ends: ~/.local/state/claude-agent-stack/sched_model.json is refreshed (needs uv with a cached pandas/numpy; skipped silently otherwise).
- `uv run --script ~/.claude/hooks/stack_sched.py plan <graph.json>` prints waves and a three-way verdict; `emit-workflow` exits 2.
- Soft limits warn once per agent type and per prompt (33M); STACK_SOFT_LIMIT_SCALE=0 disables them; hard caps are 100M/prompt and 666M/session.
- Desktop subagent viewer shows "<type>: <task>" labels.
- Known caveat: the active sched_model.json is still read mid-session until S6 adds the per-session snapshot.
