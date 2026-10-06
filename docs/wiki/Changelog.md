<!-- markdownlint-disable MD013 MD060 -->
# Changelog (condensed)

A condensed reading of `CONFIG.md` §9, newest first. The full entries there name every knob, file, test and
reason; most changes take effect only after you rerun `./install.sh` and restart Claude Code. Commit history from
before publication is in `PREVIOUS_GIT_COMMITS.md`.

## 2026-10-06

- **Wiki pages tracked in `docs/wiki/`** (this wiki): `docs/wiki/` is no longer git-ignored; `tests/test_wiki_links.py` checks the pages.
- **Prompt trims (stage-4 L10):** text the rules already state removed from the rules, game-engineer and the orchestrator; no behaviour change (about 26 tokens less per spawn).
- **Hand-back check reads `SubagentHandback`** (L7 B1): a nested subagent's hand-back message is parsed, checked and recorded like a reply, never blocked. **First-write log** (L7 B3): `stack_progress.py` records the API call of a run's first write or delegation.
- **toolsmith**, the dependency installer: a new agent, the executor `bin/stack-install` and `hooks/toolsmith_policy.py`; vetted, pinned, ledgered installs, anything else on your terminal approval; knob `STACK_TOOLSMITH_MIN_AGE_DAYS` (7).

## 2026-10-05

- **The instructor**: `tools/instructor/` with `check-suite`, `ff-merge` and `worktree-audit`; one allow rule per recipe; the absolute deny `Edit(//**/tools/instructor/**)`.
- **The `CLAUDE.md` block**: the installer owns one marked block in your `CLAUDE.md` and nothing else in it.
- **Brief budgets and early-stop signals**, observe only (`hooks/stack_progress.py`, `STACK_EARLY_STOP`).
- **3D specialists**: rigger-animator, sculptor-painter and procedural-3d-ui, with the hub `3d-animation` and new modules.
- **`--with-eq-container`**: the container isolation images (Apple `container` 1.5.0) and the WALL as installer steps 10b and 10c, opt-in and never fatal; WALL deny rules on every install.
- **Output shrink** in shadow mode (`hooks/output_shrink.py`).
- **The orchestrator holds Bash** for checks and integration, under the same no-push and protected-path checks as builders plus BlackCat's web-command check.
- **README images moved to `assets/`** at the repository root; `docs/wiki/` was git-ignored (reversed on 2026-10-06).

## 2026-10-04

- **BlackCat delegate-only, hook-enforced**: `STACK_BLACKCAT_DELEGATE_ONLY` (default 1) holds the tool allowlist and the read cap even with `STACK_POLICY=off`; a Stop hook logs turns without a reply; `BLACKCAT_MAX_DISPATCH` retired. It builds on another entry of the same date, **BlackCat only delegates** (Bash, Write and Edit dropped from its tools line).
- **Simplification phase 0**: the guard's own depth check removed (Claude Code withholds the Agent tool at depth 8).
- **Installer**: always prunes (`--no-prune` and a bare `--force` removed); legacy-version migrations removed (upgrade through `4286278` first); `--with-lsp` installs jdtls and names a cause for every missing language server; `install.sh --diff`; the skip rule (an existing tool is never installed over, upgraded or removed); hooks on `bin/stack-python` (Python 3.13) with precompiled bytecode.
- **Roster**: supreme-coder retired (ninja-coder is the top tier); coder is a leaf; the copy types retired; db-engineer and localizer retired.
- **Messaging**: no peer-to-peer messages, the `USER:` relay, the observe-only credential scrub; rules for eight layers and `delegation.md`.
- **Lazy skill listing**: 32 skills described, 96 name-only; non-stack skills hidden.
- **Compaction survival**: PreCompact snapshot and SessionStart digest of the ledger.
- **Spawn list**: a main thread with no `POLICY` row may spawn every stack agent.
- **Redundancy lint** (`tests/redundancy_lint.py`).

## 2026-10-03

- **Open-file limit** offered before step 2 (a LaunchDaemon, sudo only after `y`); the Lean group.
- **The installer sets up prerequisites and toolchains** (`lib/devtools.sh`).
- **Hand-back protocol, phase 1**: `STACK_REPORT_FORMAT=observe` by default.
- **Budgets**: session budget seed 1.92 billion context tokens, re-seeding of unlearned limits on install, `autoCompactWindow` 629,000 (another entry of the same date had set 900,000).
- **Plan as the default mode**, `acceptEdits` on the agents that write, BlackCat's step cap 24; MCP allow rules for computer-use, lean and mobilebuild.
- **Install target**: `--config-dir`, any clone location, any user name.
- **User commands**: `/stack-tree`, `/stack-doctor` answered by a hook, `/override-agent` (session model overrides, effort shown but not applied; override runs are not learned from).
- **Read gate**; the tools venv; the prompt budget base frozen into a fixture; the Playwright MCP output kept out of the working tree; the hero image under CC BY 4.0.
- Superseded the next day: "BlackCat does small jobs itself" and the rename of the top-tier coder to supreme-coder.

## 2026-10-02

- **Usage collector** and scheduler model refresh (`stack_usage.py`, `stack_sched_refresh.py`).
- **Soft token limits** and `maxTurns` set from measured turn counts.
- **Agent SDK**: `bin/stack_sdk.py`.

## 2026-09-29

- **Security rounds 2, 3 and 4**, security findings C1–C9, T1–T3 and P3 fixed; residual risks listed in CONFIG §7.
- **Desktop hang fixed**: BlackCat's children always run in the background.

Sources: `CONFIG.md` §9 (every entry above), `.gitignore`, `tests/test_moved_paths.py`.
