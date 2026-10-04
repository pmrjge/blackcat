---
name: claude-code-extensions
description: Load before changing Claude Code config — agents, skills, hooks, settings, MCP, plugins; stack conventions.
---
# Claude Code extensions (verified against code.claude.com docs, Claude Code 2.1.283)

Re-check every key against the raw docs page (`https://code.claude.com/docs/en/<page>.md`: sub-agents, skills, hooks, settings-reference, env-vars, mcp, permissions, plugins/cli-reference, workflows). Unknown fields and keys are ignored silently.

## Agent bodies: skills over big prompts
Every spawn pays for the body, the rules and the skill listing, so a body holds only: role (one line), hard constraints (safety, hook-enforced and git rules that the rules file does not already state), routing and the may-spawn list, the output contract (point to the rules' "Briefs and hand-backs" instead of restating it), and one-line skill pointers in a `## Skills` section ("load `x` when y"). Procedures, checklists, tool recipes and domain detail go to skills, loaded on demand; nothing the rules file says is repeated.

## Subagents (`~/.claude/agents/*.md`, `.claude/agents/*.md`)
Full field list and runtime facts: `references/subagents.md`. Must-knows:
- Every agent names a model alias (`opus` or `sonnet`, lint-enforced; the IDs come from `ANTHROPIC_DEFAULT_<FAMILY>_MODEL` in stack.env, which the installer copies into settings.json's env, and lint rejects a specific ID anywhere else); no `skills:` preloads (lint rejects them; every agent has the Skill tool); `maxTurns` ≤ 350 (< 200 outside orchestrator and main-/ninja-coder, none on blackcat).
- `tools` is an allowlist and must name `mcp__<server>` too, except the agent's own inline `mcpServers`, which are always visible.
- `Agent(a, b)` lists bind only the main-thread agent; in subagents `hooks/agent_guard.py` (POLICY) enforces the spawn policy.
- Workflow, scheduling, AskUserQuestion and plan-mode tools exist only on the main thread (BlackCat). BlackCat only delegates: no Bash, Write, Edit or web tool, Read ≤ 3 per prompt (`BLACKCAT_MAX_READS`; blackcat-guard refuses Bash/Write/Edit while `BLACKCAT_MAX_OWN_STEPS` is 0); its `tools` line equals `BLACKCAT_TOOLS` (lint). A `context: fork` skill runs as its `agent:` (general-purpose if omitted, which the guard refuses), with that agent's tools narrowed to the main thread's (CONFIG.md bug 8), so no Bash: ship no forked skill.

## Skills (`<dir>/SKILL.md`)
Fields, listing budget, `skillOverrides` and the hub/module layout: `references/skills.md`. Must-knows: only `LISTED_CORE` skills show descriptions in the listing (the rest are `name-only`), bodies load on invocation; a description is ≤ 140 characters, starts with `Load `/`Use `, says what and when, never names an agent, and is YAML-safe (no `: ` or ` #` unquoted); hubs ≤ 80 lines with a `## Modules` table, modules ≤ 150 lines with detail in `references/`; no `!`cmd`` injection in skills the main thread may run.

## MCP, hooks, settings, LSP
Details: `references/mcp-hooks-settings.md`. Must-knows:
- MCP tiers: a local stdio server goes inline in ONE agent's `mcpServers`; a remote HTTP server shared by agents goes to user scope with the `mcp-headers` helper (keys from stack.env, never config files); a rare server becomes a disabled magg catalog entry that mcp-broker mounts. Reserved names: `workspace`, `claude-in-chrome`, `computer-use`, `Claude Preview`, `Claude Browser`.
- Hook commands use the installer's absolute interpreter (`__PYTHON3__`): a hook that cannot start is a silent open gate. PreToolUse decides in `hookSpecificOutput.permissionDecision`; `updatedInput` replaces the whole input; `systemMessage` reaches the user, not the model.
- Settings changes go to the repo's `dot-claude/settings.json`, never the live file; loosening a permission, hook or sandbox needs the user's consent.
- User commands are skills with `disable-model-invocation: true`: `stack-doctor`, `stack-tree` (agent tree or table of a session, `static` for the design), and `override-agent` (per-session model of a delegated agent type; `list`, `reset`). UserPromptExpansion hooks answer all three (`/stack-doctor` runs `bin/doctor.sh --hook` outside the sandbox, `/stack-tree` `bin/stack-tree --hook`), and a user-only state change hooks onto that event, never UserPromptSubmit (CONFIG.md §5).

## Agent SDK
Running the installed stack from an SDK app or `claude -p` (what `setting_sources` loads, what a call can override, hooks without a TTY, JSON reports, cache order, `bin/stack_sdk.py`): `references/agent-sdk.md`.

## Validate
`jq empty <file>` for JSON; `claude plugin validate <dir>` for plugins and agent directories; in the stack repo `uv run tests/lint_agents.py`, `__CLAUDE_DIR__/venvs/tools/bin/python -m pytest -q tests/` (the tools venv), `bash tests/install_smoke.sh`; `/usr/bin/python3 <config>/hooks/agent_guard.py --self-test` (the hooks' own interpreter, as in settings.json); `/doctor` and `/stack-doctor` in a session.

Division of labour: built-in `update-config` (mechanics of editing a settings.json), `workflow-authoring` (Workflow scripts), `skill-creator` (skill evals, description tuning), `mcp-server-craft` (writing an MCP server), `prompt-and-brief-design` (CLAUDE.md, agent and skill prompts), `agent-harness-design` (agent loops outside Claude Code).
