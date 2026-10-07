# codex_config: the claude-agent-stack for the Codex CLI

`codex_config/install.sh` ports the stack to the OpenAI Codex CLI (and, optionally, the IDE extension). It does not change the Claude installer (`install.sh`, `lib/`, `dot-claude/`, `tests/` are untouched); it reads the same agent, skill, rule and settings sources and renders Codex equivalents into `CODEX_HOME`.

The design, with the Codex facts it relies on and the reasons for each choice, is in [DESIGN.md](DESIGN.md). Module contracts are in [INTERFACES.md](INTERFACES.md). Codex behaviour that was read from docs or source but never run is listed in [probes/PROBES.md](probes/PROBES.md): treat every statement below that touches Codex's own behaviour as depending on those probes.

**Installing is your step.** Nothing in this directory has been run against a real `~/.codex` by an agent, and no agent runs the installer for you.

## What it installs, and where

`CODEX_HOME` is `--codex-home`, else `$CODEX_HOME`, else `~/.codex`. The profile is `codex`, selected with `codex --profile codex`.

| Item | Path | Scope |
|---|---|---|
| Profile: model and effort of BlackCat, `approval_policy = "on-request"`, permission profile `claude-agent-stack`, `[features]`, `[agents]` limits and 56 `[agents.<name>]` entries, `[mcp_servers.*]`, the 8 guard hooks, `developer_instructions`, `web_search = "disabled"`, `skills.max_context_tokens = 6000`, `tool_output_token_limit = 25000`, `[shell_environment_policy.filters]` | `$CODEX_HOME/codex.config.toml` | the profile only; the file is owned whole |
| 56 role files (BlackCat is the main thread, not a role) | `$CODEX_HOME/stack/agents/<name>.toml` | the profile, through `config_file` (absolute paths) |
| Opt-in Astra profile and its 6 role files | `codex-astra.config.toml`, `stack/agents-astra/` | `codex --profile codex-astra` only |
| Guard: `codex-hook` stub, `codex_guard.py`, support files, `guard.json`, `agents.json`, `stack-python` link | `stack/hooks/`, `stack/bin/`, `stack/policy/` | used by the profile's hooks |
| Helper scripts and MCP servers | `stack/bin/` (`with-stack-env`, `mcp-headers`, `codex-mcp-headers`, `stack-install`, `magg-private`), `stack/mcp/`, `stack/magg/` | used by the profile's `[mcp_servers]` |
| 127 listed skills (hubs and standalones): real files in `stack/skills/<n>/`, one symlink each in `~/.agents/skills/<n>` (`--skills-root` changes the root, `none` skips the links) | `stack/skills/`, `~/.agents/skills/` | **global**: every Codex session and any other reader of `~/.agents` |
| 89 hub modules, never listed, read by absolute path from the hub's table | `stack/skill-modules/<n>/SKILL.md` | via the hubs |
| Rules (`forbidden` and `prompt`; no `allow`, except the two opt-in git forms) | `$CODEX_HOME/rules/claude-agent-stack.rules` | **global** |
| The stack's block in `AGENTS.md` (about 1.4 KiB) | `$CODEX_HOME/AGENTS.md` | **global** |
| Keys file (0600, seeded only when missing) | `$CODEX_HOME/stack.env` | read by the MCP wrappers and the header helper |
| Manifest (sha256 per owned file, hook fingerprints, link list) | `$CODEX_HOME/.stack-manifest.json` | |
| Backups | `${XDG_STATE_HOME:-~/.local/state}/codex-agent-stack-backups/` | separate from the Claude installer's |
| Guard state (spawn tree, counters), outside `CODEX_HOME` | `${XDG_STATE_HOME:-~/.local/state}/codex-agent-stack/` | |

Never touched: `hooks.json`, `agents/`, `rules/default.rules`, and everything in `config.toml` outside the regions that `--ide-default` writes (without that flag `config.toml` is not changed).

## Requirements

- Codex CLI 0.160.1 or later. With `codex` on `PATH` the installer checks the version and refuses an older one; without it, it warns and skips the Codex checks (including the rule examples run through `codex execpolicy check`).
- `uv` and Python 3.13 (`uv python install 3.13`), or `STACK_PYTHON` set to a Python 3.11 or later (the installer needs `tomllib`). The guard itself runs on `stack-python`, a link to a real interpreter binary (3.9 or later is enough); the installer refuses `/usr/bin/python3` as that target because it is a shim that fails when called under another name.
- A committed checkout. The installer snapshots the files `HEAD` tracks and refuses an edited one; files only staged or untracked are not installed.
- macOS is the tested platform. The root commands printed by `--print-requirements` use `-g wheel`, which is macOS-specific (Linux: `-g root`).

## Install: your steps

1. Review the plan, then install:

   ```
   codex_config/install.sh --dry-run
   codex_config/install.sh
   ```

   The installer prints the plan, asks before applying (`--yes` skips the question), makes one backup of everything it changes, and prints the restore command.
2. Trust the hooks. Run `codex --profile codex`, open `/hooks`, and trust the 8 hooks of the stack. **Until you do, the guard does not run at all**, and nothing in a session says so. Codex runs a non-managed hook only after trust, and the trust record covers the hook's definition (event, matcher, command, timeout), not the script's bytes.
3. Check: `codex_config/install.sh --doctor`. It exits 0 only when every stack hook has a trust record and no owned file has drifted; 1 otherwise. After a re-install that prints "re-trust N hook(s)", repeat steps 2 and 3. When only script bytes changed, the installer says no re-trust is needed.
4. Optional, Astra: `codex --profile codex-astra`, then `/hooks` (its hooks are keyed by that file's path and need their own trust). Every session started with this profile runs the six top-tier agents (ninja-coder, main-coder, mathematician, planner, proof-checker, security-auditor) on `gpt-6-astra`, at **$10 input / $50 output per 1M tokens** (Sol: $2 / $10). `--no-astra-profile` skips the file.
5. Optional, `--ide-default`. The IDE extension and the desktop app cannot select a profile, so this flag writes the profile's content into two marked regions of `config.toml`. **It changes every Codex session on the machine**: the CLI without a profile, the IDE and the desktop app. Each session then starts as BlackCat (delegate-only), starts the stack's MCP servers, has web search off, and uses the stack's model defaults; a trusted project's `.codex/config.toml` can still override the region's keys. Review with `codex_config/install.sh --ide-default --dry-run`, apply with `--ide-default --yes` or an interactive `y`, run plain `codex` and trust the hooks whose source is `config.toml`, then restart the IDE. Undo: `codex_config/install.sh --no-ide-default` (cuts exactly the two regions and keeps every other edit in the file) or `--restore`. A re-run without either flag keeps the mode of the last install.
6. Optional, the managed tier. `codex_config/install.sh --print-requirements` writes `codex_config/build/requirements.toml` and a `managed-hooks/` copy of the guard, and prints the `sudo install` commands. **You** run those lines; the installer never runs sudo and never writes `/etc`. The tier is machine-wide: it changes every Codex session and profile on the machine (allowed sandbox modes and permission profiles, web search `disabled`, `deny_read` of the credential set, the forbidden push and forge rules, managed hooks in `--scope global` mode). An existing `/etc/codex/requirements.toml` is never replaced; a diff is printed for you to merge. Afterwards check `/debug-config` in `codex --profile codex`.

## `install.sh` options

| Option | Effect |
|---|---|
| `--dry-run` | Plan only; nothing is written (`CODEX_HOME` is created only when it is `~/.codex`). |
| `--diff` | Compare the rendered stack with the live `CODEX_HOME`, by area; change nothing. |
| `--restore [DIR\|latest]` | Put `CODEX_HOME` and the skill links back as before an install (default `latest`). |
| `--force` | With `--restore`: also put back saved symlinks that point outside `CODEX_HOME`. Otherwise: overwrite a `config.toml` region edited since the install. |
| `--force-config` | With `--restore`: restore `config.toml` although it changed since the install. |
| `--yes`, `-y` | Do not ask before changing anything. |
| `--no-prompt` | Never ask; a run that needs an answer stops unless `--yes` is given. |
| `--codex-home PATH` | `CODEX_HOME` (default `$CODEX_HOME`, else `~/.codex`). It must exist when given explicitly; `/`, `$HOME`, system and credential directories, anything inside `~/.claude` or this repository, and the stack's state, backup and cache roots are refused. |
| `--skills-root PATH\|none` | Where the skill links go (default `~/.agents/skills`; `none`: no links). |
| `--profile-name NAME` | Profile name. **Only `codex` works in this version**: the installer's file scope is fixed to `codex.config.toml` and `codex-astra.config.toml`. |
| `--no-agents-md` | Do not write the stack's block into `AGENTS.md`. |
| `--no-mcp` | Write no MCP servers. |
| `--legacy-sandbox` | `sandbox_mode = "workspace-write"` instead of the permission profile (credential reads are then not denied by the sandbox). |
| `--git-allow-rules` | Also write `allow` rules for the hook-free forms `git -c core.hooksPath=/dev/null add\|commit` and `merge --ff-only`. Those run unsandboxed in every session; the guard refuses file options, `-C`, `--exec-path` and alias overrides on them. |
| `--no-escalation` | `approval_policy = "never"`: the strongest mode; unsandboxed git then fails. |
| `--with-rollout-budget` | Set `features.rollout_budget = true`. An on/off switch only; the feature is under development in Codex and no limits are written. |
| `--ide-default`, `--no-ide-default` | Write or remove the two `config.toml` regions (see step 5); the first needs `--yes` or an answer `y`. |
| `--no-astra-profile` | Do not write `codex-astra.config.toml` and `stack/agents-astra/`. |
| `--print-requirements` | The optional managed tier (step 6); never runs the root commands. |
| `--doctor` | Hook trust, manifest drift, skill links; exit 1 if a stack hook is untrusted or a file drifted. |
| `-h`, `--help` | Usage. |

`--restore`, `--print-requirements` and `--doctor` are separate runs; `--diff` does not combine with them.

## Enforced and advisory

Codex hooks fail open (a timeout, crash or malformed answer does not block the tool), and hosted tools such as web search are not hookable. This is a guardrail against the sandboxed agent, not against you.

| Layer | What it does | Status |
|---|---|---|
| Sandbox | Workspace-write through the beta permission profile `claude-agent-stack`: `CODEX_HOME`, `~/.agents` and the guard state read-only, `deny` on `auth.json`, `stack.env` and the credential set, network allowlist | enforced (beta feature); partial with `--legacy-sandbox` |
| Shell environment | 12 credential variables (`GITHUB_TOKEN`, `GH_TOKEN`, `WANDB_API_KEY`, `HF_TOKEN`, ...) filtered out of the agent's shell via `shell_environment_policy.filters` | enforced if Codex honours the key (P-B3a, P-B3b) |
| Prefix rules | `forbidden` for push, `send-pack`, `lfs`/`subtree push`, forge writes (`gh`, `tea`, `fj`); `prompt` for git writes and `stack-install`. Global: they apply to every session | enforced; matches argv prefixes only (`git -C x push` is not matched by the rule; the guard covers it) |
| Guard hook | Once trusted, on PreToolUse, PermissionRequest, PostToolUse, SubagentStart, SubagentStop, UserPromptSubmit, SessionStart, SessionEnd: no push or forge write in any shell form, self-protection of `CODEX_HOME`, credential paths, per-role tool classes and spawn rows, BlackCat delegate-only, read-only roles, MCP allowlists and caps, one computer-use agent at a time, images up to 1920 px | enforced while the hooks are trusted and the profile is active. Per-caller policy depends on the undocumented `agent_type` field of PreToolUse; if it is absent every call looks like the main thread and is denied (fails closed) |
| Managed tier | Optional; machine-wide; trusted by policy | enforced (if installed) |
| Developer instructions, the `AGENTS.md` block, skills, BlackCat's prompt | Text the model reads | **advisory** |

Lost or reduced against the Claude stack: USER-consent stamping (advisory), status line, slash-command hooks, token budgets (`rollout_budget` is opt-in and has no per-agent attribution), `maxTurns` (the guard counts calls, not turns), `output_shrink` (only `tool_output_token_limit`).

### What the same-user agent can still bypass

Local files are writable by you and by processes running as you. Residual bypasses of the local tier:

1. Untrusted or "Modified" hooks do not run (see step 2; `--doctor` and the installer's last line are the only signals).
2. Opaque code: a user-approved escalation that runs a script, MCP servers, and commands under an `allow` rule all run unsandboxed.
3. You widening permissions: `--yolo`, `danger-full-access`, a wider `/permissions`, or `writable_roots` that cover `CODEX_HOME`. Children inherit these.
4. A trusted project's `.codex/config.toml` or `.codex/rules` can relax the sandbox, approvals or `features.hooks`.
5. A hook timeout fails open.
6. Hosted tools and tool paths that opt out of hooks.
7. Sessions without `--profile codex` have only the sandbox defaults, the global rules and the `AGENTS.md` block; `--ide-default` closes this for every session.

Do not start Codex with its working directory inside `CODEX_HOME`: that makes it a writable root.

## Restore and backups

Every run that changes something saves what it changes into one backup under `${XDG_STATE_HOME:-~/.local/state}/codex-agent-stack-backups/<timestamp>-<random>/` and prints the restore command; a run that changes nothing makes none, and none is ever deleted.

```
codex_config/install.sh --restore --dry-run     # what a restore would do
codex_config/install.sh --restore               # undo the latest install
codex_config/install.sh --restore <backup-dir>  # undo a given one
```

A restore undoes the skill links first, then `CODEX_HOME`, and prints how to undo itself. If `config.toml` changed since the install (Codex writes trust records, `[projects.*]` and `/model` there), the restore refuses unless `--force-config` is given; `--no-ide-default` is the safe way to remove the regions. After a restore that removed the stack, the interpreter link and the bytecode the install made outside the engine's scope are removed too.

## Decisions that differ from the Claude stack

- **Models.** The Opus tier maps to `gpt-6.1-sol` (43 agents) and the Sonnet tier to `gpt-6-luna` (14 agents). Sol keeps the stack's effort names. Luna runs one level above the stack's value, capped at `max` (`low` to `medium`, ..., `max` stays `max`). `none`, `minimal` and `ultra` are never used (`ultra` adds Codex's own proactive subagents). The mapping, the accepted effort sets and the Astra list live in `models.toml`; an effort a model does not accept stops the build. No agent uses Astra unless you start `codex --profile codex-astra`.
- **BlackCat is the profile's main thread** (`gpt-6-luna`, effort `high`), not a role.
- **Skills.** 127 are listed and 89 are hub modules. The four skills about Claude Code itself, `claude-code-extensions`, `override-agent`, `stack-doctor` and `stack-tree`, are not installed for Codex, and text that sent a reader to them is rewritten. `/override-agent` is replaced by the `codex-astra` profile. Skill frontmatter keeps `name` and `description`; `argument-hint` is dropped and any other key (including `disable-model-invocation`) is a build error.
- **Python.** No Codex text refers to the Claude stack's venvs; ad-hoc Python is `uv run --with <pkgs> python`.
- **MCP.** All servers are declared in the profile. The stdio servers read `<CODEX_HOME>/stack.env` only (not `~/.claude/stack.env`). The user-scope HTTP servers are `exa`, `jina`, `wolfram`, `huggingface`, and `wandb` only when `stack.env` has a non-empty `WANDB_API_KEY`; keyed ones use `http_headers_helper = "<CODEX_HOME>/stack/bin/codex-mcp-headers <id>"` (the output format Codex expects is unverified: P6b).
- **Role files** carry only `model`, `model_reasoning_effort` and `developer_instructions`; `description` lives in `[agents.<name>]`, because Codex's agent schema has no `name` or `description` keys in the file (P5 confirms).
- **Skills budget.** The listing budget (6000 tokens, `skills.max_context_tokens`) counts each skill's path. A very long `HOME` makes the paths longer and can fail the build with "skills listing ... > skills.max_context_tokens".
- **Rules and prompts** are rewritten with Codex tool names (`apply_patch`, `spawn_agent`, `send_input`, ...); a Claude tool name with no mapping fails the build with file and line.

## Guard latency

Target: p95 of one hook call below 100 ms, measured as Codex runs it (`/bin/sh <stub> <mode>`, a fresh interpreter per call, precompiled bytecode). Measured 2026-10-06 on macOS arm64 inside the Claude sandbox, n = 96 per run: uv CPython 3.13 about 38-41 ms, Apple's 3.9.6 82-87 ms (97-106 ms without precompiled bytecode). The `/usr/bin/python3` xcrun shim, which the stub falls back to and the managed tier uses, cannot be timed in that sandbox. Time it yourself, outside any sandbox:

```
CODEX_GUARD_PERF_SHIM=1 uv run --no-project --python 3.13 --with pytest python -m pytest -q -s -p no:cacheprovider codex_config/tests/test_guard_perf.py
```

## Tests

```
codex_config/tests/run.sh     # the Codex suite, then the Claude installer's own install tests
codex_config/tests/smoke.sh   # the installer end to end on a scratch HOME and CODEX_HOME (from a committed checkout)
```

Both run on a scratch `HOME` and `CODEX_HOME` with a fake `codex` that answers only `--version` and `execpolicy check`; no test reaches a real Codex. `smoke.sh` fingerprints the real `~/.codex`, `~/.agents` and the Codex state folders before and after and fails if any changed. Codex's own behaviour is checked only by the probes you run: `codex_config/probes/run.sh --list`.
