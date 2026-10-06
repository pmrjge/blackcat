<!-- markdownlint-disable MD013 MD060 -->
# FAQ

## Using the stack

**How do I start a session without BlackCat?**
`claude --agent claude` gives a plain session. Any agent started with `claude --agent <name>` keeps all its tools;
only BlackCat is restricted.

**Why doesn't BlackCat run `git status` or make a one-line edit itself?**
It only delegates, by the user's decision of 2026-10-04 (CONFIG §9): Bash, Write and Edit are not on its tools line and the guard refuses
them even with `STACK_POLICY=off`. A look goes to explore, one command or a small edit to coder, merges and tests
to main-coder. Each costs a spawn.

**Why does every session start in Plan mode?**
`permissions.defaultMode` is `plan` in the shipped `settings.json`. Approve the plan, or press Shift+Tab, to change
the mode; to start in `bypassPermissions` again, set it in `~/.claude/settings.json` (the installer keeps a mode
you chose) or pass `--permission-mode` for one session.

**How do I talk to one agent directly?**
Start the prompt with `@<agent>` or `<agent>:` (for example `@verifier check …`); that agent gets the prompt
verbatim.

**How do I see who is working on what?**
`/stack-tree` for the live tree with each agent's commands and tokens; `stack-who` for a short list; the ledger is
`~/.local/state/claude-agent-stack/<session>/delegations.md`.

**Can I run one agent type on another model?**
`/override-agent coder opus` for this session only; `/override-agent list` and `/override-agent reset all`. The
model is applied; the effort is shown but not applied, because the Agent tool has no effort input. `haiku` is
refused: the stack runs no Haiku.

**Can an agent install a tool it needs?**
Yes, through [toolsmith](Toolsmith.md): Homebrew formulae, uv tools, npm/pnpm globals, `cargo install` and
`go install`, vetted and pinned, without asking you; anything else waits for your
`~/.claude/bin/stack-install approve <rq-id>` on a terminal.

**Why won't any agent push or open a pull request?**
Agents never push and never write to a forge, in any form; the no-push hook refuses it whatever `STACK_POLICY`
says. Publishing is your step; agents report the branch and commits.

## Installing

**Does it run on Linux or Windows?**
No. `install.sh` stops on any other system than macOS, and several parts depend on macOS (the `sips` image limit,
arm64-locked venvs, Keychain checks, the sandbox's `.git/modules` denies).

**Where do my API keys go?**
In `~/.claude/stack.env` (mode 0600), which agents cannot read. Remote MCP servers get their keys through
`bin/mcp-headers`, never `~/.claude.json`.

**I installed with `--config-dir` and Claude Code starts without BlackCat.**
Claude Code reads a non-default folder only when `CLAUDE_CONFIG_DIR` is exported: add
`export CLAUDE_CONFIG_DIR='PATH'` to `~/.zshrc` (bash: `~/.bash_profile`) and open a new terminal.

**How do I undo an install?**
`./install.sh --restore` undoes the latest; `--restore <backup-dir>` a given one. See
[Getting started](Getting-Started.md#backups-restore-and-the-manifest).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| A newly installed agent type is not found | a running session keeps the agent files it started with | quit every Claude Code session and start a new one |
| Claude Desktop runs one subagent at a time and seems to hang | foreground children (CONFIG §1, bugs 1 and 3) | keep `BLACKCAT_BACKGROUND` unset or `1`; remove `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT` |
| The status line starts with a red `! Bash sandbox env missing` | the session-env hook could not write `$CLAUDE_ENV_FILE` | run `bash ~/.claude/bin/doctor.sh`, then start a new session or `/clear` |
| `claude-ninja` or `uv` "not found" although installed | `~/.local/bin` is not on `PATH` yet | open a new terminal |
| Hooks stop working after the config folder moved | `settings.json`, the hooks and the MCP entries hold absolute paths | move it back, or reinstall with `--config-dir <new path>` |
| Every tool call is denied with a message naming `./install.sh` | the hook interpreter cannot start (a fail-closed guard entry) | run `./install.sh` from the stack repo; `/stack-doctor` shows which part failed |
| `uvx …` fails inside a session | the sandbox keeps uv's tool dir read-only | `uv run --with <tool> …`, or run `uvx` in your terminal |
| Headless Chrome from Bash aborts | Chrome cannot start inside the Seatbelt sandbox | use the playwright MCP (browser-operator, frontend-engineer, verifier) |
| Installing a toolchain from a session fails | by design: toolchain dirs are read-only in the sandbox | install it from your terminal, or ask for toolsmith |
| Tests fail only inside a Claude Code session | sandbox limits ([Testing and C10](Testing-and-C10.md#known-environment-failures)) | run the suite from your terminal |

## About the project

**Is it cheaper or better than plain Claude Code?**
Not measured. The one frozen baseline compares two versions of this stack, not the stack with plain Claude Code,
and no run recorded cost. Savings and quality gains are "by design, not measured" (README "Measured so far").

**Why is it called BlackCat?**
The repository does not say. The README offers an interpretation (planning for bad luck, landing on its feet,
nine lives spent in order, `cat` concatenating outputs), labelled as such.

**Does the stack support Codex?**
Not yet. A Codex port with its own installer (`codex_config/`) is being designed; nothing of it is in the
repository (see [Home](Home.md#codex-planned)).

Sources: `README.md` ("Why BlackCat?", "First run", "Typical workflows", "Commands", "Permission modes",
"Accounts and API keys", "Requirements", "Troubleshooting", "Measured so far"), `CONFIG.md` §1, §5 ("Session
model overrides") and §7 ("Hook interpreter").
