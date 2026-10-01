# Claude Code multi-agent stack

<!-- markdownlint-disable MD013 MD060 -->

BlackCat, a dispatcher on the main thread, routes work to 36 specialist agents (37 agent files). 93
skills load on demand. One policy hook, deny rules and the Claude Code sandbox hold the limits, and MCP
servers start and stop with the agents that use them. Built for Claude Code **2.1.271 or later**,
macOS only (Apple Silicon first). It runs in the terminal and in the apps that run Claude Code with
your settings: Claude Desktop's Code tab, Conductor, VS Code, Zed, Nimbalyst (see [Apps](#apps)).
Every applied parameter (model, effort, `maxTurns`, caps, knobs) and its reason is in
[CONFIG.md](CONFIG.md).

## Quick start

> [!WARNING]
> **First install over an existing `~/.claude`: run `./install.sh --dry-run` first.** The default
> run prunes. Every agent and skill under `~/.claude/agents/` and `~/.claude/skills/` that is not
> the stack's current version (your own, renamed, edited or unknown-named ones) is moved into a
> backup and replaced by the stack's. The dry run prints every change and makes none. Keep your own
> files with `--no-prune`, or restore them with `--restore` (see [Backups and restore](#backups-and-restore)).

```bash
git clone <repository-url> claude-agent-stack && cd claude-agent-stack
./install.sh --dry-run            # the plan: added / replaced / removed, each with a reason
./install.sh                      # core install; one backup of everything it changes or removes
$EDITOR ~/.claude/stack.env       # keys; read at connect time, no reinstall needed
claude                            # starts as BlackCat (the blackcat agent)
```

Optional parts: `--with-ml` (shared ML venv, several GB), `--with-lsp` (language servers for the
code-intelligence plugins), `--with-adobe` (After Effects MCP, Premiere connector),
`--with-extra-plugins` (Anthropic's skill-creator and math-olympiad plugins). Inside Claude Code:
`/stack-doctor` (health check), `/mcp` (server status), `/context`.

Run the installer while no Claude Code session is running (Desktop and Conductor included): a
running session keeps the agent files it started with while the hook and settings change at once.
Start new sessions afterwards.

## The installer

`install.sh` stages the stack's part of the config dir, validates it, backs up what it will change,
then applies. `CLAUDE_CONFIG_DIR` changes the target (default `~/.claude`).

### What a run does

1. **Main-branch rule** (see [Installs only from `main`](#installs-only-from-main)).
2. **What changed since the last install.** The manifest records the commit each install shipped.
   The run prints the diffstat of everything it ships since then (all of `dot-claude/`: agents with
   their MCP servers and hooks, skills, rules, hooks, settings, `bin/`, `mcp/`, magg's catalog, the
   LSP marketplace; plus `install.sh`, `lib/`, `requirements/`, `stack.env.example`) and any
   uncommitted edits there, capped at 40 lines with the `git diff` command to read it all. An unknown
   recorded commit gets a warning. When that list isn't empty, the run asks before anything changes
   (the venvs sync from `requirements/` in the next step):
   `The stack changed since the last install (listed above). Install it? (see the whole plan first:
   ./install.sh --dry-run) [y/N]`. Anything but `y`/`yes` stops with exit 1 and nothing changed. It
   asks on stdin/stderr when both are a terminal, otherwise on the controlling terminal (`/dev/tty`),
   so `./install.sh 2>&1 | tee install.log` still asks there. With no terminal at all (CI, cron,
   `</dev/null` without a terminal), a changed stack stops with exit 1 and "rerun with --yes"; nothing
   changed. `--yes` skips the question; `--dry-run` never asks.
3. **Stage.** The stack's part of the config dir (`agents/`, `skills/` without the claude.ai-synced
   ones, `rules/`, `hooks/`, `bin/`, `mcp/` without `vendor/`, `stack-plugins/`, `magg/config.json`,
   `settings.json`, `stack.env`, `.stack-manifest.json`, `CLAUDE.md`, temp leftovers) is copied to a
   staging dir inside the private backup root (so the staged `stack.env` is as private as the
   backups; a symlinked backup root is refused). Nothing in the config dir changes until the staged
   result is validated. A manifest key that isn't a file path in the stack's scope (`..`, an absolute
   path, a whole dir such as `bin`) stops the install here.
4. **Render, merge, prune** in the staging dir, then **validate**: JSON, agent and skill
   frontmatter, leftover placeholders, and the staged `agent_guard.py --self-test`. Validation is
   fatal only for files the stack owns.
5. **Plan.** `changes: N added, N updated, N removed`, then `replaced:` (stack files that differed;
   the backup keeps yours) and `removed: not part of the stack` (every removed hook entry named),
   each line with its reason, then `note:` lines.
6. **Apply.** `--dry-run` stops before this and prints MCP, plugin and rc changes as `would: …`. A
   real run saves every file it changes or removes into one backup, records the files it adds, then
   applies. Nothing is applied if the config dir changed during the run (Claude Code saving
   `settings.json`, an editor). A run that changes nothing makes no backup.

`lib/install_state.py` (system `python3`, stdlib only) does the staging, plan, backup, apply,
restore and validation.

### Pruning and the manifest

Pruning is the default. The installed `agents/` and `skills/` hold exactly the stack's files, and
stack config the stack no longer ships goes.

| What | Default | `--no-prune` |
|---|---|---|
| `agents/`, `skills/` (stack-owned) | files of other origins, unknown names, renamed agents (`senior-coder` → `main-coder`, `router` → `blackcat`), stale renders and leftover `.new` files removed; edited stack files replaced | kept and named in `note:` lines; an edited stack file keeps your version and gets `<file>.new` (`--force` replaces it) |
| `hooks/`, `bin/`, `mcp/`, `rules/` | stack files it no longer ships (manifest or a legacy list) removed; your own files stay | kept |
| magg catalog | edited stack entries replaced, entries it no longer ships removed; your servers stay | kept |
| MCP (user scope) | entries it registered and no longer ships, and Context7 (replaced by libdocs), removed through `claude mcp remove` and recorded in the backup | kept |
| `settings.json` | duplicate hooks and permission rules, old guard hooks (any path) and hooks on events it no longer wires removed; sandbox merged | the same |
| temp leftovers, `.new` files back in sync | removed | removed |

The manifest (`~/.claude/.stack-manifest.json`) lists every stack file as relative path + sha256,
and every setting and env key the stack wrote. It decides what is stale: a file whose hash differs
from the manifest was edited; a file the manifest doesn't list isn't the stack's. On a first run
with no manifest, a same-named file that differs from the stack's counts as stale: it is backed up
and replaced.

Never touched: credentials, `~/.claude.json` (MCP changes go through `claude mcp` only), the
claude.ai-synced skills, plugins' own files, projects and sessions. `~/.claude/CLAUDE.md` is yours;
the stack's rules live in `~/.claude/rules/claude-agent-stack.md`. (A `CLAUDE.md` that holds nothing
but an old stack version's rules is retired once, into the backup.)

### Backups and restore

- **Location:** `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/<timestamp>-<random>/`,
  outside the config dir. The folder is 0700, files 0600. `backup.json` records the entries, the
  added files, removed or replaced MCP entries, disabled plugins and rc copies.
- The backups sit beside the guard's state dir (`~/.local/state/claude-agent-stack/`), not in it:
  the guard deletes state folders idle for three days.
- Agents can't reach them: `Read`/`Edit` deny rules, sandbox `denyRead`/`denyWrite` and a
  built-in protected path of the guard.
- Backups earlier versions kept inside the config dir (`~/.claude/backup-*`, with copies of
  `stack.env`) move to `<backups>/legacy/` on every run.
- More than ten backups of one config dir: the run says so. It never deletes one.

Restore:

```bash
./install.sh --restore --dry-run                 # print what a restore would do
./install.sh --restore                           # undo the latest install
./install.sh --restore <backup-dir>              # undo a given one (also --restore=<backup-dir>)
```

A restore runs as a staged plan too. It backs up the current state first and prints
`undo this restore: ./install.sh --restore <dir>`. It puts back files, `~/.zshrc`/`~/.bashrc`, MCP
entries (re-added with `claude mcp add-json`) and plugins the install disabled. A `backup.json` that
names paths outside the config scope is refused, and `<backup-dir>` must sit in the backup root. A
saved symlink that points outside the config dir is put back only with `--force`. Without it, what is
at that path now stays (the stack's version and the files the install added below it included), so
a skill never goes missing; the message names the link and the `ln -s` that recreates it.

### Flags

As `./install.sh --help` prints them. Flags combine.

| Flag | Effect |
|---|---|
| *(none)* | core install: prune, back up, apply |
| `--dry-run` | print every change (files, removals, MCP, plugins, rc) and make none; exits 1 where the real run would stop (a symlinked dir without `--write-through-links`) |
| `--no-prune` | keep what isn't part of the stack and your edits to stack files (default: backed up, then removed or replaced) |
| `--force` | with `--no-prune`: still replace stack files you edited; with `--restore`: also put back saved symlinks that point outside the config dir. It does not write through symlinked dirs |
| `--write-through-links` | the only way past a symlinked `agents/`, `skills/`, … dir (a dotfiles checkout): writes the stack's files through the link; nothing there is ever removed (see [Symlinked config dirs](#symlinked-config-dirs)) |
| `--restore [DIR]` | put the config dir back as it was before an install (`DIR`: a backup; default: the latest), then exit |
| `--yes`, `-y` | install without asking when the stack's files changed since the last install; needed when there is no terminal (CI), where the run otherwise stops |
| `--print-managed-settings` | print an optional `managed-settings.json` that pins the stack's hook entries and deny rules against edits (the entries, not the guard's code: pinning the code needs the optional root-owned copy; see [Security model](#security-model)) |
| `--mcp-plan` | print the MCP server add/migrate/replace/keep plan and make no changes |
| `--with-ml` | also create the ML venv (`~/.claude/venvs/ml`; several GB) |
| `--with-lsp` | also install missing language servers before enabling the code-intelligence plugins |
| `--with-adobe` | also build the After Effects MCP and install the Premiere connector (macOS) |
| `--with-extra-plugins` | also install Anthropic's skill-creator and math-olympiad plugins |
| `--no-mcp` | skip registering user-scope MCP servers |
| `--no-plugins` | skip plugins (document skills, code-intelligence/LSP plugins) |
| `--keep-plugin-duplicates` | keep the document-skills and skill-creator plugins enabled where claude.ai syncs the same skills (default: disabled, one copy); also keeps mcp-server-dev |
| `--replace-mcp` | re-register exa/jina/wolfram/huggingface/wandb even if you configured them |
| `--no-deps` | skip brew/uv/node/magg/huetension/venv installs and MCP dependency prefetch (missing tools become warnings) |
| `--no-profile` | leave your shell rc files alone |
| `-h`, `--help` | print the usage header |

`--dedupe-plugins` is still accepted (it is the default now). Environment: `CLAUDE_CONFIG_DIR`
(install target), `STACK_CLAUDE_JSON` (which JSON file the MCP plan reads), `XDG_STATE_HOME`
(default `~/.local/state`; the guard state `claude-agent-stack/`, the backups
`claude-agent-stack-backups/` and the MCP servers' caches `claude-agent-stack-cache/` all sit under
it, and the sandbox deny rules are rendered from it at install time, so changing it later needs a
reinstall), `STACK_PYTHON` (the absolute interpreter for hooks and the status line; chosen
automatically, never a pyenv/asdf shim).

### Symlinked config dirs

A top-level scope dir that is a symlink (`agents/`, `skills/`, `hooks/`, … pointing into a dotfiles
checkout) is yours:

- Nothing under it is ever removed.
- The run stops unless you pass `--write-through-links`, which writes the stack's files through the
  link. `--force` doesn't lift the stop. `--no-prune --write-through-links` keeps your edits to stack
  files there (a `.new` render goes next to each).
- A link inside it stays, whether a dir link (`skills/<name>` → elsewhere: the stack's files for that
  name are skipped) or a file link (`agents/coder.md` → elsewhere). Each is named in the notes
  ("kept (a link inside your symlinked agents/)"); the link's target is never written.
- `--dry-run` without `--write-through-links` shows the whole plan, then prints the real run's
  refusal ("the real run would stop: …") and exits 1, as the real run does; with the flag it exits 0.

A per-skill symlink in a real `skills/` dir is different: it is replaced by the stack's skill, the
backup keeps the link, and its target is never written.

### Settings, keys and shell profile

`settings.json` is merged, never replaced.

- The stack owns `autoCompactEnabled`, `autoCompactWindow` (400K), the guard hooks, the spawn depth,
  the caps and budgets (marked ● in [Knobs](#knobs)), the MCP discovery cache, the no-push deny
  rules, the protected-path deny rules, `worktree.baseRef: "head"` and the `sandbox` block (the
  stack's scalars win, lists are unioned).
- `permissions.defaultMode: "bypassPermissions"`: sessions start without permission prompts. Deny
  rules, `ask` rules, the guard hooks and the sandbox still apply.
- `"agent": "blackcat"`, `statusLine` and `skillListingBudgetFraction` are set while you have none
  of your own. Your other hooks, permission rules and keys stay.
- Two models only: every agent pins `claude-opus-5-5` or `claude-sonnet-5-5`, and
  `ANTHROPIC_DEFAULT_HAIKU_MODEL` (Claude Code's small-model slot: session titles, WebFetch
  summaries) is `claude-sonnet-5-5`. An app that routes models itself
  (`CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`) ignores that key: see step 3 of
  [Claude Desktop, step by step](#claude-desktop-step-by-step).
- Removed from `env`: `DISABLE_AUTO_COMPACT`, `DISABLE_COMPACT`, `CLAUDE_CODE_AUTO_COMPACT_WINDOW`
  (they defeat auto-compaction), `CLAUDE_CODE_SUBAGENT_MODEL[_FORCE]`, `CLAUDE_CODE_EFFORT_LEVEL`,
  stale `[1m]` model pins, `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT`.
- Keys and values the stack stopped shipping are retracted while they still hold the stack's value.

`stack.env` (0600) keeps every value you wrote; variables new in `stack.env.example` are appended
commented out (the three image models set to their defaults). MCP registration never writes a key
into `~/.claude.json`: a plaintext key in an old entry is copied into `stack.env` first, then the
entry switches to the `bin/mcp-headers` header helper. An entry with a `headersHelper` of your own is
left alone.

The **shell profile line** (`~/.zshrc`, and `~/.bashrc` if present) exports only the non-empty keys
named by `STACK_EXPORT` (default `HF_TOKEN WANDB_API_KEY MLFLOW_TRACKING_URI JUPYTER_URL
JUPYTER_TOKEN`) and appends `~/.local/bin` to `PATH`. **`GITHUB_TOKEN` is no longer exported:** a
forge token in every shell reaches every agent's subprocesses. libdocs reads it from `stack.env`
itself; add it to `STACK_EXPORT` only if you want `gh` to use it.

### Installs only from `main`

The installer runs from the `main` branch of this repository's git checkout (no flag turns this
off). Started from another branch or worktree, it fast-forwards local `main` to that commit
(`git merge --ff-only`, in the worktree where `main` is checked out; with none, the checkout switches
to `main`) and re-runs itself from there. It stops before installing anything, with the fix, when
the fast-forward is blocked: uncommitted or untracked files, uncommitted changes in the `main`
checkout, or diverged history. It never pushes, and runs these git calls with hooks off. `--dry-run`
and `--mcp-plan` change nothing, so off `main` they refuse instead of merging.

### Upgrading

Re-running is idempotent: a second run over an installed stack prints `no changes` and makes no
backup. To roll back a revision, use `./install.sh --restore` (the last install), or `git revert`
its commits on `main` and re-run `./install.sh`: the manifest retracts the settings the newer
version wrote.

### Testing in a scratch HOME

For maintainers. `tests/install_smoke.sh` does all of this hermetically (fake `claude`, scratch
config dir, scratch MCP config, scratch `XDG_STATE_HOME`; it fingerprints the real `~/.claude`,
`~/.claude.json`, `~/.zshrc` and backup root before and after). By hand:

```bash
T="$(mktemp -d)"
export CLAUDE_CONFIG_DIR="$T/claude" XDG_STATE_HOME="$T/state" STACK_CLAUDE_JSON="$T/claude.json"
export PATH="$PWD/tests/fake-claude:$PATH"          # a fake claude: no real MCP or plugin changes
./install.sh --no-deps --no-profile --dry-run       # plan only
./install.sh --no-deps --no-profile                 # first run: "N added", one backup in $T/state
./install.sh --no-deps --no-profile                 # second run: "no changes", no backup
./install.sh --restore --dry-run                    # the restore plan
```

Run it from the `main` checkout (the main-branch rule applies). Without the fake `claude`, add
`--no-mcp --no-plugins`. On a terminal a run may ask before applying (the supply-diff question);
answer `y` or add `--yes`. From an agent's Bash the guard allows a scratch install only when `HOME`
and `CLAUDE_CONFIG_DIR` both point into a temp dir, so an agent also sets `HOME="$T/home"`.

## What goes where

| Path | What |
|---|---|
| `~/.claude/rules/claude-agent-stack.md` | Global rules every agent loads. `~/.claude/CLAUDE.md` stays yours |
| `~/.claude/settings.json` | `"agent": "blackcat"`, auto-compact at 400K, depth 4, caps, permissions, sandbox, hooks, status line (merged) |
| `~/.claude/agents/*.md` | 37 agent definitions, plus `researcher-copy.md` and `coder-copy.md` rendered from their base files |
| `~/.claude/skills/*/SKILL.md` | 93 skills (descriptions in context; bodies load on demand) |
| `~/.claude/hooks/agent_guard.py` | The policy hook (see [Enforced behaviours](#enforced-behaviours-hooks)) |
| `~/.claude/bin/mcp-headers` | `headersHelper`: gives exa/jina/huggingface/wandb their keys from `stack.env` at connect time |
| `~/.claude/bin/with-stack-env` | Starts spider/magg with only their own keys (`--only`); `--print-env sh` for the profile (values redacted unless `--reveal`, which agents can't pass) |
| `~/.claude/bin/claude-ultracode`, `~/.local/bin/claude-ninja`, `~/.local/bin/claude-god` | ninja-coder or god-coder as the main thread at ultracode, launched with forge tokens unset |
| `~/.claude/bin/magg-private` | Runs mcp-broker's magg on a private copy of the catalog |
| `~/.claude/bin/statusline.py`, `~/.claude/bin/doctor.sh` | Status line; health check behind `/stack-doctor` |
| `~/.claude/mcp/{libdocs,image_studio,neural_memory}_mcp.py` | The stack's own MCP servers (`uv run --script`) |
| `~/.claude/neural-memory/` | The agents' shared long-term memory (brain `claude-agent-stack`) |
| `~/.claude/magg/config.json` | On-demand MCP catalog (all disabled until mcp-broker mounts one) |
| `~/.claude/stack.env` | Keys (0600) |
| `~/.claude/venvs/sci`, `~/.claude/venvs/ml` | Science venv (always); ML venv (`--with-ml`); both hash-locked |
| `~/.claude/.stack-manifest.json` | What the installer last wrote (path + sha256, settings keys, MCP entries, deduped plugins) |
| `~/.claude.json` (or `$CLAUDE_CONFIG_DIR/.claude.json`) | User-scope MCP servers, written only through `claude mcp` |
| `~/.local/state/claude-agent-stack/<session>/` | Hook state: registry, leases, locks, markers. Pruned after 3 idle days |
| `~/.local/state/claude-agent-stack-backups/` | Installer backups (0700; agents can't read them); the run's work dir lives inside |
| `~/.local/state/claude-agent-stack-cache/` | `STACK_CACHE`: the stack's MCP servers' uv/npm caches (sandbox can't write) |
| `~/.cache/claude-sandbox/` | Sandboxed Bash's own caches (see [Sandbox and caches](#sandbox-and-caches)); safe to delete |

## No duplicates

One source per skill, agent, hook registration, MCP entry and rule. Duplicates race: two skills with
overlapping descriptions compete for the same trigger, and which one loads is up to the model on
each call; two registrations of one hook both fire (twice the latency, and two guards can disagree);
two MCP entries for one service split tool names and allowlists. So the stack's copy wins and the
others go:

- **Installer:** prunes stale and duplicate agents, skills, hooks, permission rules and MCP entries
  (see [Pruning](#pruning-and-the-manifest)).
- **Plugins disabled by default** (`--keep-plugin-duplicates` keeps them):
  - `document-skills` (docx/xlsx/pptx/pdf) and `skill-creator`, where claude.ai already syncs the same
    skills as `anthropic-skills:*` (those can't be removed). Synced skills load only in sessions
    signed in to claude.ai: if you also use API-key, gateway or Bedrock/Vertex sessions, keep the
    duplicates. A disabled plugin is re-enabled once its synced copy is gone.
  - `mcp-server-dev@claude-plugins-official`: the stack's `mcp-server-craft` absorbed its three
    skills (MCPB bundles, MCP Apps UI).
  - Each disable prints `To undo: claude plugin enable <plugin> --scope user` and is recorded for
    `--restore`.
- **Kept by decision:** the `math-olympiad` plugin (a solve-and-adversarially-verify workflow that
  `proof-craft` doesn't replicate; `proof-craft` sends competition problems to it) and the built-in
  `dataviz` skill (no `skillOverrides`). The overlap is handled by descriptions:
  `data-visualization` covers figures in code (matplotlib, seaborn, plotly, Altair), `dataviz`
  Artifact and HTML charts. Residual: `dataviz`'s and `math-olympiad`'s own descriptions still claim
  some of the same phrases.
- **Other overlaps** with skills that can't be removed (claude.ai-synced or built-in) are split by
  scope and written into both descriptions: `browser-automation` / `chrome-browser`,
  `computer-use-apps` / `computer-use`, `web-research` / `deep-research`, `claude-code-extensions` /
  `update-config`, `workflow-authoring`, `skill-creator`, `presentation-design` / `pptx`,
  `diagrams-as-code` / `artifact-diagramming`.
- **Enforced by** `tests/test_no_duplicates.py`: static checks that the repo never ships the same
  skill, agent, hook registration, MCP entry, rule or plugin skill from two sources, and that no stack
  skill shares a name with a plugin, synced or bundled skill.

## Agents

Two pinned models: `claude-opus-5-5` where judgment is the product, `claude-sonnet-5-5` for bounded
execution, lookups and tool loops. `tests/lint_agents.py` rejects any other value, and the hook strips
a per-call `model`. An agent file's `effort` counts only when the agent runs as a subagent; the main
thread runs at the session's level (`/effort medium` for BlackCat). `maxTurns` is a runaway bound
per task type (12 for oracle up to 350 for god-coder; [CONFIG.md](CONFIG.md) §3).

| Agent | Model · effort | Does | Hands off to |
|---|---|---|---|
| **blackcat** (main thread) | Sonnet 5.5 · session (medium) | Routes each prompt to one or several specialists (one parallel burst) or to the orchestrator; relays results; asks the user | orchestrator for dependent multi-specialist work; never god-coder |
| orchestrator | Opus 5.5 · high | Decomposes multi-specialist or dependent work (≤ 10 tasks), dispatches, verifies, integrates | the only spawner of god-coder, once per session |
| planner | Opus 5.5 · xhigh | Options, the chosen approach as steps with owners, risks, checks; read-only | plan-reviewer critiques; orchestrator runs |
| plan-reviewer | Opus 5.5 · high | Critiques a plan against goal, code and docs; read-only (hook) | planner writes plans |
| oracle | Opus 5.5 · low | Timeless knowledge, no web | scout for anything that changes |
| scout | Sonnet 5.5 · low | One current fact, cited | researcher for synthesis |
| explore | Sonnet 5.5 · low | Read-only codebase search with `path:line` evidence; replaces Claude Code's built-in Explore (no Bash, 40 turns) | coder / main-coder to change code |
| researcher | Opus 5.5 · high | Cited multi-source research; crawls; copies itself | scout (one fact); `NEXT: browser-operator` for pages to act on |
| mathematician | Opus 5.5 · xhigh | Proofs, derivations, symbolic/numeric computation | data-scientist (real data), quantum-engineer (simulation code) |
| quantum-engineer | Opus 5.5 · high | Circuits, quantum simulation, QEC, IBM Quantum runs | mathematician (derivations) |
| writer | Opus 5.5 · medium | Articles, docs, emails, translations (PT-PT/EN) | researcher (research), doc-specialist (Office/PDF) |
| doc-specialist | Sonnet 5.5 · medium | Reads and builds docx/xlsx/pptx/pdf | writer (the prose) |
| image-director | Opus 5.5 · medium | Image generation and edits through image-studio | designer (brand, layout, print) |
| designer | Opus 5.5 · high | Brand, layout, print, UI visuals; Illustrator; image-studio | image-director (series), frontend-engineer (UI code), cg-artist (3D) |
| motion-designer | Opus 5.5 · medium | After Effects, Premiere, motion | designer / image-director (stills), cg-artist (3D) |
| cg-artist | Opus 5.5 · medium | Blender, ZBrush, Substance, Houdini, 3D printing | designer / image-director (2D) |
| coder | Sonnet 5.5 · medium | Small and medium code; offloaded sub-tasks; copies itself | main-coder |
| main-coder | Opus 5.5 · xhigh | Large codebases, architecture, hard bugs, merges that won't fast-forward | coder (routine), ninja-coder (mathematical cores, or after two failures) |
| ninja-coder | Opus 5.5 · max | Novel algorithms, proofs, numerics, kernels | `NEXT: god-coder` with a dossier, for the orchestrator |
| god-coder | Opus 5.5 · max | Last resort | — (orchestrator only, once per session, after ninja-coder; or `claude-god`) |
| frontend-engineer | Opus 5.5 · medium | Web front end, a11y, verified headless | designer (visuals), main-coder (backend) |
| devops-engineer | Sonnet 5.5 · high | CI/CD, containers, IaC, deploys (dry-run first) | main-coder (architecture), security-auditor |
| data-engineer | Sonnet 5.5 · high | SQL, MongoDB, pipelines, dataframes | data-scientist (inference) |
| data-scientist | Opus 5.5 · high | Tests, A/B and power, regression, causal, forecasting, Bayesian | data-engineer (pipelines), ml-engineer (predictive models) |
| ml-engineer | Opus 5.5 · high | Tabular, time-series, classic NLP; MLOps | dl-engineer (deep nets), llm-engineer (LLMs) |
| dl-engineer | Opus 5.5 · high | Architectures, training loops, image-generation models | llm-engineer; mlx-/cuda-engineer (platform) |
| llm-engineer | Opus 5.5 · high | Local inference, quantization, fine-tuning, evals, RAG, agents | mlx-/cuda-engineer (kernels, platform) |
| mlx-engineer | Opus 5.5 · high | Apple Silicon performance, Metal kernels, MLX ports | dl-/llm-engineer (model decisions) |
| cuda-engineer | Opus 5.5 · high | CUDA/Triton, NCCL, vLLM, remote Linux hosts, Kaggle | dl-/llm-engineer (model decisions) |
| robotics-engineer | Opus 5.5 · high | ROS 2, control, SLAM, simulation, robot learning | dl-engineer (generic training) |
| code-reviewer | Opus 5.5 · high | Reviews diffs and codebases; read-only (hook) | security-auditor, verifier |
| verifier | Sonnet 5.5 · high | Runs tests, reproduces, re-checks; never fixes; read-only (hook) | code-reviewer, security-auditor |
| security-auditor | Opus 5.5 · xhigh | Threat model, exploitable issues; read-only (hook) | code-reviewer (general quality) |
| browser-operator | Sonnet 5.5 · medium | Acts on web pages: your Chrome or headless Playwright | spawned only by blackcat and orchestrator; never writes on a forge |
| mcp-broker | Sonnet 5.5 · medium | Mounts, runs and unmounts MCP servers through magg | permanent changes only after `NEXT: ASK USER` |
| claude-code-engineer | Opus 5.5 · high | Builds Claude Code config (in the repo, never installed copies) | claude-code-guide (questions only) |
| claude-code-guide | Sonnet 5.5 · low | Answers Claude Code / SDK / API questions; read-only (hook) | claude-code-engineer (changes) |

Descriptions name who takes the adjacent work, so the Agent tool listing every spawner sees states the
boundaries. Details of each agent's MCP servers are in [MCP servers](#mcp-servers).

### Routing and escalation

- **BlackCat** classifies and dispatches; it never does the work. Read, Grep and Glob are for quick
  checks only. It asks clarifying questions (AskUserQuestion) and ends every turn with a visible
  message.
- **Code:** coder → main-coder → ninja-coder → god-coder. ninja-coder takes a problem whose core is
  algorithmic or mathematical, or one main-coder failed twice. god-coder takes only what ninja-coder
  could not solve, and only through the orchestrator: any other agent returns `STATUS: partial` with
  `NEXT: god-coder` and a dossier, and the orchestrator spends the session's one god-coder spawn
  (follow-ups resume that god-coder with SendMessage).
- **god-coder in a plan, ninja-coder first:**
  1. planner may add at most one god-coder step, and only as the conditional fallback of a
     preceding ninja-coder step on the same problem ("if ninja-coder fails or returns partial, then
     god-coder with the dossier"), with a dossier template.
  2. plan-reviewer blocks a god-coder step that has no preceding ninja-coder step on the same
     problem, is unconditional, appears more than once, or has an incomplete dossier.
  3. BlackCat never dispatches god-coder: a plan or task with a god-coder step goes to the
     orchestrator, with the plan attached by path.
  4. The orchestrator runs the ninja-coder step first. It spawns god-coder only when ninja-coder
     reports failure or partial, with the dossier completed from ninja-coder's report; if ninja-coder
     succeeds, it drops the god-coder step and reports it as not needed. With the session's spawn
     already used, it returns `STATUS: partial`, `NEXT: god-coder for step <id>`.
  5. The hook allows god-coder only from the orchestrator, once per session, and (`GOD_AFTER_NINJA`,
     default 1) only after a ninja-coder of this session has finished. The hook checks that
     ninja-coder ran and stopped (spawned by any agent: a main-coder escalation counts); that it
     failed is enforced by the prompts, not the hook.
- **Ultracode:** `claude-god` (or `claude-ninja`) starts the agent as your main thread at ultracode;
  dispatched by another agent, both run at `max`.
- **Models and platforms:** model work goes to ml-/dl-/llm-engineer, platform performance to
  mlx-/cuda-engineer (the target hardware owns ports).
- **Checks:** reviewers and the verifier never check their own work; an author never verifies itself.
- **Missing permission or capability:** return `STATUS: partial` with `NEXT: <agent>`; a decision only
  the user can make returns `STATUS: blocked`, `NEXT: ASK USER: …` (see [Security model](#security-model)).

### Spawn policy

Claude Code ignores `Agent(a, b)` lists inside subagents, so `POLICY` in `agent_guard.py` is the
single source of truth, and `tests/lint_agents.py` checks that every agent's "May spawn:" sentence
matches it. Depth: BlackCat → L1 → L2 → L3 → L4 (`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4`); L4 cannot
spawn. Spawning is an allowlist: a missing `subagent_type`, Claude Code's generic and built-in
types (`general-purpose`, `claude`, `fork`, `Plan`, `statusline-setup`), host-defined types such as
`SubAgent`, and any type not in the caller's row are denied, for every caller: one with no row of its
own gets BlackCat's row on a main thread and nothing as a subagent. The tool's aliases (`Task`,
`SubAgent`) are matched too. A generic agent that starts anyway, outside the Agent tool (a skill
with `context: fork` and no `agent:`, a workflow stage without `agentType`), has every tool call
refused. Workflow scripts must give every `agent()` call a stack `agentType`; bundled workflows
such as `/deep-research` are refused. settings.json adds `Agent(general-purpose|claude|fork)` deny
rules and switches off the built-in Explore and Plan (`CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS`; the
stack's `explore` replaces Explore) and, in `claude -p` and Agent SDK apps, every built-in
(`CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS`). SendMessage resumes of finished agents follow the same
rows. Agents of your own are in no row: run one with `claude --agent <name>`.

- **blackcat:** every specialist except god-coder, in one burst per prompt.
- **orchestrator:** every specialist; the only spawner of god-coder, once per session
  and after a finished ninja-coder (`GOD_SPAWNERS=orchestrator`, `GOD_ONCE_PER_SESSION=1`,
  `GOD_AFTER_NINJA=1`).
- **browser-operator** (your logged-in Chrome sessions): only blackcat and orchestrator, neither of
  which reads the web itself. Web-reading agents (researcher, ml-/dl-/llm-/cuda-engineer) return
  `NEXT: browser-operator` with URLs and steps.
- **Copies:** only researcher and coder, as `researcher-copy` and `coder-copy`; a copy spawns no copies.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker,
  claude-code-guide, browser-operator, plan-reviewer, image-director, explore.

| Agent | May spawn |
|---|---|
| planner | scout, explore, claude-code-guide |
| researcher | researcher-copy, scout, doc-specialist, mathematician, data-engineer, data-scientist, mcp-broker |
| researcher-copy | scout, doc-specialist, mathematician, data-engineer, data-scientist, mcp-broker |
| writer | scout, researcher, mathematician |
| mathematician | scout, mcp-broker, quantum-engineer |
| doc-specialist | scout, mcp-broker |
| designer | image-director, scout, mcp-broker, cg-artist |
| motion-designer | image-director, designer, scout, mcp-broker, cg-artist |
| coder | coder-copy, explore, scout |
| coder-copy | explore, scout |
| main-coder | coder, explore, scout, verifier, code-reviewer, security-auditor, plan-reviewer, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, claude-code-guide, ninja-coder |
| ninja-coder | main-coder, coder, mathematician, explore, scout, verifier, code-reviewer, security-auditor, researcher, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, quantum-engineer |
| god-coder | coder, main-coder, ninja-coder, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, explore, scout, verifier, code-reviewer, security-auditor, mathematician, researcher |
| mlx-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder |
| cuda-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder |
| devops-engineer | coder, explore, scout, verifier, security-auditor, mcp-broker |
| data-engineer | coder, explore, scout, verifier, mathematician, data-scientist, doc-specialist, mcp-broker |
| frontend-engineer | coder, explore, scout, verifier, code-reviewer, designer, image-director, mcp-broker |
| data-scientist | data-engineer, ml-engineer, mathematician, coder, explore, scout, verifier, doc-specialist, writer, mcp-broker |
| ml-engineer | data-scientist, data-engineer, coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker |
| dl-engineer | mlx-engineer, cuda-engineer, data-engineer, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder |
| llm-engineer | mlx-engineer, cuda-engineer, dl-engineer, data-scientist, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, claude-code-guide, ninja-coder |
| claude-code-engineer | claude-code-guide, scout, explore, verifier, code-reviewer, mcp-broker |
| quantum-engineer | mathematician, coder, explore, scout, researcher, verifier, code-reviewer, cuda-engineer, mlx-engineer, mcp-broker, ninja-coder |
| robotics-engineer | coder, explore, scout, researcher, verifier, code-reviewer, mathematician, dl-engineer, cuda-engineer, mlx-engineer, cg-artist, mcp-broker, ninja-coder |
| cg-artist | image-director, coder, scout, verifier, mcp-broker |

**Caps** (values in [Knobs](#knobs)): 3 running children per agent, raised per type (orchestrator 10,
god-coder and main-coder 6, ninja-coder 5, researcher 4, planner and plan-reviewer 8); 2 live copies
per copy type; BlackCat 8 dispatches within 120 s and 12 tool calls per prompt; 32 subagents running
in a session; context-token budgets per prompt and per session; 64 MCP calls per subagent run. Every
BlackCat child runs in the background (the hook drops its `run_in_background: false`).

## Skills

Any agent can load any skill. Every agent has the Skill tool and sees each skill's one-line
description; a skill's body enters the agent's context only when its task matches and it loads it.
Nothing is preloaded (no `skills:` frontmatter). Agent prompts carry a short `## Skills` line naming
the skills most relevant to them ("Load `cpp-engineering` for C or C++ cores") — pointers, not
preloads; every name is lint-checked. One `Skill` allow rule pre-approves every skill, including ones
you or a plugin add later. If you open repositories you don't trust, replace it with `Skill(<name>)`
rules, since it also approves a repository's own `.claude/skills`.

**Listing budget.** Claude Code caps the listing at `skillListingBudgetFraction` of the context
window; the stack sets **0.012** (default 0.01), about 36K characters on the 1M-context models every
agent uses. The stack's own descriptions take about 17.7K characters. Over the cap, the least-used
skills show by name only. To leave room for plugin, bundled and claude.ai skills, the stack also cuts
each description at 500 characters (`skillListingMaxDescChars`) and lists six user-run commands
(`code-review`, `security-review`, `simplify`, `fewer-permission-prompts`, `keybindings-help`, `init`)
only in the `/` menu (`skillOverrides`). `/stack-doctor` reports the size; `tests/lint_agents.py`
fails if the stack's skills pass half the budget. A session with a 200K window gets a fifth of the
space; raise the fraction in your own settings there if that matters.

A skill's description starts with its trigger ("Load before …", "Use when …") and names no agent.

| Group | Skills (**new** = added in this revision) |
|---|---|
| Engineering practice | code-standards, review-protocol, secure-coding, git-workflows, python-engineering, rust-engineering, typescript-engineering, jvm-engineering, julia-engineering, haskell-engineering, **cpp-engineering**, **shell-scripting**, cmake-ninja-builds, ide-workflows, algorithm-design, formal-methods |
| Performance | accelerator-perf, cpu-performance, gpu-kernel-dev |
| Web front end | **frontend-frameworks**, **web-accessibility** |
| Apps and distribution | rust-native-gui, editor-engineering, macos-app-distribution |
| Systems, infrastructure, tooling | linux-workstation, self-hosting-ops, **container-images**, **ci-cd-pipelines**, **terraform-opentofu**, mcp-server-craft, postgresql, mongodb, claude-code-extensions, browser-automation, computer-use-apps, stack-doctor (`/stack-doctor`, typed by you) |
| Mathematics | proof-craft, lean-formalization, category-theory, numerical-methods, quantum-computing, quantum-physics-numerics |
| ML and models | ml-experiment, **tabular-ml**, **time-series-forecasting**, training-debug, **distributed-training**, **model-export**, diffusion-flow-models, image-model-pipelines, robotics-engineering, robot-learning, llm-finetuning, llm-quantization, llm-evals, local-llm-serving, hf-hub, dataset-curation |
| Data and statistics | data-analysis, **dataframes-duckdb**, **bayesian-modeling**, **causal-inference**, data-visualization |
| LLM applications and agents | rag-agents, graph-rag, agent-harness-design, prompt-and-brief-design |
| Research and writing | web-research, literature-review, technical-writing, portuguese-pt-writing, latex-typesetting, markdown-publishing, book-production, diagrams-as-code |
| Design, image and print | brand-identity, typography, color-management, **ui-design-systems**, presentation-design, image-prompting, svg-vector-craft, print-production, apparel-merch-print, tattoo-design, raster-imaging, adobe-creative-cloud |
| 3D | blender-3d, sculpting-texturing, houdini-fx, 3d-printing |
| Video and motion | media-ffmpeg, motion-graphics |

### New in this revision

| Skill | Load it when |
|---|---|
| bayesian-modeling | building or checking a Bayesian model: PyMC 6, NumPyro, Stan, R-hat/ESS/divergences, LOO, ArviZ |
| causal-inference | estimating a causal effect from observational or quasi-experimental data: DiD, event studies, IV, RD, matching, synthetic control |
| ci-cd-pipelines | writing, fixing or reviewing a CI/CD workflow: GitHub and Forgejo Actions, SHA pinning, secrets/OIDC, actionlint, zizmor |
| container-images | writing, building or auditing a Dockerfile or image: multi-stage, BuildKit, digests, non-root, multi-arch, SBOM, trivy |
| cpp-engineering | writing, reviewing or debugging C or C++: UB traps, RAII, concurrency, sanitizers, clang-tidy, ABI |
| dataframes-duckdb | transforming tabular data in code: pandas 3, polars, DuckDB, SQLite, Parquet/Arrow |
| distributed-training | training on more than one GPU or node: torchrun, DDP vs FSDP2, DCP checkpoints, NCCL, JAX sharding |
| frontend-frameworks | building a web front end: React 19, Next.js 16, Svelte 5, Vue, Astro 7, Tailwind v4, Core Web Vitals |
| model-export | exporting a trained model: torch.export, ONNX, ONNX Runtime, Core ML, ExecuTorch, TensorRT, parity checks |
| shell-scripting | a shell script or non-trivial one-liner: bash 3.2 vs zsh vs POSIX sh, BSD vs GNU, quoting, traps, shellcheck |
| tabular-ml | modeling tabular data: gradient boosting, categoricals, leak-free early stopping, Optuna, calibration, SHAP, TabPFN |
| terraform-opentofu | infrastructure as code: Terraform vs OpenTofu, state and locking, modules, moved/import/removed, tflint |
| time-series-forecasting | forecasting: rolling-origin backtests, seasonal-naive baselines, ETS/ARIMA, GBMs with lags, Chronos-2, TimesFM |
| ui-design-systems | UI screens or a component library: DTCG tokens, scales, component states, grids, dark mode, handoff |
| web-accessibility | building or auditing UI for accessibility: WCAG 2.2 AA, ARIA patterns, keyboard and focus, axe, EAA |

Neighbouring skills now split their scope with these (for example `data-analysis` keeps the causal
guardrail and points to `causal-inference`; `self-hosting-ops` runs containers, `container-images`
builds them). The per-skill table of the previous revision is in the
[Changelog](#previous-configuration-readme-as-of-e06af75).

### Code intelligence (LSP)

The `LSP` tool in the coding agents' `tools:` lines stays inactive until a code-intelligence plugin
for the file's language is installed and its server binary is on your `PATH`
([docs](https://code.claude.com/docs/en/plugins/code-intelligence)). Claude then gets diagnostics
after every edit, plus go-to-definition, references and symbol search. The installer enables the
plugin of every language whose server it finds (`--with-lsp` installs missing ones):

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

`agent-stack` is the stack's local marketplace (`dot-claude/stack-plugins/`, installed to
`~/.claude/stack-plugins/`). CUDA `.cu` files get no server. Check with `claude plugin list` or the
**Errors** tab of `/plugin`.

## Security model

The Bash sandbox is the intended boundary: `sandbox.failIfUnavailable: true` makes Claude Code
refuse to start when the sandbox can't, instead of running commands unsandboxed. The guard hook's
shell parsing is defence in depth, a heuristic, not a boundary. Managed settings (optional, your
step) pin the hook entries and deny rules. The prompts and rules are the first line, not the
guarantee.

> [!IMPORTANT]
> **The sandbox is configured, not live-verified.** The settings, the hook and 2401 tests are
> checked; that Claude Code's sandbox enforces them as configured on your machine is not. Until you
> have run the [live checks](#live-checks), count only the guard and the deny rules as tested.

- **No push, no forge writes, by any channel.** The rules forbid `git push` in every form and every
  forge write through `gh`/`tea`/`fj`, `gh api`, a forge's web UI, REST/GraphQL from curl or any HTTP
  client, or MCP. The `no-push` hook denies push and forge-write commands also inside `bash -c`,
  `eval`, `$(...)`, `ssh`, interpreter one-liners and git's own command hooks (aliases, `core.editor`,
  `rebase --exec`, …), and refuses commands decided only at run time. `STACK_POLICY=off` does not
  switch it off. Deny rules repeat the common forms; the installer's own git wrapper refuses push;
  browser-operator never writes on a forge; curl/wget/httpie writes to forge hosts are refused. Limit:
  unsandboxed `gh` or git can still reach a keychain token (see
  [Credentials and least-privilege GitHub](#credentials-and-least-privilege-github)).
- **Protected paths.** Edit/Write are denied on `~/.claude/{hooks,bin,agents,rules,mcp,magg,skills,stack-plugins}/`,
  `settings.json`, `CLAUDE.md`, `.stack-manifest.json`, the backups, the hook state dir, and a
  project's `.git/hooks`, `.git/config`, `.claude/settings*.json` and `.claude/hooks`. The hook
  extends this to Bash: a write, delete, rename or mode change of a protected path (redirection,
  `cp`/`mv`/`tee`/`sed -i`, `rm`, `find -delete`, `chmod`, inline Python, Node, Perl, Ruby, PHP, Lua,
  Julia or R code) is denied — Claude Code's own protected-path check covers only Edit/Write and is
  skipped in `bypassPermissions`. Paths are resolved after expanding `~`, `$HOME`,
  `$CLAUDE_CONFIG_DIR`, `$XDG_STATE_HOME`, `$PWD`, variables assigned earlier in the command, braces,
  globs, `cd` (also through `CDPATH`) and output options (`curl -o`, `wget -O`, `sort -o`, `patch`,
  `sponge`, awk redirects, `git clone`/`init`); `git -C <config dir>` subcommands that rewrite the
  tree are refused. A path behind something the guard can't resolve (a command substitution other
  than `mktemp`, `pwd`, `dirname`, `basename`, `git rev-parse --show-toplevel`; a variable set by
  `read`/`mapfile`/`printf -v`; a loop over one) counts when it could be steered into the config dir.
  A brace expansion past 1,024 words collapses numeric ranges first; a word that still overflows is
  refused whatever it names. The rules add: the installed stack is never edited in place; changes go
  to the repo and the user re-runs the installer.
- **Installing is your step.** The guard refuses `install.sh` for every agent and the main thread,
  except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs (`HOME` and
  `CLAUDE_CONFIG_DIR` both under a temp dir after resolving symlinks, with no link or move in the same
  command). It follows `cd <repo> && ./install.sh`, `lib/install_state.py apply|restore|stage|record|move-legacy`
  on the real config dir, and `install.sh` copied, piped or `git show`n into a shell.
- **Credential printers** are refused for every agent: `gh auth token`, `gh auth status -t`,
  `git credential fill|approve|reject`, `git credential-*`, keychain dumps with `security`, and
  `mcp-headers` in headersHelper mode.
- **Read denies for secrets and backups:** `stack.env` (anywhere under the config dir),
  `.credentials.json`, both `.claude.json` locations, the backups (new root and legacy `backup-*`),
  `~/.ssh`, `~/.aws`, `~/.config/gh/hosts.yml`, the Hugging Face token, `~/.netrc`,
  `~/.git-credentials`, `~/.npmrc`, `~/.pypirc`, `~/.docker/config.json`, `~/.kube`, `~/.gnupg`,
  `~/.config/gcloud`, `~/Library/Keychains` and the usual secret `.env` files (`.env`, `.env.local`,
  `.env.*.local`, `.env.dev[elopment]`, `.env.prod[uction]`, `.env.stag[e|ing]`). MCP tools that read
  local files (context-mode `ctx_index`, markitdown, docling, Playwright, chrome-devtools) are held to
  the same rules by the hook. Key printers are locked too: `mcp-headers` and `with-stack-env` redact
  values by default, and the hook denies `--reveal`, `with-stack-env env|printenv` and `-x` tracing of
  `install.sh`/`doctor.sh`.
- **Sandbox:** see [Sandbox and caches](#sandbox-and-caches).
- **Managed settings (optional, root-owned).** `./install.sh --print-managed-settings > managed-settings.json`
  prints a file that repeats the stack's hook entries, the protected-path and `~/` Read deny rules and
  the sandbox (with `failIfUnavailable`); the JSON goes to stdout, instructions to stderr. Installed
  at `/Library/Application Support/ClaudeCode/managed-settings.json` (macOS) it outranks
  `~/.claude/settings.json`, so editing that file can't remove the entries. **It pins the hook
  entries, not the hook's code:** they still run `~/.claude/hooks/agent_guard.py`, which you (and
  anything running as you outside the sandbox) can edit. Pinning the code needs the optional
  root-owned copy: `agent_guard.py` copied to a root-owned place, every stack hook in the managed file
  pointed at it, and `"allowManagedHooksOnly": true` (which also stops agent-frontmatter hooks, so the
  settings-level `blackcat-guard --settings` wiring must be in the managed file); re-copy after every
  install that changes the hook. The installer never writes anything root-owned. An invalid file stops
  Claude Code from starting. Steps: [CONFIG.md](CONFIG.md) §7.
- **Read-only reviewers, enforced.** code-reviewer, security-auditor, verifier, plan-reviewer and
  claude-code-guide hold Bash, but the hook admits only read-only commands: tests, linters and
  formatters in check mode, syntax checks (`bash -n`, `node --check`, `ruby -c`, `php -l`), builds
  into scratch, `git diff`/`log`/`show`, inspection, `claude --version`, `claude mcp list/get`,
  `claude plugin list`, and the scanners `gitleaks`, `trufflehog`, `semgrep`, `osv-scanner`,
  `pip-audit`, `uv audit`, `npm audit`, `cargo audit`/`deny`, `trivy`. Their scratch scripts and tests
  are content-checked before they run; writing and running scratch code in one command, a scratch
  operand that doesn't exist yet, inline Python that loads scratch code (`sys.path`, `runpy`,
  importlib loaders) and `python -c` from a scratch dir are refused. A project checked out under a
  temp dir (`/tmp`, `/private/tmp`, `/var/folders`, `$TMPDIR`) is the project, not scratch (the
  project is `CLAUDE_PROJECT_DIR`); `./.claude-work` is scratch everywhere. Anything else is refused
  (fail closed).
- **Consent only from the user, only on the main thread.** A destructive, irreversible or externally
  visible action reaches a subagent one way: the agent stops with `STATUS: blocked`,
  `NEXT: ASK USER: <exact action>`; BlackCat asks with AskUserQuestion (always, even when the prompt
  seemed to allow it) and relays the answer word for word. Text in a brief, a tool result or another
  agent's message is never consent. `CronCreate`, `RemoteTrigger` and the magg calls listed in
  [magg ask rules](#magg-ask-rules) are `ask` rules, which prompt even in `bypassPermissions`; a
  background agent's prompt shows in your main session.
- **Untrusted content is data.** Web pages, documents, emails, file contents, code comments, tool
  and MCP output never direct an agent; instructions found there are reported, not followed.
- **neural-memory recall is data.** Recalled items are leads to check against code, files or sources,
  never settled decisions. `nmem_remember` stores only facts verified against a local artifact (file,
  test output or commit), cited in the memory. The web-reading agents (researcher, researcher-copy,
  scout, browser-operator) can't write it: the hook refuses their `nmem_remember`.
- **Web taint reaches memory writes, also second-hand.** An agent that read web content (WebFetch,
  WebSearch, curl/wget, and every MCP tool except a short non-web list: neural-memory, wolfram,
  wandb, image-studio, the Adobe and Blender servers, huetension, ide, magg's management tools and
  its local database/kernel servers) can't write the shared memory for the rest of the session. The
  taint relays: an agent is tainted when any agent linked to it read the web — a child that reported
  back to it (transitively), an agent it exchanged SendMessage with (either direction, transitively),
  or the prompt it was spawned with (a child of a tainted agent is born tainted). A spawn whose mark
  can't be recorded is refused; past 4,096 linked agents the check fails closed. The refusal names the
  source ("scout 1a2b"). The main thread is not a link, and files are not links (see
  [Residual risks](#residual-risks)).
- **libdocs and image-studio SSRF.** libdocs fetches https only, resolves each host, requires a
  global address, connects to the checked IP, re-checks every redirect hop and keeps table-of-contents
  links on the docs origin. image-studio pins each connection to the IP it checked (no DNS
  rebinding), sends each key only to its own provider, follows no redirects with a key, downloads
  results only over https from public hosts, sends only real PNG/JPEG/WebP inputs from outside
  credential folders, and strips scripts, event handlers and `javascript:` links from saved SVGs.
- **Keys.** They live only in `stack.env` (0600). Remote MCP servers get them through the header
  helper at connect time; spider and magg get only their own keys; nothing goes into `~/.claude.json`,
  argv or agent files. `GITHUB_TOKEN` is no longer exported to shells, and `claude-ninja`/`claude-god`
  start with forge tokens unset. Optional: `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` in `settings.json` →
  `env` strips the credentials Claude Code recognizes from Bash, hook and MCP environments. GitHub:
  see [Credentials and least-privilege GitHub](#credentials-and-least-privilege-github).
- **Pinned supply chain.** uv 0.12.20 and huetension v0.3.0 from release tarballs checked by sha256;
  magg 1.2.1 with `--exclude-newer 2026-09-22T00:00:00Z`; the sci and ml venvs from hash-locked
  `requirements/*.txt` (`--require-hashes`, 7-day cooldown; sci also `--only-binary :all:`); the After
  Effects MCP at commit `88d5fbf0` with `npm ci --ignore-scripts`; `--with-lsp` installs pyright
  1.1.414, typescript-language-server 6.0.1 (5.3.0 on Node < 22.22.2) and typescript 6.0.3 with
  `--ignore-scripts`; third-party MCP servers pinned to exact versions (see [MCP servers](#mcp-servers)).
  Every install shows what changed in the shipped tree since the last one and, on a terminal, asks
  before applying it (see [What a run does](#what-a-run-does)).

### Sandbox and caches

`settings.json` → `sandbox`: `enabled: true`, `failIfUnavailable: true`,
`allowUnsandboxedCommands: false`.

- **Can't write** (`filesystem.denyWrite`): the config dir (`~/.claude` or `$CLAUDE_CONFIG_DIR`);
  `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack`, `-backups` and `-cache` (guard state,
  installer backups, the MCP servers' caches; rendered from `XDG_STATE_HOME` at install time); your
  own `~/.cache/uv` and `~/.cache/pre-commit`; `~/Library/Caches/Coursier`; the Playwright browser
  caches; the Hugging Face token file.
- **Can write** (`filesystem.allowWrite`) outside the project only `~/.cache/claude-sandbox`. Shared
  caches (`~/.cache`, `~/Library/Caches`, cargo, Go, Gradle, Maven, bun, matplotlib) and toolchain
  homes (`~/.local/share/uv`, `~/.npm`, rustup, elan, Julia depots) are no longer writable: installed
  toolchains work, installing new ones from a session fails. Julia can put a writable depot first:
  `JULIA_DEPOT_PATH=$HOME/.cache/claude-sandbox/julia: julia …`.
- **Can't read** (`filesystem.denyRead`): `stack.env`, `backup-*`, the backups, `.credentials.json`,
  `~/.config/gh/hosts.yml`, `~/.git-credentials`, `~/.config/git/credentials`.
- **Network** (`strictAllowlist`): localhost, package registries (PyPI, npm, crates, Go, Julia, Lean,
  Homebrew), forges (GitHub, GitLab, Codeberg, Bitbucket), Hugging Face, W&B, arXiv.
- **Environment** (`credentials.envVars`, mode deny): the forge tokens (`GITHUB_TOKEN`, `GH_TOKEN`,
  GitHub Enterprise, GitLab, Gitea, Forgejo, Codeberg), `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`,
  `WANDB_API_KEY`, `JUPYTER_TOKEN`.

**How sandboxed Bash gets its caches (`STACK_CACHE` and `CLAUDE_ENV_FILE`).** A SessionStart hook
without a matcher (`agent_guard.py session-env`, every session source) appends exports to
`$CLAUDE_ENV_FILE`, which Claude Code runs before each Bash command, the agents' included. They point
every tool at `~/.cache/claude-sandbox/<tool>`: `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR`,
`npm_config_cache`, `npm_config_devdir`, `npm_config_store_dir`, `YARN_CACHE_FOLDER`,
`BUN_INSTALL_CACHE_DIR`, `DENO_DIR`, `PRE_COMMIT_HOME`, `HF_HOME`, `MPLCONFIGDIR`, `CARGO_HOME`,
`GOMODCACHE`, `GOCACHE`, `GRADLE_USER_HOME`, `COURSIER_CACHE`, `CCACHE_DIR`, `SCCACHE_DIR`, and
`-Dmaven.repo.local=<dir>/m2` appended to `MAVEN_OPTS`. Nothing else sees them: MCP servers, hooks,
language servers and your terminal keep their normal caches, which sandboxed code can no longer write.
`~/.cache/claude-sandbox` is safe to delete. The stack's own local MCP servers keep a private cache,
`STACK_CACHE` = `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-cache/{uv,npm}`, set in each
server's `env`, warmed by the install's prefetch and denied to the sandbox.

The hooks reference promises `CLAUDE_ENV_FILE` to "subsequent Bash commands" and says nothing about
subagents. The installed CLI (2.1.284) keeps the file per session, not per agent, and prepends it to
every Bash command of the session, subagents' included, so subagents get it; that the docs don't
promise it is why it is a live check.

Trade-offs, sandboxed Bash only:

- `CARGO_HOME` moves, so `~/.cargo/config.toml` and cargo's credentials aren't read, and
  `cargo install` binaries land in the sandbox's cargo dir.
- `GRADLE_USER_HOME` moves, so `~/.gradle/gradle.properties` isn't read.
- `HF_HOME` moves, so models download again into the sandbox cache and no Hugging Face token is found.
- When `$HOME` holds a character Maven would split on (a space, a quote), `MAVEN_OPTS` is left alone
  with a warning, and Maven falls back to `~/.m2`, which the sandbox refuses.
- A tool that writes `~/Library/Caches` (or another cache) with no variable to redirect it fails.
- A Bash command that runs before the SessionStart hook has written the file gets the default paths,
  which the sandbox refuses (fails closed).

**When the hook fails** (no `CLAUDE_ENV_FILE`, an unwritable file or `~/.cache/claude-sandbox`, or
its marker missing after writing), it exits 2 and the session shows a SessionStart hook error: "the
sandboxed Bash environment is NOT set for this session (reason) … Check with …/bin/doctor.sh, then
start a new session (or /clear)." The session goes on without the sandbox caches and with git's
credential helpers on. The guard records running/ok/failed in the session's `session-env.json`; the
status line then starts with a red `! Bash sandbox env missing: doctor.sh` (also when the hook never
finished, after 30 s). `doctor.sh` runs the hook against a temp dir and warns when it failed in any
of the last 10 sessions.

An upgrade retracts from your `settings.json` the `env` keys and `allowWrite` entries earlier
installs shipped (`UV_CACHE_DIR`, `npm_config_cache`, `PRE_COMMIT_HOME`,
`GIT_CONFIG_COUNT`/`KEY_0`/`VALUE_0`; `~/.cache`, `~/Library/Caches` and the toolchain dirs), prints
each (`retracted sandbox.filesystem.allowWrite entries the stack no longer ships: …`,
`retracted stack env KEY=value (no longer shipped)`) and keeps entries of your own. A first install
(no manifest yet) retracts nothing. `doctor.sh` warns when the old keys or a broad cache dir are still
there and confirms the session-env hook is wired.

### Credentials and least-privilege GitHub

- **Git credential helpers are off in sandboxed Bash only.** The same session-env hook appends
  `'credential.helper='` (an empty helper list) to `GIT_CONFIG_PARAMETERS`, after any value already
  there, and touches no `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_*` of yours. Unsandboxed git (plugin
  marketplace updates, MCP servers, your terminal) keeps your helpers, so private marketplace
  updates work. A private HTTPS fetch from an agent's Bash needs SSH or your terminal.
- Sandboxed commands can't read `~/.config/gh/hosts.yml`, `~/.git-credentials` or
  `~/.config/git/credentials`, and don't get the token variables listed above.
- **What remains:** `gh` and git's osxkeychain helper, run outside the sandbox, can still reach a
  keychain token. **Least-privilege setup:** give the agents no write-capable GitHub credential.
  Either none at all, or a read-only fine-grained token (Contents: read, Metadata: read) that `gh`
  uses from a config dir of its own:

  ```bash
  GH_CONFIG_DIR=~/.config/gh-agents gh auth login --with-token < token-file
  export GH_CONFIG_DIR=~/.config/gh-agents     # in the shell you start claude from
  ```

  Push over SSH from your own terminal (agents never push: hook-enforced), and keep write-capable
  HTTPS credentials out of the `github.com` keychain entry git's osxkeychain helper reads, since
  unsandboxed git still uses it.
- **`doctor.sh` checks it.** Its section "GitHub credentials agents could use" reports by presence
  only (no value is printed; keychain lookups are attribute searches without `-g`/`-w`, so no secret
  is read and no prompt appears): `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`,
  `GITHUB_ENTERPRISE_TOKEN` in the environment; a plain-text `oauth_token` in gh's `hosts.yml`
  (`$GH_CONFIG_DIR` or `~/.config/gh`); a github.com line in `~/.git-credentials` or
  `${XDG_CONFIG_HOME:-~/.config}/git/credentials`; on macOS a keychain item for service
  `gh:github.com` and a github.com internet password. Each is a WARN naming who can use it and the
  least-privilege step; none found is `ok`. Run `bash ~/.claude/bin/doctor.sh` to see what an agent
  could find.

### magg ask rules

These magg calls are `ask` rules, which prompt even in `bypassPermissions`: `magg_add_server`,
`magg_load_kit`, `proxy`, `magg_enable_server`, and every `duckdb_*`, `jupyter_*`, `ros_*`
(publishes, calls services, sets parameters on a robot), `qiskit_*` (submits IBM Quantum hardware
jobs, spends quota) and `docspace_*` (writes to ONLYOFFICE DocSpace rooms and files) call.
**Invariant:** every magg catalog prefix has exactly one allow or ask rule (a test enforces it), so
no catalog server runs without a decision. The allowed `mongodb_*` and `postgres_*` rely on their
read-only flags (`--readOnly`, `--access-mode=restricted`), which a test pins. duckdb runs on an
in-memory database with extension autoload off and its settings locked; an explicit `INSTALL` in an
approved query still works.

### Residual risks

- **Language servers on writable build files.** rust-analyzer (build scripts, proc macros),
  Metals/Gradle, HLS, `lake serve` and LanguageServer.jl run outside the sandbox on build files the
  sandbox can write (`build.rs`, `build.sbt`, `lakefile`, …): a sandboxed edit gets its code run
  unsandboxed at the next server start. Accepted: the project is writable by design, and the shared
  caches are gone, so this is the project's own files only. Disable the LSP plugins for untrusted work.
- **Heuristic guard gaps.** The T2 content checks (reviewers' scratch code), the T3 taint and the
  forge-host detection are parser-based; code that hides from the patterns gets past them. Known
  gaps: a background job swapping a scratch file between calls; `python -m` of a module shadowed in a
  scratch cwd and a `PYTHONPATH` exported in an earlier call; `/usr/bin/env python3 …` and
  `env -C DIR ./install.sh`; a copy of `install.sh` run directly (no shell word); links made by
  `git clone`/`checkout`; `patch` reading its target from the diff; output flags glued to others
  (`wget -qO-FILE`); a variable exported by your own shell profile that points into the config dir.
- **Approved duckdb and jupyter calls.** An approved duckdb query can read or write files you can;
  an approved jupyter call runs arbitrary code in your kernel. Read the call before approving.
- **Read-only database servers.** `mongodb` and `postgres` run without a prompt because of their
  read-only flags; a server-side bug in those modes would go unprompted.
- **Web taint gaps.** Taint follows reports, messages and spawn prompts, not files: an agent that
  saved web text to a file and another that reads it later are not linked. The main thread is a gap
  too: its web reads are not tracked as taint.
- **`GOD_AFTER_NINJA` checks order only.** Any finished ninja-coder run of the session, even a
  trivial one, unlocks the god-coder spawn; that ninja-coder actually failed rests on the prompts.
- **A session started directly in a temp dir** (`/tmp`, say) has no project dir: all of `/tmp` is
  scratch for the read-only agents there.
- **Live checks still open** ([Live checks](#live-checks)).
- **No per-agent URL policy (T1).** WebFetch domain allow rules do nothing in `bypassPermissions`,
  and ask rules can't be scoped per agent type; which agents fetch at all is set by their `tools:`
  lines. A guard URL policy keyed on agent type was weighed and not built: a docs-domain allowlist for
  the coder types would refuse legitimate research (issue trackers, blogs, mailing lists, vendor docs
  on their own domains), and a "long high-entropy query string" check both refuses normal URLs
  (commit SHAs, signed download URLs, search queries) and misses exfiltration through path segments
  or many short requests. The boundary stays the tool lists, the web taint on memory writes, and the
  no-push/forge-write hooks.
- **Keychain tokens.** See [Credentials and least-privilege GitHub](#credentials-and-least-privilege-github).
  The keychain service name `gh:github.com` that `doctor.sh` looks for comes from gh's source and is
  unverified against a live gh.
- **Linux `.git/modules`.** On Linux/WSL2 the sandbox drops write-list entries with a mid-path
  wildcard, so the `.git/modules/**` denies protect submodule hooks and config only on macOS.
- **Unverified live:** that the sandbox honours the absolute rendered state, backup and cache paths;
  that a `denyWrite` entry wins inside `allowWrite` (the docs' `/sandbox` Config tab lists such paths
  as "Denied within allowed"); that settings `env` reaches MCP servers and hooks; that the
  `$CLAUDE_ENV_FILE` exports reach subagents' Bash.

### Live checks

Only you can run these. They are still open: until they pass, the sandbox is configured, not
verified.

1. **Install:** `./install.sh --dry-run`, read the plan, then `./install.sh` from a terminal. After a
   `git pull`, the supply-diff question appears; `n` leaves everything as it was.
2. **Sandbox denyWrite:** `/sandbox`, Config tab: `allowWrite` shows only `~/.cache/claude-sandbox`;
   the state dir (`$XDG_STATE_HOME/claude-agent-stack` or `~/.local/state/…`), the backup root and the
   cache root show under deny ("Denied within allowed" where nested). From sandboxed Bash, a write
   into `~/.claude`, the backup root, `~/.cache/uv`, the `STACK_CACHE` root and `~/Library/Caches/x`
   is refused; `uv pip download` or `npm cache ls` works (their sandbox caches).
3. **Env reach:** `echo "$UV_CACHE_DIR"` in the main thread's Bash and in a subagent's Bash (ask a
   coder to run it) prints `~/.cache/claude-sandbox/uv`, expanded, in both, and
   `git config --get-all credential.helper` prints an empty last line. Check also whether settings
   `env` reaches MCP servers and hooks as described.
4. **Keychain from the sandbox:** whether the osxkeychain helper answers inside the sandbox; count
   the bytes of its answer, never print it. A private plugin marketplace update
   (`/plugin marketplace update <name>`) still works over HTTPS with your keychain helper.
5. **Routing:** a live BlackCat probe: a task with a god-coder plan step goes to the orchestrator.
6. **Ask rules:** an ask rule prompts under `bypassPermissions` (for example, a magg `duckdb_*` call
   through mcp-broker).
7. **Credentials:** `bash ~/.claude/bin/doctor.sh`: the GitHub credentials section lists what an
   agent could use; nothing printed is a secret.

## MCP servers

**How servers turn on and off.**

1. **Agent-scoped (local stdio).** A server declared inline in an agent's `mcpServers` connects when
   that agent starts and disconnects when it finishes. BlackCat declares none.
2. **Remote, user scope (HTTP).** They belong to the session. With `MCP_DISCOVERY_CACHE=1` a server
   used before connects on its first tool call; otherwise at start, in the background. Only agents
   whose `tools:` line names a server can call it. Keys come from `stack.env` through
   `bin/mcp-headers` at every connection.
3. **Tool search:** a connected server costs only tool names until a tool is used (Claude Code's
   default on the Anthropic API; the stack leaves `ENABLE_TOOL_SEARCH` unset).
4. **On demand through mcp-broker + magg.** Catalog servers stay disabled; the broker enables one,
   runs the calls, returns the results and disables it. Each broker's magg runs on a private copy of
   the catalog (`bin/magg-private`), so parallel brokers never switch servers off under each other.
   Enabling or adding a server, loading a kit, `proxy` and the risky catalog tools ask you first
   ([magg ask rules](#magg-ask-rules)).

Third-party servers are pinned to the versions checked on 26 Sep 2026. To upgrade one, bump it in the
repo (agent files, `magg/config.json`, the installer's prefetch step) and re-run the installer.

| Server | How | Used by | Key |
|---|---|---|---|
| libdocs (custom) | stdio, agent-scoped | coders, planner, plan-reviewer, code-reviewer, ML agents | uses EXA/JINA/SPIDER keys if set; `GITHUB_TOKEN` optional, read from `stack.env` |
| image-studio (custom) | stdio, agent-scoped | image-director, designer | `OPENROUTER_API_KEY` (SVG, edits), `OPPER_API_KEY` (photos); models `IMAGE_STUDIO_SVG_MODEL`, `_IMAGE_MODEL`, `_EDIT_MODEL` |
| spider (`spider-cloud-mcp@1.2.2`) | stdio, agent-scoped | researcher | `SPIDER_API_KEY` (the only key it gets) |
| playwright (`@playwright/mcp@0.0.82 --headless --isolated`) | stdio, agent-scoped | browser-operator, frontend-engineer, verifier | — (needs Google Chrome) |
| markitdown (`markitdown-mcp==0.0.1a7`) | stdio, agent-scoped | doc-specialist | — |
| context-mode (`context-mode@1.0.169`, the MCP server only) | stdio, agent-scoped | researcher, doc-specialist | — (Node ≥ 22.5) |
| neural-memory (`neural-memory==4.62.0` through `mcp/neural_memory_mcp.py`) | stdio, agent-scoped | orchestrator, researcher, mathematician, main-/ninja-/god-coder, ml-/dl-/llm-/robotics-/quantum-engineer, data-scientist | — |
| illustrator (`illustrator-mcp-server@1.10.3`), huetension | stdio, agent-scoped | designer | — (grant macOS Automation) |
| blender (`mcp-for-blender@2.1.1`, telemetry off) | stdio, agent-scoped | cg-artist | — (Blender running with the add-on) |
| after-effects (Dakkshin, commit `88d5fbf0`), premiere (`premiere-pro-mcp@1.18.2`) | stdio, agent-scoped | motion-designer | — (`--with-adobe`) |
| magg | stdio, agent-scoped | mcp-broker | only the catalog's keys from `stack.env` |
| exa | remote | scout, researcher, planner, coders, verifier, security-auditor, ML agents | `EXA_API_KEY` optional |
| jina | remote | scout, researcher, planner, mathematician, writer, … | `JINA_API_KEY`, effectively required |
| wolfram | remote | mathematician, quantum-engineer, ninja-/god-coder | none |
| huggingface | remote | researcher, ml-/dl-/llm-engineer, data-scientist | `HF_TOKEN` optional |
| wandb | remote, registered only with a key | ml-/dl-/llm-/robotics-engineer | `WANDB_API_KEY` |
| computer-use, claude-in-chrome | built into Claude Code | GUI agents; browser-operator | computer use: `/mcp` → Enable; Chrome: `claude --chrome` |

**Catalog (disabled until mounted):** docling, playwright, lean, duckdb, arxiv, jupyter, mlflow,
docspace (ONLYOFFICE), mongodb (`--readOnly`), postgres (`--access-mode=restricted`), chrome-devtools,
ros, qiskit-runtime. duckdb, jupyter, ros, qiskit and docspace calls ask at every call; the local
servers run on the stack's private `STACK_CACHE`.
Versions and details: [mcp_servers.md](mcp_servers.md).

### Context economy: context-mode and neural-memory

Neither shrinks the live window (auto-compaction at 400K does that); they keep things out of it.
**context-mode** indexes a page or a local file into a local SQLite FTS5 store and returns only the
passages asked for (researcher, doc-specialist). Only its index/search/stats tools are allowed; its
code-execution, upgrade, purge and insight tools are denied, and the hook checks `ctx_index` paths
against the Read denies (no directories). **neural-memory** is a local associative memory shared by
twelve agents (`~/.claude/neural-memory/`, brain `claude-agent-stack`). The stack's wrapper writes a
compact `config.toml` (4 tool schemas, no hooks added to `settings.json`) and replaces the server's
instructions with the stack's policy (see [Security model](#security-model)). Delete
`~/.claude/neural-memory/` to start afresh.

## Enforced behaviours (hooks)

| Event | What `agent_guard.py` does |
|---|---|
| PreToolUse `*` (`budget`) | Context-token budgets per prompt and per session, and each subagent's MCP call cap; fails open on unreadable transcripts |
| PreToolUse `*` (`blackcat-guard --settings`) | BlackCat's own gate (acts only when `agent_type` is blackcat): its tool allowlist and `BLACKCAT_MAX_STEPS` |
| PreToolUse `Agent` | Spawn policy, depth, copy rule, fan-out caps (atomic leases), BlackCat dispatch window; god-coder orchestrator-only and once per session; strips a per-call `model`; drops BlackCat's `run_in_background: false`; denies `isolation: "remote"` (cloud agents load no hooks) |
| PreToolUse `SendMessage` | Resuming a finished agent follows the spawn policy and the parent's caps |
| PreToolUse `Bash\|Monitor\|PowerShell` (`no-push`) | Never push, never write to a forge (also curl/wget/httpie to forge hosts); credential printers; `--reveal` and `env`/`printenv` under the key helpers; `-x` tracing of `install.sh`/`doctor.sh`; running `install.sh` outside the allowed forms; Bash-level writes to protected paths; read-only allowlist and scratch-code checks for the reviewer types |
| PreToolUse `mcp__neural-memory__nmem_remember` | An agent tainted by web content, directly or through a linked agent, can't write the shared memory |
| SessionStart, no matcher (`session-env`) | Appends the sandbox cache exports and the empty git credential helper to `$CLAUDE_ENV_FILE` for Bash; on failure exits 2 (hook error notice) and records it in `session-env.json` for the status line and `doctor.sh` |
| PreToolUse `mcp__computer-use__*` | One agent on the screen at a time |
| PreToolUse local-file MCP tools | Path and `file:` arguments held to every `Read(...)` deny rule |
| PostToolUse `Agent\|TaskStop`, SubagentStart/Stop, StopFailure | Registry of who spawned whom; locks released when an agent stops |
| PostToolUseFailure / PermissionDenied | Roll back leases and markers |
| UserPromptSubmit, SessionStart | Reset per-prompt markers; clear stale locks; prune old state |
| PostToolUse `Read\|mcp__*`, PreToolUse `mcp__*` (`image-limit`) | Images an agent reads are re-encoded to ≤ 1919 px per side and under the 5 MB API cap; images uploaded through browser tools are swapped for downscaled copies |

Every hook command uses an absolute interpreter chosen at install time (a broken shim would make every
hook fail to start, which Claude Code treats as "allow"). A PreToolUse handler that errors denies the
call (fail closed); the escape hatch `STACK_POLICY=off` is shown only to you. `/stack-doctor` runs
the real hook commands on calls that must be denied, to prove the gates are closed.

### Knobs

`settings.json` → `env`. Owned knobs (●) are reset to the stack's value on every install; change them
in the repo's `dot-claude/settings.json` and re-run the installer. The rest are defaults in
`agent_guard.py` or values you may change.

| Knob | Default | Meaning |
|---|---|---|
| `BLACKCAT_MAX_DISPATCH` ● / `BLACKCAT_DISPATCH_WINDOW_S` | 8 / 120 | BlackCat Agent calls per prompt, all within this many seconds of the first |
| `BLACKCAT_MAX_STEPS` ● | 12 | BlackCat tool calls per prompt, dispatches included |
| `STACK_MAX_FANOUT` ● | 3 | Running + starting children per agent (0 = no cap) |
| `STACK_MAX_FANOUT_BY_TYPE` ● | `orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | Per-type overrides (`DEFAULT_FANOUT_BY_TYPE` in `agent_guard.py`) |
| `STACK_MAX_SELF_FANOUT` ● | 2 | Copy agents of one type running at once, session-wide |
| `STACK_PROMPT_CTX_BUDGET` ● / `STACK_SESSION_CTX_BUDGET` ● | 100000000 / 666000000 | Context tokens (input + cache writes + cache reads, all agents) per prompt / per session |
| `STACK_MAX_MCP_CALLS` ● | 64 | MCP calls per subagent per prompt, capped lower by the agent's `maxTurns` (0 = off) |
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | 32 | Claude Code's cap on subagents running in one session |
| `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` ● | 4 | BlackCat → L1 → L2 → L3 → L4 |
| `STACK_FANOUT_IDLE_S` | 600 | A background child whose whole subtree is silent this long stops counting |
| `STACK_LEASE_TTL_S` / `STACK_RESUME_TTL_S` | 21600 / 120 | Ceilings on unreported spawn leases and resume reservations |
| `GOD_SPAWNERS` / `GOD_ONCE_PER_SESSION` | `orchestrator` / 1 | Who may spawn god-coder; one spawn per session |
| `GOD_AFTER_NINJA` | 1 | A god-coder spawn needs a ninja-coder of this session that has finished; checks order, not failure (0 = off) |
| `GOD_IDLE_S` / `GOD_PENDING_TTL_S` / `GOD_LOCK_TTL_S` | 1800 / 120 / 21600 | god-coder lock: idle holder, unconfirmed lease, hard ceiling |
| `SCREEN_LOCK_TTL_S` | 900 | Screen lock expiry |
| `STRIP_AGENT_MODEL` / `BLACKCAT_BACKGROUND` | 1 / 1 | Remove per-call `model`; run BlackCat's children in the background |
| `STACK_POLICY` | on | `off` disables every deny and lock except the push and forge-write ban (bookkeeping continues) |
| `STACK_GUARD_LOG` | 0 | 1 = log raw hook events to the state dir (budget mode logs tool names and ids only) |
| `STACK_IMAGE_MAX_PX` / `STACK_IMAGE_MAX_B64` | 1919 / 4500000 | Longest image side; most base64 characters of one image |
| `STACK_IMAGE_UPLOAD_TOOLS` | — | Regex of more MCP tools whose image arguments get downscaled copies |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `claude-sonnet-5-5` | Claude Code's small-model slot |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | Web searches per session, all agents |
| `MCP_TIMEOUT`, `MAX_MCP_OUTPUT_TOKENS` | 60000, 25000 | MCP start-up timeout, tool output cap |

## Status line

`bin/statusline.py` renders `blackcat · Sonnet 5.5 · medium · ctx 156K/400K ▓▓▓░░░░░ · 5h 23% · 7d 41% · cache 91%`:
agent, model, effort, the main conversation's tokens against the 400K auto-compact window, your
plan's 5h/7d rate-limit windows, cache hit rate. When the session-env hook failed or never finished,
the line starts with a red `! Bash sandbox env missing: doctor.sh`
([Sandbox and caches](#sandbox-and-caches)). It is set only if you had no status line; remove
`statusLine` from `settings.json` to turn it off.

## ML setup (`--with-ml`)

`~/.claude/venvs/ml` is installed from the hash-locked `requirements/ml.txt`: numpy/scipy/pandas/polars,
scikit-learn, statsmodels, XGBoost, LightGBM, PyTorch, Transformers, Datasets, Accelerate, PEFT,
safetensors, and on Apple Silicon `mlx` and `mlx-lm[evaluate]`. The ML agents use the project's own
environment first, this venv second, never the system Python. Local inference stays MLX-native on the
Mac (mlx-lm; oMLX as the local endpoint); CUDA work runs only on an NVIDIA host you name.

## Apps

Every app below runs Claude Code with your user settings, so it starts as BlackCat with the whole
stack: agents, skills, hooks, rules, sandbox, MCP servers and auto-compaction at 400K. Checked on
27 Sep 2026 (details in the [previous configuration](#previous-configuration-readme-as-of-e06af75)).

| App | Runs | What to set | Limits |
|---|---|---|---|
| Terminal (Ghostty, Terminal) | your `claude` | once: `/effort medium` | none; the only place for `claude-ninja` / `claude-god` |
| **Claude Desktop, Code tab** (Local) | Claude Code built into Desktop | model **Sonnet 5.5**, effort **medium** for BlackCat sessions | no agent teams; panel commands such as `/permissions` don't open |
| **Conductor** 0.87.5 | Claude Code 2.1.280, bundled | model **Sonnet 5.5**, thinking **medium**, Ultracode **off** | always bypass-permissions (deny rules, sandbox and guard still apply) |
| VS Code / Cursor extension | its own Claude Code | nothing | a subset of slash commands |
| JetBrains plugin | your `claude`, in the IDE terminal | nothing | none |
| Zed (Claude Agent) | Claude Code through the ACP adapter | nothing | a few slash commands hidden |
| Nimbalyst | Claude Agent, or your own `claude` in a pane | the 1M model row with the CLI provider | its effort control sets `CLAUDE_CODE_EFFORT_LEVEL`, which overrides every agent's effort |
| AionUI | your `claude`, in print mode | no AionUI MCP servers in Claude chats | an AionUI MCP server passes `--strict-mcp-config`, dropping your servers |

In the Agent SDK apps (Desktop, Conductor, Nimbalyst, VS Code, Zed) the model and effort pickers set
the main thread; subagents keep their own. BlackCat's children always run in the background (a
foreground child would block the app for its whole run); a subagent passes `run_in_background: false`,
and calls sent together still run in parallel. For a plain Claude Code session instead of BlackCat,
set `"agent": "claude"` in a project's `.claude/settings.json`. `claude -p` starts in
`bypassPermissions`: pass `--permission-mode default` for scripted work that should refuse commands
that aren't pre-approved.

### Claude Desktop, step by step

1. Install from Terminal (`./install.sh`), then **restart Claude Desktop**. Open **Code**, choose
   **Local** and your project folder.
2. Set the model to **Sonnet 5.5** and effort to **medium** (Cmd+Shift+E).
3. **Background model:** in the environment dropdown, hover over **Local**, click the gear and add
   `ANTHROPIC_DEFAULT_HAIKU_MODEL` = `claude-sonnet-5-5` (Desktop can route models itself and then
   ignores that key in `settings.json`).
4. **Keys** need nothing extra: every server reads `stack.env` itself or through `bin/mcp-headers` /
   `bin/with-stack-env`, and every command is an absolute path.
5. **Computer use:** Settings → General → on, then grant Accessibility and Screen Recording.
6. **Check:** send `@oracle what is a monad?`; the subagent pane shows oracle.

### Conductor, step by step

1. Nothing to install in Conductor: it reads `~/.claude` and `~/.claude.json`. If you switch it to
   your own `claude`, keep that at 2.1.271 or later.
2. Per chat: model **Sonnet 5.5**, thinking **medium**, Ultracode **off**.
3. Work runs in the workspace's git worktree; `.claude-work/` is excluded from git there too.
4. For ninja-coder or god-coder at ultracode, use `claude-ninja` / `claude-god` in a terminal.

## Using it

- Just talk to it. To force an agent, start with `@designer …` or `@ninja-coder …` (god-coder goes
  through `@orchestrator …`, once per session, or `claude-god`).
- Long single-domain sessions can skip BlackCat: `claude --agent main-coder --effort high`. That
  agent's spawn policy still applies.
- The hardest problems at ultracode: `claude-ninja` or `claude-god` (`claude --agent <ninja|god>-coder
  --effort ultracode` with workflow launches pre-approved for that session, forge tokens unset).
  Dispatched by another agent, both run at `max`.
- Don't set `CLAUDE_CODE_EFFORT_LEVEL`: it overrides every agent file's effort.

Smoke tests: `@oracle what is a Kan extension?` · `what's the latest stable Rust version?` (scout) ·
`plan how to migrate my Astro blog to MDX` (planner) · `@researcher compare LoRA, DoRA and QLoRA …;
split the work` (researcher copies) · `@orchestrator … use god-coder twice` (the second spawn is
denied) · `/context` and `/stack-doctor`.

## For maintainers

```bash
uv run tests/lint_agents.py                       # frontmatter, maxTurns, POLICY ↔ "May spawn", copies, skills, listing size
/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test   # the hooks' own interpreter
uv run --python 3.12 --with pytest --with pillow --with httpx --with "mcp>=1.10,<2" pytest -q tests/
bash tests/install_smoke.sh                       # hermetic installer runs (see Testing in a scratch HOME)
```

Tests that pin this revision's guarantees: `test_no_duplicates.py`, `test_no_push.py`,
`test_protected_paths.py` (including the sandbox block), `test_readonly_agents.py`,
`test_libdocs_mcp.py` and `test_image_studio_mcp.py` (SSRF), `test_lint_skills.py`. A new skill is a
folder with a `SKILL.md` whose frontmatter has `name` (the folder name) and a one-line `description`
that starts with its trigger, names no agent and contains no colon-space or space-hash (YAML). Keep `__UPPERCASE__`
tokens out of skill examples: the installer replaces its placeholders and the smoke test fails on any
left over. The installer refuses to run outside macOS; the smoke test sets `STACK_ALLOW_NON_MACOS=1`.

## Troubleshooting

- **`/stack-doctor` first.** It prints the exact fix for each FAIL.
- **Something of yours disappeared after an install.** It is in the backup:
  `./install.sh --restore --dry-run`, then `./install.sh --restore`. Next time use `--no-prune`.
- **A spawn you expected was denied.** The reason names the rule. For a stuck lock, restart with
  `claude --resume` (SessionStart clears locks) or wait for the TTL.
- **A Bash command was refused as a protected-path write or by the sandbox.** Intended: change the
  stack in the repo and re-run the installer. A tool that needs another network host fails under the
  strict allowlist; add the host to the repo's `sandbox.network.allowedDomains`.
- **A build tool fails writing a cache in a session.** Sandboxed Bash writes only
  `~/.cache/claude-sandbox`; check that the tool honours one of the session-env variables
  ([Sandbox and caches](#sandbox-and-caches)). Installing a new toolchain (rustup, elan, Julia
  packages) from a session fails by design: do it in your terminal.
- **Claude Code won't start after the install.** `failIfUnavailable` stops it when the sandbox
  can't start (by design: no silent unsandboxed fallback). The error names the cause; see Claude
  Code's sandboxing docs.
- **The installer stopped on a symlinked dir.** See [Symlinked config dirs](#symlinked-config-dirs).
- **Claude Desktop shows nothing while an agent works.** A foreground child blocks BlackCat: re-run
  `./install.sh`, start a new session, and check that `BLACKCAT_BACKGROUND` isn't `0`.
- **Bypass the policy temporarily:** `"STACK_POLICY": "off"` in `settings.json` → `env` (the push
  and forge-write ban stays on).
- **Uninstall:** `./install.sh --restore <the first install's backup>` (it removes the files that
  install added and puts back what it replaced), remove the `# claude-agent-stack` line
  from your shell rc, and `claude mcp remove -s user exa` (and jina, wolfram, huggingface, wandb).

## Changelog

Every applied parameter (model, effort, maxTurns, caps, knobs) with its reason: [CONFIG.md](CONFIG.md).

### 2026-09-29 — Security rounds 2 and 3, sandbox caches, god-coder plan flow

Commits `e46fa83..cfa9ee7` on `main` (plus the documentation commits). Round 3 and round 4 audit
verdicts: pass with residuals, no HIGH open; both depend on the live sandbox, which is unverified
([Live checks](#live-checks)).

- **Prompts** (`e46fa83`, `13c5e17`, `ea80f87`). BlackCat routing tie-breaks; consent wording routed
  through `NEXT: ASK USER`; mcp-broker's approval wording matches the ask rules; god-coder as a plan
  step after ninja-coder only (planner, plan-reviewer, BlackCat, orchestrator, rules).
- **Round 2, guard** (`e94ff4a`, `74e593c`, `b3080c5`, `3047725`, `00ec1d2`, `8a60576`, `9654f9e`,
  `66629f5`, `2a42e08`, `3d2527c`). Reviewers' scratch scripts read before they run; credential
  printers, headersHelper mode, forge writes over curl/wget/httpie and `install.sh` runs refused; the
  protect scan expands variables, braces, globs, `cd`/`CDPATH` and output options, treats unresolvable
  expansions as suspect, and never fails open past the brace cap; every MCP tool outside a non-web
  list taints memory writes.
- **Round 2, settings and installer** (`24aeb01`, `c06fb33`, `e262e16`, `4d3c6a8`, `01a0c16`,
  `393b780`, `2c5284f`, `8b39815`, `6bb2ce5`). `failIfUnavailable`; MCP caches out of the sandbox's
  reach (`STACK_CACHE`); duckdb/jupyter/`magg_enable_server` ask; manifest paths checked; symlinked
  scope dirs never pruned, written through only with `--write-through-links`; private work dir; drift
  check; shipped commit shown; pinned LSP installs.
- **magg** (`bb77d58`, `17fdd46`). `ros_*`, `qiskit_*` and `docspace_*` ask at every call; every
  catalog prefix has exactly one allow or ask rule (test).
- **god-coder** (`7292272`). `GOD_AFTER_NINJA` (default 1): a god-coder spawn needs a finished
  ninja-coder of the session; god-coder flow tests.
- **Round 3** (`b93b557`, `c9ef24b`, `693296f`, `275eead`, `b7a075b`, `7e8386b`, `47acb92`,
  `1e1cd82`, `80bc1dd`, `9aeec09`, `e0b5544`). Web taint follows reports, messages and spawn
  prompts; sandbox caches and the git credential reset moved to a SessionStart `CLAUDE_ENV_FILE` for
  sandboxed Bash only, `allowWrite` reduced to `~/.cache/claude-sandbox` (upgrades retract the old
  settings); the supply diff covers everything shipped and asks on a terminal (`--yes`); the guard
  state dir renders from `XDG_STATE_HOME`; `--restore` keeps the current entry where it skips a link;
  `--dry-run` refuses like the real run; file links inside a symlinked dir are kept; `doctor.sh`
  reports GitHub credentials by presence; read-only reviewers treat a project under `/tmp` as the
  project (118 tests had failed from a `/private/tmp` checkout; 0 now); `~/.config/git/credentials`
  denied.
- **Round 4** (`df21992`, `cfa9ee7`). Without a terminal on stdin/stderr the supply question goes to
  `/dev/tty`; with no terminal at all a changed stack stops with exit 1 unless `--yes` (R4-1). A
  failed session-env hook exits 2 with a hook error, is recorded in `session-env.json`, and shows in
  the status line and `doctor.sh` (R4-2). The smoke test re-runs itself without a controlling terminal.
- **Docs** (`bbe6027`, `a0d9b4c`, `c27ff51`, `c1de9f2`, `f8124cc`, and this commit): CONFIG.md §7
  and this README describe the sandbox as configured but not live-verified, the least-privilege
  GitHub setup, the residual risks (round 4 included) and the live checks.
- **Tests** at `cfa9ee7`: pytest 2401 passed; `install_smoke.sh` 244 passed, 0 failed (2400 and
  242 at `e0b5544`, also from a `/private/tmp` checkout); `agent_guard.py --self-test` ok;
  `lint_agents.py` ok.

### 2026-09-29 — Tightened prompts, security hardening, 15 new skills, prune-by-default installer, no duplicates

Commits `eb2de04..1d7b983` on `main` (plus this README). Found by a security audit (verdict: fail),
a skills-gap review and a prompt review; every fix has a test.

- **Prompts** (`eb2de04`, `a56d4d0`, `fb095d8`). Agent bodies 14% shorter; descriptions name who
  takes the adjacent work; BlackCat's catalogue replaced by a routing table. Rules gained the
  untrusted-content rule, consent only via `NEXT: ASK USER` → AskUserQuestion on the main thread, the
  ban on forge writes by any channel, the no-in-place-edits rule and the full protected-path list.
  browser-operator removed from the spawn rows of researcher (and researcher-copy), ml-, dl-, llm- and
  cuda-engineer.
- **Skills** (`2c49198`, `c3d427c`, `5937ec3`). 15 new skills (78 → 93): bayesian-modeling,
  causal-inference, ci-cd-pipelines, container-images, cpp-engineering, dataframes-duckdb,
  distributed-training, frontend-frameworks, model-export, shell-scripting, tabular-ml,
  terraform-opentofu, time-series-forecasting, ui-design-systems, web-accessibility. Overlapping
  triggers deduplicated and scopes split; mcp-server-dev folded into mcp-server-craft; agents' `## Skills`
  lines name the new ones. `skillListingBudgetFraction` 0.01 → 0.012.
- **Security** (`e95161c`, `b08c61e`, `6466f24`, `ecc5932`, `b935f8a`, `695fbc4`). libdocs and
  image-studio SSRF hardening (C5, C9); hash-locked venvs with a 7-day cooldown (C7); protected paths
  extended to agents/, rules/, mcp/, magg/, skills/, CLAUDE.md and backups, with a Bash-level scan
  covering deletes, renames, mode changes and interpreter one-liners (C1); the inverted `--reveal`
  rule fixed (C2); sandbox block with a strict network allowlist (C3); credential files Read-denied
  (C8); read-only reviewers enforced by the hook (T2); web-reading agents can't write neural-memory
  (T3); `CronCreate` and `RemoteTrigger` are ask rules (P3); `GITHUB_TOKEN` no longer exported and
  forge tokens denied to sandboxed commands (C6).
- **Installer** (`52c0059`, `1d7b983`). Stage, validate, back up, apply. Prune by default
  (`--no-prune` opts out), manifest with sha256; `--dry-run`, `--restore [DIR]`,
  `--print-managed-settings`; backups moved out of the config dir to
  `~/.local/state/claude-agent-stack-backups` (C4); plugin duplicates and mcp-server-dev disabled by
  default (`--keep-plugin-duplicates`); uv, magg, huetension and the After Effects MCP pinned (C7).
  CONFIG.md §7 documents it, with the residual risks.
- **Tests.** `test_no_duplicates.py`, `test_protected_paths.py` and `test_readonly_agents.py` pin the
  new guarantees; `install_smoke.sh` 214 passed (dry run, restore round trips, `--no-prune`, a drifted
  config); pytest 1164 passed.
- **README** rewritten for this configuration; the previous one follows verbatim.

### Previous configuration (README as of e06af75)

The README as it stood at `e06af75`, verbatim; only its headings are demoted. Counts, flags, paths and
caps in it describe that revision: 78 skills, opt-in `--dedupe-plugins`, backups in
`~/.claude/backup-*`, `GITHUB_TOKEN` exported, no sandbox. Its links point to the current sections.

<!-- markdownlint-disable MD024 MD032 MD033 MD036 MD038 -->

<details>
<summary>Show the previous README</summary>

#### Claude Code multi-agent stack (README as of e06af75)

BlackCat, the dispatcher on the main thread, 36 specialists (37 agent files), 78 on-demand skills, short global
rules, a policy hook and MCP servers that start and stop with the agents that use them. Built
for Claude Code **2.1.271 or later** and checked against the 2.1.283 docs (26 Sep 2026). macOS only
(Apple Silicon first). It runs in the terminal and in the apps that run Claude Code with your
settings: Claude Desktop's Code tab, Conductor, VS Code, Zed, Nimbalyst (see [Apps](#apps)).

#### Install

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
  - Two models only, Opus 5.5 and Sonnet 5.5: every agent file pins `claude-opus-5-5` or
    `claude-sonnet-5-5`, and Claude Code's small-model slot — background tasks such as session titles
    and WebFetch page summaries — runs on Sonnet 5.5 too: the env key `ANTHROPIC_DEFAULT_HAIKU_MODEL`
    (Claude Code's name for that slot) is set to `claude-sonnet-5-5`, and any other value you had there
    is replaced. One exception: an app that routes models itself sets
    `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`, and Claude Code then ignores that key in settings files.
    Claude Desktop can be such an app: see step 3 of [Claude Desktop, step by step](#claude-desktop-step-by-step).
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

#### What goes where

| Path | What |
|---|---|
| `~/.claude/rules/claude-agent-stack.md` | Global rules every agent loads (short on purpose). `~/.claude/CLAUDE.md` stays yours |
| `~/.claude/settings.json` | `"agent": "blackcat"`, auto-compact on with a **400K** window, depth 4, caps, permissions, hooks, status line (merged) |
| `~/.claude/agents/*.md` | 37 agent definitions, plus `researcher-copy.md` and `coder-copy.md` rendered from their base files |
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

#### How your requirements are implemented

| Requirement | Mechanism |
|---|---|
| Subagent depth 4 | `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4`: BlackCat → L1 → L2 → L3 → L4. L4 cannot spawn. The hook also tracks depth (it reads the same variable), so an L4 agent can't slip through. The rules add *when* to spawn: only for a missing capability, substantial parallel parts or independent verification — never pass-through or "just in case", and deeper than L2 only for a missing capability or a check. |
| One agent → several subagents concurrently | Interactive sessions run subagents in the background, and BlackCat's children always do (in the Agent SDK apps too: the hook drops its `run_in_background: false`). An agent sends independent `Agent` calls in **one message** and they run in parallel. The results come back as task notifications. Caps (listed with their numbers only here and in [Knobs](#knobs)): 3 running children per agent (`STACK_MAX_FANOUT`), raised by type through `STACK_MAX_FANOUT_BY_TYPE` for the agents that coordinate or offload (orchestrator 10, god-coder and main-coder 6, ninja-coder 5, researcher 4, planner 8), 2 live copies per copy type (`STACK_MAX_SELF_FANOUT`), 8 BlackCat dispatches per prompt, all in one burst, and 12 BlackCat tool calls per prompt (`BLACKCAT_MAX_DISPATCH`, `BLACKCAT_MAX_STEPS`), 32 subagents running at once in a session (`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`). On top of these come the context-token budgets per prompt and per session (`STACK_PROMPT_CTX_BUDGET`, `STACK_SESSION_CTX_BUDGET`) and the MCP call cap per subagent run (`STACK_MAX_MCP_CALLS`); their values and exact meaning are in [Knobs](#knobs). |
| subagent1 → subagent1 where it makes sense | researcher and coder, whose parts are most often independent, launch copies of themselves as their own agent types, `researcher-copy` and `coder-copy`: the installer renders them from the base file (same tools, model and `maxTurns`), and their policy rows list neither the base nor any copy, so a copy of a copy is a plain policy denial. How many copies of a type run at once is capped by `STACK_MAX_SELF_FANOUT` (row above). Every other agent does parallel parts itself or hands them to another specialist: in the transcripts, copy-of-copy chains were about 10% of all tokens. |
| Auto-compact on, window 400K | `"autoCompactEnabled": true`, `"autoCompactWindow": 400000`. Compaction fires a little before the window is full: a little before 400K (the window minus an output reserve and a safety buffer). Subagents compact with the same logic. The installer strips env overrides that would defeat it, `/stack-doctor` warns about settings or shell exports that do (`CLAUDE_AUTOCOMPACT_PCT_OVERRIDE`, `CLAUDE_CODE_BLOCKING_LIMIT_OVERRIDE`, …), and the status line shows how close the next compaction is. |
| More agents for every Claude feature | Ten new agents (bold in the [Agents](#agents) table): ml-engineer, dl-engineer, llm-engineer, data-scientist, quantum-engineer, robotics-engineer, cg-artist, browser-operator (Claude in Chrome + Playwright), claude-code-engineer (skills, agents, hooks, plugins, settings, workflows) and ninja-coder (engineer-mathematician between main-coder and god-coder), on top of the existing 26: 36 in all (senior-coder is now main-coder). BlackCat also runs the main-thread-only features: dynamic workflows, scheduled tasks and routines, push notifications, file hand-off. |
| The same setup in Claude Desktop and Conductor | Both run Claude Code with your user settings, so a Code-tab session or a Conductor chat starts as BlackCat with every agent, skill, hook, rule and MCP server, and auto-compacts at 400K. Checked against Conductor 0.87.5 on your Mac and by replaying its options through the Agent SDK. Pick Sonnet 5.5 and medium effort there for BlackCat chats; BlackCat's children always run in the background, so the app never blocks on one; see [Apps](#apps) for the differences. |
| Skills on demand, not tied to agents | Every agent has the Skill tool and sees every skill's description; it loads the ones whose description matches its task, and only then does a skill's body enter its context. No agent preloads a skill and no skill names an agent: a description says when to load it, never who. One `Skill` allow rule pre-approves them all, including skills you or a plugin add later, so background agents never stop at a prompt. 78 skills cover the work the agents do: engineering practice (Python, Rust, TypeScript, JVM, Julia, Haskell, CMake/Ninja, IDEs), performance, apps, systems, databases, mathematics and physics, ML/LLM and data, image-model engineering, robotics, LLM applications, research and writing, design, image and print, 3D, video. `tests/lint_agents.py` keeps it that way. |
| MCP servers on demand, auto on/off | See [MCP servers](#mcp-servers): agent-scoped servers start and stop with their agent, remote ones connect on first use, every schema stays deferred until needed, and rare ones are mounted and unmounted by mcp-broker. |
| Deep reasoning where it counts | Calibrated for the 5.5 models, whose `medium` default matches or beats Opus 5 at `high` and which think more per turn at a given level (Claude Code's model-config page): `max` only for ninja-coder and god-coder (the hardest problems, worked through without you; `max` overthinks on routine work); `xhigh` where one deep answer or a large codebase is the job (planner, mathematician, security-auditor, main-coder); `high` for work that must verify itself or where edge cases are likely (orchestrator, plan-reviewer, code-reviewer, researcher, the ML/quantum/robotics/platform engineers, data-scientist, designer, claude-code-engineer, and the Sonnet verifier, data- and devops-engineer); `medium` for clear-scope execution and tool- or GUI-driven loops (BlackCat, coder, writer, image-director, frontend-engineer, motion-designer, cg-artist, doc-specialist, browser-operator, mcp-broker); `low` for lookups (scout, oracle, claude-code-guide). |
| Context that doesn't bloat | Measured with Claude Code 2.1.283 before this revision: a session started at about 42K tokens (plain Claude Code: about 34K) — the skill list about 9K, the agent list about 3.6K, the rules about 2K — and each subagent at about 40K, which prompt caching reuses after its first request. The skill descriptions are now half as long (about 15K characters) and the rules about 6% shorter; re-measure with `/context`. Auto-compaction fires a little before 400K. Skill bodies, MCP tool schemas and memories load only when used. |
| Images: SVG for graphics, raster for photos, edits for the rest | `image-studio` (image-director, designer): one tool per job, the model of each set in `stack.env` — `IMAGE_STUDIO_SVG_MODEL`, `IMAGE_STUDIO_IMAGE_MODEL`, `IMAGE_STUDIO_EDIT_MODEL` — and looked up in its provider's model catalog before every paid call, so an option or input the model lacks is refused for free. `generate_svg` — through OpenRouter (`OPENROUTER_API_KEY`), default Recraft V4.1 Pro Vector (`recraft/recraft-v4.1-pro-vector`, $0.30 an image, palette through Recraft's controls, one reference image); a model without SVG output is refused, and anything that isn't SVG is never saved. `generate_image` — through Opper (`OPPER_API_KEY`), default GPT Image 2.5 Sunburst (`openai/gpt-image-2.5-sunburst`): 1-4 images, quality low to max (about $0.006 to $0.21 at 1024x1024), 1K/2K/4K, transparency, up to 8 references; `collect_image` fetches one still rendering. `edit_image` — through OpenRouter, default Riverflow V2.5 Pro (`sourceful/riverflow-v2.5-pro`, $0.13 at 1K to $0.17 at 4K) with 1-10 input images. A missing key disables only the tools that need it; `/stack-doctor` shows the models in use and checks them. The rules keep logos, icons, illustrations and graphic design in SVG and allow no other image API. |
| Uploaded images under 1920 px | The image-limit hook (see [Enforced behaviours](#enforced-behaviours-hooks)): what agents read and what they upload through the browser tools; the image tools scale their own inputs in memory; the rules cover curl and scripts. |
| Squeeze context further | context-mode (researcher, doc-specialist): pages and long documents go into a local search index and only the passages asked for enter the context. neural-memory (12 agents): what earlier sessions settled is recalled on demand instead of re-derived, with nothing preloaded. See [Context economy](#context-economy-context-mode-and-neural-memory). |
| ninja-coder and god-coder at "ultra-code" effort | `claude-ninja` and `claude-god` start them as the main thread at ultracode: `xhigh` plus dynamic workflows, workflow launches pre-approved in those sessions only. That is the only place ultracode runs. Subagents can't run workflows, and `effort: ultracode` in an agent file is ignored: checked with the CLI, such a subagent ran at the calling session's `low`. Dispatched by BlackCat or another agent, both run at `max`, the deepest per-message level. |

#### Agents

Models are two pinned IDs and nothing else: `claude-opus-5-5` (Opus 5.5, Claude Code 2.1.280 or
later) and `claude-sonnet-5-5` (Sonnet 5.5, 2.1.284 or later); `tests/lint_agents.py` rejects any
other model. Opus 5.5 goes where judgment is the product (planning, review, mathematics, research
synthesis, hard or unfamiliar code, ML, design); Sonnet 5.5 where the work is bounded execution,
lookups or driving tools (BlackCat, coder, verifier, data-/devops-engineer, doc-specialist,
browser-operator, mcp-broker, scout, claude-code-guide). Both run with a native 1M window, so no
`[1m]` pins are needed. The model, effort and `maxTurns` come from each agent file: per-call `model`
overrides are stripped by the hook. `maxTurns` is a runaway bound by task type, set from the
transcripts (about 1.5–2× the 90th percentile of turns per run, measured on 2026-09-29): 12–30 for
lookups (oracle, scout, claude-code-guide), 80–120 for bounded analysis and single artifacts
(planner, plan-reviewer, image-director, mcp-broker, mathematician, code-reviewer,
security-auditor, writer, doc-specialist, browser-operator), 150–190 for builders and long
pipelines, 300 for main-/ninja-coder, 350 for god-coder and 250 for the orchestrator (larger
codebases and jobs; most of the orchestrator's turns are cheap waits for children); `tests/lint_agents.py` enforces ≤ 350 and < 200. One turn is one model response (parallel tool
calls count once). An agent that hits it stops without a report of its own; Claude Code returns a
"stopped at its N-turn limit" note, and a SendMessage resume continues with a fresh N turns
(both probed with `claude -p`, 2.1.283). BlackCat has no `maxTurns`: it doesn't bind a main thread
(probed), so the hook's `BLACKCAT_MAX_STEPS` is its cap.

| Agent | Model · effort | For | Agent-scoped MCP | Shared MCP | Extras |
|---|---|---|---|---|---|
| **blackcat** — BlackCat (main thread) | Sonnet 5.5 · session level (choose medium) | Classifies and dispatches (one parallel burst of up to 8 background agents per prompt, within its dispatch and step caps: [Knobs](#knobs)); relays results; Read, Grep and Glob only for quick checks (a file exists, a child's claimed diff) | — | — | Workflows, cron/loop, routines, push, file hand-off |
| orchestrator | Opus 5.5 · high | Multi-step / multi-domain work; ≤ 10 tasks per job (a DAG; soft cap about 12 spawns); children running at once capped by `STACK_MAX_FANOUT_BY_TYPE` ([Knobs](#knobs)) | neural-memory | — | cache 1h |
| planner | Opus 5.5 · xhigh | How to solve it: options, plan, owners, verification | libdocs | exa, jina | |
| plan-reviewer | Opus 5.5 · high | Critique of a plan before execution | libdocs | exa, jina | |
| oracle | Opus 5.5 · low | Timeless knowledge, no web | — | — | |
| scout | Sonnet 5.5 · low | One current fact in ≤ 3 searches | — | exa, jina | |
| explore | Sonnet 5.5 · low | Read-only codebase search (Read, Grep, Glob, LSP); skips CLAUDE.md like the built-in it replaces | — | — | |
| researcher | Opus 5.5 · high | Cited multi-source research; can crawl | spider, context-mode, neural-memory | exa, jina, huggingface | copies, cache 1h |
| mathematician | Opus 5.5 · xhigh | Proofs, derivations, symbolic/numeric computation | neural-memory | jina, wolfram | sympy/mpmath/scipy venv |
| **quantum-engineer** | Opus 5.5 · high | Quantum computing and quantum-physics code: circuits, QuTiP, tensor networks, error correction, IBM Quantum runs | libdocs, neural-memory | exa, jina, wolfram | cache 1h; qiskit-runtime via the catalog |
| writer | Opus 5.5 · medium | Articles, blog (Markdown + LaTeX/Mermaid), emails, PT-PT/EN | — | jina | |
| doc-specialist | Sonnet 5.5 · medium | docx/xlsx/pptx/pdf read, analyze, create | markitdown, context-mode | — | screen (ONLYOFFICE) |
| image-director | Opus 5.5 · medium | Image generation and editing: SVG, photos and rasters, edits and composites (defaults: Recraft V4.1 Pro Vector and Riverflow V2.5 Pro through OpenRouter, GPT Image 2.5 Sunburst through Opper) | image-studio | jina | |
| designer | Opus 5.5 · high | Vector, brand, print, UI visuals, color; generated SVG art, photos and edits | image-studio, illustrator¹, huetension | jina | screen |
| motion-designer | Opus 5.5 · medium | After Effects, Premiere, motion | after-effects¹, premiere¹ | — | screen |
| **cg-artist** | Opus 5.5 · medium | 3D: Blender, ZBrush, Substance 3D Painter, Houdini FX, 3D printing | blender (MCP for Blender), libdocs | jina | screen; Houdini via hython (no MCP server exists) |
| coder | Sonnet 5.5 · medium | Small/medium code, offloaded sub-tasks | libdocs | exa | copies |
| main-coder (was senior-coder) | Opus 5.5 · xhigh | Large codebases, architecture, hard bugs | libdocs, neural-memory | exa, jina | cache 1h |
| **ninja-coder** | **Opus 5.5 · max** | Hardest code where it meets mathematics: novel algorithms, proofs, complexity, numerics, kernels | libdocs, neural-memory | exa, jina, wolfram | cache 1h, workflows |
| god-coder | **Opus 5.5 · max** | Last resort after ninja-coder; spawned only by the orchestrator, once per session | libdocs, neural-memory | exa, jina, wolfram | cache 1h, workflows |
| frontend-engineer | Opus 5.5 · medium | Web front-end, a11y, verified in a headless browser | libdocs, playwright | exa | |
| devops-engineer | Sonnet 5.5 · high | CI/CD, containers, k8s, IaC, deploys (dry-run first) | libdocs | exa | |
| data-engineer | Sonnet 5.5 · high | SQL, schemas, pipelines, dataframes | libdocs | exa | |
| **data-scientist** | Opus 5.5 · high | EDA, tests, A/B + power, regression, causal, forecasting, reports | libdocs, neural-memory | exa, jina, huggingface | cache 1h |
| **ml-engineer** | Opus 5.5 · high | Tabular/time-series/classic ML, validation, MLOps | libdocs, neural-memory | exa, jina, huggingface, wandb | cache 1h |
| **dl-engineer** | Opus 5.5 · high | Architectures, training loops (PyTorch/JAX/MLX), ablations, NaNs | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h |
| **llm-engineer** | Opus 5.5 · high | Local inference (mlx-lm, oMLX), quantization, fine-tuning, evals, RAG, agents/MCP | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h |
| mlx-engineer | Opus 5.5 · high | Apple Silicon performance, Metal kernels, ports to MLX | libdocs | exa, jina | memory |
| cuda-engineer | Opus 5.5 · high | NVIDIA performance, CUDA/Triton, NCCL, vLLM; remote GPU hosts over SSH, remote Jupyter, Kaggle (CLI; web UIs via browser-operator) | libdocs | exa, jina | memory |
| **robotics-engineer** | Opus 5.5 · high | ROS 2, kinematics and control, SLAM, simulation, robot learning, hardware bring-up | libdocs, neural-memory | exa, jina, huggingface, wandb | memory, cache 1h; ros via the catalog |
| code-reviewer | Opus 5.5 · high | Review of diffs/PRs (read-only) | libdocs | — | |
| verifier | Sonnet 5.5 · high | Runs tests, reproduces, re-checks facts, tests web UIs and native apps | playwright | exa, jina | screen |
| security-auditor | Opus 5.5 · xhigh | Threat model, exploitable issues (read-only) | — | exa | |
| **browser-operator** | Sonnet 5.5 · medium | Acts on web pages: your logged-in Chrome, or headless Playwright | playwright | claude-in-chrome | |
| mcp-broker | Sonnet 5.5 · medium | Finds, mounts, runs and unmounts MCP servers | magg | — | |
| **claude-code-engineer** | Opus 5.5 · high | Builds Claude Code config: skills, agents, hooks, plugins, settings, workflows | — | — | |
| claude-code-guide | Sonnet 5.5 · low | Questions about Claude Code / API / Agent SDK | — | — | |

**Bold** = added in this revision. ¹ after-effects only once `--with-adobe` has built it.
- **copies**: the agent may spawn its copy type (`researcher-copy`, `coder-copy`), within `STACK_MAX_SELF_FANOUT`;
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
  per model) or `--effort`. For BlackCat, `/effort medium` once in a BlackCat session (Sonnet 5.5's
  default: at `low` it tends to dispatch without asking the clarifying question the prompt needs).
- **Shared MCP**: remote user-scope servers; only agents that list them can call them (see [MCP servers](#mcp-servers) for where their instructions show up).

##### Spawn policy (enforced by the hook)

Claude Code ignores `Agent(a, b)` lists inside subagents, so `agent_guard.py` holds the single
source of truth (`POLICY`). `tests/lint_agents.py` checks that every agent's "May spawn:" sentence
matches it. A missing `subagent_type`, generic, built-in and host-defined types (`general-purpose`,
`claude`, `fork`, `SubAgent`, ...) and every type not in the caller's row are denied (see
[Spawn policy](#spawn-policy) for workflows and forked skills). Resuming a
finished agent with SendMessage follows the same rows (an agent may always resume its own children
and its parent); messages to agents that are still running pass.

Agents of your own (other files in `~/.claude/agents/`) are in no row, so neither BlackCat nor the
stack's agents can spawn them. Run one directly with `claude --agent <name>`, or add it to
`blackcat.md`'s `tools:` line and a `POLICY` row in the repo's `agent_guard.py`, then re-run the
installer.

- **blackcat**: any specialist except god-coder (all dispatches in one burst, within `BLACKCAT_MAX_DISPATCH` and `BLACKCAT_MAX_STEPS`: [Knobs](#knobs)); follow-ups go through SendMessage.
- **orchestrator**: every specialist (copy types excluded); the only agent that may
  spawn god-coder, once per session (`GOD_SPAWNERS`, `GOD_ONCE_PER_SESSION`).
- **Copies**: only researcher and coder, through `researcher-copy` and `coder-copy`; no other row
  lists its own type.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker,
  claude-code-guide, browser-operator, plan-reviewer, image-director, explore.
- **Escalation**: coder → main-coder → ninja-coder → god-coder. ninja-coder takes a problem whose
  core is algorithmic or mathematical, or one main-coder failed twice; god-coder only what
  ninja-coder could not solve, and only through the orchestrator: any other agent returns
  `STATUS: partial` with `NEXT: god-coder` and a dossier, and the orchestrator spends its one
  god-coder spawn of the session (follow-ups resume the same god-coder with SendMessage). Model work goes to ml-/dl-/llm-engineer, and platform performance to
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
| main-coder | coder, explore, scout, verifier, code-reviewer, security-auditor, plan-reviewer, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, claude-code-guide, ninja-coder |
| ninja-coder | main-coder, coder, mathematician, explore, scout, verifier, code-reviewer, security-auditor, researcher, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, mcp-broker, quantum-engineer |
| god-coder | coder, main-coder, ninja-coder, mlx-engineer, cuda-engineer, ml-engineer, dl-engineer, llm-engineer, explore, scout, verifier, code-reviewer, security-auditor, mathematician, researcher |
| mlx-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, ninja-coder |
| cuda-engineer | coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, browser-operator, ninja-coder |
| devops-engineer | coder, explore, scout, verifier, security-auditor, mcp-broker |
| data-engineer | coder, explore, scout, verifier, mathematician, data-scientist, doc-specialist, mcp-broker |
| frontend-engineer | coder, explore, scout, verifier, code-reviewer, designer, image-director, mcp-broker |
| data-scientist | data-engineer, ml-engineer, mathematician, coder, explore, scout, verifier, doc-specialist, writer, mcp-broker |
| ml-engineer | data-scientist, data-engineer, coder, explore, scout, verifier, code-reviewer, mathematician, mcp-broker, browser-operator |
| dl-engineer | mlx-engineer, cuda-engineer, data-engineer, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, browser-operator, ninja-coder |
| llm-engineer | mlx-engineer, cuda-engineer, dl-engineer, data-scientist, coder, explore, scout, researcher, verifier, code-reviewer, mathematician, mcp-broker, claude-code-guide, browser-operator, ninja-coder |
| claude-code-engineer | claude-code-guide, scout, explore, verifier, code-reviewer, mcp-broker |
| quantum-engineer | mathematician, coder, explore, scout, researcher, verifier, code-reviewer, cuda-engineer, mlx-engineer, mcp-broker, ninja-coder |
| robotics-engineer | coder, explore, scout, researcher, verifier, code-reviewer, mathematician, dl-engineer, cuda-engineer, mlx-engineer, cg-artist, mcp-broker, ninja-coder |
| cg-artist | image-director, coder, scout, verifier, mcp-broker |

#### Skills (dynamic)

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

##### Code intelligence (LSP)

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

#### MCP servers

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

##### Context economy: context-mode and neural-memory

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

#### Enforced behaviours (hooks)

| Event | What the hook does |
|---|---|
| PreToolUse `*` (`agent_guard.py budget`) | Enforces the context-token budgets and the MCP call cap (values and what they count: [Knobs](#knobs)), reading token usage from the session's transcripts, subagents included. Over a budget every call is refused except SubagentHandback, TaskStop, AskUserQuestion, ToolSearch loading one of them, and Write/Edit under a `.claude-work/` folder or the session scratchpad; the message says to finish with what the agent has (STATUS: partial). Past its MCP cap a subagent's further `mcp__*` calls are refused while other tools keep working; the main thread is not counted (BlackCat's step cap bounds it). Fails open: a transcript or counter it can't read warns and allows. |
| PreToolUse `Agent` | Checks, in order: spawn policy, depth, the copy rule, fan-out caps (atomic leases) and the BlackCat dispatch window. Lets only the orchestrator spawn god-coder, once per session; takes the god-coder lock and strips a per-call `model`. Drops BlackCat's `run_in_background: false`, so the main thread never blocks on a foreground child (Claude Desktop and the other Agent SDK apps offer that parameter; `BLACKCAT_BACKGROUND`). Denies `isolation: "remote"`, because cloud agents load no hooks. |
| PreToolUse `SendMessage` | Resuming a finished agent follows the spawn policy (the caller's row, or its own child or parent) and counts against its parent's fan-out caps; resuming a finished god-coder takes the god-coder lock. BlackCat's SendMessage counts as one of its steps here, in the same decision as the resume's slot |
| PreToolUse `mcp__computer-use__*` | One agent on the screen at a time |
| PreToolUse local-file MCP tools: context-mode `ctx_index`, markitdown, docling, playwright, chrome-devtools (catalog) | A path or `file:` URI argument is checked against every `Read(...)` deny rule, yours and the project's, with Claude Code's `//abs`, `~/`, `/x` and relative forms. Each argument is read every way the tool might read it: `x:/../..` and `file:/../..` are relative paths to a tool that doesn't parse URIs; `~`, percent-encoding, symlinks and both the session's and the project's directory are tried. A directory that holds a protected path is denied, and `ctx_index` gets no directories at all (it would walk them). Oversized arguments are refused rather than checked, so the hook always answers within its timeout. Claude Code applies those rules to its own tools, not to MCP arguments. |
| PreToolUse `Bash\|Monitor\|PowerShell` (every call: no `if` filter) | The Git rule's **never push**: denies `git push`, `send-pack`, `lfs push`, `subtree push` and `svn dcommit`, and every forge write through `gh`, `tea` or `fj` (create, merge, review, comment, close, release, fork, `gh api`/`tea api` with a write method; read-only `view`, `list`, `checks`, `diff`, `checkout` pass), in the forms the deny rules miss: `git -C dir push`, `/usr/bin/git push`, `git 'push'`, `bash -c 'git push'`, `sh -c`, `zsh -c`, `eval`, `$(...)` and backticks, `$'\x67it'`, line continuations, heredocs, here-strings and pipes into a shell, `ssh host '...'`, `python -c`/`node -e` code that starts a process, and the places git itself runs a command (`-c alias.x=...`, `git config alias.x`, `core.editor`, `GIT_EDITOR=`, `submodule foreach`, `rebase --exec`, `bisect run`). A command decided only at run time (`git $X`, `g${X}it`, `$G push`, `xargs git`, `echo ... \| base64 -d \| sh`, `pwsh -EncodedCommand`) is refused, and so is a command the guard cannot finish checking (a parser error, nesting deeper than 8 levels, more than 64 heredocs on one line, more than 8 s of work). The command is parsed as bash/zsh would (quotes, comments, newlines, arithmetic); a heredoc body is code only when the command that owns it is a shell, `eval`, `ssh` or `source /dev/stdin`, so a commit message that mentions a push passes. PowerShell syntax is modelled only as far as `pwsh -Command`, `iex`, `Start-Process` and backtick escapes. It has no `if` filter because Claude Code's `if: "Bash(git *)"` does not fire for `bash -c`, `eval` or `/usr/bin/git` (tested on 2.1.283); commands that name no git/gh/tea/fj return at once (~40 ms a call, mostly Python start-up). Not switched off by `STACK_POLICY=off`. Best effort: an alias or function defined in an earlier command, a script file or download, a variable holding the whole command, or text assembled by string operations is out of its sight. |
| PostToolUse `Agent\|TaskStop`, SubagentStart/Stop, StopFailure | Registry of who spawned whom at which depth. Liveness: a stopped, failed or TaskStop-ed agent releases its locks. A parent that waits on its children still counts as alive while any child is. |
| PostToolUseFailure / PermissionDenied | Roll back leases and the BlackCat marker |
| UserPromptSubmit, SessionStart (startup/resume/fork) | Reset per-prompt BlackCat markers; clear stale locks; prune old state |
| PostToolUse `Read\|mcp__*`, PreToolUse `mcp__*` (image limit) | Every image an agent reads (Read, screenshots and other MCP image results) is re-encoded to at most 1919 px per side before the model sees it, and kept under the API's 5 MB image cap (JPEG at lower quality if needed; else left as it was). Local images that the browser upload tools (Playwright, Claude in Chrome) send off the machine are swapped for downscaled copies in a `.downscaled/` folder next to the original, which git ignores, under the same name — so the tools' own folder checks still pass. A copy is reused while it carries its original's modification time; nothing is ever deleted (remove `.downscaled/` folders whenever you like). JPEG stays JPEG, PNG stays PNG. The one refusal: an oversized image the hook can't copy (a symlink, an animated image, a folder it can't write) is refused with the `sips` command to make a copy. Otherwise it never blocks a call. Uses macOS `sips`. |

BlackCat's own frontmatter hook allows only its delegation tools plus Read, Grep and Glob (quick
checks, never investigation), and at most `BLACKCAT_MAX_STEPS` tool calls per prompt, Agent dispatches included. Every hook command uses an **absolute interpreter** chosen at install time. A bare
`python3` broken by a pyenv/asdf shim would make every hook fail to start, which Claude Code treats
as "allow". `/stack-doctor` runs the real hook commands on calls that must be denied, to prove the
gate is closed, and checks that the budget hook is wired and still reads usage from real
transcripts (`agent_guard.py --check-budget`).

If the hook itself errors it denies the call (fail closed). The model gets a neutral reason, while
the escape hatch (`STACK_POLICY=off`) is shown only to you.

##### Knobs

`settings.json` → `env`. Values you change are kept on re-install, except the owned
ones (marked ●): the installer resets those to the stack's value, since the caps and budgets are
guarantees rather than preferences. To change an owned knob, change it in the repo's
`dot-claude/settings.json` and re-run the installer.

| Knob | Default | Meaning |
|---|---|---|
| `BLACKCAT_MAX_DISPATCH` ● / `BLACKCAT_DISPATCH_WINDOW_S` | 8 / 120 | BlackCat Agent calls per prompt, all within this many seconds of the first (0 = no window; 120 s leaves room for 8 long briefs streamed in one message) |
| `BLACKCAT_MAX_STEPS` ● | 12 | BlackCat tool calls per prompt, Agent dispatches included (8 dispatches plus a question, a tool load and a quick check) |
| `STACK_MAX_FANOUT` ● | 3 | Running + starting children per agent, any type (0 = no cap) |
| `STACK_MAX_FANOUT_BY_TYPE` ● | `orchestrator=10,god-coder=6,main-coder=6,ninja-coder=5,researcher=4,planner=8,plan-reviewer=8` | Per-type overrides of `STACK_MAX_FANOUT` (the same table is `DEFAULT_FANOUT_BY_TYPE` in `agent_guard.py`): the orchestrator runs a job of up to 10 tasks at once; god- and main-coder a module per child on a large codebase plus a reviewer or verifier; ninja-coder keeps the mathematical core itself; researcher its 2 copies plus 2 lookups |
| `STACK_MAX_SELF_FANOUT` ● | 2 | Copy agents (`researcher-copy`, `coder-copy`) of one type running at once, session-wide |
| `STACK_PROMPT_CTX_BUDGET` ● / `STACK_SESSION_CTX_BUDGET` ● | 100000000 / 666000000 | Context tokens (input + cache writes + cache reads, all agents) per human prompt / per session; past it the hook denies work tools and tells the agent to finish with what it has |
| `STACK_MAX_MCP_CALLS` ● | 64 | MCP tool calls (`mcp__*`) per subagent per prompt (a spawn or a resume starts a new count), capped lower by the agent's own `maxTurns` (scout and claude-code-guide 30, oracle 12); past it the hook denies MCP calls only (0 = off) |
| `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` ● | 32 | Claude Code's own cap on subagents running in one session (20 by default; BlackCat's 8 plus an orchestrator's 10 plus their children would hit 20 mid-job, and a refused spawn is not retried) |
| `STACK_FANOUT_IDLE_S` | 600 | A background child whose whole subtree is silent this long stops counting |
| `STACK_LEASE_TTL_S` | 21600 | Ceiling on a spawn lease whose Agent call never reported back |
| `STACK_RESUME_TTL_S` | 120 | A resume reservation (SendMessage to a finished agent) whose agent never started stops counting after this many seconds |
| `GOD_SPAWNERS` | `orchestrator` | Parent types allowed to spawn god-coder (comma list; `main` = a main thread without an agent type) |
| `GOD_ONCE_PER_SESSION` | 1 | One god-coder spawn per session; a failed or refused spawn frees it; SendMessage resumes of that god-coder still pass (0 = only the one-at-a-time lock) |
| `GOD_IDLE_S` / `GOD_PENDING_TTL_S` / `GOD_LOCK_TTL_S` | 1800 / 120 / 21600 | god-coder lock: idle holder, unconfirmed lease, hard ceiling |
| `SCREEN_LOCK_TTL_S` | 900 | Screen lock expiry |
| `STRIP_AGENT_MODEL` | 1 | Remove per-call `model` |
| `BLACKCAT_BACKGROUND` | 1 | Drop `run_in_background: false` from BlackCat's Agent calls: its children always run in the background (0 = let it run them in the foreground) |
| `STACK_POLICY` | on | `off` disables every deny and lock (bookkeeping continues) |
| `STACK_GUARD_LOG` | 0 | 1 = log raw hook events to the state dir (debugging); budget mode, which sees every tool call, logs only the tool name and ids, never the tool input |
| `STACK_IMAGE_MAX_PX` | 1919 | Longest side of any image an agent reads or uploads (0 = off) |
| `STACK_IMAGE_UPLOAD_TOOLS` | — | Regex of more MCP tool names whose image-file arguments get downscaled copies before upload |
| `STACK_IMAGE_MAX_B64` | 4500000 | Most base64 characters of one image sent to the model (the API refuses a 5 MB image) |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | `claude-sonnet-5-5` | Claude Code's small-model slot (background tasks such as session titles and WebFetch summaries): Sonnet 5.5, so every call the stack makes runs on Opus 5.5 or Sonnet 5.5 (Claude Desktop: [step 3](#claude-desktop-step-by-step)) |
| `CLAUDE_CODE_MAX_WEB_SEARCHES_PER_SESSION` | 400 | Web searches per session, all agents together (Claude Code default 200) |
| `MCP_TIMEOUT`, `MAX_MCP_OUTPUT_TOKENS` | 60000, 25000 | MCP start-up timeout (first `npx`/`uvx` downloads), tool output cap |

#### Status line

`bin/statusline.py` renders a line like
`blackcat · Sonnet 5.5 · low · ctx 156K/400K ▓▓▓░░░░░ · 5h 23% · 7d 41% · cache 91%`.
- The **ctx** bar counts the main conversation's tokens against the 400K auto-compact window, so you
  see the next compaction coming (it fires a little before).
- 5h/7d are your plan's rate-limit windows (Pro/Max).
- It is set only if you had no status line. Remove `statusLine` from `settings.json` to turn it off.

#### ML setup (`--with-ml`)

`~/.claude/venvs/ml` holds numpy/scipy/pandas/polars, scikit-learn, statsmodels, XGBoost, LightGBM,
PyTorch, Transformers, Datasets, Accelerate, PEFT and safetensors.
- **Apple Silicon**: also `mlx` and `mlx-lm[evaluate]` (so `mlx_lm.evaluate` works).

The ML agents use the project's own environment first, this venv second, and never the system Python.

Local inference stays MLX-native on the Mac (mlx-lm; oMLX as the local OpenAI/Anthropic-compatible
endpoint). CUDA work runs only on an NVIDIA host you name.

#### Apps

Every app below runs Claude Code with your user settings, so it starts as BlackCat with the whole
stack: the 36 agents, the 78 skills, the hooks, the rules, your MCP servers and auto-compaction at
400K. Checked on 27 Sep 2026 against each app's documentation or code; for Conductor also against
the version on your Mac (0.87.5) and by running the stack through the Agent SDK with Conductor's own
options (see [How the apps were checked](#how-the-apps-were-checked)).

| App | Runs | What to set | Limits |
|---|---|---|---|
| Terminal (Ghostty, Terminal) | your `claude` | once: `/effort medium` | none: the reference, and the only place for `claude-ninja` / `claude-god` |
| **Claude Desktop, Code tab** (Local) | Claude Code 2.1.281, built into Desktop 2.9939.2 | model **Sonnet 5.5**, effort **medium** for BlackCat sessions | no agent teams; panel commands such as `/permissions` don't open; Desktop reads only `PATH` from your shell profile (the stack needs nothing else) |
| **Conductor** 0.87.5 | Claude Code 2.1.280, bundled | model **Sonnet 5.5**, thinking **medium**, Ultracode **off** for BlackCat chats | always bypass-permissions (your deny rules and the guard still apply); Conductor's own tools (diff comments, terminal reading) aren't in the agents' tool lists |
| VS Code / Cursor extension | its own copy of Claude Code, same version as the extension | nothing | a subset of slash commands |
| JetBrains plugin | your `claude`, in the IDE terminal | nothing | none |
| Zed (Claude Agent) | Claude Code 2.1.280 through the ACP adapter | nothing | a few slash commands hidden; Zed's Terminal Threads run your own `claude` |
| Nimbalyst | Claude Agent: Claude Code 2.1.280; or the "Claude Code CLI" provider: your own `claude` in a pane | the 1M model row with the CLI provider (else 200K) | its effort control sets `CLAUDE_CODE_EFFORT_LEVEL`, which overrides every agent's own effort (tested); one process per turn |
| AionUI | your `claude`, in print mode | no AionUI MCP servers in Claude chats | enabling any AionUI MCP server passes `--strict-mcp-config`, which drops your MCP servers and the agents' own |

What differs from the terminal in these apps (Desktop, Conductor, Nimbalyst, VS Code and Zed all run
Claude Code through the Agent SDK):
- **Model and effort** come from the app's pickers and set the main thread: BlackCat takes the model
  you pick, not the Sonnet 5.5 in its file. Subagents keep their own model and effort.
- **BlackCat's children run in the background; nested children return directly.** These apps give
  the Agent tool a `run_in_background` parameter (fork mode is off in the SDK). A foreground child
  blocks the main thread for its whole run: the app shows nothing until it ends, and the next
  dispatch waits (the "hang" seen in Desktop 2.1.284 sessions, whose children's `meta.json` read
  `requestShape: "foreground"`). So BlackCat never asks for the foreground — the hook drops a
  `run_in_background: false` of its (`BLACKCAT_BACKGROUND`) — answers at once, and relays each
  result when its notification arrives. A subagent, which in the SDK doesn't wait for background
  children, passes `false` (the rules); calls sent together still run in parallel.
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

##### Claude Desktop, step by step

1. Install once from Terminal (`./install.sh`), then **restart Claude Desktop**. Open **Code**, choose
   **Local** and your project folder.
2. Set the model to **Sonnet 5.5** and effort to **medium** (Cmd+Shift+E). Each subagent uses the
   model and effort in its own file.
3. **Background model**: in the environment dropdown, hover over **Local**, click the gear and add
   `ANTHROPIC_DEFAULT_HAIKU_MODEL` = `claude-sonnet-5-5`. Desktop can route models itself, and Claude Code
   then ignores that key in `settings.json`, so session titles and WebFetch summaries would stay on
   the small default model; variables set here reach the session directly. Your agents run on their
   pinned Opus 5.5 or Sonnet 5.5 either way.
4. **Keys** need nothing extra: exa/jina/huggingface/wandb get them from `stack.env` through
   `bin/mcp-headers`, image-studio and libdocs read `stack.env` themselves, spider and magg start
   through `bin/with-stack-env`, and every command is an absolute path.
5. **Computer use**: Settings → General → turn it on, then grant Accessibility and Screen Recording.
6. **Check**: send `@oracle what is a monad?`; the subagent pane shows oracle.
7. Use **Customize → Connectors** where the terminal would use `/mcp`. Desktop's Chat tab (not Code)
   has no subagents, hooks or BlackCat.

##### Conductor, step by step

1. Nothing to install in Conductor: it reads `~/.claude` (settings, agents, skills, hooks, rules) and
   `~/.claude.json` (MCP servers). Its bundled Claude Code (2.1.280) is recent enough; if you switch
   it to your own `claude` (Settings → Storage), keep that at 2.1.271 or later.
2. For each chat: model **Sonnet 5.5**, thinking **medium**, Ultracode **off** (with Ultracode on, the
   BlackCat itself would start dynamic workflows).
3. Work runs in the workspace's git worktree under `~/conductor/workspaces/`. The agents' scratch
   folder `.claude-work/` is excluded from git there too.
4. For ninja-coder or god-coder at ultracode, use `claude-ninja` / `claude-god` in a terminal (Conductor
   has no way to pick the main-thread agent); dispatched from a Conductor chat they run at `max`.

##### How the apps were checked

- Conductor 0.87.5, read on your Mac: it starts Claude Code 2.1.280 through the Agent SDK with
  `settingSources: ["user", "project", "local"]`, the `claude_code` system prompt,
  `permissionMode: "bypassPermissions"`, the chat's model and effort, AskUserQuestion swapped for its
  own tool, its own MCP server and a `conductor` skill.
- Those options were replayed with Agent SDK 0.3.283 and Claude Code 2.1.283 against a fresh install
  of the stack:
  - the main thread was BlackCat, with its tool list; 33 agents and 61 skills of that revision (plus the built-in
    ones) loaded;
  - hooks fired (SessionStart, UserPromptSubmit, PreToolUse, SubagentStart/Stop, PostToolUse);
  - auto-compaction, with the 800,000-token `autoCompactWindow` that settings.json shipped at the
    time of that run (the stack now ships 400,000): threshold 767,000 (Opus 5.5);
  - a coder subagent ran at its own effort (medium) under a session at low;
  - BlackCat → coder → two coder copies in parallel returned the right SHA-256 digests, and skills
    loaded without a prompt;
  - in plan mode BlackCat handed planning to planner.
- Found on the way, and fixed: an agent whose command was refused (`claude -p`, default mode) reported
  a guessed value; the rules now require reporting the refusal instead.
- Desktop, VS Code, Zed, Nimbalyst and AionUI: their documentation, and the code that starts Claude
  Code (Desktop's app package, the VS Code extension, Zed's adapter, Nimbalyst's and AionUI's source).
- Claude Desktop 2.1.284 transcripts (2026-09-28, `entrypoint: claude-desktop`, auto mode): the Agent
  tool had `run_in_background`, BlackCat passed `false` as the rules then said, and each child ran in
  the foreground (`requestShape: "foreground"` in its `meta.json`) for 5–15 minutes while the app
  showed nothing; the user stopped them. Terminal sessions of the same day launched every child in
  the background and ran siblings in parallel. The guard state showed no denial and no stuck lock:
  the blocking came from the foreground request alone.

#### Using it

- Just talk to it. To force an agent, start with `@designer …` or `@ninja-coder …` (god-coder goes through `@orchestrator …`, once per session, or `claude-god`).
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
- Optional: `/advisor opus` gives the Sonnet and Opus agents an Opus advisor at decision points.
  It is experimental and costs extra.

Smoke tests:
- `@oracle what is a Kan extension?`
- `what's the latest stable Rust version?` (scout)
- `plan how to migrate my Astro blog to MDX` (planner)
- `@researcher compare LoRA, DoRA and QLoRA for a 70B MoE on a 512 GB Mac; split the work` (parallel
  researcher copies)
- `@llm-engineer quantize <model> to ~4.5 bpw with mlx and report Δppl` (loads llm-quantization,
  then llm-evals)
- `@orchestrator … use god-coder twice` (the second god-coder spawn of the session is denied)
- `@ninja-coder find an O(n log n) algorithm for …, prove it, and property-test it against a brute
  force` (derivation, z3/sympy checks, hypothesis tests, verifier)
- `/context` and `/stack-doctor`

#### Security notes

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

#### For maintainers

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

#### Troubleshooting and restore

- **`/stack-doctor` first.** It prints the exact fix for each FAIL.
- **A spawn you expected was denied.** The reason names the rule. For a stuck lock, `/clear` doesn't
  help; restart with `claude --resume` (SessionStart clears locks) or wait for the TTL.
- **Claude Desktop shows nothing while an agent works, or runs one agent at a time.** That is a
  foreground child blocking BlackCat. Re-run `./install.sh` (the hook then launches BlackCat's children
  in the background) and start a new session; check that `BLACKCAT_BACKGROUND` isn't `0`. A child's
  `~/.claude/projects/<project>/<session>/subagents/agent-<id>.meta.json` names its `requestShape`.
- **Bypass the policy temporarily:** `"STACK_POLICY": "off"` in `settings.json` → `env`.
- **Restore:**
  1. Copy files back from `~/.claude/backup-*/` (the stack's old `CLAUDE.md`, if it was retired, is
     in `retired/`).
  2. Remove the `# claude-agent-stack` line from your shell rc.
  3. `claude mcp remove -s user exa` (and jina, wolfram, huggingface, wandb) if you no longer want
     them.

</details>

<!-- markdownlint-enable MD024 MD032 MD033 MD036 MD038 -->

### 2026-09-29 — Desktop parallelism, two models, effort and turn calibration, spawn caps

Found by reading Claude Desktop and terminal transcripts, the guard's state folders and the current
docs (sub-agents, hooks, model-config, env-vars, settings-reference; Claude Code 2.1.284).

- **Desktop hang / one agent at a time (fixed).** In the Agent SDK apps the Agent tool offers
  `run_in_background`, and the rules told BlackCat to pass `false`: every child ran in the foreground
  and blocked the main thread for its whole run. Now `agent_guard.py` drops `run_in_background: false`
  from BlackCat's Agent calls (`BLACKCAT_BACKGROUND=1`, new), BlackCat's prompt never asks for the
  foreground, and the rules keep `false` only for subagents (in the SDK a subagent doesn't wait for
  background children). The installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and
  `CLAUDE_CODE_FORK_SUBAGENT` from settings env (either breaks that scheduling); `/stack-doctor` warns
  about them and about `BLACKCAT_BACKGROUND=0`.
- **BlackCat output and questions.** Every turn ends with a visible message (who works on what; a
  repeated completion notice gets one line, never silence); clarifying questions cover format,
  scope, costly choices and destructive steps, with open questions in a child's report relayed
  through AskUserQuestion (plain text where the app has no question tool). Recommended main-thread
  effort is now `medium` (Sonnet 5.5's default; at `low` it skipped questions): README, installer
  hint and `/stack-doctor` follow.
- **Two models only.** Every agent pins `claude-opus-5-5` or `claude-sonnet-5-5` (the `opus` alias and
  god-coder's Fable are gone; doc-specialist moves to Sonnet 5.5, its work being extraction and
  formatting); `tests/lint_agents.py` rejects any other value. Background tasks stay on Sonnet 5.5.
- **Effort recalibrated for the 5.5 models** (their `medium` matches Opus 5 at `high`): orchestrator,
  plan-reviewer, code-reviewer and quantum-engineer `xhigh` → `high`; motion-designer and cg-artist
  `high` → `medium` (GUI and tool loops); main-coder stays `xhigh`, ninja-coder and god-coder `max`.
- **`maxTurns` by task type** from measured turns per run: oracle 12, scout and claude-code-guide 30,
  planner, plan-reviewer and image-director 80, code-reviewer and security-auditor 120, writer,
  doc-specialist and browser-operator 120, researcher, designer, motion-designer, data-scientist and
  verifier 150, devops-engineer 160, cg-artist 170, quantum-engineer and claude-code-engineer 180;
  larger scope for the coordinators: orchestrator 250, main-coder and ninja-coder 300, god-coder 350.
- **Spawn caps.** BlackCat 8 dispatches and 12 tool calls per prompt (was 6 and 8), dispatch window
  120 s (was 30: eight long briefs in one message); per-type running-children table in one place
  (`DEFAULT_FANOUT_BY_TYPE`, overridden by `STACK_MAX_FANOUT_BY_TYPE`): orchestrator 10, god-coder and
  main-coder 6, ninja-coder 5, researcher 4, planner 8, everyone else 3; session-wide
  `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 32 (was 20). The orchestrator decomposes into up to 10 tasks
  (about 12 spawns per job). Every agent with a spawn-policy row has the Agent tool and a matching
  "May spawn" sentence (lint-checked); god-coder's text wrongly said it could not spawn at L3 (only L4
  cannot).
- **god-coder: orchestrator only, once per session.** Only the orchestrator may spawn god-coder
  (`GOD_SPAWNERS=orchestrator`), and only once per session (`GOD_ONCE_PER_SESSION=1`, a marker
  claimed atomically with the spawn; a failed or refused spawn releases it; SendMessage resumes of
  that god-coder pass). BlackCat's `Agent(...)` list, main-coder, ninja-coder and the ml-platform
  engineers no longer list god-coder: they return `NEXT: god-coder` with a dossier. `claude-god`
  (god-coder as your own main thread) is unchanged.
- **Tests.** New: BlackCat foreground drop, shipped spawn defaults, god-coder orchestrator-only and once per session; the mechanics tests pin their
  former caps as a baseline; smoke and lint updated to the new values.
