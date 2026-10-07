# Codex Phase 0 probes

You run these (agents never do). They settle the unverified Codex facts in `dot-config/dot-codex_config/DESIGN.md` section 1.3 (U1 to U13, and the entries added by the build: see "Probes added after the build" below). Everything runs in a scratch `CODEX_HOME` and a scratch `HOME` under `${TMPDIR:-/tmp}`; `~/.codex`, `~/.agents` and `/etc` are never touched and auth files are never copied.

## Run

```
dot-config/dot-codex_config/probes/run.sh --list            # the 14 probes
dot-config/dot-codex_config/probes/run.sh --dry-run         # every file it would write, every command you would run; no prompts
dot-config/dot-codex_config/probes/run.sh                   # all probes (P2 first: it trusts the hooks the others need)
dot-config/dot-codex_config/probes/run.sh --probe P7b       # one probe
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

## Probes added after the build

These settle the facts the built installer still assumes. They are **manual** and are not in `run.sh` (`--list` shows the 14 above): you run them against a stack installed into a scratch `CODEX_HOME`, never `~/.codex`. Their ids follow `dot-config/dot-codex_config/DESIGN.md` §1.3 ("Added by the build"). Results go back as a line per probe: pass, fail or unknown, with the evidence named under Read.

Everything above stays out of `/etc`; the managed-hooks entry below is the one exception, and only if you choose to install the machine-wide tier (you run its `sudo` lines).

Common setup (a scratch root, a scratch `HOME`, a new empty `CODEX_HOME`; log in there as for the probes above):

```
S=$(mktemp -d "${TMPDIR:-/tmp}/codex-probe.XXXXXX"); mkdir -p "$S/home" "$S/codex"
CODEX_HOME="$S/codex" codex login
STACK_PYTHON=$(uv python find 3.13) env HOME="$S/home" ./install.sh --codex --codex-home "$S/codex" --skills-root none --yes
```

Run Codex as `env HOME="$S/home" CODEX_HOME="$S/codex" codex --profile codex`. The installer needs a committed checkout. Delete `$S` afterwards.

### P6b `http_headers_helper` output format
- Question: does Codex accept the JSON object that `<stack>/bin/codex-mcp-headers <id>` prints (`{"<header>": "<value>"}`, or `{}` without a key), and how does it run the command?
- Why: the schema types `http_headers_helper` as a string only; the helper's output format and invocation are unverified. `fail`: change the helper's output (and the build's test) to the format Codex expects.
- Steps: in the scratch profile file, `[mcp_servers.exa]` has `url=...` and `http_headers_helper="<stack>/bin/codex-mcp-headers exa"`. Put a real Exa key in `$S/codex/stack.env` (mode 0600) and start `codex --profile codex`; run `/mcp`; ask for one `mcp__exa__` search.
- Expected (pass): the server's tools are listed and the call succeeds, so the JSON object was accepted. A 401 or a helper error means the format differs.
- Read: the `/mcp` listing and the call result. Use `codex-mcp-headers --redact exa` by hand to see the output without the key.

### P2/U1 where `/hooks` writes trust
- Question: after trusting the 8 hooks in `codex --profile codex`, which file holds `[hooks.state."<key>"]`?
- Why: `--doctor` reads `config.toml`, `codex.config.toml` and `codex-astra.config.toml`; the render carries `[hooks.state]` over per file. This is P2 against the installed stack instead of the probe kit.
- Steps: `codex --profile codex`, `/hooks`, trust all, quit; then `grep -n 'hooks.state' "$S/codex/config.toml" "$S/codex/codex.config.toml"`.
- Expected: either location is a determined answer; record which. `install.sh --doctor` should then exit 0 (`--codex-home "$S/codex"`, `HOME="$S/home"`).
- Read: the grep output; the key format `<abs path>:pre_tool_use:0:0`.

### U1b `trusted_hash` against a changed definition
- Question: after a definition changes (for example a re-install after the stack's timeout changed), does `/hooks` show that hook as "Modified" while the record is still present?
- Why: `--doctor` counts a record with a non-empty `trusted_hash` as trusted and cannot compare it (the hash is Codex's own); the installer's "re-trust N hook(s)" line is the only signal. `fail` (no "Modified"): the guard would run on a stale trust, and DESIGN §4.4 must say so.
- Steps: after the P2/U1 trust, edit `timeout` of one hook handler in `$S/codex/codex.config.toml` by hand (scratch only), start `codex --profile codex`, open `/hooks`.
- Expected (pass): that hook is listed as Modified and does not run until trusted again.
- Read: the `/hooks` screen; `install.sh --doctor` output for the same state.

### P12/U13 (extension) region markers and append position
- Question: with `--ide-default` installed in the scratch home, do the region markers survive `/model` and `/hooks` writes, and does Codex append its own keys after region B?
- Why: the kit's P12 uses a synthetic file; this runs against the installer's real regions. `fail`: expect "region edited" stops and `--force`/`--no-ide-default` after Codex writes.
- Steps: `install.sh --ide-default --yes` (setup env), plain `codex`, `/hooks` trust, `/model` change, quit; compare `$S/codex/config.toml` with its content right after the install.
- Expected: four marker lines intact; new keys outside both regions; `install.sh --no-ide-default --yes` still cuts exactly the two regions.
- Read: the marker count, the keys outside the regions, the installer's message on the next run.

### P-B3a `shell_environment_policy.filters` against a user `exclude`
- Question: with the profile's `[shell_environment_policy.filters]` and a user `config.toml` holding `shell_environment_policy.exclude = [...]`, which applies (merge, profile wins, or an error)?
- Why: the schema forbids the keyed form and the legacy list together inside one table; across layers it is unverified.
- Steps: add `[shell_environment_policy]` with `exclude = ["FOO_*"]` to `$S/codex/config.toml`; `export FOO_X=1 GITHUB_TOKEN=x` before starting; in a session run `env | grep -E 'FOO_X|GITHUB_TOKEN'` through the agent.
- Expected: neither variable is visible (merge), or only one rule applies: record which.
- Read: the printed environment and any config error at start.

### P-B3b exact names in `filters` remove the variables
- Question: do the 12 exact names under `filters` (value `"exclude"`) remove those variables from the agent's shell?
- Why: the profile relies on it for `GITHUB_TOKEN`, `GH_TOKEN`, `HF_TOKEN`, `WANDB_API_KEY` and the rest.
- Steps: start Codex with `GITHUB_TOKEN=probe-not-a-secret WANDB_API_KEY=probe-not-a-secret` exported (fake values) and ask for `env | grep -c probe-not-a-secret`.
- Expected (pass): `0`.
- Read: the count.

### P-B3c `features.rollout_budget = true` without `limit_tokens`
- Question: does Codex start with `features.rollout_budget = true` and no `limit_tokens`, and does it enforce anything?
- Why: `--with-rollout-budget` writes only the switch. `fail`: the flag needs values (DESIGN §3).
- Steps: `install.sh --with-rollout-budget --yes` (setup env), start `codex --profile codex`.
- Expected: it starts without a config error; record any reminder or limit it shows.
- Read: the start-up output and `/debug-config`.

### P-B3d is `features.hooks = true` needed
- Question: do the inline hooks run when `features.hooks` is absent from the profile?
- Why: the profile sets it defensively; if hooks are on by default the key is redundant, and if it is required the managed tier's pin matters.
- Steps: remove the key from the scratch profile file by hand, re-trust, run a prompt that calls a shell command, and look for guard activity (a state file under `$S/home/.local/state/codex-agent-stack/sessions/`).
- Expected: record whether the guard ran.
- Read: the sessions folder.

### P5 (extension) role files without `name` and `description`
- Question: does Codex accept a role file that has only `model`, `model_reasoning_effort` and `developer_instructions`, reached through `[agents.<name>].config_file` (absolute path) with the description in the profile?
- Why: the build's role files have no `name` or `description` (the vendored schema has none). `fail`: the role is rejected or ignored; add the keys back and relax `codex_state validate`.
- Steps: in the installed stack, ask BlackCat to spawn `coder` with a trivial message; check the spawn succeeds and that the subagent follows the role's instructions.
- Expected (pass): the subagent starts as role `coder` and `agent_type` is `coder` in the hook log (guard state or the spawn tree under the sessions folder).
- Read: the spawn result and the tree.

### Managed hooks from the managed directory
- Question: do the hooks in `[hooks] managed_dir` run from that directory with the command as written in `requirements.toml`?
- Why: `--print-requirements` writes `/bin/sh '<managed-dir>/codex-hook' <mode> --scope global`; whether Codex runs managed hooks from there is unverified. This probe needs the machine-wide tier: do it only if you intend to install it, and run the printed `sudo` lines yourself.
- Steps: after installing the tier, start `codex --profile codex` and run `/debug-config` and a prompt that tries `git push` in a scratch repository with a local bare remote.
- Expected: the managed hook denies the push (or the rule does; read which from the message), and `/hooks` lists them as managed.
- Read: `/debug-config`, the denial text.

### JSON deny with exit 0 for PermissionRequest
- Question: does a PermissionRequest hook that prints `{"hookEventName":"PermissionRequest","decision":{"behavior":"deny","message":"..."}}` and exits 0 deny the escalation?
- Why: that is the guard's wire format (it never uses exit 2 for a deny of this event). `fail`: the guard must also exit 2 for PermissionRequest.
- Steps: with the stack trusted, make the main thread (which may not escalate) or a read-only role such as `verifier` ask for a command that needs escalation (a write outside the sandbox roots into a scratch directory). If PreToolUse denies it first, pick a command that passes the read-only allowlist but needs the network.
- Expected (pass): the escalation request is refused with the guard's message and the command does not run.
- Read: the denial text and whether it names PermissionRequest; the hook log if you keep one.

### `spawn_agent` `tool_response` shape
- Question: what does PostToolUse carry in `tool_response` for `spawn_agent`?
- Why: the guard builds the spawn tree from it and parses it defensively; the keys it looks for are unverified. `fail`: the tree is empty and `send_input`/`resume_agent` routing is refused.
- Steps: spawn one subagent, then read `$S/home/.local/state/codex-agent-stack/sessions/<session_id>/state.json`.
- Expected: the spawned agent's id appears in the tree under the main thread.
- Read: `state.json` (the guard's tree) and, for the raw shape, a PostToolUse line if you log hook stdin as P13 does.

### Id keys of `send_input`, `wait_agent` and `close_agent`
- Question: which `tool_input` keys carry the target agent id for `multi_agent_v1send_input`, `multi_agent_v1wait_agent` and `multi_agent_v1close_agent`?
- Why: routing against the spawn tree needs the key names. `fail`: a call with an unrecognised key is refused (fail closed), so BlackCat could not message its agents.
- Steps: spawn an agent, `send_input` to it, wait for it, close it.
- Expected: all three succeed through the guard; none is denied for an unknown target.
- Read: the tool results and any guard denial text.

### Guard latency outside the sandbox
- Question: is the p95 of one hook call below 100 ms with `/usr/bin/python3` as the fallback interpreter?
- Why: it could not be timed inside the build sandbox (`xcrun` cannot write its cache there); the 3.13 and Apple 3.9 numbers are in the docstring of `tests/test_guard_perf.py`.
- Steps, from the repository root, outside any sandbox:

```
CODEX_GUARD_PERF_SHIM=1 uv run --no-project --python 3.13 --with pytest python -m pytest -q -s -p no:cacheprovider dot-config/dot-codex_config/tests/test_guard_perf.py
```

- Expected (pass): the shim test passes (p95 below 100 ms).
- Read: the printed percentiles and `<tmp>/p95.json`.

## Not observable here
U7 (`omit_tools_from` deferring MCP tools) and U8 (AGENTS.md byte budget) need the stack's real config; Phase 5's smoke covers them.
