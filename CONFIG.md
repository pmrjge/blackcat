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
| 6 | god-coder's prompt said it could not spawn at depth L3 | Wrong depth in the text (only L4 cannot spawn) | Corrected to L4 |
| 7 | Mixed models (Fable on god-coder) | Drift | Every agent names `opus` or `sonnet`; the IDs come from stack.env (section 2), enforced by lint |
| 8 | `/stack-doctor` returned STATUS: blocked: its agent had no Bash | The skill forked `claude-code-guide` (`context: fork`). A forked skill's agent gets its `tools` only from the main conversation's tool pool, and BlackCat has no Bash, WebFetch or WebSearch, so it was left with Read, ToolSearch and Skill. Even with Bash, the guard holds claude-code-guide (and verifier) to read-only commands and refuses `bash doctor.sh`, and any agent's sandboxed Bash cannot read stack.env or `~/.claude.json` nor write the state dir, so doctor.sh reports false FAILs there | `/stack-doctor` is answered by a UserPromptExpansion hook (matcher `stack-doctor`, `bin/doctor.sh --hook`): it runs doctor.sh outside the sandbox and blocks the expansion with the FAIL lines, the WARN lines (each with its section) and the ok count; no model turn. The skill body is only the fallback when the hook did not run |

## 2. Models

- **Rule:** the alias is the reference; it resolves to `ANTHROPIC_DEFAULT_<FAMILY>_MODEL`. Every agent's `model:` is one of two aliases, and lint rejects any other value.
  - `opus` for judgment-heavy work.
  - `sonnet` for extraction, lookups, loops and verification.
- **Where the IDs live:** `stack.env` only, in three variables: `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL`. `stack.env.example` ships today's IDs, with their source and date.
  - `install.sh` copies the non-empty ones into the `env` block of `~/.claude/settings.json`. Re-run it after a change.
  - Upgrading appends the missing variables to your `stack.env`, set to the stack's IDs. A key already in the file, even commented out, is left as you wrote it.
  - A value you set in `settings.json` yourself is kept, and the installer reports it.
  - Lint fails on a specific ID (`claude-<family>-<version>`) anywhere else. The exceptions are the installer's `OLD_DEFAULTS` migration list, doctor's `MEASURED_MODELS` record, the lint's own test vectors (`tests/test_lint_skills.py`) and `legacy/` (byte-exact templates of a released version).
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
- **Was**: the value at commit 0abe3eb, shown only where it changed.

| Agent | Model | Effort | maxTurns | Children | Was | Why |
|---|---|---|---|---|---|---|
| blackcat (main thread) | Sonnet 5.5 | medium (session) | none | 8 dispatches/prompt | effort low | Does a job of a few tool calls itself (Read, Bash, Write, Edit) and dispatches the rest; the orchestrator gets dependent multi-specialist work. At `medium` it asks questions and stays visible. |
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
- **Depth:** BlackCat → L1 → L2 → L3 → L4. L4 cannot spawn (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4`).
- **BlackCat:** may dispatch every specialist except supreme-coder, db-engineer and localizer (`BLACKCAT_VIA_HEADS`; those two are reached through the orchestrator or a domain head such as data-engineer, devops-engineer, writer or frontend-engineer). A job of a few tool calls (a look, a small edit, one command, git inspection) it does itself with Read, Bash, Write and Edit, under the same hooks, deny rules and sandbox as any agent; anything needing a skill, specialist judgement, tests or review is dispatched (§9, 2026-10-03 "BlackCat does small jobs itself").
- **Language agents** (rust-, haskell-, julia-, go-, python-, jvm-, node-engineer) share one row (`_LANG_ROW`: coder, explore, scout, verifier, code-reviewer, test-engineer, build-fixer, mcp-broker; python-engineer adds data-engineer). BlackCat, the orchestrator and main-, ninja- and supreme-coder spawn them; domain experts spawn the one that fits (embedded- and game-engineer → rust, hpc → julia, biochem → python, frontend → node).
- **supreme-coder:**
  - Only the orchestrator may spawn it, once per session (`SUPREME_SPAWNERS=orchestrator`, `SUPREME_ONCE_PER_SESSION=1`), and only after a ninja-coder of the same session has finished (`SUPREME_AFTER_NINJA=1`). The hook checks the order only (a ninja-coder stopped, or its Agent call reported a terminal status), not that it failed; that ninja-coder may have been spawned by any agent of the session.
  - Any other agent that needs it returns `STATUS: partial` with `NEXT: supreme-coder` and a dossier.
  - In a plan: planner may add one supreme-coder step, only as the conditional fallback of a preceding ninja-coder step on the same problem; plan-reviewer blocks a step without that ninja-coder step, an unconditional one, a second one or an incomplete dossier; BlackCat sends such plans to the orchestrator; the orchestrator runs ninja-coder first and spawns supreme-coder only when ninja-coder reports failure or partial, dropping the step if ninja-coder succeeds. That it failed is enforced by these prompts, not by the hook.
  - A failed or refused spawn releases the session slot. SendMessage resumes of that supreme-coder pass.
  - `claude-supreme` (supreme-coder as your own main thread) is unaffected.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker, claude-code-guide, browser-operator, plan-reviewer, image-director, explore, proof-checker, db-engineer, test-engineer, build-fixer, localizer.
- **No generic agents:** `subagent_type` must name a stack agent in the caller's row: a missing type, `general-purpose`, `claude`, `fork`, `Plan`, `statusline-setup`, host-defined types such as `SubAgent` and plugin agents are refused for every caller (one without a row gets BlackCat's row on a main thread, nothing as a subagent), also through the tool's `Task`/`SubAgent` aliases. A generic agent started outside the Agent tool (a skill with `context: fork` and no `agent:`, a workflow stage without `agentType`) has every tool call refused. Each workflow `agent()` names a stack `agentType` the caller may spawn, with no `model`; bundled and plugin workflows (`/deep-research`) are refused. settings.json: `Agent(general-purpose)`, `Agent(claude)`, `Agent(fork)` deny rules, `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1`, `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` (`claude -p` and Agent SDK apps).
- **Copies:** only researcher and coder may spawn copies (`researcher-copy`, `coder-copy`), at most 2 at once (`STACK_MAX_SELF_FANOUT=2`).

## 5. Guard knobs and settings

Values in `dot-claude/settings.json`. Those marked "code" are defaults in `agent_guard.py`, with no settings entry.

| Key | Value | Was | Why |
|---|---|---|---|
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | 33 | 20 | Room for an orchestrator's 32 running children plus the orchestrator itself without hitting the session limit |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` | 4 | — | Four layers below BlackCat |
| `BLACKCAT_MAX_DISPATCH` | 8 | 6 | Enough to cover a multi-domain request in one burst |
| `BLACKCAT_MAX_STEPS` | 12 | 8 | Dispatches plus relays and questions within one prompt |
| `BLACKCAT_DISPATCH_WINDOW_S` | 120 | 30 | Eight long briefs in one message take longer than 30 s to emit |
| `BLACKCAT_BACKGROUND` | 1 (code) | new | Drops BlackCat's `run_in_background: false` (fixes bug 1) |
| `BLACKCAT_MAX_OWN_STEPS` | 4 (code) | new | BlackCat's own Read/Bash/Write/Edit calls per prompt: 12 − 4 leaves a full burst of 8 dispatches |
| `BLACKCAT_BASH_TIMEOUT_MS` | 120000 (code) | new | Longest timeout a BlackCat foreground Bash call may ask for; with none given, `BASH_DEFAULT_TIMEOUT_MS` counts (2 min out of the box) |
| `STACK_AGENT_LABEL` | `description` (code) | new | `description\|name\|off`. `description` prefixes each allowed Agent call's description with `<type>: ` (Claude Code shows `agent-name(description)`); `name` names an unnamed child `<type>-<n>`; zero prompt tokens |
| `STACK_AGENT_STARTED` | 1 (code) | new | SubagentStart gives a stack agent its local start time for the clean-finish line; 0 disables it |
| `STACK_REPORT_FORMAT` | unset (code) | new | `json`: SessionStart (main thread, every source) and SubagentStart (stack agents) add one line asking for the final report as one JSON line, which `bin/stack_sdk.py` `parse_report` reads; unset: no hook output, the prompt is unchanged. For Agent SDK apps (`env` option) |
| `STACK_MAX_FANOUT` | 3 | — | Default number of running children per agent |
| `STACK_MAX_FANOUT_BY_TYPE` | `orchestrator=32,supreme-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | `orchestrator=8,planner=8,plan-reviewer=8` | The coordinators get room; everyone else keeps 3 |
| `STACK_MAX_SELF_FANOUT` | 2 | — | Copies per base agent |
| `SUPREME_SPAWNERS` | `orchestrator` (code) | new | Only the orchestrator spawns supreme-coder |
| `SUPREME_ONCE_PER_SESSION` | 1 (code) | new | At most one supreme-coder spawn per session |
| `SUPREME_AFTER_NINJA` | 1 (code) | new | A supreme-coder spawn needs a ninja-coder of this session that has finished; checks order, not failure; 0 = off |
| `SUPREME_IDLE_S` | 1800 | — | Time after which an idle supreme-coder releases the lock |
| `STACK_MAX_MCP_CALLS` | 64 | — | MCP calls per agent per prompt, as set by you; unchanged (browser-operator comes near it) |
| `STACK_PROMPT_CTX_BUDGET` / `STACK_SESSION_CTX_BUDGET` | learned (seed 100,000,000 / 666,000,000), not in settings.json since S6 | — | A value you set pins `hard.prompt` / `hard.session` (`/stack-doctor` lists it) (hard: refuses every call but reporting). Since 2026-10-02 the prompt window restarts only on a human prompt, not on a task notification's turn |
| Soft token limits (code: `SOFT_LIMITS`, `SOFT_PROMPT_CTX`) | per type, below; 33,000,000 per human prompt (80,000,000 while an orchestrator runs: `SOFT_PROMPT_CTX_BY_TYPE`) | new | A wrap-up warning, never a refusal; see "Soft token limits" below |
| `STACK_SOFT_LIMIT_SCALE` | unset = 1 (code) | new | Multiplies every soft limit; `0` turns them off. Not in settings.json, so a process environment value reaches the hooks (the benchmark sets it per run) |
| `STACK_SCHED_POLICY` | `report` (code) | `fresh_fixer` | The user's decision (2026-10-03): the scheduler stays a report tool. `fresh_fixer` is opt-in: `stack_sched.py next` then also advises a fresh fixer on stderr for a resume after a gap of 270 s or more (stdout, the ready ids, is the same). Fixed knob, recorded in each session's snapshot and read from it |
| `STACK_FANOUT_IDLE_S` | 600 | — | A silent background subtree stops counting against the caps |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | — | Unchanged |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | from `stack.env` (Opus, Sonnet, Sonnet) | moved | Copied from `stack.env` by the installer; the haiku slot holds the Sonnet ID (section 2) |
| `MCP_DISCOVERY_CACHE` / `MCP_TIMEOUT` / `MAX_MCP_OUTPUT_TOKENS` | 1 / 60000 / 25000 | — | Unchanged |
| `agent` | `blackcat` | — | BlackCat is the main thread in the terminal and in SDK apps |
| `autoCompactWindow` | 900000 | 400000 | Compaction at ~900K tokens. The pinned 5.5 models run a native 1M window on the Anthropic API (no `[1m]` suffix, nothing to set; `CLAUDE_CODE_DISABLE_1M_CONTEXT` would cap them at 200K). The one place the number is set: the installer re-asserts it, doctor and the smoke test check it |

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

`bin/stack-budget` (installed as `<config>/bin/stack-budget`, stdlib Python 3.8+, run it with `/usr/bin/python3`) is the one read-only view of the limits. It never writes a snapshot, `live.json` or any state: a session's limits are fixed at its start (S6, U4), and `stack_limits.py` is the only way to change what the next session starts with. It takes the session from `--session`, else `STACK_LIMITS_SNAPSHOT`, else `CLAUDE_SESSION_ID`, else the newest snapshot (said so), else the seed.

| command | shows |
|---|---|
| `stack-budget [--all]` | this session's frozen limits with their origin (env / live / seed / frozen), the guard's token count for the prompt and the session against them, and per type turns / soft / hard with the p90 of completed runs and its 90% CI |
| `stack-budget plan GRAPH.json` | stack_sched estimate (turns and ctx, median to hi) with a verdict per node and for the whole plan against the prompt and session limits (what the session already used counts) |
| `stack-budget agent TYPE` | seed, live and snapshot values of one type, status, n, interval, the sample statistics of `runs*.csv`, `runs2*.csv` and `runs3*.csv` and the last 5 rows; like the learner, the samples leave out the runs on another model than the type's frontmatter one (`/override-agent`) and every view shows how many |
| `stack-budget static` | the static prompt budget of `tests/prompt_budget.py` (repo checkout only) |

Every command takes `--json`. Verdicts are three-way: fits (the interval's upper end is within the limit), does not fit (its lower end is over it), uncertain (it straddles the limit, or there is no interval, n < 3). A learned value that is not `supported` always prints its interval. Exit 0 ok, 1 invalid input, 2 limits unavailable.

### `stack-tree`: agents and their commands (2026-10-03)

`bin/stack-tree` (installed as `<config>/bin/stack-tree`, stdlib Python 3.9+, `#!/usr/bin/python3 -B`) prints a session's tree of agents and subagents with the tool calls each ran as leaves; `/stack-tree` is the same from any session, BlackCat included: a UserPromptExpansion hook (matcher `stack-tree`, `"__PYTHON3__" -B "__CLAUDE_DIR__/bin/stack-tree" --hook`, timeout 30 s) runs it with the command's arguments and blocks the expansion with the output as the reason (exit 2), so no model turn runs and no Bash is needed; the skill body is only the fallback when the hook did not run. The hook defaults to the event's own session, 3 distinct commands per agent and 140 columns, and cuts its output at 16,000 characters with the terminal command for the rest, `--session` included (unverified whether Claude Code caps a block reason itself). It stops itself after 20 s: transcripts not yet read show as `transcript unscanned`, text not yet filtered as `(withheld: time budget)`, never raw.

| mode | shows |
|---|---|
| `stack-tree` | header (agents, running, failed/blocked/partial/stopped, tool calls), then BlackCat and every agent: type, task, status, duration, tokens, calls; its commands collapsed (`$ git status ×3 [1 exit 1]`), then its children. `--depth N`, `--no-leaves`, `--leaves-only-failed`, `--max-leaves N` (default 10, 0 = all), `--session ID` (default: the newest ledger), `--ascii`, `--width W` (default the terminal), `--json` |
| `stack-tree --table` | GitHub-flavored markdown, one row per agent and per tool call; `--columns a,b,c` or `all`, `--csv`, `--json`, `--width` caps the cells (default 80). Leaf rows carry the agent's level and depth + 1 |
| `stack-tree --static [--table]` | the designed hierarchy: breadth first from BlackCat's `Agent(...)` allowlist through each agent's "May spawn:" sentence (the one `tests/lint_agents.py` checks against POLICY), each agent expanded once at its shallowest level (later occurrences point there), nothing expanded at L4; leaves are BlackCat's user commands and the skills each agent's `## Skills` section names (`*` = a hub module read by path) |

- **Sources** (all read, none written): `spawns/*.json` (the delegation records `delegations.md` is rendered from; the file itself only when `spawns/` is absent), `agents/*.json` (parent, spawned, started, resumed, stopped, transcript) and Claude Code's transcripts, `<projects>/<project>/<sid>.jsonl` and `<sid>/subagents/agent-<id>.jsonl`, for each agent's tool calls, their results, the token usage of each API message (input + cache writes + cache reads + output, once per message id, the largest value over the lines it spans: Claude Code writes one line per content block and the earlier ones carry a partial `output_tokens`) and the final STATUS line (done, partial, blocked; a finished report without one is a clean finish). The hooks keep no per-call log of their own, and none was added: the transcripts already hold every call.
- **Status:** the ledger's lifecycle (launching, running, finished, failed, stopped), with one difference: an agent resumed (SendMessage) and not stopped since is running (the resume's SubagentStart clears `stopped`; a foreground child's record stays `completed`). A finished agent shows its report status. Start is the earliest of started, spawned, the record's time and the transcript's first line (a foreground child's registry entry is written when its call returns; a resumed one's `started` is its resume).
- **Unrecorded:** tokens per tool call, the arguments of MCP calls (only server.tool is shown), tool results (only ok, exit N, blocked or error), the leaves of an agent whose transcript is missing (spawn failed, or a placeholder for a caller whose own spawn is in neither source), and everything but type, task and state when only `delegations.md` exists.
- **Untrusted text:** task, name, type, command, path, URL and query strings pass one filter: they are cut to 1,200 characters (at most 300 are shown), then secret-looking values are masked (`*KEY*=`/`*TOKEN*=`/`*SECRET*=`/`*PASS*=`… assignments, `name: value` and JSON `"name": "value"` pairs whose name holds key, token, secret, password, auth, cookie or credential (headers such as X-Vault-Token or PRIVATE-TOKEN), Authorization/Cookie/API-key headers, Bearer tokens, `--token`-style flags, `mysql -p…`, `sshpass -p`, `docker login -p`, `pass:…`, `aws configure set …secret…`, URL credentials and key/token/signature query values, `sk-`, `sk_live_`/`sk_test_`, `ghp_`, `github_pat_`, `xox?-`, `AKIA`, `hf_`, `AIza`, `glpat-`, `npm_`, `hvs.`, `dckr_pat_`, JWTs, PEM private-key headers; every pattern is linear or bounded by the cut), then C0/C1 controls, DEL, format (bidi, zero-width), separator, surrogate, private and unassigned code points become spaces, then the text is cut. WebFetch URLs lose their query and fragment. Markdown cells backslash-escape backslash, pipe, backtick, `<`, `>`, `[`, `]` and `&` (so a renderer cannot turn `&#x202E;` back into a bidi override); CSV cells that start with `= + - @` get a leading `'`. State files are opened `O_NONBLOCK` and read only when regular (a FIFO cannot hang it), at most 4 MB per record, 256 MB per transcript, 1 GB per run.
- **Read-only:** no file, cache, lock or bytecode is written (`-B` and `sys.dont_write_bytecode`), no network; `tests/test_stack_tree.py` compares a snapshot of the whole fixture tree before and after every mode.

### On demand and automatic: MCP servers, plugins, skills (2026-10-02)

| Kind | Automatic (the situation needs it) | On demand (asked for) | Idle cost, before → after |
|---|---|---|---|
| Skills (212: 128 listed, 83 hub modules hidden) | Listed skills: their description, plus a one-line pointer "load X when Y" in the agent or hub that needs it. Hub modules (`user-invocable-only`): the hub's table or the agent's `## Skills` line (marked `name`*) names them, and the agent Reads `~/.claude/skills/<name>/SKILL.md` (the Skill tool refuses them) | the Skill tool by name; hidden modules by Read | Listing on every spawn: 17,647 chars at 1a38c77 → 30,782 at ad22962 (all described) → 14,437 now (hubs, standalones and 15 entry-grade modules described) |
| MCP, agent-scoped | The agent's inline `mcpServers` plus its `tools:` line: the server starts and stops with that agent | spawn that agent | 0 in other agents (unchanged); tool schemas deferred until tool search loads them |
| MCP, magg catalog (23 servers, all disabled) | A one-line pointer in the agent that has the gap: "X → mcp-broker mounts `<server>`" (devops → `kubernetes`/`grafana`, data-scientist → `sec-edgar`/`gis`/`jupyter`, doc-specialist → `docling`/`docspace`, llm-engineer → `mlflow`, researcher → `arxiv`, game → `godot`, biochem → `biomcp`/`pubchem`, mobile → `mobile`/`android`, embedded → `serial`, frontend → `chrome-devtools`, robotics → `ros`, quantum → `qiskit-runtime`) | ask mcp-broker | 0 until mounted (unchanged); the pointers add ~430 chars to four agent bodies |
| MCP, user scope (exa, jina, wolfram, huggingface, wandb) | session-wide, tools deferred | — | unchanged; nothing new added to user scope |
| Plugins, LSP (pyright, typescript, rust-analyzer, gopls, jdtls, kotlin, clangd, swift; haskell, julia, lean, metals from the stack's marketplace) | enabled; a language server starts when Claude touches a matching file | — | 0 listing (no skills); unchanged |
| Plugins with skills (document-skills, math-olympiad, skill-creator) | enabled, each named by a pointer (doc-specialist, technical-writing, presentation-design → docx/xlsx/pptx/pdf; mathematician, proof-craft → math-olympiad; claude-code-engineer → skill-creator), so none is disabled for being idle; the installer still disables document-skills and skill-creator where claude.ai syncs the same skills (§7, Plugins) | `/plugin enable <id>`, or `"enabledPlugins": {"<id>": true}` in a project's `.claude/settings.json` | 2,919 listing chars (measured); unchanged |
| Bundled Claude Code skills | left as they are: several are named by stack skills (dataviz, update-config) and their use can't be read here | `/<name>` | ~3,950 (estimated); unchanged |

Per-agent plugin enabling does not exist: plugins are session-wide (user, project or local scope), so an LSP plugin is not agent-scoped; the closest per-project control is `enabledPlugins` in that project's `.claude/settings.json`. No hook enables or installs anything. Every listed skill keeps its explanatory description; the 83 hub modules are hidden (`user-invocable-only`, the user's choice of design B1x+C on 2026-10-02, not `name-only`) and read by path; `tests/test_skill_modules.py` keeps each reachable from its hub's table. The listing budget (`skillListingBudgetFraction` 0.012) covers the stack's 14,564 characters plus ~14,169 for plugin, bundled and claude.ai skills (`tests/lint_agents.py` NON_STACK) with 25% to spare.

### Usage collector and scheduler model refresh (2026-10-02)

- **What:** `hooks/stack_usage.py` (stdlib, the hooks' `/usr/bin/python3`) runs one background collector per session. It reads the session's subagent transcripts by byte offset and appends one row per agent segment (a spawn or a resume) to `runs3.csv`. When the collector exits, `hooks/stack_sched_refresh.py` refits the scheduler's cost model from those rows (it uses `fit()` of `tests/derive_sched_model.py`, installed beside it). `hooks/stack_sched.py` reads the result.
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

## 6. Recommended session settings

- **Claude Desktop, Conductor and other SDK apps:** set effort to **medium** for the main thread; the agent files set each subagent's effort. Start a new session after installing.
- **Terminal:** `claude` (BlackCat) at the session's effort, `/effort medium`. For the hardest problems:
  - `claude-ninja` and `claude-supreme` run ninja-coder and supreme-coder as the main thread at `ultracode`.
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
6. Every path in `.stack-manifest.json` must be a file path in the scope (no `..`, no absolute path, not a whole scope dir such as `bin` or `mcp`): one that isn't stops the install before anything changes, and the staged copy must hold all the stack's scripts. The manifest also records the stack commit each install shipped; the next run prints, at its start, the diffstat of everything it ships since then (all of `dot-claude/`: agents with their MCP servers and hooks, skills, rules, hooks, settings, `bin/`, `mcp/`, magg's catalog, the LSP marketplace; plus `install.sh`, `lib/`, `requirements/`, `stack.env.example`) and any uncommitted edits there, capped at 40 lines with the `git diff` command to read it all; an unknown recorded commit gets a warning. When that list isn't empty, the run asks before step 2 changes anything (the venvs sync from `requirements/` there): `The stack changed since the last install (listed above). Install it? (see the whole plan first: ./install.sh --dry-run) [y/N]`; anything but y/yes stops with exit 1 and nothing changed. It asks on stdin/stderr when both are a terminal, otherwise on the controlling terminal (`/dev/tty`: `./install.sh 2>&1 | tee install.log` still asks there). With no terminal at all (CI, cron, `</dev/null` without a terminal), a changed stack stops with exit 1: "… there is no terminal to ask: rerun with --yes to install it (--dry-run shows the whole plan)", nothing changed (R4-1). `--yes` (`-y`) installs without asking and is needed without a terminal; `--dry-run` never asks.

`lib/install_state.py` does the staging, plan, backup, apply, restore and validation (system `python3`, stdlib only).

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

- uv 0.12.20: release tarball, checked by sha256.
- magg 1.2.1: `uv tool install --exclude-newer 2026-09-22T00:00:00Z`.
- huetension v0.3.0: tarball checked by sha256 (`go install ...@v0.3.0` as fallback).
- serial-mcp 0.9.3 (magg catalog `serial`): `cargo install serial-mcp@0.9.3 --locked --root ~/.cargo` (the crate's own `Cargo.lock`; crates.io checks the crate's checksum), only when cargo is present: Rust is never installed, and without cargo the step prints one line and doctor.sh WARNs with the command. The pin lives in the catalog entry's notes; install.sh reads it from there and skips the build when `~/.cargo/.crates2.json` already records that version (or the binary exists without a cargo record).
- sci/ml/tools venvs: `requirements/*.txt` with `--require-hashes` (sci and tools also `--only-binary :all:`), 7-day cooldown. `~/.claude/venvs/tools` (Python 3.13) holds what the stack's scripts, MCP servers and tests import (`requirements/tools.in` names the importer of each line); the full suite runs as `~/.claude/venvs/tools/bin/python -m pytest -q tests/`. Hooks never use it (stdlib on `/usr/bin/python3`).
- After Effects MCP: pinned commit `88d5fbf0`, `npm ci --ignore-scripts`, then an explicit `npm run build`.
- `--with-lsp` npm installs: `pyright@1.1.414`, `typescript-language-server@6.0.1` (`@5.3.0` on Node < 22.22.2) and `typescript@6.0.3` (TypeScript 7 ships no `tsserver`), all with `--ignore-scripts` (versions checked against the npm registry 2026-09-29).
- Agents can't run `install.sh` (guard, every agent type and the main thread) except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs (`HOME` and `CLAUDE_CONFIG_DIR` both under a temp dir, checked after resolving symlinks); installing is your step. The rule follows `cd <repo> && ./install.sh`, covers `lib/install_state.py apply|restore|stage|record|move-legacy` on a non-scratch config dir, and a command that copies or pipes the stack's `install.sh` and runs a shell.

### Sandbox and managed settings

- **Status: configured, not live-verified.** The settings, the guard and the tests are checked; that Claude Code's sandbox enforces them as configured is not, until the user runs the live checks (README → Security model → Live checks). Until then the guard and the deny rules are the tested layers.
- `settings.json` turns the sandbox on with `allowUnsandboxedCommands: false`:
  - **filesystem:** `denyWrite` covers the config dir, the guard state dir (`__STACK_STATE__`), the backups (`__STACK_BACKUPS__`) and the MCP servers' cache (`__STACK_CACHE__`), all rendered from `${XDG_STATE_HOME:-~/.local/state}` at install time (changing `XDG_STATE_HOME` later needs a reinstall), plus `~/.cache/uv`, `~/.cache/pre-commit`, the Playwright browser caches, `~/Library/Caches/Coursier` and the Hugging Face token file. `denyRead` covers `stack.env`, the state dir's `*.lock` and `*.mutex` files (a flock taken from a read-only fd would stall the collector, the limits commands or the guard), `backup-*`, the backups, `.credentials.json`, `~/.config/gh/hosts.yml`, `~/.git-credentials` and `~/.config/git/credentials`. `allowWrite` is only `~/.cache/claude-sandbox`.
  - **network:** a strict allowlist of package registries, forges, Hugging Face, W&B and arXiv.
  - **credentials:** forge tokens (`GITHUB_TOKEN`, `GH_TOKEN`, GitHub Enterprise, GitLab/Gitea/Forgejo/Codeberg), `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `WANDB_API_KEY` and `JUPYTER_TOKEN` are denied to sandboxed commands.
- `failIfUnavailable: true`: Claude Code exits at startup when the sandbox can't start, instead of warning and running commands unsandboxed.
- **Caches (N4, R3-CACHES).** Sandboxed Bash and everything else no longer share a writable cache.
  - Sandboxed Bash gets its own caches, `~/.cache/claude-sandbox/<tool>`, from a SessionStart hook without a matcher (`agent_guard.py session-env`, every source) that appends exports to `$CLAUDE_ENV_FILE`; Claude Code runs that file before each Bash command, the agents' included. The variables: `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `npm_config_cache`, `npm_config_devdir`, `npm_config_store_dir`, `YARN_CACHE_FOLDER`, `BUN_INSTALL_CACHE_DIR`, `DENO_DIR`, `PRE_COMMIT_HOME`, `HF_HOME`, `MPLCONFIGDIR`, `CARGO_HOME`, `GOMODCACHE`, `GOCACHE`, `GRADLE_USER_HOME`, `COURSIER_CACHE`, `CCACHE_DIR`, `SCCACHE_DIR`, `CABAL_DIR`, `JULIA_DEPOT_PATH` (`<dir>/julia:`, the default depots after it), plus `-Dmaven.repo.local=<dir>/m2` appended to `MAVEN_OPTS`. MCP servers, hooks, language servers and the user's terminal don't see them and keep their normal caches, which sandboxed code can no longer write. Safe to delete.
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
| `uv run --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/` | 2401 passed at `cfa9ee7` (2400 at `e0b5544`, also from a snapshot under `/private/tmp`, where 118 had failed before R3-INFO) |
| `bash tests/install_smoke.sh` | 244 passed, 0 failed at `cfa9ee7` (scratch HOME only; re-runs itself without a controlling terminal, so no install in it can wait on yours; includes a drifted config, dry-run, restore round trips, `--no-prune`, symlinked scope dirs with dir and file links, manifest traversal) |
| `jq empty dot-claude/settings.json` | ok |

## 9. Changelog

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

- Security audit of f235e7a, MEDIUM: an `/override-agent` run (e.g. scout on haiku) fed `soft.agent.scout`, `turns.scout`, the pool proposals and the scheduler refit that later sessions on scout's own model use, against the "this session only" scope. The collector now writes schema 3 rows to `usage/runs3.csv` with the segment's `model`; `stack_limits.py`, `stack_sched_refresh.py` and `stack budget` skip an agent row whose model is not its frontmatter one and count what they skipped (§5, "Session model overrides" and "Usage collector"). `runs*.csv` and `runs2*.csv` are read as before and never written again. Rerun install.sh; a session collected by the old code is read again from the start the next time its collector runs.
- Audit follow-up, MEDIUM: a collector started before the install kept the old code and wrote model-less rows for override runs typed after it. The next SessionStart or SubagentStart now stops a running older-schema collector (SIGTERM after the checks in §5, "Upgrade hand-off") and a successor reads the session again as schema 3 (tests: `test_upgrade_hands_off_from_an_older_collector` runs the real schema 2 collector from `6a736c6`; `test_handoff_signals_only_a_running_older_collector_of_this_session`; `test_a_successor_waits_for_the_lock_and_then_runs`). Its audit (MEDIUM): the stopped collector's mid-session session row stood as a whole session when the successor idled out; such stale session rows are now left out (`test_a_handoff_session_row_is_not_learned_as_a_whole_session`, `test_a_session_row_older_than_its_sessions_rows_is_not_learned`). The model IDs of the usage, limits and budget tests sit on module-level constant lines, which `tests/lint_agents.py` allows (`MODEL_ID_CONST`).

### 2026-10-03 (scheduler policy back to report)

- `STACK_SCHED_POLICY` defaults to `report` again (`stack_limits.SCHED_POLICY_DEFAULT`, `stack_sched.soft_values`); `fresh_fixer` is opt-in. A session keeps the policy of its snapshot. The default enters the regime hash, so sessions without the knob start a new regime: rows of the old one count as provisional evidence until the new regime has support.
- Tests: the default gives no advice, `fresh_fixer` advises, a mid-session env change does not reach the session; the MCP caps are pinned as fixed guards (T1b); support-rule boundaries (T6b).

### 2026-10-03 (/override-agent reset, FIFO fix)

- `/reset-agent` is now the subcommand `/override-agent reset <agent|all>` (beside `list`). The effort stays display-only (the user's decision: no agent variants).
- Security audit of f235e7a (LOW): a FIFO at the override state path hung the PreToolUse(Agent) hook until its timeout. The state and log files are now opened with `O_NONBLOCK` and refused unless `S_ISREG` (test: `test_a_fifo_at_the_state_path_does_not_hang_the_agent_hook`).

### 2026-10-03 (/override-agent, built-in effort table)

- The commands are now `/override-agent <agent> <model>`, `/override-agent list` and `/reset-agent <agent|all>`. The old `/agent-override` and `/agent-reset` and their effort argument are gone. The effort comes from `hooks/agent_effort.json` (initial defaults, rule v1), clamped to the model; it is recorded and shown, not applied (§5, "Session model overrides").
- Not built: enforcing the effort through per-(agent, model) agent definition variants, which install.sh would render statically (frontmatter `model` + `effort` from the table) with the guard resolving `<agent>@<model>` to `<agent>`. That means up to 220 more agent files in the listing every Agent caller sees. Every guard keyed by agent type would also need one alias function: spawn rows and allowlists, copy rules, READONLY_TYPES (no-push read-only Bash), fan-out by type, god-coder and browser spawners, web taint, MCP and turn caps, the limits snapshot (turns, hard and soft per type), read_gate and web_caps exemptions, ledger labels, stack_usage and the scheduler model, and lint_agents. A missed site there weakens a guard, and the result can only be checked in a live session. It waits for the user's decision.

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
- `STACK_REPORT_FORMAT=json` (above); the guard's SessionStart matcher is `startup|resume|clear|compact|fork` so the line survives `/clear` and compaction (no output when unset).
- Hooks under the SDK and `claude -p`: no TTY dependence (hooks always run without a controlling terminal); `tests/test_sdk_integration.py` runs them with SDK-shaped events and environment. Cache order checked: no hook writes a system prompt or rewrites earlier context; the SubagentStart line sits in the first user message and is kept.
- Reference: `skills/claude-code-extensions/references/agent-sdk.md`; cost probe for the user: `tests/sdk_smoke.py` (real API calls; not run in the build sandbox).

### 2026-09-29 (security rounds 3 and 4, god-coder plan flow)

Commits `ea80f87`, `7292272`, `b93b557`, `c9ef24b`, `693296f`, `275eead`, `b7a075b`, `7e8386b`, `47acb92`, `1e1cd82`, `80bc1dd`, `9aeec09`, `e0b5544`, `df21992`, `cfa9ee7`; magg `bb77d58`, `17fdd46`; docs `f8124cc` and this commit.

- Without a terminal on stdin/stderr the supply question goes to `/dev/tty`; with no terminal at all a changed stack stops with exit 1 unless `--yes` (R4-1, `df21992`).
- A failed session-env hook exits 2 with a hook error, is recorded in `session-env.json`, and shows in the status line and `doctor.sh` (R4-2, `cfa9ee7`).
- Round-4 residuals recorded (taint gaps, `GOD_AFTER_NINJA` order only, a session started in `/tmp`, live checks open).

- Web taint follows reports, messages and spawn prompts (R3-T3-RELAY).
- Caches and the git credential reset moved to a SessionStart `CLAUDE_ENV_FILE` for sandboxed Bash only; `allowWrite` is `~/.cache/claude-sandbox`; an upgrade retracts the old settings (R3-CACHES, R3-GITENV).
- The supply diff covers everything shipped and asks on a terminal (`--yes`) (R3-SUPPLY).
- The guard state dir in the sandbox and `Edit` denies renders from `XDG_STATE_HOME` (R3-STATE).
- `--restore` keeps the current entry where it skips a link (R3-RESTORE-LINK); `--dry-run` refuses like the real run (R3-DRYRUN); file links inside a symlinked dir are kept (R3-WTL-INNER).
- `doctor.sh` reports GitHub credentials agents could use, by presence only (R3-N1-P2); least-privilege GitHub setup documented; `~/.config/git/credentials` denied.
- Read-only reviewers treat a project under a temp dir as the project (R3-INFO).
- magg `ros_*`, `qiskit_*`, `docspace_*` and the ten domain prefixes ask; every catalog prefix has exactly one allow or ask rule.
- god-coder only after a finished ninja-coder (`GOD_AFTER_NINJA`); a plan's god-coder step runs only after its ninja-coder step failed (planner, plan-reviewer, BlackCat, orchestrator prompts; section 4).
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
  - god-coder moved from Fable to Opus 5.5.
  - doc-specialist moved to Sonnet 5.5.
- Effort recalibrated for 5.5:
  - lowered from `xhigh` to `high`: orchestrator, plan-reviewer, code-reviewer, quantum-engineer;
  - lowered from `high` to `medium`: motion-designer, cg-artist.
- maxTurns set per task type (section 3).
- Caps:
  - BlackCat: 8 dispatches, 12 steps, 120 s window;
  - running children per agent: orchestrator 32, main-coder and god-coder 6, ninja-coder 5, researcher 4, planner 8, everyone else 3;
  - `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 33.
- god-coder: only the orchestrator spawns it, once per session. BlackCat, main-coder, ninja-coder and the ML platform engineers return `NEXT: god-coder` instead of spawning it.
- The installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT`; `/stack-doctor` warns about them.
- Tests:
  - new: BlackCat foreground drop, shipped spawn defaults, god-coder orchestrator-only and once per session;
  - the mechanics tests pin their former caps as a baseline.

The full entry is in the README as of 96d3a52 (`git show 96d3a52:README.md`, section Changelog).
