# dot-config/dot-codex_config (codex_config): design (Phase 1, no installer code)

Updated 2026-10-06 after the build: statements that the build changed are corrected below; install, flags and user steps are in [README.md](README.md).

Status: design for review, 2026-10-06. Branch `codex-design`, based on `main` at `6ecb003`.
Inputs: the researcher's mapping in `.claude-work/codex-feasibility.md`. This repo: `install.sh`, `lib/install_state.py`, `lib/claude_md_block.py`, `lib/stack_diff.py`, `dot-config/dot-claude/`.
Fact tags used below:
- **[docs]**: the official Codex or OpenAI pages listed in §11.
- **[src]**: openai/codex source at tag `rust-v0.160.1`, the latest release, published 2026-10-05.
- **[src-main]**: the same repo's `main` branch on 2026-10-06.
- **[schema]**: `codex-rs/core/config.schema.json` at that tag.
- **unverified**: everything else, and so stated where it appears.

User decisions applied:
1. Target the Codex CLI and the IDE extension.
2. Amended 2026-10-06. Enforcement lives locally in `CODEX_HOME`. `/etc/codex/requirements.toml` becomes an optional hardened tier: generated, off by default, installed by the user.
3. A dedicated profile, `codex --profile codex`.
4. Model tiers are Opus → GPT-6.1 Sol and Sonnet → GPT-6.1 Luna, with Astra only where justified.
5. Port all 57 agents and all 220 skills.
6. Added during the build (user decisions, 2026-10-06): no Codex text refers to the Claude stack's venvs (ad-hoc Python is `uv run --with <pkgs> python`, §8.2); the four skills about Claude Code itself are not installed for Codex (§8.3); `--profile-name` accepts only `codex` (§7.3).
7. Answers to Q1–Q3 (2026-10-06):
   - **Q1.** Sonnet → `gpt-6-luna` and Opus → `gpt-6.1-sol`. No agent uses Astra by default; an opt-in `codex-astra` profile is provided (§2.1).
   - **Q2.** `--ide-default` writes an installer-owned region in `config.toml`. It is off unless the flag is passed (§7.6).
   - **Q3.** Luna agents run one effort level above the stack's value; Sol keeps the same names (§2).

Two decisions had to change because the facts differ. Both are listed below and in §10.
- **Profiles are files, not tables.** "In Codex 0.134.0 and later, `--profile` no longer reads `[profiles.profile-name]` from `config.toml`" [docs config-advanced]. The profile is therefore the file `$CODEX_HOME/codex.config.toml`.
- **Model names.** "GPT-6.1 Luna" and "GPT-6.1 Astra" do not exist (§2). The user chose `gpt-6-luna` and `gpt-6.1-sol` (Q1).

## 1. Verified Codex facts, conflicts, and what stays unverified

### 1.1 Facts this design relies on

**Profiles**
- **F1 [docs config-advanced].** `--profile NAME` loads `~/.codex/config.toml`, then overlays `~/.codex/NAME.config.toml`.
  - Profile files use top-level keys.
  - Precedence: CLI/`-c` > project > profile > user > system.
  - The `features` subcommand doesn't accept `--profile` [docs dev-cmds].
- **F2 [src] `config_layer_source.rs`.** A profile is a `User { file, profile: Some(_) }` layer. Its config folder is CODEX_HOME, the same folder as the base user layer.
- **F3 [src] `hooks/engine/discovery.rs`.** Hooks are discovered as follows:
  - Inline `[hooks]` load from every config layer, the profile file included (`load_toml_hooks_from_layer`).
  - `hooks.json` loads once per config folder.
  - Consequence: hooks inline in `codex.config.toml` are **profile-scoped**, and `$CODEX_HOME/hooks.json` is **global**.
  - Hooks from the System layer (`/etc/codex/config.toml`) count as managed.
- **F4 [src] `exec_policy.rs` `load_exec_policy`.** Rules load from `<config folder>/rules/*.rules` for every layer. User and profile layers share CODEX_HOME, so **rules are global**, never profile-scoped.
- **F5 [src] `ext/skills/src/host_roots.rs`.** User skill roots are `$HOME/.agents/skills` and `$CODEX_HOME/skills`, the latter commented in the source as "Deprecated user skills location … kept for backward compatibility".
  - No skill root is per profile. Symlinked skill folders are followed [docs skills].
  - Conflict 1 in §1.2 is resolved here: use the documented `$HOME/.agents/skills`.

**Agents (roles)**
- **F6 [src] `core/src/agent/role.rs` (PR #39299, 2026-08-18).** An agent TOML can apply only these keys:
  - `developer_instructions`, `model`, `model_reasoning_effort`, `model_reasoning_summary`, `model_verbosity`, `personality`, `service_tier`;
  - `features` (disable-only, and only `shell_tool`, `apps`, `plugins`, `memory_tool`, `request_permissions_tool`);
  - `skills` (disable-only).
  - Quote: "Roles may customize the child or reduce its capabilities, but never replace the parent session's authority."
  - Consequence: **`sandbox_mode` and `mcp_servers` in an agent file are ignored.** This conflicts with [docs subagents]; see conflict 2.
- **F7 [docs subagents].** Role resolution and limits:
  - The role file's `model` and `model_reasoning_effort` override both spawn values and `[agents]` defaults.
  - A custom agent whose name equals a built-in (`default`, `worker`, `explorer`) shadows it.
  - Live `/permissions` and `--yolo` are reapplied to children.
  - `[agents]` keys [schema]: `enabled`, `max_depth` ("Ignored by V2"), `max_concurrent_threads_per_session`, `default_subagent_model`, `default_subagent_reasoning_effort`, `interrupt_message`.
  - `[agents.<name>]` keys [schema]: `description`, `config_file`, `nickname_candidates`. `config_file` paths resolve relative to the declaring file [docs config-ref].
- **F8 [src] `features/src/lib.rs`.** `multi_agent` is Stable and on by default. `multi_agent_v2` is Stable and **off** by default, so V1 is the default and `max_depth` applies.

**Hooks: payload and trust**
- **F9 [src] `hooks/src/schema.rs` and `core/src/hook_runtime.rs`.** `PreToolUseCommandInput` and `PermissionRequestCommandInput` carry optional `agent_id` and `agent_type`.
  - They are set only for thread-spawned subagents (`thread_spawn_subagent_hook_context`; a subagent with no role gets `"default"`).
  - They are absent on the main thread.
  - **Undocumented:** [docs hooks] lists them only for SubagentStart and SubagentStop.
  - This field is what makes per-caller policy enforceable (§4).
- **F10 [src-main] `multi_agents_spec.rs`.** `spawn_agent` input has `agent_type` (exposed when roles are configured), `message`/`items`, `fork_context` (V1), `model` and `reasoning_effort`.
  - **Hook tool names [src] `core/src/tools/registry.rs` `function_hook_tool_name`, `core/src/tools/mod.rs` `flat_tool_name`.** Only `spawn_agent` gets a canonical hook name. Every other namespaced tool is reported as `<namespace><name>` with no separator.
  - V1 multi-agent tools live in namespace `multi_agent_v1` (`multi_agents_spec.rs`), so hooks see `multi_agent_v1send_input`, `multi_agent_v1resume_agent`, `multi_agent_v1wait_agent` and `multi_agent_v1close_agent`. The wait tool is `wait_agent`, not `wait`.
  - V2-only names (`send_message`, `followup_task`, `list_agents`, `interrupt_agent`) are unused because V2 stays off (F8).
  - The hook `tool_name` is `spawn_agent`, matcher alias `Agent`. `apply_patch` has aliases `Edit|Write` [src-main `hook_names.rs`].
  - `Bash` and `apply_patch` pass `tool_input.command` [docs hooks].
- **F11 [docs hooks; src `discovery.rs`, `config_rules.rs`; src-main `tui/src/hooks_rpc.rs`].** Hook trust:
  - Non-managed hooks run only after `/hooks` trust.
  - Trust is stored as `[hooks.state."<source-path>:<event>:<group>:<handler>"] trusted_hash`, read from user and profile layers. `/hooks` writes it through `config/batchWrite` (key `hooks.state`, no explicit file).
  - The hash covers the **normalized definition** (event, matcher, handler: command, timeout, …), **not the script's bytes**.
  - A changed definition is "Modified" and is skipped until it is trusted again.
- **F12 [docs hooks].** Hook behaviour and coverage:
  - Multiple matching hooks run concurrently.
  - Deny is `permissionDecision:"deny"` or exit 2.
  - `updatedInput` is allowed only together with `allow`.
  - "a `PreToolUse` callback error, timeout, or malformed response can fail the hook without blocking the tool". This means fail-open.
  - Hosted tools such as WebSearch are not hookable.
  - "Treat tool hooks as a useful guardrail, not a complete enforcement boundary."
  - PermissionRequest can deny an escalation ("any `deny` wins").

**Rules, sandbox and permissions**
- **F13 [docs rules; src `exec_policy.rs`].** `prefix_rule` decisions:
  - `forbidden` maps to `ExecApprovalRequirement::Forbidden`, and that mapping does not depend on the sandbox. The call site was not traced, so whether every in-sandbox command is evaluated is **unverified** (probe P8).
  - `allow` means "Run the command outside the sandbox without prompting".
  - Allow rules are dropped for "cyber" models, while forbidden rules always apply [src `exec_policy/model_policy.rs`].
  - The TUI writes approvals to `~/.codex/rules/default.rules`.
  - Linear `&&`/`;`/`|` scripts are split. Scripts with substitutions or redirection are not.
- **F14 [docs security].** Sandbox defaults and protected paths:
  - `workspace-write` makes cwd plus `/tmp` and `$TMPDIR` writable.
  - `<root>/.git`, `<root>/.agents` and `<root>/.codex` are read-only inside any writable root.
  - [src `sandboxing/src/seatbelt.rs`] has **no** CODEX_HOME-specific rule. CODEX_HOME is read-only to the agent only because it is outside the writable roots (or, when cwd is `$HOME`, because `.codex` is protected).
- **F15 [docs permissions] (beta).** `[permissions.<name>]` permission profiles:
  - Keys: `extends` (`:workspace`/`:read-only`), `filesystem` path or glob → `read|write|deny` (special keys `:root`, `:minimal`, `:tmpdir`, `:workspace_roots`), `network.domains` (needs `features.network_proxy`).
  - Selected with `default_permissions`.
  - Prefer them over `sandbox_mode` from 0.138.0 [docs managed].

**Instructions, skills, MCP, models, managed tier**
- **F16 [docs agents-md].** A global `$CODEX_HOME/AGENTS.override.md` wins over `AGENTS.md` (first non-empty). The combined chain is capped by `project_doc_max_bytes` (32 KiB). No includes.
- **F17 [docs skills; schema].** The skills list uses at most 2% of the context window (8,000 characters if unknown). Codex shortens descriptions first, then omits skills.
  - `skills.max_context_tokens` sets the budget, "capped at 10000 tokens".
  - `[[skills.config]] {path, enabled, name}`.
  - Per-skill `agents/openai.yaml` with `policy.allow_implicit_invocation`.
- **F18 [schema].** MCP servers and tools:
  - `mcp_servers.<id>` keys include `http_headers_helper` (resolves the feasibility report's unverified "header helper"), `env_vars`, `bearer_token_env_var`, `enabled_tools`, `disabled_tools`, `default_tools_approval_mode` (`auto|prompt|writes|approve`), `omit_tools_from` (`direct|deferred|code_mode`).
  - `web_search = disabled|cached|indexed|live`.
  - `features.rollout_budget {limit_tokens, reminder_at_remaining_tokens, …}` is UnderDevelopment and off.
  - `allow_symlinked_codex_home` is read only from the host's base user config.
- **F19 [docs ide-settings].** The IDE extension reads `config.toml`. Its documented editor settings have **no profile selector**, and profiles are described as a CLI feature [docs config-advanced]. So `--profile codex` does not reach the IDE. Hence `--ide-default` (§7.6).
- **F20 [docs managed].** Requirements are applied in this order: `/etc/codex/requirements.toml`, then cloud, then legacy `managed_config.toml`, then MDM.
  - Supported keys: `allowed_approval_policies`, `allowed_sandbox_modes`/`allowed_permission_profiles` (0.138+), `[features]` pins, `[rules] prefix_rules` (prompt or forbidden), `[hooks] managed_dir` plus managed hooks, `allow_managed_hooks_only`, and an MCP allowlist.
  - Requirements are **machine-wide**: they apply to every session and every profile.
- **F21 [docs dev-cmds].** `codex execpolicy check --rules F … -- cmd` emits JSON (preview). `/debug-config` shows layers and policy sources (TUI only).
- **F22 [src] `core/src/tools/handlers/mcp.rs` `hook_tool_name`.** MCP hook names are `mcp__<server>__<tool>`: the namespace and the name are joined with `__`, and `mcp__` is added in front. A contract test pins the format.

### 1.2 Conflicts between docs and source

The source at the release tag wins.
1. **Skills location.** The env-var page says CODEX_HOME holds "skills". In the source that path is deprecated (F5). Decision: install listed skills under `$HOME/.agents/skills`.
2. **Agent-file keys.** [docs subagents] allows `sandbox_mode` and `mcp_servers` in agent files. The source drops them (F6).
   - Decision: read-only and per-agent MCP limits are enforced by the guard hook using `agent_type` (F9), not by agent files.
   - Every MCP server is declared once, in the profile.
3. **PreToolUse caller fields.** They are present in the source (F9) but undocumented. Decision: rely on them, pin the minimum Codex version, and add a contract fixture (§9).

### 1.3 Still unverified

Each item is resolved by a Phase 0 probe (§9) or stays documented as such.
- U1. Whether `/hooks` trust writes go to `config.toml` or to the active profile file (F11 names no file).
- U2. Whether hyphenated role names (`main-coder`) are accepted as `agent_type`. Fallback: map `-` to `_` everywhere.
- U3. Whether hooks run unsandboxed, which matters for the guard's state directory.
- U4. Whether a hook `command` is run through a shell or split into argv. The design uses `/bin/sh '<abs path>' <mode>`, which works either way.
- U5. Whether permission profiles from a profile layer apply; whether an explicit `"<CODEX_HOME>" = "read"` entry outranks a `:workspace_roots` write; and whether a `deny` on `<CODEX_HOME>/auth.json` outranks the `read` on CODEX_HOME. Probe P7 settles all three.
- U6. Whether a permission profile can grant `.git` write inside the sandbox (P7b, which decides the git policy in §4.3).
- U7. Whether `omit_tools_from=["direct"]` defers MCP tools to tool search as its schema text says.
- U8. Whether the global AGENTS.md counts toward `project_doc_max_bytes`. The global block is kept under 2 KiB anyway.
- U9. Whether the IDE extension reads `hooks.state` trust records written from the CLI's `/hooks`, and whether it shows its own hook-review prompt. Its config is the same `config.toml` (F19), so sharing is expected (§7.6).
- U10. Whether `matcher = ".*"` matches every tool name (regex semantics are inferred from the docs' examples).
- U11. Which "specialized tool paths" opt out of hooks [docs hooks].
- U12. Resolved: see F22.
- U13. Whether Codex's own `config.toml` writes (`/hooks` trust, `/model`, project trust) keep comment lines and append outside the stack's marked regions. Probe P12 checks this; the drift check in §7.6 covers either outcome.
- Added by the build (each has a probe entry in `probes/PROBES.md`, section "Probes added after the build"):
  - P6b: the output format Codex expects from `http_headers_helper` (the schema types it as a string; `codex-mcp-headers` prints one JSON object).
  - P2/U1 and U1b: which file `/hooks` writes trust into, and whether a changed hook definition shows as "Modified" against a recorded `trusted_hash`.
  - P12/U13 (extension): region markers survive `/model` and `/hooks` writes, and Codex appends after region B.
  - P-B3a, P-B3b: `shell_environment_policy.filters` against a user `exclude`, and whether exact names remove those variables.
  - P-B3c: `features.rollout_budget = true` without `limit_tokens`.
  - P-B3d: whether `features.hooks = true` is needed.
  - P5 (extension): role files without `name` and `description`, reached through `[agents.<name>].config_file`.
  - Managed hooks run from the managed directory; a JSON deny with exit 0 for PermissionRequest; the `spawn_agent` `tool_response` shape; the id keys of `send_input`, `wait_agent` and `close_agent`.
  - Guard latency outside the sandbox (the `/usr/bin/python3` shim).

## 2. Models and reasoning effort (verified 2026-10-06)

| User's name | Verified identifier | Status | Effort values (`model_reasoning_effort`) | API price per 1M tokens, in/out |
|---|---|---|---|---|
| GPT-6.1 Sol | **`gpt-6.1-sol`** | exists: CLI, IDE, API [docs models; api-sol] | Codex catalog: `low` (default), `medium`, `high`, `xhigh`, `max`, `ultra`. API: `low`…`max`, default `medium`; no `none` or `minimal` | $2 / $10 |
| GPT-6.1 Luna | **does not exist**. The API URL falls back to the models index; the current Luna is **`gpt-6-luna`** [api-luna] | name unverifiable | `gpt-6-luna`: Codex catalog `low`, `medium` (default), `high`, `xhigh`, `max`, without `none`. The API also accepts `none` | $0.10 / $0.50 |
| GPT-6.1 Astra | **withheld**. OpenAI said it would not release it (Gizmodo, 2026-09-29, secondary source). No API page; the current Astra is **`gpt-6-astra`** [api-astra] | name unverifiable | `gpt-6-astra`: Codex catalog `low` (default) … `max`, plus `ultra` | $10 / $50 |

Notes on the models:
- The effort sets come from Codex's own model catalog, `codex-rs/models-manager/models.json` at the pinned tag. That catalog, not the API page, decides what Codex accepts.
- `ultra` appears in the Sol and Astra sets. It is a mode that adds proactive subagents ("Ultra uses subagents…") [docs models]. It is **excluded explicitly**: the stack does its own delegation.
- **Astra is the flagship and the most expensive model, not a cheap tier.**
  - Astra costs 5× Sol, so it maps to the stack's `fable` column in `agent_effort.json` (above Opus).
  - No agent defaults to fable today.
  - Haiku is banned in the stack. The cheapest OpenAI tier, Luna, already fills the Sonnet slot, so nothing maps below Luna.
  - Decision (Q1): no agent defaults to Astra. It is opt-in through the `codex-astra` profile (§2.1).

**Mapping (decided: Q1 and Q3).**
- The `opus` tier maps to `gpt-6.1-sol` and the `sonnet` tier to `gpt-6-luna`.
- **Sol** keeps the stack's effort name one-to-one: `low`, `medium`, `high`, `xhigh`, `max` are all accepted.
- **Luna** runs one level higher: `low`→`medium`, `medium`→`high`, `high`→`xhigh`, `xhigh`→`max`, `max`→`max`. The rule is `luna_effort(e) = LEVELS[min(i(e)+1, i(max))]`, so it never goes above the highest level Luna accepts. This is the user's Q3 decision, consistent with OpenAI's "Start with High for Luna". It is not `agent_effort.json` rule v1: that rule caps at `xhigh` and applies only when an agent runs on a model weaker than its own.
- **`none` is never emitted.** The API accepts `none` for Luna, but Codex's catalog does not list it, and the stack has no level below `low` (its scale is `low…max`). The rule only ever raises the level. Sol rejects `none` and `minimal`; Astra's lowest level is `low`.
- **Validation.** An effort a model does not accept stops the build. The accepted sets are copied into `models.toml` from `models-manager/models.json` at the pinned tag, with `ultra` removed. A contract test compares them with a vendored copy of that file.
- **Single source.** `dot-config/dot-codex_config/models.toml` holds tier → id, the accepted effort sets, the Luna offset (`luna_effort_offset = 1`) and the Astra list (§2.1). Changing one line and re-running the installer is enough.

| Codex model | Effort | Agents (stack effort → Codex effort) |
|---|---|---|
| gpt-6.1-sol | max | ninja-coder |
| gpt-6.1-sol | xhigh | main-coder, mathematician, planner, proof-checker, security-auditor |
| gpt-6.1-sol | high | biochem-engineer, claude-code-engineer, code-reviewer, cuda-engineer, data-scientist, designer, dl-engineer, embedded-engineer, game-engineer, go-engineer, haskell-engineer, hpc-engineer, julia-engineer, jvm-engineer, llm-engineer, ml-engineer, mlx-engineer, node-engineer, orchestrator, plan-reviewer, procedural-3d-ui, python-engineer, quantum-engineer, researcher, robotics-engineer, rust-engineer, security-engineer, vfx-td (28) |
| gpt-6.1-sol | medium | cg-artist, frontend-engineer, image-director, mobile-engineer, motion-designer, rigger-animator, sculptor-painter, writer |
| gpt-6.1-sol | low | oracle |
| gpt-6-luna | xhigh | data-engineer, devops-engineer, verifier (high → xhigh) |
| gpt-6-luna | high | **blackcat (main thread: the profile's `model` and `model_reasoning_effort`)**, browser-operator, coder, doc-specialist, mcp-broker, test-engineer, toolsmith (medium → high) |
| gpt-6-luna | medium | build-fixer, claude-code-guide, explore, scout (low → medium) |

Total: 43 Sol and 14 Luna, 57 agents.
- No Luna agent reaches `max`: the stack's highest Sonnet-tier effort is `high`.
- `agents.default_subagent_model = "gpt-6-luna"` with `default_subagent_reasoning_effort = "high"` covers only built-in roles, which the guard refuses anyway.
- `/override-agent` (per-session model override) has no Codex hook event, so it is dropped. Its replacement is the `codex-astra` profile.

### 2.1 Opt-in `codex-astra` profile

Selected with `codex --profile codex-astra`; the file is `$CODEX_HOME/codex-astra.config.toml`.
- **What changes.** It maps the stack's top tier to `gpt-6-astra`: ninja-coder, the only `max` agent, and the five agents at `xhigh` on Opus (main-coder, mathematician, planner, proof-checker, security-auditor). The list is `models.toml` `astra.agents`.
- **Effort.** It comes from the `fable` column of `agent_effort.json` (the stack's tier above Opus: ninja-coder `max`, the other five `xhigh`), restricted to Astra's accepted `low…max`.
- **What stays.** Every other agent and BlackCat keep their `codex` settings (Sol or Luna as above).
- **Role files.** The swapped roles are `stack/agents-astra/<name>.toml`, which differ from `stack/agents/` only in `model` and effort.
- **Content of the profile file.** Profiles overlay `config.toml`, not each other (F1). So `codex-astra.config.toml` is a full copy of the `codex` profile with those six `[agents.<name>].config_file` entries pointed at `agents-astra`. Under `--ide-default` it holds only those six entries (§7.6).
- **Cost.** Astra is $10 input / $50 output per 1M tokens, 5× Sol ($2 / $10) and 100× Luna [api-astra]. The installer prints this when it writes the profile.
- **Off by default.** The file is installed (`--no-astra-profile` skips it), but nothing uses Astra unless the user starts a session with this profile.
- **Hook trust.** Trust keys include the source file's path (F11), so this profile's inline hooks are trusted separately: run `/hooks` once under `codex --profile codex-astra`.

## 3. What lives where

`$CODEX_HOME` is resolved as `--codex-home`, else `$CODEX_HOME`, else `~/.codex`. Profile `codex` means the file `$CODEX_HOME/codex.config.toml`.

| Item | Path | Scope | Notes |
|---|---|---|---|
| Profile: `model`, `model_reasoning_effort` (BlackCat), `approval_policy="on-request"`, `default_permissions` + `[permissions.claude-agent-stack]`, `[features]`, `[agents]` limits + 56 `[agents.<name>] {description, config_file}` (`config_file` is an absolute path), `[mcp_servers.*]`, inline `[hooks]` (guard), `developer_instructions` (rules R + BlackCat body), `web_search="disabled"`, `skills.max_context_tokens = 6000`, `tool_output_token_limit = 25000`, `[shell_environment_policy.filters]` | `codex.config.toml` | **profile only** | owned whole file; `hooks.state` carried over (§7.4) |
| 56 role files (BlackCat is the main thread, not a role) | `stack/agents/<name>.toml` | profile, through `config_file` | **not** in `agents/`, so roles do not leak into other sessions |
| `codex-astra` profile + 6 Astra role files | `codex-astra.config.toml`, `stack/agents-astra/` | profile `codex-astra` only | opt-in (§2.1) |
| `--ide-default` regions (off by default) | two marked regions in `config.toml` | **every session** (CLI, IDE, desktop app) | §7.6; removed by `--no-ide-default` or `--restore` |
| Guard: `codex-hook` stub, `codex_guard.py`, a copy of `stack_io.py`, `toolsmith_policy.py`, policy JSON (`agents.json`, `guard.json`), `stack-python` link | `stack/bin/`, `stack/hooks/`, `stack/policy/` | used by profile hooks | after the apply the installer links `stack-python` to a real interpreter binary (never `/usr/bin/python3`, an `xcrun` shim that fails under another name) and precompiles the guard into `stack/hooks/__pycache__` for `stack-python` and `/usr/bin/python3` |
| Helpers and MCP servers | `stack/bin/` (`with-stack-env`, `mcp-headers`, `codex-mcp-headers`, `stack-install`, `magg-private`), `stack/mcp/`, `stack/magg/` | used by the profile's `[mcp_servers]` | the MCP servers read `<CODEX_HOME>/stack.env` only; the `~/.claude/stack.env` fallback is removed from the Codex copies |
| Listed skills (127: hubs and standalones; the four skills about Claude Code itself are not installed, §8.3) | real files in `stack/skills/<n>/`, one symlink each in `$HOME/.agents/skills/<n>` | **global**: every Codex session and other `.agents` readers | no per-profile skill root exists (F5) |
| Hub modules (89; 220 shipped skills = 127 + 89 + the 4 excluded) | `stack/skill-modules/<n>/SKILL.md` | never listed; read by absolute path from the hub's table | the analogue of `user-invocable-only` |
| Rules | `rules/claude-agent-stack.rules` | **global** (F4) | only `forbidden`/`prompt` (§4.3); never `default.rules` |
| Global rules block G (about 1.5 KiB) | managed block in `AGENTS.md` | **global** | warns when `AGENTS.override.md` shadows it |
| Keys file | `$CODEX_HOME/stack.env` (0600; seeded only if missing) | read by the MCP wrapper | denied to the sandbox (F15). The engine checks the whole file mode only for the relative path `stack.env` (`install_state.py` `leaf`), so a `chmod 644` shows up as a change and is repaired |
| Manifest | `.stack-manifest.json` | — | sha256 per owned file, hook-definition fingerprints, link list, the region hashes |
| `hooks.json`, `agents/`, `rules/default.rules`; `config.toml` outside the regions | — | — | **never touched** |

Keys the build writes into the profile besides those named in the table (`templates/profile.base.toml`, `lib/render_profile.py`):
- `[features]`: `hooks = true`, `multi_agent = true`, `multi_agent_v2 = false`, `network_proxy = true` (dropped with `--legacy-sandbox`), and `rollout_budget = true` only with `--with-rollout-budget`.
- `[agents]`: `max_depth = 8`, `max_concurrent_threads_per_session = 128` (the stack's `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`), `default_subagent_model`, `default_subagent_reasoning_effort`.
- `[shell_environment_policy.filters]`: `"exclude"` for the 12 credential variables of `settings.json` `sandbox.credentials.envVars` (`GITHUB_TOKEN`, `GH_TOKEN`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`, `GITLAB_TOKEN`, `GITEA_TOKEN`, `FORGEJO_TOKEN`, `CODEBERG_TOKEN`, `HF_TOKEN`, `HUGGING_FACE_HUB_TOKEN`, `WANDB_API_KEY`, `JUPYTER_TOKEN`). It is the keyed form; the schema forbids it together with the legacy `exclude` list. How it combines with a user `config.toml`'s own policy is unverified (P-B3a, P-B3b).
- `--with-rollout-budget` is an on/off switch only: no limits are written, because the key names of `features.rollout_budget` are unverified (P-B3c).

## 4. Enforcement architecture

### 4.1 Layers

The local CODEX_HOME layer is the primary enforcement. Each later layer adds to the ones before.
- **L1 Sandbox.** Workspace-write through the beta permission profile, or `--legacy-sandbox`, which uses `sandbox_mode="workspace-write"`.
  - The profile has `extends=":workspace"`, explicit `"<CODEX_HOME>"="read"` and `"$HOME/.agents"="read"`, then `deny` for `<CODEX_HOME>/auth.json` (Codex's file credential store, which stays in use) and the credential set (the port of `settings.json` `sandbox.filesystem.denyRead`/`denyWrite` and the 33 `Read(...)` and 28 `Edit(...)` denies), and `network.domains` from the 49 allowed domains with `features.network_proxy=true`.
- **L2 Rules (global).** `forbidden` for the 34 `Bash(...)` denies (push, send-pack, `gh pr create|merge|review|comment`, `gh release …`, …). `prompt` for risky-but-legitimate commands.
  - Claude `allow` rules are **not** converted to Codex `allow`. Claude's allow means "no prompt, still sandboxed"; Codex's allow means "unsandboxed".
- **L3 Guard hook (profile).** `codex_guard.py` on PreToolUse, PermissionRequest, PostToolUse, SubagentStart, SubagentStop, UserPromptSubmit, SessionStart and SessionEnd. It enforces per-caller policy through `agent_type` (F9); see §5.
- **L4 Approval.** `on-request`. Every escalation goes through PermissionRequest, where the guard can deny before the user sees a prompt. `never` is offered as `--no-escalation`, the strongest mode, which breaks unsandboxed git (§4.3).
- **L5 Prompts.** Developer instructions, AGENTS block G and skills. Advisory only.
- **Optional managed tier (§4.5).** Root-owned, machine-wide; off by default.

### 4.2 Agent self-protection: the agent must not edit its own rules, hooks or config

- **Default protection.** CODEX_HOME is outside the writable roots, so `apply_patch` and shell writes there fail in the sandbox. When cwd is `$HOME`, `.codex` and `.agents` are protected paths (F14).
- **What the design adds:**
  - (a) The permission profile marks CODEX_HOME, `~/.agents` and the guard state directory `read` explicitly (U5). The guard's `protected_roots` (`policy/guard.json`) are CODEX_HOME, `~/.agents`, the guard state directory and the installer's backups root (plus the skills root when it lies elsewhere).
  - (b) The guard denies any `apply_patch` whose `*** Add/Update/Delete File:` or `*** Move to:` path resolves (against `cwd`, symlinks resolved) under a protected root.
  - (c) The guard denies shell commands that write, rename, chmod or delete a protected path (the port of agent_guard's Bash-level protected-path check), and any `-c`/`--config` or `--dangerously-*` passed to `codex` by the agent.
  - (d) PermissionRequest denies any escalation whose command touches a protected root or is a forge write.
  - (e) The installer refuses a CODEX_HOME that is inside the user's usual working trees (§7.2), and the README says not to start Codex with cwd inside CODEX_HOME. In that case CODEX_HOME *is* the writable root.
  - (f) The guard denies any shell, `apply_patch` or MCP path argument that resolves to `<CODEX_HOME>/auth.json`, and to `stack.env`. This is the second line behind the L1 `deny`.
  - (g) Hardening added by the security review of the build (`hooks/codex_guard.py`):
    - The read-only allowlist for read-only roles (a rewrite of `_ReadOnly`) counts a program named by path as the named tool only in fixed system directories, never when the directory or file resolves into scratch.
    - A recursive reader (`rg`, `grep -r`, archivers, `cp -r`, `find`, ...) is denied when its operand, or the working directory it runs in, is a directory that holds a credential (a strict ancestor of a listed path).
    - `codex` is refused with `-c/--config`, `-p/--profile`, `--yolo`, `--dangerously-*`, `--enable`, `--disable`, `--add-dir`, and with `-s/--sandbox` or `-a/--ask-for-approval` unless the value is a literal safe one (`read-only`, `workspace-write`; `untrusted`, `on-request`, `on-failure`). Long options match by prefix.
    - For git: `-c alias.<x>=`, `GIT_CONFIG_KEY_<n>`/`GIT_CONFIG_PARAMETERS` are read like aliases (a hidden push or `!cmd` is found); `-C` and `--exec-path` never hide the subcommand; a credential named by a file-reading option (`commit -F`, `-t`, `--pathspec-from-file`, including abbreviations and short clusters) is resolved against the `-C` directories and denied; an escalated or `--git-allow-rules` git may not carry `-C`, `--exec-path`, `--git-dir`, `--work-tree`, `--config-env`, `-c` keys that load config or name programs, or `GIT_*`/`EDITOR` in its environment.
    - Transports that run a command are treated as such: `--upload-pack`/`--exec` options of `fetch`, `pull`, `clone`, `ls-remote`, `fetch-pack`, `archive`, and `ext::` remotes.
- **`-c` overrides.** A user `-c hooks.state…` override can change hook state for one run, because SessionFlags layers are read for hook state ([src] `hooks/src/config_rules.rs`). Rule (c) stops the agent from launching `codex -c …` itself.
- **What trust protects.** Trust is keyed on the hook *definition* (F11). Editing `codex_guard.py` would change behaviour without a re-trust prompt, so the script stays under the protection of L1 and L3 (b–d) like the rest of CODEX_HOME. The trust records (`hooks.state`) sit in the same protected files.

### 4.3 Git without weakening the sandbox

`.git` is read-only in workspace-write (F14), so `git commit`, `merge --ff-only` and `worktree` need escalation. Codex `allow` rules are global (F4) and run unsandboxed, without the profile's guard in other sessions.
- **Default.** `prompt` rules for git write subcommands: the user approves.
- **`--git-allow-rules`.** Adds `allow` only for hook-free forms such as `git -c core.hooksPath=/dev/null commit …`. The guard additionally denies `-F/--file`, `-C`, `--exec-path` and `-c alias.*` arguments that would let an unsandboxed git read secrets or run code.
- **Preferred if probe P7b passes.** A permission-profile write grant on `.git` keeps git inside the sandbox and scoped to the profile.

The same reasoning puts `stack-install` (toolsmith) on `prompt`, not `allow`. The guard further restricts it to `agent_type == "toolsmith"` with `toolsmith_policy.py` checking the argv.

### 4.4 Hook trust: what the installer records and what the user does

- **Install step.** The installer writes the hooks inline in `codex.config.toml`. It stores a canonical fingerprint of each hook definition in the manifest, and prints the list of hook keys (`<abs path>:pre_tool_use:0:0`, …).
- **After install (user).** Run `codex --profile codex`. Codex warns that hooks need review; open `/hooks` and trust the stack's 8 entries.
- **Re-install.** When any fingerprint changed (command, path, timeout, matcher), the installer says "re-trust N hooks". When only script bytes changed, no re-trust is needed (F11), and the installer says so.
- **`--doctor`.** Reads `hooks.state` from `config.toml` and the profile files (tomllib, read-only). It lists keys with no trust record, or a trust record that no longer matches, and **exits non-zero** if any stack hook key is untrusted.
- **Installer's last line.** "The guard is INACTIVE until you trust its hooks: run `codex --profile codex`, then `/hooks`."

- **Not done.** The installer never writes `trusted_hash`. Doing so would replicate Codex's private hash and bypass the user's review. `--dangerously-bypass-hook-trust` is not recommended.

### 4.5 What the same-user agent can still bypass, and the optional managed tier

Local files are user-writable. This design enforces against the **sandboxed agent**, not against the user or other processes running as the user. Residual bypasses of the local tier:
0. **Untrusted or Modified hooks.** Codex registers only trusted or managed handlers ([src] `hooks/src/engine/discovery.rs`). Until `/hooks` trust, the guard does not run at all, and nothing reports this during the session. `--doctor` and the installer's last line are the only signals (§4.4).
1. **Code the guard cannot see.** A user-approved escalation that runs opaque code (`python x.py`); the MCP servers and `allow`-rule commands, which run unsandboxed.
2. **The user widens permissions.** `--yolo`, `danger-full-access`, a wider `/permissions`, or `writable_roots` covering CODEX_HOME. Children inherit these (F7).
3. **Repository content.** A *trusted* project's `.codex/config.toml` or `.codex/rules` can relax the sandbox, approvals or `features.hooks`. The agent cannot write that file (protected path), but a repository can ship it.
4. **Hook failure.** A hook timeout or crash fails open (F12). For the gating modes (PreToolUse, PermissionRequest) the `sh` stub exits 2 if Python or the guard is missing or the guard dies; the observe-only modes exit 0 in those cases. The guard's catch-all denies on internal errors, but a timeout cannot be caught.
5. **Unhooked tools.** Hosted tools, mitigated by `web_search="disabled"`, and tool paths that opt out of hooks (U11).
6. **Outside the profile.** Sessions without `--profile codex` have only L1 defaults, L2 rules and the AGENTS block. `--ide-default` closes this for every session (§7.6).

**Optional hardened tier (`--print-requirements`). OFF BY DEFAULT. MACHINE-WIDE: it changes EVERY Codex session on this machine, not just the stack's profile.**
- It writes `dot-config/dot-codex_config/build/requirements.toml` and a `managed-hooks/` copy of the guard, then prints the root commands. It never writes `/etc` and never runs sudo. The user accepted the machine-wide effect of the following keys (answer b, 2026-10-06).

The file contains:
- `allowed_sandbox_modes=["read-only","workspace-write"]` and the map `allowed_permission_profiles = { "claude-agent-stack" = true, ":workspace" = true, ":read-only" = true }`. Omitted profiles are denied. The built-in key spelling follows the permissions page and is unverified. Together with `allowed_approval_policies=["on-request","never"]` this forbids `danger-full-access`.
- `allowed_web_search_modes = ["disabled"]`: no hosted web search in any session ([src] `config/src/config_requirements.rs`).
- `[permissions.filesystem] deny_read = [<credential set>, "<CODEX_HOME>/auth.json", "<CODEX_HOME>/stack.env"]` (same source, `FilesystemRequirementsToml`). These reads are denied in every sandboxed session.
- `[features] hooks=true`.
- `[rules] prefix_rules` with the forbidden push and forge set.
- Managed `PreToolUse`/`PermissionRequest` hooks running the guard in `--scope global` mode: no-push, self-protection and credential paths only. A managed hook cannot tell which profile is active, so it carries no stack policy.
- `allow_managed_hooks_only=false`, which keeps the profile's hooks working.

The tier closes bypasses 2, 3 and 6 for those checks, machine-wide. It also makes bypass 0 moot for its own hooks, which are trusted by policy. Bypasses 1, 4 and 5 remain: the user owns the machine and root can always undo it.

## 5. Guard capability mapping (Claude guard → strongest Codex mechanism)

Status values:
- **E**: enforced locally.
- **E\***: enforced through the undocumented `agent_type` (F9).
- **P**: partial.
- **A**: advisory (prompt text only).
- **X**: lost.
- **M**: what the optional managed tier adds.

| Capability | Codex mechanism | Status | Residual (local) | M |
|---|---|---|---|---|
| No push / forge writes (all forms) | L2 `forbidden` (global) + guard Bash parser (port of agent_guard no-push: `bash -c`, `eval`, `$(…)`; `tests/test_no_push.py` corpus is the oracle) + PermissionRequest deny + sandbox network allowlist | E | opaque scripts, unsandboxed MCP; guard absent outside profile (rules still apply) | rules + managed hook |
| Self-protection of CODEX_HOME, `~/.agents`, state | §4.2 | E | §4.5 items 1–4 | pins sandbox, hooks |
| Credential and protected-path reads (`~/.ssh`, `~/.aws`, keychains, `.env`, `stack.env`, `<CODEX_HOME>/auth.json`) | permission profile `deny` (Seatbelt, beta) + guard path checks on Bash, `apply_patch`, local-file MCP args | E (beta); P with `--legacy-sandbox` (reads unrestricted) | unsandboxed MCP and `allow` commands | `deny_read` + managed hook |
| Spawn policy per caller (POLICY rows, leaves, no self-spawn) | guard on `spawn_agent`: caller `agent_type` (absent = main = blackcat row) × `tool_input.agent_type` | E\* | field removal makes all calls look main-thread, so the BlackCat gate denies them: **fails closed** | — |
| No generic or built-in agents | guard denies missing `agent_type`, `default`, `worker`, `explorer` | E | — | — |
| Model or effort escalation at spawn | role file's `model`/effort override spawn values (F7); guard also strips `model` and `reasoning_effort` (`updatedInput`) | E | — | — |
| Depth ≤ 8 | `agents.max_depth=8`, `features.multi_agent_v2=false` | E (native) | the user enabling V2 | pin feature |
| Fan-out and concurrency caps | `max_concurrent_threads_per_session` + guard spawn count per caller per prompt | E (approximate) | — | — |
| BlackCat delegate-only (main thread) | guard: no `agent_type` → only `spawn_agent`, the `MA_TOOLS` (`send_input`, `resume_agent`, `wait_agent`, `close_agent`, matched after stripping the `multi_agent_v1` prefix, F10), `update_plan`, `request_user_input`; at most 3 read-only shell calls per prompt (reset at UserPromptSubmit) | E\* | outside the profile, by design | — |
| Read-only roles (code-reviewer, security-auditor, verifier, plan-reviewer, claude-code-guide, proof-checker) | guard: deny `apply_patch`; shell limited to a read-only allowlist (port of `_ReadOnly`) | E\* (agent files cannot set `sandbox_mode`, F6) | shell classification is heuristic, as in Claude | — |
| Per-agent tool sets (`tools:` lines) | guard: no Write/Edit → deny `apply_patch`; no Bash → deny shell; no Agent → deny spawn; per-server MCP allowlist | E\* | every MCP schema is visible to all (deferred via `omit_tools_from`, U7) | — |
| `maxTurns` | guard tool-call cap per `agent_id` | P | counts calls, not turns | — |
| Token budgets, soft limits | `features.rollout_budget` (UnderDevelopment, opt-in `--with-rollout-budget`) | P / A | no per-agent attribution | — |
| MCP call cap | guard counter per `session_id` (shared by subagents) and per `agent_id` | E | — | — |
| `web_caps` | `web_search="disabled"`; web through MCP (jina, exa, spider), which the guard caps; sandbox network allowlist | E | — | `allowed_web_search_modes` |
| Web taint → memory | guard denies `nmem_remember` for researcher, scout, browser-operator | E\* | propagation through reports and `send_input`: P (spawn tree from PostToolUse(spawn_agent), Phase 4b) | — |
| SendMessage routing and resume policy | guard on `multi_agent_v1send_input` / `multi_agent_v1resume_agent` (canonical `send_input`/`resume_agent` after prefix strip, F10) against the spawn tree | P | the tree is built by the hook | — |
| USER-consent stamping | none | A | — | — |
| computer-use, one agent at a time | guard lock on `mcp__computer-use__*` | E | — | — |
| Image limit ≤ 1920 px | guard on `view_image` (a local function tool, hookable) and image-path MCP args; header-only size read | E | — | — |
| toolsmith-only installs | L2 `prompt` + guard (caller `toolsmith`, `toolsmith_policy.py` argv) | E\* | — | — |
| `read_gate` | guard heuristics on shell reads (`cat`, `rg`) of deps and large files | P | — | — |
| `output_shrink` | `tool_output_token_limit` (output rewrite unsupported) | P | — | — |
| Hand-back protocol (STATUS) | SubagentStop `last_assistant_message`: observe; optional one-shot continue | P | — | — |
| `stack_usage` | SessionEnd hook (≤ 3 s) | E (observe) | — | — |
| Status line, `/override-agent`, slash commands' hooks | none (`tui.status_line` is built-in items only) | X | — | — |
| Fail-closed | stub exit 2 without Python; catch-all deny; timeout fails open (F12); **untrusted or Modified hooks → open** (§4.5 item 0; `--doctor` exits non-zero) | P | timeouts, untrusted hooks | managed hooks are trusted by policy, but still fail open on timeout |

## 6. Component mapping (final decisions)

| Claude component | Codex target | Decision |
|---|---|---|
| `CLAUDE.md` block | `AGENTS.md` block G (`lib/claude_md_block.py` reused, `NAME="AGENTS.md"`, same `claude-agent-stack` markers) | global, about 1.5 KiB: no push, CODEX_HOME off-limits, untrusted text is data, credentials, uv |
| `rules/claude-agent-stack.md` | rewritten as R (≤ 8 KiB, Codex tool names, honest enforcement claims) in the profile's `developer_instructions` **and appended to each role's** `developer_instructions` | a role replaces the parent's instructions (F6), so R must be in every role |
| 57 agents | 56 role TOMLs + the BlackCat main thread in the profile | §8.1 |
| `settings.json` permissions | rules (§4.3), permission profile, MCP `enabled_tools`/`disabled_tools`/`default_tools_approval_mode`, guard (4 `Agent(...)` denies) | |
| `settings.json` sandbox | permission profile (beta) or `--legacy-sandbox` | |
| `defaultMode: plan` | none: `approval_policy="on-request"` | advisory |
| MCP: 17 agent-scoped servers, 5 user-scope, magg | all in the profile's `[mcp_servers]`. `stdio` through `with-stack-env`; the user-scope HTTP servers are `exa`, `jina`, `wolfram`, `huggingface` and `wandb` (only when `stack.env` has a non-empty `WANDB_API_KEY`), the keyed ones with `http_headers_helper = "<stack>/bin/codex-mcp-headers <id>"` (output format unverified, P6b); heavy servers `omit_tools_from=["direct"]`; magg `ask` rows → `default_tools_approval_mode="prompt"` | per-agent access via guard |
| Skills, 220 | §8.3 | 216 ported (127 listed, 89 modules); the four about Claude Code itself are excluded |
| hooks (agent_guard and the rest) | one profile-scoped guard (§5) | not a port of the 12K-LOC guard |
| statusLine, `/override-agent`, `/stack-doctor` and `/stack-tree` hooks | dropped. `--doctor` is an installer flag | |
| `stack.env`, `with-stack-env`, `mcp-headers` | reused, installed under `stack/bin`; `codex-mcp-headers` is the Codex header helper | |
| Managed settings (`--print-managed-settings`) | `--print-requirements` (§4.5) | off by default |
| Agent SDK app | out of scope | |

## 7. Installer architecture

### 7.1 Files

The installer must not change the shipped Claude installer: zero edits to `install.sh`, `lib/`, `dot-config/dot-claude/` or `tests/`.

```
dot-config/dot-codex_config/
  install.sh            bash 3.2; flags §7.3; orchestration only (~600–800 lines)
  models.toml           tier → model id (§2)
  templates/            AGENTS.block.md (G), rules.md (R), blackcat.md, profile.base.toml, guard.base.json
  lib/codex_state.py    loads ../../lib/install_state.py BY PATH and sets its module constants (§7.2)
  lib/codex_home.py     CODEX_HOME resolution and refusal list
  lib/toml_emit.py      minimal TOML emitter (§7.5)
  lib/convert_agents.py lib/convert_skills.py lib/convert_rules.py lib/render_profile.py
  lib/render.py        one staged CODEX_HOME from the sources; lib/doctor.py, lib/codex_diff.py, lib/requirements.py,
                       lib/permissions.py, lib/hook_defs.py
  bin/codex-mcp-headers  the http_headers_helper
  lib/skill_links.py    the $HOME/.agents/skills symlink manager (second root)
  lib/translate.py      Claude tool-name table (§8.2); unmapped → error, never a guess
  hooks/codex_guard.py hooks/codex-hook (POSIX sh stub), hooks/SUPPORT_FILES
  probes/               Phase 0 probe kit, run by the user (§9)
  tests/                pytest + fake codex + smoke.sh (§9)
```

### 7.2 Reusing `lib/install_state.py`: copy or generalize

- **Measured blast radius.** The engine functions are generic apart from module-level constants: `SCOPE_DIRS`, `SCOPE_FILES`, `EXCLUDED`, `WRITE_THROUGH`. The engine covers stage, `make_plan`, `print_plan`, `apply_plan` (drift check, O_NOFOLLOW backups), `restore`, `ensure_root` and `new_backup_dir`. The config-dir resolver (`resolve_config_dir`, `.claude.json`, `CLAUDE_CONFIG_DIR`) and `validate()` are Claude-specific.
- **Decision: reuse by path, with no edits.** `codex_state.py` imports the file with `importlib.util.spec_from_file_location`, as install_state already does for `stack_io.py` to avoid the CWE-427 `sys.path` issue. It runs in its own process and assigns:
  - `SCOPE_DIRS=("stack",)`;
  - `SCOPE_FILES=("codex.config.toml","codex-astra.config.toml","config.toml","rules/claude-agent-stack.rules","AGENTS.md","stack.env",".stack-manifest.json", the matching ".tmp" names)`. `config.toml` is **always** in scope, because otherwise older backups would fail `in_scope` on restore. Staging copies it unchanged, so it appears in a plan only when a region changes;
  - `EXCLUDED=("stack/hooks/__pycache__","stack/bin/stack-python")`. The guard state lives in `~/.local/state/codex-agent-stack`, outside CODEX_HOME;
  - `WRITE_THROUGH=("stack.env",)`, so a dotfiles link is written through, as in the Claude installer.
- **What codex_state provides itself:** `validate()` (TOML parses, required role keys, no placeholders, policy JSON schema) and `resolve_codex_home()`. The latter reuses the module's `HOME_INSIDE`, `SYSTEM_INSIDE`, `HOME_EQUAL` and `_inside`.
  - It refuses `/`, `$HOME`, system directories, anything inside `~/.claude` or the repository, the backup roots, and paths with `BAD_PATH_CHARS` or `'`.
  - CODEX_HOME must exist when it is set explicitly (Codex's own rule). The default `~/.codex` is created with mode 0700.
- **Backups.** They go to `${XDG_STATE_HOME:-~/.local/state}/codex-agent-stack-backups`, separate from the Claude installer's.
- **Engine output is worded for Claude.** `codex_state` wraps `print_plan`: it passes a plan copy whose `changed` list leaves out the `stack/agents/` and `stack/skills/` entries, the analogue of the engine's `agents/`/`skills/` summary. It also maps engine `SystemExit` texts (`install.sh --restore: …`, `set CLAUDE_CONFIG_DIR`) to Codex wording.
- **Contract tests.** They pin every engine name and signature used (`inspect.signature`), so a future Claude-side refactor that breaks this coupling fails in `dot-config/dot-codex_config/tests`. There is no CI in this repo. Both suites are run by `dot-config/dot-codex_config/tests/run.sh` and are part of Phase 5's done-when.
- **Rejected options:**
  - (a) A shared generalization through a target descriptor: it re-opens the C7/CWE review and risks the 281 Claude tests. Revisit only after both installers are stable.
  - (b) A copy: two security-reviewed engines would drift apart.
- **Source snapshot (`lib/source_snapshot.py`, about 140 lines; a port of `install.sh`'s snapshot block).**
  - It does one O_NOFOLLOW read of the HEAD-tracked files that the run reads or executes, into `$WORK/src`: `dot-config/dot-codex_config/`, `lib/install_state.py`, `lib/claude_md_block.py`, and `dot-config/dot-claude/` (including `hooks/stack_io.py`, `hooks/toolsmith_policy.py`, `hooks/agent_effort.json`, agents, skills and rules).
  - It uses the same git hardening and supply review as the Claude installer.
  - Every later step, including `codex_state`'s by-path import of `install_state.py`, reads the copy, never the repository.
  - Security review is required. Proof test: an edit to `lib/install_state.py` made after the snapshot point is never executed.

### 7.3 Flags and flow

- **Flags:**
  - `--dry-run` and `--diff` (a codex area list for `stack_diff`-style read-only comparison);
  - `--restore [DIR|latest] [--force]`, `--yes`, `--no-prompt`;
  - `--codex-home PATH`, `--skills-root PATH|none`, `--profile-name NAME` (default `codex`; **only `codex` works in this version**, because the engine's file scope is fixed to `codex.config.toml` and `codex-astra.config.toml`);
  - `--no-agents-md`, `--no-mcp`, `--legacy-sandbox`, `--git-allow-rules`, `--no-escalation`, `--with-rollout-budget` (an on/off switch, §3);
  - `--print-requirements`, `--doctor`, `--ide-default` / `--no-ide-default` (§7.6), `--no-astra-profile`.
- **Python.** Steps run under the same interpreter resolution as `stack-hook` (`$STACK_PYTHON`, else `uv python find … 3.13`), because `tomllib` needs Python 3.11 or later. Stdlib only. `codex_guard.py` itself stays Python 3.9-compatible, because managed hooks use `/usr/bin/python3`.
- **Flow.** Each step runs only if the previous one succeeded.
  1. Snapshot the sources.
  2. Resolve and check CODEX_HOME, then check `codex --version` ≥ 0.160.1 when Codex is on PATH (otherwise warn and skip the Codex checks).
  3. Stage CODEX_HOME.
  4. Render: models, roles, skills, rules, profile, guard and AGENTS block.
  5. Validate:
     - TOML via tomllib;
     - `codex execpolicy check` on every rule's `match`/`not_match` examples;
     - guard self-test: pipe synthetic PreToolUse JSON through the stub; a push must be denied and a read allowed;
     - skills-listing budget estimate.
  6. Plan; stop here under `--dry-run`.
  7. Back up and apply through the engine.
  8. Apply the skill-link plan, recording old targets in the same backup directory as `skill-links.json`.
  9. Link `stack/bin/stack-python` to the real binary of the installer's interpreter (refusing `/usr/bin/python3`), precompile the guard for `stack-python` and `/usr/bin/python3` (checked-hash pycs), print the hooks that need re-trust.
  10. Print the user steps: `/hooks` trust, `codex --profile codex`, the AGENTS.override warning.
- **Restore** undoes the links first, then calls the engine's restore.

### 7.4 Owned-file merges

- `codex.config.toml` is owned whole.
- The render carries over each live profile file's `[hooks.state]` table, parsed with tomllib and re-emitted, in case `/hooks` writes trust there (U1). It is carried into every profile file, including the comment-only `codex.config.toml` and the six-entry `codex-astra.config.toml` of `--ide-default` mode (their keys embed the source path, so each file keeps its own records). `--doctor` reads `hooks.state` from `config.toml` and both profile files. Stale hashes then show as "Modified" in `/hooks`, which is correct.
- Any other foreign table found in the live file stops the run, naming the table. The check is deep: a key or table the user added under a stack-written root (`[mcp_servers.mine]`, an extra `[[hooks.PreToolUse]]` handler) also stops it, naming its dotted path. When Codex re-trusts a key in only one profile file, the record of the file the key names wins. The user's own settings belong in `config.toml`.

### 7.5 Writing TOML

stdlib has no TOML writer, and `tomli_w` would add a runtime dependency to a stdlib-only installer, so the emitter is in-repo: `lib/toml_emit.py`, about 150 lines.
- It handles str, int, bool, lists of scalars, tables and arrays of tables, with deterministic key order and quoted keys where needed.
- `developer_instructions` is written as a `'''…'''` literal string when the text contains no `'''` or control characters, and as an escaped basic string otherwise.
- It refuses floats NaN/inf, datetimes and None.
- It is proven by round-trip tests (`tomllib.loads(emit(x)) == x`) over a seeded random corpus.

### 7.6 `--ide-default`: a stack region in `config.toml` (opt-in, Q2)

The IDE and the desktop app read `config.toml` and cannot select a profile (F19). `--ide-default` therefore writes the profile's content into `config.toml`. It is off unless the flag is passed.

**What lands there.** TOML cannot return to the root table after a table header, so there are two marked regions:
- **Region A**, at the very start of the file, holds root keys only:
  - `model` and `model_reasoning_effort` (BlackCat: `gpt-6-luna`, `high`);
  - `approval_policy`;
  - `default_permissions` (or `sandbox_mode` under `--legacy-sandbox`);
  - `developer_instructions` (R plus BlackCat);
  - `web_search`, `tool_output_token_limit`.
- **Region B**, at the end of the file, holds tables only:
  - `[features]`;
  - `[agents]` and the 56 `[agents.<name>]` entries;
  - `[mcp_servers.<id>]`;
  - `[permissions.claude-agent-stack…]`;
  - `[skills]` `max_context_tokens`;
  - the guard's `[[hooks.<Event>]]` groups.
- **Already global, so not in the regions:** the rules file, the AGENTS block and the skill links (§3).
- **The profiles shrink in this mode.**
  - `codex.config.toml` becomes a comment-only file, so `--profile codex` still works.
  - `codex-astra.config.toml` holds only its six `config_file` overrides.
  - Neither carries `[hooks]`: hooks load from every layer (F3), so the guard would otherwise run twice.

**Mechanics** (`lib/config_region.py`, patterned on `claude_md_block`):
- **Markers.** Whole-line comments `# >>> claude-agent-stack: begin A|B (install.sh --ide-default rewrites this region) >>>` and `# <<< claude-agent-stack: end A|B <<<`.
  - Exactly one pair per region must exist. Otherwise the run stops and the file is untouched.
  - Bytes outside the regions are never changed.
- **Conflict check.** Before apply, `tomllib.loads(result)` must equal `merge(tomllib.loads(user part), stack part)`, with no key defined on both sides.
  - Any overlap (a user `model`, `approval_policy`, `[features]` or `[agents]`) stops the run and names the keys.
  - So do keys the vendored schema forbids together: a user `shell_environment_policy.exclude` or `include_only` against region B's `shell_environment_policy.filters`.
  - The installer never edits the user's keys.
- **Drift.** The manifest stores each region's sha256.
  - A region that changed since install stops the run with a diff; `--force` overwrites it. Typical causes: Codex's `/model` or the IDE settings panel writing `model` in place, or a hand edit.
  - Codex rewrites `config.toml` itself (`[hooks.state]` trust, `[projects.*]`, `/model`). Whether those writes keep comment markers and where they insert keys is U13.
- **Backup.** `config.toml` is always in the engine's scope (§7.2). The engine backs up the whole file before every apply that changes it, and the manifest records its post-install sha256.
- **Removal.**
  - `--no-ide-default` cuts both regions out exactly, keeping every later edit by the user or Codex, and restores the full profile files.
  - `--restore`: `codex_state` compares the live `config.toml` sha256 with the post-install value in the manifest.
    - If they differ (Codex writes trust, project or model keys), the restore **refuses unless `--force-config`** and names `--no-ide-default` as the safe alternative.
    - The engine's own `--force` (out-of-dir symlinks only, `install_state.restore`) is passed only when the user gives `--force`.
    - The engine's drift check compares only within one run, so it does not cover this case.

**Trust.**
- The region's hook keys are `<CODEX_HOME>/config.toml:<event>:<g>:<h>`. Trust them once from plain `codex` → `/hooks`.
- The IDE shares `config.toml`, and therefore `hooks.state`; whether it also shows its own review prompt is U9.
- Until the hooks are trusted, the guard does not run in any session. The region's other keys (sandbox, approvals, model) and the global rules still apply.

**Risk.** The flag changes **every Codex session on this machine**: the CLI without a profile, the IDE extension, and the ChatGPT desktop app, which all share `config.toml` [docs models]. The installer states this and requires `--yes` or an interactive "y". In practice:
- each session starts as BlackCat, delegate-only, so quick IDE edits are delegated to a subagent;
- the stack's MCP servers start in each session, which adds startup time and needs the `stack.env` keys;
- web search is off and the stack's model and effort defaults apply;
- a trusted project's `.codex/config.toml` can still override the region's keys, because the project layer ranks above the user layer (F1).

## 8. Converter specs

### 8.1 Agent `.md` → role `.toml`

| Frontmatter or part | Codex |
|---|---|
| `name` | the role name in the profile's `[agents.<name>] description, config_file=<absolute path of stack/agents/<name>.toml>` (hyphens pending U2); **not** a key of the role file |
| `description` | `[agents.<name>].description`; the role file carries no `description` |
| `model` (`opus`/`sonnet`) | `model` from `models.toml` (§2) |
| `effort` | `model_reasoning_effort` (identity; clamped to the model's accepted set) |
| `maxTurns` | `policy.json` per-agent tool-call cap (§5) |
| `tools` | Write/Edit/Bash/Agent and `mcp__<srv>` → `policy.json` (tool classes, MCP allowlist); Agent targets come from the body's "May spawn:" line (blackcat: its `Agent(...)` list); prompts translated (§8.2) |
| `mcpServers` | merged into the profile's `[mcp_servers]` (`__UV__`/`__CLAUDE_DIR__` rendered to `stack/mcp` paths); the same id with different settings stops the build |
| `permissionMode`, `color`, `memory`, `experimental`, `omitClaudeMd` | dropped (recorded in the build report) |
| `hooks` (blackcat) | → the guard's BlackCat main-thread gate |
| body | `developer_instructions` = translated body + `\n\n` + R |

A role file therefore holds only `model`, `model_reasoning_effort` and `developer_instructions`: the vendored `config.schema.json` (`additionalProperties: false`) has no `name` or `description` there. That Codex accepts such a file is probe P5's extension.

The spawn policy is derived from the same sources that `tests/lint_agents.py` checks against `agent_guard.POLICY`. A test imports `agent_guard.py` by path and asserts that the derived JSON equals POLICY, LEAVES and READONLY_TYPES. That keeps one source of truth without executing agent_guard at install time.

### 8.2 Claude tool names in prompts and skills (`lib/translate.py`)

| Claude | Codex text |
|---|---|
| Read, Grep, Glob | shell `sed -n`, `cat`, `rg`, `rg --files` |
| Write, Edit, NotebookEdit | `apply_patch` |
| Bash, Monitor | shell; long runs with background exec and polling |
| Agent (`subagent_type`) | `spawn_agent` (`agent_type`, `message`) |
| SendMessage | `send_input` / `resume_agent` |
| TaskStop | `close_agent` |
| SubagentHandback | "end your turn with the report" |
| Skill | "open the skill's SKILL.md (path in the skills list)" |
| WebSearch, WebFetch | `mcp__jina__search_web`, `mcp__exa__web_search_exa`, `mcp__jina__read_url` |
| EnterWorktree, ExitWorktree | `git worktree add` / `remove` |
| AskUserQuestion | `request_user_input` if enabled (experimental), else ask in the reply |
| ToolSearch, LSP, Artifact, Workflow, Cron\*, ScheduleWakeup, RemoteTrigger, PushNotification, SendUserFile, ListAgents, ExitPlanMode | dropped; the sentence is rewritten |
| `~/.claude/...`, `__CLAUDE_DIR__` | `<CODEX_HOME>/stack/...` |
| `<claude dir>/venvs/<v>/bin/python`, prose about the shared venvs | `uv run --with <pkgs> python`, with the packages the sentence or code block names, else a default per venv (`sci`: numpy, scipy; `ml`: torch; `tools`: pytest). No Codex text names the Claude stack's venvs (user decision); a surviving `venvs/` path fails the build |

Tokens with no mapping fail the build with file:line. Sentences that claim "hook-enforced" are rewritten to match §5's status column. That rewrite is writer work, checked by a lint for forbidden phrases.

### 8.3 Skills: hub/module convention and the listing budget

- **Listed set (127).** Everything that is neither a hub module nor excluded, from the same classification as `settings.json` `skillOverrides` and `tests/test_skill_modules.py`.
  - The 31 `LISTED_CORE` skills keep their full description (frontmatter line ≤ 148 characters today).
  - The other 96 get a ≤ 60-character description generated from the first clause, mirroring Claude's `name-only`.
  - The build counts one line per skill (`- name: description (file: path)`, 4 characters per token) and **fails** when the listing exceeds `skills.max_context_tokens = 6000` (under the 10 K cap). The count includes the absolute paths, so a very long `HOME` can fail the build.
- **Excluded (4, user decision).** `claude-code-extensions`, `override-agent`, `stack-doctor` and `stack-tree` describe Claude Code itself and are not installed for Codex; no module is reachable only from them (`classify` reports 0 excluded modules). Sentences that send the reader to one of them are rewritten; `/override-agent` is replaced by the `codex-astra` profile (§2.1).
- **Hub modules (89).** Installed to `stack/skill-modules/`, never in a scanned root. Hub tables are rewritten to absolute paths. `tests/test_skill_modules.py`'s reachability check is mirrored on the output.
- **Frontmatter.** `name` and `description` are kept. `argument-hint` is dropped. Any other key is a build error, including `disable-model-invocation`: its only users were the excluded skills, so the mapping to `agents/openai.yaml` (`policy.allow_implicit_invocation: false`) is gone.
- **Text.** The text pass (§8.2) covers 38 files that name Claude tools and 45 that reference `~/.claude`.
- **Links.** One symlink per listed skill in `$HOME/.agents/skills`. An existing entry that is not ours (not in the manifest, or not a link into `stack/skills`) stops the run with its name. The run never overwrites or prunes foreign entries.

### 8.4 Rules → AGENTS block, developer instructions, `prefix_rule`

- G and R are rendered from `templates/`. R is about 8 KiB; it is the original 11.5 KiB minus Claude mechanics (BlackCat hook caps, SubagentHandback, `mcp__` routing through mcp-broker as written for Claude).
- `rules/claude-agent-stack.rules`:
  - one `prefix_rule(pattern, decision="forbidden", justification, match, not_match)` per converted `Bash(...)` deny, with `*` globs expanded into union tokens where finite;
  - `prompt` rules for git writes and `stack-install` (§4.3).
- `codex execpolicy check` must agree with every `match` and `not_match` example at install time.

### 8.5 Guard (`hooks/codex_guard.py`, a few hundred lines, stdlib, Python ≥ 3.9)

- **Hook commands.** `"/bin/sh '<CODEX_HOME>/stack/bin/codex-hook' <mode>"`, one matcher group `".*"` per event, timeout 10 s (SessionEnd 3 s).
- **State.** Kept under `~/.local/state/codex-agent-stack/<session_id>/`, outside CODEX_HOME. Writes use `fcntl.flock` and the atomic writes of the installed `stack_io.py` copy, because hooks run concurrently (F12).
- **No-push reuse.** If agent_guard's no-push predicate is a pure function, it is imported by path. Otherwise it is ported, with `tests/test_no_push.py`'s corpus as the oracle.
- **Global mode.** `--scope global` runs only the profile-neutral checks, for the managed tier.

## 9. Phased build plan, tests, reviews, user steps

| Phase | Work | Owner | Done when |
|---|---|---|---|
| 0 | Probe kit `probes/run.sh` (scratch `CODEX_HOME`, user logs in there). The user runs it and pastes the JSON report. Probes:<br>P1 profile hooks fire only with `--profile`<br>P2 where `/hooks` writes trust (U1)<br>P3 `agent_type` in a subagent's PreToolUse<br>P4 hyphenated roles<br>P5 roles via `[agents.x].config_file`<br>P6 profile MCP servers<br>P7 permission profile from the profile file: CODEX_HOME is readable and not writable, reading `<CODEX_HOME>/auth.json` fails (settles U5)<br>P7b `.git` write grant<br>P8 `forbidden` blocks an in-sandbox `git push`<br>P9 hooks unsandboxed<br>P10 symlinked skills listed<br>P11 IDE ignores the profile and reads `hooks.state` from the CLI's trust (U9)<br>P12 `/hooks`, `/model` and project-trust writes against a file with stack regions (U13)<br>P13 the PreToolUse `tool_name` of each multi-agent tool, `update_plan`, `request_user_input` and `view_image`<br>Added after the build, manual entries in `probes/PROBES.md` (not in `run.sh`): P6b `http_headers_helper` output; P2/U1 and U1b trust file and "Modified"; P12/U13 markers and append position; P-B3a to P-B3d shell filters, `rollout_budget`, `features.hooks`; P5 role files without `name`/`description`; managed hooks from the managed directory; JSON deny with exit 0; `spawn_agent` `tool_response`; id keys of `send_input`/`wait_agent`/`close_agent`; guard latency outside the sandbox | main-coder (kit); **user** (run) | report committed; §1.3 updated |
| 1 | This design | main-coder | Q1–Q3 answered (2026-10-06); plan-reviewer PASS |
| 2 | `toml_emit`, `codex_home`, `source_snapshot`, `codex_state` (engine by path, plan/restore wording), `skill_links`, `config_region` (§7.6) | python-engineer; tests by test-engineer; **security-auditor** (`source_snapshot`) | 55 tests green |
| 3 | `convert_agents` (+ effort map, `agents-astra`), `convert_skills`, `convert_rules`, `render_profile` (`codex`, `codex-astra`, region body), `translate`; prompt rewrites of R, G, BlackCat and flagged sentences in 57 bodies and up to 83 skill files | python-engineer; **writer** (texts) | build report: 0 unmapped; 40 tests |
| 4 | `codex_guard.py` + stub; 4b spawn tree, taint propagation, `send_input` routing | python-engineer; **security-auditor** review | 33 tests; seeded-bug proofs |
| 5 | `dot-config/dot-codex_config/install.sh`, `--doctor`, `--print-requirements`, `--ide-default`, `smoke.sh` | main-coder (core) + coder (flags, messages); security-auditor | smoke green; real `~/.codex` and `~/.agents` hashes unchanged |
| 6 | `dot-config/dot-codex_config/README.md` (what is enforced vs advisory, user steps) | writer | review PASS |
| 7 | Install | **user** | — |

**Tests: all on scratch `HOME` and scratch `CODEX_HOME`.** The design planned about 142; the built suite (`dot-config/dot-codex_config/tests/run.sh`) was 1953 passed, 1 skipped on 2026-10-06 (the skipped one is the `/usr/bin/python3` shim timing, run only with `CODEX_GUARD_PERF_SHIM=1`, outside the sandbox).
- **Planned count by area** (as designed):
  - emitter 12, including the round-trip property test;
  - converters 24: 57 roles parse; policy equals agent_guard.POLICY; unmapped token fails; skills 127/89 split and 4 excluded; hub paths; budget;
  - effort and models 8: the §2 table reproduced exactly from the frontmatter (43 Sol, same names; 14 Luna, one level up); Luna `max` stays `max`; `none` and `minimal` never emitted; an effort outside a model's accepted set stops the build; BlackCat's profile effort is `high`;
  - `codex-astra` 6: only the six `astra.agents` move to `gpt-6-astra` with fable-column effort; other roles byte-equal to `codex`; full-copy form equals the `codex` profile except 6 `config_file` values; overlay form under `--ide-default` holds only those 6 entries and no `[hooks]`; `--no-astra-profile` prunes the file and `agents-astra/`; cost notice printed;
  - rules 10: Claude `allow` never becomes `allow`; examples; fake and optional live execpolicy;
  - guard 33: no-push corpus; `apply_patch` paths; CODEX_HOME; `auth.json` through shell, `apply_patch` and MCP path args; BlackCat gate on namespaced names (`multi_agent_v1wait_agent` allowed; plain `wait` and an unknown `multi_agent_v1*` refused); `send_input` routing on the prefixed name; caller rows; built-ins; BlackCat gate; read-only roles; MCP allowlist; taint; caps under concurrent processes; stub without Python exits 2; catch-all deny; PermissionRequest; p95 < 100 ms per call through the stub, with the installer's precompiled bytecode and a real interpreter as stack-python (2026-10-06: 3.13 ≈ 40 ms, Apple 3.9 ≈ 85 ms; the `/usr/bin/python3` shim is timed by the user, `test_guard_perf.py`);
  - installer 27: snapshot proof (an edit to `lib/install_state.py` after the snapshot is never run); `--restore` after a Codex-style append to `config.toml` refuses without `--force-config`; `stack.env` `chmod 644` then a re-run shows a change; dry-run writes nothing; diff; apply, backup, restore round trip; drift abort; refusal list including `~/.claude`; foreign skill entry; `hooks.state` carry-over; AGENTS splice and override warning; re-trust detection; idempotent second run; requirements generator never touches `/etc`;
  - `--ide-default` region 12:
    - off by default (`config.toml` bytes unchanged); splice into an empty file, a root-keys-only file and a file with tables, with `tomllib(result) == merge(user, stack)` and the user's bytes outside the regions unchanged; a user root key is never captured by a region;
    - conflict with a user key or table stops the run, naming it; idempotent second run; an edited region (e.g. `/model`) stops with a diff unless `--force`; Codex-style `[hooks.state.*]` and `[projects.*]` tables appended outside the regions survive a re-run;
    - `--no-ide-default` removes exactly the regions; `--restore` round-trips an unchanged file and needs `--force` otherwise; no profile carries `[hooks]` in this mode (each hook runs once); re-trust is reported for the region's hook keys;
  - contracts 7: the hook tool-name table (spawn_agent canonical, `multi_agent_v1<name>`, `mcp__<server>__<tool>`; fixture from F10/F22, updated by P13); install_state and claude_md_block signatures; effort sets equal a vendored `models.json`; agent_guard POLICY; schema snapshot of every emitted key (vendored `config.schema.json` at the pinned tag); hook-input fixture from `hooks/src/schema.rs`.
- **Seeded-bug proofs.** At least one mutation per file, kept in the docstring; each must turn a test red. Examples:
  - flip a `forbidden` to `allow`; drop CODEX_HOME from the protected roots; remove `"` escaping in the emitter; let the BlackCat gate pass a shell write;
  - **effort:** drop the Luna +1, apply +1 to Sol, cap Luna at `xhigh` instead of `max`, start the scale at `none`; **Astra:** add a seventh agent, or read the opus column instead of fable;
  - **region:** write region A after the user's first table; skip the conflict check; let `--no-ide-default` remove one line past the end marker; keep `[hooks]` in the profile under `--ide-default`.
- **Fake `codex`.** `tests/fake-codex/codex` answers only `--version` (configurable) and `execpolicy check` (backed by an in-repo prefix-rule mirror). Any other subcommand exits 97, so no test can reach a real Codex.
- **Isolation.** `smoke.sh` hashes the real `~/.codex` and `~/.agents` before and after, as `install_smoke.sh` does for `~/.claude`.

**Review triggers (one reviewer per class):**
- security-auditor:
  - the guard and stub;
  - the rules and `allow` forms;
  - the permission profile;
  - the requirements generator and its printed root commands;
  - `install.sh`/lib paths, symlinks and O_NOFOLLOW.
- code-reviewer: converters and emitter (diff over 300 lines).
- plan-reviewer: this design, before Phase 2.

**User-run steps** (agents never run these):
1. Phase 0 probes (P1–P13; P7 checks the `auth.json` deny, P13 the hook tool names). Paste the JSON report back.
2. `./install.sh --codex --dry-run`, then `./install.sh --codex`.
3. `codex --profile codex`, then `/hooks` → trust 8 hooks. Until then the guard does not run at all. Then run `./install.sh --codex --doctor`, which exits 0 only when every stack hook is trusted. Repeat both whenever the installer says "re-trust".
4. Optional Astra: `codex --profile codex-astra`, then `/hooks` → trust its 8 hooks. Each session started this way bills the six top-tier agents at Astra rates ($10/$50 per 1M tokens).
5. Optional IDE and every-session mode:
   - `./install.sh --codex --ide-default --dry-run` to review the region diff, then the same without `--dry-run`.
   - Plain `codex` (no profile), then `/hooks` → trust the 8 hooks whose source is `config.toml`.
   - Restart the IDE (and the desktop app, if used).
   - Undo with `./install.sh --codex --no-ide-default` or `--restore`.
6. Optional: `./install.sh --codex --print-requirements`, then:
   ```
   sudo install -d -o root -g wheel -m 0755 /etc/codex "/Library/Application Support/claude-agent-stack/codex-hooks"
   sudo install -o root -g wheel -m 0755 dot-config/dot-codex_config/build/managed-hooks/* "/Library/Application Support/claude-agent-stack/codex-hooks/"
   sudo install -o root -g wheel -m 0644 dot-config/dot-codex_config/build/requirements.toml /etc/codex/requirements.toml
   ```
   Then check `/debug-config` in `codex --profile codex`. An existing `/etc/codex/requirements.toml` is never replaced: the installer prints a diff for the user to merge.

## 10. Decisions taken and risks

- **Q1 (decided 2026-10-06).** Sonnet → `gpt-6-luna` (14 agents) and Opus → `gpt-6.1-sol` (43 agents). No agent uses Astra by default; `codex-astra` is opt-in (§2.1).
- **Q2 (decided).** `--ide-default` is an opt-in `config.toml` region (§7.6). Without it the IDE gets only the global layer.
- **Q3 (decided).** Luna runs one effort level above the stack's value, capped at `max`; Sol keeps the same names; `none` is never used (§2).
- **Open:** none for Phase 2. U1–U13 are settled by the Phase 0 probes.
- **Risks:**
  - `--ide-default` changes every Codex session on the machine: CLI, IDE and desktop app (§7.6).
  - Undocumented `agent_type` (F9): pinned by the version check and the contract fixture; fails closed.
  - Beta permission profiles and experimental rules.
  - Near-daily releases: pin ≥ 0.160.1 and re-run the probes on upgrade.
  - Global leakage of skills, rules and AGENTS into non-profile sessions.
  - Prompt fidelity of 57 rewritten bodies.

## 11. Sources (read 2026-10-06)

- models — https://learn.chatgpt.com/docs/models.md
- api-sol — https://developers.openai.com/api/docs/models/gpt-6.1-sol
- api-luna — https://developers.openai.com/api/docs/models/gpt-6-luna
- api-astra — https://developers.openai.com/api/docs/models/gpt-6-astra
- `…/gpt-6.1-luna` and `…/gpt-6.1-astra` both fall back to https://developers.openai.com/api/docs/models
- Gizmodo, 2026-09-29 — https://gizmodo.com/with-no-astra-to-release-openai-pivots-to-new-gpt-6-1-sol-model-2000819044
- config-ref — https://learn.chatgpt.com/docs/config-file/config-reference.md
- config-advanced — https://learn.chatgpt.com/docs/config-file/config-advanced.md
- hooks — https://learn.chatgpt.com/docs/hooks.md
- subagents — https://learn.chatgpt.com/docs/agent-configuration/subagents.md
- skills — https://learn.chatgpt.com/docs/build-skills.md
- rules — https://learn.chatgpt.com/docs/agent-configuration/rules.md
- security — https://learn.chatgpt.com/docs/agent-approvals-security.md
- permissions — https://learn.chatgpt.com/docs/permissions.md
- managed — https://learn.chatgpt.com/docs/enterprise/managed-configuration.md
- agents-md — https://learn.chatgpt.com/docs/agent-configuration/agents-md.md
- ide-settings — https://learn.chatgpt.com/docs/developer-settings.md?surface=ide
- dev-cmds — https://learn.chatgpt.com/docs/developer-commands.md?surface=cli
- Source, tag `rust-v0.160.1` (https://github.com/openai/codex/tree/rust-v0.160.1/codex-rs):
  - `core/src/agent/role.rs`
  - `core/src/hook_runtime.rs`
  - `hooks/src/schema.rs`
  - `hooks/src/engine/discovery.rs`
  - `hooks/src/config_rules.rs`
  - `ext/skills/src/host_roots.rs`
  - `core/src/exec_policy.rs` and `core/src/exec_policy/model_policy.rs`
  - `features/src/lib.rs`
  - `sandboxing/src/seatbelt.rs`
  - `core/config.schema.json`
- Source, `main` on 2026-10-06:
  - `core/src/tools/handlers/multi_agents_spec.rs`
  - `core/src/tools/hook_names.rs`
  - `tui/src/hooks_rpc.rs`
  - `config/src/config_layer_source.rs`
- PR #39299 (commit `1a6e07a4`, 2026-08-18): "Restrict agent roles to bounded configuration overrides"
