<!-- markdownlint-disable MD013 MD060 -->
# docs/wiki: the claude-agent-stack wiki

This folder holds the wiki's pages as Markdown. They read on GitHub's repository view as they are, and follow the
GitHub wiki conventions (`Home.md`, `_Sidebar.md`, `_Footer.md`, hyphenated page names) so they can be copied into
the project's GitHub wiki. Start at [Home](Home.md).

## Pages

| Page | Covers |
|---|---|
| [Home](Home.md) | what the stack is, numbers, status, the planned Codex port |
| [Getting started](Getting-Started.md) | requirements, `install.sh` steps and options, dry run, diff, backups, restore, manifest, update, uninstall |
| [Architecture](Architecture.md) | BlackCat, layers L1–L8, spawn policy, fan-out, messages, the delegation ledger, hand-backs, models, MCP scopes |
| [Agent roster](Agent-Roster.md) | the 57 agents by family: model, effort, turns, tools, MCP servers, spawn rows, fan-out |
| [Skills](Skills.md) | hubs, modules and standalone skills, the listing states, the full catalogue |
| [Hooks and the guard](Hooks-and-Guard.md) | the hook launcher, wiring, what is enforced, what is only observed, knobs |
| [Security model](Security-Model.md) | assets and threats, layers, sandbox, permission rules, supply chain, residual risks, what is unverified |
| [Toolsmith](Toolsmith.md) | the dependency installer: parts, gate, vetting, approval, ledger |
| [Instructor](Instructor.md) | the `just` recipes `check-suite`, `ff-merge`, `worktree-audit` and their allow rules |
| [The CLAUDE.md block](CLAUDE-md-Block.md) | the one block the installer owns in your `CLAUDE.md` |
| [Container backend](Container-Backend.md) | eq-container images, the WALL, installer steps 10b/10c, checklist C1–C13 |
| [Testing and C10](Testing-and-C10.md) | the C10 suite, known environment failures, what the tests cover |
| [Operations and user steps](Operations.md) | reinstall, live checks, the paid probe, the c0 runbook, worktree cleanup, `RESET_TO_MAIN.sh`, the instructor rule's side effect |
| [Contributing](Contributing.md) | worktrees, fast-forward merges, C10, reviews, evidence-gated rounds, conventions |
| [Changelog](Changelog.md) | `CONFIG.md` §9, condensed |
| [FAQ](FAQ.md) | common questions and troubleshooting |
| [Glossary](Glossary.md) | the terms used across the stack and these pages |

`_Sidebar.md` and `_Footer.md` are the GitHub wiki's sidebar and footer.

## Accuracy

Every fact was read from the repository on `main` at `6ecb003` (2026-10-06); each page ends with its sources.
`README.md` and `CONFIG.md` stay the reference: where this wiki and they disagree, they win, and the wiki needs a
fix. Counts come from commands (each page names them), not from memory. The roster tables on [Agent roster](Agent-Roster.md)
and the catalogue on [Skills](Skills.md) were generated from the agent and skill files and the guard's
`--print-policy` output: regenerate them rather than editing them by hand.

## Assets

| File | What it is | Licence |
|---|---|---|
| `assets/blackcat-social-1280x640.jpg` | the header image on Home (the repository's social preview, byte-identical copy of `assets/` at the repository root) | CC BY 4.0 |
| `assets/blackcat-avatar-640.png` | the sidebar avatar (byte-identical copy) | CC BY 4.0 |
| `assets/LICENSE-CC-BY-4.0.txt` | the licence text, so the attribution travels with the images | — |

Attribution: "Photo by Pedro Miguel Rodrigues Jorge, AI-edited with OpenAI GPT Image 2.5 Sunburst via Opper".
Trademarks are not licensed. Provenance (prompts, hashes, the C2PA-bearing original) is in the repository's
`assets/PROVENANCE.md`; the copies here match the SHA-256 values recorded there. The repository's assets hold no
SVG logo, so the header is the 2:1 social-preview JPEG.

## Checks

```bash
uv run --with pytest pytest -q tests/test_wiki_links.py     # links, anchors, images, alt text, sidebar
markdownlint-cli2 "docs/wiki/*.md"                          # optional, if installed
```

`tests/test_wiki_links.py` runs with the rest of `tests/`, so it is part of C10.

## Copying to the GitHub wiki

The GitHub wiki is its own git repository (`<repo>.wiki.git`); a local checkout of it belongs in `github-wiki/` at
the repository root, which stays git-ignored. Copying the pages there and pushing is your step. Links here use the
`Page.md` form, which resolves in the repository view; whether the GitHub wiki resolves the `.md` suffix is
unverified. If it does not, strip it in the copy:

```bash
sed -i '' -E 's/\]\(([A-Za-z0-9_-]+)\.md(#[^)]*)?\)/](\1\2)/g' github-wiki/*.md
```

Mermaid diagrams are fenced ` ```mermaid ` blocks, which github.com renders in repository files; their rendering
in the wiki is unverified.
