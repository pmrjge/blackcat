# HANDOFF_STATE: claude-agent-stack, current state as of 2026-10-08 23:06 (main `47dce9f4`; C10 green; reinstalled)

One coherent state; it replaces every earlier version of this file (the 2026-10-05 stop, the per-branch "as of" notes and
the obsolete cells are gone; the 20:22 update adds Bayes 3a, `shrink-on`, `bayes-3a-fixes` and the measurements; the 23:06
update records both merges, the C10 on main `47dce9f4`, the reinstall and the live checks). Supersedes
`claude_info/HANDOFF_FULL.md` §0, §6 and §7 where they differ; HANDOFF_FULL stays the reference for R1/R2, the Stage-4 lever
table, the L1 review findings and older decisions. The next session starts with `hand_off/NEXT_SESSION_PROMPT.md`.

Key: **[v]** read in a file or git when this was written · **[r]** from a report or a plan, not re-run · **[unverified]**
nobody checked it.

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout, repo of record; layout: `dot-config/{dot-claude,dot-equilibrium}`
since A9) · **H** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb`
(its git-ignored `.claude-work/` holds the job files; its branch `golden/handoff-plan-continuation-c09473` is superseded, section 3)
· **W** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/project-redundancy-review-21d544` (branch
`golden/work-order-continuation-b06255` on `47dce9f4`: this hand-off, `c4bbedc7` cherry-picked and updated) · **R**
`/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728` (older worktrees, the wiki clone) · ledger
`/Users/pmrj/.local/state/claude-agent-stack/8ad965da-ee69-47f6-8e8b-40a9d258455f/delegations.md`.

## 1. State

- 2026-10-09: the Codex implementation was removed on branch `remove-codex` (user decision; awaits its C10 and the ff).
- **main = `47dce9f4`** [v] (`git -C M log --oneline -8 main`, 23:06): `shrink-on` (`c6ad573b`, `1a8a8481`, `a0791669`) and
  `bayes-3a-fixes` (`f914fd8d`, `47dce9f4`) ff-merged by the user on Bayes 3a (`91fd17d2`, 5 commits on `d6046693`). Below it
  `d6046693` (hand_off) on `52c1abcc` (`limits-raise`). Merged on main earlier (the user ran every ff merge): audit-fixes,
  eq-runtime-2 (A7: H5 removed; A8: E7 cell pass), docs-reorg, the jsonschema fix, hs-update-1007b, hs-next, and **dot-config**
  (A9 repository move: the Claude and Equilibrium trees live under `dot-config/`; `extract_src` `parents[5]` re-pinned;
  the WALL lookup depth rule; the instructor patch is applied on main),
  post-merge (`b2ee53e8` + `ff8c3392`).
- **C10 on main `47dce9f4`: GREEN** [v: `H/.claude-work/c10/c10-bayes-3a-fixes-47dce9f4.summary`, user terminal 2026-10-08
  21:11-22:05]: `failed_ids` empty (0 failed; the 7 known environment ids all pass outside the sandbox); install_smoke 282 passed /
  1 failed (the known `openpty` check); every other gate exit 0: lint_agents, prompt_budget, agent_guard and stack_progress
  self-tests, `bash -n` (311 tracked `*.sh`), instructor 77, image_studio 125, eq-wall 102, eq mutants 39/39 killed,
  equilibrium_paths, moved_paths 109, pool_sha, wiki_check, hand_off 40, eq_harness 639, pytest chunks
  2164 + 1073 + 2700 + 1432 passed. The hand-off (`c4bbedc7` on `golden/handoff-plan-continuation-c09473`) was cherry-picked onto
  `47dce9f4` as branch `golden/work-order-continuation-b06255` (W), which awaits the user's ff.
- **Programs started 2026-10-08 23:04** (another orchestrator; Bayes tracker `H/.claude-work/bayes/plan.md` "STAGE 3b-4
  EXECUTION"): branches `fix/guard-timeout`, `sdk/1`, `bayes/3b`, `bayes/4`, each at `47dce9f4` with a worktree and no commits yet
  [v 23:06, `git -C M worktree list`]; Bayes WP2 output goes to `M/.claude-work/bayes/wp2/` [r]. Work-order tracker:
  `H/.claude-work/work-order-1008/plan.md`.
- **Bayes 3a, merged** [v]: `fef81801` WP0a (B1 v2 fit frozen as the sanitized fixture `tests/fixtures/bayes/b1v2/`), `0e3e0ac8`
  WP0b/WP1a (decision record, design v3 `docs/BAYES.md`, changelog), `e05e5542` WP1c (13 review findings applied), `5a12485a` WP3a
  (stdlib Bayes tier in `stack_limits`, shadow by default, `hooks/stack_bayes_grid.py`), `91fd17d2` review fixes (p_hit zero gap,
  shadow isolation, grid load by path, scan bound / RecursionError, `hard.agent` T). It was merged on a targeted-test pass; its C10
  (`H/.claude-work/c10/c10-bayes3a-91fd17d2.summary`) [v] has 12 new failed ids: `install.sh` did not stage
  `hooks/stack_bayes_grid.py` (10 test_redundancy failures; the installed grid tier would be silently off), lint_agents model-id
  findings in the b1v2 CSVs, the venv-lock test (scipy import). **Lesson: a targeted-test pass is not a C10; run the full C10 on a
  branch tip before calling it merge-ready.**
- **`bayes-3a-fixes`, merged** [v] (`f914fd8d`, `47dce9f4`) fixes those regressions: install.sh stages `hooks/stack_bayes_grid.py`
  (so WP3c's staging part is done), a lint_agents path exemption for `tests/fixtures/bayes/b1v2` (fixture byte-unchanged; the pin
  covers dotfiles too), the scipy import moved to an importorskip test. The C10 on main `47dce9f4` covers it (green). The B1
  backtest REJECT is expected until WP2/WP5 [r]. Remaining Bayes work: WP2, 3b, 3c (rest), 4 per `H/.claude-work/bayes/plan.md`.
- **`shrink-on`, merged** [v for the commits, r for the semantics] (`c6ad573b` output_shrink, `1a8a8481` stack-run, `a0791669`
  review fixes). Hook mode `default` (`STACK_OUTPUT_SHRINK` unset) cuts only successful non-view Bash results over 8000
  chars; Read and view commands stay shadow (decided and logged, unchanged); explicit `on` cuts every class, but failed, background
  and persisted results stay whole; `shadow` and `off` are kill switches (an unknown value acts as shadow). The digest goes back as
  `updatedToolOutput` = `dict(resp, stdout=digest, stderr='')`: verified statically in the Claude Code 2.1.287 binary and **seen
  live** after the reinstall [v 23:05: `seq 1 3000` came back as a digest, section 1 live checks]. `bin/stack-run` runs a command with its full output in a 0600 log under `.claude-work/runs`
  (first 256 MiB; pruned after 7 days or past 1 GiB), prints one line `PASS|FAIL rc secs lines log=...` and the decisive lines only
  on FAIL; no masker means no log. `output_shrink.py report` prints applied vs would-cut per tool and mode. Reviews: security-auditor
  S1 HIGH (`STACK_HOOKS_DIR` exec var for read-only agents) and S2-S4 MEDIUM, code-reviewer R1-R3, all fixed with proofs [r];
  mutants 168/168 killed (`H/.claude-work/shrink-on/mutate-rebased-a0791669.out`) [v]. C10 on the pre-rebase tip `51dcd288`
  (`c10-shrink-on-51dcd288.summary`) [v]: 0 new failed ids, install_smoke 282/1 (openpty); the rebased tip is covered by the
  green C10 on main `47dce9f4`. The rules file is exactly at the prompt_budget gate (11588 chars [v]): any more rules text
  needs a gate or trim decision.
- **`limits-raise`, merged** (USER request 2026-10-08, "colliding with limits"; the soft limit of 80M had been hit):
  `soft.prompt.orchestrator` seed/floor/ceiling 80M/80M/100M -> **140M/140M/140M**; `hard.prompt` 100M/50M/250M -> **300M/300M/300M**.
  Exact pins, no headroom (USER choice). `soft.prompt` 33M and `hard.session` (1.92B seed / 2.5B ceiling) unchanged. F2 (USER: yes): for
  `hard.*` an env override can only LOWER the cap on every path without a usable snapshot (tampered or unwritable snapshot, event
  without session id, the guard's built-in constants when `stack_limits.py` is unusable); `turns.*` still ignore env there.
  Learned values are clamped into the new [floor, ceiling] on read, so no limits reset is needed. Live: `hard.prompt` 300M,
  `soft.prompt.orchestrator` 140M [v 23:05, `stack_limits.py show '*prompt*'`]. Two cosmetic points
  left unapplied: `Limits.where` wording when the seed is None; `bin/stack-budget` shows raw seeds on a fallback.
- **C10 on main `d6046693`**: done by the user 2026-10-08, green modulo environment (section 6). The 7 known environment ids are in
  `resume-770728/.claude-work/c10/c10-eqcli-321f037.failed_ids` (test_limits_guard T10, test_stack_tree x3, test_stack_usage x3).
- **Installed stack = `47dce9f4` = main** [v 23:05: `commit` in `~/.claude/.stack-manifest.json` (written 22:44) is
  `47dce9f4a4a6…`]: the user reinstalled after the green C10.
  output_shrink now cuts by default (kill switch `STACK_OUTPUT_SHRINK=shadow` or `off`).
- **Live checks, 2026-10-08 23:05** (from an agent Bash sandbox in W):
  - [v] `stack_limits.py show '*prompt*'`: `hard.prompt` 300M, `soft.prompt` 33M, `soft.prompt.orchestrator` 140M (live v22,
    bayes shadow).
  - [v] output_shrink: `seq 1 3000` (13,892 chars, 3,000 lines) came back as a digest (312 decisive lines plus the spill path under
    `M/.claude-work/output-shrink/spill/`); `output_shrink.py report M` shows `Bash/default` 67 rows, 110,984 chars cut (1,036 rows,
    2 sessions). Note: a bare `report` run from a linked worktree (W) printed 0 rows, because the hook logs to
    `M/.claude-work/output-shrink/log.jsonl`; pass M (or the log path).
  - **failed in the sandbox** `bash ~/.claude/bin/doctor.sh` (rc 0, 109 lines): 2 FAIL lines, both sandbox artefacts as far as
    seen: "missing `~/.claude/stack.env`" (the agent sandbox denies reading it) and "state dir not writable" (EPERM on
    `~/.local/state/claude-agent-stack`); WARNs: MCP servers "not registered" (`~/.claude.json` is read-denied), image-studio
    catalogs 403 through the proxy, container service not running, eq-container "unresolved pin" (known). The rest ok (claude
    2.1.287, hook launcher smoke, agent_guard self-test, limits live v22). A clean doctor needs the user's terminal [unverified].
- **Measurements, 2026-10-08** (MEASURED unless marked; `H/.claude-work/output-shrink-on/A_numbers.md` and
  `H/.claude-work/deterministic-offload/` [v]): the "85%" output-shrink saving cannot be sourced (the old MEASURE notes are gone);
  most likely it is the per-cut shrink (median 90.8%), not a total saving [inference]. Shadow log (384 rows, 1 session): would-cut
  11.2% of subagent tokens at the current thresholds (an upper bound), Bash only 5.0%. Read cuts are risky: 2 of 8 cut files were
  re-read in pages by the same agent; judge the paging cost before switching Read to `on`. Decision 6's "4 of 5 sessions" is
  untestable until the log holds 5 or more sessions. Deterministic-offload study (7.66B tokens, 20 sessions, 909 subagent runs):
  whole deterministic agent runs are 0.43% of tokens; deterministic call chains inside judgment agents hold 34.5%; the realistic
  saving is 10.3% (CI 8.2-11.7%) through stack-run style wrappers; top patterns (points of all tokens) pytest 3.31, Python scripts
  1.63, sleep/until poll loops 0.91, ruff 0.74. Next lever: a rule/habit to run tests, scripts and ruff through `bin/stack-run` and
  to replace poll loops with one background wait plus its notification (possible follow-up, section 4).
- Wiki: pushed to `pmrjge/blackcat.wiki` (`e0d2294` on `master`) [r]; the remote head is **unverified** (`ls-remote` blocked in
  the sandbox). A wiki `docs-reorg` branch awaits the user's merge.

Environment notes: an agent's Bash sandbox writes its own worktree, M and `$TMPDIR`, not H (a `touch` in H failed with EPERM,
23:06 [v]; the Write and Edit tools did write H's `.claude-work`); agents cannot merge into main; the shared uv cache
`/tmp/claude-501/uvcache` is corrupt (`uv run --no-cache`); harness runs need `EQ_AGENTS_DIR` and `EQ_CONTAINER_DIR`; BSD
`split` has no `-n l/4`; about 130 tests fail on paths when run under `.claude-work` (run from a `$TMPDIR` clone); the
verifier's read-only hook refuses harness, stack_progress and install runs (use a coder); BlackCat has a 24-tool-call cap per
prompt and the orchestrator a soft token limit (140M, live since the reinstall), so checkpoint the `plan.md` files. **A full C10
runs only from the user's terminal**: the agent sandbox refuses to create the `tools/instructor` directories in a clone. The
scripts are in `H/.claude-work/c10/`; use **`c10-ref.sh <ref>`** from now on (a copy of `c10-bayes-3a-fixes.sh`: output
`c10-<ref, / as ->-<sha8>.summary`, plus an SDK step `uv run --python 3.13 --with pytest --with claude-agent-sdk==0.2.163 pytest -q
tests/test_sdk_integration.py`; expects install_smoke 282/1; about 55 min; not yet run). Older ones: `c10-main-d6046693.sh`,
`-rerun.sh`, `c10-bayes3a.sh`, `c10-shrink-on.sh`, `c10-bayes-3a-fixes.sh`. They use the short clone `/tmp/c10s` and set
`UV_CACHE_DIR`. Each deletes and re-clones
`/tmp/c10s`: never run two at once, and launch from `cd ~`, never from inside `/tmp/c10s`. Worktrees made in the sandbox lack
`tools/instructor` (unstaged deletions): commit explicit paths only.

## 2. Decisions that stand (USER; do not re-ask)

1. Isolation backend: Apple `container` 1.5.0; Docker dropped. The user runs c0 (whether it ran: unverified; the c0 runbook is
   `hand_off/RUNBOOK_c0.md`).
2. Images: distroless (USER 2026-10-06, `lib/eq-container/DESIGN_DISTROLESS.md`): static GNU bash 5.3 + patches 001-020 from the
   GPG-signed source in a pinned Alpine builder stage (key `7C0135FB088AAF6C66C650B9BB5869F064EA74AB` enforced); no perl (the
   in-repo shim answers only `check_lean.sh`'s timeout wrapper); CP/CR on distroless cc + the glibc python-build-standalone
   Python; the Debian `full` image and `STACK_EQ_CONTAINER_SET=full` removed; Rust and Haskell deferred (profiles exit 10); node,
   julia, jvm on distroless cc, go on scratch; jq 1.8.2 static, busybox musl, uv musl 0.12.22; Scala 3 from the release
   tarball; MongoDB and PostgreSQL out. No Debian, apt or dpkg in any final image or build path; every final image is FROM the
   digest-pinned `gcr.io/distroless/cc-debian13` or scratch. The earlier Debian-package record is superseded.
3. Oracle residuals (HANDOFF_FULL 6.1) and 6.10 deferred; Stage 3 D1-D5 need the user's approval
   (`resume-770728/.claude-work/stage3/DEFERRED.md`).
4. `mcp-server-craft` stays retired (`e045482`); do not restore.
5. Plugin autoUpdate for claude-plugins-official: keep on.
6. Stage 4 build threshold: 3% pooled, 2% per class, 4 of 5 sessions.
7. SendMessage-resume rule: restrict. Subagent cache TTL: keep the default. `omitClaudeMd`: measure offline first.
8. L10 side commit: yes (merged).
9. ONE_TREE default: archive unique-commit rows as git bundles; dry-run only; never `--apply` by an agent.
10. A4 paid probe approved (one call, <= $0.25); logged-in or paid `claude` steps are user steps.
11. T/S worktree loss (2026-10-05): re-derive, no recovery.
12. Nobody but the user removes worktrees or branches (agents list them). Hand-made worktrees go under H's `.claude-work` (or
    `M/.claude-work/worktrees/<name>`); harness `isolation: "worktree"` worktrees stay in `M/.claude/worktrees`.
13. The orchestrator has `Bash` (merged; effective after the reinstall).
14. 2026-10-07: H5 leaves the pre-registration (`dot-config/dot-equilibrium/COMPARE_eq.md` section 12 A7). 2026-10-07: `eq_check.sh`
    E7 gets a cell-pass rule (A8). The run plan had reserved A9 (pilot) and A10 (confirmation) for the calibration amendments; COMPARE_eq
    section 12 A9 is now the repository-move record, so the run plan's ids need re-checking when they are applied [unverified].
15. 2026-10-08: orchestrator soft prompt 140M, `hard.prompt` 300M, exact pins; F2 yes (`limits-raise`, section 1).
16. 2026-10-08 (`shrink-on`): no masker means no log; the rules get only a short clause (the rules file is at the prompt_budget
    gate, no headroom); explicit `on` keeps the success gate.

Standing constraints: never push, no forge writes; agents never run `install.sh`; no paid runs without consent; no Haiku;
security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent definitions' tool lists)
get security-auditor + code-reviewer before merge; own worktree only; serialize agent_guard.py / settings.json / install.sh /
blackcat.md; uv for Python; C10 on main after every merge, and a full C10 on a branch tip before calling it merge-ready (a
targeted-test pass is not a C10). Agent Bash sandboxes write only their own worktree, `$TMPDIR` and M;
no `claude` login inside them. `lib/eq-wall` and `tools/instructor` are protected: agents do not edit them.

## 3. Not merged / awaiting the user

| item | state |
|---|---|
| `golden/work-order-continuation-b06255` (W) | this hand-off on `47dce9f4` (`c4bbedc7` cherry-picked, then updated); ff-able; the user ff-merges it |
| `golden/handoff-plan-continuation-c09473` `c4bbedc7` | **superseded** by `golden/work-order-continuation-b06255`; not to be merged; the user deletes it |
| `fix/guard-timeout`, `sdk/1`, `bayes/3b`, `bayes/4` | started 2026-10-08 23:04 at `47dce9f4`, no commits yet [v 23:06]; merge order in section 9 |
| scratch worktrees, rescue ref | `/private/tmp/claude-501/so-base-shrinkon`, `so-work-shrinkon`, `so-tip-shrinkon`, `so-fix-shrinkon`; `H/.claude-work/wt-bayes-3a`, `wt-shrink-on`, `wt-bayes-3a-fixes`; `refs/rescue/shrink-on-51dcd288`: both merges are done, so the user can remove them now |
| `s4-l7-l10` | "Minimum first" + A/B test; patch in the rescue folder |
| `worktree-agent-a06763fbda9c482d4` | cache-stable prefix + an untracked test |
| `worktree-agent-a08001452f6ef3994` | installer skips existing CLI tools |
| `worktree-agent-ae67658dcd0599872` | drop Conductor/Nimbalyst/Zed/JetBrains host content |
| superseded `rescue/*`, `worktree-agent-*` branches, about 115 worktrees | run `just worktree-audit`; the user removes. `RESET_TO_MAIN.sh --archive`/`--apply` are the user's (dry run done on `8912496`: rc 0, nothing changed; run it again first) |

Known loss: worktrees T and S (2026-10-05, cause unknown). The rescue folder `H/.claude-work/lost-features/rescue/` (see
`MANIFEST.md`; git-ignored, so copy it outside the worktree before any removal) holds what was recovered.

## 4. Left to do

| # | task | state |
|---|---|---|
| 19 | ff `shrink-on`, then `bayes-3a-fixes`; one C10 on main; reinstall | **done 2026-10-08** [v]: both merged (main `47dce9f4`); C10 on main GREEN (`c10-bayes-3a-fixes-47dce9f4.summary`: 0 failed ids, install_smoke 282/1 openpty); the manifest at `47dce9f4`; hand-off cherry-picked onto main as `golden/work-order-continuation-b06255` (section 1) |
| 1 | Reinstall and C10 on main `d6046693` | **done 2026-10-08, GREEN modulo environment** [r] (user terminal; details in section 6). Optional follow-up, main-coder: default `UV_CACHE_DIR` in `_run_install` (`tests/test_install_state.py:501-511`) and in the smoke harness. A re-run needs the user's terminal, a short clone path (`/tmp/c10s`) and `UV_CACHE_DIR` set (the agent sandbox refuses the `tools/instructor` directories) |
| 3 | Programs (section 9), in the merge order | Bayes 3a and its fixes merged; started 23:04: T-guard-timeout (#20), SDK-1 (`sdk/1`), Bayes WP2, WP4 (`bayes/4`), 3b (`bayes/3b`); 3c waits for the guard merge |
| 20 | T-guard-timeout (pre-existing, already at `d6046693`): `timeout 5 cp x <cfg>/hooks/f` passes agent_guard's protected-path check | in progress on `fix/guard-timeout` (no commits at 23:06); fix direction, proof test and mutant in `H/.claude-work/shrink-on/plan.md`; security surface (auditor + code-reviewer); first in the merge order |
| 21 | Output-shrink follow-ups: tests, scripts and ruff through `bin/stack-run`, poll loops replaced by one background wait (section 1 measurements); Read to `on` only after judging the paging cost; Decision 6 needs 5+ sessions of shadow log | possible; any rules text needs a prompt_budget gate or trim decision (USER) |
| 10 | `RESET_TO_MAIN.sh` `--archive`/`--apply`, worktree removals | the user (section 3) |
| 18 | A4 fold into COMPARE_eq A4 item 4 (`hand_off/A4_FOLD.md`) | after the user's paid probe (section 5); python-engineer |

Deferred: oracle residuals, 6.10 items, Stage 3 D1-D5.

## 5. User steps

1. **Merges, then one C10: done 2026-10-08** [v]: `shrink-on` and `bayes-3a-fixes` ff-merged (main `47dce9f4`); C10 on main
   green (section 1). Still yours: the wiki `docs-reorg` branch (the wiki push is yours); the ff of this hand-off
   (`git -C M merge --ff-only golden/work-order-continuation-b06255`).
2. **Reinstall: done 2026-10-08** [v: the manifest at `47dce9f4`]. Procedure for the next one (after each program merge and
   its green C10; quit every Claude Code session first; agents never run `install.sh`): `H/.claude-work/dot-config/REINSTALL.md`,
   i.e. `./install.sh --dry-run`, then `./install.sh --yes`, from M. Check: the manifest commit is main's;
   `grep -n '^tools:' ~/.claude/agents/orchestrator.md` has `Bash`; `bash ~/.claude/bin/doctor.sh` from your terminal (the agent
   sandbox run on 23:05 shows sandbox-only FAILs, section 1). Undo: `./install.sh --restore` (backups in
   `~/.local/state/claude-agent-stack-backups`).
3. Runtime Equilibrium live checks (nothing live-verified): README "Live checks" 9 (spec section 13) and
   `hand_off/R3_CONTAINER_CHECKLIST.md` C14-C23, D1-D9 (the default `core` set stops at exit 13 until the placeholder pins
   `BASH_SRC_SHA256`, `BASH_PATCHES_SHA256`, `BASH_BIN_SHA256`, `CONTAINER_PKG_SIGNER` are filled). Paid calibration:
   `hand_off/EQ_CALIBRATION_RUN_PLAN.md` (every step needs your approval and a ceiling). A class turns `validated` only when
   the committed `eq_params.json` carries it and you reinstall.
4. Stop the orphan `disc3.py` from the old mutation run: `pgrep -fl disc3.py`, then `pkill -f disc3.py` (agent sandboxes cannot).
5. Paid A4 probe (consent: one call, <= $0.25; run it from a logged-in terminal; then brief a python-engineer with the output
   path and COMPARE_eq A4). Not run yet. The command is in `hand_off/A4_FOLD.md`.
6. Paid program probes (section 9): SDK `sdk_smoke.py` <= $3.00, `sdk_probes.py` <= $10.50; Bayes pilots P1 <= $40, P2 <= $200.
7. The merges are done: remove the scratch worktrees and `refs/rescue/shrink-on-51dcd288` listed in section 3, and the
   superseded branch `golden/handoff-plan-continuation-c09473` once this hand-off is on main.
8. Per program branch, in the section 9 merge order: a full C10 on its tip from your terminal
   (`cd ~ && bash H/.claude-work/c10/c10-ref.sh <branch>`), then `git -C M merge --ff-only <branch>` (main then equals the tested
   tip), then the reinstall (step 2) when the change should go live.

## 6. Verification facts that matter

- `container` flags, verified by the user's `container run --help` (1.5.0): present `--rm --read-only --cap-drop --init --user
  --uid --gid -m -c --ulimit --tmpfs <path> --mount ...,readonly -w --name --network`; absent `--pids-limit`, `--security-opt`
  (`--ulimit nproc=512` substitutes). `--network none` is not in the help but works per the user's spike.
- Unverified: `--tmpfs` `size=`/`mode=` sub-options; the image digest field path (`image inspect` top-level keys are
  `configuration`, `id`, `variants`); whether the fake-container tests match the real CLI.
- A4 item 4 needs the paid probe: `--json-schema` answer under `--tools`; `--agent` frontmatter tools intersect `--tools`
  under `-p`; `--settings` cannot widen the list; `Skill` loads under `--strict-mcp-config`.
- Docs facts (T1g): `--agent` tools apply to the main thread (`-p` unverified); `--tools` restricts built-ins, `--allowedTools`
  only auto-approves; only `Read()`/`Edit()` path rules are consulted.
- C10 on main `d6046693` (2026-10-08, user terminal) [r]: reinstall done (manifest == main `d6046693`; orchestrator `tools:` has `Bash`; live limits
  `hard.prompt` 300M, `soft.prompt.orchestrator` 140M). Full run: all 7 known failures passed; `tests/test_moved_paths.py` green;
  `test_install_hardening` dry-run test and the install_smoke `--dry-run wrote HOME [.cache]` check fail only with `UV_CACHE_DIR` unset
  (`install.sh:1410` `uv python find` writes scratch `HOME/.cache/uv`; `_run_install` never sets it; with it set the test passes, 1 passed).
  Remaining install_smoke failure: the `openpty` pty check (known, environmental).
- C10 on main `47dce9f4` (2026-10-08, user terminal) [v]: green; numbers in section 1.
- Not run by agents: `tests/install_smoke.sh` on a terminal (1 `openpty` failure since `51dcd288`, environmental; it was 2), the c0 arm.

## 7. Open items

- Equilibrium broker TOCTOU: `load_wall_module` vs `Wall.start` in `eq_harness` (latent, MEDIUM, pre-existing).
- T-guard-timeout (pre-existing): a `timeout <duration>` prefix hides the command word from agent_guard's protected-path scan
  (section 4 #20; in progress on `fix/guard-timeout`).
- output_shrink `updatedToolOutput` replacement: **resolved**, seen live 2026-10-08 23:05 (section 1 live checks). Small follow-up:
  `output_shrink.py report` with no argument, run from a linked worktree, reads that worktree's empty log, not M's.
- doctor.sh inside an agent sandbox reports sandbox-only FAILs (`stack.env` read-denied, state dir EPERM); a clean run needs the
  user's terminal [unverified].
- A4 fold waits for the paid probe; `disc3.py` orphan; `RESET_TO_MAIN.sh` steps are the user's; unmerged side branches, scratch
  worktrees and `refs/rescue/shrink-on-51dcd288` (section 3).
- Model display: setup is fine (every agent has `model: opus|sonnet`). In that other session check project-level `.claude/agents`
  shadowing; the `d6046693` reinstall should have brought in the 5 missing agents [unverified].
- Unverified: whether the old stopped agents' stray processes still run; the wiki remote head; EQ-T snapshot completeness
  (no original listing to diff).

## 8. What is merged (one line each; all ancestors of main, [v] at the time of each merge)

| item | note |
|---|---|
| orch-bash `f5de4f6` | orchestrator holds `Bash` with the web check and git-guard gaps closed |
| handoff-docs `a3653dd`, wiki | RUNBOOK_c0, A4_FOLD, a4_fold.py, c0_support; the wiki is GitHub's wiki (USER 2026-10-06), `docs/wiki/` untracked, `tests/wiki_check.py` |
| l2-final `7c7137d` | `output_shrink` PostToolUse hook, shadow mode (`STACK_OUTPUT_SHRINK=on` cuts) |
| r3-ready `84ba493`, eq-pins, eq-cli-install `321f037`, eq-distroless `fd0a2a3` | the Apple `container` port: `lib/eq-container`, `lib/eq-wall`, `install.sh --with-eq-container`, distroless images |
| 3d-agents `41e2aae` | rigger-animator, sculptor-painter, procedural-3d-ui + 7 skills |
| l5-land `6d9713a` | `stack_progress.py` observe-only early stop (`STACK_EARLY_STOP=observe` default) |
| claude-md-block `485b855` | installer-managed `~/.claude/CLAUDE.md` block, byte-exact restore |
| s4-instructor `cf8cf68` | deterministic instructor: `tools/instructor` (`check-suite`, `ff-merge`, `worktree-audit`) |
| toolsmith `2ec6e2c` | `toolsmith` agent + `bin/stack-install` executor, vetted installs |
| reset-to-main `76e1cd4` | `hand_off/RESET_TO_MAIN.sh` (dry run by default) |
| l7-mech `a05d508` | B1 hand-back check, B3 `first_write` signal, L10 trims |
| s3-integ `b1a0703` | Stage 3 quality pass (behaviour-neutral) |
| eq-track `c0b2d8d` | the harness tracked as `dot-config/dot-equilibrium` (A5 path relativisation, A9 move) |
| audit-fixes `ad10c9ba` | no-push git gaps in agent_guard, web check, STACK_HOOK_RE, deferred profile |
| eq-runtime-2 `258d3a35` | harness p6/p7/CLI/E_rt, both product bugs fixed, A6-A8; 183 harness mutants killed |
| docs-reorg `f20c7a89`, jsonschema fix, hs-update-1007b, hs-next | layout, requirements, hand-off text |
| dot-config | A9 move, single installer, `parents[5]` re-pin, WALL lookup depth rule, instructor patch; C10 green bar the above |
| limits-raise `52c1abcc`, hand_off `d6046693` | orchestrator soft prompt 140M, `hard.prompt` 300M, F2; C10 green modulo environment |
| bayes/3a `91fd17d2` | WP0a fixture, WP0b/1a `docs/BAYES.md` v3, WP1c fixes, WP3a shadow Bayes tier + grid; regressions fixed in `bayes-3a-fixes` (merged) |
| shrink-on `a0791669` | output_shrink cuts successful Bash results over 8000 chars by default, `bin/stack-run`, review fixes (S1-S4, R1-R3); C10 green on main `47dce9f4` |
| bayes-3a-fixes `47dce9f4` | install.sh stages `hooks/stack_bayes_grid.py`, lint_agents exemption for the b1v2 fixture, scipy importorskip; C10 on main green (0 failed ids, install_smoke 282/1); reinstalled |

## 9. Next programs (plans saved; started 2026-10-08 23:04)

Every plan file is under H (git-ignored `.claude-work/`); the work-order tracker is `H/.claude-work/work-order-1008/plan.md`.
Remaining plan: the guard fix T-guard-timeout (`fix/guard-timeout`), SDK-1 (`sdk/1`), Bayes WP2, WP4, 3b, 3c.
**Merge order: guard (`fix/guard-timeout`) -> `sdk/2` -> `bayes/3b` -> `bayes/3c` (its `install.sh` staging of
`hooks/stack_bayes_grid.py` is done in `bayes-3a-fixes`; the rest waits for the guard merge: agent_guard.py edits are
serialized, per the Bayes plan) -> `sdk/3` -> `bayes/4` -> `sdk/4`**; each through review, then a full C10 on its tip from the user's terminal
(`c10-ref.sh <branch>`), then the user's ff-merge. Where `sdk/1` lands (alone before `sdk/2` or folded into it) the work order
does not say [unverified].

1. **SDK optimization**, `H/.claude-work/sdk/plan.md`. Decisions Q1-Q4: unattended runs stop at the plan with STATUS blocked;
   the installed `claude` via `cli_path`; Python only. SDK-1 (`sdk/1`): the probe script `tests/sdk_probes.py` (PEP 723 plus
   lock, run by the user, never by pytest), pinned `claude-agent-sdk==0.2.163`; then SDK-1u: the user runs
   `uv run --script tests/sdk_smoke.py` (<= $3.00) and `uv run --script tests/sdk_probes.py` (<= $10.50), and the SDK-2 design
   is frozen on the probe results.
2. **Bayesian tuning**, `H/.claude-work/bayes/plan.md` ("STAGE 3b-4 EXECUTION"). Decisions Q1-Q5: Q1 the empirical stage keeps
   deny-type values; Q2 advice only for width; Q3 consent to P1 <= $40 and P2 <= $200 (user-run pilots); Q4 amend the
   equilibrium before p data; Q5 default keep sched/fanout. Units: WP2 refit v3 on a live copy (data-scientist, output
   `M/.claude-work/bayes/wp2/`); WP4 scheduler `load_bayes_sched` (`bayes/4`); WP3b detached fitter (`bayes/3b`, needs WP2's fit
   time); WP3c remainder (`bayes/3c`, after the guard merge).
3. **Lost-work rescue**, `H/.claude-work/lost-features/rescue/` (`MANIFEST.md`, `campaign-restored/`, decision quotes in
   `bayesian-decision.md` and `sdk-request.md`). The user asked for steps; copy the folder out of the worktree first.
4. **Deterministic offload** (possible, not planned): the stack-run habit of section 4 #21; data and scripts in
   `H/.claude-work/deterministic-offload/` and `H/.claude-work/output-shrink-on/`.
