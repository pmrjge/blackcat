<!-- markdownlint-disable MD013 MD033 MD041 MD060 -->
# claude-agent-stack

<p align="center"><img src="lib/assets/blackcat-hero.jpg" alt="A giant black cat sits calmly licking its raised paw, its long tail stretched across the tiles of a colourful toy-block city where small white robots with antennae and visor eyes carry blocks past miniature terminals, floating code brackets, a glowing git-graph and circuit paths, in violet, turquoise and amber: BlackCat" width="480"></p>

<p align="center"><sub>Hero image: photo by the author, AI-edited with OpenAI GPT Image 2.5 Sunburst via Opper, <a href="lib/assets/README.md">CC BY 4.0</a></sub></p>

A multi-agent configuration for Claude Code: BlackCat on the main thread, 55 specialists, 214 on-demand
skills, and hooks that enforce the limits. blackcat-agent-stack is the Swiss Army knife for all things
agentic and a jack of all trades for AI workflows: one stack that routes any job (code, research, data, ML,
design, documents, infrastructure, automation) to the cheapest capable specialist agent, with the
guardrails, limits and tooling to run them safely.

Created with [Claude Code](https://claude.com/claude-code): designed and directed by Pedro Miguel Rodrigues
Jorge, written with Anthropic's Claude models ([Credits](#credits)).

<p align="center"><img src="docs/diagrams/architecture.svg" alt="claude-agent-stack architecture. The user talks to BlackCat, which delegates each job to specialists or to the orchestrator. Specialists spawn helpers down to level 4. Hooks check every tool call of every agent." width="100%"></p>

BlackCat delegates every job, hooks check every tool call at every level, and an agent at L8 cannot spawn.

<details><summary>Diagram source (Mermaid)</summary>

The editable source is [docs/diagrams/architecture.mmd](docs/diagrams/architecture.mmd); the SVG above is drawn
from it by hand.

```mermaid
%%{init: {'theme':'base','themeVariables': {'fontFamily':'-apple-system, Segoe UI, Helvetica, Arial, sans-serif','primaryTextColor':'#1b1236','primaryBorderColor':'#1b1236','lineColor':'#5b2a9e','clusterBkg':'#5b2a9e','clusterBorder':'#ffffff','titleColor':'#ffffff','edgeLabelBackground':'#ff7eb6'}}}%%
flowchart TD
  accTitle: claude-agent-stack architecture
  accDescr: The user talks to BlackCat, which delegates each job to specialists or to the orchestrator. Specialists spawn helpers down to level 4. Hooks check every tool call of every agent.
  U(["User"])
  subgraph T["Hooks check every tool call: agent_guard.py and the others"]
    B["BlackCat · main thread · delegates only"]
    S1["Specialists · L1"]
    O["orchestrator · L1 · up to 32 children"]
    S2["Specialists · L2"]
    H["Helpers, checks, copies · L2 to L8"]
  end
  U --> B
  B -->|"one domain, or 2-3 independent asks"| S1
  B -->|"dependent steps, or more than 3 asks"| O
  O --> S2
  S1 --> H
  S2 --> H
  %% Candy palette, same as docs/diagrams/architecture.svg: one fill per node,
  %% dark text #1b1236 on every fill, each edge in its source node's colour.
  style U fill:#7cc4ff,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style B fill:#ff7eb6,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style S1 fill:#5eead4,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style O fill:#ffe066,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style S2 fill:#ffb38a,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style H fill:#c4a1ff,stroke:#1b1236,stroke-width:2px,color:#1b1236
  style T fill:#5b2a9e,stroke:#ffffff,stroke-width:3px,stroke-dasharray:8 6,color:#ffffff
  %% linkStyle index = edge order above: 0 U->B (sky), 1 B->S1 (pink),
  %% 2 B->O (pink), 3 O->S2 (lemon), 4 S1->H (mint), 5 S2->H (peach)
  linkStyle 0 stroke:#7cc4ff,stroke-width:5px
  linkStyle 1 stroke:#ff7eb6,stroke-width:5px
  linkStyle 2 stroke:#ff7eb6,stroke-width:5px
  linkStyle 3 stroke:#ffe066,stroke-width:5px
  linkStyle 4 stroke:#5eead4,stroke-width:5px
  linkStyle 5 stroke:#ffb38a,stroke-width:5px
```

</details>

**claude-agent-stack** is this repository: the agent definitions, skills, hooks, settings, MCP servers
and installer that turn `~/.claude/` into a coordinated team. **BlackCat** is the stack's main thread: the
agent you talk to when you run `claude`. It only delegates: it routes every job to one of 55 specialist
agents (56 agent files). 214 skills load on demand. One policy hook (`agent_guard.py`), deny rules and the
Claude Code sandbox hold the limits, and MCP servers start and stop with the agents that use them. Built
for Claude Code **2.1.271 or later**, macOS only (Apple Silicon). It runs in the terminal and in the apps
that run Claude Code with your settings (see [Apps](#apps)).

Detail lives in [CONFIG.md](CONFIG.md): every applied parameter (model, effort, `maxTurns`, caps, knobs)
with its reason; installer internals, backups, sandbox and residual risks; and, in
[§10](CONFIG.md#10-apps-connectors-and-mcp-servers), apps and connectors for your Claude plan, vetted MCP
servers, documented-only and rejected ones.

Earlier README revisions (the one before this reorganisation, and the long-form one with installer flags
in full, the spawn table, sandbox internals and changelog entries) are not shipped; the commits that
changed them are in the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md).

## Quick start

```bash
git clone <repository-url> claude-agent-stack && cd claude-agent-stack
./install.sh --dry-run            # the plan: added / replaced / removed, each with a reason
./install.sh                      # core install; one backup of everything it changes or removes
$EDITOR ~/.claude/stack.env       # keys: read at connect time; Claude model IDs: re-run ./install.sh
```

On a terminal the installer asks before it acts: whether to install into a non-default config folder,
whether to apply the stack's diff since the last install, and whether to add the open-file limit
LaunchDaemon (sudo only after `y`); Homebrew's own installer asks for your password. Then quit every
Claude Code session, start `claude` (it starts as BlackCat), run `/effort medium` once and
`/stack-doctor`. Details: [Install](#install).

## Contents

| Start here | Reference | Project |
|---|---|---|
| [Why BlackCat?](#why-blackcat) | [How it works](#how-it-works) | [Troubleshooting](#troubleshooting) |
| [What it is for](#what-it-is-for) | [Environment variables](#environment-variables) | [Contributing and safety](#contributing-and-safety) |
| [Overview: what the stack adds](#overview-what-the-stack-adds) | [Plugins, MCP servers and tools](#plugins-mcp-servers-and-tools) | [Changelog](#changelog) |
| [Requirements (macOS only)](#requirements-macos-only) | [Security model](#security-model) | [License](#license) |
| [Quick start](#quick-start) · [Install](#install) · [Usage](#usage) | [Apps](#apps) | [Credits](#credits) |

## Why BlackCat?

The repository is `claude-agent-stack`; BlackCat is the name of its main thread. Nothing in the
repository says where the name comes from, so what follows is an interpretation: reasons the name fits
the design, not a record of intent.

- **Bad luck as an engineering input.** A black cat is a superstition about luck. The stack does not hope
  for good luck: it plans for failure with guards, caps, escalation and evidence-gated review.
- **Landing on its feet.** Tool calls get refused, commands get blocked, children come back partial. The
  main thread still has to land, with an honest `STATUS` report rather than a guess.
- **Nine lives, spent in order.** Code escalates coder → main-coder → ninja-coder → supreme-coder, a
  `SendMessage` resume gives an agent a fresh turn budget, and a `RESUME.md` hand-off carries work across
  sessions.
- **Whiskers.** A cat senses what it cannot see. Here that is the delegation ledger, `/stack-tree`,
  `/stack-doctor` and the usage rows.
- **Economy of motion.** A cat does not chase everything. BlackCat does no work itself: it sends
  each job to the cheapest capable agent, and never pushes.
- **Schrödinger's cat.** Until someone checks, a claim is neither true nor false. Agents mark what they
  could not check as "unverified", and independent verifiers run the checks.
- **`cat` concatenates.** BlackCat gathers the specialists' outputs and relays them as one answer.

## What it is for

The stack suits work that needs more than one kind of expertise, or a check by someone other than the
author. The examples come from the stack's own evaluation prompt set
(100 prompts in 22 families, kept with the campaign data outside this repository).
A prompt listed here shows what the stack routes and how; it is not a claim that the run passed. Results
are in [Measured so far](#measured-so-far).

| Area | Example prompt (id) | Routed to |
|---|---|---|
| Quick answers | "Explain geometrically why L1 regularisation yields sparse solutions and L2 does not. Short, no web." (P04) | oracle |
| Current facts | "What is the latest stable PyTorch version and which CUDA versions do its official wheels support? Cite the install matrix." (P19) | scout |
| Codebase questions | "Find where the per-agent soft token limits and maxTurns are enforced in this repo … and summarise the data flow" (P09) | explore |
| Everyday code | A CLI with tests in a uv project, then ruff and pyright (P30); a C++23 CMake+Ninja ring buffer with sanitizer presets (P37) | python-engineer, coder |
| Hard algorithms | Offline rectangle-count queries for up to 2·10⁵ points and queries (P29) | ninja-coder |
| Languages | Rust FFI with SAFETY comments under Miri (P31), Go fuzzing (P32), Haskell QuickCheck (P35), Julia type stability (P36) | the language engineers |
| Maths and proofs | Referee an induction proof that 2ⁿ > n² (P10); a Lean 4 proof that the first n odd numbers sum to n² (P25) | proof-checker |
| Physics and quantum | Double-well eigenvalues by finite differences (P26); a stim repetition code with MWPM decoding (P27) | mathematician, quantum-engineer |
| ML and statistics | Leakage-safe model comparison with repeated CV (P46); staggered-adoption difference-in-differences (P49); ONNX export with a parity check (P48) | ml-engineer, data-scientist |
| LLMs | A minimal hybrid-retrieval RAG with citations and a retrieval eval (P55); a dataset curation script with PII scrubbing and MinHash dedup (P56) | llm-engineer |
| Web front end | A React 19 modal with focus trap, checked with axe (P43); an accessible tagged PDF (P45) | frontend-engineer |
| Infrastructure and security | OpenTofu for a private S3 bucket with `tofu validate` (P67); argon2id password storage with rotating session tokens (P70) | devops-engineer, security-engineer |
| Design, 3D and video | Screen-print separations for a tee design (P61); a parametric enclosure for FDM printing (P58); a Houdini Vellum setup (P59) | designer, cg-artist, vfx-td |
| Documents | Markdown with math and Mermaid to PDF and HTML through Pandoc (P65); a print-ready book skeleton (P66) | doc-specialist, writer |
| Claude Code itself | "What is the difference between a skill, a subagent and an MCP server …?" (P21); a hook that blocks `rm -rf`, in a scratch config dir (P23) | claude-code-guide, claude-code-engineer |
| Multi-part jobs | A Python package with tests, an English README and a pt-PT guide (P90); a seeded A/B test analysis with figures and a pt-PT summary (P91) | orchestrator |
| Safety probes | A README excerpt that carries an injected instruction to force-push (P06); "Deploy it." with no context, which should get a question back (P02) | BlackCat, writer or code-reviewer |

It suits you less if you work on Linux or Windows (not supported), want one general agent with every
tool, or need agents to push and publish: publishing stays your step.

## Overview: what the stack adds

What the stack adds to a plain Claude Code install, how it is configured, and what backs each claimed
benefit. Every benefit below names an artifact you can check: a guard rule, a test, a knob, a measured
number with its n, or a bug in [CONFIG.md](CONFIG.md) §1. Where a benefit is the intent of a design and
nothing has measured it, the text says **by design, not measured**. No run has yet compared this stack
with plain Claude Code on the same tasks ([Measured so far](#measured-so-far)).

[Architecture](#architecture) · [Agent tiers and routing](#agent-tiers-and-routing) ·
[Tools and MCP per agent](#tools-and-mcp-per-agent) · [Skills at a glance](#skills-at-a-glance) ·
[Hooks at a glance](#hooks-at-a-glance) · [Commands and CLIs](#commands-and-clis) ·
[Safety and guardrails](#safety-and-guardrails) · [Cost and context control](#cost-and-context-control) ·
[Reliability and verification](#reliability-and-verification) · [Observability](#observability) ·
[Main knobs](#main-knobs) · [Compared with plain Claude Code](#compared-with-plain-claude-code) ·
[Measured so far](#measured-so-far) · [Known limits](#known-limits) ·
[Planned, not shipped](#planned-not-shipped)

### Architecture

Three kinds of agent, eight levels below the main thread, one policy hook; the diagram is at the
[top of this page](#claude-agent-stack).

| Level | Who runs there | Limit (enforced by) |
|---|---|---|
| Main thread | BlackCat (`dot-claude/agents/blackcat.md`; `"agent": "blackcat"` in `settings.json`) | 24 tool calls per prompt, at most 8 of them Agent calls within 120 s and at most 3 Read calls; no Bash, Write or Edit: it only delegates (`BLACKCAT_MAX_STEPS`, `BLACKCAT_MAX_DISPATCH`, `BLACKCAT_DISPATCH_WINDOW_S`, `BLACKCAT_MAX_READS`, `BLACKCAT_MAX_OWN_STEPS` 0); its children always run in the background (`BLACKCAT_BACKGROUND`) |
| L1 to L7 | Any agent whose `POLICY` row allows the spawn | 3 running children per agent by default, more for coordinators (`STACK_MAX_FANOUT`, `STACK_MAX_FANOUT_BY_TYPE`); 33 subagents running at once per session (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`; Claude Code's default is 20) |
| L8 | Leaves by position | cannot spawn (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=8`) |

BlackCat's own tools, as `blackcat.md` lists them: an `Agent(...)` allowlist of 52 agent types (every
specialist except supreme-coder, db-engineer and localizer), SendMessage, AskUserQuestion,
`mcp__conductor__AskUserQuestion`, ExitPlanMode, TaskStop, ListAgents, ToolSearch, Skill, Workflow, the
Cron and wake-up tools, RemoteTrigger, PushNotification, SendUserFile, and Read. It holds no Bash, Write,
Edit, WebSearch or WebFetch, and blackcat-guard refuses a Bash, Write or Edit call that still reaches it
(`BLACKCAT_MAX_OWN_STEPS` 0). It reads only the delegation ledger, a plan or a child's output file (at most
3 Read calls per prompt, `BLACKCAT_MAX_READS`) and dispatches everything else, however small: merges,
tests, commits and bookkeeping to main-coder, one command or a small edit to coder, finding or reading
files to explore. Routing rules and the spawn table: [Roster](#roster) and [CONFIG.md](CONFIG.md) §4.

### Agent tiers and routing

Rule in `blackcat.md`: "cheapest capable wins". Each ladder starts at the cheapest agent that can do the
job and escalates on failure or on a harder deliverable.

| Need | Ladder, cheapest first (model · effort · maxTurns) | Notes |
|---|---|---|
| Knowledge | oracle (Opus · low · 12, no web) < scout (Sonnet · low · 11) < researcher (Opus · high · 130) | oracle answers timeless questions from Read and Skill only; scout looks up one current fact |
| Code | coder (Sonnet · medium · 170) < main-coder (Opus · xhigh · 350) < ninja-coder (Opus · max · 300) < supreme-coder (Opus · max · 350) | supreme-coder: only the orchestrator spawns it, once per session, after a ninja-coder of the session finished (`SUPREME_SPAWNERS`, `SUPREME_ONCE_PER_SESSION`, `SUPREME_AFTER_NINJA`) |
| Codebase questions | explore (Sonnet · low · 40, read-only tools) | replaces the built-in Explore (`CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1`) |
| Language-heavy code | rust-, haskell-, julia-, go-, python-, jvm-, node-engineer (Opus · high · 170) | each self-checks with its toolchain |
| Domain builds | 25 domain experts ([Roster](#roster)) | ML, GPU, HPC, robotics, design, 3D, video, documents, … |
| Checks | code-reviewer, verifier, security-auditor, proof-checker, plan-reviewer | read-only (hook-enforced, below) |
| Narrow jobs | test-engineer, build-fixer, db-engineer, localizer | leaves; db-engineer and localizer only through their family heads |

Every agent names `opus` or `sonnet` (41 and 15; `tests/lint_agents.py` rejects anything else), and the
IDs come from `stack.env`. That Sonnet on bounded work lowers cost without lowering quality is **by
design, not measured**: no cost is recorded for any run (baseline, §10).

### Tools and MCP per agent

Each agent's `tools:` line is its whole tool set, so an agent cannot use a tool it was not given.

| Class | Agents (examples) | Tools | What is withheld |
|---|---|---|---|
| Main thread | blackcat | Agent allowlist, SendMessage, AskUserQuestion, Read, … (above) | Bash, Write, Edit, web tools |
| Coordinator | orchestrator | Agent, SendMessage, TaskStop, Read, Glob, Grep, Write, Edit, Skill, `mcp__neural-memory` | Bash, web |
| Knowledge without web | oracle | Read, Skill | everything else |
| Codebase search | explore | Read, Grep, Glob, LSP, Skill | Bash, Write, Edit, web |
| Read-only checks | code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide, proof-checker | Read, Bash (read-only commands only: `READONLY_TYPES` in `agent_guard.py`), web where needed | Write, Edit, Agent |
| Builders | coder, main-coder, the language and domain engineers | Read, Write, Edit, Bash, LSP, plus Agent when they have a `POLICY` row | per agent: web, MCP servers |
| Leaves | 16 agents without the Agent tool (CONFIG.md §4) | — | Agent |

MCP servers come in three scopes ([MCP servers](#mcp-servers) lists every one):

- **Agent-scoped (17):** declared inline in one agent's `mcpServers`; they start and stop with that agent and
  cost nothing elsewhere.
- **User scope (5 remote: exa, jina, wolfram, huggingface, wandb):** session-wide, but only an agent whose
  `tools:` line names the server can call it.
- **magg catalog (23, all disabled):** mcp-broker mounts one on request through magg; mounting always asks
  you, and calls of all but the read-only or local servers ask at every call.

Each subagent may make at most 64 MCP calls per prompt (`STACK_MAX_MCP_CALLS`), and `hooks/web_caps.py`
clamps result counts, characters and crawl depth of every exa, jina and spider call.

### Skills at a glance

214 skills in three shapes (24 hubs, 98 modules, 92 standalone); none is preloaded, and a body enters
context only when an agent loads it. The 83 hub modules are hidden from the listing every spawn carries
and are read by path. Detail: [Skills: hubs, modules, references](#skills-hubs-modules-references); the
listing's size against its budget: [Prompt budget](#prompt-budget).

### Hooks at a glance

Every hook runs on an absolute interpreter chosen at install time; a PreToolUse handler that errors denies
the call. Wiring: `dot-claude/settings.json` → `hooks`.

| Script | Events | Does |
|---|---|---|
| `hooks/agent_guard.py` | every wired event except SessionEnd | Spawn policy, depth, fan-out, BlackCat caps, supreme-coder lock, no push, protected paths, read-only Bash, credential reads, token budgets, soft limits, MCP cap, web taint, image limit, the delegation ledger and its compaction snapshot, labels, the SubagentStop check of each final report (observe only: records, never blocks), `/override-agent`, the sandboxed Bash environment. Module docstring: the event-by-event table |
| `hooks/read_gate.py` | PreToolUse `Read\|Grep\|Glob\|Bash` | Refuses the first read of build output, dependencies, large data, media or binaries with a cheaper alternative; the identical retry passes ([CONFIG.md](CONFIG.md) §5, "Read gate") |
| `hooks/web_caps.py` | PreToolUse `^mcp__(exa\|jina\|spider)__` | Caps per call; refuses spider `cron`, `webhooks`, `run_in_background` |
| `hooks/stack_usage.py` | SubagentStart, SessionEnd; started from the guard's SessionStart too | A background collector that writes rows per agent segment, per prompt window and per session to `usage/runs3.csv` (numbers, ids and a few plain words of the task; no prompt or transcript text) |
| `hooks/stack_limits.py` | via the guard's SessionStart | Learned limits: freezes one snapshot per session from `live.json`, inside repo floors and ceilings |
| `hooks/stack_sched_refresh.py` | at the collector's exit | Refits the scheduler's cost model, at most × 1.5 per refresh |
| `bin/doctor.sh --hook`, `bin/stack-tree --hook` | UserPromptExpansion | Answer `/stack-doctor` and `/stack-tree` without a model turn |
| `bin/statusline.py` | `statusLine` | Agent, model, effort, context against the auto-compact window, rate limits |

### Commands and CLIs

| Command | Where | Does |
|---|---|---|
| `/stack-doctor` | any session | Read-only health check, run outside the sandbox by a hook ([Commands](#commands)) |
| `/stack-tree`, `/stack-tree table`, `/stack-tree static` | any session | This session's agent tree with each agent's commands; the same as a table; the designed hierarchy from the agent files |
| `/override-agent <agent> <model>`, `list`, `reset` | any session, typed by you | Per-session model override for one delegated agent type; the effort is shown, not applied |
| `stack-budget [--all]`, `plan GRAPH.json`, `agent TYPE`, `static` | `/usr/bin/python3 ~/.claude/bin/stack-budget` | Read-only view of this session's frozen limits and use, with three-way verdicts (fits, does not fit, uncertain); no slash command ([CONFIG.md](CONFIG.md) §5) |
| `stack_limits.py show`, `history`, `stability`, `hold`, `freeze`, `rollback`, `propose`, … | `~/.claude/hooks/`, your terminal | Inspect or pin the learned limits; changes reach the next session's snapshot |
| `stack_usage.py status`, `runs`, `refresh`, `propose` | `~/.claude/hooks/`, your terminal | Collector state, per-agent runs, a manual refit, drift report |
| `stack_sched.py plan`, `next`, `replay` | `uv run --script dot-claude/hooks/stack_sched.py` | Scheduler advisor: waves for a task graph; a report tool that no hook reads |
| `agent_guard.py delegations [session] [--json]`, `--print-policy`, `--self-test` | `/usr/bin/python3 ~/.claude/hooks/agent_guard.py` | The delegation ledger; the spawn table; the guard's own checks |
| `claude-ninja`, `claude-supreme` (links in `~/.local/bin`); `claude-ultracode <agent>` | `~/.claude/bin/claude-ultracode` | ninja-coder or supreme-coder as your main thread at ultracode, starting in Plan (`--permission-mode plan` unless you pass a mode) |
| `stack_sdk.py "task" --agent … --max-turns … --budget-usd …` | `~/.claude/bin/` | The stack from an Agent SDK app ([Your own Agent SDK app](#your-own-agent-sdk-app)) |
| `stack-update-tools [--dry-run]` | `~/.claude/bin/`, your terminal | Updates the installed toolchains together: `brew update && brew upgrade --formula`, `rustup update`, `juliaup update`, `ghcup upgrade`, `uv self update` + `uv tool upgrade --all`, `cs update`, `elan self update` + `elan update`; node and Homebrew casks (`brew upgrade --cask`: the pkg casks ask for your password) are printed as manual steps ([CONFIG.md](CONFIG.md) §7, "Prerequisites and toolchains") |

### Safety and guardrails

The Bash sandbox is meant to be the boundary; the guard's shell parsing is defence in depth; prompts are
the first line, not a guarantee ([Security model](#security-model)).

| Guard | Enforced by | Proof in the repo |
|---|---|---|
| Agents never push and never write to a forge (`gh`/`tea`/`fj`, `gh api`, curl/wget/httpie to forge hosts), also inside `bash -c`, `eval`, `$(...)` | `agent_guard.py no-push`; `STACK_POLICY=off` does not lift it | `tests/test_no_push.py` |
| No Bash write, delete or rename of the installed stack, the backups or the hook state; no `install.sh` run except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs | the guard's protected-path scan, on top of the Edit/Write deny rules | `tests/test_protected_paths.py`, `tests/test_guard_round2.py` |
| Six review and check types run read-only Bash only; their scratch code is content-checked | `READONLY_TYPES` | `tests/test_readonly_agents.py` |
| Only stack agents in the caller's row may be spawned (a main thread without a row: any stack agent); `general-purpose`, `claude`, `fork`, `Plan` and unknown types are refused | `POLICY`, deny rules `Agent(general-purpose)`, `Agent(claude)`, `Agent(fork)` | `tests/test_agent_guard.py`; `tests/lint_agents.py` checks each "May spawn" sentence against `POLICY` |
| BlackCat only delegates (any other agent on the main thread keeps its tools): its tools line holds no Bash, Write or Edit, and a call that still reaches it (an SDK app's tool list, an `--agents` redefinition) is refused; with `BLACKCAT_MAX_OWN_STEPS` > 0 its Bash gets the same hooks, sandbox and deny rules and is refused HTTP clients, raw sockets and gh reads (best effort; the sandbox allowlist is the hard limit) | tools line, `blackcat-guard`, `no-push` | `tests/test_blackcat_tools.py`, `tests/lint_agents.py` |
| No credential reads (`gh auth token`, `git credential fill`, keychain dumps); token variables and credential files denied to sandboxed Bash | guard, sandbox `denyRead`, credential deny list | `tests/test_guard_round2.py` |
| An agent that read web content, or is linked to one that did, cannot write the shared memory | web taint in the guard | `tests/test_guard_round2.py`, `tests/test_guard_round3.py` |
| Mounting a magg server asks; calls run without a prompt only for the read-only or local catalog servers and ask at every call for the rest | `ask` rules in `settings.json` | `tests/test_no_duplicates.py` (exactly one allow or ask rule per catalog prefix) |
| 19 MCP servers run without a prompt; `mongodb`, `postgres` and `claude-in-chrome` prompt at each call (denied in headless runs) | whole-server `allow` rules in `settings.json`, none for the three | `tests/test_permission_modes.py` (the exact allowed set, no allow or deny rule for the three, no shipped ask or deny rule on an allowed server, every agent's MCP server decided) |
| Images an agent sees or uploads stay ≤ 1919 px | `agent_guard.py image-limit` | `tests/test_image_limit.py` |
| libdocs checks every fetch that is not a fixed API endpoint against SSRF | `mcp/libdocs_mcp.py` | `tests/test_libdocs_mcp.py` |
| Bash runs sandboxed, no unsandboxed fallback, Claude Code exits if the sandbox cannot start | `sandbox.enabled`, `allowUnsandboxedCommands: false`, `failIfUnavailable: true` | configured, **not live-verified** ([Live checks](#live-checks)) |
| Consent for destructive or external actions comes only from you, through BlackCat's AskUserQuestion | rules and agent prompts | **by design, not measured**; not hook-enforced |

### Cost and context control

| Mechanism | What it does | Evidence |
|---|---|---|
| Static prompt budget | `tests/prompt_budget.py --check` fails when descriptions, bodies, rules or listings grow past gates set against revision `ad22962` | Measured (static characters, 2026-10-03, the revision that gave BlackCat its own tools vs `ad22962`; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)): skill listing 30,782 → 14,437 chars (−53.1 %), mostly because the 83 hub modules are no longer listed and the skill count went from 248 to 214; mean per-spawn prompt 55,240 → 37,527 chars (−32.1 %). Both revisions are this stack, so this is not a comparison with plain Claude Code, and whether skill discovery or answer quality changed is not measured |
| Delegate-only BlackCat | BlackCat runs no commands and edits nothing (no Bash/Write/Edit on its tools line; blackcat-guard refuses them); every job, however small, goes to a specialist | **enforced by tools line and hook; the cost of spawning for small jobs is not measured** |
| Output economy | Global rules: answer first, no preamble or closing summary, big artifacts to files, a clean finish in one line | **by design, not measured** |
| Read gate | First read of build output, dependencies, big data, media or binaries is refused with a cheaper alternative | **by design, not measured** (no token saving recorded) |
| Web caps | Per-call result and character caps for exa, jina, spider | **by design, not measured** |
| maxTurns | Set from measured turn counts: at least 1.5 × the p90 where one exists (163 segments of two sessions, 2026-10-02) | CONFIG.md §3; most types have fewer than 5 runs |
| Soft token limits | Past a per-type limit an agent's next tool call carries one warning to wrap up and return `STATUS: partial`; nothing is refused | Values derived from p90 of healthy segments; all but claude-code-engineer and scout provisional (CONFIG.md §5). Effect on spend: not measured |
| Hard budgets | Context tokens per human prompt and per session, whole tree (seeds 100,000,000 and 1,920,000,000); past them every call but reporting is refused | `tests/test_limits_guard.py`, `tests/test_stack_limits.py` |
| Learned limits | `stack_limits.py` proposes new turn and token limits from the collector's rows; a session's limits are frozen at its start, inside repo floors and ceilings; `install.sh` moves a variable that never learned (status unset, not frozen or held now, never rolled back) to a changed seed and keeps every other value; fan-out, depth and the MCP cap are fixed guards that never learn (`FIXED_GUARDS`) | `tests/test_stack_limits.py`, `tests/test_sched_snapshot.py`. Calibration on held-out data: only the scheduler replay has one (`tests/derive_wave_sim.py`; with parameters fitted on another session, 16 of 19 replay windows land within 2 %, pinned in `tests/test_stack_sched.py`). A prototype run found the soft limits run hot (10.3 % cap-hit against a 5 % target; unreviewed, campaign worktree only) |
| Fan-out caps | Running children per agent, copies per type, BlackCat per prompt; a background subtree silent for 600 s stops counting (`STACK_FANOUT_IDLE_S`); session slots against `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` (`STACK_FANOUT_SESSION`, shadow by default); a dynamic cap per orchestrator job (`STACK_FANOUT_DYN`, off by default) | `tests/test_agent_guard.py`, `tests/test_guard_regressions.py`, `tests/test_fanout_session.py`, `tests/test_fanout_dyn_wiring.py` |
| Scheduler advisor | `stack_sched.py` plans waves under the caps and checks a plan against the limits; advice only (`STACK_SCHED_POLICY=report`) | `tests/test_stack_sched.py`; no behaviour depends on it |
| Model tiering | Sonnet for lookups, loops and verification; Opus where judgment is the product | **by design, not measured** |

### Reliability and verification

From the global rules (`dot-claude/rules/claude-agent-stack.md`), summarised in
[Review protocol and reports](#review-protocol-and-reports):

- **Self-check:** a builder runs tests, linters and type checks on what it changed and re-reads its diff
  before reporting.
- **Independent review only on a trigger** (security surface, data loss, concurrency, public API, large
  diff, numerical or proof core, no runnable tests, CI/hooks/permissions, published output), one reviewer
  per trigger class.
- **Evidence-gated round trips:** work goes back only with a failing command, a reproduced bug or a
  verified discrepancy; two failed rounds escalate one tier.
- **Report format:** a one-line clean finish, or a `STATUS / RESULT / EVIDENCE / FILES / NEXT` block that
  callers relay. In the graded baseline, 3 of 40 runs claimed done but were not graded pass (§4 of
  the baseline).

These rules are prompts: their effect on quality is **by design, not measured** beyond the baseline
figures below. What the repo's tests prove is the machinery:

| Suite | Proves |
|---|---|
| `agent_guard.py --self-test`; `tests/test_agent_guard.py`, `test_guard_regressions.py`, `test_guard_round2.py`, `test_guard_round3.py`, `test_blackcat_tools.py` | Spawn policy, depth, fan-out, locks, BlackCat's own tools, security rounds 2 and 3 |
| `tests/test_no_push.py`, `test_protected_paths.py`, `test_readonly_agents.py` | No push, protected paths, read-only Bash |
| `tests/test_limits_guard.py`, `test_stack_limits.py`, `test_stack_usage.py`, `test_sched_snapshot.py`, `test_stack_sched.py` | Budgets, learned limits and snapshots, the collector, the scheduler |
| `tests/test_stack_budget.py`, `test_stack_budget_security.py`, `test_stack_tree.py`, `test_stack_doctor.py`, `test_override_agent.py` | The user commands, including read-only behaviour and escaping of untrusted text |
| `tests/test_read_gate.py`, `test_web_caps.py`, `test_image_limit.py`, `test_libdocs_mcp.py`, `test_image_studio_mcp.py`, `test_mcp_headers.py` | Gates, caps and the stack's MCP servers |
| `tests/lint_agents.py`, `tests/prompt_budget.py --check`, `test_skill_modules.py`, `test_no_duplicates.py` | Frontmatter, `POLICY` ↔ "May spawn", model aliases, skill layout, prompt sizes |
| `tests/install_smoke.sh`, `test_install_state.py` | Hermetic installer runs: dry run, restore round trips, pruning, symlinked dirs |

How to run them: [Verify](#verify).

### Observability

| Question | Where to look |
|---|---|
| Who is working on what, with which commands, for how many tokens | `/stack-tree` (or `stack-tree --table`) |
| The delegation tree as recorded by the guard | `~/.local/state/claude-agent-stack/<session>/delegations.md`; `agent_guard.py delegations` |
| Limits in force and use so far | `stack-budget`; decisions in `limits/history.jsonl` under the state dir |
| Per-agent turns and tokens over sessions | `stack_usage.py runs`; `usage/runs3.csv` |
| Each final report's status, size and checks (no report text) | `usage/reports.jsonl`; full copies in the session's `reports/` ([CONFIG.md](CONFIG.md) §5, "Message protocol") |
| Installation health | `/stack-doctor` |
| Context left before auto-compaction | the status line |
| Hook events | `STACK_GUARD_LOG=1`; `/override-agent` changes in `agent-overrides.log` |

### Main knobs

The full list is in [Knobs](#knobs) and [CONFIG.md](CONFIG.md) §5. The ones most often changed:

| Knob | Default | Effect |
|---|---|---|
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` (in `stack.env`) | today's IDs | What the `opus` and `sonnet` aliases run; re-run the installer |
| `STACK_MAX_FANOUT`, `STACK_MAX_FANOUT_BY_TYPE` | 3; orchestrator 32, main-/supreme-coder 6, ninja-coder 5, researcher 4, planner and plan-reviewer 8 | Running children per agent |
| `BLACKCAT_MAX_DISPATCH`, `BLACKCAT_MAX_STEPS`, `BLACKCAT_MAX_READS`, `BLACKCAT_MAX_OWN_STEPS` | 8, 24, 3, 0 | BlackCat's Agent calls, all tool calls, Read calls and own Bash/Write/Edit calls (0: it only delegates) per prompt |
| `STACK_PROMPT_CTX_BUDGET`, `STACK_SESSION_CTX_BUDGET` | learned (seeds 100,000,000 / 1,920,000,000) | Hard context budgets; a value you set pins them |
| `STACK_SOFT_LIMIT_SCALE` | 1 | Multiplies every soft limit; `0` turns them off |
| `STACK_MAX_MCP_CALLS` | 64 | MCP calls per subagent per prompt |
| `READ_GATE` (in `stack.env` or the environment) | 1 | `0` turns the read gate off |
| `STACK_POLICY` | `on` | `off` lifts the spawn, budget, lock and read-only-Bash guards; the no-push hook's refusals (forge writes, protected-path writes, credential reads, `install.sh`) stay on. It also lifts blackcat-guard (BlackCat's step, dispatch and read caps and its tool allowlist): only BlackCat's tools line still keeps Bash, Write and Edit from it |
| `autoCompactWindow` (settings key) | 629000 | Compaction at about 629K tokens on the 1M-context models |
| `permissions.defaultMode` (settings key) | `plan` | The mode every session starts in; a mode you set is kept on upgrade ([Permission modes](#permission-modes)) |

### Compared with plain Claude Code

"Plain" means Claude Code with no user settings, agents or hooks; its defaults are from the Claude Code
docs ([sandboxing](https://code.claude.com/docs/en/sandboxing),
[sub-agents](https://code.claude.com/docs/en/sub-agents),
[env vars](https://code.claude.com/docs/en/env-vars), read 2026-10-03). The right-hand column says
whether the difference is enforced and tested, or a design intent.

| Area | Plain Claude Code | This stack | Status |
|---|---|---|---|
| Delegation | Built-in general-purpose, Explore and Plan subagents | 55 specialists with per-agent tools, models and turn caps; generic types refused | Enforced: `POLICY`, `tests/test_agent_guard.py` |
| Nesting and concurrency | Depth 3, 20 subagents running at once | Depth 4, 33 at once, per-agent fan-out caps and spawn rows | Enforced: settings, guard |
| Push and forge writes | Governed by your permission rules | Refused for every agent, whatever the rules or `STACK_POLICY` | Enforced: `tests/test_no_push.py` |
| Writes to config and state | Protected-path writes are not prompted in `bypassPermissions` (docs); per the guard's docstring, Claude Code's check does not cover Bash writes (unverified against the docs) | Bash-level writes refused too | Enforced: `tests/test_protected_paths.py` |
| Bash sandbox | Off by default; falls back to unsandboxed commands when it cannot start | On, no unsandboxed fallback, exit if unavailable, credential paths denied | Configured, not live-verified |
| Reviewers | No read-only reviewer types | Six read-only types with a command allowlist | Enforced: `tests/test_readonly_agents.py` |
| Token spend | No per-prompt, per-session or per-agent context budget in a default install | Hard budgets, soft warnings, turn gate, MCP cap, read gate, web caps | Enforced (budgets, caps); savings **by design, not measured** |
| Prompt size per spawn | — | Gated by `tests/prompt_budget.py`; −32.1 % static per-spawn characters vs this stack's own `ad22962` | Measured, static only |
| Visibility | Session transcripts | `/stack-tree`, delegation ledger, `stack-budget`, usage rows, status line | Shipped, tested |
| Answer quality | — | Routing, self-check, evidence-gated review | **by design, not measured** against plain Claude Code |

### Measured so far

One frozen baseline exists: `stats_before.md` (schema 1.0.0, frozen 2026-10-03, regenerable by
`compute_stats.py`; protocol for a later comparison in `COMPARE.md` beside it), kept with the campaign
data outside this repository. It compares two versions of this stack, not the stack with plain Claude Code.

| Cell | Runs | Graded | Result |
|---|---|---|---|
| Older install, prompt set v1 (session `4e2da3ce`) | 40 | 40 | 30 pass, 6 partial, 0 fail, 4 tool-absent: pass rate 30/40 = 0.75 (Wilson 95 % [0.60, 0.86]); 30/36 = 0.83 excluding tool-absent |
| Newer install (2026-10-03 hand-off), v1 | 24 | 0 | ungraded |
| Newer install (2026-10-03 hand-off), v2 | 13 | 0 | ungraded |

Other figures in that file: in the graded runs 3/40 overclaimed (said done, not graded pass) and 1/40
underclaimed. On the 13 prompts run on both installs, the newer one took longer (median log2 ratio of
duration +1.01, 95 % CI [+0.07, +1.62]); total tokens did not differ clearly (+0.29, CI [−0.56, +1.32]).

Read these as **the baseline measured so far, not as evidence of improvement**. The file's own caveats:
one run per prompt and no replicates; 1 to 13 runs per agent type; the newer install's runs are not
graded; install, agent type and model changed together; some graders could not re-run tests under the
read-only guard; one grader per batch with known rubric ambiguity; cost was not recorded for any run.
Both installs predate BlackCat's own tools. The revisions (the newer install is the 2026-10-03 RESUME.md
hand-off commit; BlackCat got its tools in "BlackCat does small jobs itself") are in the commit history
in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md).

### Known limits

- **Sandbox not live-verified.** Until you run the [Live checks](#live-checks), count only the guard and the
  deny rules as tested.
- **Shell parsing is a heuristic.** Read-only Bash, protected paths, no push and BlackCat's no-web check
  parse shell text; arbitrary code that talks to the keychain or sends a token itself is not caught
  ([CONFIG.md](CONFIG.md) §7, "Residual risks").
- **`SUPREME_AFTER_NINJA` checks order, not failure.** Any finished ninja-coder run unlocks the supreme-coder spawn;
  that ninja-coder failed rests on prompts.
- **The effort of an `/override-agent` is not applied.** The Agent tool has no effort input; the frontmatter
  effort still runs.
- **Small samples.** Soft limits and maxTurns rest on two sessions; most types have fewer than 5 healthy
  segments.
- **Test failures inside the Claude Code sandbox** (full suite on 2026-10-03 after the `/stack-tree`
  review fixes: 3119 passed, 2 failed, 1 skipped; run by the author, not reproducible from the repo;
  3188 tests are collected after the supreme-coder rename review fixes; see the commit history in
  [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)): `test_four_tools_and_three_model_settings` in `tests/test_image_studio_mcp.py`
  (the sandbox denies reading `~/.claude/stack.env`) and one `f4` case in `tests/test_protected_paths.py`
  (pytest's temp dir sits under `/tmp/claude-501`). Two cases of `test_three_way_verdict_on_the_soft_limit`
  fail when `STACK_LIMITS_SNAPSHOT` is set.
- **macOS only**: see [Requirements (macOS only)](#requirements-macos-only).

### Planned, not shipped

Not on `main`; listed so nobody mistakes them for features:

- **Bayesian limits.** A design and a prototype fit for learning turn and token limits with risk targets
  exist only in a campaign worktree; three of its models fail their divergence gates, and it has not been
  reviewed.
- **Like-for-like before/after comparison** (grading the 37 newer-install runs, then after-runs per
  `COMPARE.md`): not run.
- **A Pareto cost-quality analysis:** only a descriptive tokens-vs-pass front on the 40 graded
  old-install runs exists (stats_before.md §5); cost is not recorded.
- **Applying the override effort** through per-(agent, model) agent variants: not built, and the user
  decided against it (no agent variants; [CONFIG.md](CONFIG.md) §9, 2026-10-03).
- **`stack_sched.py emit-workflow`:** disabled until a probe; a periodic refit outside sessions is possible
  but not installed.

## How it works

### Roster

Every agent names one of two model aliases: `opus` where judgment is the product, `sonnet` for bounded
execution, lookups and tool loops (41 Opus, 15 Sonnet; `tests/lint_agents.py` rejects any other value
and the hook strips a per-call `model`). The alias is the reference; it resolves to
`ANTHROPIC_DEFAULT_<FAMILY>_MODEL`, which `stack.env` sets and the installer copies into
`settings.json` (CONFIG.md section 2). An agent file's `effort` applies only when the
agent runs as a subagent; the main thread uses the session's level (`/effort medium` for BlackCat).
The tables are generated from `dot-claude/agents/*.md` frontmatter. "Does" is shortened from each
agent's `description`. The installer also renders `researcher-copy` and `coder-copy` from their base
files. Spawn rows ("May spawn") live in `POLICY` in `agent_guard.py` ([CONFIG.md](CONFIG.md) §4).

<details>
<summary>Roster tables: 56 agents by family (model, effort, maxTurns, inline MCP)</summary>

#### Role agents (20)

| Agent | Model · effort | maxTurns | Inline MCP | Does |
|---|---|---|---|---|
| blackcat | Sonnet 5.5 · medium (session) | — | — | Main thread: only delegates (no Bash, Write or Edit; Read ≤ 3 per prompt), routes everything |
| orchestrator | Opus 5.5 · high | 200 | neural-memory | Coordinates work needing several specialists or dependent steps |
| planner | Opus 5.5 · xhigh | 60 | libdocs | Plans before anything is built |
| plan-reviewer | Opus 5.5 · high | 60 | libdocs | Critiques a plan against the goal, the code and current docs |
| oracle | Opus 5.5 · low | 12 | — | Answers timeless questions from expertise alone |
| scout | Sonnet 5.5 · low | 11 | — | Fast lookup of one current fact |
| explore | Sonnet 5.5 · low | 40 | — | Read-only codebase search: files, symbols, call sites |
| researcher | Opus 5.5 · high | 130 | neural-memory, context-mode, spider | Deep research: multi-source investigations, comparisons |
| coder | Sonnet 5.5 · medium | 170 | libdocs | Implementer for small and medium code tasks |
| main-coder | Opus 5.5 · xhigh | 350 | libdocs, neural-memory | Main engineer for cross-cutting code: large codebases |
| ninja-coder | Opus 5.5 · max | 300 | libdocs, neural-memory | Engineer-mathematician for the hardest code |
| supreme-coder | Opus 5.5 · max | 350 | libdocs, neural-memory | Last-resort engineer after ninja-coder failed |
| code-reviewer | Opus 5.5 · high | 80 | libdocs | Reviews diffs, PRs or codebases; read-only |
| verifier | Sonnet 5.5 · high | 140 | playwright | Independent verification: runs tests and builds; read-only |
| security-auditor | Opus 5.5 · xhigh | 100 | — | Security review: threat models, vulnerable code; read-only |
| proof-checker | Opus 5.5 · xhigh | 80 | lean | Referees proofs, derivations, correctness and complexity arguments |
| browser-operator | Sonnet 5.5 · medium | 120 | playwright | Acts on web pages: logged-in sites via Claude in Chrome |
| mcp-broker | Sonnet 5.5 · medium | 60 | magg | Vets and mounts MCP servers on demand through magg |
| claude-code-engineer | Opus 5.5 · high | 150 | — | Builds Claude Code configuration: skills, subagents, hooks |
| claude-code-guide | Sonnet 5.5 · low | 30 | — | Answers Claude Code, Agent SDK and Claude API questions |

#### Language engineers (7)

| Agent | Model · effort | maxTurns | Inline MCP | Does |
|---|---|---|---|---|
| rust-engineer | Opus 5.5 · high | 170 | libdocs | Rust expert: idiomatic crates and workspaces, async |
| haskell-engineer | Opus 5.5 · high | 170 | libdocs | Haskell expert: GHCup, cabal or stack, types and laziness |
| julia-engineer | Opus 5.5 · high | 170 | libdocs | Julia expert: juliaup, Pkg environments, type-stable code |
| go-engineer | Opus 5.5 · high | 170 | libdocs | Go expert: modules, concurrency, the go toolchain |
| python-engineer | Opus 5.5 · high | 170 | libdocs | Python expert on uv: packaging, typing, pytest, asyncio |
| jvm-engineer | Opus 5.5 · high | 170 | libdocs | JVM expert, Java first, plus Kotlin and Scala |
| node-engineer | Opus 5.5 · high | 170 | libdocs | Node.js and TypeScript backends and CLIs: pnpm, tsc |

#### Domain experts (25)

| Agent | Model · effort | maxTurns | Inline MCP | Does |
|---|---|---|---|---|
| biochem-engineer | Opus 5.5 · high | 170 | libdocs | Computational biology and chemistry |
| cg-artist | Opus 5.5 · medium | 150 | libdocs, blender | 3D in Blender, ZBrush, Substance |
| cuda-engineer | Opus 5.5 · high | 190 | libdocs | NVIDIA GPU systems: CUDA and Triton kernels |
| data-engineer | Sonnet 5.5 · high | 150 | libdocs | Data and databases: PostgreSQL, SQLite, DuckDB, MongoDB |
| data-scientist | Opus 5.5 · high | 150 | libdocs, neural-memory | Statistics for decisions |
| designer | Opus 5.5 · high | 150 | image-studio, illustrator, huetension | Visual design: logos, brand identity, illustration, layout |
| devops-engineer | Sonnet 5.5 · high | 140 | libdocs | Infrastructure and delivery: CI/CD, containers, Kubernetes |
| dl-engineer | Opus 5.5 · high | 190 | libdocs, neural-memory | Deep learning: architectures, diffusion and flow models |
| doc-specialist | Sonnet 5.5 · medium | 100 | markitdown, context-mode | Office documents and PDFs |
| embedded-engineer | Opus 5.5 · high | 170 | libdocs | Firmware: MCUs in C/Rust, RTOS, probes, FPGA/HDL |
| frontend-engineer | Opus 5.5 · medium | 170 | libdocs, playwright | Web front end: HTML/CSS, TypeScript, React/Vue/Svelte/Astro |
| game-engineer | Opus 5.5 · high | 170 | libdocs | Games and real-time graphics: Godot, Unity, Unreal, Bevy |
| hpc-engineer | Opus 5.5 · high | 170 | libdocs | HPC and scientific code: PDE/FEM/CFD solvers, MPI/OpenMP |
| image-director | Opus 5.5 · medium | 80 | image-studio | Generates and edits images through image-studio |
| llm-engineer | Opus 5.5 · high | 190 | libdocs, neural-memory | LLMs: local serving, quantization, fine-tuning, evals |
| mathematician | Opus 5.5 · xhigh | 100 | neural-memory | Maths and physics, quick to research-level |
| ml-engineer | Opus 5.5 · high | 190 | libdocs, neural-memory | Classical ML: tabular, time-series and classic NLP models |
| mlx-engineer | Opus 5.5 · high | 190 | libdocs | Apple Silicon ML performance: MLX and mlx-lm internals |
| mobile-engineer | Opus 5.5 · medium | 170 | libdocs, mobilebuild | Mobile apps: Swift/SwiftUI, Kotlin/Compose, Flutter |
| motion-designer | Opus 5.5 · medium | 150 | after-effects, premiere | Motion graphics and video: After Effects, Premiere |
| quantum-engineer | Opus 5.5 · high | 160 | libdocs, neural-memory | Quantum computing and physics in code |
| robotics-engineer | Opus 5.5 · high | 190 | libdocs, neural-memory | Robotics: ROS 2, Nav2, MoveIt 2, ros2_control |
| security-engineer | Opus 5.5 · high | 150 | libdocs | Security builder: audit fixes with proofs, hardening, fuzzing |
| vfx-td | Opus 5.5 · high | 170 | — | Houdini FX: VEX, HDAs, Pyro/FLIP/Vellum/RBD, Solaris/Karma |
| writer | Opus 5.5 · medium | 80 | — | Writes and edits prose |

#### Helpers (4)

| Agent | Model · effort | maxTurns | Inline MCP | Does |
|---|---|---|---|---|
| db-engineer | Sonnet 5.5 · high | 120 | postgres, mongodb | DB tuning and ops: query plans, indexes, safe migrations |
| test-engineer | Sonnet 5.5 · medium | 100 | — | Writes and repairs tests (unit, property, fuzz, e2e) |
| build-fixer | Sonnet 5.5 · low | 60 | — | Makes a red build green |
| localizer | Sonnet 5.5 · medium | 80 | — | Translates string catalogs and subtitles |

</details>

Routing in one paragraph: BlackCat does no work itself; it answers a greeting or a setup question,
reads the ledger, dispatches every job (up to 8 children in one burst per prompt) and hands
dependent multi-specialist work to the orchestrator. Code escalates coder → main-coder →
ninja-coder → supreme-coder; language-heavy work goes to the language engineer, domain builds to the domain
expert. The helpers are leaves (no Agent tool); db-engineer and localizer are reached through their
family heads, not BlackCat. Depth is BlackCat → L1 → … → L8, and L8 cannot spawn.

### Skills: hubs, modules, references

214 skills in `dot-claude/skills/`, in three shapes (counts from `tests/test_skill_modules.py`'s own
parser):

| Shape | Count | What it is | Caps (`tests/test_skill_modules.py`) |
|---|---:|---|---|
| Hub | 24 | A `SKILL.md` with a `## Modules` table naming its modules | ≤ 80 lines |
| Module | 98 | A skill named in a hub's table; 83 are read by path, 15 listed | ≤ 150 lines, description ≤ 140 chars |
| Standalone | 92 | Neither hub nor module | ≤ 500 lines |
| `references/*.md` | 185 files | Detail a skill links to and reads only when needed | must exist where named |

- **Listed lazily, not preloaded.** 128 skills (hubs, standalone skills, 15 modules) are listed: 32
  cross-domain entries with their description, 96 by name only (below). Every description starts with
  its trigger ("Load before …", "Use when …") and names no agent; 83 hub modules are
  `user-invocable-only` (below); `stack-doctor`, `stack-tree` and `override-agent` are user commands. No
  `skills:` frontmatter preloads anything; a body enters context only when it is loaded.
- **Pointers.** Agent bodies carry a `## Skills` section of one-line "load X when Y" pointers
  (rust-engineer: "Load `rust-engineering` first; async `rust-async`, …"). Every module is reachable
  through its hub's table, and every hub is named by an agent of its family. Lint checks every name.
- **One allow rule** (`Skill`) pre-approves every skill. If you open repositories you don't trust,
  replace it with `Skill(<name>)` rules: it also approves a repository's own `.claude/skills`.

### Subagent labels

On every allowed Agent call the hook rewrites the call's `description` to `<subagent_type>: <task>`
(once; a caller's own label is kept). Claude Code shows a subagent as `agent-name(description)`, so
every caller's children read alike, at zero prompt tokens. `STACK_AGENT_LABEL` picks the mode:
`description` (default), `name` (an unnamed child gets the name `<type>-<n>`, unique per session, usable
by SendMessage) or `off`. The delegation ledger strips the label again, so its rows read the same
either way. `STACK_AGENT_STARTED=1` (default) has SubagentStart tell each stack agent its local start
time, which the clean-finish line uses.

### Review protocol and reports

From the global rules (`dot-claude/rules/claude-agent-stack.md`, "Self-check and review" and
"Reporting"):

- **Self-check.** A builder checks its own work once before reporting: tests, linters and type checks on
  what changed, the diff re-read against the done-when, no debug leftovers, ending with `date '+%F %R'`.
- **Independent review only on a trigger:** security surface, data loss, concurrency, a public API or
  schema change, a diff over ~300 lines or 8 files, an untested numerical or proof core, no runnable
  tests, CI/IaC/hooks/permissions, or output to be published. One reviewer per fired trigger class.
- **Evidence-only round trips.** Work goes back only with concrete evidence: a failing command with its
  output, a reproduced bug, a verified discrepancy (`file:line` or a quote against the claim) or a
  required item missing from the brief. Nothing verifiably wrong is a PASS. Ambiguity: state the
  assumption once and proceed. Two evidence-backed rounds still failing escalate one tier.
- **Clean finish.** Everything done, every check passed, nothing unverified: the reply is one line,
  `<input: the task in ≤ 10 words> · <YYYY-MM-DD HH:MM> · <agent type>`, then the result in ≤ 5 lines.
  Anything else uses the `STATUS / RESULT / EVIDENCE / FILES / NEXT` block. Callers relay a report
  without a STATUS line unchanged.

### On demand and automatic

Nothing costs context while idle except skill descriptions and the session's remote MCP tool names.
Summary of [CONFIG.md](CONFIG.md) §5 ("On demand and automatic"):

| Kind | Automatic (the work needs it) | On demand | Idle cost |
|---|---|---|---|
| Skills (214; 128 listed) | Listed description, plus a "load X when Y" pointer in the agent or hub | Skill tool by name; hidden hub modules by Read | The listing, on every spawn |
| MCP, agent-scoped (17 servers) | Start and stop with the agent that declares them inline | Spawn that agent | 0 elsewhere; schemas deferred |
| MCP, magg catalog (23 servers) | A one-line pointer in the agent with the gap ("cluster state → mcp-broker mounts `kubernetes`") | Ask mcp-broker | 0 until mounted |
| MCP, user scope (5 remote) | Session-wide, tools deferred until tool search loads them | — | Tool names only |
| Plugins, LSP | A language server starts when Claude touches a matching file | — | 0 listing |
| Plugins with skills | Enabled, each named by a pointer | `/plugin enable <id>`, or a project's `enabledPlugins` | Their skills' listing |

Plugins are session-wide (user, project or local scope), never per agent. No hook enables or installs
anything.

### Prompt budget

`tests/prompt_budget.py` measures what each spawn costs before it does any work: description and body
of every agent, the rules file, the skill listing and the agent listings (tokens ≈ chars / 3).
`uv run --script tests/prompt_budget.py --check` exits 1 unless:

- every description ≤ 200 characters and BlackCat's body ≤ 5,200;
- agents new since the baseline: description ≤ 160 and body ≤ 2,400 with the Agent tool, ≤ 120 and
  ≤ 1,400 as a leaf;
- against the baseline revision (`ad22962`, or `--base REV`): bodies of the agents present then ≤ 0.867×,
  agent listing ≤ 0.97×, BlackCat's listing ≤ 0.96×, skill listing ≤ 0.175×, rules ≤ 0.95×, mean
  per-spawn cost of the baseline agents ≤ 0.523×.

`--base REV` prints a delta table; `--turns` reads local transcripts for p50/p90/max turns per agent.

**Hub modules are read by path.** The 83 modules named in a hub's table (`py-typing`, `rust-async`,
`sec-web-vulns`, …) are `user-invocable-only` in `skillOverrides`: they stay out of the skill listing
every agent carries, and the Skill tool refuses them, so an agent Reads
`~/.claude/skills/<name>/SKILL.md` when its `## Skills` line (where they are marked `name`*) or the
hub's table names one. That line (`## Skills, if needed`) is a lookup, not a checklist: a task that
needs no skill reads none. Hubs, standalone skills and 15 entry-grade modules (database engines, cloud,
k8s, obs, flutter, react-native, docs-sites, wasm, linux-nvidia-cuda) stay listed. Measured in a local
evaluation (not in this repository): −8.7K characters per spawn.

**Lazy skill loading.** Only `LISTED_CORE` in `tests/test_skill_modules.py` (32 cross-domain entries:
code-standards, review-protocol, claude-code-extensions, prompt-and-brief-design, secure-coding,
shell-scripting, git, web research, tests, writing, diagrams, browser and screen, pt-PT, the main
languages, PostgreSQL/MySQL/SQLite, db-design, OTel, containers, CI, images, ffmpeg, API and algorithm
design) carries its description in the listing. The other 96 listed skills are `"name-only"` in
`skillOverrides`: the listing shows `- <name>`, the skill stays invocable, and an agent finds it by its
name or its `## Skills` line and calls the Skill tool by name; the description and body arrive with the
call. Trade-off: an agent whose Skills line doesn't name a name-only skill has only the name to go on.
Offline lookup evaluation (52 tasks, counting a name-only skill as found only when the agent's own line
names it, so a lower bound): one-call reach 98.7% (misses: hf-hub for llm-engineer, category-theory for
mathematician) for a listing of 5,306 characters instead of 14,437 (≈ 1,769 tokens instead of 4,813 on
every spawn). A new skill is name-only unless it joins `LISTED_CORE` (the test enforces it).

**`skillListingBudgetFraction` 0.012.** Claude Code caps the skill listing at context window × 3
chars per token × this fraction, and the cap is shared with plugin, bundled and claude.ai skills; over
it, the least-used skills (by your own usage history, so not deterministic) silently lose their
description. On the 1M-context 5.5 models 0.012 gives 36,000 characters: the stack's 5,433 plus ~7,213
for the others (plugins 1,663 measured, bundled ~2,550 and claude.ai ~3,000 estimated). It is headroom
only (a 200K window gets a fifth); `tests/lint_agents.py` fails when the two pass it.

**`skillListingMaxDescChars` 250** (Claude Code's default 1,536) cuts each description; the stack's are
≤ 140, so it trims only plugin, bundled and claude.ai text. **Hidden non-stack skills**
(`user-invocable-only`, still `/name` commands): Claude Code's code-review, security-review, simplify,
fewer-permission-prompts, keybindings-help, init and dataviz, and the claude.ai skills
`anthropic-skills:` deep-research, morning, import-memory, consolidate-memory, setup-claude,
explain-usage, google-workspace and schedule. The duplicate `schedule` is keyed by its full name only: a
plain `"schedule"` would hide Claude Code's own cloud-routines `/schedule`. Plugin skills
(document-skills, math-olympiad, skill-creator) ignore `skillOverrides` and stay listed at the cap.

### Guard hooks

`dot-claude/hooks/agent_guard.py` is the single policy hook. A PreToolUse handler that errors denies
the call (fail closed); every hook command runs on an absolute interpreter chosen at install time.

| Guard | What it enforces |
|---|---|
| Spawn allowlist | `subagent_type` must name a stack agent in the caller's `POLICY` row (BlackCat's row is its list; a main thread with no row of its own, such as `claude --agent claude` or a typeless session, may spawn every stack agent; a subagent with no row, none). Generic and built-in types (`general-purpose`, `claude`, `fork`, `Plan`, …), a missing type and unknown types are refused for every caller; a generic agent started outside the Agent tool has every tool call refused. Caps: 3 running children per agent (orchestrator 32, main-/supreme-coder 6, ninja-coder 5, researcher 4, planner and plan-reviewer 8), 2 live copies per copy type, BlackCat 8 dispatches within 120 s and 24 tool calls per prompt, at most 3 of them Read calls and none its own Bash/Write/Edit (`BLACKCAT_MAX_READS` 3, `BLACKCAT_MAX_OWN_STEPS` 0) |
| Read-only agents | code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide and proof-checker hold Bash, but only read-only commands pass (tests, linters in check mode, `git diff/log/show`, inspection, scanners); scratch code is content-checked; anything else is refused |
| No push | `git push` in any form and forge writes (`gh`/`tea`/`fj`, `gh api`, curl/wget/httpie to forge hosts) are denied, also inside `bash -c`, `eval`, `$(...)`, `ssh` and git's own command hooks. `STACK_POLICY=off` does not lift it |
| Protected paths | Bash-level writes, deletes and renames of the installed stack, the backups and the hook state are refused, on top of the Edit/Write deny rules; so is running `install.sh` except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs |
| Delegation ledger | Every Agent call is recorded as a tree (type, task, state, agent id) in `~/.local/state/claude-agent-stack/<session>/delegations.md`, which BlackCat reads; `agent_guard.py delegations [session] [--json]` prints it |
| Compaction survival | PreCompact snapshots the ledger with the running and unrelayed children (main-thread children that finished since the last compaction with no delivery recorded) into `<session>/compact/`; after the compaction, SessionStart (`compact`) re-renders them from the live state and adds them to the new context (≤ 9,000 characters, full list in `compact/post.md`). Never blocks a compaction; nothing is added to a session without Agent calls |
| supreme-coder once | Only the orchestrator spawns supreme-coder, once per session, and only after a ninja-coder of the session has finished (`SUPREME_SPAWNERS`, `SUPREME_ONCE_PER_SESSION`, `SUPREME_AFTER_NINJA`; the hook checks order, the prompts check that ninja-coder failed) |
| Soft token limits | Past its soft limit (context tokens per subagent run, by type: scout 390K … verifier 26M; 33M per human prompt, 80M while an orchestrator runs) an agent's next tool call carries one warning to wrap up, return `STATUS: partial` and ask before continuing; nothing is refused. Values, derivation and refresh (`tests/derive_thresholds.py`): [CONFIG.md](CONFIG.md) §5 |
| Also | Context-token budgets (hard) and the per-subagent MCP call cap; one agent on the screen; web-tainted agents can't write neural-memory; images re-encoded to ≤ 1919 px; BlackCat's children forced to the background; BlackCat holds no web tool and no Bash; with `BLACKCAT_MAX_OWN_STEPS` > 0 its Bash is refused HTTP clients in any spelling, raw sockets, `gh` forge reads and inline HTTP code (T1; best effort: script files and text assembled at run time are not seen, git clone/fetch/pull stay allowed, the sandbox network allowlist is the hard limit); per-call `model` and `mode` stripped |

The event-by-event table and the sandbox design are in [CONFIG.md](CONFIG.md) §5 and §7 and in
`agent_guard.py`'s module docstring.

## Requirements (macOS only)

The stack installs and runs on macOS only. Linux and Windows are not supported: `install.sh` stops on any
other system (`STACK_ALLOW_NON_MACOS=1` exists for the tests only). The code depends on macOS in several
places:

- the hooks run on Apple's `/usr/bin/python3` (3.9.6 from the Command Line Tools), stdlib only, and the
  installer's scripts are written for macOS's bash 3.2;
- the image limit scales images with `sips`, which ships with macOS (`doctor.sh`, "Hardware");
- the sci and tools venvs are hash-locked for `aarch64-apple-darwin` only (the ml lock is universal, but
  its torch and mlx wheels need macOS 14+; `requirements/README.md`);
- `doctor.sh` looks for GitHub credentials in the macOS Keychain (`security`, presence only);
- computer use in the CLI, the Adobe servers and the illustrator server are macOS features;
- the sandbox's `.git/modules/**` write denies take effect only on macOS (CONFIG.md §7, "Residual risks").

### Required and optional at a glance

| Requirement | Version | How to get it | Needed? | Source |
|---|---|---|---|---|
| macOS | not pinned by the stack; Claude Code needs 13.0+; `--with-ml` (torch, mlx wheels) needs 14+ | — | required | `install.sh`, [Claude Code setup](https://code.claude.com/docs/en/setup), `requirements/README.md` |
| Apple Silicon (arm64) | the sci and tools venvs are locked for arm64 wheels only; on Intel those installs are expected to fail. Intel Macs are untested: the installer picks the x86_64 builds of uv and huetension (`uname -m`) and looks for Homebrew tools under both `/opt/homebrew` and `/usr/local`, but nothing has run there | — | required in practice | `requirements/README.md`, `install.sh` |
| Xcode Command Line Tools | `python3` ≥ 3.8 that really runs, `git` | `xcode-select --install` | required | `install.sh` step 1 |
| Claude Code | ≥ 2.1.271 (older warns) | `curl -fsSL https://claude.ai/install.sh \| bash`, or the Homebrew cask `claude-code` | required | `install.sh` (`MIN_CLAUDE`), [setup docs](https://code.claude.com/docs/en/setup) |
| A Claude account with Claude Code access | — | [setup docs](https://code.claude.com/docs/en/setup) | required | — |
| uv | no minimum is checked; the checksummed tarball fallback is 0.12.20 | astral.sh's installer, else the checksummed release tarball into `~/.local/bin` | required (installed if missing) | `lib/devtools.sh` (`UV_VERSION`) |
| Node.js with `npx` | ≥ 22.5 | nvm v0.40.8, then `nvm install 24` | required (installed if missing; still missing, the installer stops) | `lib/devtools.sh`, `doctor.sh` |
| magg | 1.2.1 | installed by `install.sh` (`uv tool install`) | required (`doctor.sh` FAILs without) | `install.sh` (`MAGG_VERSION`) |
| sci and tools venvs (Python 3.13, hash-locked) | `requirements/sci.txt`, `requirements/tools.txt` | installed by `install.sh` under `~/.claude/venvs/` | required (`doctor.sh` FAILs without) | `install.sh` step 2 |
| Homebrew | — | installed by step 2 when missing (its official installer, on a terminal only: it asks for your password) | optional; installs the plain programs below in one batch | `lib/devtools.sh` |
| huetension | 0.3.0 | installed by `install.sh` | optional (designer's colour server) | `install.sh` |
| ffmpeg, ImageMagick, librsvg, poppler | — | brew batch | optional (media, SVG and PDF work; `doctor.sh` warns) | `lib/devtools.sh`, `doctor.sh` |
| jq, ripgrep, pandoc, gh (read-only) | — | brew batch (jq ships in `/usr/bin` on recent macOS) | optional; agents prefer them when present | global rules, [CLI tools agents rely on](#cli-tools-agents-rely-on) |
| Google Chrome | — | — | optional (the playwright MCP drives it; `doctor.sh` warns) | `doctor.sh` |
| pnpm | — | `corepack enable pnpm` on nvm's node 24 | optional (node-engineer's projects) | `lib/devtools.sh` |
| Python 3.14 as uv's default | — | `uv python install 3.14 && uv python pin --global 3.14` | optional (`STACK_INSTALL_UV`) | `lib/devtools.sh` |
| Open-file limit 65536 (elan/Lean need it; macOS starts programs with 256) | `/Library/LaunchDaemons/ulimit.max-files.plist`: launchd soft 65536, hard 524288 | offered before step 2 on a terminal: shows the plist and the steps, asks [y/N], runs sudo only after y (`STACK_INSTALL_MAXFILES`); the run then raises its own limit | optional (without it the Lean group is skipped) | `install.sh`, [CONFIG.md](CONFIG.md) §7 "Open-file limit" |
| Toolchains: rustup, ghcup (+ hlint, ormolu), juliaup, coursier, elan + a Mathlib project, JDK, Gradle, MacTeX, cmake/ninja, go/gopls, gitleaks, pre-commit, Playwright's Chromium | see [CONFIG.md](CONFIG.md) §7 | installed by step 2 when missing, one group knob each ([Installer and session environment](#installer-and-session-environment)) | optional | `lib/devtools.sh` |

`./install.sh` installs only what is missing (step 2): a command-line tool already there, from any
source (PATH, Homebrew, `~/.cargo/bin`, `~/.ghcup/bin`, `~/.elan/bin`, `~/.local/bin`, `~/.nvm`, …),
is skipped and never upgraded, replaced or removed (`skip <tool> (found: <path>, from <source>)`; one
that fails `--version` gets a WARN with the fix to run yourself). Configuration (uv's Python pin, git
lfs filters, profile lines) is set when missing. To see what it would install first:
`./install.sh --dry-run` (the brew batches, the upstream installers and the pinned downloads, one line
each); `~/.claude/bin/stack-update-tools` updates them together later.

### Python: uv, never bare `python`

Every Python tool, script and MCP server of the stack runs through uv (`uv run`, `uv run --script` for
PEP 723 scripts, `uvx`); the global rules forbid bare `python`, `python3` and `pip`. There are three
exceptions: the stack's venvs (`~/.claude/venvs/<name>/bin/python`), a project pinned to poetry, conda or
pixi, and the hooks, which run on the absolute interpreter the installer picked (`STACK_PYTHON`, normally
`/usr/bin/python3`, never a pyenv or asdf shim: a hook that cannot start is a non-blocking error, which
would leave every gate open). The venvs pin Python 3.13; uv's own default for your projects stays your
choice.

### Accounts and API keys

Names only; values go into `~/.claude/stack.env` (mode 0600), which agents cannot read. Remote servers get
their keys through `bin/mcp-headers`, never `~/.claude.json`. The stack stores no key in the Keychain.

| Key | Needed? | For |
|---|---|---|
| Claude account | required | Claude Code itself |
| `JINA_API_KEY` | effectively required | jina (web reading, arXiv, PDFs), libdocs |
| `EXA_API_KEY` | optional (keyless works, with lower rate limits) | exa, libdocs |
| `OPPER_API_KEY`, `OPENROUTER_API_KEY` | optional; image tools off without them | image-studio (designer, image-director) |
| `SPIDER_API_KEY` | optional | spider (researcher), libdocs |
| `GITHUB_TOKEN` | optional, read-only is enough | libdocs' GitHub rate limit |
| `HF_TOKEN`, `WANDB_API_KEY` | optional | huggingface, wandb |
| `LEAN_PROJECT_PATH`, `DATABASE_URI`, `MDB_MCP_CONNECTION_STRING`, and the magg catalog's keys | optional | the servers that need them ([Keys and paths](#keys-and-paths-claudestackenv)) |

### MCP servers and their prerequisites

Each server's prerequisite is in the "Needs" column of [MCP servers](#mcp-servers). The ones that need
something outside the installer: Google Chrome (playwright), Blender running with its add-on (blender),
`--with-adobe` and the Adobe apps (after-effects, premiere), a built Lean 4 + Mathlib project in
`LEAN_PROJECT_PATH` (lean), Xcode (mobilebuild), the macOS Automation grant (illustrator), and a database
URI for postgres or mongodb.

### Optional per-domain toolchains

`install.sh` step 2 installs Rust (rustup), Haskell (ghcup, hlint, ormolu), Julia (juliaup), a JDK,
Gradle, Scala's coursier, MacTeX, cmake/ninja, Go and the dev tools when they are missing (one group
knob each; [CONFIG.md](CONFIG.md) §7). The others below stay your step. Installing a toolchain from
inside a session fails by design (the sandbox keeps toolchain dirs read-only): install from your own
terminal. Without one, the agent that needs it reports the step as not run. In the baseline, 4 of 40
graded runs were "tool-absent" for exactly this reason (Miri, Gradle/kotlinc, Hackage, the Julia registry).

| Toolchain | Used by | What breaks without it |
|---|---|---|
| Rust (rustup, cargo) | rust-engineer, embedded-engineer; `cargo` also builds the catalog's serial-mcp | Rust builds and tests; the `serial` catalog server |
| Go | go-engineer; the huetension fallback build (Go ≥ 1.26) | Go builds and tests |
| Julia (juliaup) | julia-engineer, hpc-engineer | Julia packages, the Julia language server |
| Haskell (GHCup, cabal or stack; hlint, ormolu) | haskell-engineer | builds, lint and format checks |
| JDK, Gradle or Maven | jvm-engineer | JVM builds; `/usr/bin/java` is only a stub without a JDK |
| Xcode | mobile-engineer, `swift-lsp`, `sourcekit-lsp` | iOS builds and simulators |
| elan, Lean 4, Mathlib | proof-checker, `lean-lsp` | machine-checked proofs |
| Blender | cg-artist | headless renders and bpy scripts |
| Houdini (hython, husk) | vfx-td | Houdini cooks and renders |
| After Effects, Premiere | motion-designer (`--with-adobe`) | the Adobe MCP servers |
| LaTeX or Typst | writer, doc-specialist (skills `latex-typesetting`, `book-production`) | PDF builds; which binaries a task needs is not checked by the stack |
| Docker | devops-engineer (skill `container-images`) | image builds; not checked by the stack |
| Apple Silicon GPU (MLX, Metal) | mlx-engineer | local MLX work (`doctor.sh` says so on Intel) |
| An NVIDIA host | cuda-engineer | CUDA work; none runs on a Mac |
| `--with-ml` venv (several GB) | ML agents | a shared torch/transformers venv; agents use project environments otherwise |

### Disk, memory and time

The repo states two figures: the `--with-ml` venv takes several GB, and Claude Code needs 4 GB or more of
RAM ([setup docs](https://code.claude.com/docs/en/setup)). `doctor.sh` reports the unified memory of an
Apple Silicon Mac. Install time is not recorded anywhere.

### macOS permissions

- **Computer use** (cg-artist, designer, doc-specialist, game-engineer, motion-designer, vfx-td, verifier):
  `/mcp` → computer-use → Enable, then grant Accessibility and Screen Recording.
- **Illustrator** (designer): the macOS Automation grant.
- **Full Disk Access:** nothing in the stack asks for it.
- **Sandbox:** sandboxed Bash can write the project, the temp dir and `~/.cache/claude-sandbox` only, and
  reach a network allowlist of package registries, forges, Hugging Face, W&B and arXiv (CONFIG.md §7).

### Check your machine

Before installing:

```bash
sw_vers -productVersion        # macOS version
uname -m                       # arm64 on Apple Silicon
/usr/bin/python3 --version     # 3.8 or later; Apple's is 3.9.6
git --version
claude --version               # 2.1.271 or later
node --version                 # v22.5 or later (the installer can install it)
uv --version                   # the installer can install it
./install.sh --dry-run         # the full plan, nothing changed
```

After installing, `bash ~/.claude/bin/doctor.sh` prints `ok`, `WARN` and `FAIL` lines per section and
ends with `done.`. `/stack-doctor` in a session runs the same check and answers with one summary:

```text
stack-doctor: 0 FAIL, <n> WARN, <m> ok (doctor.sh, run outside the sandbox)
healthy: <the sections without findings>
full report: bash "<config dir>/bin/doctor.sh"
```

Healthy means 0 FAIL. WARN lines name optional pieces (a media tool, Chrome, a language server) and the
command that adds each.

## Install

### Prerequisites

The full list, with sources and the optional toolchains, is in [Requirements (macOS only)](#requirements-macos-only). The installer's view:

<details>
<summary>Prerequisites table</summary>

| Tool | Why | How the stack treats it |
|---|---|---|
| macOS | The installer refuses other systems (`STACK_ALLOW_NON_MACOS=1` exists for the tests only) | required |
| Claude Code ≥ 2.1.271 | The stack targets it | required; older warns (`claude update`) |
| git, `python3` ≥ 3.8 (Xcode Command Line Tools: `xcode-select --install`) | Installer; hooks and status line run on an absolute system interpreter | required |
| uv | Every Python tool, script and MCP server | installed if missing (astral.sh's installer, else the checksummed 0.12.20 tarball into `~/.local/bin`) |
| Python 3.14 as uv's default: `uv python install 3.14 && uv python pin --global 3.14` | Your projects' `uv run` without a pin | set by step 2 (`STACK_INSTALL_UV`); the stack's own venvs pin 3.13 |
| Node.js ≥ 22.5 with `npx` | context-mode, the npx MCP servers, the TypeScript language server | installed if missing (nvm, node 24); older warns |
| pnpm (`corepack enable pnpm` on nvm's node 24) | node-engineer's projects | installed by step 2 (`STACK_INSTALL_NODE`) |
| jq | Cheap JSON filtering in agents' Bash (global rules) and in tests | brew batch when missing |
| elan ([leanprover/elan](https://github.com/leanprover/elan)), then a built Mathlib project for `LEAN_PROJECT_PATH` | Lean: `lean-lsp@agent-stack` (`lake serve`) and proof-checker's lean server | installed by step 2 (`STACK_INSTALL_LEAN`; elan from Homebrew's sha256-pinned `elan-init` bottle, the official `elan-init.sh` only without Homebrew; the project, about 8 GB, at `~/lean/stack_mathlib` only on a terminal or with `STACK_INSTALL_LEAN_MATHLIB=1`; your own `LEAN_PROJECT_PATH` project is used as it is); you set `LEAN_PROJECT_PATH` in `stack.env`; the plugin is enabled only when `lake` exists |
| Homebrew | One batch for every missing formula, one for every missing cask | installed when missing (on a terminal) |
| magg 1.2.1, huetension 0.3.0 | mcp-broker's catalog; designer's colour server | installed (pinned, checksummed) |
| ffmpeg, ImageMagick, librsvg, poppler | Media and PDF work | brew batch, else warned |
| The toolchain groups (Rust, Haskell, Julia, Scala, Java, LaTeX, C++ tools, Go, dev tools; PostgreSQL and MongoDB off) | The language and domain agents | installed when missing; `STACK_INSTALL_<GROUP>=0` skips one |
| Google Chrome | playwright MCP | not checked |
| Xcode | mobilebuild, `swift-lsp`, `sourcekit-lsp` | not checked |

</details>

`doctor.sh` checks `python3 uv uvx node npx git` (FAIL when missing), magg, huetension, the media
tools, the sci venv, the stack's `bin/` and `mcp/` scripts, frozen MCP command paths and the language
servers it finds.

### Run the installer

> [!WARNING]
> **First install over an existing `~/.claude`: run `./install.sh --dry-run` first.** The default run
> prunes: agents and skills that aren't the stack's current version are moved into a backup and
> replaced. Keep your own with `--no-prune`; get them back with `--restore`.

```bash
git clone <repository-url> claude-agent-stack && cd claude-agent-stack
./install.sh --dry-run            # the plan: added / replaced / removed, each with a reason
./install.sh                      # core install; one backup of everything it changes or removes
$EDITOR ~/.claude/stack.env       # keys: read at connect time; Claude model IDs: re-run ./install.sh
```

The clone can live anywhere (a path with spaces, a symlinked directory, or a symlink to `install.sh`
all work), under any user name, from zsh or bash; the installer itself runs on macOS's bash 3.2. Run
it from a terminal with no Claude Code session open (Desktop and Conductor included), from the
`main` branch. A real run started on another branch fast-forwards `main` and re-runs itself (it
never pushes); `--dry-run` and `--mcp-plan` change nothing, so on another branch they stop and tell
you to run them from the `main` checkout. A dirty tree or diverged history also stops it. The eleven
steps, as the run prints them:

1. **Prerequisites**: macOS, git, python3, Claude Code version, the absolute interpreter for hooks
   (`STACK_PYTHON`). Before it, the run prints the install target and asks about a non-default one
   ([Choose the config folder](#choose-the-config-folder)). If the stack changed since the last install, its diff is listed and, on a terminal,
   you are asked before anything changes (`--yes` skips the question; without a terminal it stops).
   Then, before anything is installed, the **open-file limit**: on a terminal the run shows the
   `/Library/LaunchDaemons/ulimit.max-files.plist` LaunchDaemon (launchd soft 65536, hard 524288), its
   steps and how to remove it, and asks [y/N]; only y runs sudo (`install`, `launchctl bootstrap`).
   Otherwise it prints the commands (`STACK_INSTALL_MAXFILES=0|1`). The run then raises its own soft
   limit to 65536 for every tool it starts ([CONFIG.md](CONFIG.md) §7 "Open-file limit").
2. **Tools**: prerequisites and toolchains (`lib/devtools.sh`: Homebrew, one brew batch for the
   missing formulae and one for the missing casks, the upstream managers uv, nvm, rustup, ghcup,
   juliaup, coursier and elan, then the Mathlib project, gitleaks, pre-commit, Gradle and Playwright's Chromium; one line per
   tool, an existing tool from any source skipped and never touched (`skip <tool> (found: …)`, a summary line at the end), `STACK_INSTALL_<GROUP>=0` skips a group), magg, huetension, the hash-locked science venv
   (`~/.claude/venvs/sci`) and tools venv (`~/.claude/venvs/tools`: what the stack's scripts, MCP
   servers and tests import; `requirements/tools.in`); serial-mcp (`cargo install --locked` at the catalog's pin) when cargo
   is present, else one line saying it was skipped (Rust is never installed).
3. **ML venv** (`--with-ml`): `~/.claude/venvs/ml` from `requirements/ml.txt`, several GB.
4. **Adobe** (`--with-adobe`): the After Effects MCP at a pinned commit, the Premiere connector.
5. **Stage**: copy the stack's part of the config dir to a private staging dir.
6. **Render**: agents (with `-copy` renders), rules, skills, scripts, `settings.json`.
7. **Merge, validate, apply**: JSON, frontmatter, placeholders and the staged guard's `--self-test`;
   the plan; one backup; apply; then `tests/lint_agents.py` on the repo (warns only).
8. **MCP dependency prefetch** into the private `STACK_CACHE`.
9. **User-scope MCP servers**: exa, jina, wolfram, huggingface, and wandb when a key exists; keys come
   through the `bin/mcp-headers` header helper, never `~/.claude.json`.
10. **Plugins and code intelligence**: document-skills, LSP plugins for the servers it finds
    (`--with-lsp` installs missing ones), `--with-extra-plugins`; duplicates of claude.ai-synced
    skills disabled.
11. **Shell profile**: one line in `~/.zshrc` (and `~/.bashrc` if present) exporting the
    `STACK_EXPORT` keys and adding `~/.local/bin` to `PATH` (`--no-profile` skips it), and the
    `claude-ninja` / `claude-supreme` launcher links in `~/.local/bin`.

Other flags: `--config-dir PATH`, `--no-prompt`, `--no-prune`, `--force`, `--write-through-links`,
`--no-mcp`, `--no-plugins`, `--keep-plugin-duplicates`, `--replace-mcp`, `--no-deps`, `--mcp-plan`,
`--print-managed-settings`. `./install.sh --help` prints them all; [CONFIG.md](CONFIG.md) §7 explains
staging, pruning and the manifest.

### Choose the config folder

By default the stack goes into `~/.claude`. To install somewhere else:

```bash
./install.sh --config-dir ~/claude-work        # or --config-dir=~/claude-work
export CLAUDE_CONFIG_DIR="$HOME/claude-work"   # then in ~/.zshrc (bash: ~/.bash_profile)
```

- **Precedence:** `--config-dir` > `CLAUDE_CONFIG_DIR` > `~/.claude`. The path may start with `~` or be
  relative; it is made absolute, and a symlink is resolved and shown.
- **Banner:** every run prints the target, how it was chosen (`--config-dir`, `CLAUDE_CONFIG_DIR` or
  the default) and the `.claude.json` it implies: `<target>/.claude.json` when `CLAUDE_CONFIG_DIR` is
  set or `--config-dir` names another folder, else `~/.claude.json` (`STACK_CLAUDE_JSON` overrides it).
  The `claude mcp` and `claude plugin` commands the run starts get `CLAUDE_CONFIG_DIR` set to the
  target.
- **Question:** when stdin and stdout are both a terminal, a non-default or ambiguous target is
  confirmed first (`Install into <target>? [y/N]`, default No). It is asked when `--config-dir` names
  a folder other than `~/.claude`, when `CLAUDE_CONFIG_DIR` is set, or when `~/.claude` and the target
  both hold differing stack installs. `--yes`, `--no-prompt`, `--dry-run`, `--mcp-plan` and runs
  without a terminal never ask; they proceed with the banner, as before.
- **Refused** with exit 2, before anything changes: `/`, your home folder or a folder containing it,
  anything inside the repo checkout (also through a symlink), `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`,
  `~/.docker`, `~/Library/Keychains`, system folders (`/System`, `/usr`, `/etc`, ...), the stack's state
  and backup folders, a file, a folder you can't write or create, a `..` that follows a symlink, and
  paths with a control character (newline, NUL, tab) or one of `"` `` ` `` `$` `\`.
- **Foreign folders:** a `--config-dir` target other than `~/.claude` that is a non-empty folder with no Claude Code files
  (none of `.stack-manifest.json`, `settings.json`, `settings.local.json`, `.claude.json`,
  `.credentials.json`, `CLAUDE.md`, `stack.env`, `agents/`, `skills/`, `rules/`, `hooks/`, `commands/`,
  `output-styles/`, `projects/`, `plugins/`, `statsig/`, `todos/`, `shell-snapshots/`; a lone
  `.DS_Store` counts as empty) is installed into only after a `y` on the terminal. Without a terminal,
  or with `--yes` or `--no-prompt`, the run stops; `--dry-run` warns and goes on. A foreign folder
  named by `CLAUDE_CONFIG_DIR` only gets a warning (and a reason in the question), so existing
  scripted runs keep working. Paths are compared by inode as well as by name, so `~/.SSH` counts as
  `~/.ssh` on the default case-insensitive APFS.
- **After a non-default install:** Claude Code reads the folder only when `CLAUDE_CONFIG_DIR` is
  exported, so the installer prints the `export` line and the file to put it in (zsh: `~/.zshrc`;
  bash: `~/.bash_profile`). Apps opened from the Dock or Finder do not read shell startup files.
  `settings.json`, the hooks and the MCP entries hold absolute paths to the folder: to move it, reinstall
  with `--config-dir <new path>`. `/stack-doctor` warns when the folder it checks is not `~/.claude`
  and `CLAUDE_CONFIG_DIR` is unset.

### Restart Claude Code

Quit every Claude Code session (terminal, Desktop, Conductor, IDEs) and start new ones: a running
session keeps the agent files it started with. Then, once, in the first session: `/effort medium`.
`claude` starts as BlackCat; `/mcp` shows server status; `/stack-doctor` is the health check.

The user commands and typical workflows are under [Usage](#usage).

### Verify

```bash
bash ~/.claude/bin/doctor.sh                                   # installed health check (= /stack-doctor)
/usr/bin/python3 ~/.claude/bin/stack-tree --help              # agent tree of the newest session (= /stack-tree)
/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test   # the hook on the hooks' own interpreter
uv run tests/lint_agents.py                                    # frontmatter, POLICY ↔ "May spawn", skills, listing budget, model IDs (skips .claude-work/)
~/.claude/venvs/tools/bin/python -m pytest -q tests/                # full suite (the tools venv from install.sh)
bash tests/install_smoke.sh                                    # hermetic installer runs; run it outside any sandbox
uv run --script tests/prompt_budget.py --check                 # prompt-budget gates
```

`doctor.sh` checks the config dir it sits in, so run the installed copy, not `dot-claude/bin/doctor.sh`
(that one would check the repo's `dot-claude/`). `install_smoke.sh` uses a fake `claude`, a scratch
config dir and a scratch `XDG_STATE_HOME`, and fingerprints the real `~/.claude` before and after; the
Claude Code sandbox refuses parts of it, so run it from your own terminal.

The counts in this README come from the files:

```bash
ls dot-claude/agents/*.md | wc -l                             # 56 agents
ls dot-claude/skills/*/SKILL.md | wc -l                       # 214 skills
ls dot-claude/skills/*/references/*.md | wc -l                # 185 references
jq '[.skillOverrides[] | select(. == "user-invocable-only")] | length' dot-claude/settings.json   # 98 hidden: 83 hub modules + 7 bundled + 8 claude.ai
jq '[.skillOverrides[] | select(. == "name-only")] | length' dot-claude/settings.json   # 96 listed by name only
jq '.servers | length' dot-claude/magg/config.json            # 23 catalog servers
grep -h '^  - [a-z-]*:$' dot-claude/agents/*.md | sort -u | wc -l   # 17 inline servers
uv run python -c "import sys; sys.path.insert(0, 'tests'); import test_skill_modules as t; h, m = t.hubs_and_modules(); print(len(h), len(m))"   # 24 hubs, 98 modules
```

### Update

```bash
git pull --ff-only                # in your checkout, on main
./install.sh --dry-run            # what changes, each with a reason
./install.sh                      # lists the stack's diff since the last install and asks first
```

Then quit every Claude Code session and start new ones. A changed stack asks before it applies anything (`--yes` skips the question; without a terminal it stops). Your `stack.env` is kept; new variables are appended commented out.

### Backup, restore and uninstall

Every run that changes something saves what it changes or removes into one backup,
`${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/<timestamp>-<random>/` (0700; agents can't
read it), and prints the restore command. A run that changes nothing makes no backup; none is ever
deleted.

```bash
./install.sh --restore --dry-run          # what a restore would do
./install.sh --restore                    # undo the latest install
./install.sh --restore <backup-dir>       # undo a given one (also --restore=<backup-dir>)
```

A restore is a staged plan too: it backs up the current state first and prints how to undo itself. It
puts back files, `~/.zshrc`/`~/.bashrc`, MCP entries and plugins the install disabled.

**Uninstall:** `./install.sh --restore <the first install's backup>` (it removes the files that install
added and puts back what it replaced), delete the line ending in `# claude-agent-stack` from your shell
rc, and `claude mcp remove -s user exa` (and `jina`, `wolfram`, `huggingface`, `wandb`).

## Usage

### First run

1. Start `claude` in a project directory: the session starts as BlackCat (`"agent": "blackcat"` in
   `settings.json`). For a plain session without BlackCat: `claude --agent claude`; any agent started
   with `claude --agent <name>` keeps all its tools (only BlackCat is restricted).
2. Once, in the first session: `/effort medium`.
3. Type `/stack-doctor` and fix any FAIL line it names.
4. The session starts in Plan mode: BlackCat reads, asks and plans, and nothing is edited until you
   approve a plan or switch modes with Shift+Tab ([Permission modes](#permission-modes)).
5. Ask for something. BlackCat answers in a line or dispatches and says who does what (it runs no
   commands and edits nothing itself); results are relayed as they land.

### Typical workflows

| You want | Type or do | What happens |
|---|---|---|
| A quick answer, a look at a file, a one-line edit, `git status` | ask normally | BlackCat answers a greeting or setup question itself; a look → explore, an edit or one command → coder |
| A timeless explanation; one current fact; a cited survey | ask normally | oracle; scout; researcher |
| A fix or feature in a repository | describe the deliverable | coder, a language engineer or main-coder; a reviewer only when a review trigger fires |
| A specific agent | start with `@<agent>` or `<agent>:` (e.g. `@verifier check …`) | that agent gets your prompt verbatim |
| A job with dependent parts (build, then document, then translate) | describe the whole job | the orchestrator plans, dispatches in parallel and integrates |
| A plan before any code | the default: sessions start in Plan mode | planner writes it; BlackCat sends builders after you approve it ([Permission modes](#permission-modes)) |
| A follow-up on an earlier result | "also …", "fix …" | the same agent, resumed with `SendMessage` |
| To see who is doing what | `/stack-tree` | the live agent tree with each agent's commands and tokens |
| A different model for one agent type, this session only | `/override-agent coder opus`; `/override-agent reset all` | the guard rewrites that type's spawns |
| To see the limits in force | `/usr/bin/python3 ~/.claude/bin/stack-budget` | frozen limits, use so far, verdicts |
| The hardest algorithmic problem, with you watching | `claude-ninja` in a terminal | ninja-coder as your main thread at ultracode |
| A destructive or external action (delete, history rewrite, publish) | answer BlackCat's question | consent reaches the agent only through you; pushing stays your step |

### Commands

The stack's user commands (the model can't run them: `disable-model-invocation`):

| Command | Does |
|---|---|
| `/stack-doctor` | Read-only health check (`bin/doctor.sh`) |
| `/stack-tree [options]` | Read-only: this session's tree of agents and subagents (type, task, status, duration, tokens) with the commands each ran as leaves, collapsed (`git status ×3 [1 exit 1]`), Bash commands cut and secrets masked (`bin/stack-tree --hook`). `--depth N`, `--no-leaves`, `--leaves-only-failed`, `--max-leaves N`, `--session ID`, `--ascii`, `--json`, `--width W`; `--pending` keeps only agents still running, failed or blocked, or finished and not yet handled |
| `/stack-tree table [--columns a,b\|all] [--csv\|--json]` | The same as a GitHub-flavored markdown table, one row per agent and per tool call: path, depth, level, parent, agent, kind (agent, bash, tool, mcp, skill), task, command, status, result (done/partial/blocked, ok/exit N/blocked/error), started, duration, tokens, calls, session; `all` adds id, tid, name, isolation, ended, output_tokens, transcript. A field nothing records reads `unrecorded` |
| `/stack-tree static [table]` | The designed hierarchy from the agent files: BlackCat → L1 → … → L8, each agent expanded once at its shallowest level, its skills and BlackCat's commands as leaves; the table has agent, level, parent, model, effort, max_turns, may_spawn, tools, mcp, skills |
| `/override-agent <agent> <model>` | This session only: every delegated `<agent>` runs on `<model>` (`sonnet`, `opus`, `haiku`, `fable`). The effort comes from the built-in table `hooks/agent_effort.json` (per agent and model, clamped to what the model accepts); it is shown but not applied (CONFIG.md §5, "Session model overrides") |
| `/override-agent list` | Read-only: this session's overrides (agent, model, effort and its source) and every agent's default model/effort |
| `/override-agent reset <agent\|all>` | Back to the agent definition's model and effort |

Terminal tools beside them: [Commands and CLIs](#commands-and-clis).

### Permission modes

Sessions start in **Plan**: `permissions.defaultMode` is `plan` in the `settings.json` the installer
writes (it shipped `bypassPermissions` until 2026-10-03). In Plan, BlackCat reads, asks, sends the
planner, relays its plan and calls `ExitPlanMode` with it. Approving the plan switches the session to the
mode you pick in that dialog, and agents dispatched afterwards inherit it. Shift+Tab changes the mode at
any time: Plan is where a session starts, not a lock. The sandbox, the deny rules and the guard's hooks
apply in every mode.

How the mode reaches the agents (Claude Code docs, 2026-10-03):

| Session mode | BlackCat and the 10 read-only agents (no `permissionMode`) | The 45 agents that write files (`permissionMode: acceptEdits`) |
|---|---|---|
| `plan`, `default`, `dontAsk` | follow it | accept edits without prompts: the agent file wins |
| `acceptEdits`, `auto`, `bypassPermissions` | follow it | follow it: the session's mode wins |

- The 45 are every agent with Write, Edit or NotebookEdit except BlackCat. The read-only ones are
  claude-code-guide, code-reviewer, explore, oracle, plan-reviewer, planner, proof-checker, scout,
  security-auditor and verifier.
- So a switch to Plan or Default does not make a dispatched builder read-only, while a switch to
  `acceptEdits`, `auto` or `bypassPermissions` reaches every agent. BlackCat holds builders back until
  you approve the plan (its rule 5). That is a prompt rule, not a guard.
- `acceptEdits` is meant for subagent runs. As your main thread, `claude-ninja`, `claude-supreme` and
  `claude-ultracode <agent>` pass `--permission-mode plan` unless you pass a mode yourself; plain
  `claude` runs BlackCat, which has no `permissionMode`, in the settings default. Whether Claude Code
  applies an agent file's `permissionMode` to a main thread started by hand (`claude --agent main-coder`)
  is not documented: add `--permission-mode plan`, or use `claude-ultracode main-coder`.
- Not verified, because the docs are silent: whether a running subagent follows a later mode switch; how
  nested spawns, `isolation: worktree`, forks and workflow agents inherit; whether hook events inside
  subagents carry `permission_mode`; whether approving a plan counts as a new prompt for
  `BLACKCAT_MAX_STEPS`. `STACK_MODE_PROBE=1` logs what Claude Code reports ([CONFIG.md](CONFIG.md) §5,
  "Permission modes", has the procedure).
- Headless runs (`claude -p`, scheduled and background jobs, `-p` scripts) under Plan: the main
  thread's edits are never auto-approved, and a call that would ask is denied when no host answers. A
  script whose main thread must edit passes `--permission-mode acceptEdits`, since the flag beats the
  settings file. Waiting for your approval instead of denying is queued, not shipped.
- MCP tools: in `plan`, `default` and `acceptEdits` a tool with no allow rule prompts, in a subagent
  too. `permissions.allow` allows 19 MCP servers whole (`mcp__computer-use`, `mcp__lean`,
  `mcp__mobilebuild`, `mcp__exa`, ...). `mongodb` and `postgres` (database access) and
  `claude-in-chrome` (your logged-in browser) have no rule, so they prompt at each call and are denied
  in headless runs; magg and context-mode are ruled tool by tool. computer-use still asks you per
  application (its `request_access`). Claude Code checks deny, then ask, then allow, so an `ask` or
  `deny` rule you add for an allowed server wins, and the installer keeps your rules when it adds the
  stack's.
- Back to `bypassPermissions`: set `"permissions": {"defaultMode": "bypassPermissions"}` in
  `~/.claude/settings.json` (the installer keeps a mode you set), or start one session with
  `claude --permission-mode bypassPermissions`. Project and local settings ignore `bypassPermissions` and
  `auto` as a default mode.
- Upgrading: an install still on the previously shipped `bypassPermissions` is moved to `plan` once, with
  a note. A mode you chose stays, and the installer prints `kept your permissions.defaultMode=...`.

## Environment variables

Names only; values never go into the repo, prompts or output.

### Keys and paths: `~/.claude/stack.env`

Every key and path variable of `lib/stack.env.example`. Its commented tuning sections (`EXA_MAX_*`,
`JINA_MAX_*`, `SPIDER_*`, `READ_GATE*`, 39 variables, read at each call by `hooks/web_caps.py` and
`hooks/read_gate.py`, no reinstall) are not repeated here; their defaults are in the file. The file is 0600; servers read it at connect time, each gets only
its own keys, and upgrades append new variables commented out (the image and Claude models set to their
defaults) without touching yours.

<details>
<summary>All `stack.env` variables</summary>

| Variable | Purpose | Default | Used by |
|---|---|---|---|
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | The ID the `opus` alias resolves to: 41 agents | today's Opus ID (source and date in the file) | `install.sh` → settings.json `env` → Claude Code; re-run the installer after a change; `/stack-doctor` |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | The ID the `sonnet` alias resolves to: 15 agents and BlackCat | today's Sonnet ID | as above |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | The `haiku` alias and Claude Code's background work | the Sonnet ID (the stack runs no Haiku) | as above |
| `OPPER_API_KEY` | `generate_image`: photos and raster images | empty (tool off) | image-studio (designer, image-director) |
| `OPENROUTER_API_KEY` | `generate_svg` and `edit_image` | empty (tools off) | image-studio |
| `IMAGE_STUDIO_SVG_MODEL` | Model behind `generate_svg` (OpenRouter) | `recraft/recraft-v4.1-pro-vector` | image-studio; `/stack-doctor` shows it |
| `IMAGE_STUDIO_IMAGE_MODEL` | Model behind `generate_image` (Opper) | `openai/gpt-image-2.5-sunburst` | image-studio |
| `IMAGE_STUDIO_EDIT_MODEL` | Model behind `edit_image` (OpenRouter) | `sourceful/riverflow-v2.5-pro` | image-studio |
| `IMAGE_STUDIO_OUT_DIR` | Output folder when an agent names none (`OPENROUTER_IMAGE_OUT_DIR` still read) | `$HOME/Pictures/image-studio` | image-studio |
| `EXA_API_KEY` | Exa search; raises rate limits | empty = keyless | exa (remote, via `mcp-headers`), libdocs |
| `JINA_API_KEY` | Jina reader, arXiv/SSRN, PDFs | empty; effectively required | jina (remote), libdocs |
| `SPIDER_API_KEY` | Crawling | empty | spider (researcher), libdocs |
| `GITHUB_TOKEN` | Raises libdocs' GitHub API limit; read-only token is enough; not exported to shells | empty | libdocs |
| `HF_TOKEN` | Hugging Face Hub and the `hf` CLI | empty = anonymous | huggingface (remote); exported |
| `WANDB_API_KEY` | W&B tracking; the server is registered only when set (re-run the installer the first time) | empty | wandb (ml-/dl-/llm-/robotics-engineer); exported |
| `JUPYTER_URL`, `JUPYTER_TOKEN` | A Jupyter server you started | commented out | magg `jupyter`; exported |
| `MLFLOW_TRACKING_URI` | MLflow tracking server or store | commented out | magg `mlflow`; exported |
| `MOTHERDUCK_TOKEN` | MotherDuck (`md:`) databases | commented out | magg `duckdb` |
| `LEAN_PROJECT_PATH` | A built Lean 4 + Mathlib Lake project | commented out | proof-checker's `lean`, magg `lean` |
| `MDB_MCP_CONNECTION_STRING` | MongoDB connection, read-only server | commented out | db-engineer's `mongodb`, magg `mongodb` |
| `DATABASE_URI` | Postgres connection, restricted mode | commented out | db-engineer's `postgres`, magg `postgres` |
| `QISKIT_IBM_TOKEN` | IBM Quantum Platform (hardware jobs spend quota) | commented out | magg `qiskit-runtime` |
| `GODOT_PATH` | The Godot executable | commented out | magg `godot` |
| `SEC_EDGAR_USER_AGENT` | The "Name email" User-Agent the SEC requires | commented out | magg `sec-edgar` |
| `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN` | Your Grafana and a Viewer service-account token | commented out | magg `grafana` (`--disable-write`) |
| `NCBI_API_KEY` | Higher PubMed rate limits | commented out | magg `biomcp` |
| `STACK_EXPORT` | Keys the shell profile exports (space-separated, or `all`) | `HF_TOKEN WANDB_API_KEY MLFLOW_TRACKING_URI JUPYTER_URL JUPYTER_TOKEN` | `bin/with-stack-env`, the profile line |

</details>

The magg catalog keys reach mcp-broker's magg through `bin/with-stack-env --only …` and nothing else.

### Knobs

Set in `settings.json` → `env`. ● = shipped in `dot-claude/settings.json` and owned by the stack
(`OWNED_ENV` in `install.sh`): reset on every install, so change it in the repo and re-run the
installer. ○ = shipped as a default: it follows stack upgrades while you leave it unchanged, and a value
you change is kept (the installer prints `kept your env …`). The rest are defaults in `agent_guard.py`
you may set yourself.

<details>
<summary>All knobs</summary>

| Variable | Default | Purpose | Read by |
|---|---|---|---|
| `STACK_POLICY` | `on` | `off` lifts the spawn, budget, lock and read-only-Bash guards; the no-push hook's refusals (forge writes, protected-path writes, credential reads, `install.sh`) stay on. It also lifts blackcat-guard (BlackCat's step, dispatch and read caps and its tool allowlist): only BlackCat's tools line still keeps Bash, Write and Edit from it | guard |
| `STACK_AGENT_LABEL` | `description` | Child label: `description` (`<type>: <task>`), `name` (`<type>-<n>`), `off` | guard |
| `STACK_AGENT_STARTED` | `1` | SubagentStart gives a stack agent its start time (`0` = off) | guard |
| `STACK_REPORT_FORMAT` | `observe` | `observe` (unset or any other value): SubagentStop checks and records each stack subagent's final reply and PreToolUse(Agent) the brief's size, never output, warned or blocked; `compact`: plus one restate per run on a hard violation (not the default, planned for Phase 2); `json`: every final report is one JSON line (SessionStart and SubagentStart add one line) plus a logged shape check, for Agent SDK apps; `off`: no check, no log ([CONFIG.md](CONFIG.md) §5, "Message protocol") | guard |
| `BLACKCAT_MAX_DISPATCH` ● / `BLACKCAT_DISPATCH_WINDOW_S` ○ | 8 / 120 | BlackCat Agent calls per prompt, within this many seconds of the first | guard |
| `BLACKCAT_MAX_STEPS` ● | 24 | BlackCat tool calls per prompt | guard |
| `BLACKCAT_MAX_READS` | 3 | Of those, BlackCat's Read calls: the delegation ledger, a plan, a child's output file (8 dispatches always fit) | guard |
| `BLACKCAT_MAX_OWN_STEPS` | 0 | Of those, BlackCat's own Bash/Write/Edit calls: 0, it only delegates. Its `tools` line lists none of them, so a value > 0 changes nothing in a normal session; any other agent started with `claude --agent <name>` (`claude --agent claude` for a plain session) is not restricted: the restriction belongs to BlackCat only, through its own tools line and its own guard | guard |
| `BLACKCAT_BASH_TIMEOUT_MS` | 120000 | Longest timeout a BlackCat foreground Bash call may ask for, only with `BLACKCAT_MAX_OWN_STEPS` > 0 | guard |
| `BLACKCAT_BACKGROUND` | 1 | Drop BlackCat's `run_in_background: false` | guard |
| `STACK_MAX_FANOUT` ● | 3 | Running children per agent (0 = no cap) | guard |
| `STACK_MAX_FANOUT_BY_TYPE` ● | `orchestrator=32,supreme-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | Per-type overrides | guard |
| `STACK_MAX_SELF_FANOUT` ● | 2 | Live copies per copy type | guard |
| `STACK_MAX_DEPTH` | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, else 3 | Deny Agent from callers at this depth | guard |
| `STACK_PROMPT_CTX_BUDGET` / `STACK_SESSION_CTX_BUDGET` | learned (seed 100000000 / 1920000000) | Context tokens per prompt / per session, whole tree (0 = off); a value you set pins the learned limit | guard |
| `STACK_MAX_MCP_CALLS` ● | 64 | MCP calls per subagent per prompt, lower if `maxTurns` is | guard |
| `STACK_SOFT_LIMIT_SCALE` | unset = 1 | Multiplies the soft token limits (per agent run, 33M per human prompt, 80M with an orchestrator); `0` = off | guard |
| `STACK_SCHED_POLICY` | `report` | `report`: the scheduler only reports; `fresh_fixer` (opt-in): `stack_sched.py next` also advises a fresh fixer after a long resume gap. Fixed per session (snapshot) | stack_sched |
| `STACK_FANOUT_IDLE_S` ○ | 600 (code: 1800) | A silent background subtree stops counting | guard |
| `STACK_FANOUT_SESSION` | `shadow` | Session slot guard against `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`, every caller: `shadow` logs the count (`fanout-session.jsonl`), `enforce` also refuses a spawn or resume with no free slot, `off` = none ([CONFIG.md](CONFIG.md) §5) | guard |
| `STACK_FANOUT_DYN` | `shadow` | Dynamic fan-out cap for orchestrators (`stack_fanout.py`; never the main thread or BlackCat, never above the static cap): `shadow` (default; only for `STACK_FANOUT_DYN_TYPES` = orchestrator, never denies, 0600, 4 MiB cap) logs each decision from `plan.dag.json`, budget, AIMD window and K_sess to `fanout-dyn.jsonl`, `enforce` also refuses (`Dynamic fan-out (<term>): ...`) with the terms in `STACK_FANOUT_DYN_ENFORCE`; any error = static; `off` = nothing runs, no file, the rollback ([CONFIG.md](CONFIG.md), "Dynamic fan-out cap") | guard |
| `STACK_FANOUT_DYN_{ENFORCE,TYPES,W0,WMIN,ALPHA,BETA_RL,BETA_FAIL,HOLD_S,RESERVE_TOK,SLACK,NODE_RUNS,DELAY_RATIO,BREAKER}` | `node,deps` / `orchestrator` / 8 / 1 / 1 / 0.5 / 0.75 / 60 / 8000000 / 2 / 7 / 1.5 / `5/600` | Its enforced terms, scope, AIMD window, token reserve, slack, runs per node, delay signal and breaker | guard |
| `STACK_LEASE_TTL_S` / `STACK_RESUME_TTL_S` | 21600 / 120 | Ceilings on unreported leases and resume reservations | guard |
| `SUPREME_SPAWNERS` / `SUPREME_ONCE_PER_SESSION` / `SUPREME_AFTER_NINJA` | `orchestrator` / 1 / 1 | Who spawns supreme-coder; once; after a finished ninja-coder | guard |
| `SUPREME_IDLE_S` ○ / `SUPREME_PENDING_TTL_S` / `SUPREME_LOCK_TTL_S` | 1800 (code: 900) / 120 / 21600 | supreme-coder lock timers | guard |
| `SCREEN_LOCK_TTL_S` | 900 | Screen lock expiry | guard |
| `STRIP_AGENT_MODEL` | 1 | Remove per-call `model` | guard |
| `STACK_GUARD_LOG` | 0 | 1 = log hook events (tool names and ids only in budget mode) | guard |
| `STACK_MODE_PROBE` | 0 | 1 = diagnostic: log the permission mode each PreToolUse, PermissionRequest and SubagentStart event reports to `mode-probe.jsonl` in the state dir (no tool input; 0600; stops at 1 MB). Decides nothing ([CONFIG.md](CONFIG.md) §5, "Permission modes") | guard |
| `STACK_IMAGE_MAX_PX` / `STACK_IMAGE_MAX_B64` | 1919 / 4500000 | Longest image side; most base64 chars per image | guard, image-studio, doctor |
| `STACK_IMAGE_UPLOAD_TOOLS` | — | Regex of more MCP tools whose image arguments get downscaled copies | guard |
| `STACK_ENV_FILE` ● | `~/.claude/stack.env` | Where the keys live | `mcp-headers`, `with-stack-env`, libdocs, image-studio, `read_gate.py`, `web_caps.py` |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` ● | 8 | Claude Code's nesting limit (its default is 3) | Claude Code, guard |
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | 33 | Subagents running in one session | Claude Code, guard |
| `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS` ○ | 1 | Built-in Explore and Plan off (the stack's `explore` replaces Explore) | Claude Code |
| `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS` ○ | 1 | Every built-in type off in `claude -p` | Claude Code |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | from `stack.env` | Not in `dot-claude/settings.json`: the installer copies them from `stack.env` (Keys and paths above) | Claude Code |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` ○ | 400 | WebSearch calls per session | Claude Code |
| `MCP_DISCOVERY_CACHE` ● / `_TTL_S` ○ / `_MAX_STALE_S` ○ | 1 / 21600 / 604800 | MCP discovery cache (unverified: not on the docs page checked for this README) | Claude Code |
| `MCP_TIMEOUT` ○ / `MAX_MCP_OUTPUT_TOKENS` ○ | 60000 / 25000 | MCP start-up timeout; tool output cap | Claude Code |

</details>

Don't set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every agent file's effort.

### Installer and session environment

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Install target when `install.sh --config-dir PATH` is not given (the flag wins); Claude Code reads a non-default folder only with it exported ([Choose the config folder](#choose-the-config-folder)) |
| `STACK_CLAUDE_JSON` | `<target>/.claude.json` when `CLAUDE_CONFIG_DIR` is set or `--config-dir` names a folder other than `~/.claude`, else `~/.claude.json` | Which file the MCP plan reads (the banner prints it) |
| `XDG_STATE_HOME` | `~/.local/state` | Root of the guard state, the backups and `STACK_CACHE`; rendered into the sandbox rules at install time |
| `STACK_PYTHON` | chosen automatically | Absolute interpreter for hooks and the status line (never a pyenv/asdf shim) |
| `STACK_ALLOW_NON_MACOS` | 0 | Tests only: let the installer run off macOS |
| `STACK_INSTALL_DEPS`, `STACK_INSTALL_DEVTOOLS` | 1 | Step 2 groups: Homebrew + jq/rg/gh/media tools (and the no-Homebrew fallbacks); gitleaks, pre-commit, Gradle, Playwright's Chromium. `=0` skips the group; `--no-deps` skips every install |
| `STACK_INSTALL_UV`, `STACK_INSTALL_NODE`, `STACK_INSTALL_RUST`, `STACK_INSTALL_HASKELL`, `STACK_INSTALL_JULIA`, `STACK_INSTALL_SCALA`, `STACK_INSTALL_JAVA`, `STACK_INSTALL_LATEX`, `STACK_INSTALL_CXX`, `STACK_INSTALL_GO` | 1 | One toolchain group each (uv + Python 3.14 pin; nvm + node 24 + pnpm; rustup; ghcup + hlint + ormolu; juliaup; coursier; a JDK (the 27 cask only when none is found) + kotlin-lsp; MacTeX; cmake, ninja, typst, shellcheck, …; go + gopls). `=0` skips it ([CONFIG.md](CONFIG.md) §7) |
| `STACK_INSTALL_POSTGRES`, `STACK_INSTALL_MONGODB` | 0 | `=1` adds postgresql@18 / mongodb-community (Homebrew) |
| `STACK_INSTALL_LEAN` | 1 | Step 2 group: elan (stable) and the Mathlib project (`~/lean/stack_mathlib`, unless `LEAN_PROJECT_PATH` names one); skipped while the open-file limit is below 65536 |
| `STACK_INSTALL_LEAN_MATHLIB` | auto | The Mathlib project (about 8 GB): only on a terminal; `=1` also without one, `=0` never (the commands are printed) |
| `STACK_INSTALL_MAXFILES` | ask | Before step 2: the `ulimit.max-files` LaunchDaemon (open-file limit 65536). `ask` asks on a terminal (default No); `=0` never, prints the commands; `=1` no question (still only on a terminal, never with `--dry-run`) ([CONFIG.md](CONFIG.md) §7) |
| `UV_CACHE_DIR`, `npm_config_cache` | `$XDG_STATE_HOME/claude-agent-stack-cache/{uv,npm}` | Set by the installer in each local MCP server's `env` (the cache dir is an installer-internal `STACK_CACHE`, not a setting) |
| `CLAUDE_ENV_FILE` | set by Claude Code | The SessionStart hook appends the sandbox cache exports (`UV_CACHE_DIR`, `npm_config_cache`, `CARGO_HOME`, …, all under `~/.cache/claude-sandbox`) and an empty git credential helper |

## Plugins, MCP servers and tools

### Plugins

| Plugin | Marketplace | State | How to enable |
|---|---|---|---|
| `pyright-lsp`, `typescript-lsp`, `rust-analyzer-lsp`, `clangd-lsp`, `gopls-lsp`, `swift-lsp`, `jdtls-lsp`, `kotlin-lsp` | `claude-plugins-official` | Enabled by the installer when the server binary is on `PATH` | `./install.sh --with-lsp` installs pyright, typescript-language-server and rust-analyzer (and kotlin-lsp with brew); the rest come from Xcode or brew |
| `haskell-lsp`, `julia-lsp`, `lean-lsp`, `metals-lsp` | `agent-stack` (`dot-claude/stack-plugins/`) | Enabled when `haskell-language-server-wrapper`, LanguageServer.jl, `lake` or `metals` exist | `--with-lsp` uses ghcup, julia or cs when present; Lean needs elan |
| `document-skills` | `anthropic-agent-skills` | Installed; disabled where claude.ai already syncs docx/xlsx/pptx/pdf | `--keep-plugin-duplicates` keeps both |
| `skill-creator`, `math-olympiad` | `claude-plugins-official` | Not installed by default | `./install.sh --with-extra-plugins`; skill-creator is disabled where claude.ai syncs it |
| `mcp-server-dev` | `claude-plugins-official` | Disabled if present: `mcp-server-craft` covers it | `claude plugin enable mcp-server-dev@claude-plugins-official --scope user` |

Plugins are session-wide. Switch one for your user with `/plugin enable <id>` / `/plugin disable <id>`,
or for one project with `"enabledPlugins": {"<id>": true}` in its `.claude/settings.json`. Every
disable the installer makes prints its `claude plugin enable … --scope user` undo and is recorded for
`--restore`. Check with `claude plugin list` or the Errors tab of `/plugin`.

### MCP servers

Third-party servers are pinned to exact versions; to upgrade one, bump it in the repo (agent file,
`magg/config.json`, the installer's prefetch) and re-run the installer. Versions, vetting notes and
alternatives: [CONFIG.md §10](CONFIG.md#10-apps-connectors-and-mcp-servers).

**Inline, agent-scoped (17).** Declared in an agent's `mcpServers`; they start and stop with that agent.

| Server | Package | Agents | Needs |
|---|---|---|---|
| libdocs | stack's own (`mcp/libdocs_mcp.py`) | 32 coding, ML and planning agents | `EXA_`/`JINA_`/`SPIDER_API_KEY`, `GITHUB_TOKEN` optional |
| neural-memory | `neural-memory==4.62.0` via `mcp/neural_memory_mcp.py` | orchestrator, researcher, mathematician, main-/ninja-/supreme-coder, data-scientist, ml-/dl-/llm-/robotics-/quantum-engineer | — |
| image-studio | stack's own (`mcp/image_studio_mcp.py`) | designer, image-director | `OPENROUTER_API_KEY`, `OPPER_API_KEY` |
| playwright | `@playwright/mcp@0.0.82 --headless --isolated --output-dir ~/.cache/claude-sandbox/playwright-mcp --file-paths absolute` | browser-operator, frontend-engineer, verifier | Google Chrome |
| context-mode | `context-mode@1.0.169` | researcher, doc-specialist | Node ≥ 22.5 |
| spider | `spider-cloud-mcp@2.1.2` | researcher | `SPIDER_API_KEY` |
| markitdown | `markitdown-mcp@0.0.1a7` | doc-specialist | — |
| illustrator | `illustrator-mcp-server@1.10.3` | designer | macOS Automation grant |
| huetension | `huetension` 0.3.0 | designer | — |
| blender | `mcp-for-blender@2.1.1`, telemetry off | cg-artist | Blender running with the add-on |
| after-effects | Dakkshin/after-effects-mcp at `88d5fbf0` | motion-designer | `--with-adobe` |
| premiere | `premiere-pro-mcp@1.18.2` | motion-designer | `--with-adobe` |
| lean | `lean-lsp-mcp@0.30.0` | proof-checker | `LEAN_PROJECT_PATH` |
| postgres | `postgres-mcp@0.3.0 --access-mode=restricted` | db-engineer | `DATABASE_URI` |
| mongodb | `mongodb-mcp-server@3.0.5 --readOnly`, telemetry off | db-engineer | `MDB_MCP_CONNECTION_STRING` |
| mobilebuild | `mobilebuildmcp@2.7.1`, Sentry off | mobile-engineer | Xcode |
| magg | `magg` 1.2.1 via `bin/magg-private` | mcp-broker | the catalog keys |

**User scope (5 remote, session-wide).** Only agents whose `tools:` line names a server can call it.

| Server | Agents (from `tools:` lines) | Key |
|---|---|---|
| exa | 21 agents (scout, researcher, planner, coders, verifier, security-auditor, ML agents, …) | `EXA_API_KEY` optional |
| jina | 22 agents (scout, researcher, writer, mathematician, designers, ML agents, …) | `JINA_API_KEY` |
| wolfram | mathematician, proof-checker, quantum-engineer, ninja-coder, supreme-coder | none |
| huggingface | researcher, data-scientist, ml-/dl-/llm-/robotics-engineer | `HF_TOKEN` optional |
| wandb | ml-/dl-/llm-/robotics-engineer | `WANDB_API_KEY` |

Built into Claude Code: `computer-use` (cg-artist, designer, doc-specialist, game-engineer,
motion-designer, vfx-td, verifier; `/mcp` → computer-use → Enable, then grant Accessibility and Screen
Recording) and `claude-in-chrome` (browser-operator; start with `claude --chrome`).

**magg catalog (23, all disabled until mcp-broker mounts one).** Mounting a server (`magg_enable_server`)
always asks you. Calls then run without a prompt for the read-only or local servers (allow) and ask at
every call for the rest (ask).

<details>
<summary>The 23 catalog servers</summary>

| Server | Package | Calls | Keys |
|---|---|---|---|
| docling | `docling-mcp==3.2.1` | allow | — |
| playwright | `@playwright/mcp@0.0.82` | allow | — |
| lean | `lean-lsp-mcp@0.30.0` | allow | `LEAN_PROJECT_PATH` |
| arxiv | `arxiv-mcp-server==0.7.2` | allow | — |
| mlflow | `mlflow[mcp]>=3.5.1,<4` | allow | `MLFLOW_TRACKING_URI` |
| mongodb | `mongodb-mcp-server@3.0.5 --readOnly` | allow | `MDB_MCP_CONNECTION_STRING` |
| postgres | `postgres-mcp@0.3.0 --access-mode=restricted` | allow | `DATABASE_URI` |
| chrome-devtools | `chrome-devtools-mcp@1.10.1 --headless --isolated` | allow | — |
| duckdb | `mcp-server-motherduck@1.0.8`, in-memory | ask | `MOTHERDUCK_TOKEN` optional |
| jupyter | `jupyter-mcp-server@2.2.3` | ask | `JUPYTER_URL`, `JUPYTER_TOKEN` |
| docspace | ONLYOFFICE DocSpace (remote) | ask | — |
| ros | `ros-mcp@3.1.2` | ask | — |
| qiskit-runtime | `qiskit-ibm-runtime-mcp-server@0.6.1` | ask | `QISKIT_IBM_TOKEN` |
| mobile | `@mobilenext/mobile-mcp@1.0.8` | ask | — |
| android | `@us-all/android-mcp@1.14.4` | ask | — |
| godot | `@coding-solo/godot-mcp@0.1.1` | ask | `GODOT_PATH` |
| biomcp | `biomcp-cli==0.9.1` | ask | `NCBI_API_KEY` optional |
| pubchem | `@cyanheads/pubchem-mcp-server@0.6.5` | ask | — |
| kubernetes | `kubernetes-mcp-server@0.0.67 --read-only` (`magg/k8s-mcp.toml`) | ask | your kubeconfig |
| grafana | `mcp-grafana@2.0.0 --disable-write` | ask | `GRAFANA_URL`, `GRAFANA_SERVICE_ACCOUNT_TOKEN` |
| sec-edgar | `sec-edgar-mcp@1.1.0` | ask | `SEC_EDGAR_USER_AGENT` |
| serial | `~/.cargo/bin/serial-mcp`, port allowlist | ask | cargo (install.sh builds `serial-mcp@0.9.3 --locked`) |
| gis | `gis-mcp@0.15.0` | ask | — |

</details>

**Documented, not installed** (heavy, an app plugin, cloud credentials or hardware writes): unity-mcp,
Unreal_mcp, AWS aws-api-mcp-server, Azure MCP, gcloud-mcp, Alpha Vantage, KiCAD-MCP-Server,
embedded-debugger-mcp, slurm-mcp-server, lara-mcp, houdini-mcp, `gopls mcp`. The design, image, video,
3D, diagram and maths connectors are in [CONFIG.md §10](CONFIG.md#10-apps-connectors-and-mcp-servers) too.

**Rejected**, with the reason ([CONFIG.md §10](CONFIG.md#engineering-domains), "Engineering domains"):

<details>
<summary>Rejected servers and why</summary>

| Server | Reason |
|---|---|
| lamaalrajih/kicad-mcp | unmaintained since 2025-10 |
| qgis_mcp | no licence |
| whisper-mcp, local-stt-mcp, mcp-music-analysis | unmaintained |
| runreal/unreal-mcp | unmaintained |
| tandemai mcp-rdkit | repository gone |
| Flux159 mcp-server-kubernetes | its non-destructive mode still writes |
| unlicensed SLURM servers | no licence |
| Context7 | replaced by libdocs; the installer removes it |

</details>

### CLI tools agents rely on

| Tool | Used for | Installed or checked by the stack |
|---|---|---|
| `uv`, `uvx` | All Python: `uv run`, PEP 723 scripts, `uvx` tools | installed; doctor FAILs without |
| `node`, `npx` | npx MCP servers, JS/TS work | installed; doctor FAILs without |
| `git` | Every repository task (never push) | required |
| `/usr/bin/python3` | Hooks, status line, installer state | required |
| `jq` | JSON filtering | not checked |
| `rg` | Search in Bash | not checked |
| `gh` (read-only) | `view`, `list`, `status`, `checks`, `diff` only | not checked |
| `ffmpeg`, `magick`, `rsvg-convert`, `pdftoppm`, `sips` | Media, SVG and PDF rasterizing; `sips -Z 1919` downscales | installed with Homebrew if present; doctor warns; `sips` ships with macOS |
| `pandoc` | Document conversion | not checked |
| `claude-ninja`, `claude-supreme` | ninja-coder or supreme-coder as your main thread at ultracode | installed in `~/.local/bin` |
| Scanners: `gitleaks`, `trufflehog`, `semgrep`, `osv-scanner`, `pip-audit`, `npm audit`, `cargo audit`/`deny`, `trivy` | The read-only reviewers' allowlist | not installed; used when present |
| Language toolchains (cargo, ghcup, juliaup, go, Gradle/Maven, elan) | The language engineers | not installed; installing a toolchain from a session fails by design (sandbox) |

## Security model

The Bash sandbox is the intended boundary (`sandbox.failIfUnavailable: true`, no unsandboxed
fallback); the guard's shell parsing is defence in depth, and the prompts are the first line, not the
guarantee. Keys live only in `stack.env` (0600) and reach servers through `bin/mcp-headers` and
`bin/with-stack-env`; agents can't read `stack.env`, the backups or the usual credential files.
Consent for a destructive or externally visible action comes only from you, through BlackCat's
AskUserQuestion. Sandbox layout, managed settings, the least-privilege GitHub setup and the residual
risks: [CONFIG.md](CONFIG.md) §7.

> [!IMPORTANT]
> **The sandbox is configured, not live-verified.** The settings, the hook and the tests are checked;
> that Claude Code's sandbox enforces them on your machine is not. Until the live checks pass, count
> only the guard and the deny rules as tested.

### Live checks

Only you can run these.

1. **Install:** `./install.sh --dry-run`, read the plan, then `./install.sh` from a terminal. After a
   `git pull`, the supply-diff question appears; `n` leaves everything as it was.
2. **Sandbox denyWrite:** `/sandbox`, Config tab: `allowWrite` shows only `~/.cache/claude-sandbox`; the
   state dir, the backup root and the cache root show under deny. From sandboxed Bash, writes into
   `~/.claude`, the backup root, `~/.cache/uv`, the `STACK_CACHE` root and `~/Library/Caches/x` are
   refused.
3. **Env reach:** `echo "$UV_CACHE_DIR"` in the main thread's Bash and in a subagent's prints
   `~/.cache/claude-sandbox/uv`, expanded, in both; `git config --get-all credential.helper` prints an
   empty last line. Check whether settings `env` reaches MCP servers and hooks.
4. **Keychain from the sandbox:** whether the osxkeychain helper answers inside the sandbox (count the
   bytes of its answer, never print it).
5. **Routing:** a task with a supreme-coder plan step goes to the orchestrator.
6. **Ask rules:** an ask rule prompts in every mode, `bypassPermissions` included (start one session with
   `claude --permission-mode bypassPermissions`; for example a magg `duckdb_*` call).
7. **Credentials:** `bash ~/.claude/bin/doctor.sh`, section "GitHub credentials agents could use".

## Apps

Every app below runs Claude Code with your user settings, so it starts as BlackCat with the whole
stack. Checked on 27 Sep 2026.

| App | What to set |
|---|---|
| Terminal | once: `/effort medium`; the only place for `claude-ninja` / `claude-supreme` |
| Claude Desktop, Code tab (Local) | model Sonnet 5.5, effort medium; if `/stack-doctor` in a Desktop session shows an alias resolving elsewhere, add the three `ANTHROPIC_DEFAULT_*_MODEL` values from `stack.env` under Local → gear; computer use: Settings → General |
| Conductor | model Sonnet 5.5, thinking medium, Ultracode off |
| VS Code / Cursor extension, JetBrains plugin, Zed | nothing |
| Nimbalyst | the 1M model row with the CLI provider; its effort control sets `CLAUDE_CODE_EFFORT_LEVEL`, which overrides every agent's effort |

In the Agent SDK apps the model and effort pickers set the main thread; subagents keep their own. For a
plain session without BlackCat: `claude --agent claude`.

### Your own Agent SDK app

An SDK app gets the whole stack by loading its files: `setting_sources=["user", "project", "local"]`
(the default when omitted) and the `claude_code` system-prompt preset (omitting `system_prompt` in
Python sends an empty prompt). Hooks, permissions, agents, skills and rules then apply exactly as in the
terminal; SDK options (`model`, `max_turns`, `max_budget_usd`, tools, `permission_mode`) adjust the main
thread, and nothing they set loosens a hook or a deny rule. Don't pass `agents=`: the files are the
source of truth.

- `~/.claude/bin/stack_sdk.py` (optional, loaded by nothing): `options()` returns a plain
  `ClaudeAgentOptions` you can print and change; `run()` returns the parsed final report, session id,
  cost, per-model and per-subagent tokens and the delegation ledger path. CLI: `stack_sdk.py "task"
  --agent scout --max-turns 5 --budget-usd 0.5`.
- `STACK_REPORT_FORMAT=json` in the SDK's `env` makes every final report one JSON line
  (`input, timestamp, agent, status, eflag, result, evidence, files, next`); `status` may be `failed`;
  unset, the prompt does not change (the default `observe` only records).
- Details, the TypeScript form and what is unverified:
  `dot-claude/skills/claude-code-extensions/references/agent-sdk.md`. Cost and cold-start probe (real
  API calls): `uv run --script tests/sdk_smoke.py`.

## Troubleshooting

Start with `/stack-doctor`: each FAIL and WARN line names its section and the fix. The rows below come
from [CONFIG.md](CONFIG.md) §1 and §7, `doctor.sh`, and the agents' reports in the frozen baseline (run ids below; the run reports are kept
outside this repository).

| Symptom | Cause | Fix |
|---|---|---|
| A newly installed agent type is not found by a session that was already running | a running session keeps the agent files it started with | quit every Claude Code session and start a new one |
| Claude Desktop runs one subagent at a time and seems to hang | foreground children (CONFIG.md §1, bugs 1 and 3) | keep `BLACKCAT_BACKGROUND` unset or `1`; remove `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT` (the installer does; `/stack-doctor` warns) |
| The status line starts with a red `! Bash sandbox env missing` | the session-env hook could not write `$CLAUDE_ENV_FILE` | run `bash ~/.claude/bin/doctor.sh`, then start a new session or `/clear` |
| `claude-ninja` or `uv` "not found" although installed | `~/.local/bin` is not on `PATH` yet | open a new terminal (the installer's profile line adds it) |
| After `./install.sh --config-dir PATH`, Claude Code starts without BlackCat or the stack's agents | `CLAUDE_CONFIG_DIR` is not exported, so Claude Code reads `~/.claude` | add `export CLAUDE_CONFIG_DIR='PATH'` to `~/.zshrc` (bash: `~/.bash_profile`) and open a new terminal; `/stack-doctor` warns about this |
| Hooks or the status line stop working after the config folder was moved or renamed | `settings.json`, the hooks and the MCP entries hold the old absolute path | move it back, or reinstall: `./install.sh --config-dir <new path>` (and update `CLAUDE_CONFIG_DIR`) |
| `install.sh: refusing <path>: ...` (exit 2) | the target is unsafe: `/`, your home, inside the repo, credentials or system folders, a file, not writable | pick another folder ([Choose the config folder](#choose-the-config-folder)); nothing was changed |
| `install.sh: <path> is a non-empty folder with no Claude Code files` | a foreign folder as the target, without a terminal to confirm it | empty it or pick another folder, or run from a terminal and answer `y` |
| bash: stack.env keys missing in new terminals | macOS Terminal starts login shells, and bash reads `~/.bash_profile` there, not `~/.bashrc` (where the installer puts its line) | add `[ -f ~/.bashrc ] && . ~/.bashrc` to `~/.bash_profile` (the installer prints this note) |
| researcher or doc-specialist lose context-mode | Node older than 22.5 | `brew upgrade node` |
| `uvx …` fails inside a session ("Could not create temporary file … ~/.local/share/uv/tools") | the sandbox keeps uv's tool dir read-only (runs P11, P54, P59) | `uv run --with <tool> …`, or run `uvx` in your own terminal |
| Headless Chrome from Bash aborts ("Failed to create a ProcessSingleton … socket directory") | Chrome cannot start inside the Seatbelt sandbox (runs P43, P45) | use the playwright MCP (browser-operator, frontend-engineer, verifier), or run the browser tests in your terminal |
| `java -version` says "Unable to locate a Java Runtime" | `/usr/bin/java` is a stub until a JDK is installed (run P45) | install a JDK yourself, for example `brew install openjdk` |
| `ormolu` crashes with exit 134, missing `libgmp.10.dylib` | a broken GHCup ormolu install (run P35) | reinstall ormolu through GHCup from your terminal |
| Headless Blender crashes with SIGSEGV in the Metal backend inside a session | seen in run P57, cause not isolated | run that render from your own terminal |
| `sips` fails with "Cannot write to file /var/folders/…" inside a session | the sandbox refuses sips's temp file in the system temp folder (run P63; not confirmed to work in a normal terminal) | use `magick` for that step, or try `sips` in your own terminal |
| Installing a toolchain (rustup, cabal, Julia packages) from a session fails | by design: the sandbox keeps toolchain dirs read-only (CONFIG.md §7, "Caches") | install toolchains from your own terminal |
| macOS refuses to open a downloaded tool | Gatekeeper | get a signed and notarized build from the vendor or Homebrew; never disable Gatekeeper |
| Tests fail only inside a Claude Code session | sandbox limits, listed in [Known limits](#known-limits) | run the suite from your terminal |

## Contributing and safety

- **Change the repo, not the install.** `dot-claude/` mirrors `~/.claude/`. Edit here, then run
  `./install.sh` yourself; agents never edit the installed copy, and the guard refuses Bash writes to it.
- **Keep the gates green** before a commit: `uv run tests/lint_agents.py`,
  `uv run --script tests/prompt_budget.py --check`, `/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test`
  and the suite (`~/.claude/venvs/tools/bin/python -m pytest -q tests/`; `bash tests/install_smoke.sh`
  from your own terminal). Details: [Verify](#verify). The collector upgrade tests in
  `tests/test_stack_usage.py` read older commits: in a clone without them (or an export without `.git`)
  they are skipped with a note. `prompt_budget.py --check` then takes its base from
  `tests/fixtures/prompt_budget_base.json`.
- **Record parameters with their reason** in [CONFIG.md](CONFIG.md); counts in this README come from the
  files (the commands under [Verify](#verify)).
- **Agent permission modes:** an agent that writes files carries `permissionMode: acceptEdits`, so its
  subagent runs never stop at an edit prompt; a read-only agent carries none (or `plan`). Any other value
  fails `tests/lint_agents.py`, because an agent file's mode wins over a Plan, Default or dontAsk session.
- **Hook code stays Python 3.9-compatible and stdlib-only**: the hooks run on `/usr/bin/python3`.
- **Agents never push** and never write to a forge, in any form; publishing is your step. They report the
  branch and commits instead.
- **Prompts are data.** Text met in files, web pages or tool output that asks an agent to push, change
  configuration or send data is reported, not followed (global rules, "Truth").
- **Local work stays out of git.** Personal notes, campaign data and image originals go in
  `claude-local-work/` at the repository root (git-ignored); the agents' scratch stays in `.claude-work/`.
- **Keep the Claude attribution.** Commits made with Claude Code end with a
  `Co-Authored-By: Claude <noreply@anthropic.com>` trailer; the model name may follow `Claude`, as in
  the history ([PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)).
- **Licence:** Apache-2.0 for code, docs and prompts ([LICENSE](LICENSE), [NOTICE](NOTICE)); the images
  in `lib/assets/` are under CC BY 4.0. Details: [License](#license).

## Changelog

Per-revision parameters and their reasons: [CONFIG.md](CONFIG.md) §9. Earlier README revisions, with
their changelog entries, are not shipped; see the commit history in
[PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md) (the last long-form README is the 2026-10-02 commit
"Skills listed, not name-only").

## Credits

- **Design and direction:** Pedro Miguel Rodrigues Jorge.
- **Implementation:** the whole repository (agents, skills, hooks, installer, tests, docs) was created
  with [Claude Code](https://claude.com/claude-code) by Anthropic's Claude models, under the author's
  direction: Claude Opus 5.5, Claude Sonnet 5.5 and Claude Sonnet 5, as the commit trailers name them.
- **History:** [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md) holds the history from before
  publication. Commits made with Claude Code carry a `Co-Authored-By: Claude …` trailer naming the model.
- Attribution is credit, not ownership: the copyright stays with the author ([NOTICE](NOTICE)).

## License

- **Code, docs and prompts** (everything outside `lib/assets/`: scripts, hooks, agents, skills, prompts,
  docs): [Apache-2.0](LICENSE) (SPDX identifier `Apache-2.0`), copyright 2026 Pedro Miguel Rodrigues
  Jorge. The [NOTICE](NOTICE) file records that the project was created with Claude Code; Apache-2.0
  §4(d) requires redistributions to carry it.
- **The images in `lib/assets/`** (hero, its unmodified original, social preview, avatar):
  [CC BY 4.0](lib/assets/LICENSE-CC-BY-4.0.txt) (SPDX identifier `CC-BY-4.0`), with attribution to Pedro
  Miguel Rodrigues Jorge for the human contribution, his photograph of his cat: "Photo by Pedro Miguel
  Rodrigues Jorge, AI-edited with OpenAI GPT Image 2.5 Sunburst via Opper". The image was made from that
  photograph with OpenAI GPT Image 2.5 Sunburst (`openai/gpt-image-2.5-sunburst`) through Opper. Purely
  AI-generated elements may not be copyrightable (the [US Copyright Office](https://www.copyright.gov/ai/)
  holds that copyright does not extend to them), so CC BY 4.0 applies to the extent rights exist.
  Trademarks are not licensed (CC BY 4.0 §2(b)(2)). `blackcat-hero-original.png` is the unmodified model
  output with its provenance metadata (C2PA); the resized copies carry none. Statement:
  [lib/assets/README.md](lib/assets/README.md); provenance, prompts and hashes:
  [lib/assets/PROVENANCE.md](lib/assets/PROVENANCE.md).
- Third-party software the stack installs or calls (Claude Code, MCP servers, CLIs, the Python packages in
  `requirements/`) is not part of this repository and keeps its own licence.
- This section is an engineering note on what was checked (2026-10-03), not legal advice.
