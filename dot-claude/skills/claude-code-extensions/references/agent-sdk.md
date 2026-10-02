# The installed stack under the Claude Agent SDK

Checked 2026-10-02 against code.claude.com/docs/en/agent-sdk/* (overview, python, typescript, sessions,
hooks, permissions, subagents, skills, cost-tracking, modifying-system-prompts, claude-code-features)
and the Python SDK `claude-agent-sdk==0.2.163` itself (PyPI 2026-09-30; bundles Claude Code 2.1.286;
`_internal/transport/subprocess_cli.py`, `types.py`). npm: `@anthropic-ai/claude-agent-sdk` 0.3.287.
"Unverified" = neither the docs nor the SDK source say it.

The stack's files stay the single source of truth: an SDK app loads them through `setting_sources`,
never through programmatic copies (`agents=`, inline `hooks=`).

## What an SDK call loads

| Item | Loaded when | Source |
|---|---|---|
| `~/.claude/agents`, `skills`, `commands`, `rules/*.md`, `CLAUDE.md`, `settings.json` (hooks of every type, permissions) | `"user"` in `setting_sources` | claude-code-features |
| `.claude/` of the project, project `CLAUDE.md`, `.claude/rules` | `"project"` | same |
| `settings.local.json`, `CLAUDE.local.md` | `"local"` | same |
| `~/.claude.json` (user-scope MCP servers), managed policy | always | same |
| `enabledPlugins` (LSP plugins), the `agent` key, `skillOverrides`, settings `env` | unverified | — |
| status line | not run: no UI (unverified) | — |

- `setting_sources` omitted: the CLI default, all three sources (Python: no `--setting-sources` flag is
  passed). `[]`: none, so no stack hooks, agents or skills. With `skills=` set and sources omitted the
  Python SDK passes `user,project`.
- `system_prompt` omitted: the Python SDK passes `--system-prompt ""` (an empty prompt). Use the preset
  `{"type": "preset", "preset": "claude_code"}`. CLAUDE.md and rules load by setting source, not by the
  preset (claude-code-features).
- Main-thread agent: TypeScript has `agent: "<name>"`; Python has no such field, so pass
  `extra_args={"agent": "<name>"}` (becomes `--agent <name>`). Without it the settings key
  `"agent": "blackcat"` decides (unverified under the SDK; the Desktop and Conductor hosts honor it).
- The installer already covers what GUI-launched SDK apps need: absolute interpreter paths in every
  hook and MCP command (their PATH is minimal), `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` and
  `CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1` in settings `env`.

## What an SDK call can override, and what the stack enforces regardless

| Option (Python / TS) | Effect | Still enforced by the stack |
|---|---|---|
| `model` / `model` | main thread only | each agent's frontmatter model; the hook strips `model` from Agent calls |
| `max_turns` / `maxTurns` | main thread (`--max-turns`) | subagents' frontmatter `maxTurns` |
| `max_budget_usd` / `maxBudgetUsd` | stops at the client-side cost estimate of this call (subtype `error_max_budget_usd`) | `STACK_PROMPT_CTX_BUDGET`, `STACK_SESSION_CTX_BUDGET` (context tokens, hook) |
| `allowed_tools` | auto-approve rules; no constraint under `bypassPermissions` | every PreToolUse hook |
| `disallowed_tools` | deny rules, binding even under `bypassPermissions` | settings deny rules too |
| `permission_mode` | default, dontAsk, acceptEdits, bypassPermissions, plan, auto (TS: omitted can start in auto) | hooks run and can block in every mode; deny rules hold |
| `agents` | programmatic agents beat same-named file agents | don't use: a new name is refused by the spawn allowlist; a same name keeps its policy row but swaps prompt and tools |
| `hooks` (callbacks) | run side by side with settings hooks, in parallel; the most restrictive decision wins (deny > defer > ask > allow) | a callback cannot loosen a settings hook's deny |

Precedence: managed policy > programmatic options > local > project > user (claude-code-features).
Enforced in every mode: no-push and forge writes, spawn policy, depth, fan-out and copy caps, god-coder
singleton, read-only reviewers, protected paths, token budgets, MCP call caps, image limit, labels, ledger.

## Hooks without a terminal

Command hooks always run in their own session without a controlling terminal (hooks.md), in the
terminal UI, `claude -p` and the SDK alike; `agent_guard.py` reads only its stdin JSON. The Python SDK
adds `CLAUDE_CODE_ENTRYPOINT=sdk-py` (overridable through `env`) and `CLAUDE_AGENT_SDK_VERSION` to the
CLI's environment and removes `CLAUDECODE`; the hook reads none of them, so label, background drop,
ledger, SubagentStart context and no-push behave identically (`tests/test_sdk_integration.py` runs them
with `start_new_session=True` under each entrypoint). The Python callback hook list has no SessionStart;
the stack's SessionStart is a settings hook, run by the CLI. `session-env` needs `CLAUDE_ENV_FILE`
(SessionStart only); a host without it gets a stderr notice and `session-env.json` says so (doctor.sh).

## Reports an app can parse without a model

- Default (rules, "Briefs and hand-backs"): a clean finish is `<input: task in ≤ 10 words> · <YYYY-MM-DD
  HH:MM> · <agent type>` then the result; anything else is the `STATUS / RESULT / EVIDENCE / FILES /
  NEXT` block.
- `STACK_REPORT_FORMAT=json` (the SDK `env` option, or exported): the SessionStart hook (main thread, every
  source) and SubagentStart (stack agents) add one line, `REPORT_JSON_LINE` in `agent_guard.py`, asking for
  one JSON line `{"input","timestamp","agent","status","result","evidence","files","next"}`. Unset: no
  hook output, the default prompt is unchanged.
- `stack_sdk.parse_report(text)` reads all three (the last JSON line wins) and returns
  `{format: json|clean|status|text, input, timestamp, agent, status, result, evidence, files, next}`.
- Native alternative for the main thread: `output_format={"type": "json_schema", "schema": …}` →
  `ResultMessage.structured_output` (subagents: unverified).

## Prompt-cache order

Request order is tools → system → messages.
- A subagent's system prompt is its body plus fixed harness notes (the `prompt_snapshot` entry of its
  transcript): no date, no git status, nothing a hook writes. No hook can write a system prompt.
- SubagentStart `additionalContext` ("Started …", and the JSON line) lands "at the start of the
  conversation, before the first prompt" (hooks.md): in the first user message, after tools and system,
  fixed for the whole run, so it never invalidates the run's own cache. That message already differs per
  spawn (brief, git status, date), so the line costs no cross-spawn hit on tools + system. Kept.
- PostToolUse ledger hint, image-limit `updatedToolOutput` and the label's `updatedInput` sit where their
  tool ran and are deterministic: nothing earlier is rewritten.
- SDK main thread: the preset with `exclude_dynamic_sections` (TS `excludeDynamicSections`) moves cwd,
  auto-memory and git status into the first user message, so the system prompt is identical across calls
  (`types.py`, modifying-system-prompts). `stack_sdk.options()` sets it. Unverified: its effect when
  `--agent` supplies the main-thread prompt.
- Cache-busting found: none.

## Observability

- Ledger: `${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/<session_id>/delegations.md`, one line
  per Agent call, `- <type> · "<task>" · <state> · <HH:MM:SS> · id <agent_id>`, indented per depth; as JSON
  `/usr/bin/python3 ~/.claude/hooks/agent_guard.py delegations <session_id> --json` (depth, state, type,
  task, name, child, by, by_type, ts, tid = the Agent tool_use_id).
- Labels: the hook rewrites an Agent call's description to `<subagent_type>: <task>` (`STACK_AGENT_LABEL`:
  `description` default, `name` = `<type>-<n>`, `off`).
- SDK messages: `TaskStartedMessage` / `TaskProgressMessage` / `TaskNotificationMessage` carry
  `tool_use_id` (= the ledger's tid), `description` (the label) and `usage` {total_tokens, tool_uses,
  duration_ms}. `ResultMessage.usage` counts the top-level loop only; `model_usage` and `total_cost_usd`
  include subagents (cost-tracking). `run()` joins them per subagent in `agents`. Unverified: whether
  nested (L2+) tasks reach the SDK stream.

## The helper (`~/.claude/bin/stack_sdk.py`, installed, loaded by nothing)

```python
import sys, asyncio, dataclasses; sys.path.insert(0, "/Users/<you>/.claude/bin"); import stack_sdk
opts = stack_sdk.options("coder", max_turns=20, budget_usd=1.0, permission_mode="acceptEdits",
                         json_reports=True)            # a plain ClaudeAgentOptions
opts = dataclasses.replace(opts, cwd="/path/to/repo")  # adjust anything
out = asyncio.run(stack_sdk.run("Fix the failing test in tests/test_x.py", opts, on_message=print))
out["report"]["status"], out["session_id"], out["agents"], out["model_usage"], out["ledger"]
# resume: stack_sdk.options(resume=out["session_id"]); fork: also fork=True
```
CLI (one JSON line on stdout, exit 1 on partial/blocked/error): `~/.claude/bin/stack_sdk.py "task"
--agent scout --max-turns 5 --budget-usd 0.5 --json-reports`; `--print-options` shows the options and
runs nothing; `--stream` prints every SDK message on stderr. Needs `uv` on PATH (shebang `uv run --script`).

TypeScript (the same options; not shipped):
```ts
import { query } from "@anthropic-ai/claude-agent-sdk";
for await (const m of query({ prompt: "…", options: {
  settingSources: ["user", "project", "local"], agent: "blackcat",
  systemPrompt: { type: "preset", preset: "claude_code", excludeDynamicSections: true },
  maxTurns: 30, maxBudgetUsd: 2, env: { ...process.env, STACK_REPORT_FORMAT: "json" } } })) {
  if (m.type === "result") console.log(m.result, m.total_cost_usd, m.modelUsage);
}
```
TS `env` replaces the subprocess environment (hence the spread); Python's `env` merges.

## Efficiency

Nothing is generated per call: options are plain values and every agent, skill and hook comes from the
installed files. MCP stays lazy: agent-scoped servers start with their agent, user-scope ones come from
`~/.claude.json` with `MCP_DISCOVERY_CACHE`; the helper passes no `mcp_servers`. Cold start and the tokens
of a minimal call: `uv run --script tests/sdk_smoke.py` in the stack repo (real, billed calls; bare vs
stack vs BlackCat, two runs each so the second shows the cache read).
