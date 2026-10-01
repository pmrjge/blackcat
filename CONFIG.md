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
| explore | Sonnet 5.5 | low | 40 | leaf | (built-in) | Read-only codebase search. Replaces Claude Code's built-in Explore, which inherits the main thread's model up to Opus and has no turn cap. |
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
  - Only the orchestrator may spawn it, once per session (`GOD_SPAWNERS=orchestrator`, `GOD_ONCE_PER_SESSION=1`), and only after a ninja-coder of the same session has finished (`GOD_AFTER_NINJA=1`). The hook checks the order only (a ninja-coder stopped, or its Agent call reported a terminal status), not that it failed; that ninja-coder may have been spawned by any agent of the session.
  - Any other agent that needs it returns `STATUS: partial` with `NEXT: god-coder` and a dossier.
  - In a plan: planner may add one god-coder step, only as the conditional fallback of a preceding ninja-coder step on the same problem; plan-reviewer blocks a step without that ninja-coder step, an unconditional one, a second one or an incomplete dossier; BlackCat sends such plans to the orchestrator; the orchestrator runs ninja-coder first and spawns god-coder only when ninja-coder reports failure or partial, dropping the step if ninja-coder succeeds. That it failed is enforced by these prompts, not by the hook.
  - A failed or refused spawn releases the session slot. SendMessage resumes of that god-coder pass.
  - `claude-god` (god-coder as your own main thread) is unaffected.
- **Leaves** (no Agent tool): oracle, scout, code-reviewer, verifier, security-auditor, mcp-broker, claude-code-guide, browser-operator, plan-reviewer, image-director, explore.
- **No generic agents:** `subagent_type` must name a stack agent in the caller's row: a missing type, `general-purpose`, `claude`, `fork`, `Plan`, `statusline-setup`, host-defined types such as `SubAgent` and plugin agents are refused for every caller (one without a row gets BlackCat's row on a main thread, nothing as a subagent), also through the tool's `Task`/`SubAgent` aliases. A generic agent started outside the Agent tool (a skill with `context: fork` and no `agent:`, a workflow stage without `agentType`) has every tool call refused. Each workflow `agent()` names a stack `agentType` the caller may spawn, with no `model`; bundled and plugin workflows (`/deep-research`) are refused. settings.json: `Agent(general-purpose)`, `Agent(claude)`, `Agent(fork)` deny rules, `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1`, `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` (`claude -p` and Agent SDK apps).
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
| `GOD_AFTER_NINJA` | 1 (code) | new | A god-coder spawn needs a ninja-coder of this session that has finished; checks order, not failure; 0 = off |
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
- sci/ml venvs: `requirements/*.txt` with `--require-hashes` (sci also `--only-binary :all:`), 7-day cooldown.
- After Effects MCP: pinned commit `88d5fbf0`, `npm ci --ignore-scripts`, then an explicit `npm run build`.
- `--with-lsp` npm installs: `pyright@1.1.414`, `typescript-language-server@6.0.1` (`@5.3.0` on Node < 22.22.2) and `typescript@6.0.3` (TypeScript 7 ships no `tsserver`), all with `--ignore-scripts` (versions checked against the npm registry 2026-09-29).
- Agents can't run `install.sh` (guard, every agent type and the main thread) except `--help`, `--dry-run`, `--print-managed-settings` and scratch installs (`HOME` and `CLAUDE_CONFIG_DIR` both under a temp dir, checked after resolving symlinks); installing is your step. The rule follows `cd <repo> && ./install.sh`, covers `lib/install_state.py apply|restore|stage|record|move-legacy` on a non-scratch config dir, and a command that copies or pipes the stack's `install.sh` and runs a shell.

### Sandbox and managed settings

- **Status: configured, not live-verified.** The settings, the guard and the tests are checked; that Claude Code's sandbox enforces them as configured is not, until the user runs the live checks (README → Security model → Live checks). Until then the guard and the deny rules are the tested layers.
- `settings.json` turns the sandbox on with `allowUnsandboxedCommands: false`:
  - **filesystem:** `denyWrite` covers the config dir, the guard state dir (`__STACK_STATE__`), the backups (`__STACK_BACKUPS__`) and the MCP servers' cache (`__STACK_CACHE__`), all rendered from `${XDG_STATE_HOME:-~/.local/state}` at install time (changing `XDG_STATE_HOME` later needs a reinstall), plus `~/.cache/uv`, `~/.cache/pre-commit`, the Playwright browser caches, `~/Library/Caches/Coursier` and the Hugging Face token file. `denyRead` covers `stack.env`, `backup-*`, the backups, `.credentials.json`, `~/.config/gh/hosts.yml`, `~/.git-credentials` and `~/.config/git/credentials`. `allowWrite` is only `~/.cache/claude-sandbox`.
  - **network:** a strict allowlist of package registries, forges, Hugging Face, W&B and arXiv.
  - **credentials:** forge tokens (`GITHUB_TOKEN`, `GH_TOKEN`, GitHub Enterprise, GitLab/Gitea/Forgejo/Codeberg), `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `WANDB_API_KEY` and `JUPYTER_TOKEN` are denied to sandboxed commands.
- `failIfUnavailable: true`: Claude Code exits at startup when the sandbox can't start, instead of warning and running commands unsandboxed.
- **Caches (N4, R3-CACHES).** Sandboxed Bash and everything else no longer share a writable cache.
  - Sandboxed Bash gets its own caches, `~/.cache/claude-sandbox/<tool>`, from a SessionStart hook without a matcher (`agent_guard.py session-env`, every source) that appends exports to `$CLAUDE_ENV_FILE`; Claude Code runs that file before each Bash command, the agents' included. The variables: `XDG_CACHE_HOME`, `UV_CACHE_DIR`, `PIP_CACHE_DIR`, `npm_config_cache`, `npm_config_devdir`, `npm_config_store_dir`, `YARN_CACHE_FOLDER`, `BUN_INSTALL_CACHE_DIR`, `DENO_DIR`, `PRE_COMMIT_HOME`, `HF_HOME`, `MPLCONFIGDIR`, `CARGO_HOME`, `GOMODCACHE`, `GOCACHE`, `GRADLE_USER_HOME`, `COURSIER_CACHE`, `CCACHE_DIR`, `SCCACHE_DIR`, plus `-Dmaven.repo.local=<dir>/m2` appended to `MAVEN_OPTS`. MCP servers, hooks, language servers and the user's terminal don't see them and keep their normal caches, which sandboxed code can no longer write. Safe to delete.
  - Evidence that subagents get the file: the hooks reference promises `CLAUDE_ENV_FILE` to "subsequent Bash commands" (SessionStart, Setup, CwdChanged and FileChanged hooks get it) and says nothing about subagents; the installed CLI (2.1.284) keeps the file per session id, not per agent, and prepends it to every Bash command of the session, subagents' included. The docs don't promise it, hence a live check. Fallback if a future version stops that (not built): the no-push hook could refuse sandboxed Bash lacking `UV_CACHE_DIR` under `~/.cache/claude-sandbox`.
  - Trade-offs (sandboxed Bash only): `CARGO_HOME` moves, so `~/.cargo/config.toml` and cargo's credentials aren't read and `cargo install` binaries land in the sandbox's cargo dir; `GRADLE_USER_HOME` moves, so `~/.gradle/gradle.properties` isn't read; `HF_HOME` moves, so models download again and no Hugging Face token is found; when `$HOME` holds a character Maven would split on (a space, a quote), `MAVEN_OPTS` is left alone with a warning and Maven falls back to `~/.m2`, which the sandbox refuses; a tool that writes `~/Library/Caches` (or another cache) with no variable to redirect it fails; a Bash command that runs before the hook has written the file gets the default paths, which the sandbox refuses (fails closed).
  - The stack's own local MCP servers keep their private `STACK_CACHE`, `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-cache/{uv,npm}` (sandbox-denyWrite, set in each server's `env` when the installer renders the agents, passed on by magg to the catalog servers, warmed by the prefetch): one cache the sandbox can't touch for the servers the stack ships.
  - Installed toolchains (rustup, elan, Julia packages, managed Pythons) stay readable; installing new ones from inside the sandbox fails. For Julia, a command can put a writable depot first: `JULIA_DEPOT_PATH=$HOME/.cache/claude-sandbox/julia: julia ...`.
  - An upgrade retracts from the user's `settings.json` the `env` keys and `allowWrite` entries earlier installs shipped (`UV_CACHE_DIR`, `npm_config_cache`, `PRE_COMMIT_HOME`, `GIT_CONFIG_COUNT`/`KEY_0`/`VALUE_0`; `~/.cache`, `~/Library/Caches`, the cargo/go/gradle/maven/bun/matplotlib/uv/npm/rustup/julia/elan dirs), printing each, and keeps entries of the user's own; a first install (no manifest) retracts nothing. The cache-runner warnings about the user's own MCP servers and hooks are gone from `install.sh` and `doctor.sh`; `doctor.sh` warns when the old keys or a broad cache dir are still there and confirms the session-env hook is wired.
  - **Hook failure is visible (R4-2).** If the hook can't write the environment (no `CLAUDE_ENV_FILE`, an unwritable file or `~/.cache/claude-sandbox`, or its marker missing after writing), it exits 2 and the session shows a SessionStart hook error ("the sandboxed Bash environment is NOT set for this session (reason) … Check with …/bin/doctor.sh, then start a new session (or /clear)"); the session goes on without the caches and with git's credential helpers on. The guard records running/ok/failed in the session's state dir (`session-env.json`); the status line starts with a red `! Bash sandbox env missing: doctor.sh` for that session (also when the hook never finished, after 30 s); `doctor.sh` runs the hook against a temp dir and warns when it failed in any of the last 10 sessions.
- **Credentials (N1, C2, R3-GITENV).** Git credential helpers are off in sandboxed Bash only: the session-env hook appends `'credential.helper='` (an empty helper list) to `GIT_CONFIG_PARAMETERS`, after any value already there, and touches no `GIT_CONFIG_COUNT`/`GIT_CONFIG_KEY_*` of the user's. Unsandboxed git (plugin marketplace updates, MCP servers, the terminal) keeps its helpers, so private marketplace updates work again; a private HTTPS fetch from an agent's Bash needs SSH or the terminal. `~/.config/gh/hosts.yml`, `~/.git-credentials` and `~/.config/git/credentials` are `denyRead` (and `Read` deny rules). The guard also refuses `gh auth token`, `gh auth status -t`, `git credential fill|approve|reject`, `git credential-*`, keychain dumps (`security find-*-password -w/-g`, `dump-keychain`, `export`) and Claude Code's headersHelper mode of `mcp-headers` (`CLAUDE_CODE_MCP_SERVER_NAME=...`) for every agent.
- **Least-privilege GitHub (R3-N1-P2).** Give the agents no write-capable GitHub credential: none at all, or a read-only fine-grained token (Contents: read, Metadata: read) that `gh` uses from its own config dir (`GH_CONFIG_DIR=~/.config/gh-agents gh auth login --with-token < token-file`, then export that `GH_CONFIG_DIR` in the shell `claude` starts from). Push over SSH from the user's terminal (agents never push: hook-enforced), and keep write-capable HTTPS credentials out of the `github.com` keychain entry git's osxkeychain helper reads, since unsandboxed git still uses it.
- **doctor.sh credential presence.** Section "GitHub credentials agents could use" reports by presence only (no value printed; keychain lookups are attribute searches without `-g`/`-w`, so no secret is read and no prompt appears): `GH_TOKEN`, `GITHUB_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN` in the environment; a plain-text `oauth_token` in gh's `hosts.yml` (`$GH_CONFIG_DIR` or `~/.config/gh`); a github.com line in `~/.git-credentials` or `${XDG_CONFIG_HOME:-~/.config}/git/credentials`; on macOS a keychain item for service `gh:github.com` (from gh's source; unverified against a live gh) and a github.com internet password. Each is a WARN naming who can use it (sandboxed Bash is denied the token variables, `~/.config/gh/hosts.yml` and `~/.git-credentials`; hooks, MCP servers and other unsandboxed processes are not; a `hosts.yml` under another `GH_CONFIG_DIR` isn't denied) and the least-privilege step; none found is `ok`.
- **Web taint (T3, R3-T3-RELAY).** An agent can't write the shared memory when it, or any agent linked to it, read web content: a child that reported back to it (the registry's parent links, transitively), an agent it exchanged SendMessage with (either direction, transitively), or the prompt it was spawned with (a child of a tainted agent is born tainted). A message to a name whose agent id isn't known yet is linked through the Agent call that spawned it. A spawn whose mark can't be recorded is refused; past 4,096 linked agents the check fails closed; the refusal names the source. The main thread is not a link; files are not links (residual).
- **Read-only reviewers and temp dirs (R3-INFO).** A project checked out under a temp dir (`/tmp`, `/private/tmp`, `/var/folders`, `$TMPDIR`) is the project, not scratch; `./.claude-work` stays scratch everywhere, and a session whose project is a temp dir itself keeps all of it scratch. The project is `CLAUDE_PROJECT_DIR`; only without it do the event's cwd and the hook's cwd count. Before, 118 of this repo's tests failed from a checkout under `/private/tmp` (all in `test_readonly_agents.py`); 0 now.
- **magg (N3).** `magg_add_server`, `magg_load_kit`, `proxy`, `magg_enable_server` and every `duckdb_*`, `jupyter_*`, `ros_*`, `qiskit_*` and `docspace_*` call are `ask` rules. Every catalog prefix has exactly one allow or ask rule (test), and `mongodb_*`/`postgres_*` stay allowed only with their read-only flags (`--readOnly`, `--access-mode=restricted`; test); ask rules prompt even in `bypassPermissions` ([permission modes: actions no mode auto-approves](https://code.claude.com/docs/en/permission-modes)). A background agent's prompt appears in your main session, naming the agent ([subagents](https://code.claude.com/docs/en/sub-agents)). duckdb runs on an in-memory database (no database file to write, no `--allow-switch-databases`), extensions don't autoload and its settings are locked (`--init-sql`); an explicit `INSTALL` in an approved query still works; jupyter has no read-only mode, so the prompt is its control.
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
- **Reviewers' scratch code (T2).** The read-only types' scratch scripts and test files are content-checked with the same heuristic as inline code before they run; writing scratch code and running it in the same command is refused, as is a scratch operand that doesn't exist yet, inline Python that loads scratch code (`sys.path`, `runpy`, importlib loaders) and `python -c` run from a scratch dir. Code that hides from the pattern still runs with the sandbox's project-wide write access; a background job that swaps a file between two calls, `python -m` of a module shadowed in a scratch cwd and a `PYTHONPATH` exported in an earlier call aren't seen.
- **Protected-path scan gaps.** A bare protected name (`bin`, `hooks`, ...) behind an expansion the guard can't resolve counts when that expansion could be steered: a command substitution (other than `mktemp`, `pwd`, `dirname`, `basename`, `git rev-parse --show-toplevel`), a variable set by `read`/`mapfile`/`printf -v` or from such a value, a loop over one, or a positional parameter in a command that names the config dir; inherited variables (`$VENV/bin`) don't count, so a variable exported by your own shell profile that points into the config dir isn't seen. Past 1,024 words, numeric ranges collapse to one digit pattern and a word that still overflows is refused whatever it names; `patch` reading its target from the diff and output flags glued to others (`wget -qO-FILE`) aren't parsed. `/usr/bin/env python3 ...` and `env -C DIR ./install.sh` hide the command from the install rule, and a copy of `install.sh` run directly (no shell word) isn't caught; the scratch-install exception is off in a command that creates links or moves directories, but links made by a `git clone`/`checkout` aren't seen.
- **WebFetch domains (T1, not changed; accepted residual after round 3).** Allow rules have no effect in `bypassPermissions` and ask rules can't be scoped to one agent type (a `WebFetch` ask rule would prompt on every fetch of every agent). Which agents may fetch at all is set by their `tools:` lines. A guard URL policy keyed on agent type was weighed and not built: a docs-domain allowlist for the coder types would refuse legitimate research (issue trackers, blogs, mailing lists, vendor docs on their own domains), and a "long high-entropy query string" check both refuses normal URLs (commit SHAs, signed download URLs, search queries, tracking parameters) and misses exfiltration through path segments or many short requests. Not cheap and not false-positive-safe, so the boundary stays the tool lists, the web taint on memory writes and the no-push/forge-write hooks.
- **Taint gaps (round 4).** Files an agent reads are not links (above), and the main thread is a gap too: its web reads are not tracked as taint.
- **`GOD_AFTER_NINJA` checks order only (round 4).** Any finished ninja-coder run of the session, even a trivial one, unlocks the god-coder spawn; the requirement that ninja-coder failed rests on the planner, plan-reviewer, BlackCat and orchestrator prompts.
- **Session started directly in a temp dir (round 4).** A session whose project is a temp dir itself (`/tmp`) has no project dir: all of `/tmp` is scratch for the read-only agents there.
- **Live-sandbox checks still open (round 4).** See "Unverified live" below and README → Security model → Live checks.
- **Linux `.git/modules` (LOW).** On Linux/WSL2 the sandbox drops write-list entries with a mid-path wildcard, so the `.git/modules/**/hooks/**` and `.git/modules/**/config` denies protect submodule hooks and config only on macOS (the stack's platform). The plain `.git/hooks` and `.git/config` denies apply everywhere.
- **Unverified live** (the user's checks, README → Security model → Live checks): whether Claude Code's sandbox honours the absolute `__STACK_STATE__`, `__STACK_BACKUPS__` and `__STACK_CACHE__` paths in `denyRead`/`denyWrite` exactly as written (they follow the `__CLAUDE_DIR__` pattern already shipped); that a `denyWrite` entry wins inside a wider `allowWrite` entry (read from the docs' `/sandbox` Config tab, "Denied within allowed"); that settings `env` reaches MCP servers and hooks; that the `$CLAUDE_ENV_FILE` exports reach subagents' Bash; whether the osxkeychain helper answers inside the sandbox; that ask rules prompt under `bypassPermissions`; BlackCat's routing of god-coder plans.

## 8. Validation (2026-09-29)

| Check | Result |
|---|---|
| `/usr/bin/python3 dot-claude/hooks/agent_guard.py --self-test` | ok |
| `uv run tests/lint_agents.py` | ok |
| `uv run --with pytest --with httpx --with pillow --with "mcp>=1.10,<2" pytest -q tests/` | 2401 passed at `cfa9ee7` (2400 at `e0b5544`, also from a snapshot under `/private/tmp`, where 118 had failed before R3-INFO) |
| `bash tests/install_smoke.sh` | 244 passed, 0 failed at `cfa9ee7` (scratch HOME only; re-runs itself without a controlling terminal, so no install in it can wait on yours; includes a drifted config, dry-run, restore round trips, `--no-prune`, symlinked scope dirs with dir and file links, manifest traversal) |
| `jq empty dot-claude/settings.json` | ok |

## 9. Changelog

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
- magg `ros_*`, `qiskit_*`, `docspace_*` ask; every catalog prefix has exactly one allow or ask rule.
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
