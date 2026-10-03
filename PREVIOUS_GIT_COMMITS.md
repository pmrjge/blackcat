# Previous git commits

History of the project before it was published as a fresh repository; generated from the git log of the former repository at commit `3f62cc8` on 2026-10-03; 237 commits, all by Pedro Jorge. The project was created with Claude Code (https://claude.com/claude-code) using Anthropic's Claude models, under the author's direction; messages of commits made with it end with a Co-Authored-By line naming the model. Newest first, grouped by month. Each entry gives the date, the short hash (kept so references in the text stay meaningful), the subject, the full message and a files-changed summary. Private data (home paths, e-mail addresses, keys, session ids) was removed or replaced.

## 2026-10

### 2026-10-03 19:32 · `3f62cc8`

**README Guard hooks: the per-call mode is stripped too**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +1/-1.* `README.md`.

### 2026-10-03 19:31 · `9ab382c`

**Review fixes: a rollback's stale mode record, the Agent mode input, a FIFO probe log**

> code-reviewer (MEDIUM): an older installer run after this one rewrites the manifest's commit and
> sets bypassPermissions but keeps settings_permission_scalars, which then said "plan" and kept the
> rolled-back bypassPermissions as if chosen. The record now names its commit
> (settings_permission_scalars_commit) and counts only when that is the last install's commit; else
> the commit's settings.json decides. Proof: smoke §13c "rollback through an older installer" fails
> without the fix (8 passed, 1 failed) and passes with it (9 passed).
> security-auditor: the Agent tool's `mode` input ("Deprecated; ignored" in the 2.1.287 schema) is
> stripped from every spawn, so no caller picks its child's permission mode should a later version
> honour it (test_agent_mode_input_is_removed). The probe log opens with O_NONBLOCK: a FIFO planted
> there hung the hook (HEAD: timeout; now rc 0 with a warning; test_probe_never_hangs_on_a_fifo).
> code-reviewer (LOW): test_protected_paths' docstring no longer calls bypassPermissions the stack's
> default. CONFIG.md notes the mode strip.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +50/-6.*

### 2026-10-03 19:08 · `c30b758`

**Docs: permission modes (Plan by default, 45 acceptEdits writers, launchers, probe), step cap 24**

> README: Usage → "Permission modes" (the inheritance table from the docs, the 45 writers and the 11
> agents without a mode, what a switch to Plan does and does not do, the launchers, what is not
> verified, headless runs under Plan, how to go back to bypassPermissions, the upgrade); First run
> and Typical workflows say sessions start in Plan; permissions.defaultMode in Main knobs;
> STACK_MODE_PROBE in Knobs; live check 6 needs a bypass session now; a Contributing line on agent
> modes; 24 tool calls in Guard hooks. CONFIG.md: §5 rows (permissions.defaultMode, STACK_MODE_PROBE)
> and a "Permission modes" section with the probe procedure (including the main-thread case) and
> what each outcome means; §6 launchers start in Plan; changelog entry with the docs facts.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +106/-6.* `CONFIG.md`, `README.md`.

### 2026-10-03 19:04 · `8996fa4`

**permissionMode: acceptEdits on the 14 other agents that write files**

> The user's principle (subagents only): "most ssubagents must run in accept edits or else it will
> bloat context for them too and lag on resolution time". orchestrator, designer, writer,
> researcher, doc-specialist, image-director, claude-code-engineer, cg-artist, motion-designer,
> data-scientist, mcp-broker, mathematician, browser-operator and vfx-td have Write, Edit or
> NotebookEdit and no mode: in a Plan session they inherited Plan and could not write. Now 45
> agents carry acceptEdits; without a mode: blackcat (the main thread follows the session's mode)
> and the 10 read-only agents (claude-code-guide, code-reviewer, explore, oracle, plan-reviewer,
> planner, proof-checker, scout, security-auditor, verifier). None of the 14 is in READONLY_TYPES.
> Frontmatter only: bodies unchanged (prompt_budget --check ok). test_permission_modes pins the
> exact sets.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 15 files, +24/-7.*

### 2026-10-03 19:01 · `d4a5d62`

**BLACKCAT_MAX_STEPS 12 -&gt; 24; BlackCat's rule 5 says builders edit even in Plan**

> The user: "make it 24". BLACKCAT_MAX_DISPATCH stays 8 and BLACKCAT_MAX_OWN_STEPS 4 (24 - 4 &gt;= 8:
> a full dispatch burst still fits after own work; the invariant lives in
> test_shipped_caps_leave_room_for_a_full_dispatch_burst). settings.json, the guard's three
> defaults, docstring and comment, blackcat.md, the tests that pin the shipped caps
> (test_shipped_spawn_defaults: 24 allowed then a deny; the own-work test: 4 own + 8 dispatches +
> 12 more, the 25th refused), the smoke pins, README and CONFIG §5. blackcat.md rule 5 now says why
> builders wait for the approved plan: their files carry acceptEdits, which wins over a Plan parent.
> Body length unchanged (5,187 chars; prompt_budget --check ok).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +28/-25.*

### 2026-10-03 18:59 · `b3fe905`

**Guard: STACK_MODE_PROBE, an opt-in log of the permission mode hooks see**

> The docs are silent on whether a running subagent follows a mode switch, on nested spawns and on
> permission_mode inside subagent hook events. With STACK_MODE_PROBE=1 the guard appends one JSON
> line per PreToolUse (`budget` mode, which sees every tool call, also with STACK_POLICY=off),
> PermissionRequest and SubagentStart event to &lt;state root&gt;/mode-probe.jsonl: time, session, event,
> tool name, agent type and id, depth (registry), permission_mode when the event carries one; never
> the tool input. 0600, opened O_NOFOLLOW and only if it is our regular file, no line past 1 MB; a
> failure warns and decides nothing. settings.json wires PermissionRequest to the guard, which returns
> no decision (the dialog, or a headless denial, proceeds as before). Off by default; nothing is
> enforced on the result (the enforcement follow-up waits for the probe). Tests in
> tests/test_permission_modes.py; STACK_MODE_PROBE joins test_agent_guard's scrubbed knobs.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +166/-3.* `dot-claude/hooks/agent_guard.py`, `dot-claude/settings.json`, `tests/test_agent_guard.py`, `tests/test_permission_modes.py`.

### 2026-10-03 18:57 · `02a1789`

**lint_agents: permissionMode is acceptEdits on builders or plan on read-only agents**

> Per the docs (sub-agents.md, permission-modes.md, fetched 2026-10-03) an agent file's
> permissionMode wins over a parent in plan, default or dontAsk, so in a Plan session it decides the
> subagent's mode. The 31 builder files keep permissionMode: acceptEdits (the user: subagent runs
> must not stop at edit prompts, for context and latency). New rule: acceptEdits only on agents with
> Write/Edit/NotebookEdit (no tools: line counts as every tool), plan only on read-only agents;
> default, auto, dontAsk and bypassPermissions are errors, with the docs rule in the message.
> tests/test_permission_modes.py: bad fixtures fail (each other mode, acceptEdits on a read-only
> agent, plan on a builder), allowed ones pass, the shipped files comply, settings ship plan. No agent
> file changes: no read-only agent carried acceptEdits.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +120/-0.* `tests/lint_agents.py`, `tests/test_permission_modes.py`.

### 2026-10-03 18:56 · `b03c13d`

**claude-ultracode starts its main thread in Plan unless you pass a mode**

> claude-ninja, claude-supreme and claude-ultracode &lt;agent&gt; run a builder agent as the main
> thread. The builders' files carry permissionMode: acceptEdits for their subagent runs, and the
> docs do not say whether Claude Code applies that line to a main-thread agent; the user wants
> acceptEdits only for subagent runs. The launcher now passes --permission-mode plan, unless the
> arguments already hold --permission-mode[=...] or --dangerously-skip-permissions (scanned up to
> `--`). The flag overrides the settings file; that it also overrides the agent file is expected,
> not verified. tests/test_ultracode_launcher.py (fake claude): plan added once, a mode you pass
> wins and is not doubled, `--` ends the scan, forge tokens still unset; the smoke pin follows.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +105/-2.* `dot-claude/bin/claude-ultracode`, `tests/install_smoke.sh`, `tests/test_ultracode_launcher.py`.

### 2026-10-03 18:55 · `0327d09`

**Default permission mode Plan; the installer keeps a mode you chose**

> settings.json ships permissions.defaultMode "plan" (was "bypassPermissions"). install.sh no
> longer overwrites a scalar permissions key on every run: like the unowned env keys, the stack's
> value is set while you have none or still hold the value the stack shipped last time, and a value
> you chose is kept ("kept your permissions.defaultMode=..."). The manifest records the shipped
> scalars (settings_permission_scalars); for a manifest older than that, the last install's commit
> is read from this repository (earlier installers overwrote the mode on every run, so the value in
> place was that commit's). An install still on the earlier shipped bypassPermissions moves to plan
> once, with a note on how to change or restore it; when the recorded commit is not in the
> repository nothing is changed and the installer says why. A scalar the stack stops shipping is
> retracted while unchanged. Smoke §13c covers the upgrade, a chosen mode, a restored bypass and
> an unknown commit.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +124/-7.* `dot-claude/settings.json`, `install.sh`, `tests/install_smoke.sh`, `tests/test_blackcat_tools.py`.

### 2026-10-03 18:40 · `232bb4c`

**Regenerate PREVIOUS_GIT_COMMITS.md**

> 227 commits up to 75db02f, sanitised by the generator (no home paths,
> e-mails, keys, session ids, no old agent name).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +126/-6.* `PREVIOUS_GIT_COMMITS.md`.

### 2026-10-03 18:39 · `75db02f`

**prompt_budget --check: frozen base measurement when the base commit is absent**

> In a clone without the base revision (the fresh repository, an export
> without .git) every ratio check was skipped. tests/fixtures/prompt_budget_base.json
> holds the base's measure() output reduced to what check() and the table read
> (the one base agent no current agent matches is left out: check() never
> compares it); prompt_budget.py falls back to it for DEFAULT_BASE. Tests: the
> fixture equals a live measurement when the commit is present; without it,
> --check uses the fixture and fails on a seeded violation. Verified in a copy
> without .git: "ratio checks use its frozen measurement", check ok.
> README Contributing and CONFIG.md changelog follow.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +123/-4.* `CONFIG.md`, `README.md`, `tests/fixtures/prompt_budget_base.json`, `tests/prompt_budget.py`, `tests/test_prompt_budget.py`.

### 2026-10-03 18:22 · `a75dae6`

**README Contributing: history-bound checks skip in a clone without those commits**

> prompt_budget.py's ratio checks and the collector upgrade tests in
> test_stack_usage.py read older commits through git; verified in a git archive
> export without .git: --check passes with "ratio checks skipped", and
> test_prompt_budget.py + test_stack_usage.py give 57 passed, 8 skipped.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +3/-1.* `README.md`.

### 2026-10-03 18:20 · `5cc4858`

**install.sh creates the Playwright MCP output dir (0700) that doctor.sh checks**

> The agents' inline Playwright entries and the magg catalog pass
> --output-dir ~/.cache/claude-sandbox/playwright-mcp, but nothing created it:
> doctor.sh checks every path in MCP args and FAILed on a fresh install. The
> apply step now makes it (umask 077, chmod 700) when an installed entry names
> it; --dry-run creates nothing. Tests: test_playwright_mcp.py pins the path to
> the entries; install_smoke §8 checks it under a scratch HOME, doctor's
> silence about it and --dry-run. CONFIG.md changelog.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +34/-0.* `CONFIG.md`, `install.sh`, `tests/install_smoke.sh`, `tests/test_playwright_mcp.py`.

### 2026-10-03 18:17 · `ff5e732`

**README knobs: ● only for the keys the installer owns, ○ for shipped defaults**

> install.sh resets only its 10 OWNED_ENV keys on every install; the other 10
> keys dot-claude/settings.json ships follow upgrades while unchanged and a
> changed value is kept ("kept your env ..."). The table said all 20 were reset.
> tests/test_readme_knobs.py pins ● to OWNED_ENV and ● + ○ to the shipped env.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +72/-11.* `README.md`, `tests/test_readme_knobs.py`.

### 2026-10-03 18:16 · `cc8c205`

**.gitignore: complete Python, secrets, editor/OS and log rules; local hand-off folders**

> Adds claude_next_steps/ and github-wiki/ (local, never committed), the full
> Python cache/build section, secrets (stack.env, .env\*, keys; the shipped
> lib/stack.env.example stays tracked), editor/OS files and logs/archives.
> No tracked file is hidden: git ls-files -ci --exclude-standard is empty.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +54/-5.* `.gitignore`.

### 2026-10-03 18:16 · `b575efe`

**Remove supreme-coder's previous-name compatibility layer**

> The rename shipped with shims for the agent's previous name; the installed
> copies are migrated, so they go:
>
> - install.sh: the RENAMED and RENAMED_ENV entries for the previous agent
>   file, knobs and limit overrides, and the old launcher-link note (the
>   generic mechanism stays, still used and tested by senior-coder and router)
> - bin/claude-ultracode: the old launcher alias; doctor.sh: its three warnings
> - agent_guard.py: lock/marker adoption and the old type spelling in norm()
> - stack_limits.py / stack_usage.py: RENAMED_TYPES, renamed_type, the env
>   override and live.json carry-over, the old fixed-guard prefix; rows from
>   before the rename are no longer aliased
> - tests: the alias, migration and carry-over cases; derive\_\*.py no longer
>   map recorded types; the sched fixture names supreme-coder.md
> - README and CONFIG.md: notes removed, changelog entries name agents by
>   their current names, new entry for the removal
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 15 files, +40/-239.*

### 2026-10-03 17:02 · `86ffb58`

**Regenerate PREVIOUS_GIT_COMMITS.md**

> Now from main at 9970940 (220 commits): adds the install-target commits
> and the CC BY 4.0 hero.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +125/-1.* `PREVIOUS_GIT_COMMITS.md`.

### 2026-10-03 17:02 · `9970940`

**README, NOTICE, CONFIG: credit the new hero; lib/assets images under CC BY 4.0**

> - README: alt text describing the new image, the credit line under the
>   hero, a License section split into code/docs/prompts (Apache-2.0) and
>   the images in lib/assets (CC BY 4.0, attribution to the author for his
>   photograph, to the extent rights exist, trademarks not licensed, links
>   to the legal code and the provenance); the contributing note follows.
> - NOTICE: the images in lib/assets are licensed under CC BY 4.0 instead
>   of excluded and all rights reserved.
> - CONFIG.md: changelog entry.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +24/-25.* `CONFIG.md`, `NOTICE`, `README.md`.

### 2026-10-03 17:00 · `be79cd8`

**lib/assets: new hero (variant B) under CC BY 4.0, with its unmodified original and provenance**

> Replaces the previous AI-edited hero, social preview and avatar and their
> all-rights-reserved statement. The new image is the author's photograph of
> his cat, edited with OpenAI GPT Image 2.5 Sunburst via Opper.
>
> - blackcat-hero-original.png: the model output byte for byte (keeps its
>   C2PA manifest); blackcat-hero.jpg, blackcat-social-1280x640.jpg and
>   blackcat-avatar-640.png: resized copies (no metadata).
> - LICENSE-CC-BY-4.0.txt: the CC BY 4.0 legal code (plain text).
> - README.md: licence, attribution wording, provenance note, trademarks
>   not licensed. PROVENANCE.md: prompts, settings, hashes, licensing notes;
>   the source photograph is not included (hash only).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +479/-59.*

### 2026-10-03 16:50 · `21ca24b`

**install.sh --config-dir: review fixes (case, order, forged lines, missing value)**

> - Paths compare by inode as well as by name: ~/.SSH, /USERS/&lt;you&gt; or the
>   repo in other case are refused on case-insensitive APFS, and ~/.CLAUDE
>   counts as the default.
> - The foreign-target refusal and the [y/N] question run before the
>   main-branch rule, so "Nothing was changed" holds on a side branch; a yes
>   carries to the re-run via STACK_TARGET_CONFIRMED (only with
>   STACK_MAIN_REEXEC=1 and the same target).
> - config-dir output escapes control characters, and install.sh takes the
>   first path line only: a newline in CLAUDE_CONFIG_DIR or STACK_CLAUDE_JSON
>   can't forge the target.
> - --config-dir followed by an option is a missing value (exit 2).
> - A foreign folder named by CLAUDE_CONFIG_DIR is a warning, not a refusal:
>   scripted runs that write a log into the target first keep working.
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 6 files, +140/-28.*

### 2026-10-03 16:33 · `3c6d6f6`

**Docs: choosing the config folder (--config-dir), Intel untested, troubleshooting**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +82/-9.* `CONFIG.md`, `README.md`.

### 2026-10-03 16:33 · `0857e7c`

**Tests: neutral paths instead of the author's home**

> /Users/example/project in test_protected_paths, ~/.claude in the
> test_blackcat_tools docstring, /tmp/q/me in test_guard_round2, and
> derive_thresholds strips any -Users-&lt;name&gt;- project prefix.
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 4 files, +11/-11.* `tests/derive_thresholds.py`, `tests/test_blackcat_tools.py`, `tests/test_guard_round2.py`, `tests/test_protected_paths.py`.

### 2026-10-03 16:33 · `09ceb5f`

**install.sh: --config-dir, target banner and confirmation, unsafe-target refusals**

> --config-dir PATH (or =PATH) beats CLAUDE_CONFIG_DIR, which beats ~/.claude.
> lib/install_state.py config-dir expands, resolves and checks the target before
> the main-branch rule merges anything: /, $HOME and its parents, the repo
> checkout, credential and system folders, the stack's state, files, unwritable
> paths, '..' through a symlink and shell metacharacters exit 2. A foreign
> non-empty folder needs a y on a terminal. Every run prints the target, its
> source and the .claude.json it implies; a non-default or ambiguous target is
> confirmed only when stdin and stdout are terminals and none of --yes,
> --no-prompt, --dry-run, --mcp-plan applies. The run exports CLAUDE_CONFIG_DIR
> for its claude commands, prints the export line and profile file, and warns
> that moving the folder takes a reinstall. The script follows a symlink to
> itself; bash login shells get a ~/.bash_profile note; doctor.sh warns about a
> non-default install with CLAUDE_CONFIG_DIR unset.
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 5 files, +835/-14.* `dot-claude/bin/doctor.sh`, `install.sh`, `lib/install_state.py`, `tests/install_smoke.sh`, `tests/test_installer_config_dir.py`.

### 2026-10-03 16:03 · `7aca04c`

**Regenerate PREVIOUS_GIT_COMMITS.md**

> Generated from main at 0e11144 (213 commits) with the same sanitising generator, so it now lists
> the public-layout commits and the README follow-ups; the commit that regenerates it comes after
> 0e11144 and is not listed. CONFIG.md §9 copied as it stands at 0e11144.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +92/-8.* `PREVIOUS_GIT_COMMITS.md`.

### 2026-10-03 16:02 · `0e11144`

**README: model-agnostic Co-Authored-By rule**

> Contributing now asks for a `Co-Authored-By: Claude` trailer on commits
> made with Claude Code, the model name optional after "Claude" as in the history, instead of
> prescribing one model's trailer. Credits keeps the model names found in the trailers.
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 1 file, +3/-2.* `README.md`.

### 2026-10-03 16:01 · `1c3f562`

**README, CONFIG: describe earlier commits instead of citing their hashes**

> A repository published with fresh history has none of the pre-publication commits, so
> `git show <hash>:README.md` and bare hashes would point nowhere. Each citation now names the
> commit by date and subject, with a pointer to the commit history in PREVIOUS_GIT_COMMITS.md.
> The legacy/be5b940 changelog entry no longer gives git log/show commands for the same reason.
>
> Kept: `ad22962` (tests/prompt_budget.py DEFAULT_BASE, the gate baseline) and `6a736c6`
> (tests/test_stack_usage.py V2_REV, the schema-2 collector the hand-off test runs); both tests skip
> when the commit is absent.
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +31/-22.* `CONFIG.md`, `README.md`.

### 2026-10-03 15:47 · `da021b7`

**Supply diff covers the tests/derive\_\*.py scripts install.sh copies into hooks/**

> Review finding (older than the layout change): install.sh copies tests/derive_sched_model.py and
> tests/derive_thresholds.py into hooks/, but SUPPLY_PATHS did not list them, so changes to these
> installed files never showed in the pre-apply diff. Both are listed now; the R3-SUPPLY test checks
> every script of that copy loop is covered. CONFIG.md §7 names them.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +9/-6.* `CONFIG.md`, `install.sh`, `tests/test_guard_round3.py`.

### 2026-10-03 15:41 · `25f89fa`

**Hero image in lib/assets (all rights reserved), Claude Code attribution, NOTICE, previous commits**

> - lib/assets/: the new hero (1600 px JPEG), social preview and avatar, with README.md (not under
>   Apache-2.0 or any open licence: the author's contribution all rights reserved, the AI-generated and
>   AI-edited elements subject to Sourceful's, Riverflow's and OpenRouter's terms; forks replace them)
>   and a sanitised PROVENANCE.md (the author's photograph is referenced by hash only; the model output
>   carries no provider metadata, so the stripped derivatives lose nothing).
> - docs/assets/ (the earlier AI-only hero and its CC0 text) removed; no CC0 or CC BY claim remains.
> - README: new hero path and alt text, credit and AI-edited lines under it, a "Created with Claude Code"
>   line, Credits section (models named as in the commit trailers), License rewritten for the image's
>   real status, Contributing rules for claude-local-work/ and the Co-Authored-By trailer.
> - NOTICE (Apache-2.0 §4(d)): copyright with the author, created with Claude Code, lib/assets excluded.
> - PREVIOUS_GIT_COMMITS.md: pre-publication history, generated from main (e0c0e12); lint exempts it
>   from the model-ID rule.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 11 files, +3534/-139.*

### 2026-10-03 15:35 · `ad063c4`

**Public layout: stack.env.example under lib/, mcp_servers.md into CONFIG.md, working files out of git**

> - stack.env.example moves to lib/stack.env.example; install.sh, doctor.sh's hint, the scheduler's
>   shared-docs list, lint and the tests read it there.
> - SUPPLY_PATHS lists lib/install_state.py and lib/stack.env.example instead of the whole lib/, so
>   README images under lib/assets/ never show in the pre-apply diff; the R3-SUPPLY test checks every
>   "$HERE/&lt;path&gt;" install.sh reads lies under a supply path, and the smoke test that lib/assets/ stays out.
> - mcp_servers.md becomes CONFIG.md §10 "Apps, connectors and MCP servers" (headings shifted, the stale
>   agent and skill counts dropped); README links and the duplicate-row test follow.
> - RESUME.md and the force-added campaign files under .claude-work/ leave git (kept locally under
>   claude-local-work/); README no longer links to them.
> - .gitignore: claude-local-work/, .claude/worktrees/, .claude/settings.local.json.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 133 files, +506/-126507.*

### 2026-10-03 15:20 · `e0c0e12`

**Playwright MCP output out of the working tree**

> @playwright/mcp 0.0.82 writes auto-named output (unnamed screenshots,
> snapshots, console logs, traces) to &lt;cwd&gt;/.playwright-mcp/ when no
> --output-dir is given. The inline entries (browser-operator,
> frontend-engineer, verifier) and the magg catalog entry now pass
> --output-dir \_\_HOME\_\_/.cache/claude-sandbox/playwright-mcp (absolute:
> the server does path.resolve without ~ expansion) and --file-paths
> absolute, so results name a path Read accepts. --headless --isolated
> unchanged; .playwright-mcp/ added to .gitignore; test asserts the args.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +101/-7.*

### 2026-10-03 15:19 · `a609d89`

**README: fold the licence into the rewrite**

> Image credit moves under the hero image (centred, small); Contents links
> the License section; the Contributing bullet no longer says the repository
> has no LICENSE file.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +4/-3.* `README.md`.

### 2026-10-03 15:07 · `32387c4`

**Hero image under CC0-1.0 with credit line; CC0 legalcode in docs/assets**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +129/-6.* `README.md`, `docs/assets/LICENSE-CC0.txt`.

### 2026-10-03 15:04 · `479d31d`

**README licence note: hero image model is openai/gpt-image-2.5-sunburst; cite OpenAI Services Agreement §4.1**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +7/-6.* `README.md`.

### 2026-10-03 15:00 · `d9e4a1d`

**Add Apache-2.0 licence**

> LICENSE: canonical Apache License 2.0 text (byte-identical to
> apache.org/licenses/LICENSE-2.0.txt, 11358 bytes) with the appendix
> copyright line filled in. README: a License section (SPDX id, scope,
> third-party software, hero image excluded with the terms that apply).
> No NOTICE file: the licence does not require one and the audit found no
> third-party attributions to carry.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +216/-0.* `LICENSE`, `README.md`.

### 2026-10-03 14:59 · `ff554d5`

**README: GitHub-style rewrite with macOS requirements, features, usage and hero image**

> Hero image, Why BlackCat, use cases, overview of what the stack adds, macOS-only
> requirements, install and update, usage, troubleshooting, contributing; base text
> rebased on acec941 (supreme-coder rename). Fact-check fixes applied. CONFIG.md:
> skill count 214; the agent-variant proposal marked as decided against.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +694/-40.* `CONFIG.md`, `README.md`, `docs/assets/blackcat-hero.png`.

### 2026-10-03 14:54 · `b4dba98`

**Remove legacy/be5b940; smoke tests take old-release files from tests/fixtures**

> install.sh keeps its generic legacy/&lt;version&gt;/&lt;rel&gt; recognition, which finds
> nothing while legacy/ is absent; only untracked (pre-manifest) files of that
> release are affected, and only towards keeping more. The CLAUDE.md migration
> cases put tests/fixtures/legacy-release under the scratch repo's legacy/ and
> remove it before a new case checks an unrecognised old CLAUDE.md is kept.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 15 files, +57/-277.*

### 2026-10-03 14:34 · `acec941`

**Rename review fixes: lock and marker files from before the rename adopted, old limit overrides and live state carried over, seed pools sorted, rules under budget, installer migration smoke test**

*Files changed: 10 files, +126/-8.*

### 2026-10-03 14:21 · `0589b98`

**Rename the top-tier coder agent to supreme-coder: compatibility shims for old saved state, read-time alias for old usage rows, changelog**

*Files changed: 12 files, +102/-10.*

### 2026-10-03 14:21 · `b834396`

**Rename the top-tier coder agent to supreme-coder (scripted mechanical rename: agent file, guard tables, knobs, launcher, docs, tests)**

*Files changed: 42 files, +492/-492.*

### 2026-10-03 14:19 · `43f441e`

**BlackCat does small jobs itself: Read, Bash, Write, Edit on the main thread**

> BlackCat (the main thread) gains Bash, Write and Edit (drops Grep/Glob, which
> never resolve next to Bash on macOS/Linux) so a job of a few tool calls (a
> look, a small edit, one command, git inspection) no longer costs a spawn;
> specialist, long, parallel and review work is still dispatched and the
> orchestrator keeps dependent multi-specialist jobs.
>
> Guards: no-push/protect/secrets, the Edit deny rules and the sandbox apply to
> the main thread unchanged (tests/test_blackcat_tools.py). blackcat-guard adds:
> no web content from BlackCat's Bash (T1; linear tokenizer check, review fix
> for CWE-184 and the 20,000-char scan window), at most 4 own calls per prompt
> (BLACKCAT_MAX_OWN_STEPS, so a burst of 8 dispatches always fits in 12 steps),
> and no foreground Bash timeout over 120 s (BLACKCAT_BASH_TIMEOUT_MS). The
> prompt orders dispatches before own calls. A context: fork skill's agent now
> inherits Bash. doctor.sh probes blackcat-guard with WebFetch.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 11 files, +478/-76.*

### 2026-10-03 13:53 · `17223cb`

**stack-tree review fixes: resumed agents, per-message usage, more secret shapes, linear redaction, hook deadline**

> code-reviewer on 845b6f4, each with a proof in tests/test_stack_tree.py that failed before:
>
> - F1 an agent resumed by SendMessage (SubagentStart clears `stopped`) shows running, not finished
> - F2 usage per message id takes the largest values over its lines (earlier lines: partial output_tokens)
> - F3 masks name: value / JSON "name": "value" pairs with a secret-like name, mysql -p, sshpass/docker
>   login -p, pass:, aws configure set ...secret..., sk_live\_/sk_test\_, npm\_, hvs., dckr_pat\_
> - F4 hook output is cut by lines, so a JSON document over the cap still shows its start
> - F5 abbreviated --help never prints to stdout; F6 markdown cells escape &; F7 the cut line names
>   the shown session
> Own finding: the old key: value pattern backtracked cubically (0.55 s at 1,000 chars, minutes at
> 8,000). It is now a linear scan, untrusted text is cut to 1,200 chars before redaction, the STATUS
> pattern no longer spans blank lines, and the hook stops itself after 20 s (unread transcripts:
> unscanned; unfiltered text: withheld, never raw).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +190/-33.* `CONFIG.md`, `dot-claude/bin/stack-tree`, `tests/test_stack_tree.py`.

### 2026-10-03 13:35 · `33645a5`

**/stack-tree: read-only agent tree, table and static hierarchy, answered by a UserPromptExpansion hook**

> bin/stack-tree reads the guard's delegation records (spawns/, delegations.md as fallback), its
> agent registry and Claude Code's transcripts, and prints the session's tree of agents with each
> agent's tool calls as collapsed leaves (status from the ledger and the final STATUS line, duration,
> tokens, calls); --table gives one GFM row per agent and per tool call, --static the designed
> hierarchy from agents/\*.md (May spawn lists, BlackCat -&gt; L4). Untrusted strings are redacted, then
> stripped of control/format characters, then cut; tool results are classified, never printed; state
> files are read only when regular. No writes, no bytecode, no network.
>
> /stack-tree = `stack-tree --hook` (matcher stack-tree, timeout 30 s): blocks the expansion with
> the output, so BlackCat needs no Bash and no model turn runs. install.sh stages and tracks the
> script and STACK_HOOK_RE recognises the hook; doctor.sh checks the wiring.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 10 files, +1594/-9.*

### 2026-10-03 13:24 · `ed0641d`

**Add RESUME.md hand-off and frozen pre-Bayesian stats**

*Files changed: 106 files, +124091/-130.*

### 2026-10-03 12:40 · `19bcd56`

**stack budget security review: static only in the repo, escaped output, hostile-row filter, own session, read-only model load**

> - static runs tests/prompt_budget.py only from the stack repo (HERE == &lt;root&gt;/dot-claude/bin, &lt;root&gt;/install.sh):
>   an installed copy no longer runs $(dirname &lt;config dir&gt;)/tests/prompt_budget.py
> - safe() escapes control, C1 and format characters at every print site fed by a graph, a row, a snapshot or a session id
> - rows pass stack_limits.parse_row (the learner's hostile-CSV filter); compacted &gt;= 1 is unhealthy (a count)
> - plan uses the shown session for the model and soft limits, never the ambient STACK_LIMITS_SNAPSHOT / CLAUDE_SESSION_ID
> - stack_limits.snapshot_view: the read-only half of session_limits; stack_sched.session_snapshot uses it, so a
>   snapshot vanishing between two reads no longer makes the model load write a snapshot or a tamper marker
> - robustness: non-dict or deeply nested budget.json / live.json, NaN in a snapshot (tamper), non-numeric snapshot
>   values, odd snapshot file names, a huge n, malformed model rows: degrade or exit 1, never a traceback
> - agent TYPE checks the base type (scout12345 is refused); no bytecode written beside the hooks
>
> tests/test_stack_budget_security.py: 20 proofs, all failing on 44c9fd5.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +305/-48.* `dot-claude/bin/stack-budget`, `dot-claude/hooks/stack_limits.py`, `dot-claude/hooks/stack_sched.py`, `tests/test_stack_budget_security.py`.

### 2026-10-03 12:34 · `0b3e022`

**/stack-doctor runs doctor.sh from a UserPromptExpansion hook, not a forked agent**

> The forked claude-code-guide got only Read, ToolSearch and Skill: a forked skill's agent
> draws its tools from the main conversation's pool, and BlackCat has no Bash. Even with Bash,
> the read-only guard refuses `bash doctor.sh` for claude-code-guide, and sandboxed Bash cannot
> read stack.env or ~/.claude.json (false FAILs). `doctor.sh --hook` (matcher stack-doctor) runs
> the check outside the sandbox, bounded at 150 s, and blocks with the FAIL/WARN summary.
> install.sh's STACK_HOOK_RE recognises the hook; doctor.sh checks the wiring.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 8 files, +122/-17.*

### 2026-10-03 11:52 · `44c9fd5`

**RESUME.md: handoff for the next session (state on main, install checks, B0-B3 job, cleanup)**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 1 file, +135/-0.* `RESUME.md`.

### 2026-10-03 11:48 · `0a04a59`

**Replay waves review fixes: no wave with a dependent, releases from the first dispatch, committed 4e2da3ce fixture, honest held-out numbers**

> stack_sched.py (replay only; plan/next/emit-workflow output byte-identical):
>
> - cluster_waves: a unit never shares a wave with its prerequisite or its dependent, also at equal
>   timestamps or in a record order against the graph.
> - replay: a release is measured from the window's first dispatch (the simulated origin), not its
>   first start. Neither fix changes a number on the recorded data.
>
> tests/fixtures/sched/4e2da3ce/: the snapshot the graph fixture was built on (2026-10-02 20:27 UTC,
> window 52 still open), ids and numbers only; the recorded-session replay tests run instead of skipping.
>
> derive_wave_sim.py, closed sessions only (4e2da3ce, cc39b6a0; 13998b29 is still being written):
>
> - headline = groups with more than one message wave: 2 of 12 within 2% held out (before: 2 of 12);
>   all groups 25 of 35, of which 23 single-wave groups never exercise the barrier.
> - CIs resample (session, dispatcher) clusters, labelled crude.
> - message waves are not barrier waves (negative gaps between them); the earlier "2% in every window is
>   unreachable (2.24%)" is withdrawn: on the replay's rule waves 2% in every window needs a stagger of
>   at least 13.5 s (lat 22 s), above every median in-wave gap measured (at most 9.0 s).
> - replay of 4e2da3ce: 18 of 19 windows within 2% in-session (max 2.96%), 16 of 19 held out
>   (max 4.18%; fold fitted on cc39b6a0 alone, gap a tie from 15 to 300 s); windows with a barrier
>   (1, 3, 21, 36): 3 of 4 in-session, 2 of 4 held out.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +544/-54.*

### 2026-10-03 11:39 · `b5b0dfe`

**Hand-off audit: a session row older than its session's rows is not learned; model IDs on lint-allowed constant lines**

> Audit of d779dfe (MEDIUM): SIGTERM makes the older collector's final scan write
> a `complete` session row with the context of that moment; when the successor
> idles out (no final scan) nothing replaces it, so soft.session/hard.session
> learned a truncated session. stack_limits.read_rows now leaves out a session
> row whose last_ts is below another row of its session (stats and
> proposals.json: stale_session); a final scan's row spans all its rows and stays.
>
> lint_agents: the 15 model-ID findings of f1831df. The usage, limits and budget
> tests keep their model IDs (synthetic transcripts, matcher vectors) on
> module-level constant lines, allowed per file by MODEL_ID_CONST; the
> stack_usage.py comment names no ID. dot-claude/agents is not loosened.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +109/-23.*

### 2026-10-03 11:29 · `a1bcb2d`

**lint_agents: skip paths under .claude-work/ (any depth, tracked or not)**

> Agents' scratch, some of it force-committed in 910275c, made the model-ID check report 185
> findings. under_work_dir() judges only the components below the repo root, so a checkout that
> itself lives in a .claude-work/ still lints its own files; look-alike names and shipped files
> in dot-claude/ are still checked. Tests: tracked, walked, symlinked, nested and relative roots;
> bare-python and retired-skill checks.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +102/-4.* `README.md`, `tests/lint_agents.py`, `tests/test_lint_skills.py`.

### 2026-10-03 11:10 · `d779dfe`

**Collector upgrade hand-off: a start stops a running older-schema collector, a successor rereads as schema 3**

> Audit follow-up (MEDIUM) to the model column: a collector keeps the code it
> started with, so after an install it kept writing model-less schema 2 rows for
> /override-agent runs typed later, and those counted as evidence. A start that
> finds collector.lock held now SIGTERMs the holder when collector.json is an
> older schema's, unexited, with a fresh heartbeat and a live pid (and, where ps
> runs, the pid runs this session's `stack_usage.py run`); the old collector does
> its final scan and exits with reason "signal" (no propose, no refit). A
> successor waits up to 120 s for the lock and reads the session again from the
> start; its schema 3 rows win per key, older rows stay (append-only).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +196/-7.* `CONFIG.md`, `dot-claude/hooks/stack_usage.py`, `tests/test_stack_usage.py`.

### 2026-10-03 10:54 · `f1831df`

**Override runs are no evidence: segment model column (schema 3), filtered by the learners**

> Security audit of f235e7a (MEDIUM): an /override-agent run (e.g. scout on haiku)
> fed soft.agent.scout, turns.scout, the pool proposals and the scheduler refit
> that later sessions on scout's own model use, against the "this session only"
> scope (CONFIG.md section 5).
>
> - stack_usage.py: schema 3 rows in usage/runs3.csv (runs3.lock) with `model`,
>   the transcript's message.model for the segment's calls (one id, `mixed` for
>   two, empty when none; `<synthetic>` is no model). runs\*.csv and runs2\*.csv
>   are read as before (model empty = unknown) and never written: a collector
>   started before an upgrade keeps appending to its own file. An older
>   collector's state is read again from the start.
> - stack_limits.py: agent_models() (agent_guard.agent_defaults' parse),
>   model_mismatch() by alias substring; read_rows skips mismatched agent rows
>   after the last-row-wins merge and counts them (proposals.json
>   model_mismatch). soft.prompt.&lt;type&gt; windows follow.
> - stack_sched_refresh.py: the same filter before fit(); refresh.model_mismatch.
> - stack-budget: samples leave the rows out and every view shows the count.
> - CONFIG.md: section 5 (collector files and columns, override scope, budget)
>   and the changelog.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +591/-173.*

### 2026-10-03 11:10 · `cd34b33`

**Replay barrier simulation: per-dispatcher timelines, dependency-aware waves, releases, stagger, first-start origin**

> Window 2 (-37%) and 18 (+9.6%) of the recorded replay are now within 2%; 18 of 19 windows
> within 2% (max 2.96%, window 3: the orchestrator's 99 s before a 5-unit wave). WAVE_GAP_S 60 s
> chosen by pairwise F1 against the dispatchers' own message waves (leave-one-session-out).
> tests/derive_wave_sim.py: held-out check over sessions; with the true waves and the stagger in
> its measured range no (lat, stagger) meets 2% in every window (best worst case 2.24%).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +638/-29.* `dot-claude/hooks/stack_sched.py`, `tests/derive_wave_sim.py`, `tests/test_derive_wave_sim.py`, `tests/test_stack_sched.py`.

### 2026-10-03 10:51 · `14af4ef`

**Scheduler policy back to report (advice-only); fresh_fixer opt-in; MCP-cap and support-rule tests**

> User decision 2026-10-03: STACK_SCHED_POLICY defaults to report (stack_limits.SCHED_POLICY_DEFAULT,
> stack_sched.soft_values); `next` prints the ready ids only, the fresh-fixer advice on stderr needs
> STACK_SCHED_POLICY=fresh_fixer. A session keeps its snapshot's policy (tests: default, opt-in,
> mid-session env change, resume, new session).
> Tests: T1b pins STACK_MAX_MCP_CALLS and the web caps as fixed guards (live, proposals, snapshot);
> T6b the A5 support-rule boundaries. Docs: doctor wording, README/CONFIG rows; the ctx budgets are
> learned and no longer shipped (README marker fixed).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +129/-14.*

### 2026-10-03 10:33 · `6a736c6`

**/override-agent reset replaces /reset-agent; FIFO at the override state no longer hangs the hook**

> Reset is a subcommand beside list (`/override-agent reset <agent|all>`); malformed subcommands are
> refused with the usage; the reset-agent skill goes (install.sh's pruning removes it). Security
> audit of f235e7a (LOW): the state read and the log append open with O_NONBLOCK and refuse
> anything but a regular file, so a FIFO planted at the path no longer blocks PreToolUse(Agent);
> proof test test_a_fifo_at_the_state_path_does_not_hang_the_agent_hook. Effort stays display-only.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +85/-54.*

### 2026-10-03 10:23 · `1987381`

**/override-agent &lt;agent&gt; &lt;model&gt; + /reset-agent; built-in effort table per (agent, model)**

> Renames /agent-override, /agent-reset (no aliases; install.sh prunes the old skills); two
> arguments only, a third is refused with the usage. hooks/agent_effort.json (initial defaults,
> rule v1 from frontmatter effort and model tier; staged by install.sh) gives the effort, clamped
> to the resolved model's levels (Claude Code 2.1.287 checks) and stored with the override, so a
> later table change never alters a running session's override. Effort stays recorded, not
> applied (no per-call effort). Self-test and doctor check the table; lint allows model IDs in the
> table and its test.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 17 files, +745/-485.*

### 2026-10-03 10:05 · `25137fb`

**tests: five-session U4 loop (V2b) and the PreToolUse budget-hook latency harness (V2a)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +216/-0.* `tests/bench_guard_latency.py`, `tests/test_stack_limits.py`.

### 2026-10-03 10:01 · `d28e2ff`

**Learned limits batch 2: refit env scrubbed, state locks unreadable in the sandbox, bounded append lock, compacted as a count, finite --step, live snapshots never pruned**

> - S1: refresh() runs uv with --no-config, cwd /, PATH=/usr/bin:/bin:/usr/sbin:/sbin and without
>   VIRTUAL_ENV, CONDA_PREFIX, CONDA_DEFAULT_ENV, UV_INTERNAL\_\_PARENT_INTERPRETER, UV_PYTHON,
>   UV_CONFIG_FILE, PYTHONPATH, PYTHONHOME (refresh_env); install.sh's cache warm-up uses the same env.
> - S2: sandbox denyRead \_\_STACK_STATE\_\_/\*\*/\*.lock and \*\*/\*.mutex (a flock from a read-only fd stalled the
>   collector, the limits commands, the read gate and the guard); append_rows waits at most 5 s for
>   runs2.lock, then TimeoutError (scan_once reloads its state, the next tick appends).
> - S3: parse_row reads `compacted` as a count (&gt;= 1 -&gt; 1): twice-compacted segments were dropped.
> - S4: stack_sched_refresh --step must be finite and &gt; 1 (nan/inf passed).
> - V1: a snapshot is touched at each SessionStart of its session, and the 30-day prune keeps a session
>   whose guard folder changed within the window (a running session never loses its values, U4).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 10 files, +262/-31.*

### 2026-10-03 10:02 · `4f8f6f2`

**Spider: anti-bot defaults from 77f5638 are the default again (SPIDER_ANTIBOT=1); polite mode is opt-in**

> - hooks/web_caps.py: SPIDER_ANTIBOT defaults to 1, which behaves exactly like 77f5638 (88 spider
>   events compared, 0 differences); respect_robots fill/refusal, the crawl delay floor and the
>   concurrency cap now apply only in polite mode (SPIDER_ANTIBOT=0), with the bypass refusals.
> - web-research "Blocked pages": escalation order kept; no "refused by default" wording; Spider's
>   server-side stealth/residential escalation documented as a known property.
> - researcher, stack.env.example and tests follow.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +60/-48.* `dot-claude/agents/researcher.md`, `dot-claude/hooks/web_caps.py`, `dot-claude/skills/web-research/SKILL.md`, `stack.env.example`, `tests/test_web_caps.py`.

### 2026-10-03 09:51 · `f235e7a`

**/agent-override and /agent-reset: per-session model override for delegated agent types**

> User skills agent-override/agent-reset (disable-model-invocation); agent_guard.py agent-override
> on UserPromptExpansion (user-typed slash commands only; blocks the expansion, the reason is the
> output) writes &lt;state&gt;/&lt;session&gt;/agent-overrides.json (0600, atomic, O_NOFOLLOW read, session-id
> and enum checked); on_agent sets `model` for the overridden subagent_type after every gate;
> SessionStart startup\|resume\|clear clears it. Effort is recorded, not enforced (no per-call effort
> in the Agent tool). doctor.sh probes the hook; docs in CONFIG.md §5, README, claude-code-extensions.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 10 files, +766/-17.*

### 2026-10-03 09:40 · `f986727`

**Spider polite mode: robots.txt, crawl delay, concurrency; bypass refused by default; blocked-page playbook**

> - hooks/web_caps.py: always fills respect_robots=true and refuses false; crawl delay filled and
>   floored at SPIDER_DELAY_MS (1000), concurrency_limit filled/capped at SPIDER_CONCURRENCY (2);
>   SPIDER_ANTIBOT=0 (default) refuses spider_unblocker, spider_browser_open, spider_ai_browser,
>   proxy_enabled/proxy/remote_proxy/country_code, fingerprint=true, user_agent and cookies and sends
>   fingerprint=false; SPIDER_ANTIBOT=1 restores the 77f5638 anti-bot defaults.
> - web-research: "Blocked pages" (recognise; backoff retry honouring Retry-After -&gt; rendered
>   spider_scrape -&gt; jina/exa/cached copy -&gt; browser-operator -&gt; report blocked; counts against caps).
> - researcher: challenge pages follow that order instead of unblocker/CAPTCHA-solving sessions.
> - stack.env.example documents the new knobs; self-test and tests cover them.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +104/-24.* `dot-claude/agents/researcher.md`, `dot-claude/hooks/web_caps.py`, `dot-claude/skills/web-research/SKILL.md`, `stack.env.example`, `tests/test_web_caps.py`.

### 2026-10-03 09:35 · `10490ec`

**Rotation audit follow-ups: archive with a bad header or no read access set aside, header check in bytes, the writer never emits a quoted cell**

> - \_rotate_if_needed: a runs2.1.csv whose header the strict reader would not see (BOM, stray byte,
>   another header, EACCES) read as no rows and was replaced by runs2.csv's rows; it is set aside as
>   runs2.1.unreadable-&lt;epoch&gt;.csv. read_rows(strict=True) raises Unreadable on an open error other than
>   a missing file.
> - \_header_ok compares bytes: one bad UTF-8 byte in runs2.csv's first 8 KB made every append raise.
> - Validation patterns end in \\Z ($ let a trailing newline through), and append_rows skips a row with an
>   invalid session, id, type or status: no written cell needs csv quoting, which \_csv_rows relies on.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +86/-16.* `dot-claude/hooks/stack_usage.py`, `tests/test_stack_usage.py`.

### 2026-10-03 09:21 · `ba378aa`

**Learned limits review/audit fixes: scope hits count as tight, strict rotation sets unreadable files aside, per-line CSV reads, task keeps plain words, uv/ps by absolute path**

> - M1: prompt/session limit firings tripped by a subagent's call credit the main window (load_hits keeps
>   the kind; SCOPE_KINDS); an agent's hit_soft is its own soft_agent only; the session row gets hit cells
>   from soft_session/hard_session (empty without limit-hits.jsonl); soft_session does not mark a window.
>   stack_limits.\_entry counts main/session rows with no status code as tight.
> - M2: rotation reads strictly; a runs2.csv or runs2.1.csv with a line the csv module refuses, a NUL or
>   bad UTF-8 is set aside byte for byte as runs2[.1].unreadable-&lt;epoch&gt;.csv (never over an earlier one)
>   instead of being rebuilt from the rows ahead of that line.
> - F2: \_csv_rows in both modules parses each physical line on its own: a bad line, NUL or unbalanced
>   quote costs only itself in normal reads (errors="replace").
> - F1: `task` keeps the plain words of the Agent description (no digits, paths, URLs, flags, keys);
>   CONFIG.md privacy wording.
> - Hardening: uv and ps from fixed absolute paths, resolved once, never PATH; skipped quietly when absent.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +386/-52.* `CONFIG.md`, `dot-claude/hooks/stack_limits.py`, `dot-claude/hooks/stack_usage.py`, `tests/test_stack_limits.py`, `tests/test_stack_usage.py`.

### 2026-10-03 07:38 · `d8038a3`

**Tools venv: install.sh syncs ~/.claude/venvs/tools from hash-locked requirements/tools.txt (pytest, numpy, pandas, httpx, mcp, pillow, neural-memory; Python 3.13, arm64 wheels, sci's cooldown); doctor checks its imports; full suite runs on it; a test keeps tools.in covering every third-party import; extras get their own lock**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 10 files, +907/-8.*

### 2026-10-03 07:10 · `a56c649`

**S4: stack-budget, one read-only view of the limits (summary, plan, agent, static; three-way verdicts with intervals; never writes snapshots or live.json); staged by install.sh**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 4 files, +655/-2.* `CONFIG.md`, `dot-claude/bin/stack-budget`, `install.sh`, `tests/test_stack_budget.py`.

### 2026-10-03 07:10 · `5a8a23b`

**tests: test_derive_helpers_are_the_shared_core compares behaviour, not module identity (order-independent)**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 1 file, +5/-1.* `tests/test_sched_snapshot.py`.

### 2026-10-03 07:02 · `18b8411`

**S6 follow-ups: turn gate lets the last turn run (calls &gt; turns); the collector's exit refresh passes --session; session-env exports STACK_LIMITS_SNAPSHOT**

> - agent_guard.py: the turn gate refuses from call T + 1 (the T-th call keeps its tools, as Claude
>   Code's own maxTurns stop does); report calls still pass; the refusal still asks for STATUS: partial
> - agent_guard.py session-env: `export STACK_LIMITS_SNAPSHOT=<state>/limits/snapshots/<sid>.json`
>   (stack_limits.snapshot_path's formula, from the id alone, never waiting for the file) into
>   CLAUDE_ENV_FILE; a later session id appends its own line, which wins
> - stack_usage.py: refresh(session=...) adds `--session <sid>` (ID_RE-checked) to
>   stack_sched_refresh.py; run() passes its sid at exit
> - tests: T9/T11/T18 and the other boundary cases follow calls &gt; turns; session-env export and
>   stack_sched.session_id() resolving it from the sourced env file; the exit refresh's --session
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +114/-15.* `dot-claude/hooks/agent_guard.py`, `dot-claude/hooks/stack_usage.py`, `tests/test_limits_guard.py`, `tests/test_stack_usage.py`.

### 2026-10-03 04:28 · `38d2a22`

**S6 W4: install.sh stages stack_limits.py + seed and seeds live.json once; the two token budgets leave settings.json env (retired, retracted while unchanged); the guard starts the collector; doctor shows limits status, env overrides and sched_policy**

> - install.sh: stack_limits.py (755) and stack_limits_seed.json (644) staged and tracked in
>   STACK_SCRIPTS; `stack_limits.py seed` after apply (live.json only when absent, never rewritten);
>   STACK_PROMPT_CTX_BUDGET / STACK_SESSION_CTX_BUDGET out of OWNED_ENV, into RETIRED_ENV with their
>   shipped values (a user-set value stays as an override)
> - settings.json: the two env keys and the separate `stack_usage.py start` SessionStart entry removed
>   (agent_guard.py starts the collector at SessionStart since W2)
> - doctor.sh: `stack_limits.py status` line, a WARN naming env overrides that pin a learned limit,
>   the STACK_SCHED_POLICY line
> - tests: test_install_state.py installs an older stack then this one into a temp HOME (live.json
>   byte-identical across installs, the shipped budget retracted, the user's value kept);
>   install_smoke.sh checks live.json across its two runs and no longer expects the budget keys
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 6 files, +175/-25.*

### 2026-10-03 04:23 · `6a3612c`

**S6 step 4: stack_sched and the refresh read only the session-start limits snapshot (model copy, soft limits, sched_policy fresh_fixer advice in next); refresh reads runs2\*.csv; derive\_\* use the seed and stack_limits; T21**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 6 files, +522/-77.*

### 2026-10-03 04:17 · `152fd82`

**Guard: security re-review fixes (HIGH-a, HIGH-b): uv run refuses a scratch script whose PEP 723 block names a local package; scratch .venv/bin entry points, gradlew/mvnw and venv activate scripts are read, never trusted by name**

> - script_build(): `uv run [--script|--no-project] <scratch .py>` with an inline `# /// script` block
>   naming file:, a path, editable, a workspace, tool.uv or `@ ./~` is refused (its build backend
>   runs unread); index packages stay the accepted residual
> - by_path(): the trusted-directory shortcut (system bins, ~/.local/bin, venv bins, gradlew/mvnw)
>   no longer applies when the directory is scratch (lexically or after realpath)
> - source/. of a venv activate script is allowed only outside scratch
> - proof tests in tests/test_readonly_agents.py (red before, green after)
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +68/-4.* `dot-claude/hooks/agent_guard.py`, `tests/test_readonly_agents.py`.

### 2026-10-03 04:11 · `cbdb1db`

**S6 W2: guard reads the per-session limits snapshot (turn gate, hard.agent, soft.session, limit-hits/prompt-windows JSONL, SessionStart apply_and_snapshot + collector start)**

> - SessionStart (every source): stack_limits.apply_and_snapshot first, then stack_usage.hook_start, then the
>   budget catch-up; the notice goes out as systemMessage; limits/ is skipped by the 3-day prune
> - lean hash-checked snapshot reader on the hot path (no stack_limits import, ~1.5 ms); missing -&gt;
>   ensure_snapshot, altered -&gt; seed values + one stderr line (limits-tamper marker); stack_limits
>   unusable -&gt; SOFT_LIMITS / SOFT_PROMPT_CTX[\_BY_TYPE] / budget knobs / frontmatter as fallback
> - turn gate (seg_calls per run, same run-stamp rule as seg), hard.agent cap, soft.session warning;
>   budget_exempt calls always pass; deny texts name the origin and `stack_limits.py show`
> - limit-hits.jsonl (one line per firing) and prompt-windows.jsonl (one per prompt boundary), schema v1
> - MCP cap = min(STACK_MAX_MCP_CALLS, snapshot turns); fixed guards stay env-only
> - self-test: seed covers AGENTS, no fixed guard learnable, seed = fallback constants and frontmatter,
>   lean reader round trip; tests/test_limits_guard.py (T8-T11, T18); test_agent_guard.py follows the
>   snapshot semantics (env overrides wait for the next session, new deny wording)
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +946/-89.* `dot-claude/hooks/agent_guard.py`, `tests/test_agent_guard.py`, `tests/test_limits_guard.py`.

### 2026-10-03 03:48 · `15d32c8`

**Guard: audit fixes (scratch code always read, uv run never builds a scratch project) and a JS-runner scan that a big scratch dir can't break**

> - Audit HIGH-2: drop the "older than the agent's start" exemption; another agent's scratch
>   code is content-checked like the agent's own (first_started bookkeeping removed).
> - Audit HIGH-1: uv run refuses a scratch project it would build (setup.py, [build-system],
>   backend-path, package = true, path/workspace/file: sources, --with-editable or a local
>   --with); --no-sync and --no-project build nothing.
> - scratch_tests: scan the .claude-work of the JS runner's root (nearest package.json or runner
>   config up from the cwd) and of the cwd (the session cwd too when there is no root), bounded
>   only by the hook's deadline. The 20,000-entry cap refused every JS runner for reviewers once
>   a project's .claude-work held a venv (main: 170,132 entries, walk 0.56 s, no test files).
> - Tests: audit proof tests, uv build switches, big-scratch and deadline cases, runner-root
>   scope; the READ_ONLY/WRITES lists run in a hermetic empty project, never the checkout.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +213/-169.* `CONFIG.md`, `dot-claude/hooks/agent_guard.py`, `tests/test_readonly_agents.py`.

### 2026-10-03 03:47 · `e0d0540`

**Concurrency: CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS 32 -&gt; 33 (an orchestrator plus its 32 running children); CONFIG and doctor descriptions follow the orchestrator fan-out of 32**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +7/-7.* `CONFIG.md`, `README.md`, `dot-claude/bin/doctor.sh`, `dot-claude/settings.json`, `tests/install_smoke.sh`.

### 2026-10-03 03:37 · `2c15cf8`

**Fan-out: orchestrator runs up to 32 children (DEFAULT_FANOUT_BY_TYPE and STACK_MAX_FANOUT_BY_TYPE 10 -&gt; 32, plan DAG up to 32 tasks; user-set, 2026-10-03)**

> Mirrors: settings.json env, stack_sched DEFAULT_CAPS, guard self-test, README, CONFIG,
> install smoke and guard tests; new test: settings.json's value allows 32 running children
> and refuses the 33rd, and a lower env value still lowers it.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +28/-15.*

### 2026-10-03 03:03 · `1412edd`

**S6 W1+W3: interface test - collector v2 snapshot_cells and runs2.csv rows meet the proposer (regime key)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +22/-0.* `tests/test_stack_limits.py`.

### 2026-10-03 02:45 · `12c7124`

**S6 W3: usage collector v2 (runs2.csv schema 2: tool counts, writes, topology, status_code, main-thread and session rows, provenance; v1 history read, never written; propose before refresh)**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +1064/-139.* `dot-claude/hooks/stack_usage.py`, `tests/test_stack_usage.py`.

### 2026-10-03 03:01 · `56ab1e8`

**S6 W1: soft.prompt.&lt;type&gt; from SOFT_PROMPT_CTX_BY_TYPE (user-set: seed = floor), prompt_soft_limit()**

> The seed gains soft.prompt.orchestrator (80M, floor 80M, ceiling max(100M, seed)): the learner can
> only raise it; its sample is the prompt windows in which an agent of that type ran (agent rows'
> window joined to main rows). Invariant soft.prompt.&lt;type&gt; &lt;= 0.67 x hard.prompt only while
> hard.prompt is set and supported: hard.prompt is raised within its ceiling, else both hold.
> prompt_soft_limit(values, running_types) mirrors agent_guard.soft_prompt_ctx for W2.
> Tests: seed parity with SOFT_PROMPT_CTX_BY_TYPE, 1k random proposals never below 80M.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +118/-21.* `dot-claude/hooks/stack_limits.py`, `dot-claude/hooks/stack_limits_seed.json`, `tests/test_stack_limits.py`.

### 2026-10-03 02:51 · `9881bb9`

**S6 W1: new-evidence gate on the sample the rules use (pool rows no longer move an own-sample decision)**

> Found by the replay on a copy of usage/ (variant B): a supported type kept stepping on its own
> unchanged rows whenever its pool had new rows. Regression test added.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +21/-7.* `dot-claude/hooks/stack_limits.py`, `tests/test_stack_limits.py`.

### 2026-10-03 02:46 · `48e8c20`

**S6 W1: stack_limits core - learned limits, proposer, per-session immutable snapshots**

> dot-claude/hooks/stack_limits.py (stdlib, Python 3.8+): seed/live/proposals/snapshot files under
> limits/, decision rules of s6-design-v2 section 4 (support, provisional hi, pooled, dead band,
> bounded damped steps, invariants), apply_and_snapshot as the only place values change (U4),
> ensure_snapshot, session_limits, propose (runs\*.csv + runs2\*.csv, hostile-CSV filter, bootstrap
> CIs), and the section 5 CLI. stack_limits_seed.json: turns from frontmatter maxTurns, soft.\* from
> agent_guard SOFT_LIMITS/SOFT_PROMPT_CTX, pools from derive_thresholds TIER.
> tests/test_stack_limits.py: T1-T7, T12-T17, T19, T20, seed parity, stdlib-only, hook interpreter.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +3018/-0.* `dot-claude/hooks/stack_limits.py`, `dot-claude/hooks/stack_limits_seed.json`, `tests/test_stack_limits.py`.

### 2026-10-03 03:31 · `d63dc4e`

**orchestrator: soft cap ~32 spawns per job (was ~12; user-set, 2026-10-03)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +1/-1.* `dot-claude/agents/orchestrator.md`.

### 2026-10-03 03:03 · `e810a87`

**Guard fixes from the deny-rule scan: foreign scratch code, $TMPDIR, read-only additions, sandbox env and hosts**

> - Read-only agents: a file under .claude-work whose mtime and ctime predate the agent's
>   first start (registry first_started, kept across resumes) runs like project code; its
>   same-dir imports the agent wrote are still read. A scratch pyproject.toml/tox.ini/setup.cfg
>   blocks pytest only with a pytest section (the `uv run pytest` false positive).
> - $TMPDIR, ${TMPDIR}, $CLAUDE_CODE_TMPDIR expand lexically where the shell would; quoted,
>   escaped, split or possibly rebound references stay unexpanded.
> - Read-only list: agent_guard.py --self-test/--print-policy, stack_sched.py plan/replay
>   (report in scratch), cc/c++/clang/clang++/gcc/g++ with -o into scratch, -fsyntax-only or
>   -E, pdfinfo, pdffonts, TeX engines with -no-shell-escape and -output-directory in scratch,
>   export NAME=&lt;scratch\|$(mktemp)&gt;. Compiler/TeX env knobs join the exec-var list.
> - Self-test: EPERM on the state-dir probe is a WARN (sandbox), other errors still FAIL.
> - settings.json: allow code.claude.com, repo1.maven.org, repo.maven.apache.org,
>   hackage.haskell.org, storage.julialang.net (strictAllowlist stays true).
> - SANDBOX_ENV: CABAL_DIR, JULIA_DEPOT_PATH=&lt;root&gt;/julia:.
> - Test docstrings: --python 3.13 in test_read_gate.py and test_guard_regressions.py.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +724/-20.*

### 2026-10-03 02:56 · `4b44ffd`

**Python 3.14 -&gt; 3.13 for the stack's venvs, locks, magg mlflow, docs and test commands**

> User decision: 3.13 everywhere. venv_sync targets 3.13 (a 3.12 or 3.14 venv is rebuilt).
> sci.txt and ml.txt relocked with --python-version 3.13 (same flags, same --exclude-newer):
> pins identical, headers only. doc-specialist's markitdown uvx moves 3.12 -&gt; 3.13:
> markitdown[all] 0.1.8 resolves wheels-only on 3.13 macOS arm64 (onnxruntime 1.23.2, magika 0.6.3).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 12 files, +17/-17.*

### 2026-10-03 02:56 · `5dc2a74`

**Soft limits: per-prompt soft limit 80M while an orchestrator runs (user-set, 2026-10-03)**

> SOFT_PROMPT_CTX_BY_TYPE = {"orchestrator": 80000000} in agent_guard.py: past the 33M base, soft_check
> reads the registry and uses the largest value of any running (not stopped) agent's type, copies
> counting as their base. The per-run SOFT_LIMITS (orchestrator: none) are unchanged. stack_sched.py
> mirrors it in the plan's prompt check (dispatcher or a node of a listed type). Self-test, guard and
> scheduler tests, CONFIG.md and README.md updated.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 6 files, +65/-11.*

### 2026-10-03 02:49 · `2b9eb70`

**Python 3.12 -&gt; 3.14: venv_sync rebuilds stale venvs, sci.txt relocked macOS arm64 only, ml.txt header, docs and test commands**

> Pins unchanged (sci drops colorama, tzdata: 88 -&gt; 86 packages; ml unchanged).
> doc-specialist keeps uvx --python 3.12: markitdown[all] has no 3.14 resolution (magika -&gt; onnxruntime&lt;=1.23, no cp314 wheel).
>
> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 11 files, +33/-37.*

### 2026-10-03 02:05 · `2d13551`

**Read gate: skip heredoc bodies, tree -I/-P values, directories non-recursive readers skip, tracked dirs under an ignore pattern; Grep's files_with_matches passes**

> Review findings (code-reviewer, reproducers on 3934aa9): a heredoc body was
> parsed as commands; `tree -I node_modules` took the value as a path; `grep -n x *`
> was gated on node_modules it never reads; a tracked src/build/ under a `build/`
> ignore pattern was gated; Grep's default files_with_matches was gated while
> `rg -l` passed. Each has a case in tests/test_read_gate.py (38).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +40/-10.* `CONFIG.md`, `dot-claude/hooks/read_gate.py`, `tests/test_read_gate.py`.

### 2026-10-03 01:59 · `3934aa9`

**Read gate: PreToolUse hook on Read\|Grep\|Glob\|Bash refuses the first read of build output, dependencies, large data, media and binaries**

> hooks/read_gate.py: the first Read, Grep, Glob or Bash reader (cat, grep, rg,
> find, sed, awk, jq, xxd, ...) of a gated target is refused with a cheaper
> alternative; the identical call repeated by the same agent passes. Bash is
> covered because Grep and Glob are absent by default on macOS/Linux. Ambiguous
> dirs (public dist build out target coverage vendor) are gated only when git
> ignores them, or public/ beside a Hugo config; only .lake/build of .lake.
> Read limit &lt;= 200, Grep count/head_limit, cut pipelines and .claude-work/
> pass. Per-category exemptions (build: verifier, frontend-engineer,
> browser-operator; data: data and ML agents; visual: designer,
> motion-designer, image-director, cg-artist, doc-specialist) and sizes are
> stack.env knobs; READ_GATE=0 turns it off. Retry state per session, bounded
> (READ_GATE_MAX_KEYS), under flock; every error fails open.
>
> Wiring: settings.json PreToolUse group, install.sh stage_script,
> STACK_SCRIPTS and STACK_HOOK_RE, smoke-test section; stack.env.example
> knobs; CONFIG.md section 5 "Read gate"; the rules' "Keep results small"
> bullet names it within the prompt budget.
>
> Tests: tests/test_read_gate.py (35), read_gate.py --self-test.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 8 files, +1157/-4.*

### 2026-10-03 01:28 · `910275c`

**Handoff: RESUME files, plans, baseline and usage reports (force-added from .claude-work)**

*Files changed: 10 files, +1925/-0.*

### 2026-10-03 01:01 · `5b392c8`

**Installer: build serial-mcp at the catalog's pin with cargo when present; doctor names the install command**

> The magg catalog's serial entry is the single source of the pin (cargo install
> serial-mcp@0.9.3 --locked, verified on crates.io: 0.9.3 is the newest, bin
> serial-mcp). Step 2 runs cargo install --locked --root ~/.cargo when cargo is on
> PATH or in ~/.cargo/bin, skips when ~/.cargo/.crates2.json records the pin (or
> the binary exists without a cargo record), prints one line and goes on without
> cargo, lists the build in --dry-run, and never runs under --no-deps or
> --mcp-plan. doctor.sh's WARN for a missing catalog binary now names the pinned
> cargo command. Smoke section 18 covers it with a fake cargo and stub tools.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +137/-13.*

### 2026-10-03 00:59 · `1dea215`

**S3: lint-clean model id in test_stack_usage**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 1 file, +1/-1.* `tests/test_stack_usage.py`.

### 2026-10-03 00:54 · `5f65e83`

**S1e: stack_sched reads resume_ctx, run_interval and fixer (advisor only)**

> - load_model keeps the three keys when well-formed.
> - A graph node may carry peak (the resumed agent's prior peak context): its ctx and T_w use
>   resume_ctx. Est reports turns/ctx/wall_run_hi (one run, 90%); cap checks keep the band hi.
> - replay: S_tok_measured with lo/hi from the model's fixer (fresh fixer = kappa_w x (static_cc +
>   reread)); the verdict uses it when present, the bracket otherwise. Session 4e2da3ce: barrier
>   4.00% [1.32-4.93], release 4.88% [2.69-5.67]: token side straddles 3%, ASK USER; wall STOP.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +190/-15.* `dot-claude/hooks/stack_sched.py`, `tests/test_stack_sched.py`.

### 2026-10-03 00:54 · `252e171`

**S1e: measured fresh-fixer re-read, resume ctx from the prior peak, conformal per-run intervals in fit()**

> fit() adds three top-level keys, each null below its gate and pure for a fixed generated stamp:
>
> - resume_ctx {alpha, gamma}: ctx of a resume = n \* (prior_peak + alpha + gamma \* n), Huber fit on
>   healthy resumes (alpha 783, gamma 776.2; 79 resumes, 23 agents). Adopted: ctx-given-turns error on
>   resumes falls 1.20 nats LOSO, 1.13 LOPO (bootstrap CIs exclude 0, above the baseline noise floor).
> - fixer {reread, lo, hi}: tokens a fresh builder reads before its first repo write (median 105276,
>   order-statistic 95% [86128, 176085], n 14); replaces the replay's 0/50% re-read bracket.
> - run_interval: split-conformal 90% factors of one run by &lt;tier&gt;:fresh\|resume (pooled fallback &lt; 10),
>   from leave-one-agent-out residuals; held-out coverage 0.89-0.97 on LOSO/LOPO/LOAO.
> load() derives first_ctx and ctx_at_first_write per segment. sched_model.json refitted on the pinned
> snapshot: only these keys and generated change.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +378/-4.* `dot-claude/hooks/sched_model.json`, `tests/derive_sched_model.py`, `tests/test_derive_sched_model.py`.

### 2026-10-03 00:51 · `6a8b022`

**Installer: web_caps.py is a stack hook (no duplicate PreToolUse group on re-run); doctor: missing catalog-only server is a WARN**

> STACK_HOOK_RE missed web_caps.py (77f5638), so each re-run kept the installed
> group as the user's and appended the shipped one: settings.json changed on every
> run (new backup, dry-run != real run, duplicate PreToolUse group). Existing
> duplicates are removed on the next run.
>
> doctor.sh: a command path only magg catalog entries use (serial: cargo install)
> is a WARN with an install hint; paths agents use stay FAIL.
>
> Tests: static check that STACK_HOOK_RE matches every shipped hook command;
> smoke section 2 checks hook commands appear once after a re-run; section 7
> checks the serial-mcp WARN.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +43/-5.* `dot-claude/bin/doctor.sh`, `install.sh`, `tests/install_smoke.sh`, `tests/test_install_state.py`.

### 2026-10-03 00:28 · `77f5638`

**Web caps: per-call limits for exa/jina/spider, Spider anti-bot defaults, spider-cloud-mcp 2.1.2**

> - hooks/web_caps.py (PreToolUse ^mcp\_\_(exa\|jina\|spider)\_\_): clamps results, characters,
>   crawl pages/depth/delay and fills unbounded server defaults; fills Spider request mode,
>   fingerprint, proxies (unblocker always), country, idle wait and browser stealth; refuses
>   spider cron/webhooks/run_in_background. Knobs in one table, overridable in stack.env.
> - researcher: spider-cloud-mcp 1.2.2 -&gt; 2.1.2 (browser sessions with CAPTCHA solving and
>   stealth escalation); one line on retrying challenge pages via unblocker, then a browser session.
> - stack.env.example documents every knob; installer stages and tracks the hook; tests.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 8 files, +529/-4.*

### 2026-10-03 00:12 · `2759a1f`

**S2f: scheduler review fixes (BlackCat dispatch checks, barrier next_ready dead nodes, cold-resume phases, real barrier simulation, midnight windows, next validates, band ctx fallback, kappa alias, fit(generated))**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 3 files, +214/-42.* `dot-claude/hooks/stack_sched.py`, `tests/derive_sched_model.py`, `tests/test_stack_sched.py`.

### 2026-10-03 00:07 · `cc65c26`

**Auto-compact window 900K on the models' 1M context (was 400K)**

> - dot-claude/settings.json: autoCompactWindow 400000 -&gt; 900000, the single source. Opus 5.5 and
>   Sonnet 5.5 run a native 1M window on the Anthropic API (no [1m] suffix, nothing to set).
> - tests/install_smoke.sh: compares autoCompactWindow with the shipped settings.json instead of a
>   literal.
> - doctor.sh, statusline.py docstring, install.sh notes, CONFIG.md row and changelog follow.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 6 files, +19/-14.*

### 2026-10-03 00:05 · `db93d91`

**Usage collector and scheduler model refresh (S3)**

> - hooks/stack_usage.py (stdlib, /usr/bin/python3): one detached collector per session
>   (SessionStart/SubagentStart `start`, SessionEnd `end` marker, flock single instance,
>   owner-pid and idle exits), incremental byte-offset parsing identical to
>   derive_thresholds' segments, numeric segment rows in usage/runs.csv (last row wins,
>   file lock, rotation into a compacted archive), runs view, status, propose (print only),
>   kill switch STACK_USAGE_COLLECT=0.
> - hooks/stack_sched_refresh.py (uv --offline, pandas/numpy): fit() on collected rows
>   combined with the shipped model, n-weighted, bands combined on the log scale, bounded
>   step x1.5 per refresh, provisional -&gt; supported, evidence kept; writes the active
>   sched_model.json atomically at the collector's exit only.
> - stack_sched.py: default model = STACK_SCHED_MODEL, else the active model, else shipped.
> - agent_guard.py: the three-day prune skips usage/.
> - settings.json hooks, install.sh (scripts, model, fit modules, merge regex, uv cache
>   warm-up), install_state validation, doctor line, CONFIG.md, hooks reference note.
> - tests/test_stack_usage.py: 18 tests.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 11 files, +1976/-8.*

### 2026-10-02 23:22 · `8872b3d`

**Scheduler advisor: clamp bands, read the rules-style cache_read kappa, alias in test**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +70/-7.* `dot-claude/hooks/stack_sched.py`, `tests/test_stack_sched.py`.

### 2026-10-02 23:21 · `0ca112f`

**sched_model: status and 90% bands per type, alias-keyed models, importable fit()**

> - types[t].status provisional\|supported (own &gt;= 5 healthy segments from &gt;= 3 agents)
> - band {level, method bootstrap\|pool-prior, turns, sec_per_call, ctx}: agent-cluster
>   bootstrap of the median (B 2000, seed 0) pooled like the point value, floored by the
>   normal-theory interval of a median; provisional bands never narrower than the pool's
> - kappa: models_measured keyed by alias (family -&gt; version), the Opus 5.5 cache-read
>   rule as family + version: no model ID in the repo file (lint)
> - fit(segments, frontmatter, soft_limits, seed=0) is pure, for the S3 refresh tool
> - tests/test_derive_sched_model.py: status switch, narrowing with n, pool floor,
>   determinism
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +1727/-40.* `dot-claude/hooks/sched_model.json`, `tests/derive_sched_model.py`, `tests/test_derive_sched_model.py`.

### 2026-10-02 23:16 · `de07b3d`

**Scheduler advisor: provisional bands used in the plan, three-way limit verdicts at hi, provisional share in replay**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +303/-17.* `dot-claude/hooks/stack_sched.py`, `tests/test_stack_sched.py`.

### 2026-10-02 23:12 · `c302961`

**Scheduler advisor: stack_sched.py (barrier DP, release search, replay), tests, graph fixture of session 4e2da3ce**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 3 files, +3779/-0.* `dot-claude/hooks/stack_sched.py`, `tests/fixtures/sched/graph-4e2da3ce.json`, `tests/test_stack_sched.py`.

### 2026-10-02 23:01 · `d917cf5`

**Scheduler cost model: tests/derive_sched_model.py writes dot-claude/hooks/sched_model.json**

> Per agent type: turns S/M/L, ctx(n) = a\*n + b\*n^2, static_cc, sec_per_call,
> cold-resume rule, model/ttl/maxTurns from frontmatter, soft_limit from
> agent_guard.py SOFT_LIMITS; partial pooling (n\*own + 5\*pool)/(n + 5) with
> the 5-segment/3-agent gate. Transcripts parsed with derive_thresholds.py's
> functions; data pinned to 2026-10-02T20:28Z (--until now to refresh).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +2389/-0.* `dot-claude/hooks/sched_model.json`, `tests/derive_sched_model.py`.

### 2026-10-02 22:50 · `dbb056f`

**Models review fixes: old-style IDs in the lint, doctor record reference, installer log lines**

> - lint: MODEL_ID_RE also catches old-style IDs (claude-&lt;n&gt;[-&lt;n&gt;]-&lt;family&gt;-...); test vectors in
>   tests/test_lint_skills.py (allowed file) and a check_model_ids case.
> - stack.env.example: the measured-models record is MEASURED_MODELS in bin/doctor.sh.
> - install.sh: the haiku replacement names stack.env's value; a [1m] pin no longer prints "kept"
>   before the stale-pin loop replaces it.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +28/-6.* `CONFIG.md`, `install.sh`, `stack.env.example`, `tests/lint_agents.py`, `tests/test_lint_skills.py`.

### 2026-10-02 22:49 · `61e0c4f`

**Guard: a human prompt whose UserPromptSubmit missed the budget lock starts its window on the main thread**

> budget_prompt writes prompt-pending.json before taking the lock and clears it
> in mark; once a human prompt is on record, budget_note_prompt resets the window
> only for the pending prompt_id (notification turns never get one). Review
> finding MEDIUM on d7e3b81: a lock timeout or a killed hook left prompt N in
> N-1's window (false hard refusals, no soft prompt warning).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +60/-11.* `dot-claude/hooks/agent_guard.py`, `tests/test_agent_guard.py`.

### 2026-10-02 22:43 · `b76adf9`

**Models: agents name opus/sonnet; IDs come from stack.env via ANTHROPIC_DEFAULT\_&lt;FAMILY&gt;\_MODEL**

> - stack.env.example: ANTHROPIC_DEFAULT_OPUS/SONNET/HAIKU_MODEL with today's IDs (source, date);
>   the haiku slot keeps the Sonnet ID (no Haiku in the stack).
> - install.sh: appends missing model variables to an existing stack.env set to the stack's IDs (a
>   key already there, even commented out, is left alone) and copies the non-empty ones into
>   settings.json's env; a settings.json value of the user's is kept and reported; a stale [1m] pin
>   is replaced by stack.env's ID. dot-claude/settings.json no longer ships the haiku pin.
> - Agents: model: opus (41) / sonnet (15). Lint accepts only the aliases and fails on a specific
>   model ID in any tracked file outside stack.env.example, OLD_DEFAULTS, doctor's MEASURED_MODELS
>   and legacy/.
> - doctor.sh: one line per alias (settings env, then process env), warns on drift from stack.env
>   and from MEASURED_MODELS (the models the soft limits and maxTurns were measured on);
>   derive_thresholds.py reports the models measured against that record.
> - Tests: smoke checks read the IDs from stack.env.example; new stack.env upgrade case; SDK tests
>   use the alias. Docs: README, CONFIG.md section 2, claude-code-extensions skill.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 68 files, +344/-111.*

### 2026-10-02 22:01 · `fb0b9e9`

**Guard self-test: keep the soft-limit case's expected warning off stderr (doctor prints it)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +1/-0.* `dot-claude/hooks/agent_guard.py`.

### 2026-10-02 21:47 · `35fae66`

**Docs: soft token limits (values, unit, knob, refresh, revisit), maxTurns from data; derivation script in tests/**

> tests/derive_thresholds.py is the phase-3 analysis (thresholds.py) made
> path-independent: --out (default .claude-work/agents-usage/), --agents,
> --session. CONFIG.md also corrects stale maxTurns rows (scout 11).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +728/-10.* `CONFIG.md`, `README.md`, `tests/derive_thresholds.py`.

### 2026-10-02 21:46 · `1895cd7`

**maxTurns from the 2026-10-02 transcripts; verifier hands build work back**

> claude-code-engineer 120 -&gt; 150, coder 150 -&gt; 170, main-coder 240 -&gt; 350:
> p90 x 1.5 of API calls per segment (all finished segments), never below the
> healthy maximum, rounded up to 10, within the lint caps. The verifier keeps
> 140 and routes build work to a builder or &lt;= ~90-call dispatches; the bodies
> prompt-budget gate goes to measured x 1.02 (0.867) for that line.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +10/-5.* `dot-claude/agents/claude-code-engineer.md`, `dot-claude/agents/coder.md`, `dot-claude/agents/main-coder.md`, `dot-claude/agents/verifier.md`, `tests/prompt_budget.py`.

### 2026-10-02 21:45 · `d7e3b81`

**Guard: soft token limits per agent segment and per human prompt; notification turns keep the prompt window**

> Soft limits (context tokens, thresholds derived 2026-10-02): a wrap-up warning in
> PreToolUse additionalContext, once per segment (spawn or resume) and once per
> human prompt, never a refusal. SOFT_LIMITS maps all 56 agent types (orchestrator
> and blackcat unlimited); STACK_SOFT_LIMIT_SCALE multiplies them (0 = off).
> Counted in the same budget.json pass as the hard budgets (per-file seg/seg_run).
>
> Fix: a main-thread call under a task notification's prompt_id restarted the
> hard prompt budget's window; once a UserPromptSubmit is on record it no longer
> does, and a notification delivered as a prompt event starts no window.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +451/-19.* `dot-claude/hooks/agent_guard.py`, `tests/test_agent_guard.py`.

### 2026-10-02 20:29 · `6622116`

**stack_sdk.py: review fixes — agent type only from a label, TaskUpdatedMessage status, env/extra_args merge**

> - agent_of(): the type comes from a '&lt;type&gt;: ' label prefix, or a bare type for a local_agent
>   task; otherwise None (STACK_AGENT_LABEL=name/off, shell tasks) instead of the task text.
> - TaskUpdatedMessage (no tool_use_id) is mapped to its task through task_id; patch.status is
>   recorded, so background tasks that end only this way (killed after TaskStop) get a status.
> - options(): env and extra_args from the caller are merged; any other field passed through
>   \*\*more overrides the defaults instead of raising TypeError.
> - Helper compacted to 120 lines; tests for all three.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +57/-29.* `dot-claude/bin/stack_sdk.py`, `tests/test_sdk_integration.py`.

### 2026-10-02 20:24 · `66c6d8c`

**docs: phase 3 counts**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +19/-17.* `README.md`.

### 2026-10-02 20:16 · `e696833`

**Q7: Agent SDK integration — stack_sdk.py helper, STACK_REPORT_FORMAT=json, no-TTY hook tests, SDK reference**

> - bin/stack_sdk.py (installed, loaded by nothing; PEP 723, claude-agent-sdk==0.2.163): options()
>   builds a plain ClaudeAgentOptions from the installed files (setting_sources user/project/local,
>   claude_code preset with exclude_dynamic_sections, --agent); run() returns the parsed report,
>   cost, model_usage, per-subagent Task\* usage and the ledger path; parse_report() reads the
>   clean-finish line, the STATUS block and the JSON form.
> - agent_guard.py: STACK_REPORT_FORMAT=json adds one report line at SessionStart (main thread,
>   every source) and SubagentStart (stack agents); unset = no output. SessionStart guard matcher
>   now startup\|resume\|clear\|compact\|fork.
> - tests/test_sdk_integration.py: hooks with no controlling terminal and SDK env/events, JSON
>   mode, parser, run() over a fake query, options with the pinned SDK, helper never loaded.
> - tests/sdk_smoke.py: real-API cold-start and token probe for the user (untested here).
> - references/agent-sdk.md + pointer, README section, CONFIG.md knob and changelog.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 11 files, +628/-14.*

### 2026-10-02 19:58 · `558fb10`

**Reviewers: restore the evidence gate; every review loads review-protocol**

> The five reviewer prompts (code-reviewer, plan-reviewer, security-auditor, verifier,
> proof-checker) get back the one-line evidence gate Q1 dropped (VERDICT pass when nothing
> is verifiably wrong; state an assumption once; never ask back without evidence), and load
> review-protocol on every review: the VERDICT format lives in that skill. Lint gains an
> "every &lt;x&gt;: load" forced-load pattern, whitelisted for exactly these five files. The
> bodies gate goes up 0.84 -&gt; 0.85 (measured 0.848 x ad22962) to hold the ~790 chars.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +26/-12.*

### 2026-10-02 19:39 · `d2bc994`

**Skill lookup B1x+C: hide 83 hub modules, Skills lines as optional lookups**

> - settings.json: 83 hub modules -&gt; skillOverrides "user-invocable-only" (out of the
>   listing; agents Read \_\_CLAUDE_DIR\_\_/skills/&lt;name&gt;/SKILL.md); 15 entry-grade modules
>   stay listed (KEEP_LISTED). skillListingBudgetFraction 0.0156 -&gt; 0.012 (stack 14,564 +
>   non-stack 14,169 = 28,733 of 36,000).
> - Agents: "## Skills, if needed" lookup lines (no forced or "first" loads), hidden modules
>   marked `name`\*, cross-domain pointers (biochem hpc-slurm, node sec-supply-chain,
>   llm-engineer and mcp-broker sec-llm-apps, devops sec-hardening/sec-secrets,
>   doc-specialist and writer a11y-docs-pdf, code-standards for coder/main-coder).
> - Hub tables mark hidden rows `name`\* with one path note per hub; rules and blackcat
>   say how hidden skills are read; rules: re-read a skill after compaction only if needed.
> - Tests: hidden set == table modules - KEEP_LISTED, each reachable from a marked row;
>   lint rejects unmarked hidden names, marked listed ones and forced-load wording; no
>   skills: preload; SubagentStart context &lt;= 200 chars and never SKILL.md text; listing
>   math counts hidden as 0; smoke checks hidden modules. Gates: skill_listing 0.478,
>   per_spawn_mean 0.691 (others unchanged).
> - README, CONFIG.md 5 and the claude-code-extensions reference describe read-by-path.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 77 files, +493/-207.*

### 2026-10-02 19:15 · `364cc6a`

**Phase 3 (Q4): re-set prompt-budget gates against ad22962; lint flags retired skill names**

> - tests/prompt_budget.py: DEFAULT_BASE ad22962; RATIO = measured ratio x 1.02, rounded down to 0.01
>   (bodies 0.84, agent_listing 0.97, blackcat_listing 0.96, skill_listing 0.76, rules 0.95,
>   per_spawn_mean 0.85); every absolute limit is lower than the phase-2 gate (reasons in the file)
> - tests/lint_agents.py: RETIRED_SKILLS (the 47 folded skill names from git history) and
>   check_stale_skill_refs: no agent, skill, reference or rules file names one, except
>   "(was the `x` skill)" provenance notes and references/&lt;name&gt;.md paths
> - tests/test_lint_skills.py: unit test for the matcher plus a test over shipped text;
>   tests/test_prompt_budget.py: base ad22962, within-limits case derived from RATIO["bodies"]
> - docs-sites: `write-docs-adr` → `technical-writing` `references/docs-adr.md`
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +89/-10.* `dot-claude/skills/docs-sites/SKILL.md`, `tests/lint_agents.py`, `tests/prompt_budget.py`, `tests/test_lint_skills.py`, `tests/test_prompt_budget.py`.

### 2026-10-02 19:07 · `ff4ed6e`

**agents (Q1): tighten all 56 bodies and descriptions; procedures to skills**

> - Bodies 93,839 -&gt; 77,964 chars (-16.9%), descriptions 7,325 -&gt; 6,520 (-11.0%),
>   agent listing 15,330 -&gt; 14,593; blackcat body 4,882, orchestrator 4,940.
> - Procedures a skill already holds deleted (language Verify blocks, code-standards,
>   ml-experiment, data-analysis, proof-craft, web-research, browser-automation...);
>   the rest moved to 7 references/from-&lt;agent&gt;.md files, pointed to in one line.
> - May spawn sentences rendered byte-identical to agent_guard POLICY rows.
> - Safety, consent, hardware/cluster/store gates kept in the bodies; robotics
>   safety verbatim; SUPREME_FLOW phrases kept.
> - maxTurns from transcripts (prompt_budget --turns, n&gt;=5, 1.5 x p90):
>   claude-code-engineer 190-&gt;120 (n=13, p90 79, max 88), scout 20-&gt;11
>   (n=21, p90 7, max 7), coder 190-&gt;150 (n=6, p90 98, max 149).
> - sec-threat-model pointer repointed to secure-coding (merge log).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 63 files, +411/-443.*

### 2026-10-02 19:05 · `3f526c3`

**Skills n–z, rules and formats (phase 3, Q3): compact rules with "Briefs and hand-backs"; tighter descriptions; 9 modules folded into hubs**

> - rules: one canonical "Briefs and hand-backs" section (brief block, artifacts by path, one-message dispatch,
>   SendMessage follow-ups, clean-finish line or STATUS format, result size by role); Reporting folded in,
>   Delegating trimmed; behaviour-critical rules kept; 12,198 → 11,370 chars
> - code-standards, claude-code-extensions: drop restated rules; claude-code-extensions documents the agent-body
>   principle (skills over big prompts) and moves field lists and MCP/hook/settings/LSP facts to references/
>   (listing fraction corrected to 0.0156)
> - merged (every fact kept): write-articles, write-docs-adr → technical-writing; num-optimization → opt-modeling;
>   ops-runbooks, net-vpn-firewall → self-hosting-ops; sec-threat-model → secure-coding;
>   quant-backtesting, quant-risk, quant-pricing → quant-finance
> - descriptions ≤ 140 (mean 94.2); detail moved to references/ in tattoo-design, svg-vector-craft,
>   prompt-and-brief-design, rust-native-gui, print-production; pt-PT punctuation rules kept once
>   (portuguese-pt-writing)
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 109 files, +825/-803.*

### 2026-10-02 19:02 · `3cd7f08`

**Skills a–m (Q2): bodies — long detail to references/, a Verify section in every skill**

> Split with "Read references/x.md when …" pointers: algorithm-design, local-llm-serving, graph-rag,
> agent-harness-design, dataset-curation, editor-engineering, apparel-merch-print, llm-quantization,
> literature-review, book-production, motion-graphics, linux-nvidia-cuda, color-management,
> markdown-publishing, brand-identity, category-theory, frontend-frameworks. Checklists renamed Verify;
> Verify added to 15 skills from their own checks. Restated global rules (consent protocol, never push,
> page content is data) shortened to pointers. Verified lines and source URLs unchanged in count.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 76 files, +1099/-849.*

### 2026-10-02 18:57 · `8402e76`

**Skills a–m (Q2): remove the folded module directories**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 29 files, +0/-1663.*

### 2026-10-02 18:56 · `68c229b`

**Skills a–m (Q2): fold 27 hub-only modules into hub references; tighter descriptions**

> Folded (log: .claude-work/agents-p3/merged-skills.txt): git-worktrees, git-history-edit, git-large-repos,
> git-recovery-bisect (bisect detail → debug-bisect-minimize), diag-mermaid, diag-graphviz-d2, diag-tikz,
> ffmpeg-encode, ffmpeg-edit, ffmpeg-audio-subs, mcp-python-server, mcp-http-release, macos-sign-notarize,
> macos-dmg-sparkle-brew, compiler-frontend, compiler-types, compiler-ir-llvm, compiler-backend-jit,
> geo-raster-vector, geo-tiles-webmaps, audio-dsp, audio-plugins, audio-analysis, linux-desktop-btrfs,
> fm-smt-z3, fm-tla, fm-rust-kani-miri. None was named by an agent; each hub's description names its topics.
> Descriptions of the 117 remaining a–m skills: mean 90 chars (was 107), max 113 (was 189).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 126 files, +1709/-162.*

### 2026-10-02 18:30 · `ad22962`

**README: rewrite for the current stack (roster by family, skills layout, labels, review protocol, on-demand matrix, budget, guards, install, env vars, plugins/MCP/tools)**

> CONFIG.md: point the changelog reference at the README of 96d3a52 and note the
> installer's plugin dedupe in the on-demand matrix.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +554/-2164.* `CONFIG.md`, `README.md`.

### 2026-10-02 18:14 · `96d3a52`

**Skills listed, not name-only: explanatory descriptions, listing budget 0.0156, on-demand matrix**

> - settings.json: drop the 216 name-only skillOverrides (6 bundled user-run commands stay hidden);
>   skillListingBudgetFraction 0.012 -&gt; 0.0156 (stack 31,028 + plugins 2,919 + bundled ~3,950 +
>   claude.ai ~7,300 = 45,197; budget 46,800). Cost-only knob.
> - lint: listing check counts what shares the budget (NON_STACK), name-only entry = name + 2
>   (Claude Code 2.1.287); module descriptions &lt;= 140; reachability replaces the name-only test
> - prompt_budget gates: skill_listing 1.77 x, per_spawn_mean 1.42 x (measured + 2%)
> - agents: pointers for merged skills (l10n-qa, test-mutation), hubs (technical-writing,
>   latex-typesetting, diagrams-as-code), skill-creator, and catalog MCP servers via mcp-broker
> - smoke: per-skill skillOverrides retraction on reinstall (13b)
> - CONFIG §5 / mcp_servers.md / README: on-demand and automatic matrix with idle costs
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 19 files, +157/-262.*

### 2026-10-02 18:00 · `ffaf597`

**Skills (S3): tighter descriptions; fold viz-interactive, test-mutation, sec-local-servers into their hubs**

> viz-interactive → data-visualization/references/interactive.md
> test-mutation → test-strategy/references/mutation.md
> sec-local-servers → sec-hardening § Local servers
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 85 files, +138/-151.*

### 2026-10-02 17:59 · `3622a52`

**Skills (S2): tighter descriptions; merge l10n-qa and geo-crs-gdal into sibling references**

> 73 descriptions tightened (mean 93 chars, max 113; 2,711 chars saved).
> l10n-qa → l10n-catalogs/references/qa-checks.md and geo-crs-gdal →
> geo-raster-vector/references/crs-gdal.md (content moved verbatim; hub tables in
> localization and geospatial updated); listing saves 3,004 chars in total.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 77 files, +159/-169.*

### 2026-10-02 17:58 · `4b6beac`

**skills(S1): tighter descriptions; fold write-reports, net-protocols, mcp-ts-server into hub references**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 78 files, +168/-173.*

### 2026-10-02 17:57 · `0d987f2`

**Skills (S3): explanatory descriptions (≤140 chars) for S3 and p–z skills that were name-only**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 82 files, +82/-82.*

### 2026-10-02 17:55 · `dfa4c7e`

**Skills (S2): explanatory descriptions (≤ 140 chars) for S2 skills and unowned g–o skills**

> 66 descriptions rewritten (frontmatter only): what each skill covers and when
> to load it, sibling named where it disambiguates; hubs kept unless over the cap
> (android-engineering, bio-chem-computing, quant-finance shortened).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 66 files, +66/-66.*

### 2026-10-02 17:55 · `d8054e2`

**skills(S1): explanatory descriptions**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 75 files, +75/-75.*

### 2026-10-02 17:48 · `24beb76`

**Review fixes: install magg/k8s-mcp.toml, k8s flags, npx prefetch, gate rationale**

> - install_state: magg/k8s-mcp.toml (and .tmp) in SCOPE_FILES so apply_plan installs it; unit + smoke checks
> - magg kubernetes entry passes --read-only --toolsets core (v0.0.67 cmd/root.go; flags override the config)
> - install.sh: prefetch mongodb-mcp-server and mobilebuildmcp through npm exec (deps, npx cache)
> - prompt_budget: rationale for the bodies 1.05x and rules 1.02x gates
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +29/-9.*

### 2026-10-02 17:28 · `5e3a54a`

**MCP and docs for phase 2: inline db/mobile servers, 10 magg catalog entries with ask rules, skillOverrides-aware install and doctor**

> - magg: mobile, android, godot, biomcp, pubchem, k8s (read-only toml), grafana, sec-edgar, serial, gis (disabled; ask rules)
> - install.sh: prefetch postgres-mcp, mongodb-mcp-server 3.0.5, mobilebuildmcp 2.7.1; retract stale skillOverrides entries
> - doctor.sh: skill listing honours skillOverrides
> - README, CONFIG 3-5, mcp_servers.md, stack.env.example, claude-code-extensions naming policy
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 10 files, +282/-33.*

### 2026-10-02 17:28 · `9f935c4`

**Agents phase 2: 17 new agents (10 domain/role, 7 language experts), registration and trimmed descriptions**

> - agent_guard: POLICY rows, LEAVES, explicit BlackCat row (db-engineer and localizer via heads), \_LANG_ROW
> - skills lines from skills-lines.md; descriptions &lt;=150 (language agents &lt;=120)
> - prompt_budget: agent/blackcat listing gates set to measured +2% (1.34x, 1.31x) with rationale
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 49 files, +660/-86.*

### 2026-10-02 17:16 · `26bcfb1`

**Skills wave B (S3): num/fm/gpu/perf/viz/a11y modules, 10 new skills, p–z single-topic splits**

> - numerical-methods references become num-floating-point, num-quadrature-autodiff, num-optimization
> - formal-methods, gpu-kernel-dev, cpu-performance, data-visualization, web-accessibility become hubs
>   with fm-\*, gpu-\*, perf-\*, viz-\*, a11y-\* modules
> - new: api-design, dist-systems, search-engines, codemods, dep-upgrades, debug-native,
>   debug-bisect-minimize, opt-modeling, linux-kernel-ebpf, oss-licensing
> - postgresql/mongodb: descriptions under 100 chars; db-engineer runs the servers inline
> - p–z single-topic skills over 150 lines move detail into references/
> - stale cross-references repointed (algorithm-design, cpp-engineering, diffusion-flow-models)
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 84 files, +2292/-1381.*

### 2026-10-02 17:16 · `73cb3dd`

**Skills wave B (S1): split self-hosting, linux, macOS, latex, diagrams, ffmpeg, writing, MCP hubs; new ops/cloud/net/docs-sites modules; a–f references**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 78 files, +3118/-2217.*

### 2026-10-02 17:11 · `f8a8802`

**Skills (S2): single-topic g–o skills over 150 lines move detail into references/**

> image-prompting, lean-formalization, literature-review, local-llm-serving,
> markdown-publishing, motion-graphics: whole sections moved verbatim into
> references/&lt;topic&gt;.md with a read-when pointer; every original line kept,
> descriptions unchanged, SKILL.md now 130–146 lines. haskell-engineering points
> property testing and fuzzing at test-property-based / test-fuzzing.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 21 files, +557/-506.*

### 2026-10-02 17:09 · `bd46ca6`

**Skills wave B (S2): quant-finance, audio-engineering, geospatial, compiler-engineering hubs and modules**

> 4 hubs and 14 modules with Verify sections and one reference file; versions
> checked 2026-10-02 with Verified lines; MCP mentions per mcp-vetting.md
> (gis-mcp and sec-edgar in magg, Alpha Vantage documented only, no audio server).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 19 files, +759/-0.*

### 2026-10-02 17:00 · `65a7fba`

**Skills wave A (S2): embedded, Apple, Android/cross-platform, games, HPC, bio/chem, localization hubs and modules**

> 7 hubs (embedded-firmware, swift-engineering, android-engineering, game-graphics,
> hpc-computing, bio-chem-computing, localization) and 31 modules with Verify
> sections, 9 reference files; versions checked 2026-10-02 with Verified lines.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 47 files, +1855/-0.*

### 2026-10-02 16:54 · `0bab5d4`

**Skills wave A (S3): secure-coding, test-strategy, db-design, a11y-mobile, num-\* modules**

> - secure-coding becomes a hub; its sections move to 11 sec-\* modules
>   (sec-hardening, sec-detection, sec-incident-response are new)
> - test-strategy hub (new) with test-property-based and test-fuzzing (moved
>   from formal-methods), test-mutation, test-e2e-playwright, test-contract-snapshot
> - db-design hub (new) with db-migrations, mysql, sqlite, redis; postgresql and
>   mongodb move operations detail into references/operations.md
> - web-accessibility gets a Modules table with a11y-mobile
> - numerical-methods: num-linear-algebra and num-ode-sde modules; remaining
>   bulk in references/ (hub &lt;= 80 lines)
> - version claims carry Verified 2026-10-02 &lt;URL&gt; or are marked unverified
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 37 files, +1179/-416.*

### 2026-10-02 16:53 · `f0340eb`

**Skills wave A (S1): split rust, typescript, python, git hubs into modules; new go-engineering**

> Hubs keep baseline rules and a Modules table; detail moves to modules
> (&lt;=150 lines, Verify section) and references/. Version baselines re-verified
> 2026-10-02 (Rust 1.99.0, Go 1.27.1, npm/PyPI/crates.io registries, Git 2.56);
> unverifiable claims are marked unverified.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 33 files, +1118/-661.*

### 2026-10-02 16:47 · `1c2a79e`

**Budget tooling for phase 2: skillOverrides-aware listing, gates against 1a38c77, skill module tests**

> - prompt_budget.py: skill listing reads skillOverrides (name-only = name+4,
>   user-invocable-only/off = 0); blackcat_listing from blackcat's Agent(...)
>   allowlist; --check gates per design E (new-agent caps, ratios vs base,
>   mean per spawn); --check defaults to --base 1a38c77
> - lint_agents.py: shared skill_listing_entry; validates skillOverrides values
> - test_skill_modules.py: line caps (SKILL 500, hub 80, module 150), module
>   descriptions &lt;= 100, references exist, override keys shipped or external,
>   name-only skills named by a skill or an agent body
> - settings.json skillOverrides: every skill outside the 38 kept listings is
>   name-only, including the planned wave A/B modules
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +539/-37.* `dot-claude/settings.json`, `tests/lint_agents.py`, `tests/prompt_budget.py`, `tests/test_prompt_budget.py`, `tests/test_skill_modules.py`.

### 2026-10-02 15:00 · `1a38c77`

**orchestrator: step 7 states the pass rule (nothing verifiably wrong → pass, no follow-up)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +1/-1.* `dot-claude/agents/orchestrator.md`.

### 2026-10-02 14:54 · `345854f`

**Guard: label review fixes (full ledger task, caller names kept, bare label)**

> - PostToolUse only fills the ledger's task and name, so a long description's
>   row keeps PreToolUse's text instead of the 72-char label.
> - Only names this hook gave out (marker under labels/) are hidden in the
>   ledger; a caller's own `coder-2` stays.
> - ledger_task treats a bare "&lt;type&gt;" (the label of a call without a
>   description) as labelled: no "coder: coder".
> - Tests for all three; the prefixed/unprefixed row test no longer compares
>   clocks across two sessions.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +60/-15.* `dot-claude/hooks/agent_guard.py`, `tests/test_agent_label.py`.

### 2026-10-02 14:50 · `c7cc31d`

**Agents: proof-checker (Lean inline, read-only) and vfx-td (Houdini FX); registration**

> proof-checker referees proofs and derivations: counterexample search, Lean 4 via an inline
> lean-lsp-mcp 0.30.0 (only LEAN_PROJECT_PATH from stack.env), read-only Bash (READONLY_TYPES),
> a leaf. vfx-td takes Houdini FX from cg-artist (hython, husk, Monitor/TaskStop, computer use).
> Policy rows, blackcat/orchestrator routes, May-spawn lines, the 39-agent pin, install prefetch,
> houdini-fx's MCP line (kleer001/houdini-mcp exists: optional, not enabled), README, CONFIG
> (maxTurns synced, STACK_AGENT_LABEL/STACK_AGENT_STARTED), mcp_servers.md, stack.env.example.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 19 files, +158/-73.*

### 2026-10-02 14:37 · `4240f55`

**Agents: shorter descriptions, room in the listing for the wave-2 agents**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 12 files, +12/-12.*

### 2026-10-02 14:32 · `78afe26`

**Agents: tighter prompts, shorter descriptions, maxTurns from measured turns; prompt_budget.py**

> - 31 agent files (all but blackcat, orchestrator and the four reviewers): routing prose,
>   restated rules (memory, consent, read-only, hook caps) and method steps their skills already
>   carry are cut; builder self-check lines per the rules' Self-check and review; researcher quotes
>   primary sources in the same pass. Robotics safety text verbatim; May spawn rows unchanged.
> - Descriptions &lt;= ~170 chars (agent listing -32.7% vs 75dfdfc); colors by family.
> - maxTurns = max(target, 1.5 x measured p90) within the lint caps; cg-artist gets Monitor, TaskStop.
> - tests/prompt_budget.py (PEP 723, stdlib): per-agent and per-spawn static prompt cost, base
>   comparison, --check thresholds, --turns from subagent transcripts; tests/test_prompt_budget.py.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 33 files, +651/-327.*

### 2026-10-02 14:26 · `5a4a01a`

**Guard: subagent labels, start time, lake env read-only check**

> - STACK_AGENT_LABEL=description\|name\|off (default description): after every
>   gate, an Agent call's description becomes "&lt;subagent_type&gt;: &lt;task&gt;" (or an
>   unnamed child gets the name "&lt;type&gt;-&lt;n&gt;") via a silent updatedInput without
>   permissionDecision; a caller's own label or name is kept; the delegation
>   ledger strips the label so rows are unchanged.
> - SubagentStart: stack agents get "Started YYYY-MM-DD HH:MM (local)." as
>   additionalContext (STACK_AGENT_STARTED=0 turns it off).
> - Read-only allowlist: `lake env <cmd>` now checks &lt;cmd&gt; (before, `lake env
>   rm -rf src` passed for READONLY_TYPES).
> - Tests: test_agent_label.py; ledger, guard and harness helpers accept the
>   label-only output; the MCP cap test reads maxTurns from the agent files.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +416/-26.* `dot-claude/hooks/agent_guard.py`, `tests/guard_harness.py`, `tests/test_agent_guard.py`, `tests/test_agent_label.py`, `tests/test_delegation_ledger.py`.

### 2026-10-02 14:22 · `18b8da1`

**Review protocol: evidence-gated round trips, clean-finish reports, leaner dispatch**

> Rules: Self-check and review section (builder self-check, review triggers,
> evidence-gated round trips), clean-finish report (input · time · agent, then
> the result), shorter foreground and neural-memory bullets; size +4.9%.
> review-protocol: one pass, patch-ready findings with proofs, no re-review
> without new evidence. code-standards: verify/report point at the rules.
> blackcat: Relay for clean finishes and evidence-only send-backs, routing
> collapsed onto agent descriptions (body 8,306 -&gt; 5,163 chars).
> orchestrator: verify once by fired trigger, plan-review fixes applied in
> place, maxTurns 200. Reviewers: new bodies, descriptions &lt;= 200 chars,
> maxTurns code-reviewer 80, verifier 140, plan-reviewer 60, security-auditor 100.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 9 files, +148/-127.*

### 2026-10-01 19:28 · `75dfdfc`

**Guard: delegation ledger BlackCat can read (who delegated what to whom)**

> agent_guard.py records every allowed Agent call in &lt;state&gt;/&lt;session&gt;/spawns/&lt;tool_use_id&gt;.json
> (caller, caller type, subagent_type, task = the call's description, name, agent id, status) and
> re-renders &lt;state&gt;/&lt;session&gt;/delegations.md, a tree rooted at the main thread's dispatches with
> each call's state (launching, running, finished, failed, stopped). Foreground children are linked
> at SubagentStart through meta.json's toolUseId. BlackCat gets the ledger path as PostToolUse
> additionalContext after dispatching an agent that can delegate, and Reads it in one step;
> `agent_guard.py delegations [session] [--json]` prints it. Bookkeeping only: failures warn.
>
> blackcat.md: answer "who is working on what" from the ledger, no dispatch.
> orchestrator.md: Agent descriptions carry the plan.md task id plus 3-5 words.
> Self-test and tests/test_delegation_ledger.py cover the tree, states, hint, linking and CLI.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 6 files, +443/-12.*

### 2026-10-01 14:28 · `b199ab1`

**Guard: no generic agents (spawn allowlist, workflow gate, explore agent)**

> Agent calls without a subagent_type, or with general-purpose, claude, fork,
> a built-in or a host-defined type ("SubAgent"), could reach a generic agent:
> a caller with no POLICY row (typeless main thread, a host's agent, a generic
> subagent) was unrestricted, Workflow agent() stages without agentType ran as
> workflow-subagent, and forked skills without `agent:` ran as general-purpose.
>
> - agent_guard.py: spawn allowlist of stack types for every caller (spawn_row,
>   spawn_type_violation); Task/SubAgent/RunWorkflow aliases canonicalised; a
>   running generic subagent is refused every tool (generic_agent_reason, budget
>   mode); Workflow gate (every agent() names a stack agentType, no model, no
>   effort above the agent's; scriptPath/script/name all checked; bundled and
>   nested workflows refused); self-test cases for all of it and the wiring.
> - settings.json: deny Agent(general-purpose\|claude\|fork); built-in Explore/Plan
>   off (CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS), every built-in off in -p/SDK
>   hosts (CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS); matchers cover the aliases.
> - agents/explore.md: replaces the built-in Explore (Sonnet 5.5, low, 40 turns,
>   no Bash, omitClaudeMd); a leaf BlackCat may dispatch.
> - Prompts: BlackCat routes codebase questions to explore and CLI conversions to
>   coder, types every workflow stage, sends deep research to researcher;
>   ninja-/supreme-coder type their workflow stages; rules name the subagent_type rule.
> - doctor.sh accepts the \|-list matcher; tests and docs updated.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 14 files, +816/-56.*

## 2026-09

### 2026-09-29 17:37 · `7411775`

**Docs: round-4 installer prompt and session-env warning**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +47/-23.* `CONFIG.md`, `README.md`.

### 2026-09-29 17:32 · `cfa9ee7`

**session-env: a failure reaches the user; status line and doctor.sh show it (R4-2)**

> The hook warned on stderr and exited 0 (debug log only), so a session without the sandbox caches
> and the git credential-helper reset went unnoticed. It now checks that its marker is in
> CLAUDE_ENV_FILE after writing, records running/ok/failed in the session's state dir, and on
> failure exits 2 (Claude Code shows a SessionStart hook's exit-2 stderr as a hook error notice;
> the session goes on). statusline.py puts "! Bash sandbox env missing: doctor.sh" first when that
> session's record says failed or is stuck in running; doctor.sh probes the hook in a temp dir and
> reports failures in the last sessions.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +175/-20.* `dot-claude/bin/doctor.sh`, `dot-claude/bin/statusline.py`, `dot-claude/hooks/agent_guard.py`, `tests/install_smoke.sh`, `tests/test_guard_round3.py`.

### 2026-09-29 17:32 · `df21992`

**Installer: the supply question never proceeds unasked (R4-1)**

> With stdin from /dev/null or stderr piped (`2>&1 | tee`), a non-empty supply diff was listed and
> the install went on. Now the question goes to stdin/stderr when both are a terminal, else to the
> controlling terminal (/dev/tty); with no terminal at all the run stops with exit 1 and a message
> to rerun with --yes. --help describes --yes that way. The smoke runs without a controlling
> terminal (it re-execs itself in a new session), covers no terminal (refused; --yes installs) and a
> controlling terminal with stdin /dev/null and stderr piped ('n' changes nothing), and passes
> --yes where it installs a config dir from another repo.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +101/-11.* `install.sh`, `tests/install_smoke.sh`, `tests/test_guard_round3.py`.

### 2026-09-29 17:19 · `f8124cc`

**Docs: security rounds 2-3, sandbox caveats, supreme-coder plan flow**

> Co-Authored-By: Claude Sonnet 5.5

*Files changed: 2 files, +448/-79.* `CONFIG.md`, `README.md`.

### 2026-09-29 17:06 · `e0b5544`

**Settings, doctor: git credential-store's ~/.config/git/credentials (review)**

> The second default file of git's credential-store joins ~/.git-credentials in the sandbox
> denyRead and the Read denies; doctor.sh reports a github.com line in either file (presence only).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +12/-7.* `dot-claude/bin/doctor.sh`, `dot-claude/settings.json`, `tests/test_protected_paths.py`.

### 2026-09-29 17:06 · `9aeec09`

**Installer: review fixes: ask before step 2; a first install retracts nothing of yours**

> - The supply-chain listing and the terminal question move before step 2, which syncs the venvs
>   from requirements/ (itself supply-chain input): "n" now really leaves everything unchanged.
>   The question points to --dry-run for the whole plan. The smoke asserts no step 2 after "n".
> - The fallback list of retired allowWrite dirs (for manifests older than settings_sandbox)
>   applies only when $C has a manifest from an earlier install; a first install over your own
>   settings.json keeps your ~/.cache and the like (smoke case).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +72/-61.* `install.sh`, `tests/install_smoke.sh`.

### 2026-09-29 17:04 · `80bc1dd`

**Guard: review fixes for web relay and temp-dir projects**

> - A SendMessage to a name whose agent id isn't known yet (a foreground child still running) is
>   linked through the Agent call that spawned it (names/&lt;name&gt;.json keeps its tool_use_id; the
>   agent is found by the registry or Claude Code's meta.json), both ways.
> - A spawn whose web-spawned mark can't be recorded is refused (rolled back), not let through
>   unmarked.
> - Read-only agents: the project is CLAUDE_PROJECT_DIR when set; a cwd that moved into a temp
>   subdir no longer counts as a project.
> - session-env warns when MAVEN_OPTS can't carry the sandbox path.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +162/-39.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round3.py`.

### 2026-09-29 16:40 · `1e1cd82`

**doctor.sh: report GitHub credentials agents could use, by presence only (R3-N1-P2)**

> New section: GH_TOKEN/GITHUB_TOKEN/GH_ENTERPRISE_TOKEN/GITHUB_ENTERPRISE_TOKEN in the environment,
> a plain-text oauth_token in gh's hosts.yml, a github.com line in ~/.git-credentials, and on macOS
> the gh:github.com and github.com keychain items (attribute searches only: no -g/-w, no secret
> read, no prompt). Each is a WARN naming who can use it and the least-privilege step; no value
> is ever printed (smoke-tested with fake values).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +48/-0.* `dot-claude/bin/doctor.sh`, `tests/install_smoke.sh`.

### 2026-09-29 16:40 · `47acb92`

**Installer: --dry-run refuses what the real run refuses (R3-DRYRUN); smoke case for file links**

> A --dry-run with a symlinked scope dir and no --write-through-links showed the plan and exited 0,
> while the real run stops with exit 1. It still shows the whole plan, then prints the real run's
> refusal and exits 1; with --write-through-links it exits 0. The smoke also covers a file link
> inside a symlinked agents/ (R3-WTL-INNER, fixed in 275eead): it stays a link, its target unwritten.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +27/-6.* `install.sh`, `tests/install_smoke.sh`.

### 2026-09-29 16:30 · `7e8386b`

**Settings: the guard state dir renders from XDG_STATE_HOME (R3-STATE)**

> denyWrite and the Edit deny named a fixed ~/.local/state/claude-agent-stack while the guard
> keeps its state under $XDG_STATE_HOME. New placeholder \_\_STACK_STATE\_\_, rendered like
> \_\_STACK_BACKUPS\_\_ and \_\_STACK_CACHE\_\_ (install and --print-managed-settings).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +24/-11.* `dot-claude/settings.json`, `install.sh`, `tests/install_smoke.sh`, `tests/test_agent_guard.py`, `tests/test_protected_paths.py`.

### 2026-09-29 16:30 · `b7a075b`

**Guard: a project under a temp dir is the project for read-only agents (R3-INFO)**

> Every path under /tmp, /private/tmp, /var/folders or $TMPDIR counted as scratch, so read-only
> agents could write a project checked out there, and its own tests were content-checked as
> scratch code and refused (118 tests failed from a checkout under /private/tmp). The session's
> project dirs now win over the temp roots; any .claude-work stays scratch, and a cwd that is a
> temp dir itself keeps all of it scratch.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +52/-2.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round3.py`.

### 2026-09-29 16:30 · `275eead`

**Installer: keep file links in a symlinked dir; restore keeps what a skipped link covers (R3-WTL-INNER, R3-RESTORE-LINK)**

> --write-through-links replaced a file link inside a symlinked scope dir (agents/coder.md -&gt;
> elsewhere) with a regular file in the dotfiles checkout. Such links now stay, like dir links,
> with a plan note. --restore without --force skipped a saved link that leaves the config dir but
> still removed the stack's entry there (a skill went missing); what is at that path now stays,
> the files the install added below it included.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +87/-12.* `lib/install_state.py`, `tests/test_install_state.py`.

### 2026-09-29 16:30 · `693296f`

**Installer: diff the whole shipped tree since the last install; ask on a terminal (R3-SUPPLY)**

> The supply-chain diff covered only the guard, settings.json, install.sh and lib; it now covers
> all of dot-claude (agents and their MCP servers and hooks, skills, rules, bin, mcp, magg's
> catalog, the LSP marketplace), install.sh, lib, requirements and stack.env.example, with
> listings capped at 40 lines. When that diff or uncommitted edits are non-empty and stdin and
> stderr are a terminal, the run asks before applying; anything but y/yes exits 1 with nothing
> changed. --yes (-y) skips the question.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +97/-15.* `install.sh`, `tests/install_smoke.sh`, `tests/test_guard_round3.py`.

### 2026-09-29 16:08 · `c9ef24b`

**Sandbox caches and git credential reset are Bash-only (R3-CACHES, R3-GITENV)**

> settings.json env reached every process Claude Code starts, so MCP
> servers, hooks and language servers (unsandboxed) loaded code from
> caches sandboxed commands could write, and GIT_CONFIG\_\* overrode the
> user's own and Claude Code's git (private marketplace updates).
>
> - New SessionStart hook (every source): agent_guard.py session-env
>   appends exports to $CLAUDE_ENV_FILE once: XDG_CACHE_HOME, uv, pip,
>   npm, node-gyp, pnpm, yarn, bun, deno, pre-commit, HF_HOME,
>   MPLCONFIGDIR, CARGO_HOME, GOMODCACHE, GOCACHE, GRADLE_USER_HOME,
>   COURSIER_CACHE, ccache, sccache under ~/.cache/claude-sandbox,
>   MAVEN_OPTS -Dmaven.repo.local appended, and 'credential.helper='
>   appended to GIT_CONFIG_PARAMETERS. Claude Code 2.1.284 prepends
>   that script to every Bash command of the session (subagents too:
>   read in the binary; not documented).
> - settings.json: those env keys removed; allowWrite is only
>   ~/.cache/claude-sandbox (no ~/.cache, ~/Library/Caches, cargo, Go,
>   Gradle, Maven, bun, matplotlib); ~/Library/Caches/Coursier denyWrite.
> - install.sh: the old env values and allowWrite entries are retracted
>   on upgrade (manifest; a static list for manifests older than
>   settings_sandbox), each retraction printed. The user MCP server and
>   hook cache warnings are gone (their premise no longer holds); the
>   stack's own servers keep their private cache.
> - doctor.sh: checks the session-env hook and flags cache/git keys in
>   settings env or ~/.cache in allowWrite.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 7 files, +282/-244.*

### 2026-09-29 15:55 · `b93b557`

**Guard: web taint follows reports, messages and spawn prompts (R3-T3-RELAY)**

> An agent web content reached through another agent could still write
> the shared memory. on_memory_write now walks, from the caller, its
> registry descendants (their reports) and its SendMessage peers (either
> way), and refuses when any of them is a web-reading type or tainted, or
> was spawned by an agent that was tainted at the time (marked per
> tool_use_id; matched through the registry or meta.json). The main
> thread is not a node. A graph past 4096 nodes fails closed. Files an
> agent reads are not followed (residual).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +255/-1.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round3.py`.

### 2026-09-29 15:48 · `7292272`

**Guard: supreme-coder only after a finished ninja-coder (SUPREME_AFTER_NINJA); supreme-coder flow tests**

> A supreme-coder spawn now also needs a ninja-coder of the same session that
> finished: SubagentStop, or its Agent call reported a terminal status
> (stored in the registry; a resume clears it). Checked after the
> spawner deny and before any side effect, so a refusal claims no slot.
> SUPREME_AFTER_NINJA=0 turns it off; the spawner and once-per-session
> checks are unchanged.
>
> Tests: every non-orchestrator type (copies, built-ins, main thread) is
> refused in every spelling norm() accepts; the orchestrator's first
> spawn is allowed and a second refused; the ninja-first order,
> including running, resumed and unrecognised-response ninjas; the
> markers live in the protected state dir; the plan-flow phrases in the
> planner, plan-reviewer, blackcat, orchestrator and supreme-coder prompts;
> the rules Limits line.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +220/-5.* `dot-claude/hooks/agent_guard.py`, `dot-claude/rules/claude-agent-stack.md`, `tests/guard_harness.py`, `tests/test_agent_guard.py`.

### 2026-09-29 15:28 · `ea80f87`

**Prompts: supreme-coder as a plan step, after ninja-coder only**

> planner may add one SUPREME-CODER STEP as the conditional fallback of a
> preceding ninja-coder step ("requires orchestrator; once per session; only
> after ninja-coder failed") with a dossier template; plan-reviewer blocks a
> missing ninja-coder step, an unconditional step or more than one; blackcat
> routes such plans to the orchestrator by path; the orchestrator runs
> ninja-coder first, spawns supreme-coder only on its failure or partial, drops
> the step if ninja-coder succeeds and never works around the cap; supreme-coder
> accepts the completed plan-step dossier. Hook policy unchanged.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +5/-2.* `dot-claude/agents/blackcat.md`, `dot-claude/agents/supreme-coder.md`, `dot-claude/agents/orchestrator.md`, `dot-claude/agents/plan-reviewer.md`, `dot-claude/agents/planner.md`.

### 2026-09-29 15:25 · `17fdd46`

**Settings: magg docspace\_\* asks; every catalog prefix has exactly one allow or ask rule**

> DocSpace writes to external cloud rooms and files. New invariant tests: each magg catalog prefix
> has exactly one of an allow or an ask rule (none runs unprompted without a decision), and the
> allowed mongodb/postgres entries keep their read-only flags (--readOnly, --access-mode=restricted).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +32/-3.* `dot-claude/settings.json`, `tests/install_smoke.sh`, `tests/test_no_duplicates.py`, `tests/test_protected_paths.py`.

### 2026-09-29 15:21 · `bb77d58`

**Settings: magg ros\_\* and qiskit\_\* tools ask at every call**

> Under bypassPermissions only explicit ask rules prompt, so once enabled the ROS server (publish,
> service calls, parameters on a robot) and Qiskit Runtime (hardware jobs that spend quota) ran
> unprompted. Tests: every mcp\_\_magg\_\_&lt;prefix&gt;\_\* rule names a catalog prefix, duckdb/jupyter/ros/
> qiskit ask, and allow and ask are disjoint.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +30/-3.* `dot-claude/settings.json`, `tests/install_smoke.sh`, `tests/test_no_duplicates.py`, `tests/test_protected_paths.py`.

### 2026-09-29 15:19 · `13c5e17`

**mcp-broker: approval wording matches settings.json ask rules**

> Enabling a server, adding one, loading a kit, proxy, and the mounted
> duckdb\_\* and jupyter\_\* tools ask the user; duckdb is read-only. ros and
> qiskit-runtime have no ask rule, so the prompt requires ASK USER consent
> before any publishing call or job submission (robotics-engineer no longer
> claims the ros server asks at every call).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +3/-3.* `dot-claude/agents/mcp-broker.md`, `dot-claude/agents/robotics-engineer.md`.

### 2026-09-29 15:13 · `3d2527c`

**Guard: a brace expansion past the cap never fails open**

> Numeric ranges collapse to one digit glob before expanding (their words hold only digits and '-'),
> letter ranges and lists expand in full, and a word that still overflows is denied whatever it
> names: ~/.cla{x{1..1100},u}de/hooks and ~/.c{x{1..1100},laude}/hooks are denied, touch
> out/f{1..5000}.txt stays allowed.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +65/-18.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`.

### 2026-09-29 15:13 · `6bb2ce5`

**Installer: one plan note per link inside a symlinked scope dir**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +6/-3.* `lib/install_state.py`, `tests/install_smoke.sh`, `tests/test_install_state.py`.

### 2026-09-29 13:26 · `bbe6027`

**CONFIG: residual risks after the round-3 guard fixes; validation numbers**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +4/-4.* `CONFIG.md`.

### 2026-09-29 13:20 · `2a42e08`

**Guard: install rule denies scratch installs behind same-command links and installer fetched by any program**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +66/-10.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round2.py`.

### 2026-09-29 13:20 · `66629f5`

**T2: reviewers can't run scratch code through inline python; JS runner after a data write is allowed**

> Inline-code pattern gains runpy, sys.path, site.addsitedir, SourceFileLoader, load_module,
> spec_from_file_location, exec_module, import_module; python -c / - is refused from a scratch cwd.
> A JS runner is refused after a scratch write only when the path looks like code or test config.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +125/-4.* `dot-claude/hooks/agent_guard.py`, `tests/test_readonly_agents.py`.

### 2026-09-29 13:22 · `9654f9e`

**Guard: protect-scan round 3 (every command substitution suspect but an allowlist, read/mapfile/printf -v/loop variables, fail-closed brace cap, tightened ROOT_TEXT_RE)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +216/-26.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`.

### 2026-09-29 13:22 · `8b39815`

**Installer: a link inside a symlinked scope dir is never written through**

> With skills -&gt; ~/dot/skills and ~/dot/skills/&lt;name&gt; -&gt; &lt;name&gt;-local, the plan kept the inner link
> but added the stack's files below its name, so --write-through-links overwrote the link target's
> files unsaved and --restore then removed them. The plan now skips those files with a note, and
> unsafe_paths accepts a write through a symlinked top-level dir only straight below its target.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +64/-2.* `CONFIG.md`, `lib/install_state.py`, `tests/install_smoke.sh`, `tests/test_install_state.py`.

### 2026-09-29 13:01 · `a0d9b4c`

**CONFIG: round-2 review fixes (write-through-links, per-skill links, manifest dirs, user MCP cache warnings, taint allowlist, install rule, scan gaps); validation numbers**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +16/-14.* `CONFIG.md`.

### 2026-09-29 12:56 · `8a60576`

**Guard: T3 taints every mcp\_\_ tool but a non-web allowlist; install.sh rule follows cd, install_state.py, data-copy-then-shell, symlinked scratch dirs**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +296/-18.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round2.py`.

### 2026-09-29 12:47 · `00ec1d2`

**T2: a reviewer can no longer write scratch code and run it in the same Bash command**

> An earlier segment that writes into scratch (redirect, heredoc, cp/mv/install/tee/ln/dd/touch, sed -i, tar x, unzip -d, curl/wget output) now denies a later segment that runs or collects scratch code, since the hook reads files before they exist. A missing scratch file or dir operand of a test runner counts as unreadable and is denied. Syntax-only checks, project tests and separate-call flows stay allowed.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +141/-7.* `dot-claude/hooks/agent_guard.py`, `tests/test_readonly_agents.py`.

### 2026-09-29 12:49 · `3047725`

**Guard: protect scan no longer denies $VAR/bin-style project paths; brace expansion, CDPATH, curl/wget/sort/patch/sponge/awk outputs, more git subcommands**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +531/-29.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`.

### 2026-09-29 12:53 · `2c5284f`

**Smoke: final checks of the MCP cache warnings (completes the wip commit 393b780)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +4/-3.* `tests/install_smoke.sh`.

### 2026-09-29 12:50 · `393b780`

**wip: flag user MCP servers and hooks on the sandbox-writable cache**

*Files changed: 3 files, +213/-0.* `dot-claude/bin/doctor.sh`, `install.sh`, `tests/install_smoke.sh`.

### 2026-09-29 12:43 · `01a0c16`

**Installer: --write-through-links is the only flag that writes through symlinked scope dirs**

> --force keeps --no-prune (replace edited stack files) and --restore (outside links)
> and no longer implies write-through, so a dotfiles user can keep their edits.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +33/-18.* `install.sh`, `tests/install_smoke.sh`.

### 2026-09-29 12:37 · `4d3c6a8`

**Installer: the MCP prefetch warms the servers' own cache ($STACK_CACHE)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +25/-8.* `install.sh`, `tests/test_install_state.py`.

### 2026-09-29 12:37 · `e262e16`

**Installer: per-skill symlinks install again; whole scope dirs in the manifest refused**

> - unsafe_paths resolves a path below a symlink the plan removes lexically (the link is gone
>   before anything is placed), so skills/&lt;name&gt; -&gt; ~/dotfiles/&lt;name&gt; is replaced by the stack's
>   skill again instead of blocking every install; a kept link above still refuses
> - the CLI plan step runs the same check, so --dry-run reports what the real run refuses
> - manifest keys naming a whole scope dir (bin, mcp, ...) stop the install; drop() refuses them;
>   a stale-script key that is a directory is left alone; the stage must hold the stack's scripts
> - smoke: the real ~/.claude.json check compares its MCP entries only (live sessions rewrite the
>   rest of the file during a run)
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +138/-9.* `install.sh`, `lib/install_state.py`, `tests/install_smoke.sh`, `tests/test_install_state.py`.

### 2026-09-29 12:29 · `c1de9f2`

**CONFIG: round-2 changelog entry**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +6/-0.* `CONFIG.md`.

### 2026-09-29 12:17 · `c27ff51`

**CONFIG: section 7 for the round-2 hardening (caches, credentials, magg asks, manifest, symlinked dirs, drift, managed hooks)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +30/-5.* `CONFIG.md`.

### 2026-09-29 12:15 · `c06fb33`

**Installer: manifest paths checked, symlinked scope dirs never pruned, private work dir, drift check, shipped commit shown, pinned LSP installs**

> - N-MANIFEST: every "files"/"offered" key must pass install_state.in_scope, or the install
>   stops before changing anything. drop() also refuses anything that isn't a scope path whose
>   parent resolves inside the staging dir. mcp_registered entries need a real name and host,
>   matched on a dot boundary.
> - N-SYMLINK/F2: a top-level scope dir that is a symlink (skills/, agents/, ...) is the user's.
>   Nothing under it is removed, the plan names what it keeps there, and writing the stack's
>   files through it needs --force. Otherwise the run stops, and --dry-run shows the plan. apply
>   refuses plan paths that leave the config dir.
> - F3: every removed hook entry is itemised: stale guard copies, duplicates, events the guard
>   left. Your own hooks sharing a group with the guard stay.
> - L1: the work dir (staged stack.env included) lives in the backup root. A no-change run that
>   created the root removes it.
> - L2: a restored symlink pointing outside the config dir needs --force.
> - L3: stage snapshots the config dir. plan and apply stop if anything changed meanwhile, and
>   apply checks again right before the first change.
> - L4: the backup root is lstat-checked (O_NOFOLLOW, owner, 0700), and backup files are created
>   O_EXCL\|O_NOFOLLOW.
> - N-SUPPLY: the manifest records the installed commit. A run prints the guard, settings and
>   installer diffstat since then, plus uncommitted edits there.
> - N4: every agent's stdio MCP server gets UV_CACHE_DIR/npm_config_cache in the protected cache
>   root (render-time).
> - N2: --print-managed-settings emits failIfUnavailable and the ~/ Read denies.
> - C7-residual: --with-lsp installs pyright@1.1.414, typescript-language-server@6.0.1 (5.3.0 on
>   Node &lt; 22.22.2) and typescript@6.0.3 with --ignore-scripts. TypeScript 7 ships no tsserver.
>
> Tests: tests/test_install_state.py (new), install_smoke section 16.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +700/-65.* `install.sh`, `lib/install_state.py`, `tests/install_smoke.sh`, `tests/test_install_state.py`.

### 2026-09-29 12:15 · `24aeb01`

**Settings, guard, rules: MCP caches out of the sandbox's reach, git credential helpers off, ask for duckdb/jupyter/enable, failIfUnavailable**

> - N4: allowWrite loses ~/.local/share/uv, ~/.npm, ~/.rustup, ~/.julia and ~/.elan; denyWrite
>   gains the MCP servers' cache root (\_\_STACK_CACHE\_\_), ~/.cache/uv, ~/.cache/pre-commit and the
>   Playwright browser caches. Sandboxed commands get their own uv, npm and pre-commit caches
>   under ~/.cache/claude-sandbox (env).
> - N1: GIT_CONFIG_COUNT/KEY_0/VALUE_0 empty the credential helper list for every command.
>   ~/.config/gh/hosts.yml and ~/.git-credentials are sandbox denyRead.
> - N3: magg_enable_server, duckdb\_\* and jupyter\_\* move from allow to ask. Ask rules prompt even
>   in bypassPermissions (permission-modes: actions no mode auto-approves). duckdb runs read-only
>   (no --read-write or --allow-switch-databases); extensions don't autoload and the config is
>   locked.
> - N2: sandbox.failIfUnavailable.
> - C2-residual: HF_TOKEN, HUGGING_FACE_HUB_TOKEN, WANDB_API_KEY and JUPYTER_TOKEN are denied to
>   sandboxed commands.
> - Guard: the cache root is protected like the state and backup roots. A cd into an unresolvable
>   directory that names protected files now counts at the next relative write, not at the cd.
> - rules:58: the protected list names .stack-manifest.json, the state/backup/cache roots and
>   install.sh as the user's step.
>
> The installer half (the \_\_STACK_CACHE\_\_ render) follows in the next commit.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +116/-24.* `dot-claude/hooks/agent_guard.py`, `dot-claude/magg/config.json`, `dot-claude/rules/claude-agent-stack.md`, `dot-claude/settings.json`, `tests/test_protected_paths.py`.

### 2026-09-29 12:00 · `b3080c5`

**Guard: protect scan expands $HOME/$CLAUDE_CONFIG_DIR/$XDG_STATE_HOME/$PWD and assigned variables, checks globs, opaque expansions, cd forms and git work-tree rewrites**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +485/-11.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`.

### 2026-09-29 11:57 · `74e593c`

**Guard: round-2 checks (credential reads, headersHelper mode, forge over curl/wget/httpie, install.sh, web taint)**

> - N1: gh auth (except plain status), git credential fill\|approve\|reject, git credential-\*,
>   git-credential-\* binaries, security find-\*-password -w/-g, dump-keychain, export: "secrets" hits
> - C2: CLAUDE_CODE_MCP_SERVER_NAME assignment and bare mcp-headers: "secrets" hits
> - P2: curl/wget/httpie/xh writes to forge hosts (parsed host, not substring): "forge" hits
> - N-SUPPLY: running the stack's install.sh is denied for every agent and the main thread
>   (--help, --dry-run, --print-managed-settings and scratch installs under a temp dir pass)
> - T3: per-agent web-taint marker; nmem_remember refused from a tainted agent
> - tests/test_no_push.py: bare mcp-headers and bash install.sh moved out of the "safe" list
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +841/-7.* `dot-claude/hooks/agent_guard.py`, `tests/test_guard_round2.py`, `tests/test_no_push.py`.

### 2026-09-29 11:57 · `e94ff4a`

**Guard: reviewers' scratch scripts and tests are read before they run; allow syntax-only checks**

> Scratch files run by interpreters, shells, source, by path or test runners get the
> same content checks as inline code (256 KiB cap, binaries refused, conftest and
> imports read). Test runner options that load scratch code or config, JS runners
> with test files under .claude-work, and search-path variables are refused.
> bash/sh/zsh/dash/ksh -n, node --check, ruby -c and php -l are allowed on any file.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +755/-39.* `dot-claude/hooks/agent_guard.py`, `tests/test_readonly_agents.py`.

### 2026-09-29 11:43 · `e46fa83`

**Prompts: BlackCat routing tie-breaks; consent wording routed through ASK USER**

> - F6: blackcat Route — logo as SVG → image-director, identity/layout →
>   designer; Claude API and Agent SDK questions → claude-code-guide; a
>   "Nobody's job" row (push, forge writes): no dispatch, one line that the
>   user does that step.
> - F7: "explicit instruction/approval/go-ahead" replaced with the ASK USER
>   flow (STATUS: blocked, NEXT: ASK USER; BlackCat asks with
>   AskUserQuestion) in cuda-, data-, devops-, dl-, quantum-, robotics-
>   engineer, plan-reviewer, cg-artist and the 3d-printing, code-standards,
>   robotics-engineering, hf-hub and git-workflows skills.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 14 files, +19/-18.*

### 2026-09-29 11:29 · `0b899c3`

**README: rewrite for tightened stack; old config moved to Changelog**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +859/-23.* `README.md`.

### 2026-09-29 11:15 · `1d7b983`

**CONFIG: installer, backups and hardening; restore names what it undoes**

> - CONFIG.md section 7: how an install runs (stage, validate, plan, back up,
>   apply), the prune table with --no-prune, backups and --restore, plugin
>   dedupe, pinned supply chain, the sandbox and the managed-settings recipe,
>   and the residual risks (shell parsing is a heuristic, gh's stored token,
>   the fixed state path in denyWrite, Linux .git/modules wildcards).
>   Validation table and changelog updated.
> - A restore lists the files it removes as "added by the install being
>   undone" instead of "not part of the stack".
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 2 files, +75/-10.* `CONFIG.md`, `lib/install_state.py`.

### 2026-09-29 11:11 · `52c0059`

**Installer: stage, validate, back up, then apply; prune by default; --dry-run, --no-prune, --restore**

> install.sh no longer edits the config dir in place. It stages the stack's
> part of $C, renders, merges and prunes there, validates the result (JSON,
> agent and skill frontmatter, placeholders, the staged guard's --self-test),
> prints the plan and, unless --dry-run, saves everything it changes or
> removes into one backup before applying (lib/install_state.py).
>
> - Default prune: agents/ and skills/ hold exactly the stack's files; files
>   of other origins, renamed ones (senior-coder, router), stale renders,
>   stack scripts and rules no longer shipped, stale magg entries and MCP
>   entries, old guard hooks and duplicate hooks/permissions go; edited stack
>   files are replaced. Listed under "removed: not part of the stack" and
>   "replaced:". Manifest of relpath + sha256; on a first run a same-named
>   differing file counts as stale. --no-prune keeps them (edits get a .new,
>   --force replaces); settings dedupe and temp leftovers apply either way.
> - Backups: ${XDG_STATE_HOME:-~/.local/state}/claude-agent-stack-backups/
>   (0700, files 0600, backup.json), outside the guard's pruned state dir and
>   denied to agents (settings Read/Edit deny, sandbox denyRead/denyWrite,
>   guard protect spec). Legacy $C/backup-\* dirs (with stack.env copies) move
>   there on every run. A no-op run makes no backup.
> - --restore [DIR\|latest] (also with --dry-run): staged, backed up itself,
>   puts back files, rc files, removed or replaced MCP entries and disabled
>   plugins; backup.json paths are checked against the config scope.
> - Symlinked leaves are never written through (staged scripts, .new renders,
>   skill subdirs); stack.env's mode counts, so a world-readable copy is
>   repaired; one path resolution for dry and real runs.
> - The STACK_EXPORT migration and post-apply manifest/stack.env writes are
>   part of the plan or recorded in the backup, so restores are exact.
> - Plugins: duplicates of claude.ai-synced skills disabled by default
>   (--keep-plugin-duplicates keeps them); mcp-server-dev disabled; each
>   disable recorded for --restore.
> - Supply chain (C7): uv and huetension tarballs checked by sha256, magg
>   1.2.1 via uv tool install --exclude-newer, venvs from hash-locked
>   requirements, the After Effects MCP at a pinned commit with npm ci
>   --ignore-scripts.
> - --print-managed-settings prints an optional managed-settings.json (JSON
>   only on stdout); the installer never installs anything root-owned.
> - doctor.sh probes the settings wiring of blackcat-guard and the read-only
>   reviewer rule; tests/install_smoke.sh covers all of the above in scratch
>   dirs (dirty config, dry-run, restore exactness, idempotence, --no-prune);
>   tests/test_no_duplicates.py checks one source per skill, agent, hook, MCP
>   entry, rule and plugin skill.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 6 files, +2443/-388.*

### 2026-09-29 11:03 · `695fbc4`

**Guard: no false positives on reads through write methods; cover plain R**

> Code review of the installer diff:
>
> - MUTATE_CODE_RE matches free functions only: sys.stdout.write(...),
>   process.stdout.write(...), Julia's write(stdout, ...) and fopen in read
>   mode no longer count as writes into protected paths (they did for every
>   agent). fopen needs a w/a/x/+ mode.
> - The plain R interpreter (R -e, R --slave -e) is parsed like Rscript, for
>   protected paths, no-push and the read-only check.
> - Tests for both directions.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +34/-7.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`, `tests/test_readonly_agents.py`.

### 2026-09-29 10:54 · `b935f8a`

**Guard: review fixes for the protected-path and read-only checks**

> - PROTECT_TRIGGER_RE and MUTATE_CODE_RE also catch writes and deletes from
>   julia, lua/luajit, Rscript and php one-liners (file.remove, unlink, cp/mv
>   calls, writeLines, sink, fopen/fwrite, file_put_contents, io.output).
> - The installer's backup root (&lt;state root&gt;-backups) is a built-in protected
>   path: agents can neither read nor change their own config backups.
> - Read-only reviewers may run `uv audit` (read like `uv tree`).
> - Tests for each case.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +56/-8.* `dot-claude/hooks/agent_guard.py`, `tests/test_protected_paths.py`, `tests/test_readonly_agents.py`.

### 2026-09-29 10:30 · `5937ec3`

**Agents: wire the 15 new skills into their Skills lines**

> Apply skills-map.md: coder, main-coder, ninja-coder, code-reviewer,
> security-auditor, verifier, plan-reviewer, researcher, devops-,
> frontend-, data-, dl-, ml-, llm-, mlx-, cuda-, robotics-engineer,
> designer, data-scientist and mathematician now name the new skills
> they should load; browser-operator points at anthropic-skills:chrome-browser.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 21 files, +46/-8.*

### 2026-09-29 10:08 · `ecc5932`

**Forge tokens out of agent environments (C6)**

> with-stack-env no longer exports GITHUB_TOKEN to shells by default (libdocs reads it from
> stack.env itself; STACK_EXPORT can still add it). claude-ninja/claude-supreme/claude-ultracode
> launch claude with GITHUB_TOKEN, GH_TOKEN and the other forge tokens unset; settings.json's
> sandbox also unsets them for every sandboxed command.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 3 files, +14/-5.* `dot-claude/bin/claude-ultracode`, `dot-claude/bin/with-stack-env`, `stack.env.example`.

### 2026-09-29 10:08 · `6466f24`

**Guard and settings: protected config, --reveal flip, read-only reviewers, sandbox (C1-C4, C8, T1-T3, P3)**

> C1  Edit denies and the guard's protect scan now cover agents/, rules/, mcp/, magg/,
>     skills/, CLAUDE.md, backup-\*/ and .stack-manifest.json in the config dir, and the
>     scan treats deletes, renames and mode changes as writes: rm/unlink/rmdir/shred,
>     mv sources, find -delete/-exec, chmod/ln/touch/truncate, tar -x/unzip, cd tracking,
>     xargs, inline python/node/perl code (os.remove, rmtree, rmSync...). The hook state
>     dir (supreme-coder lock, markers) is protected even without settings rules.
>     blackcat-guard is also wired from settings.json (`blackcat-guard --settings`, acts
>     only when agent_type is blackcat); both wirings count one step per tool_use_id.
> C2  mcp-headers/with-stack-env: the redacted defaults are allowed, any --reveal (and
>     env/printenv under with-stack-env) is denied; SECRETS_REASON no longer suggests
>     --reveal.
> C3  sandbox block: enabled, allowUnsandboxedCommands false, denyWrite for the config
>     dir and hook state, denyRead for stack.env/backups/credentials, toolchain caches
>     writable, strict network allowlist for registries, forges and model hubs, forge
>     tokens unset inside the sandbox. Edit(.git/\*\*) narrowed to hooks/config files: a
>     whole-.git deny becomes a sandbox denyWrite and would break git commit.
> C4/C8 Read denies for \*\*/stack.env, backup-\*, .git-credentials, .npmrc, .pypirc,
>     .docker/config.json, .kube, .gnupg, gcloud, Keychains; image-studio's deny roots
>     match.
> T1  browser-operator is spawned only by blackcat and the orchestrator.
> T2  code-reviewer, security-auditor, verifier, plan-reviewer and claude-code-guide get
>     read-only Bash (tests, linters, scanners, builds into scratch, git/gh reads,
>     inspection, claude --version / mcp list); fails closed.
> T3  researcher, scout and browser-operator can't write the shared memory; its
>     instructions present recalled items as data to verify, not decisions.
> P3  CronCreate and RemoteTrigger are ask rules (they prompt even in bypassPermissions).
> skillListingBudgetFraction 0.01 -&gt; 0.012 for the new skills.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 8 files, +2337/-138.*

### 2026-09-29 09:43 · `c3d427c`

**Skills: dedupe triggers, state division of labour, fold mcp-server-dev in**

> - browser-automation / computer-use-apps: stack policy only; tool mechanics
>   deferred to anthropic-skills:chrome-browser, built-in-browser, computer-use.
> - mcp-server-craft: absorbs MCPB bundles (incl. uv server type) and MCP Apps
>   from the mcp-server-dev plugin, so the installer can disable that plugin.
> - rag-agents narrowed to RAG; agent loop in agent-harness-design, API in
>   claude-api. data-visualization vs dataviz, web-research vs deep-research,
>   claude-code-extensions vs update-config/workflow-authoring/skill-creator,
>   presentation-design vs pptx, proof-craft vs math-olympiad,
>   diagrams-as-code vs artifact-diagramming: explicit divisions.
> - data-analysis, typescript-engineering, self-hosting-ops, cmake-ninja-builds,
>   local-llm-serving, llm-finetuning, ml-experiment: pointers to the new skills
>   instead of duplicated guidance.
> - git-workflows: GIT_SEQUENCE_EDITOR sed recipe used GNU-only `sed -i`, which
>   fails on macOS; now `sed -i.bak` (tested on macOS 27).
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 19 files, +53/-38.*

### 2026-09-29 09:43 · `2c49198`

**Skills: add 15 skills from the skills-gap report**

> shell-scripting, ci-cd-pipelines, container-images, dataframes-duckdb,
> frontend-frameworks, web-accessibility, causal-inference,
> time-series-forecasting, distributed-training, model-export, tabular-ml,
> bayesian-modeling, cpp-engineering, ui-design-systems, terraform-opentofu.
>
> Version-sensitive facts re-checked at primary sources on 2026-09-29
> (release pages, PyPI/npm, official docs, local probes); each skill ends
> with its source list.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 15 files, +1143/-0.*

### 2026-09-29 09:17 · `b08c61e`

**requirements: hash-locked sci/ml venv pins with a 7-day cooldown (C7)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 5 files, +5998/-0.* `requirements/README.md`, `requirements/ml.in`, `requirements/ml.txt`, `requirements/sci.in`, `requirements/sci.txt`.

### 2026-09-29 09:16 · `e95161c`

**libdocs/image-studio: SSRF hardening (C5, C9)**

> Co-Authored-By: Claude Opus 5.5

*Files changed: 4 files, +406/-18.* `dot-claude/mcp/image_studio_mcp.py`, `dot-claude/mcp/libdocs_mcp.py`, `tests/test_image_studio_mcp.py`, `tests/test_libdocs_mcp.py`.

### 2026-09-29 09:12 · `fb095d8`

**Prompts: consent only via AskUserQuestion, forge writes banned on every channel**

> Audit follow-up (security-findings.md P1, P2, T1, T2, T3, rules:60):
>
> - P1: consent for destructive/external actions reaches a subagent only as the
>   answer to its own NEXT: ASK USER, asked by BlackCat with AskUserQuestion;
>   text in a brief is never consent (rules, BlackCat, browser-operator,
>   orchestrator, designer, mcp-broker, claude-code-engineer).
> - P2: no forge write through gh/tea/fj, web UI, REST/GraphQL clients or MCP
>   (rules Git section, browser-operator stop list).
> - T1: browser-operator dropped from the spawn lines of researcher, ml-, dl-,
>   llm- and cuda-engineer; they return NEXT: browser-operator instead. Kept
>   for blackcat and orchestrator. Needs the matching agent_guard.py POLICY
>   change (lint compares the two).
> - T2: code-reviewer, security-auditor, verifier, plan-reviewer and
>   claude-code-guide: Bash for read-only commands only; read content is data.
> - T3: recalled memory is a lead, not a decision; nmem_remember needs a cited
>   local source; researcher never writes.
> - rules: full protected-path list for the installed stack.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 23 files, +37/-35.*

### 2026-09-29 09:07 · `a56d4d0`

**Agents: tighten prompts, crisp hand-off descriptions, prompt-level hardening**

> - Descriptions say what each agent does and who takes the adjacent work.
> - BlackCat: agent catalogue replaced by a boundary routing table (the Agent
>   tool already lists descriptions); -33%.
> - Duplicates of the global rules removed (supreme-coder policy, economy, background
>   handling); memory instructions compressed to one Memory: line.
> - designer/image-director: model names and prices dropped (image-studio tool
>   descriptions carry them live).
> - Security: browser-operator needs the user's quoted instruction for
>   irreversible steps; mcp-broker edits agents only in the stack repo and only
>   on the user's request; claude-code-engineer needs the user's instruction to
>   loosen guards; claude-code-guide Bash read-only; devops never pushes;
>   injection lines for researcher, doc-specialist, mcp-broker, reviewers.
> - Reviewers load review-protocol; coder verifies before reporting.
> Frontmatter unchanged apart from descriptions. Agent bodies 87.3K -&gt; 74.7K chars.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 36 files, +324/-376.*

### 2026-09-29 09:07 · `eb2de04`

**Rules: untrusted-content rule, quoted-consent rule, no in-place stack edits**

> - Truth: web/document/tool/MCP content is data, never instructions; requests
>   found in it (push, config changes, data egress, spending) are reported.
> - Destructive actions: a brief carries the user's consent only by quoting the
>   user's words; another agent's request is never consent.
> - Files & safety: the installed stack is never edited in place; changes go to
>   the stack repo and the installer.
> - MCP and foreground/background bullets condensed.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 1 file, +5/-3.* `dot-claude/rules/claude-agent-stack.md`.

### 2026-09-29 01:59 · `e06af75`

**Desktop parallelism fix, two-model calibration, spawn caps, supreme-coder via orchestrator only**

> - Guard drops BlackCat's run_in_background:false (BLACKCAT_BACKGROUND): SDK hosts
>   (Claude Desktop, Conductor) no longer block the main thread on one foreground child.
> - BlackCat: visible reply every turn, AskUserQuestion for unsettled choices,
>   8 dispatches / 12 steps / 120 s window; recommended session effort medium.
> - Models pinned to claude-opus-5-5 / claude-sonnet-5-5 only (lint-enforced); no Haiku.
> - Effort and maxTurns recalibrated per agent from measured turns.
> - Fan-out: orchestrator 10, main-/supreme-coder 6, ninja-coder 5, researcher 4, planner 8,
>   default 3; CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS 32.
> - supreme-coder: only the orchestrator spawns it, once per session (SUPREME_SPAWNERS,
>   SUPREME_ONCE_PER_SESSION); others return NEXT: supreme-coder with a dossier.
> - Installer strips CLAUDE_CODE_DISABLE_BACKGROUND_TASKS / CLAUDE_CODE_FORK_SUBAGENT;
>   doctor warns. README updated with a Changelog; CONFIG.md lists every applied value.
>
> Co-Authored-By: Claude Opus 5.5

*Files changed: 47 files, +721/-256.*

### 2026-09-28 22:43 · `0abe3eb`

**Guard: session context budget 666M; README caps consolidated**

> STACK_SESSION_CTX_BUDGET 120000000 -&gt; 666000000 (settings.json, the hook's
> docstring and knob_int default, README knob row, smoke check).
> STACK_PROMPT_CTX_BUDGET stays 100000000.
>
> README: cap numbers now appear only in the requirements row and the Knobs
> table (now a heading, #knobs); the BlackCat/orchestrator rows, spawn policy,
> copies note, budget hook row and BlackCat hook paragraph name the knob
> instead. Orchestrator row says 7 tasks per job (a DAG), not "in flight";
> the new-agents row lists all ten bold agents (36 in all); claude-code-guide
> joins the low-effort lookups; the 800K window in "How the apps were checked"
> is labelled as that run's shipped setting.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 4 files, +20/-17.* `README.md`, `dot-claude/hooks/agent_guard.py`, `dot-claude/settings.json`, `tests/install_smoke.sh`.

### 2026-09-28 22:43 · `b2e29d5`

**Models: Sonnet tier pinned to claude-sonnet-5-5 (Sonnet 5.5)**

> The nine Sonnet agents (blackcat, scout, coder, devops-engineer, data-engineer,
> verifier, browser-operator, mcp-broker, claude-code-guide) now name the model
> explicitly as claude-sonnet-5-5 instead of the sonnet alias. The Haiku
> redirect ANTHROPIC_DEFAULT_HAIKU_MODEL moves from claude-sonnet-5 to
> claude-sonnet-5-5; the installer treats the old claude-sonnet-5 value as a
> stack default and upgrades it. doctor.sh reads BlackCat's saved effort under
> modelSettings.claude-sonnet-5-5 (Sonnet 5.5 defaults to medium). README,
> mcp_servers.md, the claude-code-extensions skill, statusline docstring and
> tests follow. Sonnet 5.5 needs Claude Code 2.1.284 or later.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 18 files, +52/-51.*

### 2026-09-28 22:26 · `bed42c6`

**Guard: MCP call cap per prompt, lowered to 64**

> The per-subagent MCP call count now covers one run of the agent (one prompt):
> the counter stores the registry's `started` stamp, which SubagentStart rewrites
> on every spawn and resume, and a different stamp starts the count again from 0.
> A message to a still-running agent gets no new allowance. STACK_MAX_MCP_CALLS
> drops from 88 to 64 (effective cap: min(64, the agent's maxTurns)). Docs,
> rules, settings, smoke check and tests updated; a new test covers the reset.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 6 files, +62/-28.*

### 2026-09-28 22:11 · `922d3d6`

**Guard: raise fan-out caps (orchestrator/planner/plan-reviewer 8, BlackCat 6)**

> STACK_MAX_FANOUT_BY_TYPE default orchestrator=6,planner=4 -&gt; orchestrator=8,planner=8,
> plan-reviewer=8; BLACKCAT_MAX_DISPATCH 4 -&gt; 6. STACK_MAX_FANOUT stays 3 for every other
> agent; copy, maxTurns, MCP-call and token caps unchanged. Hook defaults, self-test,
> settings.json, README, blackcat.md and the tests follow.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 6 files, +29/-28.*

### 2026-09-28 22:15 · `48ad791`

**Settings: auto-compact window 400K instead of 300K**

> autoCompactWindow 300000 -&gt; 400000 (user's choice over the audit's 300K
> recommendation). README, installer messages, status-line docstring,
> doctor check and install smoke assertions follow the new value; the
> status-line examples now show 156K/400K so the bar matches the ratio.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 6 files, +23/-23.*

### 2026-09-28 21:35 · `3d59dd7`

**Guard: cap each subagent's MCP tool calls per session**

> agent_guard.py counts every subagent's mcp\_\_\* calls per agent_id per session
> (budget mode and the main hook's MCP tools) and refuses further MCP calls past
> min(STACK_MAX_MCP_CALLS=88, the agent's frontmatter maxTurns); other tools and
> reporting keep working. The main thread is left to BLACKCAT_MAX_STEPS. Fails
> open like the token budgets. New owned knob in settings.json and install.sh;
> README, rules, self-test (every agent file yields maxTurns) and tests updated.
> No agent's maxTurns changes.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 7 files, +197/-14.*

### 2026-09-28 20:59 · `e1447f2`

**Guard: BlackCat resume steps, resumes past a stuck lock, test gaps**

> Review round 2 (approve-with-fixes), three LOW findings:
>
> - A BlackCat SendMessage at BLACKCAT_MAX_STEPS was refused by
>   blackcat-guard after the main hook, running in parallel, had already
>   reserved a resume slot under the target's parent (held for
>   STACK_RESUME_TTL_S). The main hook now claims BlackCat's step for a
>   SendMessage together with the reservation, as on_agent does for Agent;
>   a refusal rolls back both, and blackcat-guard leaves SendMessage to it.
> - on_subagent_start recorded a resume inside the fanout mutex; on a
>   MutexTimeout the agent stayed 'stopped' and supreme_confirm was skipped.
>   It now records the start and drops the reservation outside the lock.
> - Tests: doctor.sh's SessionStart fork matcher check (install smoke),
>   and a supreme_resume error after the reservation was written.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 4 files, +165/-20.* `README.md`, `dot-claude/hooks/agent_guard.py`, `tests/install_smoke.sh`, `tests/test_agent_guard.py`.

### 2026-09-28 20:41 · `e037ec9`

**README: resume TTL knob, budget-mode guard log, fork matcher, title typo**

> - Knobs table: STACK_RESUME_TTL_S (120 s) next to STACK_LEASE_TTL_S.
> - STACK_GUARD_LOG: budget mode logs only the tool name and ids, never
>   the tool input.
> - Hook table: SessionStart runs on startup, resume and fork, matching
>   the settings.json matcher.
> - Drop the stray "y" before the title on line 1.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 1 file, +4/-3.* `README.md`.

### 2026-09-28 20:36 · `94c4555`

**Merge branch 'worktree-agent-a1836ef9ade558698' into worktree-agent-a301f27cdf346c15c**

*Files changed: 6 files, +23/-16 (against first parent).*

*Merge commit (parents `af6b047`, `cb5f066`).*

### 2026-09-28 20:34 · `af6b047`

**Reserve resume slots, drop leaked leases, wire fork; BlackCat reads**

> Spawn-policy hook review fixes (agent_guard.py):
>
> - SendMessage resumes of finished agents now take a reservation
>   fanout/&lt;parent&gt;/resume-&lt;agent&gt;.json under the fan-out mutex, counted
>   like a spawn lease, so resumes sent in one message respect the fan-out
>   and copy caps. SubagentStart turns it into a live background child
>   (fanout then registry lock); unstarted ones expire after
>   STACK_RESUME_TTL_S (120 s); a supreme-lock refusal rolls it back.
> - A starting agent voids its own leftover spawn leases; a stopped child
>   drops the lease of the call that spawned it (toolUseId/parentAgentId
>   from its meta.json when present).
> - on_agent_done drops the lease in a finally, outside the mutex, so a
>   lock timeout no longer leaks it.
> - --check-budget fails on 50+ transcript lines with no assistant line
>   and says "skipped" instead of "ok (0 API calls)" for young sessions.
> - Budget deny messages say a raised knob holds until the next install.
> - budget mode logs only the tool name and ids with STACK_GUARD_LOG=1.
> - BlackCat may use Read, Grep and Glob (each call counts toward
>   BLACKCAT_MAX_STEPS); Write, Edit and Bash stay denied.
> - cuda-, dl-, ml- and llm-engineer rows add browser-operator.
>
> settings.json: SessionStart matcher startup\|resume\|fork (fork handling
> never ran). doctor.sh checks that matcher. install.sh make_copy strips
> base-body sentences naming a &lt;type&gt;-copy; install_smoke asserts it.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 7 files, +563/-106.*

### 2026-09-28 20:18 · `cb5f066`

**BlackCat quick checks; remote NVIDIA and Kaggle runs in cuda-engineer**

> - blackcat: add Read, Grep and Glob for quick checks only (a file exists,
>   spot-check a child's claimed diff), counted against the 8-step cap.
> - cuda-engineer: "Remote NVIDIA hosts and competitions" section (SSH
>   preflight, rsync, tmux/nohup with Monitor waits, remote Jupyter over a
>   port-forward, the Kaggle CLI via uvx with credentials never printed,
>   submissions and public kernels only on explicit instruction, web-only
>   UIs to browser-operator).
> - dl-, ml-, llm-engineer: pointer to that section, or hand the run to
>   cuda-engineer.
> - cuda-, dl-, ml-, llm-engineer: browser-operator in May spawn, matching
>   the hook's pending POLICY change; README rows and hook text follow.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 6 files, +23/-16.*

### 2026-09-28 19:47 · `cfda071`

**Integrate the hook and config branches: copy types, budget doctor check**

> The hook keeps AGENTS to the 36 shipped files and publishes the copy types as COPY_OF
> (copy_types in --print-policy) plus POLICY rows; lint_agents now reads them from there
> instead of expecting researcher-copy/coder-copy in AGENTS, and asserts plan-reviewer and
> image-director are leaves while planner keeps a row.
>
> doctor.sh: the policy probe skips the `budget` hook command (budget mode leaves Agent calls
> to the main hook, so the probe FAILed); new checks that a PreToolUse "\*" group runs
> agent_guard.py budget and that --check-budget still reads usage from real transcripts. The
> agent-files check counts the rendered copy types instead of warning about them.
>
> install_smoke: every installed May spawn sentence, the rendered copies included, equals its
> POLICY row; doctor's budget lines are asserted. README: budget hook row in the hook table,
> STACK_LEASE_TTL_S knob, STACK_FANOUT_IDLE_S applies to background children.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 4 files, +74/-18.* `README.md`, `dot-claude/bin/doctor.sh`, `tests/install_smoke.sh`, `tests/lint_agents.py`.

### 2026-09-28 19:36 · `7398391`

**Merge config branch: installer retraction, copy-type rendering, knobs, rules**

> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 119 files, +822/-349 (against first parent).*

*Merge commit (parents `74e98dd`, `518cefb`).*

### 2026-09-28 19:35 · `74e98dd`

**Merge hook branch: leases, copy types, per-type caps, context budgets**

> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 4 files, +1376/-238 (against first parent).* `dot-claude/hooks/agent_guard.py`, `dot-claude/settings.json`, `tests/test_agent_guard.py`, `tests/test_guard_regressions.py`.

*Merge commit (parents `372e81b`, `d15fa48`).*

### 2026-09-28 19:33 · `d15fa48`

**Make plan-reviewer and image-director leaves in the spawn policy**

> A plan review and an image job are one bounded task each: both rows are
> now empty and both agents are in LEAVES, so the hook refuses any Agent
> call from them. planner keeps its row (scout, explore, claude-code-guide).
> Their agent files must drop Agent and SendMessage and the "May spawn"
> sentence (other branch).
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 2 files, +5/-3.* `dot-claude/hooks/agent_guard.py`, `tests/test_agent_guard.py`.

### 2026-09-28 19:30 · `ae592d5`

**Enforce spawn caps with call-long leases, copy types and token budgets**

> Leases (plan-review #1 ii-iv): a spawn lease lives from PreToolUse(Agent)
> until that tool_use_id's PostToolUse, PostToolUseFailure or
> PermissionDenied, so a foreground child counts for its whole run.
> PostToolUse "async_launched" records a live background child; the
> SubagentStart of a stopped agent (a resume) makes it one again. Leases
> are voided when their caller stops, at SessionStart, and after
> STACK_LEASE_TTL_S (6 h). Nothing links a child to a lease by type; a
> child's parent is written once, from the caller's own PostToolUse.
>
> Copies: only researcher and coder copy themselves, as the agent types
> researcher-copy and coder-copy (install.sh renders them). A copy's row
> never lists its base or any copy, and the copy rule is decided on the
> caller's agent_type alone, with the decisions.md message. At most
> STACK_MAX_SELF_FANOUT=2 live copies per type in the whole session. No
> other agent may spawn its own type.
>
> Caps: STACK_MAX_FANOUT=3, STACK_MAX_FANOUT_BY_TYPE="orchestrator=6,
> planner=4" in both the spawn and the resume check, BLACKCAT_MAX_DISPATCH
> =4, and BLACKCAT_MAX_STEPS=8 now counts dispatches (in the main hook,
> with the lease). The main thread has no per-parent cap. Registry and
> folder checks come before the fan-out mutex (review #15).
>
> Token budgets (review #4): STACK_PROMPT_CTX_BUDGET=100M per human prompt
> and STACK_SESSION_CTX_BUDGET=120M per session, context tokens summed
> over the main and subagent transcripts, deduplicated by message.id +
> requestId, read incrementally with byte offsets. A new `budget` mode
> runs on every PreToolUse (settings.json group "\*"); the main hook's own
> tools check first, before any lease. Reporting and stop calls are never
> refused. Fails open with a warning; --check-budget is the doctor check.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 4 files, +1350/-227.* `dot-claude/hooks/agent_guard.py`, `dot-claude/settings.json`, `tests/test_agent_guard.py`, `tests/test_guard_regressions.py`.

### 2026-09-28 19:23 · `518cefb`

**plan-reviewer and image-director become leaves (no Agent, SendMessage)**

> Neither spawned a child in the audited sessions, and both already have
> the tools their only children (scout, explore, claude-code-guide) would
> use; without Agent they no longer carry the agent-types listing and the
> two tool schemas on every call. planner keeps Agent and SendMessage.
> Needs the hook's POLICY rows for both emptied and LEAVES extended
> (parallel hook branch); README leaves list and spawn table follow.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 3 files, +6/-7.* `README.md`, `dot-claude/agents/image-director.md`, `dot-claude/agents/plan-reviewer.md`.

### 2026-09-28 19:23 · `deb09f2`

**Cut token waste: copy types, knobs, maxTurns tiers, shorter listing and rules**

> Settings (decisions.md): autoCompactWindow 300000; skill listing at the
> 0.01 default with skillListingMaxDescChars 500 and skillOverrides for six
> user-run bundled commands; env knobs STACK_MAX_FANOUT=3,
> STACK_MAX_FANOUT_BY_TYPE=orchestrator=6,planner=4, BLACKCAT_MAX_DISPATCH=4,
> BLACKCAT_MAX_STEPS=8, STACK_MAX_SELF_FANOUT=2, STACK_PROMPT_CTX_BUDGET=1e8,
> STACK_SESSION_CTX_BUDGET=1.2e8, CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS=20.
>
> Installer: renders researcher-copy.md and coder-copy.md from their base
> files (COPY_TYPES; own name and short description, same tools, model,
> maxTurns and servers, May spawn = base minus base and copies); the spawn
> and budget knobs are owned env; skillListingMaxDescChars/skillOverrides
> merged set-if-absent. Smoke tests for copies, owned knobs and rollback.
>
> Lint: maxTurns tiers (all &lt;= 350, bounded &lt; 200, none on blackcat), copy
> types against install.sh and the hook policy, no agent lists itself, a
> bare python/pip check over agent and skill text, the 500-char cut.
>
> Agents: maxTurns per knob-recommendations; self-spawn removed except
> researcher and coder, which name their copy types; orchestrator,
> blackcat and main-coder per proposal section 4 plus plan.md checkpoints
> at every dispatch; vector/raster ASK USER flow (designer, image-director,
> blackcat, orchestrator); neural-memory start/end lines in the eight
> research and modelling agents.
>
> Rules: 10,051 -&gt; 9,476 bytes; tiered reply sizes, numberless caps, uv
> with its exceptions, restored cues, ASK USER line, MCP lifecycle as
> probed. Skills: shorter descriptions (Appendix A plus restored nouns),
> uv instead of bare python/pip. README: knobs, copies, migration and
> rollback, 200K-window listing note, neural-memory counts.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 119 files, +701/-339.*

### 2026-09-28 19:23 · `a5913d5`

**Installer: retract dropped settings keys, make plugin dedupe opt-in**

> - Set-if-absent keys an earlier stack version shipped and this one does
>   not (a rollback) are removed while they still hold the stack's value,
>   as the manifest already does for env keys and permission rules;
>   skillOverrides is retracted per skill.
> - --dedupe-plugins disables the document-skills and skill-creator
>   plugins only on request where claude.ai already syncs those skills
>   (synced skills load only in claude.ai-login sessions), prints the
>   re-enable command, records the plugin in the manifest and re-enables
>   it once the synced copy is gone. The synced-path check now accepts
>   skills/synced/&lt;account&gt;/&lt;name&gt;.
> - Smoke test section 12 covers the opt-in, the record and re-enable.
>
> Kept separate so that reverting the token-waste changes that follow
> leaves the retraction code in place.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 2 files, +115/-3.* `install.sh`, `tests/install_smoke.sh`.

### 2026-09-28 19:06 · `0300b11`

**Import the guard's heavy stdlib modules where they are used**

> base64, shlex, shutil, struct, subprocess, tempfile and urllib.parse cost
> about 9 ms of every hook start. The guard is about to run on every tool
> call, so they now load only in the image, no-push, local-file and
> session-start paths that use them. write_json_atomic makes its own
> O_EXCL temp name instead of tempfile.mkstemp.
>
> Measured on /usr/bin/python3 3.9.6, PreToolUse(Agent): 47.6 -&gt; 39.7 ms
> median over 40 runs.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 1 file, +21/-8.* `dot-claude/hooks/agent_guard.py`.

### 2026-09-28 16:58 · `372e81b`

**Add code intelligence for the stack's other languages**

> The installer already enabled Anthropic's official LSP plugins (pyright, typescript,
> rust-analyzer, swift, clangd, gopls, jdtls) when their servers were on PATH. Add:
>
> - kotlin-lsp@claude-plugins-official to that list.
> - A local directory marketplace, agent-stack (dot-claude/stack-plugins, installed to
>   ~/.claude/stack-plugins and loaded in place), with LSP plugins for the languages the
>   official marketplace does not cover: Haskell (haskell-language-server-wrapper --lsp),
>   Julia (LanguageServer.jl from the @claude-lsp environment, analysing the project that
>   holds CLAUDE_PROJECT_DIR), Lean 4 (lake serve) and Scala (Metals, builds auto-imported).
>   Each is installed only when its server is present; a changed copy is backed up.
> - --with-lsp installs HLS, LanguageServer.jl, Metals and kotlin-lsp through ghcup, julia,
>   cs and brew, only when that toolchain is already present.
> - An Edit deny rule for ~/.claude/stack-plugins (its server commands run on their own),
>   the doctor's language-server check, README and claude-code-extensions notes, and a
>   smoke-test section for the marketplace step.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 11 files, +268/-12.*

### 2026-09-28 07:53 · `b7568de`

**Harden secrets and permissions for bypassPermissions mode**

> A security review found mcp-headers, with-stack-env, install.sh and doctor.sh
> could leak real API keys to a terminal, log or agent transcript, and that
> bypassPermissions mode (just made the default) removes several safety nets
> that were only a permission prompt.
>
> Secrets:
>
> - mcp-headers: a server name given as a CLI argument now redacts the header
>   value by default; --reveal opts in. Claude Code's own invocation (via
>   CLAUDE_CODE_MCP_SERVER_NAME, no CLI argument) is untouched.
> - with-stack-env --print-env: redacts key values by default too, same
>   --reveal opt-in. The shell-profile line install.sh writes passes --reveal
>   (it must export real values into the user's own shell); doctor.sh's checks
>   never did and still don't.
> - install.sh: URLs in the MCP plan's output are shown as scheme+host+path
>   only (no query string); a user's own headersHelper or stdio command shows
>   as "(your own command)"; the settings.json parse-error excerpt masks
>   key/token/secret/password/auth\* values.
> - doctor.sh: strips query strings from `claude mcp list` passthrough lines.
> - agent_guard.py (no-push hook, reusing its shell lexer): denies a bare
>   `mcp-headers <server>` or `with-stack-env --print-env` without --reveal,
>   and `bash -x`/`sh -x`/`zsh -x` on install.sh or doctor.sh (xtrace would
>   echo every key). Matching settings.json deny rules use exact-match
>   strings, never a trailing wildcard, so they cannot also catch the
>   --reveal-carrying form (Claude Code deny rules can't be carved out by an
>   allow rule).
> - tests/install_smoke.sh: unsets every real credential and cache-path env
>   var up front, adds --reveal where a test needs the real value, and hashes
>   helper output instead of printing it on failure.
> - tests/test_mcp_headers.py: also clears XDG_CACHE_HOME.
>
> Traced the trusted path end to end: stack.env -&gt; mcp-headers/with-stack-env
> -&gt; Claude Code's headersHelper (CLAUDE_CODE_MCP_SERVER_NAME, no CLI arg) -&gt;
> MCP server headers, and the equivalent for local stdio servers (with-stack-
> env exec, or a server reading stack.env itself, e.g. image_studio_mcp.py) —
> keys reach the target process via its own env, never as a Bash argv the
> model would see, and are never printed. That path is unchanged. Residual
> risk, not fixed here: `claude mcp add-json` takes its JSON on argv, so a
> migration's failure-path restore of a user's pre-existing (already
> plaintext) MCP entry is briefly visible in `ps`; this is Claude Code's own
> CLI interface, not something this stack's scripts can avoid.
>
> Permissions (bypassPermissions removed the implicit prompt for tools not in
> `allow`, and the built-in protected-path check for Bash):
>
> - settings.json: added `permissions.ask` for mcp-broker's magg_add_server,
>   magg_load_kit and proxy (explicit ask rules still prompt in every mode,
>   including bypassPermissions). Added Edit deny rules for .git/\*\*  and a
>   project's .claude/settings.json, settings.local.json and hooks/\*\* (not
>   all of .claude/\*\*, which would also block legitimate agent/skill edits).
> - agent_guard.py: extended the no-push hook with a "protect" scan that
>   denies a Bash-level write (redirection, cp/mv/install/rsync, tee, dd,
>   sed/perl -i, also through bash -c/eval) into any path already denied to
>   Read/Edit/Write, reusing the same shell lexer and settings.json deny
>   rules (Read denies also block Edit/Write on the same path).
> - README.md updated to describe the ask-rule mechanism instead of the
>   now-removed implicit prompt.
>
> Added/updated tests for the --reveal opt-in, the new deny rules, and the
> protected-path hook (tests/test_no_push.py, tests/test_protected_paths.py,
> tests/test_mcp_headers.py). Full suite green: pytest (607 passed, the 9
> image_studio_mcp PIL failures are pre-existing/unrelated), install_smoke.sh
> (144 passed), agent_guard.py --self-test, lint_agents.py.
>
> Co-Authored-By: Claude Sonnet 5

*Files changed: 11 files, +588/-49.*

### 2026-09-28 07:23 · `b74a62d`

**Start sessions in bypassPermissions mode**

> Set permissions.defaultMode to "bypassPermissions" in the shipped
> settings.json (user scope, where Claude Code honors this value; project
> and local settings ignore it). The installer copies non-list permission
> keys over, so every install re-sets it.
>
> PreToolUse hooks (agent_guard.py: no-push, Read-deny checks for MCP file
> tools, spawn policy) and permissions.deny rules still apply in this mode.
> Protections that were only a permission prompt do not: mcp-broker's
> magg add-server/proxy calls, Bash writes to hooks/bin/settings.json, and
> any other tool call no deny rule or hook blocks. README updated to say so,
> and claude -p now inherits this mode.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 2 files, +13/-4.* `README.md`, `dot-claude/settings.json`.

### 2026-09-28 01:08 · `28d20be`

**Harden the no-push rule: nested shells, forge writes, unfiltered hook**

> - agent_guard.py no-push: the detector is now a quote-aware shell lexer
>   and scanner. It recurses into sh/bash/zsh/pwsh -c, eval, ssh/watch/su/
>   tmux, here-strings, pipes and heredocs into a shell, command-position
>   $(...), python -c style inline code, and the places git runs commands
>   (-c alias/core.editor, git config, GIT_EDITOR, submodule foreach,
>   rebase --exec, bisect run). What only resolves at run time (git $X,
>   g${X}it, xargs git, base64 -d \| sh, pwsh -EncodedCommand) is refused,
>   and so is a command it cannot finish checking (parser error, nesting
>   deeper than 8, more than 64 heredocs on a line, more than 8 s of work).
>   pwsh switches are matched by prefix as pwsh does; compound commands
>   (while ... done &lt;&lt;EOF) own their heredocs.
> - Forge writes through gh, tea and fj (create, merge, review, comment,
>   release, fork, gh/tea api with a write method) are denied the same way;
>   read-only commands pass. Command trees checked against the gh manual,
>   tea docs/CLI.md and forgejo-cli's clap definitions.
> - settings.json: the no-push hook runs on Bash\|Monitor\|PowerShell with no
>   `if` filter (tested on Claude Code 2.1.283: `if: "Bash(git *)"` does not
>   fire for bash -c, sh -c, zsh -c, eval or /usr/bin/git); deny rules for
>   the common forge writes.
> - Rules, git-workflows skill and README say exactly what is enforced.
> - doctor.sh probes the nested and Monitor forms and flags a filtered hook;
>   install_smoke checks the wiring and no longer inherits STACK_ENV_FILE
>   (run inside a session it served, and on failure printed, a real key).
> - tests/test_no_push.py: 404 cases (nested, obfuscated, run-time opaque,
>   forge reads and writes, three rounds of review regressions, input-size
>   timing, fail closed on parser errors).
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 8 files, +1548/-70.*

### 2026-09-27 23:12 · `f743ca4`

**Add the stack's Git rule: never push, work on main, always merge back**

> New global rule for every agent (rules/claude-agent-stack.md, "Git"):
>
> - Never push: no git push in any form, no send-pack, lfs push or
>   subtree push, no forge command that writes to a remote. Publishing
>   is the user's step.
> - Work on local main when possible; use a worktree or branch only when
>   the work needs isolation.
> - Always merge back: fast-forward local main to the branch
>   (merge --ff-only), run the tests on main, then remove the worktree
>   and delete the branch.
> - A fast-forward that fails (diverged history, conflicts, a dirty main
>   checkout) goes to main-coder, which rebases or merges, resolves,
>   tests and fast-forwards; never force, reset, stash or discard.
>
> Enforcement:
>
> - settings.json: deny rule Bash(git push \*), plus worktree.baseRef
>   "head" so new worktrees start from local work and can fast-forward
>   back (origin/main goes stale when nothing is pushed).
> - agent_guard.py no-push mode: PreToolUse Bash hook (if: Bash(git \*))
>   that catches the forms the deny rule misses (git -C dir push,
>   git -c k=v push, quoted 'push', pushes inside $(...) or backticks),
>   skips heredoc bodies, and ignores STACK_POLICY=off.
> - install.sh main-only guard: installs only from main; from another
>   branch or worktree it fast-forwards local main (ff-only, git hooks
>   off, push subcommands refused) and re-runs from the main checkout,
>   or stops with the fix when the fast-forward is blocked.
>
> Also: main-coder owns merge resolution, git-workflows skill rewritten
> around local main, doctor.sh probes the no-push hook, the installer
> merges worktree settings key by key, README documents all of it.
> Tests: tests/test_no_push.py (parser, hook, settings wiring) and
> install_smoke.sh section 10 (ff from worktree/branch, diverged,
> dirty branch, dirty main, --mcp-plan, remote refs untouched); the
> smoke test now installs from a scratch git snapshot on main.
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 10 files, +458/-26.*

### 2026-09-27 21:55 · `c17e463`

**Changed agent name**

*Files changed: 20 files, +399/-338.*

### 2026-09-27 20:30 · `e83cac1`

**Final version of my set of agents**

*Files changed: 3 files, +6/-6.* `README.md`, `dot-claude/agents/router.md`, `dot-claude/rules/claude-agent-stack.md`.

### 2026-09-27 20:10 · `13ca8d8`

**Merge branch 'claude/multi-agent-config-setup-357a55'**

*Files changed: 64 files, +1480/-128 (against first parent).*

*Merge commit (parents `cbf46c4`, `8ea96cc`).*

### 2026-09-27 20:04 · `cbf46c4`

**Final version of claude config installer**

*Files changed: 1 file, +1/-1.* `README.md`.

### 2026-09-27 17:02 · `8ea96cc`

**Add quantum, robotics and 3D agents; depth 4; 17 skills; new catalog MCP servers**

> - New agents: quantum-engineer, robotics-engineer, cg-artist (POLICY rows, router/orchestrator lists)
> - All agents: model aliases opus/sonnet/fable only; generous maxTurns (60-2000)
> - Depth 4 (CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH=4) plus "spawn only when it pays" rules
> - Skills: julia, haskell, jvm, cmake-ninja, ide-workflows, postgresql, mongodb, robotics,
>   robot-learning, blender-3d, sculpting-texturing, houdini-fx, 3d-printing,
>   adobe-creative-cloud, raster-imaging, quantum-physics-numerics, image-model-pipelines
> - MCP: agent-scoped mcp-for-blender (cg-artist); magg catalog mongodb, postgres, ros,
>   chrome-devtools, qiskit-runtime (read-only DB servers pre-approved; ros/qiskit ask)
> - Hook guards chrome-devtools file arguments; jdtls LSP plugin; skill listing 2.5%
> - Tests, doctor, README updated
>
> Co-Authored-By: Claude Opus 5.5 (1M context)

*Files changed: 64 files, +1480/-128.*

### 2026-09-27 12:57 · `441ebf0`

**Final claude configuration installation**

*Files changed: 132 files, +24352/-0.*

## Changelog from CONFIG.md

Section 9 of CONFIG.md at the same commit, copied as it stood (names and paths sanitised).

Entries name agents, knobs and files by their current names.

### 2026-10-03 (Plan as the default mode, acceptEdits on the 45 writers, step cap 24)

- **Plan by default.** `dot-claude/settings.json` ships `permissions.defaultMode: "plan"`; the previous value was `"bypassPermissions"` (shipped since 2026-09-28). The user: "I want the default permissions to be Plan, it makes much more sense and I want it if the user changes permissions to pass them down chain to subagents". Docs facts (claude-code-guide's report on `code.claude.com/docs/en/permission-modes.md`, `settings.md`, `sub-agents.md`, fetched 2026-10-03; not re-fetched for this entry): `defaultMode` takes `default`, `acceptEdits`, `plan`, `auto`, `dontAsk` or `bypassPermissions`; user scope accepts all of them, and project and local settings ignore `auto` and `bypassPermissions`; the settings file loses to `--permission-mode`; the terminal default is `auto` from 2.1.283; an agent without `permissionMode` inherits the main mode; a parent in `bypassPermissions`, `acceptEdits` or `auto` beats the agent file, while with a parent in `default`, `dontAsk` or `plan` the file wins (except `bypassPermissions`); ExitPlanMode is removed from subagents not in plan, subagents in plan are read-only, and approving a plan switches the session's mode, which new subagents inherit.
- **Installer:** a scalar `permissions` key is no longer overwritten on every run. The stack's value is set while you have none or still hold the value shipped last time; a mode you chose is kept (`kept your permissions.defaultMode=…`). The manifest records the shipped scalars (`settings_permission_scalars`). For an older manifest the previous value is read from the recorded commit's `dot-claude/settings.json` (earlier installers overwrote the mode on every run, so that value was in place). An install still on the old shipped `bypassPermissions` moves to `plan` once, with a note on Shift+Tab, ExitPlanMode and how to set `bypassPermissions` again. When the recorded commit is not in the repository, nothing changes and the installer says why. Smoke §13c.
- **Agents:** 45 agent files carry `permissionMode: acceptEdits`: the 31 builders as before, plus orchestrator, designer, writer, researcher, doc-specialist, image-director, claude-code-engineer, cg-artist, motion-designer, data-scientist, mcp-broker, mathematician, browser-operator and vfx-td. The user: "most ssubagents must run in accept edits or else it will bloat context for them too and lag on resolution time", for subagent runs. Without a mode: blackcat and the 10 read-only agents (claude-code-guide, code-reviewer, explore, oracle, plan-reviewer, planner, proof-checker, scout, security-auditor, verifier). New lint rule (`tests/lint_agents.py` `permission_mode_problem`, `tests/test_permission_modes.py`): `acceptEdits` only with Write/Edit/NotebookEdit, `plan` only without; any other value fails. blackcat.md rule 5 now says builders edit even in Plan, so they go out only after approval (body length unchanged).
- **Launchers:** `bin/claude-ultracode` passes `--permission-mode plan` unless you pass `--permission-mode` or `--dangerously-skip-permissions`. This replaces "no mode flag in the launcher": the user wants `acceptEdits` only "when run as subagents, not when on main thread", and whether a main-thread agent's frontmatter mode applies is not documented. That the flag also beats the agent file is expected, not verified. `tests/test_ultracode_launcher.py`.
- **Probe:** `STACK_MODE_PROBE=1` logs the `permission_mode` hooks see (section 5, "Permission modes", has the procedure); settings.json wires PermissionRequest to the guard, which returns no decision. The guard also strips the Agent tool's `mode` input (deprecated and ignored in 2.1.287) from every spawn. A guard rule that denies edits to builder subagents while the main thread is in plan (`STACK_MODE_ENFORCE`) is a follow-up that waits for the probe; it is not built.
- **`BLACKCAT_MAX_STEPS` 12 → 24** (the user: "make it 24"); `BLACKCAT_MAX_DISPATCH` stays 8 and `BLACKCAT_MAX_OWN_STEPS` 4, so 24 − 4 ≥ 8 holds.
- Rerun `./install.sh` from the main checkout and restart Claude Code. To keep starting in `bypassPermissions`, set it in `~/.claude/settings.json` after the install (later runs keep it), or pass `--permission-mode bypassPermissions` for one session.

### 2026-10-03 (prompt budget base frozen)

- `tests/prompt_budget.py --check` compares with its base revision through git; in a clone without that commit (a fresh history, an export without `.git`) it skipped every ratio check. It now falls back to `tests/fixtures/prompt_budget_base.json`, the base's measurement frozen (totals, and per agent description, body, maxTurns and per spawn; the base agent no current agent matches is left out, as `check()` never compares it), so the ratios run there too. `tests/test_prompt_budget.py` checks the fixture against a live measurement when the commit is present and the fallback with a seeded violation. The collector upgrade tests in `tests/test_stack_usage.py` still skip without their commits (README, Contributing). Nothing to rerun.

### 2026-10-03 (Playwright MCP output dir created by the installer)

- install.sh now creates `~/.cache/claude-sandbox/playwright-mcp` (the rendered `--output-dir` of the Playwright entries; parents new to it get 0700, like the session-env hook's `~/.cache/claude-sandbox`, and the folder itself is set to 0700) after applying the files, when an installed agent or the magg catalog names it; `--dry-run` creates nothing. doctor.sh checks every path in an MCP entry's args and reported `[Binaries] ~/.cache/claude-sandbox/playwright-mcp missing` as a FAIL on a fresh install: the entry below assumed the server creates the folder on its first write, and doctor checks before any server has run. doctor's check stays. Tests: `tests/test_playwright_mcp.py` (the path install.sh builds matches the entries) and `tests/install_smoke.sh` §8 (created 0700 under a scratch HOME, doctor quiet about it, nothing under `--dry-run`). Rerun install.sh.

### 2026-10-03 (previous-name compatibility removed)

- The compatibility layer for supreme-coder's previous name is gone. install.sh's `RENAMED` (agent files) and `RENAMED_ENV` (settings knobs) keep only the senior-coder → main-coder and router → blackcat entries, so the mechanism and its smoke tests stay. `bin/claude-ultracode` answers to `claude-ninja`, `claude-supreme` and `claude-ultracode <agent>` only; install.sh no longer notes an old launcher link, and doctor.sh no longer warns about one, about a left-over agent file or about knobs under the previous prefix. The guard no longer adopts a lock or spawn marker written under the previous name, nor maps that spelling to supreme-coder.
- Usage rows recorded before the rename are not aliased. `stack_limits` and `stack_usage.read_rows` read them under the type they were recorded with, a type the stack no longer ships, so they feed no supreme-coder limit (`stack_limits.RENAMED_TYPES`/`renamed_type` and `stack_usage.RENAMED_TYPES` are removed). An env override or live.json state under the previous name no longer carries over, and `tests/derive_*.py` count such transcripts under their recorded type. The frozen fixture `tests/fixtures/sched/graph-4e2da3ce.json` names `dot-claude/agents/supreme-coder.md`.
- Upgrading straight from an install older than the rename: the previous agent file is still pruned as no longer shipped (the backup keeps it), and a shipped knob still at its default is retracted. A knob you tuned under the previous prefix stays in settings.json unread: set its `SUPREME_*` name. An old launcher link in `~/.local/bin` is no longer recognised: remove it. Rerun install.sh and restart Claude Code.

### 2026-10-03 (hero image, CC BY 4.0)

- Hero image replaced: the author's cat photograph edited with OpenAI GPT Image 2.5 Sunburst via Opper; images licensed CC BY 4.0. `lib/assets/` holds the unmodified model output (`blackcat-hero-original.png`, with its C2PA manifest), the resized hero, social preview and avatar, the CC BY 4.0 legal code and the provenance (prompts, settings, hashes); README's License section and NOTICE follow. `lib/assets/` is not installed: nothing to rerun.

### 2026-10-03 (install target: --config-dir, any clone, any user)

- `install.sh --config-dir PATH` (also `--config-dir=PATH`) and `--no-prompt`; precedence `--config-dir` > `CLAUDE_CONFIG_DIR` > `~/.claude`; a banner on every run; a `[y/N]` question on a terminal for a non-default or ambiguous target; unsafe and foreign targets refused (§7, "Install target"). Before, `CLAUDE_CONFIG_DIR` was used as given, unchecked (`CLAUDE_CONFIG_DIR=/` was accepted), and nothing said where the install went except one line in step 1. Runs without a terminal behave as before, apart from the new refusals. `--no-prompt` also makes a changed stack stop instead of asking on `/dev/tty`.
- The script follows a symlink to itself to find the clone (before, a link to `install.sh` in `~/bin` took `~/bin` as the repo). A bash login shell whose `~/.bash_profile` does not source `~/.bashrc` gets a note at step 11. `doctor.sh` warns when the folder it checks is not `~/.claude` and `CLAUDE_CONFIG_DIR` is unset.
- Author-specific paths removed from the tests and `tests/derive_thresholds.py` (the report's project column now strips any `-Users-<name>-` prefix). Intel Macs remain untested (README, Requirements).
- Tests: `tests/test_installer_config_dir.py`; `tests/install_smoke.sh` §19 (precedence, banner, refusals, the question with an injected answer and on a pty when one can be opened, a target and a clone with spaces, a symlinked clone and a symlink to `install.sh`); the §16 pty driver answers the target question first. Nothing to rerun for an existing `~/.claude` install.

### 2026-10-03 (Playwright MCP output out of the working tree)

- The Playwright MCP wrote auto-named output (screenshots and snapshots without a file name, console logs, traces) to `<cwd>/.playwright-mcp/`, so every session left that folder in the project's working tree: with no `--output-dir` (or `PLAYWRIGHT_MCP_OUTPUT_DIR`), 0.0.82 resolves `outputDir` to `path.join(cwd, ".playwright-mcp")` (tmpdir only when cwd is unwritable). The inline entries of browser-operator, frontend-engineer and verifier and the magg catalog entry now pass `--output-dir __HOME__/.cache/claude-sandbox/playwright-mcp` (an absolute path: the server does `path.resolve` with no `~` expansion; the installer renders `__HOME__`; the server creates the directory on first write) and `--file-paths absolute`, so a result names a path the Read tool takes instead of `../../.cache/...`. `~/.cache/claude-sandbox` is the sandbox's only writable cache (`sandbox.filesystem.allowWrite`), so sandboxed Bash can move or clear the files; the read gate does not gate it. Files given an explicit name still resolve against the working directory (`--output-dir` help text), which is why the agents and `browser-automation` keep naming `./.claude-work/<job>/...`. `--headless --isolated` unchanged; `.playwright-mcp/` added to `.gitignore`. Sources: `npx @playwright/mcp@0.0.82 --help` and its `coreBundle.js` (`outputDir()`, `PLAYWRIGHT_MCP_OUTPUT_DIR`), https://github.com/microsoft/playwright-mcp (README, options), read 2026-10-03. Test: `tests/test_playwright_mcp.py`. Rerun install.sh (the magg entry is updated because the manifest recorded the old one) and restart Claude Code; delete old `.playwright-mcp/` folders by hand.

### 2026-10-03 (legacy/be5b940 removed)

- The repo no longer ships `legacy/be5b940/` (old `CLAUDE.md`, `agents/senior-coder.md`, seven skills); it stays in the history from before publication (the 2026-10-03 commit "Remove legacy/be5b940; smoke tests take old-release files from tests/fixtures"; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)). install.sh keeps its generic `legacy/<version>/<rel>` recognition (`legacy_renders`, `template_copy`), which finds nothing while `legacy/` is absent, and the model-ID lint keeps its `legacy/` exception. Upgrade effect, only for an install whose files the manifest does not track (pre-manifest): an unedited untracked `CLAUDE.md` of that release (and a leftover `CLAUDE.md.new`) is now kept instead of moved to the backup, without the "kept" advice (its line similarity to today's rules, 0.385, is under `similar()`'s 0.4), and an untracked old skill file under `--no-prune` is kept with a `.new` render instead of refreshed (with pruning it is replaced and listed). Tracked files, and `senior-coder.md` (removed by name as renamed), behave as before. `tests/install_smoke.sh` takes its old-release files from `tests/fixtures/legacy-release/` and puts them under the scratch repo's `legacy/` only for the CLAUDE.md migration cases; a new case checks an unrecognised old `CLAUDE.md` is kept. Nothing to rerun.

### 2026-10-03 (top-tier coder agent renamed to supreme-coder)

- The top-tier coder agent is now supreme-coder: the agent file (`agents/supreme-coder.md`, `name: supreme-coder`), the guard's `POLICY` rows, fan-out, soft-limit and read-only tables, the limits seed (`turns.`, `soft.agent.`, `hard.agent.supreme-coder`), `sched_model.json`, `agent_effort.json`, every agent body, the rules, skills, docs and tests. Its knobs are `SUPREME_SPAWNERS`, `SUPREME_ONCE_PER_SESSION`, `SUPREME_AFTER_NINJA`, `SUPREME_PENDING_TTL_S`, `SUPREME_IDLE_S`, `SUPREME_LOCK_TTL_S` and the `STACK_{MAXTURNS,SOFTCTX,HARDCTX,SOFT_PROMPT_CTX}_SUPREME_CODER` overrides; the lock and markers in the hook state are `supreme-coder.lock`, `supreme-coder.spawned` and `supreme.mutex`; the launcher is `claude-supreme`. Rules file trimmed by 17 characters to stay inside `tests/prompt_budget.py` (rules <= 0.95 x base). The compatibility layer for the previous name that shipped with it is gone (entry "previous-name compatibility removed"). Rerun install.sh and restart Claude Code.

### 2026-10-03 (BlackCat does small jobs itself)

- BlackCat's `tools` and `BLACKCAT_TOOLS` gain Bash, Write and Edit and drop Grep and Glob (with Bash listed, Claude Code leaves them out on macOS/Linux; `find`/`grep` run through Bash, `tests/lint_agents.py` checks it). The prompt's Decide rule 3 now has a "yourself" class (a few tool calls, no skill or specialist judgement: a look, a small edit the user spelled out, one command or test, git inspection, committing its own edit, the delegation ledger), a stop-and-dispatch rule when such a job grows, and a "Doing it yourself" section (same guards as every agent, Git rules for its edits, AskUserQuestion before destructive steps). Specialist, long, parallel and review work is dispatched as before; the orchestrator gets dependent multi-specialist jobs. The 12-call and 8-dispatch caps count its own work.
- Not granted: WebFetch, WebSearch, Monitor (WebSocket source), NotebookEdit, LSP. The main thread holds browser-operator and the consent path (T1), so blackcat-guard also refuses a BlackCat Bash command that fetches the web (`blackcat_web_command`: the command unquoted and case-folded, split into segments; the command word after keywords and wrappers such as `timeout 10`, `env VAR=x`, `if`, `{` must not be an HTTP client, raw socket tool or `gh` with a forge read; inline HTTP code such as `urllib` or `fetch(` anywhere; a command over 20,000 chars is refused; linear time). Best effort: a script file, an alias, text assembled at run time and `sudo -u user curl` are not seen; git clone/fetch/pull stay allowed (repository files are read like local files); the sandbox network allowlist is the hard limit. The main thread is still not a web-taint node (T3 unchanged: what BlackCat relays into a spawn prompt is not marked). The self-test fails if `BLACKCAT_TOOLS` gains a web or MCP tool or the check misjudges its probe commands. Found by the code review of this change (MEDIUM, CWE-184: the first version reused `WEB_TAINT_CMD_RE`, which misses `timeout 10 curl`, `'curl'`, `CURL`, `{ curl; }`, `gh issue view`, inline urllib; LOW: only the first 20,000 chars were scanned).
- Guards unchanged and now proven for the main thread (`tests/test_blackcat_tools.py`): no-push denies a push or forge write from BlackCat's Bash (also with `STACK_POLICY=off`), its protect scan denies a Bash write to the installed stack; Write/Edit there hit the `Edit(/__CLAUDE_DIR__/...)` deny rules, which hold in `bypassPermissions` and for every file-editing tool (permission-modes.md, permissions.md), backed by the sandbox's denyWrite.
- A `context: fork` skill's agent inherits the main conversation's tools (sub-agents.md, "Available tools"), so under BlackCat it now gets Bash, Write and Edit (it was left with Read, ToolSearch and Skill: §1, bug 8). `/stack-doctor` stays on its UserPromptExpansion hook (sandboxed Bash still cannot read stack.env).
- The main thread stays free for dispatch and relays. (a) `BLACKCAT_MAX_OWN_STEPS=4`: own Read/Bash/Write/Edit calls per prompt; they also count against the 12 steps, never against the 8 dispatches, so even own work done first leaves a full burst of 8 (`test_blackcat_own_work_never_eats_the_dispatch_burst`). ToolSearch, AskUserQuestion and SendMessage are steps outside the sub-cap, so 4 own calls plus a question plus 8 dispatches is 13 and the 8th dispatch is refused: the prompt orders dispatches first. (b) `BLACKCAT_BASH_TIMEOUT_MS=120000`: a foreground BlackCat Bash call asking for a longer timeout, or relying on a raised `BASH_DEFAULT_TIMEOUT_MS`, is refused; `run_in_background: true` passes. (c) The prompt: all Agent calls in one message before its own calls (prompt-only: the hook cannot know dispatches will follow); builds, suites and installs go to `run_in_background` or a specialist, servers and watchers to a specialist. The 120 s dispatch window (`BLACKCAT_DISPATCH_WINDOW_S`) is a further reason to dispatch first: a second dispatch after a 2-minute command would fall outside it.
- What the harness does (docs, not live-tested): BlackCat's children always run in the background (`BLACKCAT_BACKGROUND`), so a foreground Bash on the main thread never stops them; their completion notifications reach the main thread "in a later turn" (sub-agents.md), and messages queued during tool calls are passed on "as soon as those tool calls finish" (interactive-mode.md), so a relay waits at most for the running foreground call, which the cap bounds at 120 s; at its timeout Claude Code moves a foreground command to the background instead of stopping it (tools-reference.md, "Foreground commands that move to the background"; the installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS`). Unverified live: whether task notifications themselves (not typed messages) are delivered between tool calls of a turn or only at turn end, and whether Agent and Bash calls in one message start concurrently.
- doctor.sh probes blackcat-guard with a WebFetch call (a Bash probe is now allowed). Rerun install.sh and restart Claude Code.

### 2026-10-03 (/stack-tree)

- New read-only `bin/stack-tree` and user command `/stack-tree` (§5, "`stack-tree`"): a session's agent tree with each agent's commands as leaves, `--table` for a markdown table of every agent and tool call, `--static` for the designed hierarchy from the agent files. settings.json gets a third UserPromptExpansion group (matcher `stack-tree`, `"__PYTHON3__" -B "__CLAUDE_DIR__/bin/stack-tree" --hook`, timeout 30 s); install.sh stages `bin/stack-tree`, tracks it in the manifest and its `STACK_HOOK_RE` recognises the hook (`/bin/stack-tree" --hook`), so a re-install replaces it instead of keeping a second copy; doctor.sh checks the skill and the hook are wired. Tests: `tests/test_stack_tree.py`, `tests/test_override_agent.py::test_skills_are_user_only_and_wired`. Rerun install.sh and restart Claude Code.

### 2026-10-03 (/stack-doctor runs from a hook)

- `/stack-doctor` no longer forks claude-code-guide, which had no Bash under BlackCat (§1, bug 8). settings.json gets a second UserPromptExpansion group (matcher `stack-doctor`, `/bin/bash "__CLAUDE_DIR__/bin/doctor.sh" --hook`, timeout 180 s); `doctor.sh --hook` runs the full check outside the Bash sandbox, stops it after `STACK_DOCTOR_HOOK_BUDGET` seconds (default 150; stock macOS has no timeout(1), and Claude Code drops a timed-out hook's output) and exits 2 with the summary as the block reason; a run that did not reach its last line is a FAIL. install.sh's `STACK_HOOK_RE` recognises the hook (`/bin/doctor.sh" --hook`), so a re-install replaces it instead of keeping a second copy. `skills/stack-doctor` drops `context`, `agent`, `background` and `allowed-tools` and only tells the model the hook did not run. doctor.sh checks that the skill and the hook are wired. Tests: `tests/test_stack_doctor.py`, `tests/test_override_agent.py::test_skills_are_user_only_and_wired`. Rerun install.sh and restart Claude Code.

### 2026-10-03 (override runs are no longer learned from)

- Security audit of the first `/override-agent` commit (2026-10-03, "/agent-override and /agent-reset: per-session model override for delegated agent types"; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)), MEDIUM: an `/override-agent` run (e.g. scout on haiku) fed `soft.agent.scout`, `turns.scout`, the pool proposals and the scheduler refit that later sessions on scout's own model use, against the "this session only" scope. The collector now writes schema 3 rows to `usage/runs3.csv` with the segment's `model`; `stack_limits.py`, `stack_sched_refresh.py` and `stack budget` skip an agent row whose model is not its frontmatter one and count what they skipped (§5, "Session model overrides" and "Usage collector"). `runs*.csv` and `runs2*.csv` are read as before and never written again. Rerun install.sh; a session collected by the old code is read again from the start the next time its collector runs.
- Audit follow-up, MEDIUM: a collector started before the install kept the old code and wrote model-less rows for override runs typed after it. The next SessionStart or SubagentStart now stops a running older-schema collector (SIGTERM after the checks in §5, "Upgrade hand-off") and a successor reads the session again as schema 3 (tests: `test_upgrade_hands_off_from_an_older_collector` runs the real schema 2 collector from `6a736c6`; `test_handoff_signals_only_a_running_older_collector_of_this_session`; `test_a_successor_waits_for_the_lock_and_then_runs`). Its audit (MEDIUM): the stopped collector's mid-session session row stood as a whole session when the successor idled out; such stale session rows are now left out (`test_a_handoff_session_row_is_not_learned_as_a_whole_session`, `test_a_session_row_older_than_its_sessions_rows_is_not_learned`). The model IDs of the usage, limits and budget tests sit on module-level constant lines, which `tests/lint_agents.py` allows (`MODEL_ID_CONST`).

### 2026-10-03 (scheduler policy back to report)

- `STACK_SCHED_POLICY` defaults to `report` again (`stack_limits.SCHED_POLICY_DEFAULT`, `stack_sched.soft_values`); `fresh_fixer` is opt-in. A session keeps the policy of its snapshot. The default enters the regime hash, so sessions without the knob start a new regime: rows of the old one count as provisional evidence until the new regime has support.
- Tests: the default gives no advice, `fresh_fixer` advises, a mid-session env change does not reach the session; the MCP caps are pinned as fixed guards (T1b); support-rule boundaries (T6b).

### 2026-10-03 (/override-agent reset, FIFO fix)

- `/reset-agent` is now the subcommand `/override-agent reset <agent|all>` (beside `list`). The effort stays display-only (the user's decision: no agent variants).
- Security audit of the first `/override-agent` commit (LOW): a FIFO at the override state path hung the PreToolUse(Agent) hook until its timeout. The state and log files are now opened with `O_NONBLOCK` and refused unless `S_ISREG` (test: `test_a_fifo_at_the_state_path_does_not_hang_the_agent_hook`).

### 2026-10-03 (/override-agent, built-in effort table)

- The commands are now `/override-agent <agent> <model>`, `/override-agent list` and `/reset-agent <agent|all>`. The old `/agent-override` and `/agent-reset` and their effort argument are gone. The effort comes from `hooks/agent_effort.json` (initial defaults, rule v1), clamped to the model; it is recorded and shown, not applied (§5, "Session model overrides").
- Not built: enforcing the effort through per-(agent, model) agent definition variants, which install.sh would render statically (frontmatter `model` + `effort` from the table) with the guard resolving `<agent>@<model>` to `<agent>`. That means up to 220 more agent files in the listing every Agent caller sees. Every guard keyed by agent type would also need one alias function: spawn rows and allowlists, copy rules, READONLY_TYPES (no-push read-only Bash), fan-out by type, supreme-coder and browser spawners, web taint, MCP and turn caps, the limits snapshot (turns, hard and soft per type), read_gate and web_caps exemptions, ledger labels, stack_usage and the scheduler model, and lint_agents. A missed site there weakens a guard, and the result can only be checked in a live session. Decided later the same day: no agent variants (the user's decision; entry above).

### 2026-10-03 (session model overrides)

- `/agent-override <agent> <model|-> [<effort|->]`, `/agent-override list`, `/agent-reset <agent|all>` (renamed the same day; above): per-session model override for delegated agents, set only by the user's typed command (UserPromptExpansion hook), applied by the guard's Agent rewrite; effort recorded, not enforced (§5, "Session model overrides"). Rerun install.sh and restart Claude Code.

### 2026-10-03 (tools venv)

- install.sh step 2 also syncs `~/.claude/venvs/tools` from `requirements/tools.txt` (hash-locked, Python 3.13, macOS arm64 wheels, same 7-day cooldown as sci): pytest, numpy, pandas, httpx, mcp, pillow, neural-memory, i.e. every third-party import of `bin/`, `mcp/`, `hooks/stack_sched_refresh.py` and `tests/`. `claude-agent-sdk==0.2.163` (stack_sdk.py, one importorskip test) is left out until it clears the cooldown. Extras such as a future Bayesian stack go in their own lock (`requirements/README.md`). doctor.sh checks the venv's imports. Rerun install.sh.

### 2026-10-03 (read gate)

- New `hooks/read_gate.py` (PreToolUse `Read|Grep|Glob|Bash`): the first read of build output, dependency dirs, large data, media or binaries is refused with a cheaper alternative; the identical retry passes (§5, "Read gate"). One line in the global rules. Rerun install.sh.

### 2026-10-03 (auto-compact window 900K)

- `autoCompactWindow` 400000 → 900000 in `dot-claude/settings.json` (the single source): sessions on the 5.5 models' native 1M window compact at ~900K instead of 400K (Claude Code's default would be ~967K). The status line's bar, `/stack-doctor` and the installer's notes follow it. Rerun install.sh.

### 2026-10-02 (usage collector, scheduler model refresh)

- `hooks/stack_usage.py`: per-session background collector (SessionStart and SubagentStart `start`, SessionEnd `end`) writing segment rows to `usage/runs.csv`; `hooks/stack_sched_refresh.py` refits the active `sched_model.json` at the collector's exit. See section 5, "Usage collector and scheduler model refresh".
- `stack_sched.py`: prefers the active model.
- `agent_guard.py`: the three-day prune skips `usage/`.
- install.sh: installs `stack_usage.py`, `stack_sched.py`, `stack_sched_refresh.py`, `sched_model.json`, and `derive_sched_model.py` / `derive_thresholds.py` (from `tests/`) into `hooks/`. It treats `stack_usage.py` hook entries as the stack's when merging settings.json and warms the refit's uv cache.
- `/stack-doctor` gets one usage line.

### 2026-10-02 (soft token limits, maxTurns from data)

- `agent_guard.py`: soft token limits per agent segment and per human prompt (section 5, "Soft token limits"); `STACK_SOFT_LIMIT_SCALE`. Fix: a BlackCat tool call in a task notification's turn (its own prompt id, no UserPromptSubmit) restarted the hard prompt budget's window; it no longer does once a human prompt is on record.
- maxTurns: claude-code-engineer 150, coder 170, main-coder 350 (section 3); the verifier routes build work to a builder or to dispatches of about 90 tool calls or fewer.
- `tests/derive_thresholds.py`: the derivation, recomputable.
- Prompt budget: bodies gate 0.85 → 0.867 (the verifier line, measured × 1.02).

### 2026-10-02 (Q7: Agent SDK)

- `bin/stack_sdk.py` (installed, loaded by nothing; PEP 723, `claude-agent-sdk==0.2.163`): `options()` builds a plain `ClaudeAgentOptions` from the installed files (`setting_sources` user/project/local, the `claude_code` preset with `exclude_dynamic_sections`, `--agent`), `run()` returns the parsed report, cost, per-model and per-subagent usage and the ledger path; `parse_report()` reads the clean-finish line, the STATUS block and the JSON form.
- `STACK_REPORT_FORMAT=json` (above); the guard's SessionStart matcher is `startup|resume|clear|compact|fork` so the line survives `/clear` and compaction (no output when unset).
- Hooks under the SDK and `claude -p`: no TTY dependence (hooks always run without a controlling terminal); `tests/test_sdk_integration.py` runs them with SDK-shaped events and environment. Cache order checked: no hook writes a system prompt or rewrites earlier context; the SubagentStart line sits in the first user message and is kept.
- Reference: `skills/claude-code-extensions/references/agent-sdk.md`; cost probe for the user: `tests/sdk_smoke.py` (real API calls; not run in the build sandbox).

### 2026-09-29 (security rounds 3 and 4, supreme-coder plan flow)

The 2026-09-29 commits of security rounds 3 and 4, two for magg, one for the docs and the one that added this entry; see the commit history in [PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md).

- Without a terminal on stdin/stderr the supply question goes to `/dev/tty`; with no terminal at all a changed stack stops with exit 1 unless `--yes` (R4-1).
- A failed session-env hook exits 2 with a hook error, is recorded in `session-env.json`, and shows in the status line and `doctor.sh` (R4-2).
- Round-4 residuals recorded (taint gaps, `SUPREME_AFTER_NINJA` order only, a session started in `/tmp`, live checks open).

- Web taint follows reports, messages and spawn prompts (R3-T3-RELAY).
- Caches and the git credential reset moved to a SessionStart `CLAUDE_ENV_FILE` for sandboxed Bash only; `allowWrite` is `~/.cache/claude-sandbox`; an upgrade retracts the old settings (R3-CACHES, R3-GITENV).
- The supply diff covers everything shipped and asks on a terminal (`--yes`) (R3-SUPPLY).
- The guard state dir in the sandbox and `Edit` denies renders from `XDG_STATE_HOME` (R3-STATE).
- `--restore` keeps the current entry where it skips a link (R3-RESTORE-LINK); `--dry-run` refuses like the real run (R3-DRYRUN); file links inside a symlinked dir are kept (R3-WTL-INNER).
- `doctor.sh` reports GitHub credentials agents could use, by presence only (R3-N1-P2); least-privilege GitHub setup documented; `~/.config/git/credentials` denied.
- Read-only reviewers treat a project under a temp dir as the project (R3-INFO).
- magg `ros_*`, `qiskit_*`, `docspace_*` and the ten domain prefixes ask; every catalog prefix has exactly one allow or ask rule.
- supreme-coder only after a finished ninja-coder (`SUPREME_AFTER_NINJA`); a plan's supreme-coder step runs only after its ninja-coder step failed (planner, plan-reviewer, BlackCat, orchestrator prompts; section 4).
- N-MANAGED: managed settings pin the hook entries, not the hook's code, unless the root-owned copy is installed (documented).
- T1 URL policy weighed and not built (residual risks).

### 2026-09-29 (security round 2)

- Also: a link inside a symlinked scope dir is never written through; brace expansions past the cap never fail open.

- Installer: manifest paths are checked against the stack's scope, symlinked `agents/`, `skills/` (and the other scope dirs) are never pruned and need `--write-through-links` (new flag) to be written through, per-skill symlinks are replaced by the stack's skill again, whole scope dirs named in the manifest are refused, the backup root must be a private real directory, the work dir lives inside it, a config change during the run aborts before anything is written, restored links that leave the config dir need `--force`, the removal list names every hook entry, the LSP installs are pinned with `--ignore-scripts`, the MCP prefetch warms the servers' own cache, and your own MCP servers and hooks that run package runners on the sandbox cache are named (section 7).
- Settings: `sandbox.failIfUnavailable`, tool caches moved out of the sandbox's writable set, git credential helpers off, token env vars denied to sandboxed commands, `magg_enable_server`/duckdb/jupyter tools ask; duckdb runs in memory with extension autoload and config changes locked.
- Guard: protected-path checks expand `$HOME`, `$CLAUDE_CONFIG_DIR`, assigned variables, braces, globs, `cd` and `CDPATH` forms, and see output options (`curl -o`, `wget -O`, `sort -o`, `-o/--output` generally), `patch`, `sponge`, awk redirects and `git clone/init`; `$VAR/bin`-style project paths are no longer denied; `git -C <config dir>` tree-rewriting subcommands (now also bisect, submodule, merge-file, worktree add, archive/format-patch output) are denied; credential reads, forge writes over curl/wget/httpie and `install.sh`/`install_state.py` runs are denied; read-only reviewers may run syntax-only checks but not write-then-run scratch code; any MCP tool outside a non-web list marks the agent as web-tainted.

### 2026-09-29 (security and installer)

- Security findings C1–C9, T1–T3 and P3 fixed (guard, settings, MCP servers, installer); section 7 lists the residual risks.
- The installer stages, validates, backs up and then applies. It prunes by default (`--no-prune` opts out) and supports `--dry-run`, `--restore [DIR]` and `--print-managed-settings` (section 7).
- Plugin duplicates of synced skills and `mcp-server-dev` are disabled by default (`--keep-plugin-duplicates`).
- `skillListingBudgetFraction` 0.0156 (was 0.012): every skill is listed with its description, and the budget also holds plugin, bundled and claude.ai skills (stack ~31K + ~14.2K measured, plus 3.5%; rationale in `tests/prompt_budget.py` SKILL_BUDGET). Cost-only knob. `tests/lint_agents.py`, `doctor.sh` and the smoke test read it from `settings.json`.
- Read-only reviewers may also run `claude --version`, `claude mcp list/get`, `claude plugin list` and the audit scanners (`gitleaks`, `trufflehog`, `semgrep`, `osv-scanner`, `pip-audit`, `uv audit`, `npm audit`, `cargo audit`/`deny`, `trivy`).

### 2026-09-29

- Desktop hang fixed: BlackCat's children always run in the background, and the hook drops `run_in_background: false`.
- BlackCat always gives a visible reply and asks clarifying questions. The recommended main-thread effort is `medium`.
- Models: only Opus 5.5 and Sonnet 5.5 are used, with no Haiku.
  - supreme-coder moved from Fable to Opus 5.5.
  - doc-specialist moved to Sonnet 5.5.
- Effort recalibrated for 5.5:
  - lowered from `xhigh` to `high`: orchestrator, plan-reviewer, code-reviewer, quantum-engineer;
  - lowered from `high` to `medium`: motion-designer, cg-artist.
- maxTurns set per task type (section 3).
- Caps:
  - BlackCat: 8 dispatches, 12 steps, 120 s window;
  - running children per agent: orchestrator 32, main-coder and supreme-coder 6, ninja-coder 5, researcher 4, planner 8, everyone else 3;
  - `CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 33.
- supreme-coder: only the orchestrator spawns it, once per session. BlackCat, main-coder, ninja-coder and the ML platform engineers return `NEXT: supreme-coder` instead of spawning it.
- The installer removes `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS` and `CLAUDE_CODE_FORK_SUBAGENT`; `/stack-doctor` warns about them.
- Tests:
  - new: BlackCat foreground drop, shipped spawn defaults, supreme-coder orchestrator-only and once per session;
  - the mechanics tests pin their former caps as a baseline.

The full entry was in the Changelog section of the README as of the 2026-10-02 commit "Skills listed, not
name-only" (that README revision is not shipped; see the commit history in
[PREVIOUS_GIT_COMMITS.md](PREVIOUS_GIT_COMMITS.md)).
