# Codex Phase 0 probes

You run these (agents never do). They settle the unverified Codex facts in `codex_config/DESIGN.md` section 1.3 (U1 to U13) before Phase 2 builds on them. Everything runs in a scratch `CODEX_HOME` and a scratch `HOME` under `${TMPDIR:-/tmp}`; `~/.codex`, `~/.agents` and `/etc` are never touched and auth files are never copied.

## Run

```
codex_config/probes/run.sh --list            # the 14 probes
codex_config/probes/run.sh --dry-run         # every file it would write, every command you would run; no prompts
codex_config/probes/run.sh                   # all probes (P2 first: it trusts the hooks the others need)
codex_config/probes/run.sh --probe P7b       # one probe
```

1. Start it. It prints the scratch root and `CODEX_HOME=<scratch> codex login`: run that once (a separate terminal is easiest), then press Enter.
2. For each probe it prints numbered steps and exact commands (`env HOME=<scratch home> CODEX_HOME=<scratch> ... codex ...`). Run them in another terminal, come back, press Enter; it inspects the hook log and files itself and asks y/n only where nothing can be read mechanically.
3. At the end it prints the path of `report.json` (`{"meta": {...}, "probes": {"P1": {"result": "pass|fail|unknown", "evidence": "...", "notes": "..."}, ...}}`). Paste it back; it contains no credentials. Delete the scratch root afterwards.

`CODEX_HOME` in the environment is honoured only if it names a new or empty directory; `~/.codex` and any non-empty directory are refused. The script itself runs only `codex --version`.

Meaning of results: `pass` = the behaviour the design assumes (or, for questions with two acceptable answers such as P2, P11 and P12, the answer was determined and is in the evidence); `fail` = the fallback named below is needed; `unknown` = the probe could not decide (not logged in, hooks untrusted, model did not do what the prompt asked): read `evidence` and the `.out` file under `<scratch>/logs/`, rerun with `--probe`.

Unverified assumptions about the Codex CLI itself: the `exec --skip-git-repo-check -C` flags, the `spawn_agent` argument names and the permission-profile TOML spelling (taken from the vendored schema and docs, not run). A probe whose evidence says "model did not call" may need its prompt adjusted in `run.sh`.

Automation: fully automatic after the commands run: P1, P2, P3, P4 (a role-error y/n only if no subagent starts), P5, P6, P7b (a y/n only on failure), P9, P13. Automatic checks plus y/n answers: P7 (read results), P8 (attribution), P10 (fallback y/n). Manual TUI or IDE steps: P2 and the trust step used by every other probe (`/hooks`), P11 (IDE), P12 (`/hooks`, `/model`, project trust, then automatic file checks).

Each hook writes a `#meta` line (event, argument 2, and whether the hook could write outside the sandbox and read `auth.json`) and a `<event><TAB><stdin JSON>` line to `<scratch>/logs/hooks.jsonl`.

## Probes

### P1 profile hooks fire only with `--profile` (also U4)
- Question: do hooks declared in `probe.config.toml` fire under `codex --profile probe` and not under plain `codex`?
- Why: DESIGN F1/F3 and section 7.6 put the guard in the profile only; a leak would run it in every Codex session, and no firing would make the profile design void.
- Steps: (trust hooks if needed) run the same `exec` prompt without and with `--profile probe`.
- Expected (pass): hook lines in the second run only.
- Read: `evidence` gives the line counts. `notes` records U4: the hook command is `/bin/sh <path> PreToolUse $PROBE_U4`; arg2 `expanded` means Codex runs the command through a shell, a literal `$PROBE_U4` means it splits argv (the design's `/bin/sh '<abs path>' <mode>` shape works either way).

### P2 where `/hooks` writes trust (U1)
- Question: after trusting hooks in `/hooks` under the profile, does `[hooks.state."<key>"]` land in `config.toml` or in `probe.config.toml`?
- Why: section 4.4 and 7.6 carry over `[hooks.state]` from the live file when re-rendering; the doctor must read the right file.
- Steps: `codex --profile probe`, `/hooks`, trust all, quit.
- Expected: either location is a determined answer (`pass`); `unknown` if no record appeared.
- Read: `evidence` shows `config.toml=yes|no probe.config.toml=yes|no` and the first keys (their format sets the doctor's key parsing).

### P3 `agent_type` in a subagent's PreToolUse (F9)
- Question: does a subagent's PreToolUse payload carry `agent_type` (undocumented but in the source)?
- Why: the whole per-agent policy of the guard (section 5) keys on it. `fail`: the guard cannot tell callers apart; fall back to SubagentStart bookkeeping or drop per-agent policy to the main thread.
- Steps: `exec` a prompt that spawns role `probe_worker` which runs `echo`.
- Expected: PreToolUse lines with `"agent_type": "probe_worker"`.
- Read: `evidence` lists the distinct values seen.

### P4 hyphenated role names (U2)
- Question: is `probe-worker` accepted as a role and reported as `agent_type` unchanged?
- Why: 57 agents keep their hyphenated names (section 7.5). `fail`: set `role_name_style="underscore"` (INTERFACES.md) and map `-` to `_` everywhere.
- Steps/Expected/Read: as P3 with `probe-worker`; `fail` evidence shows the values actually reported.

### P5 roles via `[agents.x].config_file`
- Question: does the role file's `developer_instructions` reach the subagent?
- Why: all 57 agent bodies travel in role files. `fail`: bodies would have to be inlined into the profile.
- Expected: the subagent's final message starts with `PROBE-ROLE-OK` (read from SubagentStop's `last_assistant_message` or the captured output).

### P6 profile MCP servers load
- Question: does `[mcp_servers.probe_echo]` in the profile file start and serve tools?
- Why: the stack's MCP servers are merged into the profile (section 7.5). `fail`: put them in `config.toml` (global) instead.
- Expected: `<scratch>/logs/mcp.log` has `method=initialize`, `tools/list`, `tools/call text=hello-p6`.
- Read: `notes` shows the MCP `tool_name` shape the hooks saw (for per-server allowlists).

### P7 permission profile from the profile file (U5)
- Question: with `default_permissions` and `[permissions.probe-perm]` in the profile file: is `<CODEX_HOME>` readable and not writable, and does an `auth.json` `deny` outrank the `read` on CODEX_HOME? `approval_policy = "never"` prevents escalation from masking a denial.
- Why: section 4.2 relies on it for credential and self-protection; `fail` makes the guard the primary control.
- Steps: `exec` with four shell commands (read config.toml, write into CODEX_HOME, read 8 bytes of auth.json, write into the workspace); the script checks the files, you answer two y/n questions from the printed output.
- Expected: CODEX_HOME write not created; auth.json count `0`; config.toml count `1`; the workspace write is the control.

### P7b `.git` write grant (U6)
- Question: can a permission profile grant `<workspace>/.git` write so an in-sandbox `git commit` works?
- Why: decides the git policy in section 4.3 (in-sandbox commits vs unsandboxed escalation).
- Expected: commit `p7b-commit` exists in the work repo (`pass`); `fail` if Codex reports the denial.

### P8 `forbidden` rule blocks `git push`
- Question: does `prefix_rule(["git","push"], forbidden)` in `<CODEX_HOME>/rules/` block `git push` from the sandbox?
- Why: section 4.3's no-push layer 1. Remote is a local bare repo in the scratch dir, never a network remote. `fail` (the push arrived): the guard hook must carry the rule.
- Read: `pass` needs an empty remote and your y/n that the block was attributed to the rule. Prefix rules match the exact command start (`git push`), not `git -C x push`: keep that in mind for the final rule set.
- Optional: the printed `codex execpolicy check` command shows the rule parses.

### P9 hooks run unsandboxed (U3)
- Question: when the session runs under the restrictive `probe-perm` profile, can the hook still write outside the sandbox roots (`<scratch>/outside/hook-wrote-*`) and read `auth.json`?
- Why: the guard keeps state in `~/.local/state/codex-agent-stack`. `fail`: the permission profile must grant that directory.
- Read: `evidence` has the `#meta` counts.

### P10 symlinked skills listed
- Question: is a folder symlinked into `$HOME/.agents/skills` (scratch HOME) listed by Codex?
- Why: `skill_links` installs symlinks (F5). `fail`: copy skill folders instead.
- Expected: the captured reply names `probe-skill`.

### P11 IDE and `hooks.state` (U9, manual)
- Question: do hooks defined in `config.toml` and trusted from the CLI also run in the IDE extension (which ignores profiles), without a second review prompt?
- Why: `--ide-default` (section 7.6). `fail`: the IDE needs its own trust step; document it.
- Steps: trust from plain `codex`; start the IDE with the scratch env (`env HOME=... CODEX_HOME=... code -n <work>`; adapt for another IDE), log in there, run a prompt; answer whether the IDE showed its own prompt.
- Read: hook lines after the `P11/ide` marker prove the IDE ran them. The script restores the base `config.toml` afterwards.

### P12 Codex's own `config.toml` writes (U13)
- Question: after `/hooks` trust, `/model` and project trust, are the user comments and the two stack-marker regions intact, region bodies byte-identical, and the new keys (`[hooks.state...]`, `[projects...]`, `model`) outside the regions?
- Why: section 7.6's drift check works either way, but the install and restore messages depend on whether Codex keeps markers. `fail`: expect re-renders after every Codex write and tell the user.
- Read: `evidence` lists marker count (4), comment count (3), region state and the keys found outside. The rewritten file stays at `<scratch>/p12.after.toml`.

### P13 hook `tool_name` of special tools (U10, U11)
- Question: which `tool_name` do PreToolUse hooks see for `spawn_agent`, `send_input`, `wait_agent`, `resume_agent`, `close_agent` (any `multi_agent_v1` prefix shows here), `update_plan`, `request_user_input`, `view_image`?
- Why: the BlackCat delegate-only allowlist and `MA_TOOLS` matching (section 5, F10). The matcher is `.*`, so a tool absent from the log while the model called it opts out of hooks (U11) and `.*` matching everything is tested too (U10).
- Read: `evidence` lists the names seen and the names missing. `request_user_input` is experimental and may be disabled in `exec`: a missing one is not necessarily a hook gap (check `<scratch>/logs/P13.out`).

## Not observable here
U7 (`omit_tools_from` deferring MCP tools) and U8 (AGENTS.md byte budget) need the stack's real config; Phase 5's smoke covers them.
