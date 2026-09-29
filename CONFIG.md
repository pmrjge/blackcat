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
| 7 | Mixed model IDs (`opus` alias, Fable on god-coder) | Drift | Every agent pins `claude-opus-5-5` or `claude-sonnet-5-5`, enforced by lint |

## 2. Models

- **Rule:** only two models are allowed, and lint rejects any other value.
  - `claude-opus-5-5` for judgment-heavy work.
  - `claude-sonnet-5-5` for extraction, lookups, loops and verification.
- **BlackCat** (the main thread) runs on Sonnet 5.5.
- **No Haiku anywhere.** `ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-sonnet-5-5` moves Claude Code's small-model slot (background tasks, titles) to Sonnet 5.5.
  - This key is kept deliberately: it is the only way to move that slot.
  - A host that sets `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST` ignores it in settings files. There, set it in the app's launch environment instead.

## 3. Per-agent parameters

Column key:

- **Effort** binds only when the agent runs as a subagent. The main thread uses the session level.
- **Children**: how many of its own subagents may run at once, enforced by the hook. "leaf" = no Agent tool.
- **Was**: the value at commit 0abe3eb, shown only where it changed.

| Agent | Model | Effort | maxTurns | Children | Was | Why |
|---|---|---|---|---|---|---|
| blackcat (main thread) | Sonnet 5.5 | medium (session) | none | 8 dispatches/prompt | effort low | Routes every request, trivial or complex, to specialists. At `medium` it asks questions and stays visible. |
| orchestrator | Opus 5.5 | high | 250 | 10 | xhigh, 300 | Decomposes a job into up to 10 parallel tasks. On 5.5, `high` is enough for coordination. |
| planner | Opus 5.5 | xhigh | 80 | 8 | 100 | Read-only design work that needs deep reasoning and few turns |
| plan-reviewer | Opus 5.5 | high | 80 | leaf | xhigh, 100 | Critique against the code and docs. `high` suffices on 5.5. |
| oracle | Opus 5.5 | low | 12 | leaf | 20 | Answers from knowledge alone and uses almost no tools |
| scout | Sonnet 5.5 | low | 30 | leaf | 40 | Looks up one fact from a few sources |
| researcher | Opus 5.5 | high | 150 | 4 | 170 | Measured p90 is 82 turns. 4 children = 2 researcher copies + 2 lookups. |
| mathematician | Opus 5.5 | xhigh | 100 | 3 | — | Proofs need depth, not many turns |
| quantum-engineer | Opus 5.5 | high | 180 | 3 | xhigh, 190 | Code and simulation loops. `high` on 5.5. |
| image-director | Opus 5.5 | medium | 80 | leaf | 100 | Prompt and spec work with short loops |
| designer | Opus 5.5 | high | 150 | 3 | 100 | Iterative vector and raster work needs more turns |
| motion-designer | Opus 5.5 | medium | 150 | 3 | high, 190 | GUI and tool loops, not deep reasoning |
| cg-artist | Opus 5.5 | medium | 170 | 3 | high, 190 | Same reason: DCC tool loops |
| writer | Opus 5.5 | medium | 120 | 3 | 130 | Prose; voice matters more than depth |
| doc-specialist | Sonnet 5.5 | medium | 120 | 3 | Opus, 130 | Extraction and formatting work |
| coder | Sonnet 5.5 | medium | 190 | 3 (+2 copies) | — | Small and medium implementation |
| main-coder | Opus 5.5 | xhigh | 300 | 6 | 250 | Large codebases; measured p90 is 128 turns, and long refactors run past that. Offloads to coder and the ML engineers. |
| ninja-coder | Opus 5.5 | max | 300 | 5 | 250 | The hardest algorithmic and mathematical cores, worked through without the user |
| god-coder | Opus 5.5 | max | 350 | 6 | Fable, 250 | Last resort. The orchestrator spawns it, at most once per session. |
| frontend-engineer | Opus 5.5 | medium | 190 | 3 | — | Implementation plus browser checks |
| devops-engineer | Sonnet 5.5 | high | 160 | 3 | 190 | Plans and dry runs; bounded scope |
| data-engineer | Sonnet 5.5 | high | 190 | 3 | — | SQL and pipelines with recomputation checks |
| data-scientist | Opus 5.5 | high | 150 | 3 | 190 | Analysis with stated uncertainty |
| ml-, dl-, llm-, mlx-, cuda-, robotics-engineer | Opus 5.5 | high | 190 | 3 | — | Long experiment and benchmark loops |
| code-reviewer | Opus 5.5 | high | 120 | leaf | xhigh, 150 | Read-only review. `high` on 5.5. |
| verifier | Sonnet 5.5 | high | 150 | leaf | 160 | Measured p90 is 92 turns: runs tests, reproduces, checks |
| security-auditor | Opus 5.5 | xhigh | 120 | leaf | 150 | Finding exploit paths needs depth |
| browser-operator | Sonnet 5.5 | medium | 120 | leaf | 160 | Browser loops. It has come close to the 64-per-prompt MCP cap (62 calls in one run). |
| mcp-broker | Sonnet 5.5 | medium | 80 | leaf | — | Mounts, calls and unmounts MCP servers |
| claude-code-engineer | Opus 5.5 | high | 180 | 3 | 150 | Measured p90 is 123 turns: validation-heavy |
| claude-code-guide | Sonnet 5.5 | low | 30 | leaf | 40 | Documentation lookups |

Effort scale:

- On the 5.5 models, `medium` matches or beats Opus 5 at `high`. The docs call `max` "prone to overthinking", so it is kept for ninja-coder and god-coder only.
- `CLAUDE_CODE_EFFORT_LEVEL` would override every agent's effort. Leave it unset.

maxTurns:

- One turn is one model response.
- When an agent reaches its limit, it is marked partial. A SendMessage resume gives it a fresh budget.
- Lint enforces ≤ 350 for all agents, and < 200 for all agents except the orchestrator and main-, ninja- and god-coder.

## 4. Spawn policy

- **Source of truth:** `POLICY` in `agent_guard.py`. The "May spawn" sentences must match it (lint-checked). Every agent with a POLICY row has the Agent tool.
- **Depth:** BlackCat → L1 → L2 → L3 → L4. L4 cannot spawn (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4`).
- **BlackCat:** may dispatch every specialist except god-coder, so trivial and complex requests alike go through the specialists.
- **god-coder:**
  - Only the orchestrator may spawn it, once per session (`GOD_SPAWNERS=orchestrator`, `GOD_ONCE_PER_SESSION=1`).
  - Any other agent that needs it returns `STATUS: partial` with `NEXT: god-coder` and a dossier.
  - A failed or refused spawn releases the session slot. SendMessage resumes of that god-coder pass.
  - `claude-god` (god-coder as your own main thread) is unaffected.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker, claude-code-guide, browser-operator, plan-reviewer, image-director.
- **Copies:** only researcher and coder may spawn copies (`researcher-copy`, `coder-copy`), at most 2 at once (`STACK_MAX_SELF_FANOUT=2`).

## 5. Guard knobs and settings

Values in `dot-claude/settings.json`. Those marked "code" are defaults in `agent_guard.py`, with no settings entry.

| Key | Value | Was | Why |
|---|---|---|---|
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` | 32 | 20 | Room for BlackCat 8 × orchestrator 10 without hitting the session limit |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` | 4 | — | Four layers below BlackCat |
| `BLACKCAT_MAX_DISPATCH` | 8 | 6 | Enough to cover a multi-domain request in one burst |
| `BLACKCAT_MAX_STEPS` | 12 | 8 | Dispatches plus relays and questions within one prompt |
| `BLACKCAT_DISPATCH_WINDOW_S` | 120 | 30 | Eight long briefs in one message take longer than 30 s to emit |
| `BLACKCAT_BACKGROUND` | 1 (code) | new | Drops BlackCat's `run_in_background: false` (fixes bug 1) |
| `STACK_MAX_FANOUT` | 3 | — | Default number of running children per agent |
| `STACK_MAX_FANOUT_BY_TYPE` | `orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | `orchestrator=8,planner=8,plan-reviewer=8` | The coordinators get room; everyone else keeps 3 |
| `STACK_MAX_SELF_FANOUT` | 2 | — | Copies per base agent |
| `GOD_SPAWNERS` | `orchestrator` (code) | new | Only the orchestrator spawns god-coder |
| `GOD_ONCE_PER_SESSION` | 1 (code) | new | At most one god-coder spawn per session |
| `GOD_IDLE_S` | 1800 | — | Time after which an idle god-coder releases the lock |
| `STACK_MAX_MCP_CALLS` | 64 | — | MCP calls per agent per prompt, as set by you; unchanged (browser-operator comes near it) |
| `STACK_PROMPT_CTX_BUDGET` / `STACK_SESSION_CTX_BUDGET` | 100,000,000 / 666,000,000 | — | As set by you; unchanged |
| `STACK_FANOUT_IDLE_S` | 600 | — | A silent background subtree stops counting against the caps |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | — | Unchanged |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `claude-sonnet-5-5` | — | Moves the small-model slot to Sonnet 5.5 (section 2) |
| `MCP_DISCOVERY_CACHE` / `MCP_TIMEOUT` / `MAX_MCP_OUTPUT_TOKENS` | 1 / 60000 / 25000 | — | Unchanged |
| `agent` | `blackcat` | — | BlackCat is the main thread in the terminal and in SDK apps |
| `autoCompactWindow` | 400000 | — | Unchanged |

## 6. Recommended session settings

- **Claude Desktop, Conductor and other SDK apps:** set effort to **medium** for the main thread; the agent files set each subagent's effort. Start a new session after installing.
- **Terminal:** `claude` (BlackCat) at the session's effort, `/effort medium`. For the hardest problems:
  - `claude-ninja` and `claude-god` run ninja-coder and god-coder as the main thread at `ultracode`.
  - Dispatched as subagents, both run at `max`.
- **Not verified:**
  - whether AskUserQuestion is offered to the main thread in Claude Desktop (it goes through the host's `canUseTool`); BlackCat falls back to plain-text questions;
  - Desktop behavior after the fix. It is inferred from transcripts and the hook tests, not from a live Desktop run.

## 7. Validation (2026-09-29)

| Check | Result |
|---|---|
| `/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test` | ok |
| `uv run tests/lint_agents.py` | ok |
| `uv run --python 3.12 --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/` | 799 passed |
| `bash tests/install_smoke.sh` | 171 passed, 0 failed |
| `jq empty dot-claude/settings.json` | ok |

## 8. Changelog

### 2026-09-29

- Desktop hang fixed: BlackCat's children always run in the background, and the hook drops `run_in_background: false`.
- BlackCat always gives a visible reply and asks clarifying questions. The recommended main-thread effort is `medium`.
- Models: only `claude-opus-5-5` and `claude-sonnet-5-5` are used, with no Haiku.
  - god-coder moved from Fable to Opus 5.5.
  - doc-specialist moved to Sonnet 5.5.
- Effort recalibrated for 5.5:
  - lowered from `xhigh` to `high`: orchestrator, plan-reviewer, code-reviewer, quantum-engineer;
  - lowered from `high` to `medium`: motion-designer, cg-artist.
- maxTurns set per task type (section 3).
- Caps:
  - BlackCat: 8 dispatches, 12 steps, 120 s window;
  - running children per agent: orchestrator 10, main-coder and god-coder 6, ninja-coder 5, researcher 4, planner 8, everyone else 3;
  - `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 32.
- god-coder: only the orchestrator spawns it, once per session. BlackCat, main-coder, ninja-coder and the ML platform engineers return `NEXT: god-coder` instead of spawning it.
- The installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT`; `/stack-doctor` warns about them.
- Tests:
  - new: BlackCat foreground drop, shipped spawn defaults, god-coder orchestrator-only and once per session;
  - the mechanics tests pin their former caps as a baseline.

The full entry is in `README.md` → Changelog.
