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

## 7. Installer, backups and hardening

### How an install runs
1. The stack's part of the config dir (`agents/`, `skills/` without `synced/`, `rules/`, `hooks/`, `bin/`, `mcp/` without `vendor/`, `stack-plugins/`, `magg/config.json`, `settings.json`, `stack.env`, `.stack-manifest.json`, `CLAUDE.md`, temp leftovers) is copied to a staging dir inside the backup root (so the staged `stack.env` is as private as the backups), with a snapshot of what was copied. A top-level scope dir that is a symlink (a dotfiles `skills/` or `agents/`) is yours: nothing under it is ever removed, and the run stops unless `--write-through-links` lets it write the stack's files through the link (`--dry-run` shows the plan either way). `--force` doesn't lift that stop, so `--no-prune --write-through-links` keeps your edits to stack files there (each gets a `.new` render). A symlink one level down (`skills/<name>` pointing into a dotfiles checkout) is replaced by the stack's copy of that skill; the backup keeps the link and its target is never written.
2. Render, settings merge and pruning run there. The staged result is validated before anything changes: JSON, agent and skill frontmatter, placeholders, and the staged `agent_guard.py --self-test`. Validation is fatal only for files the stack owns (their sha256 matches the manifest).
3. The plan is printed: `changes: N added, N updated, N removed`, then `replaced:` (stack files that differed) and `removed: not part of the stack`, each with a reason.
4. `--dry-run` stops here; MCP, plugin and rc changes are printed as `would: ...`. A real run saves every file it changes or removes into one backup, records the files it adds, then applies. A run that changes nothing makes no backup.
5. Nothing is applied if the config dir changed after staging (Claude Code saving `settings.json`, an editor): the plan and the apply both compare it with the snapshot, the second time right before the first change. Plan paths that are not scope paths, or that resolve out of the config dir, are refused (by the plan step too, so `--dry-run` reports what the real run would refuse); a path below a symlink the plan removes first is resolved as the directory that replaces it.
6. Every path in `.stack-manifest.json` must be a file path in the scope (no `..`, no absolute path, not a whole scope dir such as `bin` or `mcp`): one that isn't stops the install before anything changes, and the staged copy must hold all the stack's scripts. The manifest also records the stack commit each install shipped; the next run prints the diffstat of `dot-claude/hooks`, `dot-claude/settings.json`, `install.sh` and `lib/` since then (and any uncommitted edits there) before the plan.

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
- A saved symlink whose target leaves the config dir is restored only with `--restore DIR --force`; without it the run names the link and the `ln -s` that recreates it.

### Plugins
One copy of each skill is the default. A plugin that duplicates a claude.ai-synced skill (document-skills, skill-creator) is disabled, and so is `mcp-server-dev@claude-plugins-official` (the stack's `mcp-server-craft` covers it). Each disable prints `To undo: claude plugin enable ...` and is recorded for `--restore`; `--keep-plugin-duplicates` keeps both. `math-olympiad` (with `--with-extra-plugins`) and the built-in `dataviz` skill stay.

### Supply chain (C7)
- uv 0.12.20: release tarball, checked by sha256.
- magg 1.2.1: `uv tool install --exclude-newer 2026-09-22T00:00:00Z`.
- huetension v0.3.0: tarball checked by sha256 (`go install ...@v0.3.0` as fallback).
- sci/ml venvs: `requirements/*.txt` with `--require-hashes` (sci also `--only-binary :all:`), 7-day cooldown.
- After Effects MCP: pinned commit `88d5fbf0`, `npm ci --ignore-scripts`, then an explicit `npm run build`.
- `--with-lsp` npm installs: `pyright@1.1.414`, `typescript-language-server@6.0.1` (`@5.3.0` on Node < 22.22.2) and `typescript@6.0.3` (TypeScript 7 ships no `tsserver`), all with `--ignore-scripts` (versions checked against the npm registry 2026-09-29).
- Agents can't run `install.sh` (guard, every agent type and the main thread) except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs (`HOME` and `CLAUDE_CONFIG_DIR` both under a temp dir, checked after resolving symlinks); installing is your step. The rule follows `cd <repo> && ./install.sh`, covers `lib/install_state.py apply|restore|stage|record|move-legacy` on a non-scratch config dir, and a command that copies or pipes the stack's `install.sh` and runs a shell.

### Sandbox and managed settings
- `settings.json` turns the sandbox on with `allowUnsandboxedCommands: false`:
  - **filesystem:** `denyWrite` covers the config dir, the guard state dir and the backups; `denyRead` covers `stack.env`, `backup-*`, the backups and `.credentials.json`.
  - **network:** a strict allowlist of package registries, forges, Hugging Face, W&B and arXiv.
  - **credentials:** forge tokens (`GITHUB_TOKEN`, `GH_TOKEN`, GitLab/Gitea/Forgejo/Codeberg) are denied to sandboxed commands.
- `failIfUnavailable: true`: Claude Code exits at startup when the sandbox can't start, instead of warning and running commands unsandboxed.
- **Caches (N4).** The caches the stack's own unsandboxed processes load code from are not writable from inside the sandbox (your own MCP servers and hooks are the exception: see Residual risks):
  - `allowWrite` keeps `~/.cache`, `~/Library/Caches`, the cargo registry/git, `~/go/pkg`, the Gradle/Maven/bun caches and `~/.matplotlib`; it no longer has `~/.local/share/uv` (uv tools such as magg, managed Pythons), `~/.npm` (the `npx` MCP servers), `~/.rustup`, `~/.julia` or `~/.elan` (language servers and their toolchains).
  - `denyWrite` adds `~/.cache/uv` and `~/.cache/pre-commit` (your own tools' caches), the Playwright browser caches (the Playwright MCP server launches those browsers) and `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-cache`.
  - Every local (stdio) MCP server an agent starts gets `UV_CACHE_DIR` and `npm_config_cache` in that cache root: the installer adds them to each server's `env` when it renders the agents (magg passes them on to the catalog servers it runs), and its dependency prefetch warms that cache.
  - Sandboxed commands use `~/.cache/claude-sandbox/{uv,npm,pre-commit}` (`settings.json` `env`). Installed toolchains (rustup, elan, Julia packages, managed Pythons) stay readable; installing new ones from inside the sandbox fails. For Julia, a command can put a writable depot first: `JULIA_DEPOT_PATH=$HOME/.cache/claude-sandbox/julia: julia ...`.
- **Credentials (N1, C2).** `env` sets `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=credential.helper`, `GIT_CONFIG_VALUE_0=` (an empty helper list) for every command Claude Code starts, so `git credential fill` finds nothing: fetching a private HTTPS repo from a session needs SSH or your terminal. `~/.config/gh/hosts.yml` and `~/.git-credentials` are `denyRead` (and `Read` deny rules); `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `WANDB_API_KEY` and `JUPYTER_TOKEN` join the forge tokens denied to sandboxed commands. The guard also refuses `gh auth token`, `gh auth status -t`, `git credential fill|approve|reject`, `git credential-*`, keychain dumps (`security find-*-password -w/-g`, `dump-keychain`, `export`) and Claude Code's headersHelper mode of `mcp-headers` (`CLAUDE_CODE_MCP_SERVER_NAME=...`) for every agent.
- **magg (N3).** `magg_enable_server`, `duckdb_*` and `jupyter_*` are `ask` rules; ask rules prompt even in `bypassPermissions` ([permission modes: actions no mode auto-approves](https://code.claude.com/docs/en/permission-modes)). A background agent's prompt appears in your main session, naming the agent ([subagents](https://code.claude.com/docs/en/sub-agents)). duckdb runs on an in-memory database (no database file to write, no `--allow-switch-databases`), extensions don't autoload and its settings are locked (`--init-sql`); an explicit `INSTALL` in an approved query still works; jupyter has no read-only mode, so the prompt is its control.
- The installer merges this block into yours: the stack's scalars win and lists are unioned.
- `./install.sh --print-managed-settings > managed-settings.json` prints an optional root-level file (instructions go to stderr). It repeats the guard hook, the protected-path deny rules and the sandbox, so editing `~/.claude/settings.json` can't switch them off.
- Installing that file is your step: `/Library/Application Support/ClaudeCode/managed-settings.json` (macOS) or `/etc/claude-code/managed-settings.json`. The installer never writes anything root-owned. Re-print it after an install that changed the hook or deny rules. The printed file includes `failIfUnavailable`.
- **Stronger, optional (N-MANAGED, documented only).** The printed file still runs the guard from `~/.claude/hooks/`, which you (and anything running as you outside the sandbox) can edit. To pin it:
  1. Copy `agent_guard.py` to a root-owned place (`sudo install -o root -m 755 ~/.claude/hooks/agent_guard.py '/Library/Application Support/ClaudeCode/hooks/agent_guard.py'`).
  2. Point every hook command of the stack at that copy in `managed-settings.json` (all events of `settings.json` `hooks`, not only the no-push one).
  3. Add `"allowManagedHooksOnly": true` (managed-only key): user, project, local, plugin and agent-frontmatter hooks stop running. BlackCat's frontmatter wiring then no longer runs, so the settings-level `blackcat-guard --settings` hook must be in the managed file.
  4. Re-copy the hook after every install that changes it.

### Residual risks
- **The shell parsing is a heuristic.** The read-only reviewer allowlist, the protected-path scan and no-push all parse shell text. The sandbox, and managed settings once you install them, are the real boundary; without the sandbox a determined interpreter one-liner can still slip past the parser.
- **`gh` can still use a keychain token.** `hosts.yml` is unreadable in the sandbox now, but `gh` (and git's `osxkeychain` helper run directly) can still reach a token stored in the macOS keychain. The guard refuses the commands that print it and the no-push hook refuses forge writes (`gh`, `git push`, `curl`/`wget`/`httpie` writes to forge hosts); arbitrary code that talks to the keychain or sends the token itself isn't caught by either.
- **Language servers run outside the sandbox on files the sandbox can write.** rust-analyzer runs build scripts and proc macros, Metals/Gradle, HLS and `lake serve` run build code, and LanguageServer.jl loads packages: a sandboxed command that edits a project's build files gets that code run unsandboxed the next time the language server starts. The cargo registry, `~/go/pkg`, `~/.m2` and `~/.gradle/caches` are still sandbox-writable for the same reason builds need them. Disable the LSP plugins for untrusted work.
- **Your own MCP servers and hooks on the sandbox cache.** `settings.json` `env` points every process Claude Code starts at `~/.cache/claude-sandbox/{uv,npm}`, which the sandbox can write. The stack's servers override it; your own stdio servers (`~/.claude.json`, user or project scope; plugin `.mcp.json` servers) and your own hooks that run `uvx`/`npx`/`uv run`/`npm exec`/`bunx` don't, so a sandboxed command could plant a package they later run unsandboxed. `install.sh` (also with `--dry-run`) and `doctor.sh` name each such server or hook with the `env` to add; they change nothing. Plugin servers aren't listed.
- **Other writable caches.** `~/.cache` (apart from uv, pre-commit and Playwright) and `~/Library/Caches` stay writable for sandboxed builds; a tool of yours that later loads code from one of them outside Claude Code (pip's wheel cache, for example) can pick up what a sandboxed command left there.
- **Approved duckdb/jupyter calls.** Once you approve it, a duckdb query can read (or `COPY TO`) any file you can, and a jupyter call runs code in your kernel: read the call before approving.
- **Web reads in memory (T3).** An agent that read web content in a task (WebFetch, WebSearch, curl/wget in Bash, and every MCP tool except a short non-web list: neural-memory, wolfram, wandb, image-studio, the Adobe and Blender servers, huetension, ide, magg's management tools and its local database/kernel servers) can't write the shared memory for the rest of the session; content fetched by other means (inline Python, say) isn't seen.
- **Reviewers' scratch code (T2).** The read-only types' scratch scripts and test files are content-checked with the same heuristic as inline code before they run; writing scratch code and running it in the same command is refused, as is a scratch operand that doesn't exist yet. Code that hides from the pattern still runs with the sandbox's project-wide write access, and a background job that swaps a file between two calls isn't seen.
- **Protected-path scan gaps.** A path behind an expansion the guard can't resolve counts only when that expansion is tied to the config dir in the same command (`D=$(echo ~/.claude)`, a loop over it) or the path names `.claude` itself; `patch` reading its target from the diff and output flags glued to others (`wget -qO-FILE`) aren't parsed. `/usr/bin/env python3 ...` and `env -C DIR ./install.sh` hide the command from the install rule, and a copy of `install.sh` run directly (no shell word) isn't caught.
- **WebFetch domains (T1, not changed).** Allow rules have no effect in `bypassPermissions` and ask rules can't be scoped to one agent type (a `WebFetch` ask rule would prompt on every fetch of every agent). Which agents may fetch at all is set by their `tools:` lines.
- **The guard state path is fixed in the sandbox.** `denyWrite` names `~/.local/state/claude-agent-stack`. With `XDG_STATE_HOME` set elsewhere, the guard state dir is protected only by the guard's own path check. The backups use the rendered `__STACK_BACKUPS__` path and are covered either way.
- **Linux `.git/modules` (LOW).** On Linux/WSL2 the sandbox drops write-list entries with a mid-path wildcard, so the `.git/modules/**/hooks/**` and `.git/modules/**/config` denies protect submodule hooks and config only on macOS (the stack's platform). The plain `.git/hooks` and `.git/config` denies apply everywhere.
- **Unverified:** whether Claude Code's sandbox honours the absolute `__STACK_BACKUPS__` and `__STACK_CACHE__` paths in `denyRead`/`denyWrite` exactly as written (they follow the `__CLAUDE_DIR__` pattern already shipped). That a `denyWrite` entry wins inside a wider `allowWrite` entry is read from the docs' `/sandbox` Config tab ("Denied within allowed"), not tested live.

## 8. Validation (2026-09-29)

| Check | Result |
|---|---|
| `/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test` | ok |
| `uv run tests/lint_agents.py` | ok |
| `uv run --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/` | 2249 passed |
| `bash tests/install_smoke.sh` | 236 passed, 0 failed (scratch dirs only; includes a drifted config, dry-run, restore round trips, `--no-prune`, symlinked scope dirs, manifest traversal, the MCP cache warnings) |
| `jq empty dot-claude/settings.json` | ok |

## 9. Changelog

### 2026-09-29 (security round 2)

- Installer: manifest paths are checked against the stack's scope, symlinked `agents/`, `skills/` (and the other scope dirs) are never pruned and need `--write-through-links` (new flag) to be written through, per-skill symlinks are replaced by the stack's skill again, whole scope dirs named in the manifest are refused, the backup root must be a private real directory, the work dir lives inside it, a config change during the run aborts before anything is written, restored links that leave the config dir need `--force`, the removal list names every hook entry, the LSP installs are pinned with `--ignore-scripts`, the MCP prefetch warms the servers' own cache, and your own MCP servers and hooks that run package runners on the sandbox cache are named (section 7).
- Settings: `sandbox.failIfUnavailable`, tool caches moved out of the sandbox's writable set, git credential helpers off, token env vars denied to sandboxed commands, `magg_enable_server`/duckdb/jupyter tools ask; duckdb runs in memory with extension autoload and config changes locked.
- Guard: protected-path checks expand `$HOME`, `$CLAUDE_CONFIG_DIR`, assigned variables, braces, globs, `cd` and `CDPATH` forms, and see output options (`curl -o`, `wget -O`, `sort -o`, `-o/--output` generally), `patch`, `sponge`, awk redirects and `git clone/init`; `$VAR/bin`-style project paths are no longer denied; `git -C <config dir>` tree-rewriting subcommands (now also bisect, submodule, merge-file, worktree add, archive/format-patch output) are denied; credential reads, forge writes over curl/wget/httpie and `install.sh`/`install_state.py` runs are denied; read-only reviewers may run syntax-only checks but not write-then-run scratch code; any MCP tool outside a non-web list marks the agent as web-tainted.

### 2026-09-29 (security and installer)

- Security findings C1–C9, T1–T3 and P3 fixed (guard, settings, MCP servers, installer); section 7 lists the residual risks.
- The installer stages, validates, backs up and then applies. It prunes by default (`--no-prune` opts out) and supports `--dry-run`, `--restore [DIR]` and `--print-managed-settings` (section 7).
- Plugin duplicates of synced skills and `mcp-server-dev` are disabled by default (`--keep-plugin-duplicates`).
- `skillListingBudgetFraction` 0.012; `tests/lint_agents.py`, `doctor.sh` and the smoke test read it from `settings.json`.
- Read-only reviewers may also run `claude --version`, `claude mcp list/get`, `claude plugin list` and the audit scanners (`gitleaks`, `trufflehog`, `semgrep`, `osv-scanner`, `pip-audit`, `uv audit`, `npm audit`, `cargo audit`/`deny`, `trivy`).

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
