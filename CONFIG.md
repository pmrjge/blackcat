<!-- markdownlint-disable MD013 MD060 -->
# CONFIG — applied parameters, choices and settings

This is the configuration the stack ships as of 2026-09-29, with the reason for each choice. It is
a reference, not a source of truth. The values live in:

- `dot-claude/agents/*.md`: frontmatter (model, effort, maxTurns, tools) and the "May spawn" sentences;
- `dot-claude/hooks/agent_guard.py`: POLICY, `DEFAULT_FANOUT_BY_TYPE` and the knob defaults;
- `dot-claude/settings.json`: env and settings keys.

`./install.sh` copies all three into `~/.claude/`. To check that this file still matches them, run
`uv run tests/lint_agents.py`, `/usr/bin/python3 dot-claude/hooks/agent_guard.py --print-policy`
and `jq .env dot-claude/settings.json`.

Sources: Claude Code docs (sub-agents, hooks, model-config, env-vars, settings-reference), Claude
Code 2.1.284. Turn counts were measured from this machine's transcripts.

## 1. Bugs found and fixed

| # | Symptom | Cause | Fix |
|---|---|---|---|
| 1 | Claude Desktop runs one subagent at a time and seems to hang | Agent SDK apps (Desktop, Conductor, VS Code, Zed, `claude -p`) give the Agent tool a `run_in_background` parameter. The rules told every agent, BlackCat included, to pass `false`, so each child ran in the foreground and blocked the main thread for its whole run (child `meta.json`: `requestShape: "foreground"`). | The hook drops `run_in_background: false` from BlackCat's calls (`BLACKCAT_BACKGROUND=1`). BlackCat's prompt no longer asks for the foreground. Only subagents pass `false`, because in the SDK a subagent does not wait for its background children. |
| 2 | BlackCat shows nothing in Desktop and never asks questions | The main thread was blocked on a foreground child (bug 1), and the prompt allowed silent turns. The main thread also ran at `low` effort, where it skips clarifying questions. | Every turn ends with a visible message. Rule 4 now asks via AskUserQuestion (1–4 questions) about format, scope, costly choices and destructive steps, and relays a child's open questions to the user. Recommended session effort is `medium`. |
| 3 | Settings could silently disable background scheduling | `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT` in settings env | The installer removes both and warns. `/stack-doctor` warns about them and about `BLACKCAT_BACKGROUND=0`. |
| 4 | BlackCat ran out of dispatches on large prompts | 6 dispatches, 8 steps and a 30 s dispatch window; eight long briefs in one message take longer than 30 s | 8 dispatches, 12 steps, 120 s window |
| 5 | The session limit could throttle a full fan-out | `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` was 20, below BlackCat 8 × orchestrator 10 | 32 |
| 6 | supreme-coder's prompt said it could not spawn at depth L3 | Wrong depth in the text (only L4 cannot spawn) | Corrected to L4 |
| 7 | Mixed models (Fable on supreme-coder) | Drift | Every agent names `opus` or `sonnet`; the IDs come from stack.env (section 2), enforced by lint |
| 8 | `/stack-doctor` returned STATUS: blocked: its agent had no Bash | The skill forked `claude-code-guide` (`context: fork`). A forked skill's agent gets its `tools` only from the main conversation's tool pool, and BlackCat has no Bash, WebFetch or WebSearch, so it was left with Read, ToolSearch and Skill. Even with Bash, the guard holds claude-code-guide (and verifier) to read-only commands and refuses `bash doctor.sh`, and any agent's sandboxed Bash cannot read stack.env or `~/.claude.json` nor write the state dir, so doctor.sh reports false FAILs there | `/stack-doctor` is answered by a UserPromptExpansion hook (matcher `stack-doctor`, `bin/doctor.sh --hook`): it runs doctor.sh outside the sandbox and blocks the expansion with the FAIL lines, the WARN lines (each with its section) and the ok count; no model turn. The skill body is only the fallback when the hook did not run |

## 2. Models

- **Rule:** the alias is the reference; it resolves to `ANTHROPIC_DEFAULT_<FAMILY>_MODEL`. Every agent's `model:` is one of two aliases, and lint rejects any other value.
  - `opus` for judgment-heavy work.
  - `sonnet` for extraction, lookups, loops and verification.
- **Where the IDs live:** `stack.env` only, in three variables: `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL`. `lib/stack.env.example` ships today's IDs, with their source and date.
  - `install.sh` copies the non-empty ones into the `env` block of `~/.claude/settings.json`. Re-run it after a change.
  - Upgrading appends the missing variables to your `stack.env`, set to the stack's IDs. A key already in the file, even commented out, is left as you wrote it.
  - A value you set in `settings.json` yourself is kept, and the installer reports it.
  - Lint fails on a specific ID (`claude-<family>-<version>`) anywhere else. The exceptions are the installer's `OLD_DEFAULTS` migration list, doctor's `MEASURED_MODELS` record, the lint's own test vectors (`tests/test_lint_skills.py`) and `legacy/` (byte-exact templates of a released version that the installer recognises on upgrade; none kept today).
- **Frontmatter can't name a variable.** The subagent docs list only aliases, full IDs and `inherit` for `model:`, and say nothing about expanding `$VAR`. So agents name the alias, and Claude Code resolves it.
- **Where it resolves** (code.claude.com/docs/en/model-config and sub-agents, checked 2026-10-02):
  - The variables set what `opus`, `sonnet` and `haiku` resolve to. The `haiku` one also sets Claude Code's background work.
  - Claude Code writes a settings file's `env` over the inherited environment in most sessions, so `settings.json` wins over a shell export.
  - Terminal and `claude -p`: verified in the docs.
  - Agent SDK: verified in the docs. `query()` reads user settings unless `settingSources` excludes them; `bin/stack_sdk.py` passes user, project and local.
  - Desktop Code tab: the docs say settings `env` reaches Claude sessions. A host that sets `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` ignores these variables only in a *managed* `env` block. Unverified on a live Desktop session.
- **Exception:** when the main conversation already runs a model of the same family, a family alias in frontmatter gets the main conversation's exact model. If you pick an older Opus as the main model, the `opus` agents run it too.
- **BlackCat** (the main thread) runs on `sonnet`.
- **No Haiku anywhere.** `ANTHROPIC_DEFAULT_HAIKU_MODEL` holds the Sonnet ID, which moves Claude Code's small-model slot (background tasks, titles) to Sonnet. The key is kept deliberately: it is the only way to move that slot.
- **Model change:** `/stack-doctor` prints what each alias resolves to. It warns when Opus or Sonnet differs from `MEASURED_MODELS`, the models the soft token limits and maxTurns were measured on. Re-derive those values with `tests/derive_thresholds.py`, then update `MEASURED_MODELS` in `bin/doctor.sh`. The check makes no model call.

## 3. Per-agent parameters

Column key:

- **Effort** binds only when the agent runs as a subagent. The main thread uses the session level.
- **Children**: how many of its own subagents may run at once, enforced by the hook. "leaf" = no Agent tool.
- **Was**: the value at the 2026-09-28 commit "Guard: session context budget 666M; README caps
  consolidated" (see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)), shown
  only where it changed.

| Agent | Model | Effort | maxTurns | Children | Was | Why |
|---|---|---|---|---|---|---|
| blackcat (main thread) | Sonnet 5.5 | medium (session) | none | 8 dispatches/prompt | effort low | Only delegates (no Bash, Write or Edit; Read ≤ 3 per prompt for the ledger, a plan or a child's output); the orchestrator gets dependent multi-specialist work. At `medium` it asks questions and stays visible. |
| orchestrator | Opus 5.5 | high | 200 | 32 | xhigh, 300 | Decomposes a job into up to 32 parallel tasks. On 5.5, `high` is enough for coordination. |
| planner | Opus 5.5 | xhigh | 60 | 8 | 100 | Read-only design work that needs deep reasoning and few turns |
| plan-reviewer | Opus 5.5 | high | 60 | leaf | xhigh, 100 | Critique against the code and docs. `high` suffices on 5.5. |
| oracle | Opus 5.5 | low | 12 | leaf | 20 | Answers from knowledge alone and uses almost no tools |
| scout | Sonnet 5.5 | low | 11 | leaf | 40 | Looks up one fact from a few sources; measured max 7 turns (2026-10-02) |
| explore | Sonnet 5.5 | low | 40 | leaf | (built-in) | Read-only codebase search. Replaces Claude Code's built-in Explore, which inherits the main thread's model up to Opus and has no turn cap. |
| researcher | Opus 5.5 | high | 130 | 4 | 170 | Measured p90 is 82 turns. 4 children = 2 researcher copies + 2 lookups. |
| mathematician | Opus 5.5 | xhigh | 100 | 3 | — | Proofs need depth, not many turns |
| proof-checker | Opus 5.5 | xhigh | 80 | leaf | new | Referees one argument: depth over turns; Lean goal loop; read-only (hook) |
| quantum-engineer | Opus 5.5 | high | 160 | 3 | xhigh, 190 | Code and simulation loops. `high` on 5.5. |
| image-director | Opus 5.5 | medium | 80 | leaf | 100 | Prompt and spec work with short loops |
| designer | Opus 5.5 | high | 150 | 3 | 100 | Iterative vector and raster work needs more turns |
| motion-designer | Opus 5.5 | medium | 150 | 3 | high, 190 | GUI and tool loops, not deep reasoning |
| cg-artist | Opus 5.5 | medium | 150 | 3 | high, 190 | Same reason: DCC tool loops |
| vfx-td | Opus 5.5 | high | 170 | 3 | new | Houdini cook, sim and render loops (hython, husk) |
| writer | Opus 5.5 | medium | 80 | 3 | 130 | Prose; voice matters more than depth |
| doc-specialist | Sonnet 5.5 | medium | 100 | 3 | Opus, 130 | Extraction and formatting work |
| coder | Sonnet 5.5 | medium | 170 | 3 (+2 copies) | — | Small and medium implementation. 2026-10-02 data: p90 107 turns per segment (× 1.5 = 160), healthy max 169 |
| main-coder | Opus 5.5 | xhigh | 350 | 6 | 250 | Large codebases; long refactors. 2026-10-02 data: p90 228 turns per segment (× 1.5 = 342; 9 segments of one agent, the longest turn-limited at 300), healthy max 57. Offloads to coder and the ML engineers. |
| ninja-coder | Opus 5.5 | max | 300 | 5 | 250 | The hardest algorithmic and mathematical cores, worked through without the user |
| supreme-coder | Opus 5.5 | max | 350 | 6 | Fable, 250 | Last resort. The orchestrator spawns it, at most once per session. |
| frontend-engineer | Opus 5.5 | medium | 170 | 3 | 190 | Implementation plus browser checks |
| devops-engineer | Sonnet 5.5 | high | 140 | 3 | 190 | Plans and dry runs; bounded scope |
| data-engineer | Sonnet 5.5 | high | 150 | 3 | 190 | SQL and pipelines with recomputation checks |
| data-scientist | Opus 5.5 | high | 150 | 3 | 190 | Analysis with stated uncertainty |
| ml-, dl-, llm-, mlx-, cuda-, robotics-engineer | Opus 5.5 | high | 190 | 3 | — | Long experiment and benchmark loops |
| security-engineer | Opus 5.5 | high | 150 | 3 | new | Implements security fixes and hardening; review stays with security-auditor |
| embedded-, game-, hpc-, biochem-engineer | Opus 5.5 | high | 170 | 3 | new | Domain build, flash, sim and benchmark loops |
| mobile-engineer | Opus 5.5 | medium | 170 | 3 | new | Build-and-run loops on simulators and devices (MobileBuildMCP, macOS only) |
| rust-, haskell-, julia-, go-, python-, jvm-, node-engineer | Opus 5.5 | high | 170 | 3 | new | One expert per language; each self-checks its toolchain (linters, type checker, tests) before reporting |
| db-engineer | Sonnet 5.5 | high | 120 | leaf | new | Schemas, migrations, query plans; postgres-mcp (restricted) and mongodb-mcp-server (`--readOnly`) inline |
| test-engineer | Sonnet 5.5 | medium | 100 | leaf | new | Writes and repairs tests only |
| build-fixer | Sonnet 5.5 | low | 60 | leaf | new | Turns a red build green with the smallest change; never disables checks |
| localizer | Sonnet 5.5 | medium | 80 | leaf | new | i18n extraction, message catalogs, locale QA |
| code-reviewer | Opus 5.5 | high | 80 | leaf | xhigh, 150 | Read-only review. `high` on 5.5. |
| verifier | Sonnet 5.5 | high | 140 | leaf | 160 | Measured p90 is 92 turns: runs tests, reproduces, checks |
| security-auditor | Opus 5.5 | xhigh | 100 | leaf | 150 | Finding exploit paths needs depth |
| browser-operator | Sonnet 5.5 | medium | 120 | leaf | 160 | Browser loops. It has come close to the 64-per-prompt MCP cap (62 calls in one run). |
| mcp-broker | Sonnet 5.5 | medium | 60 | leaf | 80 | Mounts, calls and unmounts MCP servers |
| claude-code-engineer | Opus 5.5 | high | 150 | 3 | 150 | Validation-heavy. 2026-10-02 data: p90 83 turns per segment (× 1.5 = 125), healthy max 147 |
| claude-code-guide | Sonnet 5.5 | low | 30 | leaf | 40 | Documentation lookups |

Effort scale:

- On the 5.5 models, `medium` matches or beats Opus 5 at `high`. The docs call `max` "prone to overthinking", so it is kept for ninja-coder and supreme-coder only.
- `CLAUDE_CODE_EFFORT_LEVEL` would override every agent's effort. Leave it unset.

maxTurns:

- One turn is one model response.
- Values as of the token-lean overhaul (2026-10-02): where a p90 was measured, at least 1.5 × that p90, within the lint caps.
- Re-check of 2026-10-02 (`tests/derive_thresholds.py`, 163 finished segments of two sessions; one turn = one API call, i.e. one assistant message deduplicated by message id and request id, counted per segment — a spawn or a resume — as maxTurns counts them: the harness verifier stopped at exactly 150 calls under maxTurns 150). Raised to max(p90 × 1.5, healthy maximum), rounded up to 10: claude-code-engineer 120 → 150, coder 150 → 170, main-coder 240 → 350. verifier keeps 140 (verification jobs: p90 91, max 91; the 150-call segment was a harness build, now routed to a builder by its prompt). Every other observed type's maxTurns is above its healthy maximum (scout 11 vs 7, code-reviewer 80 vs 66, researcher 130 vs 52, planner 60 vs 35, browser-operator 120 vs 43, claude-code-guide 30 vs 11, explore 40 vs 8, writer 80 vs 10, orchestrator 200 vs 14); the other types have no runs yet.
- When an agent reaches its limit, it is marked partial. A SendMessage resume gives it a fresh budget.
- Lint enforces ≤ 350 for all agents, and < 200 for all agents except the orchestrator and main-, ninja- and supreme-coder.

## 4. Spawn policy

- **Source of truth:** `POLICY` in `agent_guard.py`. The "May spawn" sentences must match it (lint-checked). Every agent with a POLICY row has the Agent tool.
- **Depth:** BlackCat → L1 → … → L8. L8 cannot spawn (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=8`).
- **BlackCat:** may dispatch every specialist except supreme-coder, db-engineer and localizer (`BLACKCAT_VIA_HEADS`; those two are reached through the orchestrator or a domain head such as data-engineer, devops-engineer, writer or frontend-engineer). A job of a few tool calls (a look, a small edit, one command, git inspection) it does itself with Read, Bash, Write and Edit, under the same hooks, deny rules and sandbox as any agent; anything needing a skill, specialist judgement, tests or review is dispatched (§9, 2026-10-03 "BlackCat does small jobs itself").
- **Language agents** (rust-, haskell-, julia-, go-, python-, jvm-, node-engineer) share one row (`_LANG_ROW`: coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker; python-engineer adds data-engineer). BlackCat, the orchestrator and main-, ninja- and supreme-coder spawn them; domain experts spawn the one that fits (embedded- and game-engineer → rust, hpc → julia, biochem → python, frontend → node).
- **supreme-coder:**
  - Only the orchestrator may spawn it, once per session (`SUPREME_SPAWNERS=orchestrator`, `SUPREME_ONCE_PER_SESSION=1`), and only after a ninja-coder of the same session has finished (`SUPREME_AFTER_NINJA=1`). The hook checks the order only (a ninja-coder stopped, or its Agent call reported a terminal status), not that it failed; that ninja-coder may have been spawned by any agent of the session.
  - Any other agent that needs it returns `STATUS: partial` with `NEXT: supreme-coder` and a dossier.
  - In a plan: planner may add one supreme-coder step, only as the conditional fallback of a preceding ninja-coder step on the same problem; plan-reviewer blocks a step without that ninja-coder step, an unconditional one, a second one or an incomplete dossier; BlackCat sends such plans to the orchestrator; the orchestrator runs ninja-coder first and spawns supreme-coder only when ninja-coder reports failure or partial, dropping the step if ninja-coder succeeds. That it failed is enforced by these prompts, not by the hook.
  - A failed or refused spawn releases the session slot. SendMessage resumes of that supreme-coder pass.
  - `claude-supreme` (supreme-coder as your own main thread) is unaffected.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker, claude-code-guide, browser-operator, plan-reviewer, image-director, explore, proof-checker, db-engineer, test-engineer, build-fixer, localizer.
- **No generic agents:** `subagent_type` must name a stack agent in the caller's row: a missing type, `general-purpose`, `claude`, `fork`, `Plan`, `statusline-setup`, host-defined types such as `SubAgent` and plugin agents are refused for every caller (BlackCat's row is its own list; a caller without a row may spawn every stack agent on a main thread — supreme-coder still only under `SUPREME_SPAWNERS` — and nothing as a subagent; an agent context of no known type keeps BlackCat's row), also through the tool's `Task`/`SubAgent` aliases. A generic agent started outside the Agent tool (a skill with `context: fork` and no `agent:`, a workflow stage without `agentType`) has every tool call refused. Each workflow `agent()` names a stack `agentType` the caller may spawn, with no `model`; bundled and plugin workflows (`/deep-research`) are refused. settings.json: `Agent(general-purpose)`, `Agent(claude)`, `Agent(fork)` deny rules, `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1`, `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` (`claude -p` and Agent SDK apps).
- **Copies:** only researcher and coder may spawn copies (`researcher-copy`, `coder-copy`), at most 2 at once (`STACK_MAX_SELF_FANOUT=2`).

## 5. Guard knobs and settings

Values in `dot-claude/settings.json`. Those marked "code" are defaults in `agent_guard.py`, with no settings entry.

| Key | Value | Was | Why |
|---|---|---|---|
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | 33 | 20 | Room for an orchestrator's 32 running children plus the orchestrator itself without hitting the session limit |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` | 8 | — | Eight layers below BlackCat |
| `BLACKCAT_MAX_DISPATCH` | 8 | 6 | Enough to cover a multi-domain request in one burst |
| `BLACKCAT_MAX_STEPS` | 24 | 12 | Dispatches plus relays, questions and reads within one prompt; 12 ran out on long prompts (the user, 2026-10-03) |
| `BLACKCAT_DISPATCH_WINDOW_S` | 120 | 30 | Eight long briefs in one message take longer than 30 s to emit |
| `BLACKCAT_BACKGROUND` | 1 (code) | new | Drops BlackCat's `run_in_background: false` (fixes bug 1) |
| `BLACKCAT_MAX_OWN_STEPS` | 0 (code) | 4 | BlackCat's own Bash/Write/Edit calls per prompt: 0, BlackCat only delegates (any other agent on the main thread is not restricted; its `tools` line lists none of them; the guard refuses them too) |
| `BLACKCAT_MAX_READS` | 3 (code) | new | BlackCat's Read calls per prompt: the delegation ledger, a plan, a child's output file; 24 − 3 leaves room for a full burst of 8 dispatches |
| `BLACKCAT_BASH_TIMEOUT_MS` | 120000 (code) | new | Longest timeout a BlackCat foreground Bash call may ask for, only with `BLACKCAT_MAX_OWN_STEPS` > 0; with none given, `BASH_DEFAULT_TIMEOUT_MS` counts (2 min out of the box) |
| `STACK_AGENT_LABEL` | `description` (code) | new | `description\|name\|off`. `description` prefixes each allowed Agent call's description with `<type>: ` (Claude Code shows `agent-name(description)`); `name` names an unnamed child `<type>-<n>`; zero prompt tokens |
| `STACK_AGENT_STARTED` | 1 (code) | new | SubagentStart gives a stack agent its local start time for the clean-finish line; 0 disables it |
| `STACK_REPORT_FORMAT` | `observe` (code; unset or any other value) | new | `observe`: SubagentStop checks and records every spawned stack subagent's final reply, PreToolUse(Agent) records the brief's size; nothing is output, warned or blocked, the prompt is unchanged. `compact`: the same plus one restate per run on a hard violation and a brief warning (not the default: planned for Phase 2). `json`: SessionStart (main thread, every source) and SubagentStart (stack agents) add one line asking for the final report as one JSON line, which `bin/stack_sdk.py` `parse_report` reads, plus a logged shape check. `off`: no check, no log (the rollback). See "Message protocol" below. For Agent SDK apps (`env` option) |
| `STACK_MAX_FANOUT` | 3 | — | Default number of running children per agent |
| `STACK_MAX_FANOUT_BY_TYPE` | `orchestrator=32,supreme-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | `orchestrator=8,planner=8,plan-reviewer=8` | The coordinators get room; everyone else keeps 3 |
| `STACK_MAX_SELF_FANOUT` | 2 | — | Copies per base agent |
| `SUPREME_SPAWNERS` | `orchestrator` (code) | new | Only the orchestrator spawns supreme-coder |
| `SUPREME_ONCE_PER_SESSION` | 1 (code) | new | At most one supreme-coder spawn per session |
| `SUPREME_AFTER_NINJA` | 1 (code) | new | A supreme-coder spawn needs a ninja-coder of this session that has finished; checks order, not failure; 0 = off |
| `SUPREME_IDLE_S` | 1800 | — | Time after which an idle supreme-coder releases the lock |
| `STACK_MAX_MCP_CALLS` | 64 | — | MCP calls per agent per prompt, as set by you; unchanged (browser-operator comes near it) |
| `STACK_PROMPT_CTX_BUDGET` / `STACK_SESSION_CTX_BUDGET` | learned (seed 100,000,000 / 1,920,000,000), not in settings.json since S6 | — | A value you set pins `hard.prompt` / `hard.session` (`/stack-doctor` lists it) (hard: refuses every call but reporting). Since 2026-10-02 the prompt window restarts only on a human prompt, not on a task notification's turn |
| Soft token limits (code: `SOFT_LIMITS`, `SOFT_PROMPT_CTX`) | per type, below; 33,000,000 per human prompt (80,000,000 while an orchestrator runs: `SOFT_PROMPT_CTX_BY_TYPE`) | new | A wrap-up warning, never a refusal; see "Soft token limits" below |
| `STACK_SOFT_LIMIT_SCALE` | unset = 1 (code) | new | Multiplies every soft limit; `0` turns them off. Not in settings.json, so a process environment value reaches the hooks (the benchmark sets it per run) |
| `STACK_SCHED_POLICY` | `report` (code) | `fresh_fixer` | The user's decision (2026-10-03): the scheduler stays a report tool. `fresh_fixer` is opt-in: `stack_sched.py next` then also advises a fresh fixer on stderr for a resume after a gap of 270 s or more (stdout, the ready ids, is the same). Fixed knob, recorded in each session's snapshot and read from it |
| `STACK_FANOUT_IDLE_S` | 600 | — | A silent background subtree stops counting against the caps |
| `STACK_FANOUT_SESSION` | `shadow` (code) | new | Session slot guard for every caller, the main thread included: live spawn leases and resume reservations plus live background agents (idle ones too; a SubagentStart record alone never counts) against `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (20 when unset), checked under the `fanout` mutex for each spawn and each resume of a finished agent. Claude Code refuses an Agent call past that limit without a retry and checks no resume. `shadow` logs each count to `fanout-session.jsonl` in the session's state dir and refuses nothing; `enforce` also refuses a spawn or resume with no free slot; `off` = no lock, no count. `STACK_POLICY=off` turns it off. Shadow by default: a background child whose stop event never arrives keeps counting until SessionStart. Not counted: agents Claude Code starts without an Agent call. Fixed knob (dynamic fan-out plan, step 3) |
| `STACK_FANOUT_DYN` | `shadow` (code) | new | Dynamic fan-out cap (`hooks/stack_fanout.py`) for the types in `STACK_FANOUT_DYN_TYPES` (orchestrator), never the main thread or BlackCat: `shadow` computes each spawn and resume decision from the orchestrator's `plan.dag.json`, the token budget, the AIMD window and K_sess, logs it to `fanout-dyn.jsonl` and refuses nothing; `enforce` also refuses with the terms in `STACK_FANOUT_DYN_ENFORCE`; `off` = nothing runs, no file is written (the rollback). An unset, empty or unknown value is the default, `shadow`; `STACK_POLICY=off` forces `off`. Never above the static cap; any error is the static decision. See "Dynamic fan-out cap" below. Fixed knob (plan step 5b) |
| `STACK_FANOUT_DYN_{ENFORCE,TYPES,W0,WMIN,ALPHA,BETA_RL,BETA_FAIL,HOLD_S,RESERVE_TOK,SLACK,NODE_RUNS,DELAY_RATIO,BREAKER}` | `node,deps` / `orchestrator` / 8 / 1 / 1 / 0.5 / 0.75 / 60 / 8000000 / 2 / 7 / 1.5 / `5/600` (code) | new | The terms enforced (`node`, `deps`, `conflict`, `budget`, `aimd`; `budget` and `aimd` wait for the shadow campaign), the types in scope, the AIMD window's start, floor, step, cuts and hold, the tokens held back from the budget, unplanned spawns allowed past the plan, runs per plan node, the delay signal (logged only) and the breaker (that many dynamic refusals in that many seconds with no new child send the orchestrator back to the static cap). An invalid value takes its default with a warning. Fixed knobs, never learned |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | — | Unchanged |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | from `stack.env` (Opus, Sonnet, Sonnet) | moved | Copied from `stack.env` by the installer; the haiku slot holds the Sonnet ID (section 2) |
| `MCP_DISCOVERY_CACHE` / `MCP_TIMEOUT` / `MAX_MCP_OUTPUT_TOKENS` | 1 / 60000 / 25000 | — | Unchanged |
| `agent` | `blackcat` | — | BlackCat is the main thread in the terminal and in SDK apps |
| `permissions.defaultMode` | `plan` | `bypassPermissions` | Every session starts in Plan (the user, 2026-10-03). Not owned: the installer keeps a mode you set, and moves an install still on the previously shipped `bypassPermissions` to `plan` once ("Permission modes" below) |
| `STACK_MODE_PROBE` | 0 (code) | new | `1` = diagnostic: one JSON line per PreToolUse, PermissionRequest and SubagentStart event in `<state root>/mode-probe.jsonl` (time, session, event, tool name, agent type and id, depth, `permission_mode` when present; never the tool input; 0600; stops at 1 MB). Decides nothing |
| `autoCompactWindow` | 629000 | 400000 | Compaction at ~629K tokens. The pinned 5.5 models run a native 1M window on the Anthropic API (no `[1m]` suffix, nothing to set; `CLAUDE_CODE_DISABLE_1M_CONTEXT` would cap them at 200K). The one place the number is set: the installer re-asserts it, doctor and the smoke test check it |

### Dynamic fan-out cap (2026-10-03)

From the dynamic fan-out plan (revision 2; steps 3-5b built, the shadow and enforce campaigns are user steps). Decision core `hooks/stack_fanout.py` (pure, stdlib; `stack_fanout.py check PLAN.json`, `stack_fanout.py report --session SID [--json]`); guard side `hooks/stack_fanout_wire.py`, which `agent_guard.py` imports only while the switch is not `off` and a cheap pre-gate passes (caller type in `STACK_FANOUT_DYN_TYPES`, a `plan.dag.json` path, or an existing `fanout-dyn/` folder), so a call of any other agent costs no import and no file access. The default is `shadow` since 2026-10-04 (before: `off`).

- **Plan:** the orchestrator writes `./.claude-work/<job>/plan.dag.json` (`{"job", "slack"?, "nodes": [{"id", "a", "alt"?, "dep", "w", "rd", "r"}]}`, a subset of the `stack_sched` graph) with Write. The `budget` PreToolUse hook validates `tool_input.content` (never the file on disk: no symlink or race) against the orchestrator's spawn row and the D1 limits (64 KiB, depth 6, 32 nodes, ids `^[A-Za-z][A-Za-z0-9_.-]{0,15}$`, 16 globs of 256 characters, no cycle) and keeps a normalized copy in `<state>/<session>/fanout-dyn/<agent>.plan.json`. The Write gets `plan accepted: N nodes, max width W` or `plan rejected: <reason>; static cap 32 applies` as context; an Edit keeps the previous copy and says to rewrite with Write. A spawn belongs to node `T3` when its `description` starts with `T3` and its type is the node's `a`, its `alt` or a later step of coder → main-coder → ninja-coder → supreme-coder; anything else is unplanned.
- **Decision:** inside the `fanout` mutex, after the session, fan-out and copy checks allowed the call, so it never allows what they refuse. Terms: the node has no live run, fewer than `NODE_RUNS` runs, its dependencies have ended runs, no write-glob or exclusive-tag (gui, accel) conflict with a live node; unplanned spawns within the slack; the AIMD window (ignored with no child running); the token budget (`min(hard.prompt - used, hard.session - total) - running children's expected use - RESERVE_TOK`, costs from the session's sched model); K_sess is reported, enforced only by `STACK_FANOUT_SESSION`. A resume has no plan terms. Glob-overlap work is capped at 20 ms per pass; past it the conflict term is skipped.
- **Shadow (`STACK_FANOUT_DYN=shadow`, the default):** each decision is one line in `<state>/<session>/fanout-dyn.jsonl` (mode, kind, allow, would_allow, cap, binding term, deny code, node id, terms, eligible count, running children, delay ratio; 0600, no more lines past 4 MiB); AIMD changes go to `fanout-dyn-events.jsonl`. Nothing is refused; the main thread and BlackCat are never in scope.
- **Enforce:** a refusal reads `Dynamic fan-out (<code>): <why> Free slots: N; ready nodes: <ids>.` (fixed text, integers and validated ids only), e.g. `node T2 waits on T1, not ended yet.`, `node T1 already has a live run. Wait for its task notification, or TaskStop it if it is stuck.` Five refusals in 600 s with no new child trip the breaker: that orchestrator gets the static cap until the session restarts.
- **Node runs and rollback:** a run is recorded when a spawn is allowed, bound to its child at PostToolUse, ended at SubagentStop, TaskStop or StopFailure. A spawn a later gate refuses (supreme-coder once per session or busy, BlackCat markers, taint) and a failed or denied Agent call (PostToolUseFailure, PermissionDenied) remove their run, so the node is free again; a run whose lease is gone with no child bound counts as aborted anyway.
- **AIMD:** `+ALPHA` on a healthy finish (stopped normally, within the type's `wall_hi`, no soft per-agent hit, budget left ≥ 25 % of `hard.prompt`); `×BETA_RL` on StopFailure `rate_limit`/`overloaded` or a PostToolUseFailure carrying "Concurrent subagent limit reached" (that text is unverified); `×BETA_FAIL` on `server_error`/`unknown`; at most one cut per `HOLD_S`.
- **Fail to static:** any exception, an unreadable or corrupt state file, a missing module or a lock timeout in the dynamic layer gives the static decision; state lives only in the hook state dir and `fanout-dyn/` goes with `fanout/` at SessionStart startup|resume.
- **Rollback:** `STACK_FANOUT_DYN=off` in the process environment; the code path is then the static one, with no import and no file.
- **Open:** whether StopFailure fires inside subagents (if not, the window falls only on PostToolUseFailure and a child ending that way counts until SessionStart); the exact PostToolUseFailure text at Claude Code's spawn limit (0(e)); whether idle background agents and Claude Code's internal agents (0(d)) take session slots.

### Soft token limits (2026-10-02)

- **What:** past a limit, the next tool call carries one short warning (PreToolUse `additionalContext`): "Soft token limit reached …: wrap up, return STATUS: partial with what is done and what remains, and ask your caller (BlackCat: the user) before continuing." Nothing is refused; the hard budgets above, the MCP call cap and maxTurns are unchanged and independent.
- **Unit:** context tokens, `input + cache_creation + cache_read` per API call (output excluded), the hard budgets' unit, counted in the same `budget.json` pass.
- **Per agent segment:** one subagent run, a spawn or a SendMessage resume (the MCP call cap's reset rule: the registry's `started` stamp), from the agent's own transcript; warns once per segment. **Per human prompt:** 33,000,000 since the last UserPromptSubmit, whole session tree; 80,000,000 while an orchestrator runs (`SOFT_PROMPT_CTX_BY_TYPE`, set by the user on 2026-10-03, not derived); warns once per prompt, to the agent whose tool call comes next. No per-session soft limit (two sessions are not a distribution).
- **Values** (soft = p90 of healthy segments × 1.25–1.5, floor 2 × median, 2 significant figures; a type with fewer than 5 healthy segments from 3 agents takes its pool's value):

| Limit | Types | Derived from |
|---|---|---|
| 19,000,000 | claude-code-engineer | own runs (36 segments) |
| 26,000,000 | verifier | own runs (6) |
| 8,700,000 | code-reviewer | own runs (5) |
| 680,000 | claude-code-guide | own runs (7) |
| 390,000 | scout | own runs (24) |
| 19,000,000 | coder, main-coder, ninja-coder, supreme-coder, build-fixer, test-engineer, data-scientist, data-engineer, db-engineer, devops-engineer, frontend-engineer, the 7 language engineers, mobile-, game-, embedded-, hpc-, cuda-, mlx-, dl-, ml-, llm-, robotics-, quantum-, biochem-, security-engineer, vfx-td, mathematician | builder pool (49) |
| 8,700,000 | planner, plan-reviewer, researcher, security-auditor, proof-checker | analyst pool (11) |
| 450,000 | explore, oracle, mcp-broker | lookup pool (34) |
| 3,100,000 | writer, browser-operator, doc-specialist, designer, image-director, localizer, motion-designer, cg-artist | artifact pool (6) |
| none | orchestrator (short relays; two runs that differ ~2×), blackcat (the main thread: the prompt limit covers it) | — |

- **Knob:** `STACK_SOFT_LIMIT_SCALE` (float; `2` doubles every soft limit, `0` turns them off). A copy type uses its base's value; a type the table does not name gets none (self-test: the table covers every type in `AGENTS`).
- **Refresh:** `uv run --script tests/derive_thresholds.py` (pandas, read-only over `~/.claude/projects/`) rewrites `.claude-work/agents-usage/thresholds.md` and its CSVs (first run as `.claude-work/agents-usage/thresholds.py` in the phase-3 worktree); copy changed values into `SOFT_LIMITS` / `SOFT_PROMPT_CTX` by hand.
- **Revisit** when the healthy segment count of a type, or the number of sessions, doubles, and after any major stack change (agent prompts, skill loading, models, maxTurns). Today's counts: orchestrator 46, claude-code-engineer 36, scout 24, claude-code-guide 7, coder 7, verifier 6, main-coder 6, code-reviewer 5, researcher 4, browser-operator 4, explore 3, planner 2, writer 2; sessions 2. All values except claude-code-engineer and scout are provisional.

### `stack budget`: where the limits stand (2026-10-03)

`bin/stack-budget` (installed as `<config>/bin/stack-budget`, stdlib Python 3.8+, a CLI tool run outside the hooks with `/usr/bin/python3` or `bin/stack-python`) is the one read-only view of the limits. It never writes a snapshot, `live.json` or any state: a session's limits are fixed at its start (S6, U4), and `stack_limits.py` is the only way to change what the next session starts with. It takes the session from `--session`, else `STACK_LIMITS_SNAPSHOT`, else `CLAUDE_SESSION_ID`, else the newest snapshot (said so), else the seed.

| command | shows |
|---|---|
| `stack-budget [--all]` | this session's frozen limits with their origin (env / live / seed / frozen), the guard's token count for the prompt and the session against them, and per type turns / soft / hard with the p90 of completed runs and its 90% CI |
| `stack-budget plan GRAPH.json` | stack_sched estimate (turns and ctx, median to hi) with a verdict per node and for the whole plan against the prompt and session limits (what the session already used counts) |
| `stack-budget agent TYPE` | seed, live and snapshot values of one type, status, n, interval, the sample statistics of `runs*.csv`, `runs2*.csv` and `runs3*.csv` and the last 5 rows; like the learner, the samples leave out the runs on another model than the type's frontmatter one (`/override-agent`) and every view shows how many |
| `stack-budget static` | the static prompt budget of `tests/prompt_budget.py` (repo checkout only) |

Every command takes `--json`. Verdicts are three-way: fits (the interval's upper end is within the limit), does not fit (its lower end is over it), uncertain (it straddles the limit, or there is no interval, n < 3). A learned value that is not `supported` always prints its interval. Exit 0 ok, 1 invalid input, 2 limits unavailable.

### `stack-tree`: agents and their commands (2026-10-03)

`bin/stack-tree` (installed as `<config>/bin/stack-tree`, stdlib Python 3.9+, `#!/usr/bin/python3 -B`; its `/stack-tree` hook runs it with `bin/stack-python`) prints a session's tree of agents and subagents with the tool calls each ran as leaves; `/stack-tree` is the same from any session, BlackCat included: a UserPromptExpansion hook (matcher `stack-tree`, `"__PYTHON3__" -B "__CLAUDE_DIR__/bin/stack-tree" --hook`, timeout 30 s) runs it with the command's arguments and blocks the expansion with the output as the reason (exit 2), so no model turn runs and no Bash is needed; the skill body is only the fallback when the hook did not run. The hook defaults to the event's own session, 3 distinct commands per agent and 140 columns, and cuts its output at 16,000 characters with the terminal command for the rest, `--session` included (unverified whether Claude Code caps a block reason itself). It stops itself after 20 s: transcripts not yet read show as `transcript unscanned`, text not yet filtered as `(withheld: time budget)`, never raw.

| mode | shows |
|---|---|
| `stack-tree` | header (agents, running, failed/blocked/partial/stopped, tool calls), then BlackCat and every agent: type, task, status, duration, tokens, calls; its commands collapsed (`$ git status ×3 [1 exit 1]`), then its children. `--depth N`, `--no-leaves`, `--leaves-only-failed`, `--max-leaves N` (default 10, 0 = all), `--session ID` (default: the newest ledger), `--ascii`, `--width W` (default the terminal), `--json` |
| `stack-tree --table` | GitHub-flavored markdown, one row per agent and per tool call; `--columns a,b,c` or `all`, `--csv`, `--json`, `--width` caps the cells (default 80). Leaf rows carry the agent's level and depth + 1 |
| `stack-tree --pending` | live tree, table or JSON of what needs attention: running or launching agents, failed or blocked ones, and finished agents not yet handled (handled = a foreground Agent call returned the result, ledger status `completed`, or a registry `handled` mark, which nothing writes yet: planned for the compaction read-back, NEXT_STEPS §13h); ancestors are kept; not with `--static`. Table columns `eflag` and `report`, JSON keys `eflag` and `report` |
| `stack-tree --static [--table]` | the designed hierarchy: breadth first from BlackCat's `Agent(...)` allowlist through each agent's "May spawn:" sentence (the one `tests/lint_agents.py` checks against POLICY), each agent expanded once at its shallowest level (later occurrences point there), nothing expanded at L8; leaves are BlackCat's user commands and the skills each agent's `## Skills` section names (`*` = a hub module read by path) |

- **Sources** (all read, none written): `spawns/*.json` (the delegation records `delegations.md` is rendered from; the file itself only when `spawns/` is absent), `agents/*.json` (parent, spawned, started, resumed, stopped, transcript) and Claude Code's transcripts, `<projects>/<project>/<sid>.jsonl` and `<sid>/subagents/agent-<id>.jsonl`, for each agent's tool calls, their results, the token usage of each API message (input + cache writes + cache reads + output, once per message id, the largest value over the lines it spans: Claude Code writes one line per content block and the earlier ones carry a partial `output_tokens`) and the final STATUS line (done, partial, blocked; a finished report without one is a clean finish). The hooks keep no per-call log of their own, and none was added: the transcripts already hold every call.
- **Status:** the ledger's lifecycle (launching, running, finished, failed, stopped), with one difference: an agent resumed (SendMessage) and not stopped since is running (the resume's SubagentStart clears `stopped`; a foreground child's record stays `completed`). A finished agent shows its report status. Start is the earliest of started, spawned, the record's time and the transcript's first line (a foreground child's registry entry is written when its call returns; a resumed one's `started` is its resume).
- **Unrecorded:** tokens per tool call, the arguments of MCP calls (only server.tool is shown), tool results (only ok, exit N, blocked or error), the leaves of an agent whose transcript is missing (spawn failed, or a placeholder for a caller whose own spawn is in neither source), and everything but type, task and state when only `delegations.md` exists.
- **Untrusted text:** task, name, type, command, path, URL and query strings pass one filter: they are cut to 1,200 characters (at most 300 are shown), then secret-looking values are masked (`*KEY*=`/`*TOKEN*=`/`*SECRET*=`/`*PASS*=`… assignments, `name: value` and JSON `"name": "value"` pairs whose name holds key, token, secret, password, auth, cookie or credential (headers such as X-Vault-Token or PRIVATE-TOKEN), Authorization/Cookie/API-key headers, Bearer tokens, `--token`-style flags, `mysql -p…`, `sshpass -p`, `docker login -p`, `pass:…`, `aws configure set …secret…`, URL credentials and key/token/signature query values, `sk-`, `sk_live_`/`sk_test_`, `ghp_`, `github_pat_`, `xox?-`, `AKIA`, `hf_`, `AIza`, `glpat-`, `npm_`, `hvs.`, `dckr_pat_`, JWTs, PEM private-key headers; every pattern is linear or bounded by the cut), then C0/C1 controls, DEL, format (bidi, zero-width), separator, surrogate, private and unassigned code points become spaces, then the text is cut. WebFetch URLs lose their query and fragment. Markdown cells backslash-escape backslash, pipe, backtick, `<`, `>`, `[`, `]` and `&` (so a renderer cannot turn `&#x202E;` back into a bidi override); CSV cells that start with `= + - @` get a leading `'`. State files are opened `O_NONBLOCK` and read only when regular (a FIFO cannot hang it), at most 4 MB per record, 256 MB per transcript, 1 GB per run.
- **Read-only:** no file, cache, lock or bytecode is written (`-B` and `sys.dont_write_bytecode`), no network; `tests/test_stack_tree.py` compares a snapshot of the whole fixture tree before and after every mode.

### On demand and automatic: MCP servers, plugins, skills (2026-10-02)

| Kind | Automatic (the situation needs it) | On demand (asked for) | Idle cost, before → after |
|---|---|---|---|
| Skills (214: 128 listed, 32 of them described, 96 name-only; 83 hub modules hidden) | Described skills: their description; name-only skills: their name; both plus a one-line pointer "load X when Y" in the agent or hub that needs it. Hub modules (`user-invocable-only`): the hub's table or the agent's `## Skills` line (marked `name`*) names them, and the agent Reads `~/.claude/skills/<name>/SKILL.md` (the Skill tool refuses them) | the Skill tool by name; hidden modules by Read | Listing on every spawn: 17,647 chars at the phase-2 base (2026-10-02; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)) → 30,782 at ad22962 (all described) → 14,437 (hubs, standalones and 15 entry-grade modules described) → 5,306 now (2026-10-04: 32 described, 96 name-only) |
| MCP, agent-scoped | The agent's inline `mcpServers` plus its `tools:` line: the server starts and stops with that agent | spawn that agent | 0 in other agents (unchanged); tool schemas deferred until tool search loads them |
| MCP, magg catalog (23 servers, all disabled) | A one-line pointer in the agent that has the gap: "X → mcp-broker mounts `<server>`" (devops → `kubernetes`/`grafana`, data-scientist → `sec-edgar`/`gis`/`jupyter`, doc-specialist → `docling`/`docspace`, llm-engineer → `mlflow`, researcher → `arxiv`, game → `godot`, biochem → `biomcp`/`pubchem`, mobile → `mobile`/`android`, embedded → `serial`, frontend → `chrome-devtools`, robotics → `ros`, quantum → `qiskit-runtime`) | ask mcp-broker | 0 until mounted (unchanged); the pointers add ~430 chars to four agent bodies |
| MCP, user scope (exa, jina, wolfram, huggingface, wandb) | session-wide, tools deferred | — | unchanged; nothing new added to user scope |
| Plugins, LSP (pyright, typescript, rust-analyzer, gopls, jdtls, kotlin, clangd, swift; haskell, julia, lean, metals from the stack's marketplace) | enabled; a language server starts when Claude touches a matching file | — | 0 listing (no skills); unchanged |
| Plugins with skills (document-skills, math-olympiad, skill-creator) | enabled, each named by a pointer (doc-specialist, technical-writing, presentation-design → docx/xlsx/pptx/pdf; mathematician, proof-craft → math-olympiad; claude-code-engineer → skill-creator), so none is disabled for being idle; the installer still disables document-skills and skill-creator where claude.ai syncs the same skills (§7, Plugins) | `/plugin enable <id>`, or `"enabledPlugins": {"<id>": true}` in a project's `.claude/settings.json` | 2,919 listing chars (measured); unchanged |
| Bundled Claude Code skills | listed, except seven user-run commands (code-review, security-review, simplify, fewer-permission-prompts, keybindings-help, init, dataviz) that are `user-invocable-only`; update-config is named by stack skills | `/<name>` | ~3,950 → ~2,550 (estimated; cap 250, dataviz hidden) |
| claude.ai-synced skills (`anthropic-skills:*`) | listed, except deep-research, morning, import-memory, consolidate-memory, setup-claude, explain-usage, google-workspace and schedule (`user-invocable-only`, keyed by the full name) | `/<name>` | ~7,300 → ~3,000 (estimated margin; cap 250) |

Per-agent plugin enabling does not exist: plugins are session-wide (user, project or local scope), so an LSP plugin is not agent-scoped; the closest per-project control is `enabledPlugins` in that project's `.claude/settings.json`. No hook enables or installs anything. Lazy skill loading (2026-10-04, the user's decision): only `LISTED_CORE` (32 cross-domain entries, `tests/test_skill_modules.py`) keeps its description in the listing; the other 96 listed skills are `name-only`, invoked by name through the Skill tool, which returns the full SKILL.md. The 83 hub modules are hidden (`user-invocable-only`, design B1x+C of 2026-10-02) and read by path; `tests/test_skill_modules.py` keeps each reachable from its hub's table. The listing budget (`skillListingBudgetFraction` 0.012) covers the stack's 5,433 characters plus ~7,213 for plugin, bundled and claude.ai skills (`tests/lint_agents.py` NON_STACK).

### Usage collector and scheduler model refresh (2026-10-02)

- **What:** `hooks/stack_usage.py` (stdlib, on the hooks' `bin/stack-python`) runs one background collector per session. It reads the session's subagent transcripts by byte offset and appends one row per agent segment (a spawn or a resume) to `runs3.csv`. When the collector exits, `hooks/stack_sched_refresh.py` refits the scheduler's cost model from those rows (it uses `fit()` of `tests/derive_sched_model.py`, installed beside it). `hooks/stack_sched.py` reads the result.
- **Lifecycle:**
  - SessionStart (every source) and SubagentStart run `stack_usage.py start`. It starts the collector detached (`start_new_session`, stdio on `/dev/null`) unless one is already running. An `flock` on `collector.lock` keeps it to one per session.
  - SessionEnd runs `stack_usage.py end`, which only writes an `end` marker. SessionEnd hooks share a 1.5 s budget (https://code.claude.com/docs/en/hooks, "Timeouts"), so the collector does the work: it scans one last time, refreshes and exits.
  - It also exits when the Claude Code process that ran the hook is gone (pid plus start time), or after `STACK_USAGE_IDLE_S` without growth. The next start resumes from the saved offsets.
  - Upgrade hand-off: a collector keeps the code it started with, so after an install a session's collector may still write an older schema (no `model`, so an `/override-agent` run typed after the install would read as unknown and be learned from). A start that finds the lock held checks `collector.json`: no `schema` (or a lower one), `exited` unset, heartbeat at most `HANDOFF_FRESH_S` (120 s) old, pid alive and, where `ps` runs, that pid running this session's `stack_usage.py run` (without `ps`, as in a sandbox, the held lock and the fresh meta are the proof). Then it sends SIGTERM (the older collector scans one last time and exits with reason `signal`: no proposals, no refit) and spawns a successor that waits up to `HANDOFF_WAIT_S` (120 s) for the lock. The successor reads the session again from the start (another schema's `state.json`) and writes schema 3 rows, which win over the older rows of the same key; nothing is rewritten or deleted. An override run is a subagent, so its own SubagentStart (new code after the install) hands off, and the successor's row for it supersedes any the older collector wrote. A collector of this schema or a newer one is never stopped. The stopped collector's final scan also writes a `complete` session row with the context of that moment; `stack_limits.py` leaves out a session row older than another row of its session (`stale_session` in `proposals.json`), so a truncated session is not learned by `soft.session`/`hard.session` when the successor idles out before the session's end.
  - The docs say command hooks "run in their own session without a controlling terminal". They do not say whether a detached child survives the hook. `tests/test_stack_usage.py` checks that it survives a kill of the hook's process group. If it is killed anyway, the next SessionStart or SubagentStart restarts it and nothing is lost.
- **Files** under `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/`:
  - `usage/runs3.csv` (schema 3, append-only, header, `runs3.lock`)
  - `usage/runs3.1.csv` (the archive: past `STACK_USAGE_MAX_BYTES` the file is merged in, last row per key, and the newest sessions are kept up to 4 × the cap)
  - `usage/runs.csv`, `runs.1.csv` (schema 1) and `usage/runs2.csv`, `runs2.1.csv` (schema 2): the earlier collectors' rows, read (a later schema's row of the same key wins) and never written, renamed or rotated. A new file per schema because a collector started before an upgrade keeps running the old code until it exits; with one shared file each version would set the other's header aside.
  - `usage/sessions/<id>/` (`collector.json` with pid, owner, heartbeat and exit reason; `state.json` with offsets; `end`)
  - `usage/refresh.json` (the last refresh)
  - `sched_model.json` (the active model)
  - The guard's three-day prune skips `usage/`; the collector prunes its own session folders after 14 days.
- **Rows:** key (session, agent id, seg), last row wins. Columns: `schema_version`, `type`, `status` (partial while the segment's last event is a tool call or result and the transcript changed within 600 s), `api_calls`, `ctx` (input + cache_creation + cache_read), input, output, cache_creation, cache_read, `first_cc`, `first_cr`, peak, prev_peak, gap_s, `first_ts`/`last_ts` (epoch seconds), wall_s, `compacted` (count), `turn_limited`, `after_limit`; schema 2 added tool counts, writes, parent/depth/node/window, status code, limit hits, snapshot cells, `task`, `stack_commit`, `src`; schema 3 adds `model`, the `message.model` the transcript reports for the segment's calls (one id, `mixed` for two, empty when none; v1/v2 rows read as empty, never guessed). Segments are cut as in `tests/derive_thresholds.py`. On this machine's 188 segments the incremental parser matches `derive_sched_model.load` column for column.
- **Privacy:** numbers and ids (the model id among them) only, plus `task` (the plain words of the Agent description: no digits, paths, URLs, flags or key-like tokens; ≤ 60 chars). No prompt, transcript text, tool input or secret is written; user messages are matched against the resume/compaction patterns in memory only (a test asserts this). No network, no paid calls.
- **Refresh:**
  - When it runs: at the collector's exit only (session end, owner gone, idle), never during a plan. It runs `uv run --offline --script` with the uv cache install.sh warms (`claude-agent-stack-cache/uv`). uv (and the collector's `ps`) are taken from fixed absolute paths (`~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`, `~/.cargo/bin`; `/bin/ps`, `/usr/bin/ps`), never looked up on `PATH`. Without uv or that cache it is skipped silently, and `refresh.json` says so.
  - Target: the shipped `hooks/sched_model.json` combined with `fit()` on every complete row of sessions the shipped model did not use, as an n-weighted mean per type and pool, without the rows of runs on another model than the type's frontmatter one (`refresh.model_mismatch` counts them; "Session model overrides" below). Counts add, and new rows count once `fit()` gives the type a value. A type becomes `supported` at ≥ 5 healthy segments from ≥ 3 agents.
  - Bands: each type's band is combined as for a weighted mean on the log scale, so it narrows as n grows.
  - Bounded step: each value moves at most × `STACK_SCHED_REFRESH_STEP` (default 1.5) per refresh from the model in force. Each type keeps `evidence`, and the file keeps a `refresh` record.
  - It never writes limits, thresholds, maxTurns, prompts or agent files.
  - `stack_sched.py` prefers the active file when it is a JSON object with non-empty `types`; otherwise it uses the shipped one. `STACK_SCHED_MODEL` overrides both.
- **CLI** (your terminal; agents' sandbox cannot read the state folder):
  - `python3 ~/.claude/hooks/stack_usage.py status` (the `/stack-doctor` line)
  - `runs [--session ID] [--json]` (the agent-run view: segments summed per agent)
  - `refresh [--online] [--force]` (`--online` lets uv download pandas/numpy)
  - `propose`: prints maxTurns and soft-limit drift against the model, nothing else
- **Env:**
  - `STACK_USAGE_COLLECT=0`: kill switch. Hooks do nothing; a running collector stops at the session's end.
  - `STACK_USAGE_REFRESH=0`: collect but never refit automatically.
  - `STACK_USAGE_IDLE_S` (default 7200)
  - `STACK_USAGE_POLL_S` (default 5)
  - `STACK_USAGE_MAX_BYTES` (default 8000000)
  - `STACK_SCHED_REFRESH_STEP` (default 1.5)
  - `STACK_SCHED_REFRESH_B` (bootstrap replicates, default 2000)
- **Optional:** a periodic refit outside sessions (cron or a launchd agent running `stack_usage.py refresh`) is possible but not installed; the stack ships none.

### Read gate (2026-10-03)

- **What:** `hooks/read_gate.py`, PreToolUse on `Read|Grep|Glob|Bash`. The first read of a gated target is refused (`permissionDecision: deny`) with a cheaper alternative; the identical call repeated by the same agent passes, so "only when strictly necessary" is the agent's explicit second call, not a ban. Bash is covered because Grep and Glob are absent by default on macOS and Linux: agents search with `grep` and `find` through Bash (https://code.claude.com/docs/en/tools-reference, "Glob tool behavior"). Permission rules can't do this: `deny`/`ask` win over a hook `allow`, a Read deny also blocks Edit, and `ask` prompts you.
- **Gated** (the lists live in the hook):

| Category | Targets | Exempt agents (stack.env knob) |
|---|---|---|
| build | `.next` `.nuxt` `.output` `.svelte-kit` `.astro` `.docusaurus` `_site` `htmlcov` `.nyc_output` `DerivedData` `.build` `dist-newstyle` `_build` `zig-out` `.stack-work` `resources/_gen` (Hugo), `.lake/build` only (`.lake/packages` holds Mathlib); `public` `dist` `build` `out` `target` `coverage` only when git ignores and does not track them, or `public/` beside a Hugo config (Vite's `public/` source folder stays readable); `*.min.js` `*.min.css` `*.map` | verifier, frontend-engineer, browser-operator (`READ_GATE_EXEMPT_BUILD`) |
| deps | `node_modules` `.venv` `venv` `.tox` `__pycache__` `.mypy_cache` `.pytest_cache` `.ruff_cache` `.gradle` `Pods` `.terraform` `.pixi` `.dart_tool` `.yarn/cache` and other caches; `vendor` when git-ignored; lockfiles over 64 KiB | none (`READ_GATE_EXEMPT_DEPS`) |
| data | weights and binary data (`.parquet` `.db` `.sqlite` `.duckdb` `.npy` `.pkl` `.pt` `.safetensors` `.onnx` `.gguf` `.bin` ...); text data (`.csv` `.tsv` `.jsonl` `.json` `.xml` `.log` `.sql`) over 256 KiB | data-engineer, data-scientist, db-engineer, ml-, dl-, llm-, mlx-engineer (`READ_GATE_EXEMPT_DATA`) |
| visual | video, audio, 3D and layered design files; images over 2 MiB | designer, motion-designer, image-director, cg-artist, doc-specialist (`READ_GATE_EXEMPT_VISUAL`) |
| binary | objects, libraries, archives, fonts, bytecode | none (`READ_GATE_EXEMPT_BINARY`) |

- **Never gated:** anything under `.claude-work/`; Read with `limit` <= 200; the Grep tool unless `output_mode: content` without `head_limit` <= 200; Bash readers whose output is cut or capped (`head`, `tail`, `wc`, `| head`, `| grep`, `grep -l/-c/-q`, non-recursive `grep` on a directory, `sed -n`, `> file`, `find -maxdepth` <= 2, plain `ls`); builds and tests (they don't go through these readers); Edit and Write.
- **Bash readers parsed:** `cat bat less more nl tac strings xxd hexdump od grep egrep fgrep ugrep rg ag ack find bfs fd tree ls -R sed awk jq`, per pipeline segment, with `cd` followed, heredoc bodies skipped, globs expanded and `$VAR` words skipped. `bash -c`, `$(...)` and `xargs` are not followed (a token gate, not a guard).
- **Retry state:** `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/<session_id>/read-gate.json`, keyed by agent, tool and input (Bash: the command, not its description), at most `READ_GATE_MAX_KEYS` (512) entries, oldest dropped, under `flock`; agent_guard's SessionStart deletes session folders idle for 3 days.
- **Fails open:** a bad event, an unparsable command, git failing or a state that can't be written lets the call pass (stderr note).
- **Knobs** (stack.env, read at each call; `/usr/bin/python3 ~/.claude/hooks/read_gate.py --print` shows the effective values): `READ_GATE` (0 = off; the environment variable works too), `READ_GATE_LIMIT`, `READ_GATE_DATA_BYTES`, `READ_GATE_LOCK_BYTES`, `READ_GATE_IMAGE_BYTES`, `READ_GATE_MAX_KEYS`, and the `READ_GATE_EXEMPT_*` lists above (a value replaces the list; `<type>-copy` counts as its base). To exempt another agent from build output: `READ_GATE_EXEMPT_BUILD=verifier,frontend-engineer,browser-operator,coder`.
- **Tests:** `/usr/bin/python3 dot-claude/hooks/read_gate.py --self-test`; `uv run --python 3.13 --with pytest pytest -q tests/test_read_gate.py`.

### Session model overrides (2026-10-03)

- **Commands** (user skill `skills/override-agent`, `disable-model-invocation: true`): `/override-agent <agent> <model>`, `/override-agent list`, `/override-agent reset <agent|all>`; a malformed subcommand (`list x`, `reset`, `reset a b`) is refused with the usage. `<agent>` is a stack agent with a definition file (not blackcat: `/model` changes the main thread); models are the Agent tool's `model` enum (`sonnet`, `opus`, `haiku`, `fable`). There is no effort argument: the effort comes from the built-in table, and a third argument is refused with the usage. Arguments are letters, digits, `-` and spaces only, at most 120 characters; anything else is refused and nothing changes. The earlier names `/agent-override`, `/agent-reset` and `/reset-agent` are gone (install.sh's default pruning removes their skills).
- **Mechanism:** `agent_guard.py override-agent` on UserPromptExpansion (matcher `override-agent`) parses `command_args`, writes `<state>/<session_id>/agent-overrides.json` (0600, atomic, read back with `O_NOFOLLOW | O_NONBLOCK` and `S_ISREG`, so a symlink or FIFO planted there is ignored instead of hanging the hook, and checked against the session id and the enums) and logs to `agent-overrides.log`. It always blocks the expansion: the block reason is the command's output (shown as "UserPromptExpansion operation blocked by hook:" followed by the change: agent, old → new model with its resolved ID, the table's effort and its source, scope this session) and no model turn runs. The PreToolUse(Agent) handler, after every gate (spawn policy, depth, fan-out leases, BlackCat limits, supreme-coder), strips a caller's `model` as before and sets `model` to the override for that `subagent_type` (a `<type>-copy` follows its base), in nested spawns too; the call gets a `systemMessage` and an `apply` log line. Without an override, nothing changes.
- **Only the user sets it:** the state is written only from a UserPromptExpansion event of the main thread (no `agent_id`) for a `slash_command` from `userSettings`. Claude Code fires that event when a slash command typed by the user expands; prompts it queues itself (cron and `/loop` wake-ups the model scheduled, SendMessage to the main thread, task notifications, auto-continuations) carry `skipSlashCommands` and never expand (Claude Code 2.1.287), and the Skill tool can't run a `disable-model-invocation` skill. UserPromptSubmit is not used, since a cron fire puts model-written text in its `prompt`. Agents can't write the state dir (sandbox `denyWrite`, the no-push hook's protected paths).
- **Scope:** keyed by session id. SessionStart `startup`, `resume` and `clear` delete it; `compact` keeps it. Limits are untouched: the snapshot, soft limits, turn and MCP caps and fan-out are keyed by agent type and fixed at session start.
- **No evidence for later sessions:** the collector records each segment's `model` (schema 3, above), and the learners skip an agent row whose model is set and does not contain its frontmatter `model`'s alias (`haiku`, `sonnet`, `opus`, `fable`; a `<type>-copy` uses its base's): `stack_limits.py` proposals (`turns`, `soft.agent`, `hard.agent` per type and pool, and `soft.prompt.<type>`, whose sample is the prompt windows that type ran in; `proposals.json` counts the skipped rows in `model_mismatch`), the scheduler refit and `stack budget`. Rows are not rewritten (append-only, provenance kept): the filter is at read time, after the last row per key has won. Kept as before: v1/v2 rows and an empty model (unknown); a type whose frontmatter `model` names no alias (`inherit`, which follows the parent: the row does not say the parent's model, and no stack agent uses it today); the prompt and session limits, which measure the whole tree's use whatever models ran in it (as after `/model`). The match is by the resolved ID: an alias that resolves to the agent's own family (the haiku slot pointed at a Sonnet model) still counts, and a custom ID without the alias name counts as another model.
- **Built-in effort table** (`hooks/agent_effort.json`, staged by install.sh beside the guard): one level per (agent, model alias) for every overridable agent. These are **initial defaults** from rule v1, to be re-derived from measured data by the Bayesian/Pareto limits jobs. Rule v1: base = the agent's frontmatter effort (its class level, as tuned on its own model: planner, ninja-coder and supreme-coder high to max; oracle, scout and explore low). The same or a stronger model (tiers haiku < sonnet < opus < fable) gets base. A weaker model than the agent's own (an opus agent on sonnet) gets one level up, at most xhigh: the rule never picks max. The haiku slot, the cheap and fast pick (this stack points it at Sonnet 5.5), gets one level down, at least low. At `/override-agent` time the level is clamped to what the resolved model accepts. The model ID comes from `ANTHROPIC_DEFAULT_<ALIAS>_MODEL`, else, for fable (no stack.env line), the table's record of Claude Code's own default. Clamping follows Claude Code 2.1.287's own checks: no xhigh on the 4.6 models (xhigh → high), no max or xhigh on Opus 4.5 and older, none at all on Haiku 4.5 and claude-3 (assumed; unverified). The resolved level and its source (`table`, or `table, xhigh clamped to high for …`) are stored with the override, so a table changed by a later install never alters an override already set in a running session. `list` shows agent, model, effort and source.
- **The effort is recorded and shown, NOT applied.** The Agent tool has no effort input (2.1.287: `description`, `prompt`, `subagent_type`, `model`, `run_in_background`, `name`, `team_name`, `mode`, `isolation`, `cwd`). A child's effort is its frontmatter `effort`, else the session's (`CLAUDE_CODE_EFFORT_LEVEL` beats both), and no hook output changes it. Applying it would need per-(agent, model) agent definition variants, which are not built (see the proposal in the 2026-10-03 changelog entry). The command says the effort is not applied and names the frontmatter effort that still runs.
- **Limits:** `CLAUDE_CODE_SUBAGENT_MODEL_FORCE` makes Claude Code drop per-call models, and the command warns when it is set. Workflow `agent()` stages are not rewritten: the guard refuses a `model` there.
- **Tests:** `uv run --python 3.13 --with pytest pytest -q tests/test_override_agent.py` (parser, table validity and rule, clamping, the rewrite, isolation, injection); `agent_guard.py --self-test` checks the table covers every agent and model.

### Permission modes (2026-10-03)

- **Default:** `permissions.defaultMode: "plan"` in the user `settings.json` (was `bypassPermissions`). User scope accepts every mode; project and local settings ignore `auto` and `bypassPermissions` there; `claude --permission-mode` beats the settings file; Claude Code's own terminal default is `auto` (2.1.283+), so the setting matters. A once-only prompt may offer Pro/Max/Team users a switch to `auto`; declining keeps Plan. No project or managed settings file sets the mode, and only the launchers pass the flag (below).
- **Inheritance** (sub-agents.md, permission-modes.md, as reported by claude-code-guide, 2026-10-03): an agent without `permissionMode` inherits the main conversation's mode. A parent in `bypassPermissions`, `acceptEdits` or `auto` wins over the agent file; a parent in `plan`, `default` or `dontAsk` loses to it (`bypassPermissions` in a file excepted). A subagent in plan is read-only, and ExitPlanMode is removed from subagents not in plan. Approving a plan switches the session's mode, and new subagents inherit the new one.
- **The stack's agents:** 45 carry `permissionMode: acceptEdits`, every agent with Write, Edit or NotebookEdit except BlackCat, so their subagent runs never stop at an edit prompt (the user: subagents must not bloat their context or wait on prompts). The other 11 carry none: blackcat (the main thread follows the session's mode) and the read-only claude-code-guide, code-reviewer, explore, oracle, plan-reviewer, planner, proof-checker, scout, security-auditor and verifier. `tests/lint_agents.py` (`permission_mode_problem`) allows `acceptEdits` only on agents that write files and `plan` only on read-only ones; `default`, `auto`, `dontAsk` and `bypassPermissions` fail. Consequence: a switch to Plan or Default does not make a dispatched builder read-only. BlackCat's rule 5 sends builders only after the plan is approved; that is a prompt rule. A guard check that would make Plan bind builders waits for the probe below.
- **Main thread:** `bin/claude-ultracode` (claude-ninja, claude-supreme, `claude-ultracode <agent>`) adds `--permission-mode plan` unless the arguments already hold `--permission-mode[=…]` or `--dangerously-skip-permissions` (scanned up to `--`). Whether Claude Code applies a main-thread agent's `permissionMode` is not documented, so a builder started by hand (`claude --agent main-coder`) may start in `acceptEdits`; the probe's last step checks it.
- **Headless:** with `claude -p`, scheduled or background jobs under Plan, the main thread's edits are never auto-approved, and a call that would ask is denied when no host answers. A script whose main thread must edit passes `--permission-mode acceptEdits`. Making such runs wait for an approval is queued, not built.
- **MCP tools:** in `plan`, `default` and `acceptEdits` an MCP tool with no allow rule prompts, in subagents too (acceptEdits approves edits only). `permissions.allow` names 19 servers whole (`mcp__<server>`, the docs' form for every tool of a server): exa, jina, libdocs, wolfram, huggingface, wandb, spider, image-studio, huetension, markitdown, illustrator, after-effects, premiere, blender, computer-use, lean, mobilebuild, playwright, neural-memory. `mongodb`, `postgres` and `claude-in-chrome` have no rule, so they prompt and are denied headless; magg and context-mode are ruled tool by tool. Deny, then ask, then allow: the first match wins, so a user's ask or deny rule on an allowed server keeps it prompting or blocked. `tests/test_permission_modes.py` pins the set and fails on a new agent MCP server without a decision.
- **Not verified** (the docs are silent): whether a running subagent follows a later mode switch; inheritance through nested spawns, `isolation: worktree`, forks and workflow agents; whether subagent hook events carry `permission_mode`; whether plan approval counts as a new prompt for `BLACKCAT_MAX_STEPS`. The Agent tool's own `mode` input is "Deprecated; ignored" in the 2.1.287 schema (security-auditor, from the local bundle); the guard strips it anyway, so no caller picks its child's mode should a later version honour it.

**The probe** (`STACK_MODE_PROBE=1`; no agent can run it, because it needs your interactive session and Shift+Tab). The log is `~/.local/state/claude-agent-stack/mode-probe.jsonl` (under `$XDG_STATE_HOME` if set). The variable must be in the environment of the `claude` process, so export it in that terminal; settings.json does not set it.

1. `export STACK_MODE_PROBE=1; claude` in a scratch project. Do not pass `--permission-mode`. The footer shows plan mode.
2. Ask: `@planner list the files in this folder` (read-only, no mode), then `@coder run git status and report it` (acceptEdits), then `@orchestrator have explore list the files here` (explore nested under an acceptEdits parent).
3. While a longer agent runs (for example `@verifier run the test suite`), press Shift+Tab until the footer shows another mode (say, accept edits), then ask `@planner list the files again`.
4. Main thread: quit, then `STACK_MODE_PROBE=1 claude --agent ninja-coder` (no flag; ask one read-only question, then quit), then `STACK_MODE_PROBE=1 claude-ninja` (the launcher).
5. Read the log, then delete it and unset the variable:

```bash
L="${XDG_STATE_HOME:-$HOME/.local/state}/claude-agent-stack/mode-probe.jsonl"
jq -r '[.time, .event, (.agent_type // "main"), (.depth|tostring), (.tool // "-"), (.permission_mode // "absent")] | @tsv' "$L"
jq -s 'group_by(.session) | map({session: .[0].session, by_agent: (group_by(.agent_type // "main") | map({agent: (.[0].agent_type // "main"), modes: (map(.permission_mode // "absent") | unique)}))})' "$L"
rm -f "$L"; unset STACK_MODE_PROBE
```

What the outcome means:

| Observation | Meaning | Then |
|---|---|---|
| Subagent lines (depth ≥ 1) never have `permission_mode` | the field is not on subagent events | the enforcement follow-up cannot use it; keep rule 5 as the only brake |
| planner shows `plan` in step 2 and the new mode in step 3 | new read-only subagents inherit the session's mode, as documented | nothing |
| coder shows `acceptEdits` while the session is in plan | the agent file wins over a Plan parent, as documented | nothing; this is why rule 5 matters |
| explore under orchestrator shows `plan` / `acceptEdits` | nested agents inherit the main thread's / their parent's mode | record it in NEXT_STEPS |
| the long-running verifier's lines change mode after the switch / do not | running subagents follow a switch / keep their start mode | record it; README "Permission modes" |
| `claude --agent ninja-coder` starts with `plan` | the frontmatter is not applied to a main thread | nothing |
| `claude --agent ninja-coder` starts with `acceptEdits`, `claude-ninja` with `plan` | the frontmatter is applied to a main thread; the flag beats it | use the launchers (or pass the flag) for builders as main thread |
| `claude-ninja` also starts with `acceptEdits` | the flag does not beat the frontmatter | remove `permissionMode` from the builders and give subagent runs their edits another way (a guard PreToolUse `allow` for Write/Edit in builder subagents, which never overrides a deny rule) |

### Message protocol (2026-10-03)

Phase 1 of the hand-back protocol is behaviour-neutral: in the default mode `observe` the hooks measure and record, and never change a prompt, a reply or a decision. The reply format, the compact default and the read gate are Phase 2 and planned, not shipped. Code: `dot-claude/hooks/stack_report.py` (module docstring), `agent_guard.py` (SubagentStop, PreToolUse(Agent)).

| `STACK_REPORT_FORMAT` | SubagentStop | PreToolUse(Agent) and prompt |
|---|---|---|
| `observe` (default) | checks and records every spawned stack subagent's final reply; never outputs, warns or blocks | records the brief's size and pasted content in the ledger; prompt unchanged |
| `compact` | the same, plus ONE restate per run (`decision: block`, reason <= 400 chars) on a hard violation | the same, plus a warning (additionalContext) for a brief over 2,000 agent-written chars (a `USER:` block is exempt) or with a pasted report or blob. Not the default: planned for Phase 2, after the caps are calibrated (plan step S5b) |
| `json` | today's JSON report line (now with `failed` and `eflag`) plus a shape check, logged, never blocks | SessionStart and SubagentStart add the JSON-line request |
| `off` | no check, no log | nothing recorded |

- **Who is checked:** an agent_type in the stack's spawnable types (never `blackcat`: Claude Code runs prompt suggestions and `/btw` as the session's agent) that was spawned by an Agent call the guard allowed (registry `spawned`; for a foreground child still in its call, Claude Code's `meta.json` naming an Agent call in the ledger). `meta.json` is undocumented, so such a child may go unchecked. Skipped: an empty reply, and a run whose transcript's last tool_use is `SubagentHandback` (logged with format `handback`).
- **Grammar** (written by the model, the existing STATUS prefix): `STATUS: done|partial|failed|blocked [· E:look|E:drop]`, `RESULT:`, `FILES:` (one `path — purpose` per line, purpose `deleted` allowed; the older comma list still parses), `EVIDENCE:` (at most 5 lines, or `→ path[:a-b]`), `NEXT:`.
- **Wrapped replies:** a reply wrapped whole in one code fence (the first non-empty line opens a ``` or ~~~ fence with the STATUS line inside) is unwrapped before the STATUS and blob checks (8 of the 80 frozen hand-backs were wrapped so: markup, not content). `wrapped` is recorded; the size still counts the reply as sent.
- **Hard violations** (compact only can restate): no or invalid STATUS; a non-done report without EVIDENCE or NEXT; a blob (10+ Read-output lines, a code fence over 15 lines or 1,500 chars, a base64 or hex run of 200+, control characters, a line over 2,000 chars); a size above 1.5x the class cap. **Soft** (logged only): size within 1.5x, an implied E flag, `suspect` (done, no E flag, RESULT says skipped, unverified or not run), missing files (`missing: [...]`, never a block). In the review and plan classes blob and size are soft too.
- **Caps** (chars, FILES lines excluded; PROVISIONAL, enforced only in compact until the S5b calibration):

  | class | types | cap |
  |---|---|---|
  | lookup | oracle, scout, explore, claude-code-guide | 1,000 |
  | builder | every other type | 800 done, 2,500 otherwise |
  | coord | orchestrator | 2,500 |
  | review | code-reviewer, plan-reviewer, security-auditor, verifier, proof-checker | 6,000 soft |
  | plan | planner | 12,000 soft |

  On the 80 frozen pre-protocol hand-backs (builder 65, lookup 8, review 6, plan 1, coord 0), 70/80 would be restated at 1.0x and 60/80 at 1.5x; the measured p90 of rewritten compliant builder reports is 3,100 chars done (n=29) and 3,200 otherwise (n=19) (the counterfactual on the frozen baseline, 2026-10-03; local-only, not linked).
- **Restate once:** the check-and-set of `restate_key` (the run's registry `started` stamp) runs under one registry lock (`reg_update`); `stop_hook_active` true never blocks; a blocked agent is not marked stopped (it keeps its locks and fan-out slot) until its next SubagentStop. Unverified: whether a child that hits maxTurns while restating fires another SubagentStop (otherwise it counts as running for the per-parent fan-out until `STACK_FANOUT_IDLE_S`, and a background child keeps its session slot (K_sess) until TaskStop, StopFailure or the next SessionStart).
- **Fail open:** any error warns on stderr, marks the agent stopped and outputs no decision; a record that cannot be written never cancels a decision.
- **Rollback:** `STACK_REPORT_FORMAT=off` in `stack.env` or the environment. `agent_guard.py --self-test` now runs `report_self_test`.

**Where it is recorded** (no report text outside the first two):

- Registry `agents/<id>.json` gains `report`: run, stops, status, eflag, format, class, cap, chars, counted, hard, soft, blob, verdict, counts, mode, restated, blocked, restate_key, path, `files` (`[{path, state, size, mtime, sha8}]`) and missing.
- `reports/<agent_id>.<int(started)>.<n>.md` in the session's state folder: the full reply copy (n=1 first, 2 restated), created O_EXCL, mode 0600 in a 0700 folder, cut at 2 MiB, pruned with the session folder.
- `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/usage/reports.jsonl`, beside `runs3.csv`: one JSON line per check, no report text; it rotates to `reports.jsonl.1` past 16 MiB. A `handback` row has only the common fields.

  | field | meaning |
  |---|---|
  | `v` | schema version, 1 |
  | `ts` | time of the check |
  | `session` | session id |
  | `agent_id` | the agent's id |
  | `run` | the registry `started` stamp as a string; a restate's rows share session, agent_id and run, and the last row of a run is the final report |
  | `type`, `class`, `mode` | agent type, size class, `STACK_REPORT_FORMAT` mode |
  | `format` | `status`, `clean`, `text`, `json` or `handback` |
  | `wrapped` | the reply came in one code fence |
  | `status`, `status_raw` | the parsed STATUS word (done, partial, failed, blocked or null); the first word when it is not one of those |
  | `eflag` | `look`, `drop` or none |
  | `restated`, `blocked`, `stop_hook_active` | restate state of this row |
  | `n` | copy index (1 first, 2 restated) |
  | `report_chars` | reply length as sent |
  | `counted_chars` | length with FILES lines excluded |
  | `report_tokens_est` | `ceil(report_chars/3)` |
  | `brief_chars`, `brief_tokens_est` | the brief's size, same estimate |
  | `est` | the label "ceil(chars/3): an estimate, not a token count" |
  | `hard`, `soft` | violations found |
  | `blob` | the blob checks that hit, by name |
  | `verdict`, `counts` | a review's `VERDICT` (pass, pass-with-fixes, fail) and its severity counts (CRITICAL, HIGH, MEDIUM, LOW, BLOCKING) |
  | `files` | number of FILES paths |
  | `missing` | number of missing files; null when not computed (on a block) |

- Ledger `spawns/<tid>.json` gains `brief_chars`, `brief_user_chars`, `brief_blob`, `brief_pasted`, and from PostToolUse(Agent) `duration_ms`, `tool_uses`, `total_tokens`. The last three exist for foreground calls only (absent for background children, i.e. every child of an interactive fork-mode session) and are measurement only: no metric uses them.
- `delegations.md` rows of finished agents gain `report <status> [E:look|E:drop] · <copy path>`.

**File metadata safety.** FILES paths are model text and command hooks run outside the sandbox, so a path is looked at only when its realpath is inside the event cwd, `$CLAUDE_PROJECT_DIR` or the main checkout's `.claude-work/` (the checkout's realpath joined with `.claude-work`: a `.claude-work` symlink never moves the root; a root that is `/`, the home folder or one of its ancestors does not count; credential paths such as `.ssh`, `.aws`, `.gnupg`, `.env*`, `stack.env`, `.config/git/credentials`, `.cache/huggingface/token`, `~/.claude/ide/` and the stack's backups never do, matched case-insensitively). Anything else is recorded `outside` with no stat. The file is opened `O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_NOCTTY`, the descriptor's own path is re-checked (`F_GETPATH` on macOS), then `fstat` must say S_ISREG. States: ok, missing, deleted, outside, not_regular, symlink, error. `sha8` is the first 8 hex of the SHA-256 for files up to 8 MiB that are not iCloud placeholders, hashed in a daemon thread joined for at most 2 s (else `hash: timeout`). At most 20 paths; the metadata runs after the restate decision and never decides one (not computed on a block).

**Readers.** `stack-tree`: the registry `report` status and E flag win over the transcript scan, `failed` is accepted, `--pending` is new (above). `stack_usage.py`: `STATUS: failed` maps to status_code 1 like partial; the domain {0, 1, 2} and the learned limits are unchanged. `stack_sdk.parse_report`: new key `eflag`, `failed` status (exit code 1 like partial and blocked), FILES `path — purpose` lines and dash bullets give paths only.

## 6. Recommended session settings

- **Claude Desktop, Conductor and other SDK apps:** set effort to **medium** for the main thread; the agent files set each subagent's effort. Start a new session after installing.
- **Terminal:** `claude` (BlackCat) at the session's effort, `/effort medium`. For the hardest problems:
  - `claude-ninja` and `claude-supreme` run ninja-coder and supreme-coder as the main thread at `ultracode`, in Plan: the launcher passes `--permission-mode plan` unless you pass a mode yourself ("Permission modes" above).
  - Dispatched as subagents, both run at `max`.
- **Not verified:**
  - whether AskUserQuestion is offered to the main thread in Claude Desktop (it goes through the host's `canUseTool`); BlackCat falls back to plain-text questions;
  - Desktop behavior after the fix. It is inferred from transcripts and the hook tests, not from a live Desktop run.

## 7. Installer, backups and hardening

### How an install runs

1. The stack's part of the config dir (`agents/`, `skills/` without `synced/`, `rules/`, `hooks/`, `bin/`, `mcp/` without `vendor/`, `stack-plugins/`, `magg/config.json`, `settings.json`, `stack.env`, `.stack-manifest.json`, `CLAUDE.md`, temp leftovers) is copied to a staging dir inside the backup root (so the staged `stack.env` is as private as the backups), with a snapshot of what was copied. A top-level scope dir that is a symlink (a dotfiles `skills/` or `agents/`) is yours: nothing under it is ever removed, and the run stops unless `--write-through-links` lets it write the stack's files through the link. `--dry-run` without that flag shows the whole plan, then prints the real run's refusal ("the real run would stop: ...") and exits 1, as the real run does; with it, it exits 0. `--force` doesn't lift that stop, so `--no-prune --write-through-links` keeps your edits to stack files there (each gets a `.new` render). A symlink one level down in a real dir (`skills/<name>` pointing into a dotfiles checkout) is replaced by the stack's copy of that skill; the backup keeps the link and its target is never written. Inside a symlinked scope dir, a link stays, whether a dir link (`skills/<name>`: the stack's files for that name are skipped) or a file link (`agents/coder.md`); each is named in the notes ("kept (a link inside your symlinked agents/)"), and its target is never written.
2. Render, settings merge and pruning run there. The staged result is validated before anything changes: JSON, agent and skill frontmatter, placeholders, and the staged `agent_guard.py --self-test`. Validation is fatal only for files the stack owns (their sha256 matches the manifest).
3. The plan is printed: `changes: N added, N updated, N removed`, then `replaced:` (stack files that differed) and `removed: not part of the stack`, each with a reason.
4. `--dry-run` stops here; MCP, plugin and rc changes are printed as `would: ...`. A real run saves every file it changes or removes into one backup, records the files it adds, then applies. A run that changes nothing makes no backup.
5. Nothing is applied if the config dir changed after staging (Claude Code saving `settings.json`, an editor): the plan and the apply both compare it with the snapshot, the second time right before the first change. Plan paths that are not scope paths, or that resolve out of the config dir, are refused (by the plan step too, so `--dry-run` reports what the real run would refuse); a path below a symlink the plan removes first is resolved as the directory that replaces it.
6. Every path in `.stack-manifest.json` must be a file path in the scope (no `..`, no absolute path, not a whole scope dir such as `bin` or `mcp`): one that isn't stops the install before anything changes, and the staged copy must hold all the stack's scripts. The manifest also records the stack commit each install shipped; the next run prints, at its start, the diffstat of everything it ships since then (all of `dot-claude/`: agents with their MCP servers and hooks, skills, rules, hooks, settings, `bin/`, `mcp/`, magg's catalog, the LSP marketplace; plus `install.sh`, `lib/install_state.py`, `lib/stack.env.example`, `requirements/`, the two `tests/derive_*.py` scripts copied into `hooks/`; not `lib/assets/`) and any uncommitted edits there, capped at 40 lines with the `git diff` command to read it all; an unknown recorded commit gets a warning. When that list isn't empty, the run asks before step 2 changes anything (the venvs sync from `requirements/` there): `The stack changed since the last install (listed above). Install it? (see the whole plan first: ./install.sh --dry-run) [y/N]`; anything but y/yes stops with exit 1 and nothing changed. It asks on stdin/stderr when both are a terminal, otherwise on the controlling terminal (`/dev/tty`: `./install.sh 2>&1 | tee install.log` still asks there). With no terminal at all (CI, cron, `</dev/null` without a terminal), a changed stack stops with exit 1: "… there is no terminal to ask: rerun with --yes to install it (--dry-run shows the whole plan)", nothing changed (R4-1). `--yes` (`-y`) installs without asking and is needed without a terminal; `--dry-run` never asks.

`lib/install_state.py` does the staging, plan, backup, apply, restore and validation (system `python3`, stdlib only).

### Hook interpreter: `stack-python` and the launcher (2026-10-04)

- **Command shape.** Every Python hook in `settings.json` (and blackcat.md's) runs `/bin/sh "<config>/bin/stack-hook" [--fail-closed] <module> [args]`, modules `agent_guard`, `stack_usage`, `read_gate`, `web_caps`. `bin/stack-hook` (POSIX sh) finds the interpreter without starting a Python: `$STACK_PYTHON`, `${CLAUDE_CONFIG_DIR:-~/.claude}/bin/stack-python`, the `stack-python` beside the launcher, then `uv python find --system --managed-python --no-project --no-config 3.13` (never a project's `.venv`, `VIRTUAL_ENV` or `uv.toml`), and execs `hooks/stack_hook.py`, which imports the module so its bytecode in `hooks/__pycache__` is reused. The status line and `/stack-tree`'s hook run `"<config>/bin/stack-python" ...` directly.
- **`bin/stack-python`** is a symlink to uv's managed Python 3.13 (uv's minor-version link, so a patch upgrade keeps it valid). The hook code's floor is 3.13; Apple's `/usr/bin/python3` is no longer used by any hook. The installer makes the link (step 2 runs `uv python install 3.13` only when no 3.13 is found; not under `--no-deps` or `STACK_INSTALL_UV=0`; `--dry-run` prints it as `would:`). `STACK_PYTHON` exported when you run `./install.sh` names another interpreter for the link; it must be Python >= 3.13, or the run stops before changing anything. Exported in a session's environment it wins over the link (`/stack-doctor` FAILs it when it is older than 3.13). `bin/stack-update-tools` runs `uv python upgrade 3.13`, re-points the link at uv's 3.13 (a non-uv target, your choice, stays) and recompiles.
- **Order in the installer.** After step 6 (render) and before step 7 writes `settings.json`, the run links `bin/stack-python` (atomically) and smoke-tests the staged launcher, stub and guard on it: a PreToolUse Read through `--fail-closed agent_guard budget` must be allowed and a `git push` through `--fail-closed agent_guard no-push` denied. No Python 3.13, or a failed smoke test, stops the run there with the previous link restored: the hooks you had keep running, nothing else in the config dir changes, and the message names the fix (`uv python install 3.13`, or `STACK_PYTHON=/path/to/python3.13+`, then `./install.sh`). After apply the hook modules are compiled with `stack-python -m compileall -f --invalidation-mode timestamp` (a source whose mtime or size differs from what its pyc records is recompiled on import; bytecode stays in the protected `hooks/__pycache__`; `install_state.py` never backs up, compares or prunes `__pycache__` or `bin/stack-python`).
- **Fail closed, PreToolUse only.** `--fail-closed` is on the guard's PreToolUse entries (main, `no-push`, `image-limit`, `budget`, `blackcat-guard`); `read_gate` and `web_caps` stay fail-open by design, and no other event carries it (exit 2 on Stop, UserPromptSubmit or PermissionRequest has side effects). When the hook cannot start (no interpreter, no stub, an import error, an interpreter older than 3.13) a fail-closed entry denies the tool call (the launcher exits 2, the stub prints the guard's own deny) with a message naming `./install.sh`; the other entries exit 0 and write the reason to stderr. **Recovery:** run `./install.sh` from the stack repo (it repairs the link and the bytecode; `/stack-doctor` shows which part failed). `"STACK_POLICY": "off"` in settings.json's env lets the fail-closed entries through while the hook cannot start, except `agent_guard no-push`, which is never lifted: in that doubly degraded state Bash stays blocked until `./install.sh` has repaired the hooks.
- **Without uv or Python 3.13.** The installer stops before step 7 (above); an install that later loses its 3.13 (a dangling link after removing uv's Pythons) falls back to `uv python find 3.13` per call and, with none, blocks tool calls on the fail-closed entries until `./install.sh` runs again.
- **CLI tools outside the hooks.** `bin/stack-tree` and `bin/stack-budget` keep their `/usr/bin/python3` shebangs and stay Python 3.9-compatible: they are run by you (or `/stack-tree`'s hook through `stack-python`), not as hooks. `bin/mcp-headers` stays Python because the installer loads its parser under the bootstrap `python3`; its headersHelper entry names `stack-python`.
- **Doctor.** `/stack-doctor` checks that `bin/stack-python` resolves to Python >= 3.13, that the launcher and stub exist, that the guard's and the hook modules' timestamp pycs are fresh, and runs the launcher smoke test (a Read through the fail-closed budget entry is allowed).

### Install target (2026-10-03)

| Knob | Default | Effect |
|---|---|---|
| `--config-dir PATH` / `--config-dir=PATH` | not given | install target; beats `CLAUDE_CONFIG_DIR`; `~` and relative paths expanded, symlinks resolved and shown |
| `CLAUDE_CONFIG_DIR` | unset | install target when the flag is not given |
| (neither) | `~/.claude` | the default target |
| `--no-prompt` | off | never ask: the target question is skipped (a foreign target stops the run), a changed stack stops unless `--yes` |
| `--yes` / `-y` | off | no target question and no changed-stack question (a foreign target still stops the run) |
| `STACK_CLAUDE_JSON` | `<target>/.claude.json` when `CLAUDE_CONFIG_DIR` is effectively set, else `~/.claude.json` | the `.claude.json` the banner names and the MCP plan reads |

`lib/install_state.py config-dir` resolves and checks the target, and the run refuses or asks, before the main-branch rule can fast-forward `main` or switch the checkout (a yes carries over to the re-run from the main checkout through `STACK_TARGET_CONFIRMED`, honoured only with `STACK_MAIN_REEXEC=1` and the same target) (`resolve_config_dir`, `check_config_dir`, `decide_prompt`; `tests/test_installer_config_dir.py`, `tests/install_smoke.sh` §19). Rules:

- **Refused, exit 2, nothing changed:** `/`; `$HOME` or any folder containing it; the repo checkout and anything inside it (this checkout and the main worktree, logical and resolved paths, so a symlink into the repo is caught); inside `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`, `~/.docker`, `~/Library/Keychains`, `/System`, `/usr`, `/bin`, `/sbin`, `/etc`, `/private/etc`, `/dev`, `/Library`, `/Applications`, or the stack's state, backup and cache folders; exactly `~/.config`, `~/.local`, `~/.local/bin`, `~/.cache`, `~/Library`, `~/Desktop`, `~/Documents`, `~/Downloads`, `~/Applications`, `/Users`, `/Volumes`, `/private`, `/var`, `/tmp`, `/private/tmp`, `/private/var`, `/opt`; an existing non-directory; a directory you can't write, or a missing one whose nearest existing parent you can't write; a `..` after a symlink (the shell and the file system would disagree on the folder); a control character (newline, NUL, tab) or `"` `` ` `` `$` `\`, which would break the double-quoted hook commands in `settings.json`.
- **Same path:** two paths are the same when they are equal as strings or, for existing entries, by inode (`os.path.samefile`), so a different letter case on case-insensitive APFS (`~/.SSH`, `/USERS/<you>`, the repo in other case) is caught; "inside" walks the target's existing ancestors the same way.
- **Foreign target:** a `--config-dir` target other than `~/.claude` that is a non-empty directory (`.DS_Store` ignored) with none of `.stack-manifest.json`, `settings.json`, `settings.local.json`, `.claude.json`, `.credentials.json`, `CLAUDE.md`, `stack.env`, `agents/`, `skills/`, `rules/`, `hooks/`, `commands/`, `output-styles/`, `projects/`, `plugins/`, `statsig/`, `todos/`, `shell-snapshots/`. Installed into only after `y` on a terminal; without one, or with `--yes`/`--no-prompt`, exit 2; `--dry-run`, `--mcp-plan` and `--print-managed-settings` warn and go on. `~/.claude` itself is never foreign (a fresh Claude Code may have left anything there). A foreign folder named by `CLAUDE_CONFIG_DIR` is only warned about (and is a reason in the question on a terminal): that variable is what Claude Code itself reads and what scripted runs set, and such runs (`tests/install_smoke.sh` writes its log into the target before installing) worked before; refusing them non-interactively would break them.
- **Question** (`Install into <target>? [y/N]`, default No; y, Y or yes go on, anything else, EOF included, exits 1 before anything changes): only when stdin and stdout are both terminals and none of `--dry-run`, `--mcp-plan`, `--print-managed-settings`, `--yes`, `--no-prompt` is given, and the target is non-default or ambiguous: `--config-dir` other than `~/.claude`, `CLAUDE_CONFIG_DIR` set, `--config-dir` with a `CLAUDE_CONFIG_DIR` naming another folder, `~/.claude` and the target holding differing stack manifests (repo or commit), or a foreign target. It shows the target, its source, why it asks and what the run writes. Runs without a terminal proceed with the banner, as before.
- **Banner** (every run, after the main-branch rule): the target, the source, the resolved path when a symlink is involved, the `.claude.json` it implies, whether this run sets or unsets `CLAUDE_CONFIG_DIR` for its `claude` commands, an overridden `CLAUDE_CONFIG_DIR`, another stack install in `~/.claude`. For a non-default target it adds, and repeats after the install: the `export CLAUDE_CONFIG_DIR='<target>'` line, the startup file for the login shell (zsh `~/.zshrc`, `~/.zprofile` for login shells only; bash `~/.bash_profile`), that apps opened from the Dock do not read it, and that the absolute paths in `settings.json`, the hooks and the MCP entries mean moving the folder takes a reinstall.
- **Environment of the run:** `--config-dir` naming another folder exports `CLAUDE_CONFIG_DIR=<target>` for the run, so `claude mcp` and `claude plugin` act on the target's `.claude.json`; `--config-dir ~/.claude` unsets an inherited `CLAUDE_CONFIG_DIR`, unless it names the same folder.

### Pruning (default) and `--no-prune`

| What | Default | `--no-prune` |
|---|---|---|
| `agents/`, `skills/` (stack-owned) | files of other origins, renamed agents (`senior-coder` → `main-coder`, `router` → `blackcat`), stale renders removed; edited stack files replaced | kept, listed as notes; an edited stack file keeps your version and gets `<file>.new` (`--force` replaces it; `--write-through-links` doesn't) |
| `hooks/`, `bin/`, `mcp/`, `rules/` | stack files it no longer ships (manifest or a legacy list) removed; your own files stay | kept |
| magg catalog | edited stack entries replaced, entries it no longer ships removed; your servers stay | kept |
| MCP (user scope) | entries it registered and no longer ships (and Context7) removed via `claude mcp remove`, recorded in the backup | kept |
| `settings.json` | duplicate hooks and permission rules, old guard hooks (any path) and hooks on events it no longer wires removed, each hook entry listed; your own hooks sharing a group with the guard stay; sandbox merged (stack scalars win, lists unioned) | the same |
| temp leftovers, `.new` of files back in sync | removed | removed |

The manifest (`.stack-manifest.json`) lists every stack file as relpath + sha256. On a first run without a manifest, a same-named file that differs from the stack's counts as stale: it is backed up and replaced. **A first install over an existing `~/.claude` therefore moves your own agents and skills into the backup: run `./install.sh --dry-run` first.**

### Repo vs install: `--diff` (2026-10-04)

`./install.sh --diff [--config-dir PATH]` runs `lib/stack_diff.py` (`python3 -B`) right after option parsing, before the main-branch rule, the target checks and the backup root: it works from any branch or worktree, asks nothing, and writes nothing (no temp file, no bytecode, `GIT_OPTIONAL_LOCKS=0` for its one `git rev-parse`). Target: `--config-dir` > `CLAUDE_CONFIG_DIR` > `~/.claude`, resolved as install.sh resolves it (`install_state.choose_config_dir`/`expand_path`: lexical, so a symlinked `~/.claude` keeps the name `__CLAUDE_DIR__` renders) but without the install's safety checks. Any other option with `--diff`, an empty `--config-dir=`, or a target that is a file, is a usage error (exit 2); otherwise it exits 0, differences or not (a missing target prints "nothing installed"; an area that cannot be compared becomes a `note:` line).
- **Compared:** `agents/` (with the rendered `coder-copy.md`/`researcher-copy.md`), `rules/`, `skills/` (`synced/` aside), the `hooks/`, `bin/`, `mcp/` (`vendor/` aside) and `magg/` files install.sh stages (read from its `stage_script` lines, including the two `tests/derive_*.py` copies), `stack-plugins/`, the hook wiring of `settings.json` as (event, matcher, command) triples, and magg's catalog entries minus `enabled`/`kits`. Not compared: the rest of `settings.json` (merged with yours), `stack.env`, `CLAUDE.md`, MCP registrations.
- **Rendering:** text is compared with the installer's render: `__CLAUDE_DIR__`, `__HOME__`, `__STACK_REPO__` and the `__STACK_*__` dirs are filled in, the tool paths found at install time (`__PYTHON3__`, `__UV__`, `__UVX__`, `__NPX__`, `__NODE__`, `__MAGG__`, `__HUETENSION__`) match any path, the same one throughout a file; agents also pass through install.sh's own `make_copy`, `drop_servers` and `mcp_cache_env`, executed from install.sh's source (if they can't be read, a note says the agents were compared without them). A fresh install therefore diffs clean.
- **Output:** one block per area (`in sync` or counts), one line per path: `+ repo only` (the next install adds it), `- installed only` (stale stack files are pruned by the next install unless `--no-prune`; your own files are pruned too in `agents/` and `skills/`, elsewhere they stay), `~ differs` with `+a -r lines to install` (text; `edited since the last install` when the file no longer matches its manifest hash) or the two sizes (verbatim copies), `? unreadable`. Repo files install.sh doesn't stage are listed as notes; a summary line ends it.
- **Agents** can't run `./install.sh --diff` (the guard allows `--help`, `--dry-run`, `--print-managed-settings` and scratch installs); `python3 -B lib/stack_diff.py --repo <checkout>` is the same comparison.
- **Tests:** `tests/test_install_diff.py`: a real scratch install (fresh HOME, fake `claude`) diffs clean except the `--no-plugins` marketplace; eleven seeded drifts on both sides each appear; HOME and the repo are fingerprinted before and after; usage errors; the `stage_script` parse and the extracted installer code.

### Backups and `--restore`

- Location: `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/<timestamp>-<random>/`. The folder is 0700, files are 0600, and `backup.json` holds the entries, added files, removed or replaced MCP entries, disabled plugins and rc copies.
- The backups sit beside the guard's state dir, not inside it (the guard deletes state folders idle for three days).
- Agents can't reach them: `Read`/`Edit` deny rules, sandbox `denyRead`/`denyWrite` and a guard protected path.
- Backups that earlier versions kept inside the config dir (`backup-*`, with copies of `stack.env`) are moved to `<backups>/legacy/` on every run.
- `./install.sh --restore [DIR]` (default: the latest install backup) puts back files, rc files, MCP entries and plugins. It works as a staged plan, backs up the current state first and prints `undo this restore: ...`. `--restore --dry-run` only prints the plan.
- A `backup.json` naming paths outside the config scope is refused. rc restores are limited to `~/.zshrc` and `~/.bashrc`.
- More than ten backups of one config dir: the run says so; it never deletes one.
- The backup root must be a real directory of yours: a symlink, a file or another user's directory there stops the run (checked with `O_NOFOLLOW`, then set to 0700). Backup files are created `O_EXCL|O_NOFOLLOW`. The run's work dir (`.work.*`) lives inside the root and is removed on exit; a `--dry-run`, `--mcp-plan` or `--print-managed-settings` that had to create the root removes it again.
- A saved symlink whose target leaves the config dir is restored only with `--restore DIR --force`; without it, what is at that path now stays (the stack's version and the files the install added below it included, so a skill no longer goes missing), and the run names the link and the `ln -s` that recreates it.

### Plugins

One copy of each skill is the default. A plugin that duplicates a claude.ai-synced skill (document-skills, skill-creator) is disabled, and so is `mcp-server-dev@claude-plugins-official` (the stack's `mcp-server-craft` covers it). Each disable prints `To undo: claude plugin enable ...` and is recorded for `--restore`; `--keep-plugin-duplicates` keeps both. `math-olympiad` (with `--with-extra-plugins`) and the built-in `dataviz` skill stay.

### Supply chain (C7)

- uv: the astral.sh installer, else the 0.12.20 release tarball checked by sha256; the prerequisites and toolchains: "Prerequisites and toolchains" below (`lib/devtools.sh`).
- magg 1.2.1: `uv tool install --exclude-newer 2026-09-22T00:00:00Z`.
- huetension v0.3.0: tarball checked by sha256 (`go install ...@v0.3.0` as fallback).
- serial-mcp 0.9.3 (magg catalog `serial`): `cargo install serial-mcp@0.9.3 --locked --root ~/.cargo` (the crate's own `Cargo.lock`; crates.io checks the crate's checksum), only when cargo is present: Rust is never installed, and without cargo the step prints one line and doctor.sh WARNs with the command. The pin lives in the catalog entry's notes; install.sh reads it from there and skips the build when `~/.cargo/.crates2.json` already records that version (or the binary exists without a cargo record).
- sci/ml/tools venvs: `requirements/*.txt` with `--require-hashes` (sci and tools also `--only-binary :all:`), 7-day cooldown. `~/.claude/venvs/tools` (Python 3.13) holds what the stack's scripts, MCP servers and tests import (`requirements/tools.in` names the importer of each line); the full suite runs as `~/.claude/venvs/tools/bin/python -m pytest -q tests/`. Hooks never use it (stdlib on `bin/stack-python`).
- After Effects MCP: pinned commit `88d5fbf0`, `npm ci --ignore-scripts`, then an explicit `npm run build`.
- `--with-lsp` npm installs: `pyright@1.1.414`, `typescript-language-server@6.0.1` (`@5.3.0` on Node < 22.22.2) and `typescript@6.0.3` (TypeScript 7 ships no `tsserver`), all with `--ignore-scripts` (versions checked against the npm registry 2026-09-29).
- Agents can't run `install.sh` (guard, every agent type and the main thread) except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs (`HOME` and `CLAUDE_CONFIG_DIR` both under a temp dir, checked after resolving symlinks); installing is your step. The rule follows `cd <repo> && ./install.sh`, covers `lib/install_state.py apply|restore|stage|record|move-legacy` on a non-scratch config dir, and a command that copies or pipes the stack's `install.sh` and runs a shell.

### Open-file limit (2026-10-03)

macOS starts programs with a soft open-file limit of 256; elan and lake (`lake exe cache get`) need
65536, and cargo, ghcup/cabal builds and brew batches run into the default too. So before step 2
installs anything (after the step-1 checks and the change-review question), `install.sh` handles it:

1. **The LaunchDaemon** `/Library/LaunchDaemons/ulimit.max-files.plist` (Label `ulimit.max-files`,
   `RunAtLoad`, `ProgramArguments` = `/bin/launchctl limit maxfiles 65536 524288`) sets launchd's
   limit at every boot. The plist is a fixed template (a quoted heredoc, nothing interpolated;
   `tests/test_install_devtools.py` snapshots it). On a terminal (stdin and stdout) the run shows the
   path, the whole plist, the three steps, that sudo asks for the admin password itself, that running
   apps may need a re-login or reboot, and the removal commands, then asks `[y/N]`; only `y`/`yes`
   proceeds: (1) the template into a temp file, `plutil -lint`; (2) `sudo install -m 644 -o root -g
   wheel <temp> /Library/LaunchDaemons/ulimit.max-files.plist`, then `stat -f '%Su:%Sg %Lp'` must print
   `root:wheel 644` (printed); (3) `sudo launchctl bootout system <plist>` when `launchctl print
   system/ulimit.max-files` shows it loaded, then `sudo launchctl bootstrap system <plist>` (`launchctl
   load` is the deprecated form; `launchctl help` on macOS 27.0.1 lists `load` as "Recommended
   alternatives: bootstrap"); (4) `launchctl limit maxfiles`, one line. A failed step stops the
   sequence and prints the manual commands; the install goes on. This is the only place `install.sh`
   calls sudo (`lib/devtools.sh` and `stack-update-tools` never do; a test checks it).
2. **Nothing is installed, the commands are printed** (with the plist) when there is no terminal,
   under `--dry-run`, `--no-deps`, `STACK_INSTALL_MAXFILES=0`, on any answer but y, and under `--yes`
   or `--no-prompt` (they never ask; `STACK_INSTALL_MAXFILES=1`, which you set yourself, skips the
   question, still only on a terminal and never in a dry run). Already in place: launchd's soft limit
   ≥ 65536 and the plist there with the same content gives one `ok` line; ≥ 65536 set by another
   LaunchDaemon that names `maxfiles` (say `limit.maxfiles.plist`) also gives one `ok` line naming it,
   and nothing is written. Another content at the same path, or another such daemon while the limit
   is low: the diff is shown and a second `[y/N]` comes before writing; the other daemon is never
   touched (its removal commands are printed).
3. **This run's own limit.** launchd's limit reaches only programs started after it, so the run then
   raises its own soft limit with `ulimit -Sn 65536` (soft only: `ulimit -n` would also lower the hard
   limit for good), which elan, lake, rustup, cargo, brew and ghcup/cabal inherit. It reads `ulimit -Hn`
   and `sysctl -n kern.maxfilesperproc`; 65536 refused, it takes the highest value accepted (the
   smaller of those two, else 49152, 32768, …) and prints one line with the effective value. Below
   65536 step 2 skips the Lean group with the reason and the commands; the other groups go on.

Hard limit 524288 as asked: launchd itself already reports a hard limit of `unlimited` here, so the
value only matters for programs that read the hard limit (unverified whether the kernel clamps it to
`kern.maxfilesperproc`, which the sandbox can't read). This machine (read-only, 2026-10-03):
`launchctl limit maxfiles` = 65536 / unlimited, set by an existing
`/Library/LaunchDaemons/limit.maxfiles.plist` (soft 65536, hard 200000, `launchctl` without a path);
`ulimit.max-files.plist` does not exist. The next install therefore prints the `ok … set by
limit.maxfiles.plist` line and writes nothing.

### Prerequisites and toolchains (2026-10-03)

`install.sh` step 2 runs `lib/devtools.sh all` (bash 3.2; you run it in a terminal, outside the
sandbox). Order: (1) Homebrew, (2) one Homebrew batch per type, (3) the upstream version managers,
(4) the required check, (5) the rest.

**The skip rule (2026-10-04): an existing command-line tool is skipped, from whatever source.** Every
program the installer would install (brew formulae and casks, the upstream managers and what they
provide, Gradle, pre-commit, gitleaks, hlint, ormolu, Playwright's browsers, cs, elan, magg,
huetension, serial-mcp, …) is looked up first, in this order (`lib/devtools.sh`'s header and its
`DETECT_ROWS` table are the reference):
(1) PATH (`command -v`);
(2) the system login PATH, `/usr/libexec/path_helper -s` run with an empty PATH (`/etc/paths`,
`/etc/paths.d/*`: the Go .pkg registers `/usr/local/go/bin`, MacTeX `/Library/TeX/texbin`), added
to the installer's own PATH only, never to a profile;
(3) the known locations while they are not on PATH: the managers' bin dirs (`~/.local/bin`,
`~/.cargo/bin`, `~/.ghcup/bin`, `~/.cabal/bin`, `~/.elan/bin`, `~/.juliaup/bin`, Coursier's,
`~/.nvm/versions/node/*/bin`, `~/go/bin`), the mise, asdf and nix shims and profiles, `/opt/homebrew/bin`,
`/usr/local/bin`, MacPorts' `/opt/local/bin`, `/usr/local/go/bin`, `/Library/TeX/texbin`,
`/usr/local/texlive/*/bin/*`;
(4) for the tools in `DETECT_ROWS` (go, MacTeX, JDK, cmake, julia, postgres): their app bundles in
`/Applications`, `~/Applications`, `/Applications/Utilities` (a plain directory check), then
Spotlight by bundle id (`mdfind`, silent when it finds nothing; a hit under your home folder other
than `~/Applications` does not count, since sandboxed agents can write the projects there), each bundle's CLI dirs
(`Contents/MacOS`, `Contents/Resources/bin`, `Contents/Versions/*/bin`, `Contents/Home/bin` and the
row's own);
(5) their .pkg receipts (`pkgutil --pkgs`, read once per run): a receipt whose commands are not
where the pkg puts them is skipped with a `WARN` and the fix (reinstall from the .pkg, or `sudo
pkgutil --forget <id>` and rerun);
(6) `brew list --formula/--cask`; and the special paths: any JDK (its `release` file) in
`/Library/Java/JavaVirtualMachines`, `~/Library/Java/JavaVirtualMachines`, `$JAVA_HOME`, SDKMAN's
candidates or Homebrew's `openjdk` kegs (older than 27: a `WARN`, never the cask), Playwright's
revision under the browsers path.
A path is also judged with its symlinks followed (a link into a `.app` is the app, into a `Cellar`
is brew). Found means skipped: not installed, not upgraded, not replaced, not removed, with one
line `skip <tool> (found: <path>, from brew|app|pkg|<manager>|macOS|PATH)` (the same in
`--dry-run`). A manager is skipped when a
tool it provides is found (rustup: `cargo`/`rustc`; ghcup: `ghc`; juliaup: `julia`; coursier:
`coursier`; elan: `lake`/`lean`; nvm and node 24: any `node`), so no upstream installer runs again
over an existing toolchain; pnpm is set up through corepack only on nvm's own node 24. A found tool
that fails `<tool> --version` (checked for uv, rustup, juliaup, elan, ghcup, hlint, ormolu,
pre-commit, gradle, pnpm; in a real run only: `--dry-run` and `--no-deps` execute none of the tools
they find) is not touched either: one `WARN` line names it and the exact fix for you to
run (the known case: ghcup's ormolu 0.8.0.2, which crashes; the fix printed is `ghcup rm ormolu
0.8.0.2; cabal update; cabal install --ignore-project ormolu-0.9.0.0 --overwrite-policy=always`).
The side GHC 9.12.4 is installed only to build a missing hlint. magg and serial-mcp of another
version than the pin, and rustup's `rust-analyzer` proxy without the component (`--with-lsp`), get a
`WARN` with the command instead of being replaced. Step 10's language-server check runs the servers
(`rust-analyzer --version`, julia for LanguageServer.jl) in a real run only: under `--dry-run` a found
server counts and LanguageServer.jl counts when an environment's `Project.toml` lists it, so a dry run
writes no `~/.rustup` or `~/.julia`. **Configuration is not an install** and stays
idempotent: uv's global Python 3.14 pin, git's lfs filters (`git lfs install`), the Homebrew
`shellenv` line, the stack's profile and sandbox snippets: `ok` when set, set when not. Other lines:
`+` installed, `!` missing or failed (with its log and the command); the step ends with `summary: N
installed, N skipped (already there), N failed, N not installed` (dry-run: would be installed;
`--no-deps`: missing / present), plus the WARN count.

- **Homebrew batch.** The missing formulae of every enabled group go into ONE
  `HOMEBREW_NO_ANALYTICS=1 HOMEBREW_NO_AUTO_UPDATE=1 brew install …` and the missing casks into ONE
  `brew install --cask …`. Each remaining name is checked once with `brew info --formula|--cask`; a
  name brew can't resolve is reported (`! brew could not resolve: …`) and left out. A failed batch is
  retried name by name and the failures are named; nothing aborts the other groups. The cask batch
  (`oracle-jdk` and `mactex` are pkg installers that ask for your password) runs only when stdin is a
  terminal, otherwise the exact command is printed. Formula versions are Homebrew's current ones
  (not pinned; Homebrew checks each bottle's sha256 against its formula).
- **Upstream managers** stay outside Homebrew on purpose: rustup, ghcup, nvm, juliaup, uv and
  coursier each manage several toolchains and update themselves; under Homebrew, per-project
  toolchain selection (`rust-toolchain.toml`, `cabal.project` GHC pins, `.nvmrc`, `juliaup`
  channels, `.python-version`) would break. elan is the exception: with Homebrew it is the
  `elan-init` bottle (which still selects each project's `lean-toolchain`), its official installer
  only without Homebrew. Each runs its official installer, user-approved: fetched
  with `curl --proto '=https' --tlsv1.2` into a temp file (never piped, so a cut-off download never
  runs half a script), its URL and sha256 written to the log, then run with its non-interactive flags;
  never in a dry run. Everything that is a plain program comes from Homebrew.
- **Required check.** uv and node + npx: still missing after steps 1-3 (and the uv tarball fallback),
  the run stops with one message listing each and its command. `--no-deps` lists what is missing and
  installs nothing (nothing then stops the run). `--dry-run` prints `would: …` lines, including the
  two exact batch commands with their final lists, and runs nothing.
- **Lean** (`STACK_INSTALL_LEAN`): elan from Homebrew's `elan-init` formula in the brew batch (a
  bottle whose sha256 the formula pins; it links `elan`, `lake` and `lean`, is built without
  self-update, and gets `elan toolchain install leanprover/lean4:stable && elan default
  leanprover/lean4:stable` once, after the managers above). Only without Homebrew (the fallback route):
  `https://elan.lean-lang.org/elan-init.sh` with `-y --default-toolchain stable` (flags from the
  script's usage text, fetched 2026-10-03, sha256 `a620ff16…aa685bf53` that day; residual risk, only
  on this fallback route: the script itself downloads the elan binary from
  `github.com/leanprover/elan/releases/latest` with `curl -sSfL`, no checksum). Either is skipped
  when `elan`, `lake` or `lean` is found anywhere. Then, in "the rest",
  the Mathlib project by the repo's convention (`lib/stack.env.example`, the lean-formalization skill):
  a project `LEAN_PROJECT_PATH` names (your `stack.env`, else the environment) is used as it is and
  never touched; otherwise `~/lean/stack_mathlib` is made with `lake +stable new stack_mathlib math`
  (its `lakefile.toml` requires Mathlib at the tag of its `lean-toolchain`; checked after creation, a
  mismatch stops with the fix), then `lake exe cache get` and, only if that succeeded, `lake build`
  (the template's library, cheap with the cache; a failed cache never starts a build of all of
  Mathlib). About 8 GB and 10-30 minutes: only on a terminal or with `STACK_INSTALL_LEAN_MATHLIB=1`
  (`=0` never), otherwise the commands are printed. The run then prints the `LEAN_PROJECT_PATH=…`
  line to put in your `stack.env` (proof-checker's lean server reads it; the installer doesn't write
  it). The whole group is skipped while the open-file limit is below 65536 ("Open-file limit" above).
  `~/.elan/bin` joins the PATH of the rest of the run (the `lean-lsp` plugin then finds `lake`).
- **`--no-profile`** reaches the installers that have a switch for it (rustup `--no-modify-path`,
  elan `--no-modify-path`,
  juliaup `--add-to-path=no`, uv `UV_NO_MODIFY_PATH=1`, nvm `PROFILE=/dev/null`, ghcup without
  `BOOTSTRAP_HASKELL_ADJUST_BASHRC`) and stops the Homebrew `shellenv` line. Without it, Homebrew
  installed by this step gets `eval "$(/opt/homebrew/bin/brew shellenv)"` in `~/.zprofile`, once
  (skipped when any profile already has a `brew shellenv` line).

Groups (environment, read by `lib/devtools.sh`; `=0` skips one, `=1` adds an off-by-default one):

| Knob | Default | What it covers |
|---|---|---|
| `STACK_INSTALL_DEPS` | 1 | Homebrew itself; jq, ripgrep, gh, ffmpeg, imagemagick, librsvg, poppler; the uv tarball and the jq/gitleaks binary fallbacks when there is no Homebrew |
| `STACK_INSTALL_DEVTOOLS` | 1 | gitleaks (batch), pre-commit, Gradle 9.8.0, Playwright 1.63.0's Chromium and headless shell |
| `STACK_INSTALL_UV` | 1 | uv (astral.sh installer) and Python 3.14 as uv's global pin |
| `STACK_INSTALL_NODE` | 1 | nvm v0.40.8, node 24, pnpm through corepack |
| `STACK_INSTALL_RUST` | 1 | rustup (default toolchain) |
| `STACK_INSTALL_HASKELL` | 1 | ghcup (bootstrap with HLS and stack when missing), hlint 3.10 (GHC 9.12.4), ormolu 0.9.0.0 |
| `STACK_INSTALL_JULIA` | 1 | juliaup |
| `STACK_INSTALL_SCALA` | 1 | coursier (`cs setup -y`: JVM tools, scala, sbt) |
| `STACK_INSTALL_JAVA` | 1 | `oracle-jdk` cask when no JDK is installed (an older one than 27: WARN only), `kotlin-lsp` cask |
| `STACK_INSTALL_LATEX` | 1 | `mactex` cask (about 5 GB; `brew install --cask mactex-no-gui` is the smaller one) |
| `STACK_INSTALL_CXX` | 1 | cmake, cmake-docs, ninja, ffmpeg-full, pandoc, git-lfs, tesseract, typst, shellcheck, markdownlint-cli2; then `git lfs install` when its global filters are missing |
| `STACK_INSTALL_GO` | 1 | go, gopls |
| `STACK_INSTALL_LEAN` | 1 | elan (stable toolchain) and the Mathlib project (`~/lean/stack_mathlib` unless `LEAN_PROJECT_PATH` names one); skipped while the open-file limit is below 65536 |
| `STACK_INSTALL_LEAN_MATHLIB` | auto | the Mathlib project (about 8 GB): auto = only on a terminal, `1` also without one, `0` never (the commands are printed) |
| `STACK_INSTALL_MAXFILES` | ask | read by `install.sh` itself, before step 2: the `ulimit.max-files` LaunchDaemon. `ask` = asks on a terminal (default No), `0` = never (prints the commands), `1` = no question (still only on a terminal, never in `--dry-run`) |
| `STACK_INSTALL_POSTGRES` | 0 | postgresql@18 (keg-only: `$(brew --prefix postgresql@18)/bin`; `brew services start postgresql@18`) |
| `STACK_INSTALL_MONGODB` | 0 | `brew tap mongodb/brew`, then mongodb/brew/mongodb-community |

Dependency table (for review; the last column is what the next install does on this machine, from
read-only lookups with `lib/devtools.sh where <tool>` on 2026-10-04 inside the sandbox: "skip" =
found, never touched; "batch" = joins the brew batch; "install" = its route runs):

| Tool | Required? | Route | Version / integrity | Next install here |
|---|---|---|---|---|
| python3, git (Command Line Tools) | required | not installed: step 1 stops with `xcode-select --install` | — | present |
| Claude Code | required | not installed: step 1 stops with the install command (it runs before the change-review question, R4) | ≥ 2.1.271 | present |
| Homebrew | optional (needed for the batch) | `/bin/bash` running `https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh`, terminal only, interactive | latest (HEAD), not pinned | skip (`/opt/homebrew/bin/brew`) |
| uv | required | astral.sh installer `https://astral.sh/uv/install.sh`; else the 0.12.20 release tarball | installer latest; tarball sha256-pinned | skip (`~/.local/bin/uv`) |
| Python 3.14 global pin | optional | `uv python install 3.14 && uv python pin --global 3.14` | uv's checksummed managed Pythons | configuration: the pin is set (3.14 present) |
| nvm, node 24 | required (node) | `https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.8/install.sh`, then `nvm install 24` | nvm pinned v0.40.8 (latest unverified); node from nodejs.org via nvm | skip (node v24.21.0 from nvm) |
| pnpm | optional | `corepack enable pnpm` (only on nvm's node 24, only when no pnpm is found), then `COREPACK_ENABLE_DOWNLOAD_PROMPT=0 pnpm -v`; a found pnpm that fails `--version` gets a `WARN`, never `corepack enable` over it (checked in a real run only: `pnpm --version` could make corepack download pnpm) | corepack's signature check | skip (nvm's node 24 `pnpm`) |
| rustup | optional | `https://sh.rustup.rs` with `-y`; skipped when `rustup`, `cargo` or `rustc` is found | latest | skip (`~/.cargo/bin/rustup`) |
| ghcup | optional | `https://get-ghcup.haskell.org`, `BOOTSTRAP_HASKELL_NONINTERACTIVE=1 BOOTSTRAP_HASKELL_INSTALL_HLS=1 BOOTSTRAP_HASKELL_ADJUST_BASHRC=1`; skipped when `ghcup` or `ghc` is found | latest | skip (`~/.ghcup/bin/ghcup`) |
| hlint | optional | `ghcup install ghc 9.12.4` (no `--set`), `cabal update`, `cabal install --ignore-project -w ghc-9.12.4 hlint-3.10 --overwrite-policy=always` (`CABAL_DIR`, `XDG_CACHE_HOME` unset); only when no hlint is found | 3.10; ghcup checks GHC's sha256, cabal Hackage's signed index | install (no hlint found) |
| ormolu | optional | `cabal update; cabal install --ignore-project ormolu-0.9.0.0 --overwrite-policy=always`, only when no ormolu is found (never `ghcup rm`) | 0.9.0.0 | skip + WARN: `~/.ghcup/bin/ormolu` aborts on `--version` (fix printed, run it yourself) |
| juliaup | optional | `https://install.julialang.org` with `--yes`; skipped when `juliaup` or `julia` is found | latest | skip (`~/.juliaup/bin/juliaup`) |
| coursier | optional | `https://github.com/coursier/coursier/releases/latest/download/cs-aarch64-apple-darwin.gz`, gunzip, quarantine removed, `./cs setup -y`, temp copy deleted | latest, no checksum | skip (Coursier's `cs`) |
| jq, ripgrep, gh, ffmpeg, imagemagick, librsvg, poppler | optional | brew batch (jq without Homebrew: 1.8.2 release binary, sha256) | Homebrew current | skip jq (`/usr/bin/jq`, macOS), ffmpeg, imagemagick, librsvg, poppler; batch: ripgrep, gh |
| gitleaks | optional | brew batch (without Homebrew: 8.30.1 release tarball, sha256 from `gitleaks_8.30.1_checksums.txt`) | Homebrew 8.30.1 | batch (none found) |
| cmake, cmake-docs, ninja, ffmpeg-full, pandoc, git-lfs, tesseract, typst, shellcheck, markdownlint-cli2 | optional | brew batch | Homebrew current (cmake 4.4.3, ffmpeg-full 9.0.2 keg-only, typst 0.15.1, …) | skip (all in `/opt/homebrew/bin` or brew's list) |
| go, gopls | optional | brew batch (`gopls` is a formula, not a cask); go only when no Go is found anywhere (the official .pkg counts: `/usr/local/go/bin` from `path_helper` or the known dirs, or its receipt `org.golang.go`). gopls next to a non-Homebrew Go: Homebrew's bottle, which needs no go (`brew deps gopls` is empty, go is build-only; checked 2026-10-04); should the formula pull Homebrew's go in (a runtime dependency, or no bottle for this macOS) it is `go install golang.org/x/tools/gopls@v<the formula's version>` with your Go instead, into your `GOBIN` (`go env GOBIN`) or else `~/.local/bin` (go's default `~/go/bin` is often on no PATH), with `GOMODCACHE`/`GOCACHE` unset so a sandbox cache is never used, and the run says which | Homebrew current (go 1.27.1, gopls 0.23.0); `go install` checked by the Go checksum database | skip (go `/usr/local/go/bin/go` from pkg, gopls `/opt/homebrew/bin/gopls` from brew) |
| Oracle JDK | optional | `oracle-jdk` cask, terminal only, only when no JDK of any version is found (each JDK's `release` file in `/Library/Java/JavaVirtualMachines`, `~/Library/Java/JavaVirtualMachines` (IntelliJ's downloads), `$JAVA_HOME`, SDKMAN's `~/.sdkman/candidates/java`, Homebrew's `opt/openjdk*` kegs; `/usr/bin/java` is only macOS's stub). The newest one found older than 27: left alone with a `WARN` naming `brew install --cask oracle-jdk` (installing it would make 27 the `java_home` default: a replacement in effect) | cask 27 | skip (jdk-27.jdk, from pkg: receipt `com.oracle.jdk-27`) |
| kotlin-lsp | optional | `kotlin-lsp` cask (homebrew/cask, not JetBrains' tap) | cask 263.4702.0 | skip (`/opt/homebrew/bin/kotlin-lsp`) |
| MacTeX | optional | `mactex` cask, terminal only, only when no TeX is found: `pdflatex` on PATH or `path_helper`'s dirs, `/Library/TeX/texbin`, `/usr/local/texlive/*/bin/*`, or a receipt `org.tug.mactex.texlive*` / `org.tug.mactex.basictex*` (MacTeX or BasicTeX from their .pkg). Updates are yours: `tlmgr` (the stack never runs it, nor sudo for it; `stack-update-tools` prints the reminder) | cask 2026.0324 | skip (`/Library/TeX/texbin/pdflatex` from pkg) |
| Tools installed any other way (.pkg, .dmg, apps, other managers) | — | looked up before any route: PATH plus the system login PATH (`path_helper -s`, this run only); the known dirs (managers, `~/go/bin`, mise/asdf/nix shims, MacPorts, `/usr/local/go/bin`, `/Library/TeX/texbin`, `/usr/local/texlive`); for go, MacTeX, the JDK, cmake, julia, postgres (`DETECT_ROWS` in `lib/devtools.sh`) their apps in `/Applications`, `~/Applications`, `/Applications/Utilities`, then Spotlight by bundle id, CLIs inside the bundle, and their receipts (`pkgutil --pkgs`, read once). A receipt whose files are gone: skip + WARN with the fix | receipt ids seen here: `org.golang.go`, `org.tug.mactex.texlive2026`, `com.oracle.jdk-27`; the others from the casks' `pkgutil`/`app`/`binary` stanzas (not installed here: unverified on this machine) | `skip … from pkg` for go, MacTeX, the JDK |
| postgresql@18, mongodb-community | optional, off | brew batch (mongodb after `brew tap mongodb/brew`) | Homebrew current | skip (`postgres`, `mongod` in `/opt/homebrew/bin`; no `brew tap` either) |
| pre-commit | optional | `uv tool install --python 3.14 --exclude-newer 2026-09-26T00:00:00Z pre-commit==4.6.2` | version + dependency cooldown | install (none found) |
| Gradle | optional | `gradle-9.8.0-all.zip` from `github.com/gradle/gradle-distributions` into `~/.local/opt/gradle-9.8.0`, linked from `~/.local/bin/gradle` (not Homebrew: its formula pulls a second JDK) | 9.8.0, sha256 `46ac66d4…47bc0cf` (equal to Homebrew's for the same zip) | install (none found) |
| Playwright Chromium + headless shell | optional | `npx -y playwright@1.63.0 install chromium chromium-headless-shell` into Playwright's default cache (or `$PLAYWRIGHT_BROWSERS_PATH`) | npm package 1.63.0 (registry integrity); browser revision 1243 over HTTPS, no published checksum; skipped when revision 1243's two browsers are complete there | install unless present (not checked) |
| Open-file limit LaunchDaemon `/Library/LaunchDaemons/ulimit.max-files.plist` | optional (Lean needs the limit) | `install.sh` before step 2, after your y on a terminal: `sudo install -m 644 -o root -g wheel`, `sudo launchctl bootstrap system` (the only sudo the installer runs) | fixed template in `install.sh`, `plutil -lint` | limit already 65536 via `limit.maxfiles.plist`: one `ok` line, nothing written |
| elan (+ Lean stable) | optional | Homebrew's `elan-init` in the brew batch, then `elan toolchain install leanprover/lean4:stable && elan default leanprover/lean4:stable`; without Homebrew only (fallback): `https://elan.lean-lang.org/elan-init.sh` `-y --default-toolchain stable` | Homebrew: elan-init 4.2.4, bottle sha256 pinned in the formula, brings `coreutils` and `gmp` at runtime (checked 2026-10-04); fallback route only: latest, the script fetches elan's latest GitHub release with no checksum; skipped when `elan`, `lake` or `lean` is found; `stack-update-tools` skips `elan self update` for Homebrew's elan | skip (`~/.elan/bin/elan`) |
| Mathlib project | optional | `lake +stable new stack_mathlib math` in `~/lean`, `lake exe cache get`, `lake build`; terminal or `STACK_INSTALL_LEAN_MATHLIB=1` | Mathlib pinned to the `lean-toolchain` tag (lake manifest pins the commit); cache from Mathlib's own `cache` tool | `~/lean/stack_mathlib` missing; `LEAN_PROJECT_PATH` unknown (stack.env unreadable from the sandbox) |
| magg, huetension, serial-mcp, venvs | as in "Supply chain" | install.sh step 2; magg, huetension and serial-mcp follow the skip rule (another magg or serial-mcp version: WARN with the command) | as there | skip magg, huetension (`~/.local/bin`) |

Corrections to the commands as first written (applied): Homebrew runs interactively, not with
`NONINTERACTIVE=1` (that mode uses `sudo -n`, which fails without a cached sudo; checked in the
installer script); ghcup has no `BOOTSTRAP_HASKELL_INSTALL_STACK` (stack is installed unless
`BOOTSTRAP_HASKELL_INSTALL_NO_STACK` is set; the variable names come from `bootstrap-haskell` on
GitHub, `get-ghcup.haskell.org` itself is not reachable from the sandbox); rustup and juliaup take
`-y` / `--yes` instead of piped Enter keys (flags checked in `rustup-init.sh` and `juliaup-init.sh`
on GitHub; `sh.rustup.rs` and `install.julialang.org` were not reachable); corepack's download
question is answered by `COREPACK_ENABLE_DOWNLOAD_PROMPT=0`; nvm is sourced in a child bash; uv's
global pin is `uv python pin --global 3.14` (`uv python pin --help`, uv 0.12.22); Coursier comes from
`coursier/coursier` releases (the asset `cs-aarch64-apple-darwin.gz` answers 200), not the archived
`VirtusLab/coursier-m1` (alternative: `brew install coursier`, in homebrew/core); `go-pls` is the
`gopls` formula; `kotlin-lsp` is a homebrew/cask cask; `ffmpeg-full` and `postgresql@18` are keg-only
(not linked into PATH: `ffmpeg` on PATH stays the `ffmpeg` formula's); the JDK is the `oracle-jdk`
cask (27, matching the installed Oracle JDK) because a cask's pkg lands in
`/Library/Java/JavaVirtualMachines`, where `java_home` picks the highest version, while Homebrew's
keg-only `openjdk` needs a `sudo ln -sfn` that install.sh never runs.

**Updating together: `~/.claude/bin/stack-update-tools [--dry-run]`.** This is the explicit update
command, not the installer: unlike `install.sh` (which never upgrades anything it finds) it updates
the tools that are present. One line per tool, a missing
one skipped, a failure never stopping the rest: `brew update && brew upgrade --formula` (casks are
printed as a manual line, `brew upgrade --cask`: the pkg casks run sudo installers), `rustup update`, `juliaup update`, `ghcup upgrade` (ghcup itself; GHC/cabal/HLS versions stay
yours: `ghcup tui`), `uv self update` (only for uv not installed by Homebrew) and `uv tool upgrade
--all` (pre-commit, magg: within the constraints they were installed with), `cs update`, `elan self
update` (only for elan not installed by Homebrew) and `elan update` (the channels you installed; a
project's `lean-toolchain` and Mathlib move only with `lake update` there); node is
manual (it prints the version and the `nvm install 24 --reinstall-packages-from=current` command).
The pinned tools (Gradle, Playwright's browsers, hlint/ormolu, the venvs) move when a newer
`install.sh` pins newer versions. From an agent's sandboxed Bash every step fails on the sandbox's
write rules: run it in your terminal.

ormolu 0.9.0.0 may format differently from 0.8.0.2 (unverified); fourmolu (installed through ghcup on
this machine) is the fallback.

Why the browsers stay in Playwright's default cache: `~/Library/Caches/ms-playwright` is readable by
sandboxed commands and `denyWrite` to them, so a sandboxed `npx playwright test` on 1.63.0 finds the
installed revision and nothing sandboxed can plant a browser your terminal or the playwright MCP
starts later. A project on another Playwright version needs that version's browsers installed from
your terminal (`npx playwright install chromium chromium-headless-shell` in the project). Google
Chrome through `channel: 'chrome'` fails in the sandbox (Crashpad and the ProcessSingleton socket
under `/var/folders`): use the bundled Chromium there. That a sandboxed run launches the headless
shell from this path is unverified until the first run after an install.

In the sandbox (P34-style builds; not the installer's job): `GRADLE_USER_HOME` already points at
`~/.cache/claude-sandbox/gradle`; `JAVA_HOME` must be set explicitly (`/usr/libexec/java_home` fails
in the sandbox; this machine: `/Library/Java/JavaVirtualMachines/jdk-27.jdk/Contents/Home`);
`services.gradle.org`, `plugins.gradle.org` and `downloads.gradle.org` are not on the allowlist, so
use `pluginManagement { repositories { mavenCentral() } }` and a GitHub `distributionUrl` for a
wrapper; set `kotlin.compiler.execution.strategy=in-process`; the JVM ignores `HTTPS_PROXY`, so pass
`-Dhttps.proxyHost/Port/User/Password` and `-Djdk.http.auth.tunneling.disabledSchemes=` through
`JAVA_TOOL_OPTIONS` built at run time from `$HTTPS_PROXY` (never written to a file). pnpm 12.8.1
ignores `npm_config_store_dir` (it reads `pnpm_config_store_dir` or `--store-dir`), and the Corepack
shim fails behind the proxy unless `COREPACK_HOME` points at the Corepack home that already holds
pnpm (`~/.cache/node/corepack`; the sandbox's `XDG_CACHE_HOME` moves Corepack's default away from
it). The session-env hook exports both (`pnpm_config_store_dir`, `COREPACK_HOME`) for sandboxed Bash;
outside the sandbox pass `--store-dir ~/.cache/claude-sandbox/pnpm-store` and
`COREPACK_HOME=~/.cache/node/corepack` yourself.

### Sandbox and managed settings

- **Status: configured, not live-verified.** The settings, the guard and the tests are checked; that Claude Code's sandbox enforces them as configured is not, until the user runs the live checks (README → Security model → Live checks). Until then the guard and the deny rules are the tested layers.
- `settings.json` turns the sandbox on with `allowUnsandboxedCommands: false`:
  - **filesystem:** `denyWrite` covers the config dir, the guard state dir (`__STACK_STATE__`), the backups (`__STACK_BACKUPS__`) and the MCP servers' cache (`__STACK_CACHE__`), all rendered from `${XDG_STATE_HOME:-~/.local/state}` at install time (changing `XDG_STATE_HOME` later needs a reinstall), plus `~/.cache/uv`, `~/.cache/pre-commit`, the Playwright browser caches, `~/Library/Caches/Coursier` and the Hugging Face token file. `denyRead` covers `stack.env`, the state dir's `*.lock` and `*.mutex` files (a flock taken from a read-only fd would stall the collector, the limits commands or the guard), `backup-*`, the backups, `.credentials.json`, `~/.config/gh/hosts.yml`, `~/.git-credentials` and `~/.config/git/credentials`. `allowWrite` is only `~/.cache/claude-sandbox`.
  - **network:** a strict allowlist of package registries, forges, Hugging Face, W&B and arXiv.
  - **credentials:** forge tokens (`GITHUB_TOKEN`, `GH_TOKEN`, GitHub Enterprise, GitLab/Gitea/Forgejo/Codeberg), `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `WANDB_API_KEY` and `JUPYTER_TOKEN` are denied to sandboxed commands.
- `failIfUnavailable: true`: Claude Code exits at startup when the sandbox can't start, instead of warning and running commands unsandboxed.
- **Caches (N4, R3-CACHES).** Sandboxed Bash and everything else no longer share a writable cache.
  - Sandboxed Bash gets its own caches, `~/.cache/claude-sandbox/<tool>`, from a SessionStart hook without a matcher (`agent_guard.py session-env`, every source) that appends exports to `$CLAUDE_ENV_FILE`; Claude Code runs that file before each Bash command, the agents' included. The variables: `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `npm_config_cache`, `npm_config_devdir`, `npm_config_store_dir` and `pnpm_config_store_dir` (one `pnpm-store` dir: pnpm 12 reads only the second), `YARN_CACHE_FOLDER`, `BUN_INSTALL_CACHE_DIR`, `DENO_DIR`, `PRE_COMMIT_HOME`, `HF_HOME`, `MPLCONFIGDIR`, `CARGO_HOME`, `GOMODCACHE`, `GOCACHE`, `GRADLE_USER_HOME`, `COURSIER_CACHE`, `CCACHE_DIR`, `SCCACHE_DIR`, `CABAL_DIR`, `JULIA_DEPOT_PATH` (`<dir>/julia:`, the default depots after it), plus `-Dmaven.repo.local=<dir>/m2` appended to `MAVEN_OPTS`. Outside the cache root: `COREPACK_HOME` = `~/.cache/node/corepack` (the Corepack home that already holds pnpm; the shim fails behind the proxy without it, and the sandbox's `XDG_CACHE_HOME` would move it), and `JAVA_HOME` from `/usr/libexec/java_home` as this hook (outside the sandbox) sees it, kept when already set, left out when the tool fails or prints anything but an existing plain absolute path (it fails inside the sandbox). MCP servers, hooks, language servers and the user's terminal don't see them and keep their normal caches, which sandboxed code can no longer write. Safe to delete.
  - Evidence that subagents get the file: the hooks reference promises `CLAUDE_ENV_FILE` to "subsequent Bash commands" (SessionStart, Setup, CwdChanged and FileChanged hooks get it) and says nothing about subagents; the installed CLI (2.1.284) keeps the file per session id, not per agent, and prepends it to every Bash command of the session, subagents' included. The docs don't promise it, hence a live check. Fallback if a future version stops that (not built): the no-push hook could refuse sandboxed Bash lacking `UV_CACHE_DIR` under `~/.cache/claude-sandbox`.
  - Trade-offs (sandboxed Bash only): `CARGO_HOME` moves, so `~/.cargo/config.toml` and cargo's credentials aren't read and `cargo install` binaries land in the sandbox's cargo dir; `GRADLE_USER_HOME` moves, so `~/.gradle/gradle.properties` isn't read; `HF_HOME` moves, so models download again and no Hugging Face token is found; when `$HOME` holds a character Maven would split on (a space, a quote), `MAVEN_OPTS` is left alone with a warning and Maven falls back to `~/.m2`, which the sandbox refuses; a tool that writes `~/Library/Caches` (or another cache) with no variable to redirect it fails; a Bash command that runs before the hook has written the file gets the default paths, which the sandbox refuses (fails closed).
  - The stack's own local MCP servers keep their private `STACK_CACHE`, `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-cache/{uv,npm}` (sandbox-denyWrite, set in each server's `env` when the installer renders the agents, passed on by magg to the catalog servers, warmed by the prefetch): one cache the sandbox can't touch for the servers the stack ships.
  - Installed toolchains (rustup, elan, Julia packages, managed Pythons) stay readable; installing new ones from inside the sandbox fails (`~/.rustup` and the uv tool dir stay unwritable). Julia's first depot is the sandbox's own, so precompiled caches and new packages land there; cabal's `CABAL_DIR` starts empty (run `cabal update` once; `hackage.haskell.org` is allowed).
  - An upgrade retracts from the user's `settings.json` the `env` keys and `allowWrite` entries earlier installs shipped (`UV_CACHE_DIR`, `npm_config_cache`, `PRE_COMMIT_HOME`, `GIT_CONFIG_COUNT`/`KEY_0`/`VALUE_0`; `~/.cache`, `~/Library/Caches`, the cargo/go/gradle/maven/bun/matplotlib/uv/npm/rustup/julia/elan dirs), printing each, and keeps entries of the user's own; a first install (no manifest) retracts nothing. The cache-runner warnings about the user's own MCP servers and hooks are gone from `install.sh` and `doctor.sh`; `doctor.sh` warns when the old keys or a broad cache dir are still there and confirms the session-env hook is wired.
  - **Hook failure is visible (R4-2).** If the hook can't write the environment (no `CLAUDE_ENV_FILE`, an unwritable file or `~/.cache/claude-sandbox`, or its marker missing after writing), it exits 2 and the session shows a SessionStart hook error ("the sandboxed Bash environment is NOT set for this session (reason) … Check with …/bin/doctor.sh, then start a new session (or /clear)"); the session goes on without the caches and with git's credential helpers on. The guard records running/ok/failed in the session's state dir (`session-env.json`); the status line starts with a red `! Bash sandbox env missing: doctor.sh` for that session (also when the hook never finished, after 30 s); `doctor.sh` runs the hook against a temp dir and warns when it failed in any of the last 10 sessions.
- **Credentials (N1, C2, R3-GITENV).** Git credential helpers are off in sandboxed Bash only: the session-env hook appends `'credential.helper='` (an empty helper list) to `GIT_CONFIG_PARAMETERS`, after any value already there, and touches no `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_*` of the user's. Unsandboxed git (plugin marketplace updates, MCP servers, the terminal) keeps its helpers, so private marketplace updates work again; a private HTTPS fetch from an agent's Bash needs SSH or the terminal. `~/.config/gh/hosts.yml`, `~/.git-credentials` and `~/.config/git/credentials` are `denyRead` (and `Read` deny rules). The guard also refuses `gh auth token`, `gh auth status -t`, `git credential fill|approve|reject`, `git credential-*`, keychain dumps (`security find-*-password -w/-g`, `dump-keychain`, `export`) and Claude Code's headersHelper mode of `mcp-headers` (`CLAUDE_CODE_MCP_SERVER_NAME=...`) for every agent.
- **Least-privilege GitHub (R3-N1-P2).** Give the agents no write-capable GitHub credential: none at all, or a read-only fine-grained token (Contents: read, Metadata: read) that `gh` uses from its own config dir (`GH_CONFIG_DIR=~/.config/gh-agents gh auth login --with-token < token-file`, then export that `GH_CONFIG_DIR` in the shell `claude` starts from). Push over SSH from the user's terminal (agents never push: hook-enforced), and keep write-capable HTTPS credentials out of the `github.com` keychain entry git's osxkeychain helper reads, since unsandboxed git still uses it.
- **doctor.sh credential presence.** Section "GitHub credentials agents could use" reports by presence only (no value printed; keychain lookups are attribute searches without `-g`/`-w`, so no secret is read and no prompt appears): `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN` in the environment; a plain-text `oauth_token` in gh's `hosts.yml` (`$GH_CONFIG_DIR` or `~/.config/gh`); a github.com line in `~/.git-credentials` or `${XDG_CONFIG_HOME:-~/.config}/git/credentials`; on macOS a keychain item for service `gh:github.com` (from gh's source; unverified against a live gh) and a github.com internet password. Each is a WARN naming who can use it (sandboxed Bash is denied the token variables, `~/.config/gh/hosts.yml` and `~/.git-credentials`; hooks, MCP servers and other unsandboxed processes are not; a `hosts.yml` under another `GH_CONFIG_DIR` isn't denied) and the least-privilege step; none found is `ok`.
- **Web taint (T3, R3-T3-RELAY).** An agent can't write the shared memory when it, or any agent linked to it, read web content: a child that reported back to it (the registry's parent links, transitively), an agent it exchanged SendMessage with (either direction, transitively), or the prompt it was spawned with (a child of a tainted agent is born tainted). A message to a name whose agent id isn't known yet is linked through the Agent call that spawned it. A spawn whose mark can't be recorded is refused; past 4,096 linked agents the check fails closed; the refusal names the source. The main thread is not a link; files are not links (residual).
- **Read-only reviewers and temp dirs (R3-INFO).** A project checked out under a temp dir (`/tmp`, `/private/tmp`, `/var/folders`, `$TMPDIR`) is the project, not scratch; `./.claude-work` stays scratch everywhere, and a session whose project is a temp dir itself keeps all of it scratch. The project is `CLAUDE_PROJECT_DIR`; only without it do the event's cwd and the hook's cwd count. Before, 118 of this repo's tests failed from a checkout under `/private/tmp` (all in `test_readonly_agents.py`); 0 now.
- **magg (N3).** `magg_add_server`, `magg_load_kit`, `proxy`, `magg_enable_server` and every `duckdb_*`, `jupyter_*`, `ros_*`, `qiskit_*`, `docspace_*` call and every call of the domain catalog servers (`mobile_*`, `android_*`, `godot_*`, `biomcp_*`, `pubchem_*`, `k8s_*`, `grafana_*`, `edgar_*`, `serial_*`, `gis_*`) are `ask` rules. Every catalog prefix has exactly one allow or ask rule (test), and `mongodb_*`/`postgres_*` stay allowed only with their read-only flags (`--readOnly`, `--access-mode=restricted`; test); ask rules prompt even in `bypassPermissions` ([permission modes: actions no mode auto-approves](https://code.claude.com/docs/en/permission-modes)). A background agent's prompt appears in your main session, naming the agent ([subagents](https://code.claude.com/docs/en/sub-agents)). duckdb runs on an in-memory database (no database file to write, no `--allow-switch-databases`), extensions don't autoload and its settings are locked (`--init-sql`); an explicit `INSTALL` in an approved query still works; jupyter has no read-only mode, so the prompt is its control.
- The installer merges this block into yours: the stack's scalars win and lists are unioned.
- `./install.sh --print-managed-settings > managed-settings.json` prints an optional root-level file (instructions go to stderr). It repeats the stack's hook entries, the protected-path and `~/` Read deny rules and the sandbox, so editing `~/.claude/settings.json` can't remove them. It pins the hook entries, not the hook's code: the guard still runs from `~/.claude/hooks/` unless the root-owned copy below is installed.
- Installing that file is your step: `/Library/Application Support/ClaudeCode/managed-settings.json` (macOS) or `/etc/claude-code/managed-settings.json`. The installer never writes anything root-owned. Re-print it after an install that changed the hook or deny rules. The printed file includes `failIfUnavailable`.
- **Stronger, optional (N-MANAGED, documented only).** The printed file still runs the guard from `~/.claude/hooks/`, which you (and anything running as you outside the sandbox) can edit. To pin it:
  1. Copy `agent_guard.py` to a root-owned place (`sudo install -o root -m 755 ~/.claude/hooks/agent_guard.py '/Library/Application Support/ClaudeCode/hooks/agent_guard.py'`).
  2. Point every hook command of the stack at that copy in `managed-settings.json` (all events of `settings.json` `hooks`, not only the no-push one).
  3. Add `"allowManagedHooksOnly": true` (managed-only key): user, project, local, plugin and agent-frontmatter hooks stop running. BlackCat's frontmatter wiring then no longer runs, so the settings-level `blackcat-guard --settings` hook must be in the managed file.
  4. Re-copy the hook after every install that changes it.

### Residual risks

- **The shell parsing is a heuristic.** The read-only reviewer allowlist, the protected-path scan and no-push all parse shell text. The sandbox, and managed settings once you install them, are the real boundary; without the sandbox a determined interpreter one-liner can still slip past the parser.
- **`gh` can still use a keychain token.** `hosts.yml` is unreadable in the sandbox now, but `gh` (and git's `osxkeychain` helper run directly) can still reach a token stored in the macOS keychain from code the guard doesn't recognise. The guard refuses the commands that print it and the no-push hook refuses forge writes (`gh`, `git push`, `curl`/`wget`/`httpie` writes to forge hosts); arbitrary code that talks to the keychain or sends the token itself isn't caught by either. Mitigation: the least-privilege GitHub setup above; `doctor.sh` reports what an agent could find. The keychain service name `gh:github.com` is unverified.
- **Language servers run outside the sandbox on files the sandbox can write.** rust-analyzer runs build scripts and proc macros, Metals/Gradle, HLS and `lake serve` run build code, and LanguageServer.jl loads packages: a sandboxed command that edits a project's build files (`build.rs`, `build.sbt`, `lakefile`, ...) gets that code run unsandboxed the next time the language server starts. Accepted: the project is writable by design; round 3 removed the shared caches, so this is now the project's own files only. Disable the LSP plugins for untrusted work.
- **Caches (round 3).** The two round-2 cache residuals (your own MCP servers and hooks on the sandbox cache; other writable caches) are closed: sandboxed Bash and everything else no longer share a writable cache. What stays: the trade-offs listed under Caches, and a sandboxed tool with no cache variable failing instead of writing elsewhere.
- **Read-only database servers.** `mongodb` and `postgres` catalog entries are allowed without a prompt because of their read-only flags; a server-side bug in those modes would go unprompted.
- **MCP servers allowed whole run outside the sandbox.** Claude Code's sandbox covers Bash, PowerShell and Monitor commands and their children only (permissions docs, "How permissions interact with sandboxing"). Unprompted since 2026-10-03: lean-lsp-mcp compiles Lean, whose `#eval` can run `IO`; mobilebuild runs Xcode builds, whose script phases run code; computer-use clicks and types in the apps you granted it (its per-application grant still applies). The same held for every MCP tool under `bypassPermissions`, and blender, after-effects and magg's `lean_*` were already allowed. Put a server in `ask` in your own `settings.json` to be asked again.
- **Approved duckdb/jupyter calls.** Once you approve it, a duckdb query can read (or `COPY TO`) any file you can, and a jupyter call runs code in your kernel: read the call before approving.
- **Web reads in memory (T3).** An agent that read web content in a task (WebFetch, WebSearch, curl/wget in Bash, and every MCP tool except a short non-web list: neural-memory, wolfram, wandb, image-studio, the Adobe and Blender servers, huetension, ide, magg's management tools and its local database/kernel servers), or is linked to one (see Web taint above), can't write the shared memory for the rest of the session; content fetched by other means (inline Python, say) isn't seen. Taint follows reports, messages and spawn prompts but not files: an agent that saved web text to a file and another that reads it later are not linked (tracking file provenance would need content tagging the hooks can't do).
- **Reviewers' scratch code (T2).** The read-only types' scratch scripts and test files are content-checked with the same heuristic as inline code before they run; writing scratch code and running it in the same command is refused, as is a scratch operand that doesn't exist yet, inline Python that loads scratch code (`sys.path`, `runpy`, importlib loaders) and `python -c` run from a scratch dir. Code that hides from the pattern still runs with the sandbox's project-wide write access; a background job that swaps a file between two calls, `python -m` of a module shadowed in a scratch cwd and a `PYTHONPATH` exported in an earlier call aren't seen. Scratch code another agent wrote is checked the same way (no exemption by age). A scratch `pyproject.toml`, `tox.ini` or `setup.cfg` blocks pytest only with a pytest section (`pytest.ini` always). `uv run` refuses a scratch project it would build, whose backend runs unread: `setup.py`, `[build-system]`, `backend-path`, `package = true`, path, workspace or `file:` sources, `--with-editable` (`--no-sync` and `--no-project` build nothing). JS runners scan the `.claude-work` of their root (nearest `package.json` or runner config up from the cwd) and of the cwd, bounded by the hook's deadline, not by a file count.
- **Protected-path scan gaps.** A bare protected name (`bin`, `hooks`, ...) behind an expansion the guard can't resolve counts when that expansion could be steered: a command substitution (other than `mktemp`, `pwd`, `dirname`, `basename`, `git rev-parse --show-toplevel`), a variable set by `read`/`mapfile`/`printf -v` or from such a value, a loop over one, or a positional parameter in a command that names the config dir; inherited variables (`$VENV/bin`) don't count, so a variable exported by your own shell profile that points into the config dir isn't seen. Past 1,024 words, numeric ranges collapse to one digit pattern and a word that still overflows is refused whatever it names; `patch` reading its target from the diff and output flags glued to others (`wget -qO-FILE`) aren't parsed. `/usr/bin/env python3 ...` and `env -C DIR ./install.sh` hide the command from the install rule, and a copy of `install.sh` run directly (no shell word) isn't caught; the scratch-install exception is off in a command that creates links or moves directories, but links made by a `git clone`/`checkout` aren't seen.
- **WebFetch domains (T1, not changed; accepted residual after round 3).** Allow rules have no effect in `bypassPermissions` and ask rules can't be scoped to one agent type (a `WebFetch` ask rule would prompt on every fetch of every agent). Which agents may fetch at all is set by their `tools:` lines. A guard URL policy keyed on agent type was weighed and not built: a docs-domain allowlist for the coder types would refuse legitimate research (issue trackers, blogs, mailing lists, vendor docs on their own domains), and a "long high-entropy query string" check both refuses normal URLs (commit SHAs, signed download URLs, search queries, tracking parameters) and misses exfiltration through path segments or many short requests. Not cheap and not false-positive-safe, so the boundary stays the tool lists, the web taint on memory writes and the no-push/forge-write hooks.
- **Taint gaps (round 4).** Files an agent reads are not links (above), and the main thread is a gap too: its web reads are not tracked as taint.
- **`SUPREME_AFTER_NINJA` checks order only (round 4).** Any finished ninja-coder run of the session, even a trivial one, unlocks the supreme-coder spawn; the requirement that ninja-coder failed rests on the planner, plan-reviewer, BlackCat and orchestrator prompts.
- **Session started directly in a temp dir (round 4).** A session whose project is a temp dir itself (`/tmp`) has no project dir: all of `/tmp` is scratch for the read-only agents there.
- **Live-sandbox checks still open (round 4).** See "Unverified live" below and README → Security model → Live checks.
- **Linux `.git/modules` (LOW).** On Linux/WSL2 the sandbox drops write-list entries with a mid-path wildcard, so the `.git/modules/**/hooks/**` and `.git/modules/**/config` denies protect submodule hooks and config only on macOS (the stack's platform). The plain `.git/hooks` and `.git/config` denies apply everywhere.
- **Unverified live** (the user's checks, README → Security model → Live checks): whether Claude Code's sandbox honours the absolute `__STACK_STATE__`, `__STACK_BACKUPS__` and `__STACK_CACHE__` paths in `denyRead`/`denyWrite` exactly as written (they follow the `__CLAUDE_DIR__` pattern already shipped); that a `denyWrite` entry wins inside a wider `allowWrite` entry (read from the docs' `/sandbox` Config tab, "Denied within allowed"); that settings `env` reaches MCP servers and hooks; that the `$CLAUDE_ENV_FILE` exports reach subagents' Bash; whether the osxkeychain helper answers inside the sandbox; that ask rules prompt under `bypassPermissions`; BlackCat's routing of supreme-coder plans.

## 8. Validation (2026-09-29)

| Check | Result |
|---|---|
| `/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test` | ok |
| `uv run tests/lint_agents.py` | ok |
| `uv run tests/redundancy_lint.py` | ok (2026-10-04): no long sentence in 3+ agent/skill files, no dangling `see`/`load`/`name`*/§ skill reference, no hook file outside settings.json or install.sh's staging, beyond `tests/redundancy_allowlist.json` (justified repeats and placeholders; `TODO:` entries are the baseline to fix; `--strict` lists stale entries) |
| `uv run --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/` | 2401 passed at the R4-2 session-env commit (2400 at the credential-store review commit before it, also from a snapshot under `/private/tmp`, where 118 had failed before R3-INFO; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)) |
| `bash tests/install_smoke.sh` | 244 passed, 0 failed at the R4-2 session-env commit (scratch HOME only; re-runs itself without a controlling terminal, so no install in it can wait on yours; includes a drifted config, dry-run, restore round trips, `--no-prune`, symlinked scope dirs with dir and file links, manifest traversal) |
| `jq empty dot-claude/settings.json` | ok |

## 9. Changelog

Entries name agents, knobs and files by their current names.

### 2026-10-04 (hooks on stack-python 3.13, launcher, precompiled bytecode)

- Every hook runs `/bin/sh <config>/bin/stack-hook [--fail-closed] <module>` on `<config>/bin/stack-python` (a link to uv's managed Python 3.13), through `hooks/stack_hook.py` with timestamp bytecode compiled at install; `/usr/bin/python3` is no longer a hook interpreter (§7, "Hook interpreter"). The installer links and smoke-tests the interpreter before it writes `settings.json`; a failure stops it with the old hooks in place. The guard's PreToolUse entries fail closed when the hook cannot start; `STACK_POLICY=off` lifts that except for `no-push`. A dry run no longer leaves an empty state dir behind (the guard's self-test probed it). Rerun `./install.sh` and restart Claude Code.

### 2026-10-04 (`install.sh --diff`; redundancy lint)

- `install.sh --diff` (`lib/stack_diff.py`): read-only repo-vs-install comparison (§7, "Repo vs install: `--diff`"); `tests/test_install_diff.py`. Nothing to rerun.
- `tests/redundancy_lint.py` with `tests/redundancy_allowlist.json` (§8): long sentences repeated in 3+ agent/skill files, dangling `see`/`load`/`name`*/§ skill references, hook files neither wired nor staged. Baseline `TODO:` entries: 5 repeats, 2 section refs (`self-hosting-ops` § systemd, `technical-writing` §10), `hooks/stack_hook.py`; `tests/test_redundancy.py` proves each check by mutation.

### 2026-10-04 (lazy skill listing)

- The user's decision: description cap 250, nine non-stack skills hidden, and skills loaded lazily with only a name for most. `skillListingMaxDescChars` 500 → 250; `skillOverrides` adds dataviz and `anthropic-skills:{deep-research,morning,import-memory,consolidate-memory,setup-claude,explain-usage,google-workspace,schedule}` as `user-invocable-only`, and 96 stack skills as `name-only` (all listed ones outside `LISTED_CORE`). Stack text no longer routes to dataviz or deep-research.
- Listing: stack 14,437 → 5,306 chars (prompt_budget; ≈ 4,813 → 1,769 tokens per spawn), mean per spawn 37,516 → 28,385; non-stack ~11,460 → ~5,310 in a desktop session (estimated from the synced manifest and the listing). Gates: skill_listing 0.478 → 0.175, per_spawn_mean 0.691 → 0.523 (measurement × 1.02).
- Lookup evaluation, offline (harness from the 2026-10-02 lookup study, 52 tasks; a name-only skill counts as found in one call only when the agent's own Skills line names it, so reach is a lower bound): one-call reach 100% → 98.7%, named 72.2% with the shipped Skills lines (88.6% with code-standards/review-protocol counted), unchanged. Usage in 360 subagent runs: review-protocol 77, claude-code-extensions 54, prompt-and-brief-design 24, secure-coding 7, shell-scripting 5, the rest ≤ 4; 51% of runs loaded no skill.
- What Claude Code supports (2026-10-04, Claude Code 2.1.287). Verified in the docs: the four `skillOverrides` states and their listing effect (settings-reference.md#skilloverrides: `"name-only"`: "Claude sees the skill by name without its description"); plugin skills ignore overrides (skills.md: "Plugin skills are not affected by `skillOverrides`"); `skillListingMaxDescChars` default 1536 and `skillListingBudgetFraction` default 0.01, over which "Claude Code keeps every skill's name but drops the descriptions of the least-used skills" (settings-reference.md); `SLASH_COMMAND_TOOL_CHAR_BUDGET` sets a fixed budget (skills.md); `disable-model-invocation: true` takes the description out of context (skills.md); `/context`'s Skills row is the listing after the budget (skills.md, v2.1.196+). Verified only in the 2.1.287 binary, undocumented: a name-only skill stays model-invocable and is listed as `- <name>`; an override is looked up by the full name, then by the short name unless another command holds it; `paths:` frontmatter keeps a skill out of the listing until a matching file under the working directory is touched (not used: tasks that create files never trigger it); the budget cut orders by a decayed per-user usage count (so not used as the lazy mechanism). Unverified: whether consolidate-memory, setup-claude, explain-usage and schedule under `anthropic-skills:` (not in `~/.claude/skills/synced`, provided by the desktop app) honour the override; if they arrive as plugin skills it is ignored.

### 2026-10-04 (spawn list is BlackCat's alone)

- Loosens one guard, by explicit user decision (relayed by the main thread, 2026-10-04): a main thread that is not BlackCat and has no `POLICY` row of its own (typeless `claude`, `claude --agent claude`, a host's or foreign agent) may now spawn every stack agent (`spawn_row`, `MAIN_THREAD` from `caller_is_main` when the event has no `agent_id`); since b199ab1 it got BlackCat's row, which leaves out db-engineer and localizer. Unchanged: BlackCat's own row, every typed main thread's row (`claude --agent main-coder` keeps main-coder's), subagent rows, an agent context of no known type (agent_id, no type: BlackCat's row), supreme-coder (only under `SUPREME_SPAWNERS` "main" and without a type; once per session), generic, built-in, foreign and copy child types (refused), depth, fan-out caps, K_sess, workflow typing, no-push. Tests: `test_rowless_main_thread_spawns_every_stack_agent`, `test_rows_unchanged_for_blackcat_typed_main_threads_and_subagents`; self-test probes.
### 2026-10-04 (the skip rule: existing command-line tools are never touched)

- `lib/devtools.sh` and `install.sh`: every command the installer would install is looked up from any source (PATH, the managers' own bin dirs, brew's list, the JDK/TeX/Playwright paths) and, when found, skipped with `skip <tool> (found: <path>, from <source>)`: never installed, upgraded, replaced or removed. A manager is skipped when a tool it provides is found. A found tool failing `--version` gets a WARN with the fix (ghcup's broken ormolu is no longer removed, hlint/ormolu no longer rebuilt over existing ones). magg and serial-mcp of another version are left alone with a WARN (no more `uv tool install --force` or cargo rebuild). Configuration (uv's pin, lfs filters, profile lines) stays idempotent. A summary line counts installed/skipped/failed. `lib/devtools.sh where NAME` reports where a tool is. §7 "Prerequisites and toolchains". Tests: `tests/test_install_devtools.py` (all present → zero install calls, broken present → WARN only, found off PATH, only missing installed); `tests/install_smoke.sh` serial-mcp cases follow the rule.

### 2026-10-04 (BlackCat only delegates)

- The user: BlackCat does no work, it only decides how to delegate (BlackCat only, never whatever agent runs on the main thread). Each layer now enforces it. **Tools line** (hard, hook-independent): blackcat.md and `BLACKCAT_TOOLS` drop Bash, Write and Edit; what is left is Agent(...), SendMessage, TaskStop, ListAgents, AskUserQuestion (+ Conductor's), ExitPlanMode, ToolSearch, Skill, Workflow, Cron*, ScheduleWakeup, RemoteTrigger, PushNotification, SendUserFile and Read. `tests/lint_agents.py` fails on Bash/Write/Edit/NotebookEdit there or on a missing delegation tool; the self-test fails on a work tool in `BLACKCAT_TOOLS`. **Guard**: `BLACKCAT_MAX_OWN_STEPS` defaults to 0, so blackcat-guard refuses a Bash/Write/Edit call that still reaches it (an SDK app's tool list, an `--agents` redefinition) with a reason naming whom to dispatch (main-coder for merges, tests, commits and bookkeeping, coder, explore, claude-code-engineer); new `BLACKCAT_MAX_READS=3` caps Read per prompt (ledger, a plan, one child's output file; the 4th read points at explore). Every `BLACKCAT_*` knob is a fixed guard (`stack_limits.FIXED_PREFIXES`). **Prompt**: "Doing it yourself" becomes "Delegate only"; the Decide rule keeps only greetings, setup questions and the ledger for BlackCat. **Rules**: "no spawn for work of a few tool calls" and the spawn-cost line exempt BlackCat. **Settings**: nothing; permission rules are session-wide (permissions.md), so a deny of Bash for BlackCat alone is not expressible and would also block every subagent.
- Consequence: BlackCat runs no command and edits no file, however small (git status, a test, a merge, a copy): each costs a spawn. Merges and tests go to main-coder (SendMessage to the one holding the work). A forked skill's agent would get no Bash (none ships forked; `test_no_shipped_skill_forks`). `/stack-doctor`, `/stack-tree` and the status line run from hooks and settings, not BlackCat's tools, and are unaffected; the ledger stays readable (Read). Any other agent started with `claude --agent <name>` (`claude --agent claude` for a plain session, `main-coder`, …) is not restricted: the restriction belongs to BlackCat only, through its own tools line and its own guard (blackcat.md's frontmatter hook runs only in a BlackCat session; the settings.json wiring returns at once unless `agent_type` is `blackcat`); `BLACKCAT_MAX_OWN_STEPS` > 0 alone changes nothing while the tools line lacks the tools. Rerun install.sh and restart Claude Code.

### 2026-10-03 (open-file limit before step 2; Lean group)
- `install.sh`, before step 2 installs anything: the open-file limit step (§7 "Open-file limit"). On a terminal it offers `/Library/LaunchDaemons/ulimit.max-files.plist` (launchd soft 65536, hard 524288; fixed template, `plutil -lint`), asks `[y/N]`, and only after y runs `sudo install -m 644 -o root -g wheel`, checks `root:wheel 644` with `stat`, `sudo launchctl bootout` (when loaded) and `bootstrap system`, and prints `launchctl limit maxfiles`; otherwise it prints the commands. Knob `STACK_INSTALL_MAXFILES=ask|0|1`. Then the run raises its own soft limit (`ulimit -Sn 65536`, else the highest accepted) for every tool it starts.
- `lib/devtools.sh`: group `STACK_INSTALL_LEAN` (on): elan from its official script (`-y --default-toolchain stable`, `--no-modify-path` under `--no-profile`), then the Mathlib project (`~/lean/stack_mathlib` by `lake +stable new … math`, `lake exe cache get`, `lake build`; a `LEAN_PROJECT_PATH` project is used as it is), the project only on a terminal or with `STACK_INSTALL_LEAN_MATHLIB=1`. Skipped while the open-file limit is below 65536. `stack-update-tools` adds `elan self update` and `elan update`. Tests: `tests/test_install_devtools.py` (shimmed sudo, launchctl, plutil, stat, sysctl and `ulimit`; a scratch-repo install run checks that the step precedes every install call).

### 2026-10-03 (installer sets up prerequisites and toolchains)
- `lib/devtools.sh all`, called from step 2: Homebrew, one brew batch per type (formulae, casks) for every missing item of the enabled groups, the upstream managers (uv + Python 3.14 pin, nvm + node 24 + pnpm, rustup, ghcup + hlint/ormolu, juliaup, coursier), the required check (uv, node), then pre-commit, Gradle 9.8.0, Playwright 1.63.0's Chromium and `git lfs install`. Group knobs `STACK_INSTALL_{DEPS,DEVTOOLS,UV,NODE,RUST,HASKELL,JULIA,SCALA,JAVA,LATEX,CXX,GO}` (on) and `STACK_INSTALL_{POSTGRES,MONGODB}` (off). New `bin/stack-update-tools`. Pins, routes and the dependency table: §7 "Prerequisites and toolchains". `lib/devtools.sh` joins the change-review diff (`SUPPLY_PATHS`); uv, node and the media tools moved there from install.sh. Tests: `tests/test_install_devtools.py`.

### 2026-10-03 (hand-back protocol, Phase 1: observe)

- `STACK_REPORT_FORMAT` default is now `observe` (§5, "Message protocol"): SubagentStop checks and records every spawned stack subagent's final reply (registry `report`, `reports/` copies, `usage/reports.jsonl`), PreToolUse(Agent) records the brief's size in the ledger. Nothing is output, warned or blocked; the prompt is unchanged. `compact` (one restate per run, a brief warning) exists but is not the default; the compact default, the reply-format prompts and the read gate are Phase 2, planned. Rollback: `STACK_REPORT_FORMAT=off`.
- `stack-tree --pending`, the registry `report` status and E flag in `stack-tree`; `stack_usage.py` maps `STATUS: failed` to status_code 1; `stack_sdk.parse_report` gains `eflag` and `failed`; `agent_guard.py --self-test` runs `report_self_test`.

### 2026-10-03 (session budget 1.92B, re-seed on install, auto-compact window 629K)

- `hard.session` (per-session hard context budget, whole tree): seed 666,000,000 → 1,920,000,000, repo ceiling 1,500,000,000 → 2,500,000,000, floor 300,000,000 unchanged (`dot-claude/hooks/stack_limits_seed.json`; the guard's built-in fallback and the doctor's seed check follow).
- `stack_limits.py seed` (run by install.sh): a variable still at its seed (status unset, no evidence, not frozen or held now, never rolled back) takes a changed shipped seed, unless the soft ≤ ratio × hard invariant would then move a learned or frozen partner; learned, frozen and held values are kept, and a re-seeded variable keeps learning. History records the move as `reseeded`. Schema-0 values imported with a value other than the seed are marked `migrated` and so never re-seeded.
- `autoCompactWindow` 900000 → 629000 in `dot-claude/settings.json` (the single source; Claude Code accepts 100000–1000000, capped at the model's window). The installer re-asserts it; `/stack-doctor` and the status line's bar follow it. It bounds one conversation's context, not the cumulative budgets: `hard.session` and `hard.prompt` count context tokens summed over every call of the tree.
- Tests: `tests/test_stack_limits.py` T15b–T15d, `tests/test_install_state.py::test_install_reseeds_unlearned_limits_and_keeps_learned_ones`, `tests/test_autocompact_window.py`.
- Rerun `./install.sh` from the main checkout and restart Claude Code. A window you saved with `/autocompact` (under `modelSettings` in your own settings) still wins over the stack's key for that model.

### 2026-10-03 (MCP allow rules for computer-use, lean, mobilebuild)

- Under Plan and acceptEdits, MCP tools without an allow rule prompted where `bypassPermissions` had run them, which stalled subagents and filled their context. The user's decision, "All except DB and Chrome (Recommended)": `dot-claude/settings.json` adds `mcp__computer-use`, `mcp__lean` and `mcp__mobilebuild` to `permissions.allow` (40 → 43; ask 21 and deny 97 unchanged). `mcp__mongodb`, `mcp__postgres` (database access) and `mcp__claude-in-chrome` (the user's logged-in browser) stay without a rule: they prompt, and are denied in headless runs. No shipped ask or deny rule names the three allowed servers. magg's `mongodb_*` and `postgres_*` stay allowed as before (read-only catalog flags, `tests/test_no_duplicates.py`).
- Installer: unchanged. The permissions merge keeps the user's rules and appends the shipped ones, so an upgrade adds the three allows and keeps a user's own ask or deny rule, which wins over allow. Smoke §4 checks it with a removed `mcp__lean` and a user `ask` rule on `mcp__mobilebuild`.
- Tests: `tests/test_permission_modes.py` pins the whole-server allow set (19 servers), asserts no allow or deny rule for mongodb, postgres or claude-in-chrome, no shipped ask or deny on an allowed server, and that every MCP server an agent's `tools:` names is decided.
- Rerun `./install.sh` from the main checkout and restart Claude Code.

### 2026-10-03 (Plan as the default mode, acceptEdits on the 45 writers, step cap 24)

- **Plan by default.** `dot-claude/settings.json` ships `permissions.defaultMode: "plan"`; the previous value was `"bypassPermissions"` (shipped since 2026-09-28). The user: "I want the default permissions to be Plan, it makes much more sense and I want it if the user changes permissions to pass them down chain to subagents". Docs facts (claude-code-guide's report on `code.claude.com/docs/en/permission-modes.md`, `settings.md`, `sub-agents.md`, fetched 2026-10-03; not re-fetched for this entry): `defaultMode` takes `default`, `acceptEdits`, `plan`, `auto`, `dontAsk` or `bypassPermissions`; user scope accepts all of them, and project and local settings ignore `auto` and `bypassPermissions`; the settings file loses to `--permission-mode`; the terminal default is `auto` from 2.1.283; an agent without `permissionMode` inherits the main mode; a parent in `bypassPermissions`, `acceptEdits` or `auto` beats the agent file, while with a parent in `default`, `dontAsk` or `plan` the file wins (except `bypassPermissions`); ExitPlanMode is removed from subagents not in plan, subagents in plan are read-only, and approving a plan switches the session's mode, which new subagents inherit.
- **Installer:** a scalar `permissions` key is no longer overwritten on every run. The stack's value is set while you have none or still hold the value shipped last time; a mode you chose is kept (`kept your permissions.defaultMode=…`). The manifest records the shipped scalars (`settings_permission_scalars`). For an older manifest the previous value is read from the recorded commit's `dot-claude/settings.json` (earlier installers overwrote the mode on every run, so that value was in place). An install still on the old shipped `bypassPermissions` moves to `plan` once, with a note on Shift+Tab, ExitPlanMode and how to set `bypassPermissions` again. When the recorded commit is not in the repository, nothing changes and the installer says why. Smoke §13c.
- **Agents:** 45 agent files carry `permissionMode: acceptEdits`: the 31 builders as before, plus orchestrator, designer, writer, researcher, doc-specialist, image-director, claude-code-engineer, cg-artist, motion-designer, data-scientist, mcp-broker, mathematician, browser-operator and vfx-td. The user: "most ssubagents must run in accept edits or else it will bloat context for them too and lag on resolution time", for subagent runs. Without a mode: blackcat and the 10 read-only agents (claude-code-guide, code-reviewer, explore, oracle, plan-reviewer, planner, proof-checker, scout, security-auditor, verifier). New lint rule (`tests/lint_agents.py` `permission_mode_problem`, `tests/test_permission_modes.py`): `acceptEdits` only with Write/Edit/NotebookEdit, `plan` only without; any other value fails. blackcat.md rule 5 now says builders edit even in Plan, so they go out only after approval (body length unchanged).
- **Launchers:** `bin/claude-ultracode` passes `--permission-mode plan` unless you pass `--permission-mode` or `--dangerously-skip-permissions`. This replaces "no mode flag in the launcher": the user wants `acceptEdits` only "when run as subagents, not when on main thread", and whether a main-thread agent's frontmatter mode applies is not documented. That the flag also beats the agent file is expected, not verified. `tests/test_ultracode_launcher.py`.
- **Probe:** `STACK_MODE_PROBE=1` logs the `permission_mode` hooks see (section 5, "Permission modes", has the procedure); settings.json wires PermissionRequest to the guard, which returns no decision. The guard also strips the Agent tool's `mode` input (deprecated and ignored in 2.1.287) from every spawn. A guard rule that denies edits to builder subagents while the main thread is in plan (`STACK_MODE_ENFORCE`) is a follow-up that waits for the probe; it is not built.
- **`BLACKCAT_MAX_STEPS` 12 → 24** (the user: "make it 24"); `BLACKCAT_MAX_DISPATCH` stays 8 and `BLACKCAT_MAX_OWN_STEPS` 4, so 24 − 4 ≥ 8 holds.
- Rerun `./install.sh` from the main checkout and restart Claude Code. To keep starting in `bypassPermissions`, set it in `~/.claude/settings.json` after the install (later runs keep it), or pass `--permission-mode bypassPermissions` for one session.

### 2026-10-03 (prompt budget base frozen)

- `tests/prompt_budget.py --check` compares with its base revision through git; in a clone without that commit (a fresh history, an export without `.git`) it skipped every ratio check. It now falls back to `tests/fixtures/prompt_budget_base.json`, the base's measurement frozen (totals, and per agent description, body, maxTurns and per spawn; the base agent no current agent matches is left out, as `check()` never compares it), so the ratios run there too. `tests/test_prompt_budget.py` checks the fixture against a live measurement when the commit is present and the fallback with a seeded violation. The collector upgrade tests in `tests/test_stack_usage.py` still skip without their commits (README, Contributing). Nothing to rerun.

### 2026-10-03 (Playwright MCP output dir created by the installer)

- install.sh now creates `~/.cache/claude-sandbox/playwright-mcp` (the rendered `--output-dir` of the Playwright entries; parents new to it get 0700, like the session-env hook's `~/.cache/claude-sandbox`, and the folder itself is set to 0700) after applying the files, when an installed agent or the magg catalog names it; `--dry-run` creates nothing. doctor.sh checks every path in an MCP entry's args and reported `[Binaries] ~/.cache/claude-sandbox/playwright-mcp missing` as a FAIL on a fresh install: the entry below assumed the server creates the folder on its first write, and doctor checks before any server has run. doctor's check stays. Tests: `tests/test_playwright_mcp.py` (the path install.sh builds matches the entries) and `tests/install_smoke.sh` §8 (created 0700 under a scratch HOME, doctor quiet about it, nothing under `--dry-run`). Rerun install.sh.

### 2026-10-03 (previous-name compatibility removed)

- The compatibility layer for supreme-coder's previous name is gone. install.sh's `RENAMED` (agent files) and `RENAMED_ENV` (settings knobs) keep only the senior-coder → main-coder and router → blackcat entries, so the mechanism and its smoke tests stay. `bin/claude-ultracode` answers to `claude-ninja`, `claude-supreme` and `claude-ultracode <agent>` only; install.sh no longer notes an old launcher link, and doctor.sh no longer warns about one, about a left-over agent file or about knobs under the previous prefix. The guard no longer adopts a lock or spawn marker written under the previous name, nor maps that spelling to supreme-coder.
- Usage rows recorded before the rename are not aliased. `stack_limits` and `stack_usage.read_rows` read them under the type they were recorded with, a type the stack no longer ships, so they feed no supreme-coder limit (`stack_limits.RENAMED_TYPES`/`renamed_type` and `stack_usage.RENAMED_TYPES` are removed). An env override or live.json state under the previous name no longer carries over, and `tests/derive_*.py` count such transcripts under their recorded type. The frozen fixture `tests/fixtures/sched/graph-4e2da3ce.json` names `dot-claude/agents/supreme-coder.md`.
- Upgrading straight from an install older than the rename: the previous agent file is still pruned as no longer shipped (the backup keeps it), and a shipped knob still at its default is retracted. A knob you tuned under the previous prefix stays in settings.json unread: set its `SUPREME_*` name. An old launcher link in `~/.local/bin` is no longer recognised: remove it. Rerun install.sh and restart Claude Code.

### 2026-10-03 (hero image, CC BY 4.0)

- Hero image replaced: the author's cat photograph edited with OpenAI GPT Image 2.5 Sunburst via Opper; images licensed CC BY 4.0. `lib/assets/` holds the unmodified model output (`blackcat-hero-original.png`, with its C2PA manifest), the resized hero, social preview and avatar, the CC BY 4.0 legal code and the provenance (prompts, settings, hashes); README's License section and NOTICE follow. `lib/assets/` is not installed: nothing to rerun.

### 2026-10-03 (install target: --config-dir, any clone, any user)

- `install.sh --config-dir PATH` (also `--config-dir=PATH`) and `--no-prompt`; precedence `--config-dir` > `CLAUDE_CONFIG_DIR` > `~/.claude`; a banner on every run; a `[y/N]` question on a terminal for a non-default or ambiguous target; unsafe and foreign targets refused (§7, "Install target"). Before, `CLAUDE_CONFIG_DIR` was used as given, unchecked (`CLAUDE_CONFIG_DIR=/` was accepted), and nothing said where the install went except one line in step 1. Runs without a terminal behave as before, apart from the new refusals. `--no-prompt` also makes a changed stack stop instead of asking on `/dev/tty`.
- The script follows a symlink to itself to find the clone (before, a link to `install.sh` in `~/bin` took `~/bin` as the repo). A bash login shell whose `~/.bash_profile` does not source `~/.bashrc` gets a note at step 11. `doctor.sh` warns when the folder it checks is not `~/.claude` and `CLAUDE_CONFIG_DIR` is unset.
- Author-specific paths removed from the tests and `tests/derive_thresholds.py` (the report's project column now strips any `-Users-<name>-` prefix). Intel Macs remain untested (README, Requirements).
- Tests: `tests/test_installer_config_dir.py`; `tests/install_smoke.sh` §19 (precedence, banner, refusals, the question with an injected answer and on a pty when one can be opened, a target and a clone with spaces, a symlinked clone and a symlink to `install.sh`); the §16 pty driver answers the target question first. Nothing to rerun for an existing `~/.claude` install.

### 2026-10-03 (Playwright MCP output out of the working tree)

- The Playwright MCP wrote auto-named output (screenshots and snapshots without a file name, console logs, traces) to `<cwd>/.playwright-mcp/`, so every session left that folder in the project's working tree: with no `--output-dir` (or `PLAYWRIGHT_MCP_OUTPUT_DIR`), 0.0.82 resolves `outputDir` to `path.join(cwd, ".playwright-mcp")` (tmpdir only when cwd is unwritable). The inline entries of browser-operator, frontend-engineer and verifier and the magg catalog entry now pass `--output-dir __HOME__/.cache/claude-sandbox/playwright-mcp` (an absolute path: the server does `path.resolve` with no `~` expansion; the installer renders `__HOME__`; the server creates the directory on first write) and `--file-paths absolute`, so a result names a path the Read tool takes instead of `../../.cache/...`. `~/.cache/claude-sandbox` is the sandbox's only writable cache (`sandbox.filesystem.allowWrite`), so sandboxed Bash can move or clear the files; the read gate does not gate it. Files given an explicit name still resolve against the working directory (`--output-dir` help text), which is why the agents and `browser-automation` keep naming `./.claude-work/<job>/...`. `--headless --isolated` unchanged; `.playwright-mcp/` added to `.gitignore`. Sources: `npx @playwright/mcp@0.0.82 --help` and its `coreBundle.js` (`outputDir()`, `PLAYWRIGHT_MCP_OUTPUT_DIR`), https://github.com/microsoft/playwright-mcp (README, options), read 2026-10-03. Test: `tests/test_playwright_mcp.py`. Rerun install.sh (the magg entry is updated because the manifest recorded the old one) and restart Claude Code; delete old `.playwright-mcp/` folders by hand.

### 2026-10-03 (legacy/be5b940 removed)

- The repo no longer ships `legacy/be5b940/` (old `CLAUDE.md`, `agents/senior-coder.md`, seven skills); it stays in the history from before publication (the 2026-10-03 commit "Remove legacy/be5b940; smoke tests take old-release files from tests/fixtures"; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)). install.sh keeps its generic `legacy/<version>/<rel>` recognition (`legacy_renders`, `template_copy`), which finds nothing while `legacy/` is absent, and the model-ID lint keeps its `legacy/` exception. Upgrade effect, only for an install whose files the manifest does not track (pre-manifest): an unedited untracked `CLAUDE.md` of that release (and a leftover `CLAUDE.md.new`) is now kept instead of moved to the backup, without the "kept" advice (its line similarity to today's rules, 0.385, is under `similar()`'s 0.4), and an untracked old skill file under `--no-prune` is kept with a `.new` render instead of refreshed (with pruning it is replaced and listed). Tracked files, and `senior-coder.md` (removed by name as renamed), behave as before. `tests/install_smoke.sh` takes its old-release files from `tests/fixtures/legacy-release/` and puts them under the scratch repo's `legacy/` only for the CLAUDE.md migration cases; a new case checks an unrecognised old `CLAUDE.md` is kept. Nothing to rerun.

### 2026-10-03 (top-tier coder agent renamed to supreme-coder)

- The top-tier coder agent is now supreme-coder: the agent file (`agents/supreme-coder.md`, `name: supreme-coder`), the guard's `POLICY` rows, fan-out, soft-limit and read-only tables, the limits seed (`turns.`, `soft.agent.`, `hard.agent.supreme-coder`), `sched_model.json`, `agent_effort.json`, every agent body, the rules, skills, docs and tests. Its knobs are `SUPREME_SPAWNERS`, `SUPREME_ONCE_PER_SESSION`, `SUPREME_AFTER_NINJA`, `SUPREME_PENDING_TTL_S`, `SUPREME_IDLE_S`, `SUPREME_LOCK_TTL_S` and the `STACK_{MAXTURNS,SOFTCTX,HARDCTX,SOFT_PROMPT_CTX}_SUPREME_CODER` overrides; the lock and markers in the hook state are `supreme-coder.lock`, `supreme-coder.spawned` and `supreme.mutex`; the launcher is `claude-supreme`. Rules file trimmed by 17 characters to stay inside `tests/prompt_budget.py` (rules <= 0.95 x base). The compatibility layer for the previous name that shipped with it is gone (entry "previous-name compatibility removed"). Rerun install.sh and restart Claude Code.

### 2026-10-03 (BlackCat does small jobs itself)

- BlackCat's `tools` and `BLACKCAT_TOOLS` gain Bash, Write and Edit and drop Grep and Glob (with Bash listed, Claude Code leaves them out on macOS/Linux; `find`/`grep` run through Bash, `tests/lint_agents.py` checks it). The prompt's Decide rule 3 now has a "yourself" class (a few tool calls, no skill or specialist judgement: a look, a small edit the user spelled out, one command or test, git inspection, committing its own edit, the delegation ledger), a stop-and-dispatch rule when such a job grows, and a "Doing it yourself" section (same guards as every agent, Git rules for its edits, AskUserQuestion before destructive steps). Specialist, long, parallel and review work is dispatched as before; the orchestrator gets dependent multi-specialist jobs. The 12-call and 8-dispatch caps count its own work.
- Not granted: WebFetch, WebSearch, Monitor (WebSocket source), NotebookEdit, LSP. The main thread holds browser-operator and the consent path (T1), so blackcat-guard also refuses a BlackCat Bash command that fetches the web (`blackcat_web_command`: the command unquoted and case-folded, split into segments; the command word after keywords and wrappers such as `timeout 10`, `env VAR=x`, `if`, `{` must not be an HTTP client, raw socket tool or `gh` with a forge read; inline HTTP code such as `urllib` or `fetch(` anywhere; a command over 20,000 chars is refused; linear time). Best effort: a script file, an alias, text assembled at run time and `sudo -u user curl` are not seen; git clone/fetch/pull stay allowed (repository files are read like local files); the sandbox network allowlist is the hard limit. The main thread is still not a web-taint node (T3 unchanged: what BlackCat relays into a spawn prompt is not marked). The self-test fails if `BLACKCAT_TOOLS` gains a web or MCP tool or the check misjudges its probe commands. Found by the code review of this change (MEDIUM, CWE-184: the first version reused `WEB_TAINT_CMD_RE`, which misses `timeout 10 curl`, `'curl'`, `CURL`, `{ curl; }`, `gh issue view`, inline urllib; LOW: only the first 20,000 chars were scanned).
- Guards unchanged and now proven for the main thread (`tests/test_blackcat_tools.py`): no-push denies a push or forge write from BlackCat's Bash (also with `STACK_POLICY=off`), its protect scan denies a Bash write to the installed stack; Write/Edit there hit the `Edit(/__CLAUDE_DIR__/...)` deny rules, which hold in `bypassPermissions` and for every file-editing tool (permission-modes.md, permissions.md), backed by the sandbox's denyWrite.
- A `context: fork` skill's agent inherits the main conversation's tools (sub-agents.md, "Available tools"), so under BlackCat it now gets Bash, Write and Edit (it was left with Read, ToolSearch and Skill: §1, bug 8). `/stack-doctor` stays on its UserPromptExpansion hook (sandboxed Bash still cannot read stack.env).
- The main thread stays free for dispatch and relays. (a) `BLACKCAT_MAX_OWN_STEPS=4`: own Read/Bash/Write/Edit calls per prompt; they also count against the 12 steps, never against the 8 dispatches, so even own work done first leaves a full burst of 8 (`test_blackcat_own_work_never_eats_the_dispatch_burst`). ToolSearch, AskUserQuestion and SendMessage are steps outside the sub-cap, so 4 own calls plus a question plus 8 dispatches is 13 and the 8th dispatch is refused: the prompt orders dispatches first. (b) `BLACKCAT_BASH_TIMEOUT_MS=120000`: a foreground BlackCat Bash call asking for a longer timeout, or relying on a raised `BASH_DEFAULT_TIMEOUT_MS`, is refused; `run_in_background: true` passes. (c) The prompt: all Agent calls in one message before its own calls (prompt-only: the hook cannot know dispatches will follow); builds, suites and installs go to `run_in_background` or a specialist, servers and watchers to a specialist. The 120 s dispatch window (`BLACKCAT_DISPATCH_WINDOW_S`) is a further reason to dispatch first: a second dispatch after a 2-minute command would fall outside it.
- What the harness does (docs, not live-tested): BlackCat's children always run in the background (`BLACKCAT_BACKGROUND`), so a foreground Bash on the main thread never stops them; their completion notifications reach the main thread "in a later turn" (sub-agents.md), and messages queued during tool calls are passed on "as soon as those tool calls finish" (interactive-mode.md), so a relay waits at most for the running foreground call, which the cap bounds at 120 s; at its timeout Claude Code moves a foreground command to the background instead of stopping it (tools-reference.md, "Foreground commands that move to the background"; the installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`). Unverified live: whether task notifications themselves (not typed messages) are delivered between tool calls of a turn or only at turn end, and whether Agent and Bash calls in one message start concurrently.
- doctor.sh probes blackcat-guard with a WebFetch call (a Bash probe is now allowed). Rerun install.sh and restart Claude Code.

### 2026-10-03 (/stack-tree)

- New read-only `bin/stack-tree` and user command `/stack-tree` (§5, "`stack-tree`"): a session's agent tree with each agent's commands as leaves, `--table` for a markdown table of every agent and tool call, `--static` for the designed hierarchy from the agent files. settings.json gets a third UserPromptExpansion group (matcher `stack-tree`, `"__PYTHON3__" -B "__CLAUDE_DIR__/bin/stack-tree" --hook`, timeout 30 s); install.sh stages `bin/stack-tree`, tracks it in the manifest and its `STACK_HOOK_RE` recognises the hook (`/bin/stack-tree" --hook`), so a re-install replaces it instead of keeping a second copy; doctor.sh checks the skill and the hook are wired. Tests: `tests/test_stack_tree.py`, `tests/test_override_agent.py::test_skills_are_user_only_and_wired`. Rerun install.sh and restart Claude Code.

### 2026-10-03 (/stack-doctor runs from a hook)

- `/stack-doctor` no longer forks claude-code-guide, which had no Bash under BlackCat (§1, bug 8). settings.json gets a second UserPromptExpansion group (matcher `stack-doctor`, `/bin/bash "__CLAUDE_DIR__/bin/doctor.sh" --hook`, timeout 180 s); `doctor.sh --hook` runs the full check outside the Bash sandbox, stops it after `STACK_DOCTOR_HOOK_BUDGET` seconds (default 150; stock macOS has no timeout(1), and Claude Code drops a timed-out hook's output) and exits 2 with the summary as the block reason; a run that did not reach its last line is a FAIL. install.sh's `STACK_HOOK_RE` recognises the hook (`/bin/doctor.sh" --hook`), so a re-install replaces it instead of keeping a second copy. `skills/stack-doctor` drops `context`, `agent`, `background` and `allowed-tools` and only tells the model the hook did not run. doctor.sh checks that the skill and the hook are wired. Tests: `tests/test_stack_doctor.py`, `tests/test_override_agent.py::test_skills_are_user_only_and_wired`. Rerun install.sh and restart Claude Code.

### 2026-10-03 (override runs are no longer learned from)

- Security audit of the first `/override-agent` commit (2026-10-03, "/agent-override and /agent-reset: per-session model override for delegated agent types"; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)), MEDIUM: an `/override-agent` run (e.g. scout on haiku) fed `soft.agent.scout`, `turns.scout`, the pool proposals and the scheduler refit that later sessions on scout's own model use, against the "this session only" scope. The collector now writes schema 3 rows to `usage/runs3.csv` with the segment's `model`; `stack_limits.py`, `stack_sched_refresh.py` and `stack budget` skip an agent row whose model is not its frontmatter one and count what they skipped (§5, "Session model overrides" and "Usage collector"). `runs*.csv` and `runs2*.csv` are read as before and never written again. Rerun install.sh; a session collected by the old code is read again from the start the next time its collector runs.
- Audit follow-up, MEDIUM: a collector started before the install kept the old code and wrote model-less rows for override runs typed after it. The next SessionStart or SubagentStart now stops a running older-schema collector (SIGTERM after the checks in §5, "Upgrade hand-off") and a successor reads the session again as schema 3 (tests: `test_upgrade_hands_off_from_an_older_collector` runs the real schema 2 collector from `6a736c6`; `test_handoff_signals_only_a_running_older_collector_of_this_session`; `test_a_successor_waits_for_the_lock_and_then_runs`). Its audit (MEDIUM): the stopped collector's mid-session session row stood as a whole session when the successor idled out; such stale session rows are now left out (`test_a_handoff_session_row_is_not_learned_as_a_whole_session`, `test_a_session_row_older_than_its_sessions_rows_is_not_learned`). The model IDs of the usage, limits and budget tests sit on module-level constant lines, which `tests/lint_agents.py` allows (`MODEL_ID_CONST`).

### 2026-10-03 (scheduler policy back to report)

- `STACK_SCHED_POLICY` defaults to `report` again (`stack_limits.SCHED_POLICY_DEFAULT`, `stack_sched.soft_values`); `fresh_fixer` is opt-in. A session keeps the policy of its snapshot. The default enters the regime hash, so sessions without the knob start a new regime: rows of the old one count as provisional evidence until the new regime has support.
- Tests: the default gives no advice, `fresh_fixer` advises, a mid-session env change does not reach the session; the MCP caps are pinned as fixed guards (T1b); support-rule boundaries (T6b).

### 2026-10-03 (/override-agent reset, FIFO fix)

- `/reset-agent` is now the subcommand `/override-agent reset <agent|all>` (beside `list`). The effort stays display-only (the user's decision: no agent variants).
- Security audit of the first `/override-agent` commit (LOW): a FIFO at the override state path hung the PreToolUse(Agent) hook until its timeout. The state and log files are now opened with `O_NONBLOCK` and refused unless `S_ISREG` (test: `test_a_fifo_at_the_state_path_does_not_hang_the_agent_hook`).

### 2026-10-03 (/override-agent, built-in effort table)

- The commands are now `/override-agent <agent> <model>`, `/override-agent list` and `/reset-agent <agent|all>`. The old `/agent-override` and `/agent-reset` and their effort argument are gone. The effort comes from `hooks/agent_effort.json` (initial defaults, rule v1), clamped to the model; it is recorded and shown, not applied (§5, "Session model overrides").
- Not built: enforcing the effort through per-(agent, model) agent definition variants, which install.sh would render statically (frontmatter `model` + `effort` from the table) with the guard resolving `<agent>@<model>` to `<agent>`. That means up to 220 more agent files in the listing every Agent caller sees. Every guard keyed by agent type would also need one alias function: spawn rows and allowlists, copy rules, READONLY_TYPES (no-push read-only Bash), fan-out by type, supreme-coder and browser spawners, web taint, MCP and turn caps, the limits snapshot (turns, hard and soft per type), read_gate and web_caps exemptions, ledger labels, stack_usage and the scheduler model, and lint_agents. A missed site there weakens a guard, and the result can only be checked in a live session. Decided later the same day: no agent variants (the user's decision; entry above).

### 2026-10-03 (session model overrides)

- `/agent-override <agent> <model|-> [<effort|->]`, `/agent-override list`, `/agent-reset <agent|all>` (renamed the same day; above): per-session model override for delegated agents, set only by the user's typed command (UserPromptExpansion hook), applied by the guard's Agent rewrite; effort recorded, not enforced (§5, "Session model overrides"). Rerun install.sh and restart Claude Code.

### 2026-10-03 (tools venv)

- install.sh step 2 also syncs `~/.claude/venvs/tools` from `requirements/tools.txt` (hash-locked, Python 3.13, macOS arm64 wheels, same 7-day cooldown as sci): pytest, numpy, pandas, httpx, mcp, pillow, neural-memory, i.e. every third-party import of `bin/`, `mcp/`, `hooks/stack_sched_refresh.py` and `tests/`. `claude-agent-sdk==0.2.163` (stack_sdk.py, one importorskip test) is left out until it clears the cooldown. Extras such as a future Bayesian stack go in their own lock (`requirements/README.md`). doctor.sh checks the venv's imports. Rerun install.sh.

### 2026-10-03 (read gate)

- New `hooks/read_gate.py` (PreToolUse `Read|Grep|Glob|Bash`): the first read of build output, dependency dirs, large data, media or binaries is refused with a cheaper alternative; the identical retry passes (§5, "Read gate"). One line in the global rules. Rerun install.sh.

### 2026-10-03 (auto-compact window 900K)

- `autoCompactWindow` 400000 → 900000 in `dot-claude/settings.json` (the single source): sessions on the 5.5 models' native 1M window compact at ~900K instead of 400K (Claude Code's default would be ~967K). The status line's bar, `/stack-doctor` and the installer's notes follow it. Rerun install.sh.

### 2026-10-02 (usage collector, scheduler model refresh)

- `hooks/stack_usage.py`: per-session background collector (SessionStart and SubagentStart `start`, SessionEnd `end`) writing segment rows to `usage/runs.csv`; `hooks/stack_sched_refresh.py` refits the active `sched_model.json` at the collector's exit. See section 5, "Usage collector and scheduler model refresh".
- `stack_sched.py`: prefers the active model.
- `agent_guard.py`: the three-day prune skips `usage/`.
- install.sh: installs `stack_usage.py`, `stack_sched.py`, `stack_sched_refresh.py`, `sched_model.json`, and `derive_sched_model.py` / `derive_thresholds.py` (from `tests/`) into `hooks/`. It treats `stack_usage.py` hook entries as the stack's when merging settings.json and warms the refit's uv cache.
- `/stack-doctor` gets one usage line.

### 2026-10-02 (soft token limits, maxTurns from data)

- `agent_guard.py`: soft token limits per agent segment and per human prompt (section 5, "Soft token limits"); `STACK_SOFT_LIMIT_SCALE`. Fix: a BlackCat tool call in a task notification's turn (its own prompt id, no UserPromptSubmit) restarted the hard prompt budget's window; it no longer does once a human prompt is on record.
- maxTurns: claude-code-engineer 150, coder 170, main-coder 350 (section 3); the verifier routes build work to a builder or to dispatches of about 90 tool calls or fewer.
- `tests/derive_thresholds.py`: the derivation, recomputable.
- Prompt budget: bodies gate 0.85 → 0.867 (the verifier line, measured × 1.02).

### 2026-10-02 (Q7: Agent SDK)

- `bin/stack_sdk.py` (installed, loaded by nothing; PEP 723, `claude-agent-sdk==0.2.163`): `options()` builds a plain `ClaudeAgentOptions` from the installed files (`setting_sources` user/project/local, the `claude_code` preset with `exclude_dynamic_sections`, `--agent`), `run()` returns the parsed report, cost, per-model and per-subagent usage and the ledger path; `parse_report()` reads the clean-finish line, the STATUS block and the JSON form.
- `STACK_REPORT_FORMAT=json` (above; the report line is `{"input","timestamp","agent","status","eflag","result","evidence","files","next"}`, `status` may be `failed`); the guard's SessionStart matcher is `startup|resume|clear|compact|fork` so the line survives `/clear` and compaction (no output when unset).
- Hooks under the SDK and `claude -p`: no TTY dependence (hooks always run without a controlling terminal); `tests/test_sdk_integration.py` runs them with SDK-shaped events and environment. Cache order checked: no hook writes a system prompt or rewrites earlier context; the SubagentStart line sits in the first user message and is kept.
- Reference: `skills/claude-code-extensions/references/agent-sdk.md`; cost probe for the user: `tests/sdk_smoke.py` (real API calls; not run in the build sandbox).

### 2026-09-29 (security rounds 3 and 4, supreme-coder plan flow)

The 2026-09-29 commits of security rounds 3 and 4, two for magg, one for the docs and the one that added this entry; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md).

- Without a terminal on stdin/stderr the supply question goes to `/dev/tty`; with no terminal at all a changed stack stops with exit 1 unless `--yes` (R4-1).
- A failed session-env hook exits 2 with a hook error, is recorded in `session-env.json`, and shows in the status line and `doctor.sh` (R4-2).
- Round-4 residuals recorded (taint gaps, `SUPREME_AFTER_NINJA` order only, a session started in `/tmp`, live checks open).

- Web taint follows reports, messages and spawn prompts (R3-T3-RELAY).
- Caches and the git credential reset moved to a SessionStart `CLAUDE_ENV_FILE` for sandboxed Bash only; `allowWrite` is `~/.cache/claude-sandbox`; an upgrade retracts the old settings (R3-CACHES, R3-GITENV).
- The supply diff covers everything shipped and asks on a terminal (`--yes`) (R3-SUPPLY).
- The guard state dir in the sandbox and `Edit` denies renders from `XDG_STATE_HOME` (R3-STATE).
- `--restore` keeps the current entry where it skips a link (R3-RESTORE-LINK); `--dry-run` refuses like the real run (R3-DRYRUN); file links inside a symlinked dir are kept (R3-WTL-INNER).
- `doctor.sh` reports GitHub credentials agents could use, by presence only (R3-N1-P2); least-privilege GitHub setup documented; `~/.config/git/credentials` denied.
- Read-only reviewers treat a project under a temp dir as the project (R3-INFO).
- magg `ros_*`, `qiskit_*`, `docspace_*` and the ten domain prefixes ask; every catalog prefix has exactly one allow or ask rule.
- supreme-coder only after a finished ninja-coder (`SUPREME_AFTER_NINJA`); a plan's supreme-coder step runs only after its ninja-coder step failed (planner, plan-reviewer, BlackCat, orchestrator prompts; section 4).
- N-MANAGED: managed settings pin the hook entries, not the hook's code, unless the root-owned copy is installed (documented).
- T1 URL policy weighed and not built (residual risks).

### 2026-09-29 (security round 2)

- Also: a link inside a symlinked scope dir is never written through; brace expansions past the cap never fail open.

- Installer: manifest paths are checked against the stack's scope, symlinked `agents/`, `skills/` (and the other scope dirs) are never pruned and need `--write-through-links` (new flag) to be written through, per-skill symlinks are replaced by the stack's skill again, whole scope dirs named in the manifest are refused, the backup root must be a private real directory, the work dir lives inside it, a config change during the run aborts before anything is written, restored links that leave the config dir need `--force`, the removal list names every hook entry, the LSP installs are pinned with `--ignore-scripts`, the MCP prefetch warms the servers' own cache, and your own MCP servers and hooks that run package runners on the sandbox cache are named (section 7).
- Settings: `sandbox.failIfUnavailable`, tool caches moved out of the sandbox's writable set, git credential helpers off, token env vars denied to sandboxed commands, `magg_enable_server`/duckdb/jupyter tools ask; duckdb runs in memory with extension autoload and config changes locked.
- Guard: protected-path checks expand `$HOME`, `$CLAUDE_CONFIG_DIR`, assigned variables, braces, globs, `cd` and `CDPATH` forms, and see output options (`curl -o`, `wget -O`, `sort -o`, `-o/--output` generally), `patch`, `sponge`, awk redirects and `git clone/init`; `$VAR/bin`-style project paths are no longer denied; `git -C <config dir>` tree-rewriting subcommands (now also bisect, submodule, merge-file, worktree add, archive/format-patch output) are denied; credential reads, forge writes over curl/wget/httpie and `install.sh`/`install_state.py` runs are denied; read-only reviewers may run syntax-only checks but not write-then-run scratch code; any MCP tool outside a non-web list marks the agent as web-tainted.

### 2026-09-29 (security and installer)

- Security findings C1–C9, T1–T3 and P3 fixed (guard, settings, MCP servers, installer); section 7 lists the residual risks.
- The installer stages, validates, backs up and then applies. It prunes by default (`--no-prune` opts out) and supports `--dry-run`, `--restore [DIR]` and `--print-managed-settings` (section 7).
- Plugin duplicates of synced skills and `mcp-server-dev` are disabled by default (`--keep-plugin-duplicates`).
- `skillListingBudgetFraction` 0.0156 (was 0.012): every skill is listed with its description, and the budget also holds plugin, bundled and claude.ai skills (stack ~31K + ~14.2K measured, plus 3.5%; rationale in `tests/prompt_budget.py` SKILL_BUDGET). Cost-only knob. `tests/lint_agents.py`, `doctor.sh` and the smoke test read it from `settings.json`.
- Read-only reviewers may also run `claude --version`, `claude mcp list/get`, `claude plugin list` and the audit scanners (`gitleaks`, `trufflehog`, `semgrep`, `osv-scanner`, `pip-audit`, `uv audit`, `npm audit`, `cargo audit`/`deny`, `trivy`).

### 2026-09-29

- Desktop hang fixed: BlackCat's children always run in the background, and the hook drops `run_in_background: false`.
- BlackCat always gives a visible reply and asks clarifying questions. The recommended main-thread effort is `medium`.
- Models: only Opus 5.5 and Sonnet 5.5 are used, with no Haiku.
  - supreme-coder moved from Fable to Opus 5.5.
  - doc-specialist moved to Sonnet 5.5.
- Effort recalibrated for 5.5:
  - lowered from `xhigh` to `high`: orchestrator, plan-reviewer, code-reviewer, quantum-engineer;
  - lowered from `high` to `medium`: motion-designer, cg-artist.
- maxTurns set per task type (section 3).
- Caps:
  - BlackCat: 8 dispatches, 12 steps, 120 s window;
  - running children per agent: orchestrator 32, main-coder and supreme-coder 6, ninja-coder 5, researcher 4, planner 8, everyone else 3;
  - `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 33.
- supreme-coder: only the orchestrator spawns it, once per session. BlackCat, main-coder, ninja-coder and the ML platform engineers return `NEXT: supreme-coder` instead of spawning it.
- The installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT`; `/stack-doctor` warns about them.
- Tests:
  - new: BlackCat foreground drop, shipped spawn defaults, supreme-coder orchestrator-only and once per session;
  - the mechanics tests pin their former caps as a baseline.

The full entry was in the Changelog section of the README as of the 2026-10-02 commit "Skills listed, not
name-only" (that README revision is not shipped; see the commit history in
[PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)).

## 10. Apps, connectors and MCP servers

Formerly `mcp_servers.md` (checked 26 and 27 September 2026; the engineering-domain servers on 2 October 2026).

Two kinds of tools work with your Max 20x plan: apps that run Claude Code itself under your login, which load your `~/.claude` stack, and connectors that give Claude a design, media or maths tool, each billed by that tool's own plan or free. Best picks first, then the full lists.

### Best pick per job

For coding, keep Claude Code with your stack in the terminal and add Conductor for parallel work; for everything else, add one connector per job from this table.

| Job | Best pick | Why | Next best |
| --- | --- | --- | --- |
| Coding, deep work | Claude Code in Ghostty or Terminal | Every feature of your stack, including `claude-ninja` and `claude-supreme` at ultracode | Claude Desktop, Code tab |
| Coding, many tasks at once | [Conductor](https://conductor.build) | Parallel chats in git worktrees; loads your `~/.claude` as is | Superset, Emdash, Claude Squad |
| UI and visual design | [Claude Design](https://claude.com/product/design) + [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | Design from a prompt, then read and write real Figma files | Penpot (free, open source), Canva |
| Vector graphics (SVG) | [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server) | Generates true vector images and vectorizes rasters | SVGator for animated SVG; Illustrator (Beta) MCP |
| Image generation | [ComfyUI](https://docs.comfy.org/agent-tools/mcp) locally + [fal](https://mcp.fal.ai/mcp) for hosted models | ComfyUI runs on your Mac at no cost; fal reaches hundreds of hosted models through one server | BFL FLUX, Replicate, Krea, Runway |
| Motion graphics | [Remotion Agent Skills](https://www.remotion.dev/docs/ai/skills) | Videos as React code that Claude Code writes, previews and renders | HyperFrames, Rive, Lottie Creator |
| Video editing | [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/) | Built-in MCP server: edit timelines by instruction | Descript |
| 3D | [MCP for Blender](https://github.com/ahujasid/blender-mcp) | Drives Blender through its Python API | Spline, Blender Lab's official server |
| Diagrams | [draw.io](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/) plugin | Free; writes `.drawio` files you can edit | Excalidraw, Mermaid |
| Maths | [Wolfram](https://claude.com/marketplace/connectors-plugins) connector | Already in your stack, free: exact computation and curated data | Lean tools, math-olympiad skills |
| Papers | alphaXiv connector | Search and full text of arXiv | arxiv-mcp-server, Elicit |

### Coding apps that run Claude Code on your plan

Every row works with your Claude login, no API key; rows marked Yes run Claude Code with your user settings, so your whole stack loads (BlackCat, its agents and skills, hooks, MCP servers). In those, pick Sonnet 5.5 and low effort for BlackCat chats.

| App | What it is | Your stack |
| --- | --- | --- |
| [Claude Code](https://code.claude.com/docs/en/overview) CLI | The reference, in any terminal | Yes, everything |
| Claude Desktop, Code tab | Local sessions with diff view and preview | Yes; add the background-model variable in its Local environment |
| Claude Code on the web and mobile | Cloud sessions on your GitHub repos | No: the repo's `.claude/` only |
| [VS Code extension](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) | Also runs in Cursor, Windsurf and Kiro | Yes |
| JetBrains plugin | Your `claude` in the IDE terminal, with IDE diffs | Yes |
| Xcode 26.3 or later | Xcode's Claude Agent, signed in with your Claude account | No |
| [claude-code-action](https://github.com/anthropics/claude-code-action) | GitHub Actions; `claude setup-token` gives the OAuth token | Repo's `.claude/` only |
| Claude in Slack | Hands a thread's coding task to a cloud session | No |
| Claude for Excel, PowerPoint, Word | Office add-ins; Outlook in beta | No |
| [Conductor](https://conductor.build) | Parallel chats in git worktrees, diff review | Yes |
| [T3 Code](https://github.com/pingdotgg/t3code) | Open-source GUI for Claude Code and Codex | Yes |
| [Nimbalyst](https://github.com/nimbalyst/nimbalyst) | Visual workspace, successor of Crystal | Yes; its effort control overrides every agent's effort |
| [Sculptor](https://github.com/imbue-ai/sculptor) | Imbue's app; runs Claude Code sandboxed with auto-approved tools | Yes; swaps in its own question and plan tools |
| [Superset](https://github.com/superset-sh/superset) | Many agents in worktrees, terminal-first | Yes |
| [Emdash](https://github.com/generalaction/emdash) | Parallel agents in worktrees | Yes |
| [Vibe Kanban](https://github.com/BloopAI/vibe-kanban) | Kanban board; each card runs an agent | Yes |
| [Claude Squad](https://github.com/smtg-ai/claude-squad) | tmux manager for many sessions | Yes |
| [cmux](https://github.com/manaflow-ai/cmux) | macOS terminal built for agents: tabs, notifications | Yes |
| [Jean](https://github.com/coollabsio/jean) | Projects, worktrees and sessions across agent CLIs | Yes |
| [Maestro](https://github.com/pedramamini/Maestro) | Agent orchestration desktop app | Yes |
| [CCManager](https://github.com/kbwo/ccmanager) | Session manager across worktrees | Yes |
| [Vibeyard](https://github.com/elirantutia/vibeyard) | IDE for coding agents; several logins side by side | Yes |
| [Cate](https://github.com/0-AI-UG/cate) | Zoomable canvas of editor, terminal and browser panels | Yes, in its terminals |
| [Warp](https://www.warp.dev) | Terminal with agent management | Yes |
| [Zed](https://zed.dev) | Claude Agent through the ACP adapter | Yes; a few slash commands hidden |
| Emacs: [agent-shell](https://github.com/xenodium/agent-shell), [claude-code-ide.el](https://github.com/manzaltu/claude-code-ide.el) | Claude Code inside Emacs | Yes |
| Neovim: [claudecode.nvim](https://github.com/coder/claudecode.nvim), [CodeCompanion](https://github.com/olimorris/codecompanion.nvim) | Claude Code inside Neovim | Yes |
| [Claudian](https://github.com/YishenTu/claudian) | Claude Code in an Obsidian vault | Yes |
| [CloudCLI](https://github.com/siteboon/claudecodeui) | Web and phone UI for Claude Code on your Mac | Yes |
| [Happy](https://github.com/slopus/happy), [HAPI](https://github.com/tiann/hapi) | Phone apps that drive Claude Code on your Mac | Yes |
| [AionUi](https://github.com/iOfficeAI/AionUi) | Desktop GUI for CLI agents | Yes, until you enable an AionUi MCP server |
| [Claude Threads](https://github.com/anneschuth/claude-threads) | Claude Code sessions in Slack or Mattermost threads | Yes |
| [Cline](https://github.com/cline/cline) | VS Code agent with a Claude Code provider | Partly: Cline drives, `claude` answers |
| [Goose](https://github.com/block/goose) | Block's agent, through its Claude ACP provider | Partly |

The Claude app itself (web, desktop, phone) adds chat, research, artifacts and Claude Design on the same plan; it runs its own agent, not your `~/.claude`.

### Design and graphics

Claude Design covers most visual work inside your plan; connect Figma or Penpot when the result must live in a design file.

| Tool | What Claude does with it | Connect | Cost |
| --- | --- | --- | --- |
| [Claude Design](https://claude.com/product/design) | Screens, flows, posters and prototypes from a prompt, exported as PDF or image | Built into Claude | Your plan |
| [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/) | Reads design context for code, and writes native frames and components to the canvas | Remote: `https://mcp.figma.com/mcp` | Starter seats: 20 calls a month; Dev or Full seats: 200 a day; canvas writes aren't rate-limited |
| [Penpot](https://help.penpot.app/mcp/) | The same for Penpot's open-source design files | `npx @penpot/mcp@stable` | Free |
| Adobe connector | Edits and combines images, documents and designs with Adobe tools | Remote: `https://adobe-creativity.adobe.io/mcp` | Adobe account |
| [Illustrator (Beta)](https://helpx.adobe.com/in/illustrator/desktop/connect-with-other-apps-and-tools/about-using-ai-tools-with-illustrator.html) | Its built-in MCP server reads, creates and exports artwork | Your stack's designer agent drives it through illustrator-mcp-server; Adobe's own server is in the Illustrator beta | Creative Cloud |
| Canva | Creates, edits and exports Canva designs | Remote: `https://mcp.canva.com/mcp` | Canva free or Pro |
| [Affinity](https://www.affinity.studio) | Automates repetitive work in the Affinity app | Desktop extension from the connector directory | App is free |
| Sketch | Explores and organizes your Sketch documents | Local server inside the Sketch app | Sketch plan |
| Framer | Builds and edits Framer sites through its External Agent connection; no separate MCP needed | Framer's agent setup | Framer account |
| v0 | Generates full-stack web apps | Remote: `https://v0.app/api/mcp` | v0 account |
| Brandfetch, Frontify | Your brand's logos, colours and guidelines, so output stays on brand | Remote connectors | An account with each |
| Unsplash, Shutterstock | Stock photos to place in layouts | Remote connectors | Unsplash free; Shutterstock licence |
| Mobbin | Real app screens as UI references | Remote: `https://api.mobbin.com/mcp` | Mobbin account |

Figma's remote server also works in Claude Desktop; the connector directory lists the rest with one-click setup for the Claude app.

### Vector graphics and SVG

Recraft is the hosted generator that returns real vector files; for icons, logos, charts and diagrams, Claude writes clean SVG itself.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server) | Raster or vector images from a prompt, vectorizing rasters, reusable styles | `claude mcp add --transport http recraft https://mcp.recraft.ai/mcp`, then `/mcp` to sign in | Recraft credits, same prices as its web app |
| [SVGator](https://www.svgator.com/help/svgator-mcp/connect-svgator-to-your-ai-assistant) | Animated SVG from your SVGator projects | `claude mcp add --transport http svgator https://mcp.svgator.com/mcp` | SVGator account |
| Illustrator (Beta) | Vector artwork created and exported in Illustrator | Your stack's designer agent, or the beta's built-in server | Creative Cloud |
| Figma, Penpot | Vector frames and components inside design files | See Design and graphics | See above |
| Claude, no tool | Hand-written SVG; in your stack the designer agent with the brand-identity, typography and color-management skills | Nothing to add | Your plan |
| Inkscape | Conversions such as SVG to PDF or PNG from its command line | No official MCP; Claude runs the CLI | Free |

### Image generation

Keep the Opper server your stack already has, add ComfyUI for free local generation, and add fal or FLUX for the strongest hosted models. All of these bill outside your Claude plan except ComfyUI on your own Mac.

| Tool | Models and use | Connect | Cost |
| --- | --- | --- | --- |
| Opper (in your stack) | Many providers' image models behind one key: generate, edit, upload references | Set `OPPER_API_KEY` in `~/.claude/stack.env` | Opper credits |
| [ComfyUI](https://docs.comfy.org/agent-tools/mcp) | Images, video, audio and 3D from your own workflows, models and custom nodes | Local: [comfy-mcp](https://github.com/Comfy-Org/comfy-mcp). Cloud: `/plugin marketplace add Comfy-Org/comfy-skills`, then `/plugin install comfy-cloud@comfy-skills` | Local free (partner models such as FLUX use credits); Cloud needs a Comfy Cloud plan |
| [fal](https://mcp.fal.ai/mcp) | Hundreds of hosted image and video models | `claude mcp add --transport http fal-ai https://mcp.fal.ai/mcp --header "Authorization: Bearer $FAL_KEY"` | Pay per use |
| [BFL FLUX](https://docs.bfl.ml/api_integration/mcp_integration) | FLUX images and video: generate, edit, vary, reuse results | `claude mcp add --transport http FLUX https://mcp.bfl.ai`; signs in on first use | BFL credits |
| [Replicate](https://replicate.com/docs/reference/mcp) | Any public model on Replicate | Remote `https://mcp.replicate.com`; web sign-in with your API token | Pay per use |
| [Krea](https://www.krea.ai/docs/developers/mcp) | Krea's image and video models | Remote `https://api.krea.ai/mcp`, sign in with your Krea account | Krea compute units |
| [Runway](https://runway.com/mcp) | Images and video with Gen-4.5, Seedance 2.5, Kling 3.0 and Veo 3.1, as your plan allows | Remote connector, [setup](https://help.runwayml.com/hc/en-us/articles/51931843164691-Connecting-to-Runway-MCP) | Runway credits |
| Google Imagen, Veo | Google's image and video models through Vertex AI | MCP servers in the `experiments/` folder of [vertex-ai-creative-studio](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio) | Google Cloud billing |

OpenAI's image models, Ideogram, Stability and Midjourney have no official MCP server; for the ones with an API, Claude calls it from a script, after downscaling any input image.

### Motion graphics, video and audio

For motion made in code, Remotion's skills are the best fit for Claude Code; for motion made in an editor, your stack's motion-designer agent already drives After Effects and Premiere Pro once you run `./install.sh --with-adobe`.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [Remotion Agent Skills](https://www.remotion.dev/docs/ai/skills) | Videos as React code: create, preview in Studio, render | `npx remotion skills add` in a Remotion project; the old hosted Remotion MCP is deprecated | Free for individuals and small teams; companies need a licence |
| After Effects, Premiere Pro (in your stack) | Comps, layers, keyframes, expressions; edits, sequences, exports | `./install.sh --with-adobe` | Creative Cloud |
| [HyperFrames](https://hyperframes.heygen.com) by HeyGen | Animated slides and motion graphics written in HTML, rendered in the cloud | Remote: `https://mcp.heygen.com/mcp/hyperframes` | HeyGen account |
| [Rive](https://rive.app/docs/editor/ai/mcp) | Artboards, state machines, view models and shapes for interactive animation | MCP in the Rive desktop editor (macOS, Windows) | Rive account |
| [Lottie Creator](https://docs.lottiefiles.com/en/creator/13_ai-tools/lottie-creator-mcp) | Builds and edits Lottie animations layer by layer | Local bridge to LottieFiles Creator | LottieFiles account |
| Moda | Editable decks, ads, social posts and motion graphics | Remote: `https://agents.moda.app/mcp` | Moda account |
| [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/) | Controls the edit by instruction, released 8 Sep 2026 | Built-in MCP server | 21.1 moved Python scripting to Studio ($295): check your edition |
| Descript | Imports, edits or creates video from prompts | Remote: `https://api.descript.com/v2/mcp/claude` | Descript account |
| Riverside, Tella | Edit, clip and publish recordings and podcasts | Remote connectors | Account with each |
| Splice | Search sounds and build stacks for a soundtrack | Remote: `https://mcp.splice.com/mcp` | Splice account |
| Manim, ffmpeg | Maths animation and any conversion, cut or encode | Nothing: Claude writes the code; your motion-graphics and media-ffmpeg skills cover them | Free |

### 3D and CAD

Blender through MCP for Blender is the most capable free route; Spline suits web 3D, and Fusion covers CAD.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [MCP for Blender](https://github.com/ahujasid/blender-mcp) | Creates and modifies objects and materials, runs Python in Blender, pulls Poly Haven and Sketchfab assets, generates models with Hyper3D Rodin | `uvx blender-mcp install-addon`, enable the add-on, then `claude mcp add --scope user blender -- uvx blender-mcp` | Free (community project) |
| Blender Lab's server | Blender's Python API and documentation through natural language | Desktop extension in the [connector directory](https://claude.com/marketplace/connectors-plugins) | Free |
| [Spline](https://docs.spline.design/generate/spline-mcp-server) | Builds and edits 3D scenes and Hana designs, generates 3D models and images | Built into the Spline desktop app (macOS, Windows) | Spline account |
| Autodesk Fusion | Creates, modifies and inspects CAD geometry | Desktop extension in the connector directory | Fusion licence |
| three.js | 3D on the web, written by Claude directly | Nothing to add | Free |
| [houdini-mcp](https://github.com/kleer001/houdini-mcp) | Drives Houdini (nodes, sims, PDG, USD/Solaris, renders) through a Houdini-side plugin over local TCP; starts headless hython when no GUI runs | Optional, not enabled in your stack: its bootstrap installs a plugin and a `pythonrc.py` hook into your Houdini preferences; then `claude mcp add --scope user houdini -- uv --directory <repo> run python houdini_mcp_server.py` and `mcp__houdini` on vfx-td's tools line | Free (MIT) |

### Diagrams and whiteboards

For diagrams that live in a repository, Mermaid and draw.io files cost nothing; team whiteboards need the whiteboard's own connector.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| [draw.io](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/) | Editable `.drawio` diagrams, images or share links | `/plugin marketplace add jgraph/drawio-mcp`, then install its `drawio` plugin; or `npx @drawio/mcp` | Free |
| Mermaid, Graphviz, D2 | Diagrams as code in Markdown and docs | Nothing: your diagrams-as-code skill writes and renders them | Free |
| Excalidraw | Hand-drawn style sketches | Claude writes `.excalidraw` files; your diagrams-as-code skill covers the format | Free |
| tldraw | Sketch and diagram together on a canvas | Remote connector for the Claude app and Desktop | Free |
| Lucid | Lucidchart diagrams and docs | Remote: `https://mcp.lucid.app/mcp` | Lucid plan |
| Whimsical | Flowcharts, mind maps, wireframes | Remote: `https://mcp.whimsical.com/mcp` | Whimsical account |
| Eraser | Architecture diagrams and design docs | Remote: `https://app.eraser.io/api/mcp` | Eraser account |
| Miro | Boards shared with your team | Miro's connector | Miro plan |

### Maths and research

Your stack's mathematician agent (Opus 5.5 at xhigh) with the formal-methods, latex-typesetting and literature-review skills handles proofs and write-ups, the proof-checker agent referees them and checks Lean proofs; Wolfram adds exact computation.

| Tool | Use | Connect | Cost |
| --- | --- | --- | --- |
| Wolfram | Exact symbolic and numeric computation, curated data | Already in your stack for the mathematician: `https://agenttools.wolfram.com/mcp` | Free, no key |
| math-olympiad skills | Anthropic's competition-maths skills | `./install.sh --with-extra-plugins` | Free |
| Lean 4 and Mathlib | Machine-checked proofs | In your stack: proof-checker runs `lean-lsp-mcp` itself and mcp-broker can mount the catalog copy; you install elan and a built Mathlib Lake project and set `LEAN_PROJECT_PATH` in stack.env; LeanExplore searches Mathlib | Free |
| [arxiv-mcp-server](https://github.com/blazickjp/arxiv-mcp-server) | Search, download and read arXiv papers | In your stack's catalog as `arxiv` | Free |
| alphaXiv | Search and full text of arXiv papers | Remote: `https://api.alphaxiv.org/mcp/v1` | Free |
| Elicit | Search and analyse scientific papers | Remote: `https://elicit.com/api/mcp` | Elicit plan |
| Manim | Maths animations | Nothing: Claude writes the scenes | Free |

### On demand and automatic

Each server loads automatically when an agent's work needs it and on request otherwise, and costs nothing while idle. An inline server starts and stops with its one agent. A catalog server stays unmounted until an agent's one-line pointer ("cluster state → mcp-broker mounts `kubernetes`") or your request sends mcp-broker to it. Nothing new went into user scope. Plugins are session-wide, never per agent; skills are listed with a description and loaded by name. The full matrix with idle costs is in §5, "On demand and automatic".

### Engineering domains

Servers for the database, mobile, game, embedded, HPC, bio/chem, cloud and finance agents, vetted on 2 Oct 2026 (licence, last release, flags, telemetry). In your stack they run either inside one agent (inline) or through mcp-broker's catalog, where every call asks you first.

| Tool | Use | In your stack | Cost |
| --- | --- | --- | --- |
| [postgres-mcp](https://github.com/crystaldba/postgres-mcp) 0.3.0 | Schema, read-only SQL, EXPLAIN, index advice | Inline in db-engineer, `--access-mode=restricted`; `DATABASE_URI` in stack.env | Free |
| [mongodb-mcp-server](https://github.com/mongodb-js/mongodb-mcp-server) 3.0.5 | find, aggregate, explain, indexes | Inline in db-engineer, `--readOnly`, telemetry off; `MDB_MCP_CONNECTION_STRING` | Free |
| [MobileBuildMCP](https://github.com/getsentry/MobileBuildMCP) 2.7.1 (was XcodeBuildMCP) | Xcode builds, tests, simulators | Inline in mobile-engineer (macOS), Sentry telemetry off | Free |
| [mobile-mcp](https://github.com/mobile-next/mobile-mcp) 1.0.8 | iOS simulator and Android emulator UI: screenshots, taps, installs | Catalog `mobile` (no read-only mode; telemetry off) | Free |
| [android-mcp](https://github.com/us-all/android-mcp-server) 1.14.4 | Android over adb, read-only by default | Catalog `android` | Free |
| [godot-mcp](https://github.com/Coding-Solo/godot-mcp) 0.1.1 | Run Godot projects, edit scenes, read debug output | Catalog `godot`; `GODOT_PATH` | Free |
| [biomcp](https://github.com/genomoncology/biomcp) 0.9.1 | PubMed, trials, variants, genes, drugs (public APIs) | Catalog `biomcp`; optional `NCBI_API_KEY` | Free |
| [pubchem-mcp-server](https://github.com/cyanheads/pubchem-mcp-server) 0.6.5 | PubChem compounds, read-only | Catalog `pubchem` | Free |
| [kubernetes-mcp-server](https://github.com/containers/kubernetes-mcp-server) 0.0.67 | Pods, logs, events through your kubeconfig | Catalog `kubernetes`: read-only, Secrets denied (`magg/k8s-mcp.toml`) | Free |
| [mcp-grafana](https://github.com/grafana/mcp-grafana) 2.0.0 | Dashboards, datasources, alerts | Catalog `grafana`, `--disable-write`, usage stats off; `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Free |
| [sec-edgar-mcp](https://github.com/stefanoamorelli/sec-edgar-mcp) 1.1.0 | SEC filings and XBRL financials (AGPL-3.0) | Catalog `sec-edgar`; `SEC_EDGAR_USER_AGENT` | Free |
| [serial-mcp](https://github.com/qarnet/serial-mcp) 0.9.3 | Serial consoles of dev boards, port allowlist | Catalog `serial`; install.sh builds it with cargo (`--locked`) when cargo is present | Free |
| [gis-mcp](https://github.com/mahdin75/gis-mcp) 0.15.0 | Geometry, CRS, vector and raster operations | Catalog `gis` | Free |

Documented, not installed (heavy, an app plugin, cloud credentials or hardware writes): [unity-mcp](https://github.com/CoplayDev/unity-mcp) (Unity Editor package; set `DISABLE_TELEMETRY`), [Unreal_mcp](https://github.com/ChiR24/Unreal_mcp) (C++ editor plugin), AWS [aws-api-mcp-server](https://github.com/awslabs/mcp) (`READ_OPERATIONS_ONLY=true`, telemetry off), Azure (`npx -y @azure/mcp@2.0.5 server start --read-only`, `AZURE_MCP_COLLECT_TELEMETRY=false`), [gcloud-mcp](https://github.com/googleapis/gcloud-mcp) 0.5.3 (no read-only flag), [Alpha Vantage](https://github.com/alphavantage/alpha_vantage_mcp) (API key passed on the command line), [KiCAD-MCP-Server](https://github.com/mixelpixx/KiCAD-MCP-Server) v2.8.2 (built from git), [embedded-debugger-mcp](https://github.com/Adancurusul/embedded-debugger-mcp) v0.3.0 (writes flash), [slurm-mcp-server](https://github.com/charlie-z-work/slurm-mcp-server) 2.0.1 (submits jobs over SSH), [lara-mcp](https://github.com/translated/lara-mcp) 2.0.0 (cloud translation memory), [houdini-mcp](https://github.com/kleer001/houdini-mcp) (see 3D), gopls's built-in `gopls mcp` (experimental; the gopls LSP plugin already gives go-engineer code intelligence).

Rejected: lamaalrajih/kicad-mcp (unmaintained since 2025-10), qgis_mcp (no licence), the audio servers whisper-mcp, local-stt-mcp and mcp-music-analysis (unmaintained), runreal/unreal-mcp (unmaintained), tandemai mcp-rdkit (repository gone), Flux159 mcp-server-kubernetes (its non-destructive mode still writes), unlicensed SLURM servers.

### Connecting a tool, and the 1920 px image limit

A new connector takes one command, but your stack's agents see it only once it is on their tool list.

1. Add it for every project: `claude mcp add --transport http --scope user recraft https://mcp.recraft.ai/mcp`; for a local server, `claude mcp add --scope user <name> -- npx -y <package>`. Then run `/mcp` once to sign in.
2. Give it to an agent: add `mcp__recraft` to the `tools:` line of that agent in the repo (`dot-claude/agents/image-director.md` for image tools, `designer.md` for design tools, `motion-designer.md` for motion tools) and rerun `./install.sh`. Only agents that name a server can use it.
3. For a one-off, ask BlackCat to have mcp-broker use it, or start `claude --agent claude`, a plain session that sees every tool.
4. In the Claude app and Desktop chat, add connectors under Customize, then Connectors.

Tool schemas load only when a tool is used, so extra connectors cost almost no context.

The image limit, as installed:

- Images agents read (files, screenshots, images returned by any MCP tool) reach the model at 1919 px or less on the longest side.
- Local images passed to MCP upload or image tools (image, reference, mask and file parameters) are swapped for downscaled copies in `~/.cache/claude-agent-stack/images`; originals stay untouched.
- For curl, scripts and SDK calls, the rules make agents downscale a copy first: `sips -Z 1919 in.png --out out.png`.
- Images you paste into a chat are only capped by Claude Code's own 2000 px limit: hooks can't change a prompt.
- Generated deliverables keep their full resolution. `STACK_IMAGE_MAX_PX` changes the limit; `0` turns it off.

### Subscription rules, and what to avoid

Today every app in the coding table draws from your plan's normal usage limits, because each one runs Anthropic's own Claude Code or Agent SDK under your login.

- Anthropic announced a separate monthly credit for Agent SDK, `claude -p` and third-party app use (from $20 on Pro), then paused it on 15 June 2026: "For now, nothing has changed." It promises notice before any change ([support article](https://support.claude.com/en/articles/15036540)). If it returns, apps built on the SDK (Conductor, Zed, Nimbalyst, Sculptor, AionUi) would likely move to that credit; the terminal would not.
- Apps may not offer their own claude.ai login unless Anthropic approved them ([Agent SDK docs](https://code.claude.com/docs/en/agent-sdk/overview)).

| Avoid | Why | Instead |
| --- | --- | --- |
| [Craft Agents](https://github.com/lukilabs/craft-agents-oss) | Ships its own Claude sign-in | Any app in the coding table |
| [OpenCode](https://github.com/sst/opencode) | Can't use your Claude plan; needs an API key | Claude Code, or OpenCode with an API key |
| JetBrains AI's Claude Agent | Billed through JetBrains AI, not your plan | The Claude Code JetBrains plugin |
| Claude Tag, Code Review | Team and Enterprise plans only | Claude Code with your stack's code-reviewer agent |

### Sources

Checked 26 and 27 September 2026. Connector URLs without a link come from Anthropic's connector directory.

- Anthropic: [connector directory](https://claude.com/marketplace/connectors-plugins), [Claude Design](https://claude.com/product/design), [Agent SDK with your plan](https://support.claude.com/en/articles/15036540), [Agent SDK overview](https://code.claude.com/docs/en/agent-sdk/overview), [Claude Code MCP](https://code.claude.com/docs/en/mcp)
- Coding apps: [Vibeyard](https://github.com/elirantutia/vibeyard), [Jean](https://github.com/coollabsio/jean), [Maestro](https://github.com/pedramamini/Maestro), [Claude Threads](https://github.com/anneschuth/claude-threads), [Cate](https://github.com/0-AI-UG/cate); Conductor, Desktop, Zed, Nimbalyst and AionUi were checked in their code for your stack's README
- Design: [Figma MCP](https://developers.figma.com/docs/figma-mcp-server/), [Penpot MCP](https://help.penpot.app/mcp/), [Illustrator (Beta)](https://helpx.adobe.com/in/illustrator/desktop/connect-with-other-apps-and-tools/about-using-ai-tools-with-illustrator.html), [Affinity](https://www.affinity.studio)
- Vector: [Recraft](https://www.recraft.ai/docs/mcp-reference/remote-server), [SVGator](https://www.svgator.com/help/svgator-mcp/connect-svgator-to-your-ai-assistant)
- Images: [Comfy MCP](https://docs.comfy.org/agent-tools/mcp), [BFL](https://docs.bfl.ml/api_integration/mcp_integration), [Replicate](https://replicate.com/docs/reference/mcp), [Krea](https://www.krea.ai/docs/developers/mcp), [Runway](https://runway.com/mcp), [vertex-ai-creative-studio](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio)
- Motion: [Remotion skills](https://www.remotion.dev/docs/ai/skills), [HyperFrames](https://hyperframes.heygen.com), [Rive MCP](https://rive.app/docs/editor/ai/mcp), [Lottie Creator MCP](https://docs.lottiefiles.com/en/creator/13_ai-tools/lottie-creator-mcp), [DaVinci Resolve 21.1](https://www.cgchannel.com/2026/09/blackmagic-design-releases-resolve-21-1/)
- 3D and diagrams: [MCP for Blender](https://github.com/ahujasid/blender-mcp), [Spline MCP](https://docs.spline.design/generate/spline-mcp-server), [draw.io MCP](https://www.drawio.com/docs/manual/generate/drawio-mcp-server/)
