<!-- markdownlint-disable MD013 MD060 -->
# Toolsmith: the dependency installer

Agents' Bash runs in the sandbox, which keeps toolchain and package directories read-only, so an agent cannot
install the program it needs. **toolsmith** fills that gap without loosening the sandbox for anyone else: it is
the only agent that may run `~/.claude/bin/stack-install`, the one program the stack takes out of the sandbox,
and that program installs only vetted, pinned packages from official registries and records each install with
its uninstall command. Anything outside those rules waits for your approval on a terminal.

## Parts

| Part | Role |
|---|---|
| `dot-claude/agents/toolsmith.md` | Sonnet, effort medium, 60 turns, a leaf; tools `Read, Bash, Skill`; `permissionMode: acceptEdits` (it writes no files, but as a subagent inheriting Plan it could never install) |
| `dot-claude/bin/stack-install` | the executor (Python 3.8+, stdlib, `#!/usr/bin/python3 -IB`) |
| `dot-claude/hooks/toolsmith_policy.py` | the rules: grammar, installer argv and environment, vetting verdicts, ledger fold; loaded by the executor from beside it and by the guard |
| `settings.json` | `sandbox.excludedCommands` = the executor only, by absolute path; `permissions.allow` = `Bash(<config>/bin/stack-install *)` |
| `agent_guard.py` `toolsmith_gate` | who may run the executor, and how (below); absolute, also with `STACK_POLICY=off` |

BlackCat (route "Dependencies"), the orchestrator, main-coder, ninja-coder and devops-engineer may spawn toolsmith;
every other agent returns `NEXT: toolsmith` with the package, installer and version it needs. The web readers
(researcher, scout, browser-operator) never reach it.

## Who runs what

- **Every agent but toolsmith, and the main thread:** any command whose command word is `stack-install` is
  refused, also behind quotes, `VAR=` prefixes and wrappers such as `env`, `exec`, `timeout`, `nice` or `xargs`.
  Reading or naming the file (`cat`, `git log -- …/stack-install`, a commit message) stays allowed.
- **toolsmith:** its Bash runs only that absolute path, alone, without shell syntax; its arguments must parse with
  the executor's own grammar, `--for` must name a stack agent, and `run <rq-id>` needs your approval on record.
  The hook then writes a one-use ticket for that exact argv, which the executor claims within 120 s; no ticket, no
  run.
- **You:** `approve`, `deny`, `list`, `pending`, `manifest` and `show` work only on a real terminal (stdin and
  stdout are ttys and `/dev/tty` opens).

## What installs without asking

| Installer | Spec | Command the policy fixes |
|---|---|---|
| Homebrew | `<formula>` from homebrew/core (no tap, path or URL) | `brew install --formula` |
| uv | `<name>==<version>` | `uv tool install --no-config --no-sources --default-index https://pypi.org/simple --no-build --exclude-newer <now − age>` |
| npm | `<name>@<x.y.z>` | `npm install --global --registry=https://registry.npmjs.org/ --ignore-scripts --before=<now − age>` |
| pnpm | `<name>@<x.y.z>` | `pnpm add --global --registry=… --ignore-scripts`, age via `PNPM_CONFIG_MINIMUM_RELEASE_AGE` |
| cargo | `<crate>@<x.y.z>` | `cargo install --locked` |
| go | `<host.tld/path>@v<x.y.z>` | `go install` with the official proxy and checksum database, `GOENV=off` |

Never: version ranges, tags, `latest`, git, URL, path or file sources, `sudo`, `pip`, a shell or a download piped
into one. The installer runs with an allowlisted environment (no tokens, no sandbox caches, no `HOMEBREW_*`,
`npm_config_*`, `UV_*`, `CARGO_*`, `GO*` or `PIP_*` of yours), a private temp and working directory, and stdin
`/dev/null`.

**Vetting** reads registry metadata over https (formulae.brew.sh, pypi.org, registry.npmjs.org, api.npmjs.org,
crates.io, proxy.golang.org). Refused outright: not found, yanked, a disabled formula, a tap other than
homebrew/core, a crate without binaries. A request for you instead (exit 3): a version younger than
`STACK_TOOLSMITH_MIN_AGE_DAYS` (7 days), a package first published less than 90 days ago, popularity under the
floors (npm 1,000 downloads last week, crates.io 10,000 in 90 days, Homebrew 1,000 installs on request in a
year), a deprecated formula or npm version, a PyPI release without a wheel, metadata that cannot be fetched,
`--allow-scripts` or `--allow-build`, or an executable name that is reserved (installers, git, ssh, sudo,
shells, python, pip, node, claude, gh, curl, core file tools, …) or already answers on PATH.

## Approval: your terminal, your typed id

```mermaid
sequenceDiagram
  accTitle: A toolsmith request that needs your approval
  accDescr: toolsmith records a request and returns blocked; BlackCat asks you; you approve in a terminal by typing the id; toolsmith then runs the approved request once.
  participant A as Requesting agent
  participant B as BlackCat
  participant T as toolsmith
  participant X as stack-install
  participant U as You (terminal)
  A->>B: NEXT: toolsmith (package, installer, version)
  B->>T: dispatch
  T->>X: install ... --why ... --for <agent>
  X-->>T: exit 3, request rq-id recorded
  T-->>B: STATUS: blocked, NEXT: ASK USER
  B->>U: AskUserQuestion
  U->>X: stack-install approve <rq-id> (shows command, reasons, checks; you type the id)
  B->>T: SendMessage with your answer
  T->>X: run <rq-id>
  X-->>T: installed, ledgered
```

An approval is valid for 24 hours and used once; a request changed after its approval is refused. An approved
install skips only the checks it failed, never the hard rules. Any other installer (a cask, gem, pipx, …) goes
through `request --why … -- <program> <args>`, whose program must be on an allowlist of installers and whose words
may name no `sudo`, `pip`, Python interpreter or shell.

## Ledger and management

`${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack/toolsmith/ledger.jsonl` (0600) records one event per line:
`attempt` (written before the installer runs), `installed`, `removed`, `failed`, `ran`, with installer, package,
version, source, why, for whom, who asked, the argv, the uninstall argv, the vetting report, the approval id and
the exit code.

| Command (your terminal) | Does |
|---|---|
| `~/.claude/bin/stack-install pending` | requests waiting for you (an expired approval shows as `expired`) |
| `~/.claude/bin/stack-install approve <rq-id>` / `deny <rq-id>` | decide one request |
| `~/.claude/bin/stack-install list [--all]` | what toolsmith installed |
| `~/.claude/bin/stack-install manifest` | a Brewfile-style list of `stack-install install …` lines that replays through the same vetting |

`upgrade` and `uninstall` act only on packages the ledger says toolsmith installed: a program you installed
yourself is never upgraded or removed (the skip rule, checked before any registry call). The state directory is
sandbox `denyWrite`, Edit-denied and a guard protected path; `/stack-doctor` has a "toolsmith" section.

## Limits you should know

- **Installed code runs as you, unsandboxed.** Vetting lowers the odds of a fresh or typosquatted compromise; it
  does not review code. `brew` installs the formula's current version, and cargo's and go's dependency trees have
  no age cutoff.
- **Configured, not live-verified.** That Claude Code runs the `excludedCommands` entry unsandboxed and the allow
  rule removes its prompt is README live check 8. If either does not hold, installs fail or prompt; they do not
  widen.
- **Approvals need a terminal you control:** anything running as you outside the sandbox could type them.

Tests: `tests/test_toolsmith.py` (grammar, argv and environment, vetting verdicts, the guard for every caller,
the executor against a fake installer and a fixture registry, end to end, and seeded bugs that each flip a probe).

Sources: `dot-claude/agents/toolsmith.md`, `dot-claude/settings.json`, `README.md` ("toolsmith: the dependency
installer", "Live checks" item 8), `CONFIG.md` §4 ("toolsmith"), §5 (`STACK_TOOLSMITH_MIN_AGE_DAYS`), §7
("Dependency installer: toolsmith", "Residual risks") and §9 (2026-10-06).
