# Claude Code multi-agent stack

BlackCat, the dispatcher on the main thread, 35 specialists (36 agent files), 78 on-demand skills, short global
rules, a policy hook and MCP servers that start and stop with the agents that use them. Built
for Claude Code **2.1.271 or later** and checked against the 2.1.283 docs (26 Sep 2026). macOS only
(Apple Silicon first). It runs in the terminal and in the apps that run Claude Code with your
settings: Claude Desktop's Code tab, Conductor, VS Code, Zed, Nimbalyst (see [Apps](#apps)).

## Install

```bash
cd claude-agent-stack
./install.sh                      # core
./install.sh --with-ml            # + shared ML venv (see below; several GB)
./install.sh --with-lsp           # + language servers for the code-intelligence plugins
./install.sh --with-adobe         # macOS: build the After Effects MCP, install the Premiere connector
./install.sh --with-extra-plugins # + Anthropic skill plugins: skill-creator, mcp-server-dev, math-olympiad
$EDITOR ~/.claude/stack.env       # keys; read at connect time, no reinstall needed
claude                            # starts as BlackCat (the blackcat agent)
```

Flags combine. Other flags: `--no-mcp`, `--no-plugins`, `--dedupe-plugins` (disable the document-skills
and skill-creator plugins where claude.ai already syncs the same skills; it prints the command that
re-enables each, records them, and re-enables one once its synced copy is gone. Synced skills load
only in sessions signed in to claude.ai, so skip it if you also use API-key, gateway or Bedrock
sessions), `--replace-mcp`, `--force` (overwrite files
you edited), `--no-deps` (install nothing with brew/uv/npm; missing tools become warnings),
`--no-profile` (leave shell rc files alone), `--mcp-plan` (print what would happen to the user-scope
MCP servers and change nothing). `CLAUDE_CONFIG_DIR` changes the target (default `~/.claude`).

Inside Claude Code: `/stack-doctor` (health check), `/mcp` (server status), `/context`.

**Upgrading and rolling back.** Run the installer while no Claude Code session is running (Desktop
and Conductor included): a running session keeps the agent files it started with, while the hook
and settings change at once, so an old session would run old agents under new rules. Start new
sessions afterwards. To roll a revision back, `git revert` its commits on `main` and re-run
`./install.sh`: the manifest (`~/.claude/.stack-manifest.json`) records every setting and env key
the stack wrote, so keys the older version doesn't ship (for example `skillListingMaxDescChars`,
`skillOverrides`, the budget knobs) are removed while they still hold the stack's value, and
values it changed go back. Agent files it no longer ships (such as the rendered copy types) move
into the backup folder. Plugins `--dedupe-plugins` disabled stay disabled: re-enable them with the
`claude plugin enable <plugin> --scope user` line the installer printed. Keep the installer commit
that added this manifest retraction when reverting (it predates the settings it retracts).

**Installs only from `main`.** The installer runs from the `main` branch of this repository's git
checkout, always (no flag turns this off). Started from another branch or worktree, it first
fast-forwards local `main` to that checkout's commit (`git merge --ff-only`, in the worktree where
`main` is checked out; with none, the checkout switches to `main`) and re-runs itself from the `main`
checkout. It stops before installing anything, with the fix, when the fast-forward is blocked:
uncommitted or untracked files on the branch, uncommitted changes in the `main` checkout, or
diverged history (rebase the branch onto `main`, or merge `main` into it, then re-run). It never
pushes, and runs these git calls with hooks off so no hook can push either. `--mcp-plan` changes
nothing, so off `main` it refuses instead of merging.

**Safe to re-run.** Everything the installer would overwrite is copied to
`~/.claude/backup-<time>-<random>/` first, rc files included. A run that changes nothing keeps no
duplicate backup.
- Agents, the rules file and skills are tracked in `.stack-manifest.json`. A file you edited since
  the last install is kept, and the new version goes next to it as `<file>.new` (offered once;
  `--force` takes it). A same-named agent or skill of your own that was never the stack's is kept
  the same way. An untracked skill file is replaced only when every line of it is one an earlier
  stack version shipped (the repo's `legacy/` holds those versions). The installer's final summary
  lists every pending `.new`, and `/stack-doctor` warns about them.
- Agent files the stack no longer ships move into the backup's `retired/agents/` while unedited:
  `senior-coder.md` is now `main-coder.md`, and the main thread's `router.md` is now `blackcat.md`.
  An edited one stays (Claude Code would still load it), and the installer and `/stack-doctor` say
  so. The rename also moves `"agent": "router"` to `"blackcat"` and any `ROUTER_*` knob you tuned
  to its `BLACKCAT_*` name.
- **Your `~/.claude/CLAUDE.md` is yours.** The stack's global rules live in
  `~/.claude/rules/claude-agent-stack.md`, which Claude Code loads in every session and subagent.
  Upgrading from a version that installed them as `CLAUDE.md` (the one on the Mac did): a copy that
  holds nothing but the stack's old rules moves into the backup (`retired/`), together with an old
  `CLAUDE.md.new`; one with lines of your own stays, and you remove the old stack sections from it.
  This happens once; afterwards the installer never looks at `CLAUDE.md`.
- `settings.json` is merged, never replaced:
  - The stack owns `autoCompactEnabled`, `autoCompactWindow`, the guard hooks, the spawn depth, the
    concurrency cap, the MCP discovery cache, the no-push deny rules (`Bash(git push *)` and the
    common forge writes: `gh pr create|merge`, `tea pulls merge`, `fj pr merge`, ...) and
    `worktree.baseRef: "head"` (agents never push, so `origin/main` goes stale: new worktrees start
    from local work so they can fast-forward back into `main`); your other `worktree` keys stay.
  - `permissions.defaultMode: "bypassPermissions"`: sessions start without permission prompts
    (re-set on every install). Deny rules and the guard hooks still apply; the protections that
    were only a permission prompt (see [Security notes](#security-notes)) do not.
  - `"agent": "blackcat"`, `statusLine` and `skillListingBudgetFraction` are set while you have none
    of your own (see [Apps](#apps) and [Skills](#skills-dynamic)).
  - Other env knobs you changed are kept. Your own hooks, permission rules and keys stay.
  - Rules and env values the stack stopped shipping are retracted once, while they still hold the
    stack's value: on the upgrade from the Mac's version that is the blanket `mcp__magg` allow,
    `Read(**/.env.*)` and `ENABLE_TOOL_SEARCH=true`. Add one back and it stays.
  - Nothing runs on Haiku: `ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-sonnet-5` moves the `haiku` alias and
    Claude Code's background tasks (session titles, WebFetch page summaries) to Sonnet 5, and a Haiku
    value you had there is replaced. No agent names a Haiku model either. One exception: an app that
    routes models itself sets `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, and Claude Code then ignores this
    key in settings files (it logs "Ignoring ANTHROPIC_DEFAULT_HAIKU_MODEL from userSettings"). Claude
    Desktop can be such an app: see step 3 of [Claude Desktop, step by step](#claude-desktop-step-by-step).
  - Env vars that would silently defeat the 400K auto-compaction are removed:
    `DISABLE_AUTO_COMPACT`, `DISABLE_COMPACT`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`. It also removes
    `CLAUDE_CODE_SUBAGENT_MODEL[_FORCE]`, `CLAUDE_CODE_EFFORT_LEVEL` and stale `[1m]` model pins.
- The magg catalog gets new servers. An entry is updated only while it is still exactly what an
  earlier version shipped. Catalog servers are reset to disabled.
- `stack.env` keeps every value you wrote. Variables that are new in `stack.env.example` are appended,
  commented out — except the three image models, appended set to their defaults — and an empty `KEY=`
  is filled in when a key is rescued from an old MCP entry. Image lines that earlier versions of the
  example put there are brought up to date: stale comments get today's wording, and settings nothing
  reads any more are dropped while they still hold the old default (the previous file goes to the
  backup folder); a retired setting you changed stays, and the installer names it.
- MCP registration never writes a key into `~/.claude.json`. An entry that carries a plaintext key
  has the key copied into `stack.env` first; only then is it switched to the header helper. An
  entry with a `headersHelper` of your own (a password-manager script, say) is left alone.

The **shell profile line** (`~/.zshrc`, and `~/.bashrc` if you have one) exports only the
**non-empty** keys that CLI tools read, named by
`STACK_EXPORT` in `stack.env` (default: `HF_TOKEN WANDB_API_KEY GITHUB_TOKEN MLFLOW_TRACKING_URI
JUPYTER_URL JUPYTER_TOKEN`), and appends `~/.local/bin` to `PATH`. The OpenRouter, Opper, Exa, Jina and
Spider keys stay out of your shells: MCP servers read `stack.env` themselves, and a server started through
`with-stack-env` gets only its own keys. Upgrading from the old `set -a; . stack.env` line: variables
of your own in `stack.env` (an `OPENAI_API_KEY`, say) are added to `STACK_EXPORT`, so they stay
exported.

## What goes where

| Path | What |
|---|---|
| `~/.claude/rules/claude-agent-stack.md` | Global rules every agent loads (short on purpose). `~/.claude/CLAUDE.md` stays yours |
| `~/.claude/settings.json` | `"agent": "blackcat"`, auto-compact on with a **400K** window, depth 4, caps, permissions, hooks, status line (merged) |
| `~/.claude/agents/*.md` | 36 agent definitions, plus `researcher-copy.md` and `coder-copy.md` rendered from their base files |
| `~/.claude/skills/*/SKILL.md` | 78 skills (descriptions in context; bodies load on demand) |
| `~/.claude/hooks/agent_guard.py` | The policy hook (spawn policy, depth, fan-out caps, copies, god-coder lock, screen lock, BlackCat limits, secrets guard for local-file MCP tools) |
| `~/.claude/bin/mcp-headers` | `headersHelper`: gives exa/jina/huggingface/wandb their keys from `stack.env` at connect time |
| `~/.claude/bin/with-stack-env` | Starts spider/magg with just their own keys (`--only`; Claude Desktop passes only `PATH`); `--print-env sh` for the profile |
| `~/.claude/bin/claude-ultracode`, `~/.local/bin/claude-ninja`, `~/.local/bin/claude-god` | ninja-coder or god-coder as the main thread at ultracode (the two names link to the one script; written by the profile step) |
| `~/.claude/bin/magg-private` | Runs mcp-broker's magg on a private copy of the catalog (copies under the hook state dir, pruned after a day) |
| `~/.claude/bin/statusline.py` | Status line: agent · model · effort · context vs the 400K window · 5h/7d limits · cache hit |
| `~/.claude/bin/doctor.sh` | Health check behind `/stack-doctor` |
| `~/.claude/mcp/{libdocs,image_studio,neural_memory}_mcp.py` | MCP servers run with `uv run --script`: library docs; image-studio (SVG and edits through OpenRouter, photos and rasters through Opper; the models set in `stack.env`); neural-memory with the stack's settings |
| `~/.claude/neural-memory/` | The agents' shared long-term memory (SQLite brain `claude-agent-stack`, `config.toml`) |
| `~/.claude/magg/config.json` | On-demand MCP catalog (all disabled until mcp-broker mounts one) |
| `~/.claude/stack.env` | Keys (chmod 600) |
| `~/.claude/venvs/sci`, `~/.claude/venvs/ml` | Science venv (always); ML venv (`--with-ml`) |
| `~/.claude/.stack-manifest.json` | What the installer last wrote (edit detection, knob and catalog upgrades) |
| `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`) | User-scope MCP servers, written only through `claude mcp` |
| `~/.local/state/claude-agent-stack/<session>/` | Hook state: registry, leases, locks, markers. Pruned after 3 idle days |

## How your requirements are implemented

| Requirement | Mechanism |
|---|---|
| Subagent depth 4 | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4`: BlackCat → L1 → L2 → L3 → L4. L4 cannot spawn. The hook also tracks depth (it reads the same variable), so an L4 agent can't slip through. The rules add *when* to spawn: only for a missing capability, substantial parallel parts or independent verification — never pass-through or "just in case", and deeper than L2 only for a missing capability or a check. |
| One agent → several subagents concurrently | Interactive sessions run subagents in the background. An agent sends independent `Agent` calls in **one message** and they run in parallel. The results come back as task notifications. Caps: 3 running children per agent (`STACK_MAX_FANOUT`; orchestrator, planner and plan-reviewer 8 through `STACK_MAX_FANOUT_BY_TYPE`), 6 BlackCat dispatches per prompt (`BLACKCAT_MAX_DISPATCH`), 20 per session (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), and a context-token budget per prompt and per session (`STACK_PROMPT_CTX_BUDGET`, `STACK_SESSION_CTX_BUDGET`) past which the hook tells agents to finish with what they have, and at most 64 MCP tool calls per subagent per prompt (`STACK_MAX_MCP_CALLS`; a spawn or a resume starts a new count; an agent whose `maxTurns` is lower gets that instead). |
| subagent1 → subagent1 where it makes sense | researcher and coder, whose parts are most often independent, launch copies of themselves as their own agent types, `researcher-copy` and `coder-copy`: the installer renders them from the base file (same tools, model and `maxTurns`), and their policy rows list neither the base nor any copy, so a copy of a copy is a plain policy denial. At most 2 copies of a type run at once (`STACK_MAX_SELF_FANOUT`). Every other agent does parallel parts itself or hands them to another specialist: in the transcripts, copy-of-copy chains were about 10% of all tokens. |
| Auto-compact on, window 400K | `"autoCompactEnabled": true`, `"autoCompactWindow": 400000`. Compaction fires a little before the window is full: a little before 400K (the window minus an output reserve and a safety buffer). Subagents compact with the same logic. The installer strips env overrides that would defeat it, `/stack-doctor` warns about settings or shell exports that do (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE`, …), and the status line shows how close the next compaction is. |
| More agents for every Claude feature | ml-engineer, dl-engineer, llm-engineer, data-scientist, browser-operator (Claude in Chrome + Playwright), claude-code-engineer (skills, agents, hooks, plugins, settings, workflows) and ninja-coder (engineer-mathematician between main-coder and god-coder), on top of the existing 26 (senior-coder is now main-coder). BlackCat also runs the main-thread-only features: dynamic workflows, scheduled tasks and routines, push notifications, file hand-off. |
| The same setup in Claude Desktop and Conductor | Both run Claude Code with your user settings, so a Code-tab session or a Conductor chat starts as BlackCat with every agent, skill, hook, rule and MCP server, and auto-compacts at 400K. Checked against Conductor 0.87.5 on your Mac and by replaying its options through the Agent SDK. Pick Sonnet 5 and low effort there for BlackCat chats; see [Apps](#apps) for the differences. |
| Skills on demand, not tied to agents | Every agent has the Skill tool and sees every skill's description; it loads the ones whose description matches its task, and only then does a skill's body enter its context. No agent preloads a skill and no skill names an agent: a description says when to load it, never who. One `Skill` allow rule pre-approves them all, including skills you or a plugin add later, so background agents never stop at a prompt. 78 skills cover the work the agents do: engineering practice (Python, Rust, TypeScript, JVM, Julia, Haskell, CMake/Ninja, IDEs), performance, apps, systems, databases, mathematics and physics, ML/LLM and data, image-model engineering, robotics, LLM applications, research and writing, design, image and print, 3D, video. `tests/lint_agents.py` keeps it that way. |
| MCP servers on demand, auto on/off | See [MCP servers](#mcp-servers): agent-scoped servers start and stop with their agent, remote ones connect on first use, every schema stays deferred until needed, and rare ones are mounted and unmounted by mcp-broker. |
| Deep reasoning where it counts | The coordinating, planning and reviewing agents run at `xhigh` (orchestrator, planner, plan-reviewer, main-coder, code-reviewer, mathematician, quantum-engineer, security-auditor), ninja-coder and god-coder at `max`, most specialists at `high`; cheap lookups (BlackCat, scout, oracle) stay `low` so they answer fast. Opus 5.5's own default is `medium`. |
| Context that doesn't bloat | Measured with Claude Code 2.1.283 before this revision: a session started at about 42K tokens (plain Claude Code: about 34K) — the skill list about 9K, the agent list about 3.6K, the rules about 2K — and each subagent at about 40K, which prompt caching reuses after its first request. The skill descriptions are now half as long (about 15K characters) and the rules about 6% shorter; re-measure with `/context`. Auto-compaction fires a little before 400K. Skill bodies, MCP tool schemas and memories load only when used. |
| Images: SVG for graphics, raster for photos, edits for the rest | `image-studio` (image-director, designer): one tool per job, the model of each set in `stack.env` — `IMAGE_STUDIO_SVG_MODEL`, `IMAGE_STUDIO_IMAGE_MODEL`, `IMAGE_STUDIO_EDIT_MODEL` — and looked up in its provider's model catalog before every paid call, so an option or input the model lacks is refused for free. `generate_svg` — through OpenRouter (`OPENROUTER_API_KEY`), default Recraft V4.1 Pro Vector (`recraft/recraft-v4.1-pro-vector`, $0.30 an image, palette through Recraft's controls, one reference image); a model without SVG output is refused, and anything that isn't SVG is never saved. `generate_image` — through Opper (`OPPER_API_KEY`), default GPT Image 2.5 Sunburst (`openai/gpt-image-2.5-sunburst`): 1-4 images, quality low to max (about $0.006 to $0.21 at 1024x1024), 1K/2K/4K, transparency, up to 8 references; `collect_image` fetches one still rendering. `edit_image` — through OpenRouter, default Riverflow V2.5 Pro (`sourceful/riverflow-v2.5-pro`, $0.13 at 1K to $0.17 at 4K) with 1-10 input images. A missing key disables only the tools that need it; `/stack-doctor` shows the models in use and checks them. The rules keep logos, icons, illustrations and graphic design in SVG and allow no other image API. |
| Uploaded images under 1920 px | The image-limit hook (see [Enforced behaviours](#enforced-behaviours-hooks)): what agents read and what they upload through the browser tools; the image tools scale their own inputs in memory; the rules cover curl and scripts. |
| Squeeze context further | context-mode (researcher, doc-specialist): pages and long documents go into a local search index and only the passages asked for enter the context. neural-memory (12 agents): what earlier sessions settled is recalled on demand instead of re-derived, with nothing preloaded. See [Context economy](#context-economy-context-mode-and-neural-memory). |
| ninja-coder and god-coder at "ultra-code" effort | `claude-ninja` and `claude-god` start them as the main thread at ultracode: `xhigh` plus dynamic workflows, workflow launches pre-approved in those sessions only. That is the only place ultracode runs. Subagents can't run workflows, and `effort: ultracode` in an agent file is ignored: checked with the CLI, such a subagent ran at the calling session's `low`. Dispatched by BlackCat or another agent, both run at `max`, the deepest per-message level. |

## Agents

Models are the aliases `opus` (Opus 5.5), `sonnet` (Sonnet 5) and `fable` (Fable 5.1) — nothing
else. On the Anthropic API those aliases resolve to exactly these models; on Bedrock, Google Cloud,
Foundry or a Claude apps gateway they can resolve to older versions (see Claude Code's model-config
page), and `ANTHROPIC_DEFAULT_OPUS_MODEL`/`_SONNET_MODEL`/`_FABLE_MODEL` pin them there. All three run
with a native 1M window, so no `[1m]` pins are needed. The model, effort and `maxTurns` come from each
agent file: per-call `model` overrides are stripped by the hook. `maxTurns` is a runaway bound, set
from the transcripts (about twice the 90th percentile of calls per spawn): 20–40 for lookups, below
200 for every bounded agent, 250 for main-/ninja-/god-coder and 300 for the orchestrator;
`tests/lint_agents.py` enforces ≤ 350 and < 200. One turn is one model response (parallel tool
calls count once). An agent that hits it stops without a report of its own; Claude Code returns a
"stopped at its N-turn limit" note, and a SendMessage resume continues with a fresh N turns
(both probed with `claude -p`, 2.1.283). BlackCat has no `maxTurns`: it doesn't bind a main thread
(probed), so the hook's `BLACKCAT_MAX_STEPS` is its cap.

| Agent | Model · effort | For | Agent-scoped MCP | Shared MCP | Extras |
|---|---|---|---|---|---|
| **blackcat** — BlackCat (main thread) | Sonnet 5 · session level (choose low) | Classifies and dispatches (up to 6 agents in one burst, 8 tool calls per prompt); relays results; Read, Grep and Glob only for quick checks (a file exists, a child's claimed diff) | — | — | Workflows, cron/loop, routines, push, file hand-off |
| orchestrator | Opus 5.5 · xhigh | Multi-step / multi-domain work; ≤ 7 tasks in flight | neural-memory | — | cache 1h |
| planner | Opus 5.5 · xhigh | How to solve it: options, plan, owners, verification | libdocs | exa, jina | |
| plan-reviewer | Opus 5.5 · xhigh | Critique of a plan before execution | libdocs | exa, jina | |
| oracle | Opus 5.5 · low | Timeless knowledge, no web | — | — | |
| scout | Sonnet 5 · low | One current fact in ≤ 3 searches | — | exa, jina | |
| researcher | Opus 5.5 · high | Cited multi-source research; can crawl | spider, context-mode, neural-memory | exa, jina, huggingface | copies, cache 1h |
| mathematician | Opus 5.5 · xhigh | Proofs, derivations, symbolic/numeric computation | neural-memory | jina, wolfram | sympy/mpmath/scipy venv |
| **quantum-engineer** | Opus 5.5 · xhigh | Quantum computing and quantum-physics code: circuits, QuTiP, tensor networks, error correction, IBM Quantum runs | libdocs, neural-memory | exa, jina, wolfram | cache 1h; qiskit-runtime via the catalog |
| writer | Opus 5.5 · medium | Articles, blog (Markdown + LaTeX/Mermaid), emails, PT-PT/EN | — | jina | |
| doc-specialist | Opus 5.5 · medium | docx/xlsx/pptx/pdf read, analyze, create | markitdown, context-mode | — | screen (ONLYOFFICE) |
| image-director | Opus 5.5 · medium | Image generation and editing: SVG, photos and rasters, edits and composites (defaults: Recraft V4.1 Pro Vector and Riverflow V2.5 Pro through OpenRouter, GPT Image 2.5 Sunburst through Opper) | image-studio | jina | |
| designer | Opus 5.5 · high | Vector, brand, print, UI visuals, color; generated SVG art, photos and edits | image-studio, illustrator¹, huetension | jina | screen |
| motion-designer | Opus 5.5 · high | After Effects, Premiere, motion | after-effects¹, premiere¹ | — | screen |
| **cg-artist** | Opus 5.5 · high | 3D: Blender, ZBrush, Substance 3D Painter, Houdini FX, 3D printing | blender (MCP for Blender), libdocs | jina | screen; Houdini via hython (no MCP server exists) |
| coder | Sonnet 5 · medium | Small/medium code, offloaded sub-tasks | libdocs | exa | copies |
| main-coder (was senior-coder) | Opus 5.5 · xhigh | Large codebases, architecture, hard bugs | libdocs, neural-memory | exa, jina | cache 1h |
| **ninja-coder** | **Opus 5.5 · max** | Hardest code where it meets mathematics: novel algorithms, proofs, complexity, numerics, kernels | libdocs, neural-memory | exa, jina, wolfram | cache 1h, workflows |
| god-coder | **Fable 5.1 · max** | Last resort after ninja-coder; one at a time per session | libdocs, neural-memory | exa, jina, wolfram | cache 1h, workflows |
| frontend-engineer | Opus 5.5 · medium | Web front-end, a11y, verified in a headless browser | libdocs, playwright | exa | |
| devops-engineer | Sonnet 5 · high | CI/CD, containers, k8s, IaC, deploys (dry-run first) | libdocs | exa | |
| data-engineer | Sonnet 5 · high | SQL, schemas, pipelines, dataframes | libdocs | exa | |
| **data-scientist** | Opus 5.5 · high | EDA, tests, A/B + power, regression, causal, forecasting, reports | libdocs, neural-memory | exa, jina, huggingface | cache 1h |
| **ml-engineer** | Opus 5.5 · high | Tabular/time-series/classic ML, validation, MLOps | libdocs, neural-memory | exa, jina, huggingface, wandb | cache 1h |
| **dl-engineer** | Opus 5.5 · high | Architectures, training loops (PyTorch/JAX/MLX), ablations, NaNs | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h |
| **llm-engineer** | Opus 5.5 · high | Local inference (mlx-lm, oMLX), quantization, fine-tuning, evals, RAG, agents/MCP | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h |
| mlx-engineer | Opus 5.5 · high | Apple Silicon performance, Metal kernels, ports to MLX | libdocs | exa, jina | memory |
| cuda-engineer | Opus 5.5 · high | NVIDIA performance, CUDA/Triton, NCCL, vLLM; remote GPU hosts over SSH, remote Jupyter, Kaggle (CLI; web UIs via browser-operator) | libdocs | exa, jina | memory |
| **robotics-engineer** | Opus 5.5 · high | ROS 2, kinematics and control, SLAM, simulation, robot learning, hardware bring-up | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h; ros via the catalog |
| code-reviewer | Opus 5.5 · xhigh | Review of diffs/PRs (read-only) | libdocs | — | |
| verifier | Sonnet 5 · high | Runs tests, reproduces, re-checks facts, tests web UIs and native apps | playwright | exa, jina | screen |
| security-auditor | Opus 5.5 · xhigh | Threat model, exploitable issues (read-only) | — | exa | |
| **browser-operator** | Sonnet 5 · medium | Acts on web pages: your logged-in Chrome, or headless Playwright | playwright | claude-in-chrome | |
| mcp-broker | Sonnet 5 · medium | Finds, mounts, runs and unmounts MCP servers | magg | — | |
| **claude-code-engineer** | Opus 5.5 · high | Builds Claude Code config: skills, agents, hooks, plugins, settings, workflows | — | — | |
| claude-code-guide | Sonnet 5 · low | Questions about Claude Code / API / Agent SDK | — | — | |

**Bold** = added in this revision. ¹ after-effects only once `--with-adobe` has built it.
- **copies**: the agent may spawn its copy type (`researcher-copy`, `coder-copy`), at most 2 at a time;
  a copy spawns no copies and skips the memory lines (its parent recalls and remembers).
- **cache 1h**: the agent waits on background children, so its prompt cache is kept for an hour
  (`experimental.cacheTtl`). The 5-minute default would re-read its whole context at every wake-up.
- **memory**: the agent keeps a user-level `MEMORY.md` of verified facts about your machines
  (measured limits, working recipes), loaded when it starts. neural-memory is the other kind: project
  decisions and findings shared by the twelve agents that have it. Eight of them (researcher,
  data-scientist, ml-/dl-/llm-/robotics-/quantum-engineer, mathematician) recall once at the start
  of a task and remember at most three durable findings at the end; the orchestrator and the
  main-/ninja-/god-coder recall when continuing earlier work.
- **workflows**: `claude-ninja` / `claude-god` start the agent as the main thread at ultracode, and
  it lists the Workflow tool, so it can launch dynamic workflows (where your account has them). As a
  subagent it runs at `max`, without them.
- An agent file's `effort` counts only when the agent runs as a subagent. The main thread (the
  BlackCat, or any `claude --agent <name>`) runs at the session's level: pick it with `/effort` (saved
  per model) or `--effort`. For BlackCat, `/effort low` once in a BlackCat session.
- **Shared MCP**: remote user-scope servers; only agents that list them can call them (see [MCP servers](#mcp-servers) for where their instructions show up).

### Spawn policy (enforced by the hook)

Claude Code ignores `Agent(a, b)` lists inside subagents, so `agent_guard.py` holds the single
source of truth (`POLICY`). `tests/lint_agents.py` checks that every agent's "May spawn:" sentence
matches it. `general-purpose`, `fork` and every type not in the caller's row are denied. Resuming a
finished agent with SendMessage follows the same rows (an agent may always resume its own children
and its parent); messages to agents that are still running pass.

Agents of your own (other files in `~/.claude/agents/`) are in no row, so neither BlackCat nor the
stack's agents can spawn them. Run one directly with `claude --agent <name>`, or add it to
`blackcat.md`'s `tools:` line and a `POLICY` row in the repo's `agent_guard.py`, then re-run the
installer.

- **blackcat**: any specialist (at most 6 dispatches, all in one burst, within 8 tool calls per prompt); follow-ups go through SendMessage.
- **orchestrator**: every specialist plus Explore (copy types excluded).
- **Copies**: only researcher and coder, through `researcher-copy` and `coder-copy`; no other row
  lists its own type.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker,
  claude-code-guide, browser-operator, plan-reviewer, image-director.
- **Escalation**: coder → main-coder → ninja-coder → god-coder. ninja-coder takes a problem whose
  core is algorithmic or mathematical, or one main-coder failed twice; god-coder only what
  ninja-coder could not solve. Model work goes to ml-/dl-/llm-engineer, and platform performance to
  mlx-/cuda-engineer (the target hardware owns ports). Reviewers and the verifier never check their
  own work.

Everything else, row by row:

| Agent | May spawn |
|---|---|
| planner | scout, explore, claude-code-guide |
| researcher | researcher-copy, scout, doc-specialist, mathematician, data-engineer, data-scientist, browser-operator, mcp-broker |
| researcher-copy | scout, doc-specialist, mathematician, data-engineer, data-scientist, browser-operator, mcp-broker |
| writer | scout, researcher, mathematician |
| mathematician | scout, mcp-broker, quantum-engineer |
| doc-specialist | scout, mcp-broker |
| designer | image-director, scout, mcp-broker, cg-artist |
| motion-designer | image-director, designer, scout, mcp-broker, cg-artist |
| coder | coder-copy, explore, scout |
| coder-copy | explore, scout |
| main-coder | coder, explore, scout, verifier, code-reviewer, security-auditor, plan-reviewer, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, claude-code-guide, ninja-coder, god-coder |
| ninja-coder | main-coder, coder, mathematician, explore, scout, verifier, code-reviewer, security-auditor, researcher, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, god-coder, quantum-engineer |
| god-coder | coder, main-coder, ninja-coder, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, explore, scout, verifier, code-reviewer, security-auditor, mathematician, researcher |
| mlx-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder, god-coder |
| cuda-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, browser-operator, ninja-coder, god-coder |
| devops-engineer | coder, explore, scout, verifier, security-auditor, mcp-broker |
| data-engineer | coder, explore, scout, verifier, mathematician, data-scientist, doc-specialist, mcp-broker |
| frontend-engineer | coder, explore, scout, verifier, code-reviewer, designer, image-director, mcp-broker |
| data-scientist | data-engineer, ml-engineer, mathematician, coder, explore, scout, verifier, doc-specialist, writer, mcp-broker |
| ml-engineer | data-scientist, data-engineer, coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, browser-operator |
| dl-engineer | mlx-engineer, cuda-engineer, data-engineer, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, browser-operator, ninja-coder, god-coder |
| llm-engineer | mlx-engineer, cuda-engineer, dl-engineer, data-scientist, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, claude-code-guide, browser-operator, ninja-coder, god-coder |
| claude-code-engineer | claude-code-guide, scout, explore, verifier, code-reviewer, mcp-broker |
| quantum-engineer | mathematician, coder, explore, scout, researcher, verifier, code-reviewer, cuda-engineer, mlx-engineer, mcp-broker, ninja-coder |
| robotics-engineer | coder, explore, scout, researcher, verifier, code-reviewer, mathematician, dl-engineer, cuda-engineer, mlx-engineer, cg-artist, mcp-broker, ninja-coder |
| cg-artist | image-director, coder, scout, verifier, mcp-broker |

## Skills (dynamic)

Any agent can load any skill. Every agent has the Skill tool, sees each skill's one-line description
and loads a skill when its task matches; the body enters that agent's context only then. Nothing is
preloaded, no agent file names a skill, and no description names an agent. A skill you add (to
`~/.claude/skills/`, or through a plugin) is available to every agent at once: one `Skill` allow
rule pre-approves them all. If you open repositories you don't trust, replace it with
`Skill(<name>)` rules, since it also approves a repository's own `.claude/skills`.

Every agent sees one line per skill. The 77 model-invocable descriptions take about 15K characters
of each agent's context. Claude Code caps that listing at `skillListingBudgetFraction` of the
context window, 1% by default (the stack keeps it): about 30K characters on the 1M-context models
every agent here uses. Over the cap, the least-used skills lose their description and show by name
only. So that plugin, bundled and claude.ai skills fit alongside, the stack also cuts every
description at 500 characters (`skillListingMaxDescChars`) and lists six user-run commands
(`code-review`, `security-review`, `simplify`, `fewer-permission-prompts`, `keybindings-help`,
`init`) only in the `/` menu (`skillOverrides`); `./install.sh --dedupe-plugins` disables the
document-skills and skill-creator plugins where claude.ai already syncs the same skills. `/stack-doctor` reports the
size, and `tests/lint_agents.py` fails if the stack's own skills pass half the budget.

The budget is a share of the context window, so a session with a 200K window (a gateway or Bedrock
model without 1M context, or `CLAUDE_CODE_DISABLE_1M_CONTEXT`) gets a fifth of the space, about
6K characters: there the least-used skills show by name only. Raise `skillListingBudgetFraction`
in your own settings for such sessions if that matters. `--dedupe-plugins` (see Install) frees
about 3.4K characters where claude.ai already syncs the document and skill-creator skills.

**Engineering practice**

| Skill | Load it when |
|---|---|
| code-standards | writing or changing code, scripts or infrastructure config |
| review-protocol | reviewing code, a plan or security, or verifying someone else's work |
| secure-coding | code handles untrusted input, secrets, auth, crypto, dependencies, local servers or agent tool use |
| git-workflows | git beyond a plain commit: worktrees, rebases, history edits, recovery, secrets in history |
| python-engineering | a Python project or script: uv, pyproject, typing, ruff, pytest, packaging |
| rust-engineering | writing, testing or releasing Rust |
| typescript-engineering | TypeScript or JavaScript tools, sites and servers (TS 7 vs 6, Node, pnpm, Vite, ESLint, Vitest) |
| jvm-engineering | Java 21+, Scala 3 and Kotlin interop: JDKs, Gradle/Maven/sbt/Mill, tests, JFR/JMH, GC |
| julia-engineering | Julia: juliaup, Pkg environments, type stability, BenchmarkTools, SciML, GPUs |
| haskell-engineering | Haskell: GHCup, cabal/stack, warnings, laziness and space leaks, profiling, STM |
| cmake-ninja-builds | C/C++/CUDA builds: modern CMake, presets, Ninja, vcpkg/Conan, sanitizers |
| ide-workflows | VS Code, JetBrains IDEs via Toolbox, EditorConfig, Chrome DevTools |
| algorithm-design | a problem needs a non-trivial algorithm or data structure |
| formal-methods | code or a protocol needs machine-checked assurance: z3, TLA+, Kani/Miri, property tests, fuzzing |

**Performance**

| Skill | Load it when |
|---|---|
| accelerator-perf | before a benchmark, kernel or port, and before any speed or memory claim |
| cpu-performance | measuring or optimizing CPU-side speed or memory (macOS or Linux) |
| gpu-kernel-dev | writing or tuning a Metal (MLX), CUDA or Triton kernel, Blackwell `sm_120` included |

**Apps and distribution**

| Skill | Load it when |
|---|---|
| rust-native-gui | a native desktop GUI in Rust (Iced 0.14 first) |
| editor-engineering | editor or IDE internals: ropes, tree-sitter, LSP/DAP, terminals, GPU text |
| macos-app-distribution | packaging, signing, notarizing or shipping a macOS app |

**Systems and tooling**

| Skill | Load it when |
|---|---|
| linux-workstation | the CachyOS/Ubuntu laptop: NVIDIA Blackwell drivers, CUDA/PyTorch matching, fish, Wayland |
| self-hosting-ops | a personal service reached over Tailscale: Forgejo, containers, systemd, backups, runbooks |
| mcp-server-craft | building, testing or registering an MCP server |
| postgresql | PostgreSQL design, indexes, EXPLAIN, vacuum, lock-safe migrations, backups, pgvector |
| mongodb | MongoDB modeling, ESR indexes and explain, aggregation, transactions, sharding, security |
| claude-code-extensions | writing or changing Claude Code configuration |
| browser-automation | any multi-step browser task |
| computer-use-apps | any computer-use step (macOS) |
| stack-doctor | `/stack-doctor`, typed by you (runs doctor.sh in a forked claude-code-guide, which starts no MCP servers) |

**Mathematics**

| Skill | Load it when |
|---|---|
| proof-craft | proving, disproving, repairing or refereeing a mathematical claim |
| lean-formalization | Lean 4 and Mathlib code (the Lean server mounts from the MCP catalog) |
| category-theory | a categorical construction, proof or diagram |
| numerical-methods | writing or trusting any numerical computation: floating point, low precision, solvers |
| quantum-computing | a quantum derivation, simulation, circuit or hardware run |
| quantum-physics-numerics | simulating a quantum system outside the circuit model: ED, Lindblad, tensor networks |

**ML, LLMs and data**

| Skill | Load it when |
|---|---|
| ml-experiment | running or comparing a model, training run or evaluation |
| training-debug | a run misbehaves: NaNs, divergence, plateaus, overfitting, slow input pipelines |
| diffusion-flow-models | building, training, sampling or evaluating a diffusion or flow-matching model |
| image-model-pipelines | running, fine-tuning (LoRA/DreamBooth), serving or evaluating open-weight image generators |
| robotics-engineering | ROS 2, frames, ros2_control, Nav2, MoveIt, kinematics, control, estimation, bring-up |
| robot-learning | simulators, RL, imitation learning and VLAs, LeRobot, sim-to-real, success-rate evaluation |
| llm-finetuning | preparing data for or launching a fine-tune (mlx-lm on the Mac, PEFT/TRL on CUDA) |
| llm-quantization | any quantization or precision recipe, 0.5–1T-parameter MoE models on the 512 GB Mac included |
| llm-evals | before reporting any LLM quality number |
| local-llm-serving | running, serving, sizing or benchmarking an LLM on the Mac or the 12 GB GPU |
| hf-hub | downloading or publishing a model or dataset, multi-hundred-GB downloads included |
| dataset-curation | building, cleaning or auditing a dataset: licenses, PII, dedup, decontamination |
| data-analysis | any analysis of a dataset |
| data-visualization | a chart, figure or dashboard meant to communicate |

**LLM applications and agents**

| Skill | Load it when |
|---|---|
| rag-agents | a RAG pipeline or an LLM application on the Claude API or Agent SDK |
| graph-rag | retrieval or memory needs relations, multi-hop answers or facts that change over time |
| agent-harness-design | building an agent runtime: loop, tools, permissions, compaction, memory, multi-agent |
| prompt-and-brief-design | a system prompt, agent definition, CLAUDE.md, research prompt, output schema or few-shot set |

**Research and writing**

| Skill | Load it when |
|---|---|
| web-research | any web work beyond one search |
| literature-review | finding papers, building a bibliography, checking every citation |
| technical-writing | technical or scientific prose: articles, docs, READMEs, ADRs, reports |
| portuguese-pt-writing | anything in European Portuguese (pt-PT, not Brazilian) |
| latex-typesetting | LaTeX papers, theses, slides and arXiv submissions, or Typst |
| markdown-publishing | a Markdown publishing pipeline: math, Mermaid, Astro sites, Pandoc |
| book-production | a manuscript to print-ready PDF, DOCX or EPUB; KDP and IngramSpark |
| diagrams-as-code | a diagram as text: Mermaid, Graphviz, D2, PlantUML, TikZ/tikz-cd |

**Design, image and print**

| Skill | Load it when |
|---|---|
| brand-identity | creating or revising a logo or identity |
| typography | choosing, setting or specifying type |
| color-management | choosing, converting or checking colors for screen or print (ICC, CMYK, WCAG) |
| presentation-design | designing, rebuilding or exporting a slide deck |
| image-prompting | generating or editing an image: SVG for graphic design, photos and rasters, edits (the models set in `stack.env`) |
| svg-vector-craft | creating, converting or delivering vector files (SVG, Illustrator, cutters, plotters) |
| print-production | any file meant for print: bleed, profiles, ink limits, PDF/X, preflight |
| apparel-merch-print | artwork for garments or merchandise: screen, DTG, DTF, sublimation, vinyl, embroidery |
| tattoo-design | drawing or revising a tattoo design a studio can execute |
| raster-imaging | resizing, converting, compositing, compressing or rasterizing images with code |
| adobe-creative-cloud | Photoshop, InDesign, Lightroom, Acrobat, Bridge: scripting, actions, output |

**3D**

| Skill | Load it when |
|---|---|
| blender-3d | Blender modeling, scripting, materials, rendering, export, the MCP for Blender server |
| sculpting-texturing | sculpting (ZBrush, Blender), retopology, UVs, baking, Substance 3D Painter, PBR |
| houdini-fx | Houdini: VEX, Pyro, FLIP, Vellum, RBD, Solaris/Karma, hython and PDG |
| 3d-printing | design rules, mesh repair, parametric CAD, slicing, materials for FDM and resin |

**Video and motion**

| Skill | Load it when |
|---|---|
| media-ffmpeg | running ffmpeg or ffprobe |
| motion-graphics | motion for video or UI: easing, kinetic type, After Effects/Premiere, Lottie, delivery |

Anthropic's document skills (docx/xlsx/pptx/pdf) come from the `document-skills` plugin. If you are
signed in to claude.ai they are already synced as `anthropic-skills:*` and the plugin is skipped.
`--with-extra-plugins` adds three more Anthropic skill plugins: `skill-creator`, `mcp-server-dev`
and `math-olympiad`, available to every agent like the rest.

### Code intelligence (LSP)

The `LSP` tool in the coding agents' `tools:` lines stays inactive until a code-intelligence plugin
for the file's language is installed and its language server binary is on your `PATH`
([docs](https://code.claude.com/docs/en/plugins/code-intelligence)). Then Claude gets the server's
diagnostics after every edit, and go-to-definition, references and symbol search through `LSP`.
A server starts the first time Claude edits a file of its language, in the terminal and in Claude
Desktop's local sessions (the app reads `PATH` from your shell profile; cloud sessions start none).
Step 10 of the installer installs the plugin of every language whose server it finds:

| Language | Plugin | Server | `--with-lsp` installs it with |
|---|---|---|---|
| Python | `pyright-lsp@claude-plugins-official` | `pyright-langserver` | npm |
| TypeScript / JavaScript | `typescript-lsp@claude-plugins-official` | `typescript-language-server` | npm |
| Rust | `rust-analyzer-lsp@claude-plugins-official` | `rust-analyzer` | rustup |
| C / C++ | `clangd-lsp@claude-plugins-official` | `clangd` | — (Xcode Command Line Tools) |
| Go, Swift, Java | `gopls-lsp`, `swift-lsp`, `jdtls-lsp` (official) | `gopls`, `sourcekit-lsp`, `jdtls` | — (brew, Xcode) |
| Kotlin | `kotlin-lsp@claude-plugins-official` | `kotlin-lsp` | brew, when `kotlin`/`kotlinc` is present |
| Haskell | `haskell-lsp@agent-stack` | `haskell-language-server-wrapper` | ghcup, when present |
| Julia | `julia-lsp@agent-stack` | LanguageServer.jl in the environment `@claude-lsp` | julia, when present |
| Lean 4 | `lean-lsp@agent-stack` | `lake serve` | nothing (comes with elan) |
| Scala | `metals-lsp@agent-stack` | `metals` | cs (Coursier), when present |

`agent-stack` is the stack's own local marketplace (`dot-claude/stack-plugins/`, installed to
`~/.claude/stack-plugins/` and loaded in place) for the languages the official one has no plugin
for. CUDA `.cu` files get no server (clangd needs a CUDA toolkit, absent on macOS). Check with
`claude plugin list`, the **Errors** tab of `/plugin` (`Executable not found in $PATH` names a
missing binary), or ask Claude to introduce and fix a type error: a `Found N new diagnostic issues`
line under the edit means the server runs.

## MCP servers

**How servers turn on and off by themselves.**
1. **Agent-scoped (local stdio).** A server declared inline in an agent's `mcpServers` connects when
   that agent starts and disconnects when it finishes (sub-agents docs, "Scope MCP servers to a
   subagent"). Its instructions reach only that agent, not its children, and arrive a moment after
   the agent starts (probed with `claude -p`, 2.1.283). BlackCat declares none.
2. **Remote, user scope (HTTP).** They belong to the session. With `MCP_DISCOVERY_CACHE=1` (owned by
   the stack) a server used before, whose cache entry is younger than
   `MCP_DISCOVERY_CACHE_MAX_STALE_S`, connects on its first tool call; otherwise it connects at start
   in the background (mcp docs, "server status"). No setting makes a never-used server lazy. Only
   agents whose `tools:` line names a server can call it. Their instructions (jina and huggingface
   have some) load in the main thread; in `claude -p` probes a subagent without their tools saw
   none, while agents in Claude Desktop sessions have been seen carrying the instruction blocks of
   computer-use (the app's own server), jina, huggingface and even agent-scoped neural-memory. That
   is the host's doing, not something the stack's config sets; moving a server inline would not stop
   it (neural-memory is inline) and would reconnect it at every spawn, so the servers stay at user
   scope. Keys come from `stack.env` through `bin/mcp-headers` at every connection.
3. **Tool search**: even a connected server costs only tool names until a tool is actually used.
   This is Claude Code's default on the Anthropic API, so the stack leaves `ENABLE_TOOL_SEARCH`
   unset: `true` would force it through an `ANTHROPIC_BASE_URL` gateway that may reject it.
4. **On demand through mcp-broker + magg.** Catalog servers stay disabled. The broker enables one,
   runs the calls another agent needs, returns the results and disables it again.
   - Only the broker holds `mcp__magg`.
   - Catalog tools and magg's list/enable/disable are pre-approved.
   - Adding a *new* server, loading a kit or using `proxy` asks you first, because the broker
     reads web content.
   - magg saves every enable/disable into its config file, and every running magg reloads that
     file. So each broker's magg runs on a private copy of the catalog (`bin/magg-private`): brokers
     working in parallel never switch servers off under each other, and a run that ends early
     leaves nothing mounted for the next one. The shared catalog stays all-disabled.
   - To make a server permanent for an agent, the broker edits that agent's `mcpServers`.

Third-party servers are **pinned** to the versions checked on 26 Sep 2026 (a new release can't run
on your machine unannounced). To upgrade one, bump the version in the repo — agent files,
`magg/config.json` and the installer's prefetch step — and re-run the installer.

| Server | How | Used by | Key |
|---|---|---|---|
| libdocs (custom) | stdio, agent-scoped | coders, planner, plan-reviewer, reviewer, ML agents | uses EXA/JINA/SPIDER keys if set; `GITHUB_TOKEN` optional |
| image-studio (custom) | stdio, agent-scoped | image-director, designer | `OPENROUTER_API_KEY` (SVG, edits), `OPPER_API_KEY` (photos); models: `IMAGE_STUDIO_SVG_MODEL`, `_IMAGE_MODEL`, `_EDIT_MODEL` |
| spider (`spider-cloud-mcp@1.2.2`) | stdio, agent-scoped | researcher | `SPIDER_API_KEY` (the only key it gets) |
| playwright (`@playwright/mcp@0.0.82 --headless --isolated`) | stdio, agent-scoped | browser-operator, frontend-engineer, verifier | — (needs Google Chrome) |
| markitdown (`markitdown-mcp==0.0.1a7`) | stdio, agent-scoped | doc-specialist | — |
| context-mode (`context-mode@1.0.169`, the MCP server only) | stdio, agent-scoped | researcher, doc-specialist | — (Node ≥ 22.5) |
| neural-memory (`neural-memory==4.62.0` through `mcp/neural_memory_mcp.py`) | stdio, agent-scoped | orchestrator, researcher, mathematician, main-/ninja-/god-coder, ml/dl/llm-/robotics-/quantum-engineer, data-scientist | — |
| illustrator (`illustrator-mcp-server@1.10.3`), huetension | stdio, agent-scoped | designer | — (grant macOS Automation) |
| blender (`mcp-for-blender@2.1.1`, telemetry off) | stdio, agent-scoped | cg-artist | — (Blender running with the add-on: `uvx mcp-for-blender@2.1.1 install-addon`, then Connect) |
| after-effects (Dakkshin), premiere (`premiere-pro-mcp@1.18.2`) | stdio, agent-scoped | motion-designer | — (`--with-adobe`; after-effects is declared once built) |
| magg | stdio, agent-scoped | mcp-broker | only `JUPYTER_URL`, `JUPYTER_TOKEN`, `MLFLOW_TRACKING_URI`, `MOTHERDUCK_TOKEN`, `LEAN_PROJECT_PATH`, `MDB_MCP_CONNECTION_STRING`, `DATABASE_URI`, `QISKIT_IBM_TOKEN` from `stack.env` |
| exa `https://mcp.exa.ai/mcp?tools=web_search_exa,web_fetch_exa,web_search_advanced_exa` | remote | scout, researcher, planner, coders, verifier, security, ML agents | `EXA_API_KEY` optional (keyless is rate-limited) |
| jina `https://mcp.jina.ai/v1` | remote | scout, researcher, planner, math, writer, … | `JINA_API_KEY`, effectively required (reader, arXiv and PDF tools refuse without it) |
| wolfram `https://agenttools.wolfram.com/mcp` | remote | mathematician | none (free, stateless calls) |
| huggingface `https://huggingface.co/mcp` | remote | researcher, ml/dl/llm-engineer, data-scientist | `HF_TOKEN` optional (a wrong token makes it fail) |
| wandb `https://mcp.withwandb.com/mcp` | remote, registered only with a key | ml/dl/llm-engineer | `WANDB_API_KEY` |
| computer-use, claude-in-chrome | built into Claude Code | GUI agents; browser-operator | computer use: macOS, `/mcp` → Enable; Chrome: `claude --chrome`, claude.ai login |

**Catalog (disabled until mounted):**
- docling: local PDF/Office conversion with OCR.
- playwright.
- lean (Lean 4).
- duckdb: SQL over local files.
- arxiv: full papers.
- jupyter: needs your own running server.
- mlflow.
- docspace (ONLYOFFICE): OAuth. For regular use add it to Claude Code with `/mcp`, since magg
  can't keep keys out of its config.
- mongodb (`mongodb-mcp-server@3.0.4 --readOnly`, telemetry off): `MDB_MCP_CONNECTION_STRING`. Tools pre-approved (read-only).
- postgres (Postgres MCP Pro `postgres-mcp@0.3.0 --access-mode=restricted`): `DATABASE_URI`; EXPLAIN, index advice, health checks. Tools pre-approved (read-only).
- chrome-devtools (`chrome-devtools-mcp@1.10.1`, headless, isolated, no usage statistics or CrUX lookups): traces, Lighthouse, network, heap snapshots. Tools pre-approved; the hook holds its file arguments to the Read deny rules.
- ros (`ros-mcp@3.1.2`, over rosbridge): topics, services, actions. **Not** pre-approved — it can move a robot, so every call asks you.
- qiskit-runtime (`qiskit-ibm-runtime-mcp-server@0.6.1`): IBM Quantum hardware jobs, `QISKIT_IBM_TOKEN`. **Not** pre-approved — it spends your quota.

No maintained MCP server exists for Houdini, ZBrush, Substance 3D Painter, 3D-printer slicers,
InDesign or Photoshop (a community Photoshop/InDesign bridge, adb-mcp, needs a UXP plugin and a
proxy; not installed). cg-artist and designer use scripts (hython, husk, slicer CLIs, ExtendScript/UXP
via osascript) and computer use there. JetBrains IDEs ship an MCP server (2025.2+), but its
auto-configure writes an always-on user entry, so the stack leaves it out (see `ide-workflows`).

Entries you already have under the same names are kept. Services registered under other names don't
match the agents' allowlists, and the installer tells you which ones to rename.

### Context economy: context-mode and neural-memory

Neither shrinks the live window; auto-compaction at 400K does that. They keep things out of it.

**context-mode** indexes a page (`ctx_fetch_and_index`) or a local file (`ctx_index`) into a local
SQLite FTS5 store and returns a short preview; `ctx_search` then returns only the matching
passages, verbatim. It serves the two agents that read in bulk: researcher (long pages, docs
sections, anything queried twice) and doc-specialist (a long PDF converted to markdown on disk, then
searched). Its tools start with those agents and stop with them.
- **The MCP server, not the plugin.** The plugin's hooks run on nearly every tool call, rewrite
  every subagent's prompt with routing rules, block `curl`/`wget` and steer Bash output away from
  the context. That fights BlackCat, the spawn policy and the agents' own instructions, and costs
  a Node process per tool call. Without the hooks it saves less than the headline figure: it is a
  tool agents choose to use.
- **Allowed**: `ctx_fetch_and_index`, `ctx_index`, `ctx_search`, `ctx_stats`. **Denied**:
  `ctx_execute`, `ctx_execute_file`, `ctx_batch_execute` (they run code outside Claude Code's
  permission checks; agents run code through Bash), `ctx_upgrade` (it replaces the pinned version
  from GitHub), `ctx_purge` and `ctx_insight` (a hosted analytics dashboard). An agent's `tools:`
  line doesn't hide the tools of its own inline servers, so the deny rules are what holds.
- `ctx_index` reads any file you name. Its own Read-deny check misreads Claude Code's `//abs` and
  `~/` rule forms, so it would index `stack.env`, `~/.ssh` or `~/.aws`; the stack's hook checks the
  path first (see [hooks](#enforced-behaviours-hooks)) and refuses directories, so agents index
  files one at a time.
- Data: `~/.claude/context-mode/`; content older than 14 days is dropped at start. Licence: Elastic
  License 2.0 (free to use, not to offer as a service).

**neural-memory** is an associative long-term memory: a local SQLite graph with spreading-activation
recall. Twelve agents that do long, decision-heavy work share one brain, so a new session recalls what
an earlier one settled instead of re-deriving it. Nothing is preloaded: an agent pays tokens only for
what it recalls. The server runs through `mcp/neural_memory_mcp.py`, which:
- keeps the data in `~/.claude/neural-memory/` (brain `claude-agent-stack`), apart from any
  `~/.neuralmemory` of your own (4.62 still puts its consolidation lock files there);
- writes `config.toml` before the first start, if missing: 4 tool schemas instead of 10–63,
  compact results, no unasked-for "related memories", no version checks, no Mem0 sync. Without that
  file, nmem-mcp's first start adds four hooks to `~/.claude/settings.json` that would run on every
  session and every tool call. `/stack-doctor` warns if such hooks are present;
- replaces the server's instructions (about 560 tokens telling every agent to save everything) with
  the stack's policy in about 120: recall with project tags before re-deriving; remember only
  verified, durable decisions and findings; never secrets or raw output.
To start the memory afresh, delete `~/.claude/neural-memory/`. Claude Code's own agent memory
(`MEMORY.md`, see **memory** above) stays as it was.

## Enforced behaviours (hooks)

| Event | What the hook does |
|---|---|
| PreToolUse `*` (`agent_guard.py budget`) | The context-token budgets (`STACK_PROMPT_CTX_BUDGET`, `STACK_SESSION_CTX_BUDGET`), counted from the session's transcripts, subagents included. Over budget every call is refused except SubagentHandback, TaskStop, AskUserQuestion, ToolSearch loading one of them, and Write/Edit under a `.claude-work/` folder or the session scratchpad; the message says to finish with what the agent has (STATUS: partial). Also the MCP call cap: each subagent's `mcp__*` calls are counted per prompt (one run: a spawn or a resume starts a new count), and past min(`STACK_MAX_MCP_CALLS`, its `maxTurns`) further MCP calls are refused while other tools keep working (the main thread is left to BlackCat's step cap). Fails open: a transcript or counter it can't read warns and allows. |
| PreToolUse `Agent` | Checks, in order: spawn policy, depth, the copy rule, fan-out caps (atomic leases) and the BlackCat dispatch window. Takes the god-coder lock and strips a per-call `model`. Denies `isolation: "remote"`, because cloud agents load no hooks. |
| PreToolUse `SendMessage` | Resuming a finished agent follows the spawn policy (the caller's row, or its own child or parent) and counts against its parent's fan-out caps; resuming a finished god-coder takes the god-coder lock. BlackCat's SendMessage counts as one of its steps here, in the same decision as the resume's slot |
| PreToolUse `mcp__computer-use__*` | One agent on the screen at a time |
| PreToolUse local-file MCP tools: context-mode `ctx_index`, markitdown, docling, playwright, chrome-devtools (catalog) | A path or `file:` URI argument is checked against every `Read(...)` deny rule, yours and the project's, with Claude Code's `//abs`, `~/`, `/x` and relative forms. Each argument is read every way the tool might read it: `x:/../..` and `file:/../..` are relative paths to a tool that doesn't parse URIs; `~`, percent-encoding, symlinks and both the session's and the project's directory are tried. A directory that holds a protected path is denied, and `ctx_index` gets no directories at all (it would walk them). Oversized arguments are refused rather than checked, so the hook always answers within its timeout. Claude Code applies those rules to its own tools, not to MCP arguments. |
| PreToolUse `Bash\|Monitor\|PowerShell` (every call: no `if` filter) | The Git rule's **never push**: denies `git push`, `send-pack`, `lfs push`, `subtree push` and `svn dcommit`, and every forge write through `gh`, `tea` or `fj` (create, merge, review, comment, close, release, fork, `gh api`/`tea api` with a write method; read-only `view`, `list`, `checks`, `diff`, `checkout` pass), in the forms the deny rules miss: `git -C dir push`, `/usr/bin/git push`, `git 'push'`, `bash -c 'git push'`, `sh -c`, `zsh -c`, `eval`, `$(...)` and backticks, `$'\x67it'`, line continuations, heredocs, here-strings and pipes into a shell, `ssh host '...'`, `python -c`/`node -e` code that starts a process, and the places git itself runs a command (`-c alias.x=...`, `git config alias.x`, `core.editor`, `GIT_EDITOR=`, `submodule foreach`, `rebase --exec`, `bisect run`). A command decided only at run time (`git $X`, `g${X}it`, `$G push`, `xargs git`, `echo ... \| base64 -d \| sh`, `pwsh -EncodedCommand`) is refused, and so is a command the guard cannot finish checking (a parser error, nesting deeper than 8 levels, more than 64 heredocs on one line, more than 8 s of work). The command is parsed as bash/zsh would (quotes, comments, newlines, arithmetic); a heredoc body is code only when the command that owns it is a shell, `eval`, `ssh` or `source /dev/stdin`, so a commit message that mentions a push passes. PowerShell syntax is modelled only as far as `pwsh -Command`, `iex`, `Start-Process` and backtick escapes. It has no `if` filter because Claude Code's `if: "Bash(git *)"` does not fire for `bash -c`, `eval` or `/usr/bin/git` (tested on 2.1.283); commands that name no git/gh/tea/fj return at once (~40 ms a call, mostly Python start-up). Not switched off by `STACK_POLICY=off`. Best effort: an alias or function defined in an earlier command, a script file or download, a variable holding the whole command, or text assembled by string operations is out of its sight. |
| PostToolUse `Agent\|TaskStop`, SubagentStart/Stop, StopFailure | Registry of who spawned whom at which depth. Liveness: a stopped, failed or TaskStop-ed agent releases its locks. A parent that waits on its children still counts as alive while any child is. |
| PostToolUseFailure / PermissionDenied | Roll back leases and the BlackCat marker |
| UserPromptSubmit, SessionStart (startup/resume/fork) | Reset per-prompt BlackCat markers; clear stale locks; prune old state |
| PostToolUse `Read\|mcp__*`, PreToolUse `mcp__*` (image limit) | Every image an agent reads (Read, screenshots and other MCP image results) is re-encoded to at most 1919 px per side before the model sees it, and kept under the API's 5 MB image cap (JPEG at lower quality if needed; else left as it was). Local images that the browser upload tools (Playwright, Claude in Chrome) send off the machine are swapped for downscaled copies in a `.downscaled/` folder next to the original, which git ignores, under the same name — so the tools' own folder checks still pass. A copy is reused while it carries its original's modification time; nothing is ever deleted (remove `.downscaled/` folders whenever you like). JPEG stays JPEG, PNG stays PNG. The one refusal: an oversized image the hook can't copy (a symlink, an animated image, a folder it can't write) is refused with the `sips` command to make a copy. Otherwise it never blocks a call. Uses macOS `sips`. |

BlackCat's own frontmatter hook allows only its delegation tools plus Read, Grep and Glob (quick
checks, never investigation), and at most 8 tool calls per prompt, Agent dispatches included. Every hook command uses an **absolute interpreter** chosen at install time. A bare
`python3` broken by a pyenv/asdf shim would make every hook fail to start, which Claude Code treats
as "allow". `/stack-doctor` runs the real hook commands on calls that must be denied, to prove the
gate is closed, and checks that the budget hook is wired and still reads usage from real
transcripts (`agent_guard.py --check-budget`).

If the hook itself errors it denies the call (fail closed). The model gets a neutral reason, while
the escape hatch (`STACK_POLICY=off`) is shown only to you.

**Knobs** (`settings.json` → `env`). Values you change are kept on re-install, except the owned
ones (marked ●): the installer resets those to the stack's value, since the caps and budgets are
guarantees rather than preferences. To change an owned knob, change it in the repo's
`dot-claude/settings.json` and re-run the installer.

| Knob | Default | Meaning |
|---|---|---|
| `BLACKCAT_MAX_DISPATCH` ● / `BLACKCAT_DISPATCH_WINDOW_S` | 6 / 30 | BlackCat Agent calls per prompt, all within this many seconds of the first (0 = no window) |
| `BLACKCAT_MAX_STEPS` ● | 8 | BlackCat tool calls per prompt, Agent dispatches included |
| `STACK_MAX_FANOUT` ● | 3 | Running + starting children per agent, any type (0 = no cap) |
| `STACK_MAX_FANOUT_BY_TYPE` ● | `orchestrator=8,planner=8,plan-reviewer=8` | Per-type overrides of `STACK_MAX_FANOUT` |
| `STACK_MAX_SELF_FANOUT` ● | 2 | Copy agents (`researcher-copy`, `coder-copy`) of one type running at once, session-wide |
| `STACK_PROMPT_CTX_BUDGET` ● / `STACK_SESSION_CTX_BUDGET` ● | 100000000 / 120000000 | Context tokens (input + cache writes + cache reads, all agents) per human prompt / per session; past it the hook denies work tools and tells the agent to finish with what it has |
| `STACK_MAX_MCP_CALLS` ● | 64 | MCP tool calls (`mcp__*`) per subagent per prompt (a spawn or a resume starts a new count), capped lower by the agent's own `maxTurns` (scout and claude-code-guide 40, oracle 20); past it the hook denies MCP calls only (0 = off) |
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | 20 | Claude Code's own cap on subagents running in one session |
| `STACK_FANOUT_IDLE_S` | 600 | A background child whose whole subtree is silent this long stops counting |
| `STACK_LEASE_TTL_S` | 21600 | Ceiling on a spawn lease whose Agent call never reported back |
| `STACK_RESUME_TTL_S` | 120 | A resume reservation (SendMessage to a finished agent) whose agent never started stops counting after this many seconds |
| `GOD_IDLE_S` / `GOD_PENDING_TTL_S` / `GOD_LOCK_TTL_S` | 1800 / 120 / 21600 | god-coder lock: idle holder, unconfirmed lease, hard ceiling |
| `SCREEN_LOCK_TTL_S` | 900 | Screen lock expiry |
| `STRIP_AGENT_MODEL` | 1 | Remove per-call `model` |
| `STACK_POLICY` | on | `off` disables every deny and lock (bookkeeping continues) |
| `STACK_GUARD_LOG` | 0 | 1 = log raw hook events to the state dir (debugging); budget mode, which sees every tool call, logs only the tool name and ids, never the tool input |
| `STACK_IMAGE_MAX_PX` | 1919 | Longest side of any image an agent reads or uploads (0 = off) |
| `STACK_IMAGE_UPLOAD_TOOLS` | — | Regex of more MCP tool names whose image-file arguments get downscaled copies before upload |
| `STACK_IMAGE_MAX_B64` | 4500000 | Most base64 characters of one image sent to the model (the API refuses a 5 MB image) |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `claude-sonnet-5` | What the `haiku` alias and Claude Code's background tasks run on: Sonnet 5, so nothing runs on Haiku (Claude Desktop: [step 3](#claude-desktop-step-by-step)) |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | Web searches per session, all agents together (Claude Code default 200) |
| `MCP_TIMEOUT`, `MAX_MCP_OUTPUT_TOKENS` | 60000, 25000 | MCP start-up timeout (first `npx`/`uvx` downloads), tool output cap |

## Status line

`bin/statusline.py` renders a line like
`blackcat · Sonnet 5 · low · ctx 156K/400K ▓▓▓░░░░░ · 5h 23% · 7d 41% · cache 91%`.
- The **ctx** bar counts the main conversation's tokens against the 400K auto-compact window, so you
  see the next compaction coming (it fires a little before).
- 5h/7d are your plan's rate-limit windows (Pro/Max).
- It is set only if you had no status line. Remove `statusLine` from `settings.json` to turn it off.

## ML setup (`--with-ml`)

`~/.claude/venvs/ml` holds numpy/scipy/pandas/polars, scikit-learn, statsmodels, XGBoost, LightGBM,
PyTorch, Transformers, Datasets, Accelerate, PEFT and safetensors.
- **Apple Silicon**: also `mlx` and `mlx-lm[evaluate]` (so `mlx_lm.evaluate` works).

The ML agents use the project's own environment first, this venv second, and never the system Python.

Local inference stays MLX-native on the Mac (mlx-lm; oMLX as the local OpenAI/Anthropic-compatible
endpoint). CUDA work runs only on an NVIDIA host you name.

## Apps

Every app below runs Claude Code with your user settings, so it starts as BlackCat with the whole
stack: the 36 agents, the 78 skills, the hooks, the rules, your MCP servers and auto-compaction at
400K. Checked on 27 Sep 2026 against each app's documentation or code; for Conductor also against
the version on your Mac (0.87.5) and by running the stack through the Agent SDK with Conductor's own
options (see [How the apps were checked](#how-the-apps-were-checked)).

| App | Runs | What to set | Limits |
|---|---|---|---|
| Terminal (Ghostty, Terminal) | your `claude` | once: `/effort low` | none: the reference, and the only place for `claude-ninja` / `claude-god` |
| **Claude Desktop, Code tab** (Local) | Claude Code 2.1.281, built into Desktop 2.9939.2 | model **Sonnet 5**, effort **low** for BlackCat sessions | no agent teams; panel commands such as `/permissions` don't open; Desktop reads only `PATH` from your shell profile (the stack needs nothing else) |
| **Conductor** 0.87.5 | Claude Code 2.1.280, bundled | model **Sonnet 5**, thinking **low**, Ultracode **off** for BlackCat chats | always bypass-permissions (your deny rules and the guard still apply); Conductor's own tools (diff comments, terminal reading) aren't in the agents' tool lists |
| VS Code / Cursor extension | its own copy of Claude Code, same version as the extension | nothing | a subset of slash commands |
| JetBrains plugin | your `claude`, in the IDE terminal | nothing | none |
| Zed (Claude Agent) | Claude Code 2.1.280 through the ACP adapter | nothing | a few slash commands hidden; Zed's Terminal Threads run your own `claude` |
| Nimbalyst | Claude Agent: Claude Code 2.1.280; or the "Claude Code CLI" provider: your own `claude` in a pane | the 1M model row with the CLI provider (else 200K) | its effort control sets `CLAUDE_CODE_EFFORT_LEVEL`, which overrides every agent's own effort (tested); one process per turn |
| AionUI | your `claude`, in print mode | no AionUI MCP servers in Claude chats | enabling any AionUI MCP server passes `--strict-mcp-config`, which drops your MCP servers and the agents' own |

What differs from the terminal in these apps (Desktop, Conductor, Nimbalyst, VS Code and Zed all run
Claude Code through the Agent SDK):
- **Model and effort** come from the app's pickers and set the main thread: BlackCat takes the model
  you pick, not the Sonnet 5 in its file. Subagents keep their own model and effort.
- **Subagents return their results directly.** In the SDK a subagent doesn't wait for background
  children, so the rules have every agent pass `run_in_background: false` where the Agent tool offers
  it; calls sent together still run in parallel.
- **Plan mode**: BlackCat sends the planning to planner and leaves plan mode with ExitPlanMode.
- **Questions**: Conductor replaces AskUserQuestion with its own tool; BlackCat has both.
- **A plain Claude Code session** instead of BlackCat: `"agent": "claude"` in a project's
  `.claude/settings.json` (that repository only) or in `~/.claude/settings.json` (everywhere; the
  installer keeps it, and `claude --agent blackcat` starts the stack). In your own SDK code:
  `settings: { agent: "claude" }`, or `settingSources: ["project", "local"]` to leave the stack out.
  In scripts: `claude -p --agent claude "…"`.
- **`claude -p`** starts in the stack's `defaultMode` (`bypassPermissions`): nothing is refused
  except deny rules, the guard hooks and the calls no mode auto-approves. Pass
  `--permission-mode default` (or `acceptEdits`, or a narrower `--allowedTools`) for scripted work
  that should refuse commands that aren't pre-approved.

### Claude Desktop, step by step

1. Install once from Terminal (`./install.sh`), then **restart Claude Desktop**. Open **Code**, choose
   **Local** and your project folder.
2. Set the model to **Sonnet 5** and effort to **low** (Cmd+Shift+E). Each subagent uses the effort in
   its own file.
3. **Background model**: in the environment dropdown, hover over **Local**, click the gear and add
   `ANTHROPIC_DEFAULT_HAIKU_MODEL` = `claude-sonnet-5`. Desktop can route models itself, and Claude Code
   then ignores that key in `settings.json`, so session titles and WebFetch summaries would stay on
   Haiku 4.5; variables set here reach the session directly. Your agents never run on Haiku either way.
4. **Keys** need nothing extra: exa/jina/huggingface/wandb get them from `stack.env` through
   `bin/mcp-headers`, image-studio and libdocs read `stack.env` themselves, spider and magg start
   through `bin/with-stack-env`, and every command is an absolute path.
5. **Computer use**: Settings → General → turn it on, then grant Accessibility and Screen Recording.
6. **Check**: send `@oracle what is a monad?`; the subagent pane shows oracle.
7. Use **Customize → Connectors** where the terminal would use `/mcp`. Desktop's Chat tab (not Code)
   has no subagents, hooks or BlackCat.

### Conductor, step by step

1. Nothing to install in Conductor: it reads `~/.claude` (settings, agents, skills, hooks, rules) and
   `~/.claude.json` (MCP servers). Its bundled Claude Code (2.1.280) is recent enough; if you switch
   it to your own `claude` (Settings → Storage), keep that at 2.1.271 or later.
2. For each chat: model **Sonnet 5**, thinking **low**, Ultracode **off** (with Ultracode on, the
   BlackCat itself would start dynamic workflows).
3. Work runs in the workspace's git worktree under `~/conductor/workspaces/`. The agents' scratch
   folder `.claude-work/` is excluded from git there too.
4. For ninja-coder or god-coder at ultracode, use `claude-ninja` / `claude-god` in a terminal (Conductor
   has no way to pick the main-thread agent); dispatched from a Conductor chat they run at `max`.

### How the apps were checked

- Conductor 0.87.5, read on your Mac: it starts Claude Code 2.1.280 through the Agent SDK with
  `settingSources: ["user", "project", "local"]`, the `claude_code` system prompt,
  `permissionMode: "bypassPermissions"`, the chat's model and effort, AskUserQuestion swapped for its
  own tool, its own MCP server and a `conductor` skill.
- Those options were replayed with Agent SDK 0.3.283 and Claude Code 2.1.283 against a fresh install
  of the stack:
  - the main thread was BlackCat, with its tool list; 33 agents and 61 skills of that revision (plus the built-in
    ones) loaded;
  - hooks fired (SessionStart, UserPromptSubmit, PreToolUse, SubagentStart/Stop, PostToolUse);
  - auto-compaction: 800,000-token window from settings, threshold 767,000 (Opus 5.5);
  - a coder subagent ran at its own effort (medium) under a session at low;
  - BlackCat → coder → two coder copies in parallel returned the right SHA-256 digests, and skills
    loaded without a prompt;
  - in plan mode BlackCat handed planning to planner.
- Found on the way, and fixed: an agent whose command was refused (`claude -p`, default mode) reported
  a guessed value; the rules now require reporting the refusal instead.
- Desktop, VS Code, Zed, Nimbalyst and AionUI: their documentation, and the code that starts Claude
  Code (Desktop's app package, the VS Code extension, Zed's adapter, Nimbalyst's and AionUI's source).

## Using it

- Just talk to it. To force an agent, start with `@designer …` or `god-coder: …`.
- Long single-domain sessions can skip BlackCat: `claude --agent main-coder --effort high`. The
  spawn policy of that agent still applies. Pass `--effort`: a main-thread agent takes the session's
  level, not its file's (Opus 5.5 defaults to `medium`).
- The hardest problems in a session of their own, at ultracode: `claude-ninja` or `claude-god`
  (any `claude` flags pass through, e.g. `claude-ninja -c`). They run
  `claude --agent <ninja|god>-coder --effort ultracode` with workflow launches pre-approved for that
  session. `claude --agent ninja-coder --effort max` is the other option: the deepest per-message
  reasoning, no workflows. Dispatched by BlackCat, both agents run at `max`.
- Don't set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every agent file's effort. `/effort` only sets
  the session level, which each subagent's own `effort` overrides.
- Optional: `/advisor opus` gives the Sonnet and Opus agents an Opus advisor at decision points
  (Fable's god-coder rejects it). It is experimental and costs extra.

Smoke tests:
- `@oracle what is a Kan extension?`
- `what's the latest stable Rust version?` (scout)
- `plan how to migrate my Astro blog to MDX` (planner)
- `@researcher compare LoRA, DoRA and QLoRA for a 70B MoE on a 512 GB Mac; split the work` (parallel
  researcher copies)
- `@llm-engineer quantize <model> to ~4.5 bpw with mlx and report Δppl` (loads llm-quantization,
  then llm-evals)
- `ask two god-coders in parallel to …` (the second is denied)
- `@ninja-coder find an O(n log n) algorithm for …, prove it, and property-test it against a brute
  force` (derivation, z3/sympy checks, hypothesis tests, verifier)
- `/context` and `/stack-doctor`

## Security notes

- One `Skill` allow rule pre-approves every skill, a repository's own `.claude/skills` included (see
  [Skills](#skills-dynamic)).
- Keys live only in `stack.env` (0600).
  - Remote MCP servers get them through the header helper at connect time.
  - Nothing goes into `~/.claude.json`, argv or agent files.
  - The installer rescues plaintext keys from old MCP entries into `stack.env`.
  - Your shells (and so every agent's Bash, hook and MCP process started from them) get only the
    `STACK_EXPORT` keys that CLI tools need; spider and magg get only their own keys. Keep
    `STACK_EXPORT` short: anything exported can be read by an agent's Bash call.
  - Optional hardening: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` in `settings.json` → `env` makes
    Claude Code strip the credentials it recognizes from the environment of Bash, hooks and MCP
    stdio servers. CLI tools may then need
    their own logins (`hf auth login`, `wandb login`).
- Deny rules keep agents out of `stack.env`, `.credentials.json`, both `.claude.json` locations,
  `~/.ssh`, `~/.aws`, `gh` hosts, the HF token, `.netrc` and the `.env` files that usually hold
  secrets (`.env`, `.env.local`, `.env.*.local`, `.env.dev[elopment]`, `.env.prod[uction]`,
  `.env.stag[e|ing]`). `.env.example`, `.env.test` and the like stay editable: a Read deny also
  blocks Edit and Write.
- Deny rules stop the agents' Edit/Write tools from changing the hooks, `bin/`, `settings.json`,
  `stack-plugins/` (its language-server commands run on their own) or the hook state (Bash is not
  covered).
- MCP tools that read local files (context-mode's `ctx_index`, markitdown, docling, Playwright's
  `file:` URLs and uploads) are held to the same Read deny rules by the hook, so a prompt injected
  into a web page can't pull `stack.env` in through them. context-mode's code-execution tools are
  denied outright.
- image-studio sends each key only to its own provider (OpenRouter, Opper) and follows no
  redirects with a key; result downloads carry no key and must be https to a public host. An input
  image goes out only if it is a real PNG/JPEG/WebP outside credential folders (scaled under 1920 px
  in memory), saved SVGs lose scripts, event handlers and `javascript:` links, and no file overwrites
  another.
- mcp-broker can't add servers, load a kit, or use `proxy` without asking: `permissions.ask`
  names `magg_add_server`, `magg_load_kit` and `proxy`, so they still prompt even in
  `bypassPermissions` (explicit ask rules are one of the few things no mode auto-approves). Every
  other prompt for a tool or Bash command that no deny rule or guard hook blocks is skipped in
  that mode. Page, document and tool text is treated as data, never as instructions.

## For maintainers

```bash
uv run tests/lint_agents.py                       # frontmatter, maxTurns tiers, POLICY ↔ "May spawn", copy types, bare python/pip, skills, listing size
/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test   # the hooks' own interpreter (the one exception to uv)
uv run --python 3.12 --with pytest --with pillow --with httpx --with "mcp>=1.10,<2" pytest -q tests/
bash tests/install_smoke.sh                       # hermetic: fake claude, scratch CLAUDE_CONFIG_DIR
```

`legacy/<version>/` holds files as the version before this one installed them, untracked: the global
`CLAUDE.md`, the skills and `agents/senior-coder.md` (now main-coder). The installer uses them to
recognise a copy that holds nothing but the stack's own lines. Everything is hash-tracked in the
manifest from this version on, so nothing new needs to go there.

A new skill is a folder with a `SKILL.md` whose frontmatter has `name` (the folder name) and a
one-line `description` that starts with its trigger ("Load before …", "Use when …"), names no agent
and has no `: ` or ` #` in it (YAML). The lint checks all of that and the listing size. The
installer replaces its placeholders (`__CLAUDE_DIR__`, `__HOME__`, …) in skill bodies, and the smoke
test fails on any `__UPPERCASE__` token left after that, so keep such tokens out of examples.

The installer refuses to run outside macOS; the smoke test sets `STACK_ALLOW_NON_MACOS=1` so it also
runs on Linux (CI, containers). It passes under macOS's bash 3.2 and Python 3.9 too, and simulates
the macOS render of the Adobe servers. `STACK_GUARD_LOG=1` in a live session records raw hook events, which is the way
to confirm undocumented runtime details:
- whether `SubagentStop` fires for stopped agents;
- `prompt_id` on scheduled turns;
- agent-id formats.

## Troubleshooting and restore

- **`/stack-doctor` first.** It prints the exact fix for each FAIL.
- **A spawn you expected was denied.** The reason names the rule. For a stuck lock, `/clear` doesn't
  help; restart with `claude --resume` (SessionStart clears locks) or wait for the TTL.
- **Bypass the policy temporarily:** `"STACK_POLICY": "off"` in `settings.json` → `env`.
- **Restore:**
  1. Copy files back from `~/.claude/backup-*/` (the stack's old `CLAUDE.md`, if it was retired, is
     in `retired/`).
  2. Remove the `# claude-agent-stack` line from your shell rc.
  3. `claude mcp remove -s user exa` (and jina, wolfram, huggingface, wandb) if you no longer want
     them.
