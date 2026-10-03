# Claude Code multi-agent stack

<!-- markdownlint-disable MD013 MD060 -->

BlackCat, a dispatcher on the main thread, routes work to 55 specialist agents (56 agent files). 214
skills load on demand. One policy hook (`agent_guard.py`), deny rules and the Claude Code sandbox hold
the limits, and MCP servers start and stop with the agents that use them. Built for Claude Code
**2.1.271 or later**, macOS only (Apple Silicon first). It runs in the terminal and in the apps that run
Claude Code with your settings (see [Apps](#apps)).

Detail lives in two companion files:

- [CONFIG.md](CONFIG.md): every applied parameter (model, effort, `maxTurns`, caps, knobs) with its reason;
  installer internals, backups, sandbox and residual risks.
- [mcp_servers.md](mcp_servers.md): apps and connectors for your Claude plan, vetted MCP servers,
  documented-only and rejected ones.

The README this one replaces (installer flags in full, the spawn table, sandbox internals, changelog
entries) is `git show 96d3a52:README.md`.

**Contents:** [How it works](#how-it-works) · [Install](#install) ·
[Environment variables](#environment-variables) · [Plugins, MCP servers and tools](#plugins-mcp-servers-and-tools) ·
[Security model](#security-model) · [Apps](#apps) · [Changelog](#changelog)

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

#### Role agents (20)

| Agent | Model · effort | maxTurns | Inline MCP | Does |
|---|---|---|---|---|
| blackcat | Sonnet 5.5 · medium (session) | — | — | Main-thread dispatcher; never does the work |
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
| god-coder | Opus 5.5 · max | 350 | libdocs, neural-memory | Last-resort engineer after ninja-coder failed |
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

Routing in one paragraph: BlackCat classifies and dispatches (up to 8 children in one burst per prompt)
or hands dependent multi-specialist work to the orchestrator. Code escalates coder → main-coder →
ninja-coder → god-coder; language-heavy work goes to the language engineer, domain builds to the domain
expert. The helpers are leaves (no Agent tool); db-engineer and localizer are reached through their
family heads, not BlackCat. Depth is BlackCat → L1 → L2 → L3 → L4, and L4 cannot spawn.

### Skills: hubs, modules, references

214 skills in `dot-claude/skills/`, in three shapes (counts from `tests/test_skill_modules.py`'s own
parser):

| Shape | Count | What it is | Caps (`tests/test_skill_modules.py`) |
|---|---:|---|---|
| Hub | 24 | A `SKILL.md` with a `## Modules` table naming its modules | ≤ 80 lines |
| Module | 98 | A skill named in a hub's table; 83 are read by path, 15 listed | ≤ 150 lines, description ≤ 140 chars |
| Standalone | 92 | Neither hub nor module | ≤ 500 lines |
| `references/*.md` | 185 files | Detail a skill links to and reads only when needed | must exist where named |

- **Listed, not preloaded.** 128 skills (hubs, standalone skills, 15 modules) are listed with an
  explanatory description that starts with its trigger ("Load before …", "Use when …") and names no
  agent; 83 hub modules are `user-invocable-only` (below); `stack-doctor`, `override-agent` and `reset-agent` are user commands. No
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
  agent listing ≤ 0.97×, BlackCat's listing ≤ 0.96×, skill listing ≤ 0.478×, rules ≤ 0.95×, mean
  per-spawn cost of the baseline agents ≤ 0.691×.

`--base REV` prints a delta table; `--turns` reads local transcripts for p50/p90/max turns per agent.

**Hub modules are read by path.** The 83 modules named in a hub's table (`py-typing`, `rust-async`,
`sec-web-vulns`, …) are `user-invocable-only` in `skillOverrides`: they stay out of the skill listing
every agent carries, and the Skill tool refuses them, so an agent Reads
`~/.claude/skills/<name>/SKILL.md` when its `## Skills` line (where they are marked `name`*) or the
hub's table names one. That line (`## Skills, if needed`) is a lookup, not a checklist: a task that
needs no skill reads none. Hubs, standalone skills and 15 entry-grade modules (database engines, cloud,
k8s, obs, flutter, react-native, docs-sites, wasm, linux-nvidia-cuda) stay listed with their
descriptions. Measured in `.claude-work/agents-p3/lookup/lookup-eval.md`: −8.7K characters per spawn.

**`skillListingBudgetFraction` 0.012.** Claude Code caps the skill listing at context window × 3
chars per token × this fraction, and the cap is shared with plugin, bundled and claude.ai skills; over
it, the least-used skills silently lose their description. On the 1M-context 5.5 models 0.012 gives
36,000 characters: the stack's 14,564 plus ~14,169 for the others (plugins 2,919 measured, bundled
~3,950 and claude.ai ~7,300 estimated) with 25% to spare. `tests/lint_agents.py` fails when the listing
plus that 14,169 passes the budget; a session with a 200K window gets a fifth of the space.
`skillListingMaxDescChars` 500 cuts each description, and six user-run bundled commands are hidden
from the model through `skillOverrides`.

### Guard hooks

`dot-claude/hooks/agent_guard.py` is the single policy hook. A PreToolUse handler that errors denies
the call (fail closed); every hook command runs on an absolute interpreter chosen at install time.

| Guard | What it enforces |
|---|---|
| Spawn allowlist | `subagent_type` must name a stack agent in the caller's `POLICY` row. Generic and built-in types (`general-purpose`, `claude`, `fork`, `Plan`, …), a missing type and unknown types are refused for every caller; a generic agent started outside the Agent tool has every tool call refused. Caps: 3 running children per agent (orchestrator 32, main-/god-coder 6, ninja-coder 5, researcher 4, planner and plan-reviewer 8), 2 live copies per copy type, BlackCat 8 dispatches within 120 s and 12 tool calls per prompt |
| Read-only agents | code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide and proof-checker hold Bash, but only read-only commands pass (tests, linters in check mode, `git diff/log/show`, inspection, scanners); scratch code is content-checked; anything else is refused |
| No push | `git push` in any form and forge writes (`gh`/`tea`/`fj`, `gh api`, curl/wget/httpie to forge hosts) are denied, also inside `bash -c`, `eval`, `$(...)`, `ssh` and git's own command hooks. `STACK_POLICY=off` does not lift it |
| Protected paths | Bash-level writes, deletes and renames of the installed stack, the backups and the hook state are refused, on top of the Edit/Write deny rules; so is running `install.sh` except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs |
| Delegation ledger | Every Agent call is recorded as a tree (type, task, state, agent id) in `~/.local/state/claude-agent-stack/<session>/delegations.md`, which BlackCat reads; `agent_guard.py delegations [session] [--json]` prints it |
| god-coder once | Only the orchestrator spawns god-coder, once per session, and only after a ninja-coder of the session has finished (`GOD_SPAWNERS`, `GOD_ONCE_PER_SESSION`, `GOD_AFTER_NINJA`; the hook checks order, the prompts check that ninja-coder failed) |
| Soft token limits | Past its soft limit (context tokens per subagent run, by type: scout 390K … verifier 26M; 33M per human prompt, 80M while an orchestrator runs) an agent's next tool call carries one warning to wrap up, return `STATUS: partial` and ask before continuing; nothing is refused. Values, derivation and refresh (`tests/derive_thresholds.py`): [CONFIG.md](CONFIG.md) §5 |
| Also | Context-token budgets (hard) and the per-subagent MCP call cap; one agent on the screen; web-tainted agents can't write neural-memory; images re-encoded to ≤ 1919 px; BlackCat's children forced to the background; per-call `model` stripped |

The event-by-event table and the sandbox design are in [CONFIG.md](CONFIG.md) §5 and §7 and in
`agent_guard.py`'s module docstring.

## Install

### Prerequisites

| Tool | Why | How the stack treats it |
|---|---|---|
| macOS | The installer refuses other systems (`STACK_ALLOW_NON_MACOS=1` exists for the tests only) | required |
| Claude Code ≥ 2.1.271 | The stack targets it | required; older warns (`claude update`) |
| git, `python3` ≥ 3.8 (Xcode Command Line Tools: `xcode-select --install`) | Installer; hooks and status line run on an absolute system interpreter | required |
| uv | Every Python tool, script and MCP server | installed if missing (Homebrew, else the checksummed 0.12.20 tarball into `~/.local/bin`) |
| Python 3.14 as uv's default: `uv python install 3.14 && uv python pin --global 3.14` | Your projects' `uv run` without a pin | your step, not checked; the stack's own venvs pin 3.12 |
| Node.js ≥ 22.5 with `npx` | context-mode, the npx MCP servers, the TypeScript language server | installed with Homebrew if missing; older warns |
| pnpm (`corepack enable pnpm` or `brew install pnpm`) | node-engineer's projects | your step, not checked |
| jq | Cheap JSON filtering in agents' Bash (global rules) and in tests | your step, not checked |
| elan ([leanprover/elan](https://github.com/leanprover/elan)), then a built Mathlib project for `LEAN_PROJECT_PATH` | Lean: `lean-lsp@agent-stack` (`lake serve`) and proof-checker's lean server | your step; the plugin is enabled only when `lake` exists |
| Homebrew | Installs uv, node and the optional media tools | optional |
| magg 1.2.1, huetension 0.3.0 | mcp-broker's catalog; designer's colour server | installed (pinned, checksummed) |
| ffmpeg, ImageMagick, librsvg, poppler | Media and PDF work | installed with Homebrew if present, else warned |
| Google Chrome | playwright MCP | not checked |
| Xcode | mobilebuild, `swift-lsp`, `sourcekit-lsp` | not checked |

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

Run it from a terminal with no Claude Code session open (Desktop and Conductor included), from the
`main` branch (started elsewhere, it fast-forwards `main` and re-runs itself; it never pushes). The
eleven steps, as the run prints them:

1. **Prerequisites**: macOS, git, python3, Claude Code version, the absolute interpreter for hooks
   (`STACK_PYTHON`).
2. **Tools**: uv, node, magg, huetension, media tools, the hash-locked science venv
   (`~/.claude/venvs/sci`) and tools venv (`~/.claude/venvs/tools`: what the stack's scripts, MCP
   servers and tests import; `requirements/tools.in`); serial-mcp (`cargo install --locked` at the catalog's pin) when cargo
   is present, else one line saying it was skipped (Rust is never installed).
3. **ML venv** (`--with-ml`): `~/.claude/venvs/ml` from `requirements/ml.txt`, several GB.
4. **Adobe** (`--with-adobe`): the After Effects MCP at a pinned commit, the Premiere connector.
5. **Stage**: copy the stack's part of the config dir to a private staging dir.
6. **Render**: agents (with `-copy` renders), rules, skills, scripts, `settings.json`.
7. **Merge, validate, apply**: JSON, frontmatter, placeholders and the staged guard's `--self-test`;
   the plan; one backup; apply. A changed stack asks first on a terminal (`--yes` skips the question).
8. **MCP dependency prefetch** into the private `STACK_CACHE`.
9. **User-scope MCP servers**: exa, jina, wolfram, huggingface, and wandb when a key exists; keys come
   through the `bin/mcp-headers` header helper, never `~/.claude.json`.
10. **Plugins and code intelligence**: document-skills, LSP plugins for the servers it finds
    (`--with-lsp` installs missing ones), `--with-extra-plugins`; duplicates of claude.ai-synced
    skills disabled.
11. **Shell profile**: one line in `~/.zshrc` (and `~/.bashrc` if present) exporting the
    `STACK_EXPORT` keys and adding `~/.local/bin` to `PATH` (`--no-profile` skips it).

Other flags: `--no-prune`, `--force`, `--write-through-links`, `--no-mcp`, `--no-plugins`,
`--keep-plugin-duplicates`, `--replace-mcp`, `--no-deps`, `--mcp-plan`, `--print-managed-settings`.
`./install.sh --help` prints them all; [CONFIG.md](CONFIG.md) §7 explains staging, pruning and the
manifest.

### Restart Claude Code

Quit every Claude Code session (terminal, Desktop, Conductor, IDEs) and start new ones: a running
session keeps the agent files it started with. Then, once, in the first session: `/effort medium`.
`claude` starts as BlackCat; `/mcp` shows server status; `/stack-doctor` is the health check.

The stack's user commands (the model can't run them: `disable-model-invocation`):

| Command | Does |
|---|---|
| `/stack-doctor` | Read-only health check (`bin/doctor.sh`) |
| `/override-agent <agent> <model>` | This session only: every delegated `<agent>` runs on `<model>` (`sonnet`, `opus`, `haiku`, `fable`). The effort comes from the built-in table `hooks/agent_effort.json` (per agent and model, clamped to what the model accepts); it is shown but not applied (CONFIG.md §5, "Session model overrides") |
| `/override-agent list` | Read-only: this session's overrides (agent, model, effort and its source) and every agent's default model/effort |
| `/reset-agent <agent\|all>` | Back to the agent definition's model and effort |

### Verify

```bash
bash ~/.claude/bin/doctor.sh                                   # installed health check (= /stack-doctor)
/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test   # the hook on the hooks' own interpreter
uv run tests/lint_agents.py                                    # frontmatter, POLICY ↔ "May spawn", skills, listing budget
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
jq '[.skillOverrides[] | select(. == "user-invocable-only")] | length' dot-claude/settings.json   # 89 hidden: 83 hub modules + 6 bundled
jq '.servers | length' dot-claude/magg/config.json            # 23 catalog servers
grep -h '^  - [a-z-]*:$' dot-claude/agents/*.md | sort -u | wc -l   # 17 inline servers
uv run python -c "import sys; sys.path.insert(0, 'tests'); import test_skill_modules as t; h, m = t.hubs_and_modules(); print(len(h), len(m))"   # 24 hubs, 98 modules
```

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

## Environment variables

Names only; values never go into the repo, prompts or output.

### Keys and paths: `~/.claude/stack.env`

Every variable of `stack.env.example`. The file is 0600; servers read it at connect time, each gets only
its own keys, and upgrades append new variables commented out (the image and Claude models set to their
defaults) without touching yours.

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

The magg catalog keys reach mcp-broker's magg through `bin/with-stack-env --only …` and nothing else.

### Knobs

Set in `settings.json` → `env`. ● = shipped in `dot-claude/settings.json` and reset on every install:
change it in the repo and re-run the installer. The rest are defaults in `agent_guard.py` you may set
yourself.

| Variable | Default | Purpose | Read by |
|---|---|---|---|
| `STACK_POLICY` | `on` | `off` disables every deny and lock except the push and forge-write ban | guard |
| `STACK_AGENT_LABEL` | `description` | Child label: `description` (`<type>: <task>`), `name` (`<type>-<n>`), `off` | guard |
| `STACK_AGENT_STARTED` | `1` | SubagentStart gives a stack agent its start time (`0` = off) | guard |
| `STACK_REPORT_FORMAT` | unset | `json`: every final report is one JSON line (SessionStart and SubagentStart add one line); for Agent SDK apps | guard |
| `BLACKCAT_MAX_DISPATCH` ● / `BLACKCAT_DISPATCH_WINDOW_S` ● | 8 / 120 | BlackCat Agent calls per prompt, within this many seconds of the first | guard |
| `BLACKCAT_MAX_STEPS` ● | 12 | BlackCat tool calls per prompt | guard |
| `BLACKCAT_BACKGROUND` | 1 | Drop BlackCat's `run_in_background: false` | guard |
| `STACK_MAX_FANOUT` ● | 3 | Running children per agent (0 = no cap) | guard |
| `STACK_MAX_FANOUT_BY_TYPE` ● | `orchestrator=32,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | Per-type overrides | guard |
| `STACK_MAX_SELF_FANOUT` ● | 2 | Live copies per copy type | guard |
| `STACK_MAX_DEPTH` | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`, else 3 | Deny Agent from callers at this depth | guard |
| `STACK_PROMPT_CTX_BUDGET` ● / `STACK_SESSION_CTX_BUDGET` ● | 100000000 / 666000000 | Context tokens per prompt / per session, whole tree (0 = off) | guard |
| `STACK_MAX_MCP_CALLS` ● | 64 | MCP calls per subagent per prompt, lower if `maxTurns` is | guard |
| `STACK_SOFT_LIMIT_SCALE` | unset = 1 | Multiplies the soft token limits (per agent run, 33M per human prompt, 80M with an orchestrator); `0` = off | guard |
| `STACK_FANOUT_IDLE_S` ● | 600 (code: 1800) | A silent background subtree stops counting | guard |
| `STACK_LEASE_TTL_S` / `STACK_RESUME_TTL_S` | 21600 / 120 | Ceilings on unreported leases and resume reservations | guard |
| `GOD_SPAWNERS` / `GOD_ONCE_PER_SESSION` / `GOD_AFTER_NINJA` | `orchestrator` / 1 / 1 | Who spawns god-coder; once; after a finished ninja-coder | guard |
| `GOD_IDLE_S` ● / `GOD_PENDING_TTL_S` / `GOD_LOCK_TTL_S` | 1800 (code: 900) / 120 / 21600 | god-coder lock timers | guard |
| `SCREEN_LOCK_TTL_S` | 900 | Screen lock expiry | guard |
| `STRIP_AGENT_MODEL` | 1 | Remove per-call `model` | guard |
| `STACK_GUARD_LOG` | 0 | 1 = log hook events (tool names and ids only in budget mode) | guard |
| `STACK_IMAGE_MAX_PX` / `STACK_IMAGE_MAX_B64` | 1919 / 4500000 | Longest image side; most base64 chars per image | guard, image-studio, doctor |
| `STACK_IMAGE_UPLOAD_TOOLS` | — | Regex of more MCP tools whose image arguments get downscaled copies | guard |
| `STACK_ENV_FILE` ● | `~/.claude/stack.env` | Where the keys live | `mcp-headers`, `with-stack-env`, libdocs, image-studio |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` ● | 4 | Claude Code's nesting limit (its default is 3) | Claude Code, guard |
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | 33 | Subagents running in one session | Claude Code |
| `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS` ● | 1 | Built-in Explore and Plan off (the stack's `explore` replaces Explore) | Claude Code |
| `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS` ● | 1 | Every built-in type off in `claude -p` | Claude Code |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` / `_SONNET_MODEL` / `_HAIKU_MODEL` | from `stack.env` | Not in `dot-claude/settings.json`: the installer copies them from `stack.env` (Keys and paths above) | Claude Code |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` ● | 400 | WebSearch calls per session | Claude Code |
| `MCP_DISCOVERY_CACHE` ● / `_TTL_S` ● / `_MAX_STALE_S` ● | 1 / 21600 / 604800 | MCP discovery cache (unverified: not on the docs page checked for this README) | Claude Code |
| `MCP_TIMEOUT` ● / `MAX_MCP_OUTPUT_TOKENS` ● | 60000 / 25000 | MCP start-up timeout; tool output cap | Claude Code |

Don't set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every agent file's effort.

### Installer and session environment

| Variable | Default | Purpose |
|---|---|---|
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Install target |
| `STACK_CLAUDE_JSON` | `$CLAUDE_CONFIG_DIR/.claude.json` when that is set, else `~/.claude.json` | Which file the MCP plan reads |
| `XDG_STATE_HOME` | `~/.local/state` | Root of the guard state, the backups and `STACK_CACHE`; rendered into the sandbox rules at install time |
| `STACK_PYTHON` | chosen automatically | Absolute interpreter for hooks and the status line (never a pyenv/asdf shim) |
| `STACK_ALLOW_NON_MACOS` | 0 | Tests only: let the installer run off macOS |
| `STACK_CACHE` | `$XDG_STATE_HOME/claude-agent-stack-cache` | Set by the installer in each local MCP server's `env`: their private uv/npm caches |
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
alternatives: [mcp_servers.md](mcp_servers.md).

**Inline, agent-scoped (17).** Declared in an agent's `mcpServers`; they start and stop with that agent.

| Server | Package | Agents | Needs |
|---|---|---|---|
| libdocs | stack's own (`mcp/libdocs_mcp.py`) | 32 coding, ML and planning agents | `EXA_`/`JINA_`/`SPIDER_API_KEY`, `GITHUB_TOKEN` optional |
| neural-memory | `neural-memory==4.62.0` via `mcp/neural_memory_mcp.py` | orchestrator, researcher, mathematician, main-/ninja-/god-coder, data-scientist, ml-/dl-/llm-/robotics-/quantum-engineer | — |
| image-studio | stack's own (`mcp/image_studio_mcp.py`) | designer, image-director | `OPENROUTER_API_KEY`, `OPPER_API_KEY` |
| playwright | `@playwright/mcp@0.0.82 --headless --isolated` | browser-operator, frontend-engineer, verifier | Google Chrome |
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
| wolfram | mathematician, proof-checker, quantum-engineer, ninja-coder, god-coder | none |
| huggingface | researcher, data-scientist, ml-/dl-/llm-/robotics-engineer | `HF_TOKEN` optional |
| wandb | ml-/dl-/llm-/robotics-engineer | `WANDB_API_KEY` |

Built into Claude Code: `computer-use` (cg-artist, designer, doc-specialist, game-engineer,
motion-designer, vfx-td, verifier; `/mcp` → computer-use → Enable, then grant Accessibility and Screen
Recording) and `claude-in-chrome` (browser-operator; start with `claude --chrome`).

**magg catalog (23, all disabled until mcp-broker mounts one).** Mounting a server (`magg_enable_server`)
always asks you. Calls then run without a prompt for the read-only or local servers (allow) and ask at
every call for the rest (ask).

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

**Documented, not installed** (heavy, an app plugin, cloud credentials or hardware writes): unity-mcp,
Unreal_mcp, AWS aws-api-mcp-server, Azure MCP, gcloud-mcp, Alpha Vantage, KiCAD-MCP-Server,
embedded-debugger-mcp, slurm-mcp-server, lara-mcp, houdini-mcp, `gopls mcp`. The design, image, video,
3D, diagram and maths connectors are in [mcp_servers.md](mcp_servers.md) too.

**Rejected**, with the reason ([mcp_servers.md](mcp_servers.md), "Engineering domains"):

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
| `claude-ninja`, `claude-god` | ninja-coder or god-coder as your main thread at ultracode | installed in `~/.local/bin` |
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
5. **Routing:** a task with a god-coder plan step goes to the orchestrator.
6. **Ask rules:** an ask rule prompts under `bypassPermissions` (for example a magg `duckdb_*` call).
7. **Credentials:** `bash ~/.claude/bin/doctor.sh`, section "GitHub credentials agents could use".

## Apps

Every app below runs Claude Code with your user settings, so it starts as BlackCat with the whole
stack. Checked on 27 Sep 2026.

| App | What to set |
|---|---|
| Terminal | once: `/effort medium`; the only place for `claude-ninja` / `claude-god` |
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
  (`input, timestamp, agent, status, result, evidence, files, next`); unset, nothing changes.
- Details, the TypeScript form and what is unverified:
  `dot-claude/skills/claude-code-extensions/references/agent-sdk.md`. Cost and cold-start probe (real
  API calls): `uv run --script tests/sdk_smoke.py`.

## Changelog

Per-revision parameters and their reasons: [CONFIG.md](CONFIG.md) §9. Earlier README revisions, with
their changelog entries, are in git history (`git log --follow README.md`; the last long-form one is
`git show 96d3a52:README.md`).
