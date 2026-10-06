<!-- markdownlint-disable MD013 MD033 MD041 MD060 -->
<p align="center"><img src="assets/blackcat-social-1280x640.jpg" alt="A giant black cat sits in a colourful toy-block city, licking its raised paw, its long tail stretched across violet and turquoise tiles while small white robots with antennae carry blocks past glowing code brackets, pipes and a terminal screen" width="100%"></p>

<p align="center"><sub>Image: photo by Pedro Miguel Rodrigues Jorge, AI-edited with OpenAI GPT Image 2.5 Sunburst via Opper, <a href="assets/LICENSE-CC-BY-4.0.txt">CC BY 4.0</a></sub></p>

# claude-agent-stack

claude-agent-stack is a multi-agent configuration for Claude Code on macOS. Its installer turns the Claude Code
config folder (`~/.claude` by default) into a team: **BlackCat**, a main-thread agent that only delegates, 56
specialist agents, 220 skills that load on demand, and hooks that enforce the limits on every tool call of every
agent. Agents never push; installing, publishing and anything destructive stay your steps.

This wiki explains the stack by topic. The repository's `README.md` and `CONFIG.md` remain the reference: every
number here was read from the files on `main` at commit `6ecb003` (2026-10-06), and each page ends with the files
it was taken from.

## Start here

| If you want to | Read |
|---|---|
| Install, update, back up or remove the stack | [Getting started](Getting-Started.md) |
| Understand how a prompt becomes work | [Architecture](Architecture.md) |
| See who does what | [Agents](Agents.md) · [Skills](Skills.md) |
| Know what is enforced, and by what | [Hooks and the guard](Hooks-and-Guard.md) · [Security model](Security-Model.md) |
| Let agents install tools | [Toolsmith](Toolsmith.md) |
| Run checks and merges with fixed recipes | [Instructor](Instructor.md) · [Testing and C10](Testing-and-C10.md) |
| Know what the installer writes into your `CLAUDE.md` | [The CLAUDE.md block](CLAUDE-md-Block.md) |
| Build the isolation images | [Container backend](Container-Backend.md) |
| Do the steps only you can do | [Operations and user steps](Operations.md) |
| Change the stack | [Contributing](Contributing.md) · [Changelog](Changelog.md) |
| Look something up | [FAQ](FAQ.md) · [Glossary](Glossary.md) |

## The stack in numbers

| Item | Count | How it was counted |
|---|---:|---|
| Agent files (BlackCat + specialists) | 57 (1 + 56) | `ls dot-claude/agents/*.md \| wc -l` |
| Agents on Opus / on Sonnet | 43 / 14 | `model:` in each agent's frontmatter (`tests/lint_agents.py` allows only `opus` and `sonnet`) |
| Leaves (no Agent tool) | 16 | `agent_guard.py --print-policy`, key `leaves` |
| Skills: hubs / modules / standalone | 220: 28 / 104 / 88 | `tests/test_skill_modules.py` `hubs_and_modules()` |
| Skill reference files | 182 | `ls dot-claude/skills/*/references/*.md \| wc -l` |
| MCP servers: agent-scoped / user scope / magg catalog | 17 / 5 / 23 | agents' `mcpServers`, README "MCP servers", `dot-claude/magg/config.json` |
| Environment keys `settings.json` ships (installer-owned) | 17 (8) | `dot-claude/settings.json` `env`; `OWNED_ENV` in `install.sh` |
| Tests collected in `tests/` | 5172 | `pytest --collect-only` on the tools venv, 2026-10-06 |

## Status

Shipped on `main` and covered by tests: the agents, skills, guard hooks, installer, toolsmith, the instructor and
the `CLAUDE.md` block. Shipped but deliberately passive or not yet proven:

- **The Bash sandbox is configured, not live-verified.** Until you run the live checks, count only the guard and
  the deny rules as tested ([Security model](Security-Model.md#what-is-not-verified)).
- **Observe-only mechanisms.** The output shrink (`STACK_OUTPUT_SHRINK=shadow`), the brief-budget and early-stop
  signals (`STACK_EARLY_STOP=observe`), the hand-back check (`STACK_REPORT_FORMAT=observe`) and the dynamic
  fan-out cap (`STACK_FANOUT_DYN=shadow`) log and change nothing by default.
- **Container isolation is opt-in.** `install.sh --with-eq-container` stops at a placeholder pin until the
  maintainer resolves it, and the `container` behaviour it relies on waits for your checklist C1–C13
  ([Container backend](Container-Backend.md)).
- **No measured comparison with plain Claude Code.** The one frozen baseline compares two versions of this stack;
  savings and quality gains are "by design, not measured" (README "Measured so far").

## Codex (planned)

> **Planned, not shipped.** A Codex port of the stack, with its own installer (`codex_config/`), is being designed.
> Nothing of it is in this repository yet, so this wiki describes no Codex behaviour. This section will be
> replaced once the port lands. Source: the project plan relayed with this wiki's brief, not a repository file
> (unverified).

## Licence

Code, docs and prompts are Apache-2.0 (`LICENSE`, `NOTICE`). The BlackCat images are CC BY 4.0, with the
attribution above; the licence text is in [assets/LICENSE-CC-BY-4.0.txt](assets/LICENSE-CC-BY-4.0.txt), and the
image's provenance (prompts, hashes, C2PA metadata) is recorded in the repository's `assets/PROVENANCE.md`.
Trademarks are not licensed.

Sources: `README.md` (introduction, "Measured so far", "Known limits", "License"), `CONFIG.md` §5 and §7,
`assets/README.md`, `assets/PROVENANCE.md`, the commands in the table above.
