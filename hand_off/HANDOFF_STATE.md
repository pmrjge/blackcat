# HANDOFF_STATE: claude-agent-stack, current state as of 2026-10-08 (main = branch `limits-raise` after the user's ff merge)

One coherent state; it replaces every earlier version of this file (the 2026-10-05 stop, the per-branch "as of" notes and
the obsolete cells are gone). Supersedes `claude_info/HANDOFF_FULL.md` §0, §6 and §7 where they differ; HANDOFF_FULL stays the
reference for R1/R2, the Stage-4 lever table, the L1 review findings and older decisions. The next session starts with
`hand_off/NEXT_SESSION_PROMPT.md`.

Key: **[v]** read in a file or git when this was written · **[r]** from a report or a plan, not re-run · **[unverified]**
nobody checked it.

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout, repo of record; layout: three directories under `dot-config/`
since A9) · **H** `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb`
(branch `golden/claude-info-handoff-setup-05c3bb`; its git-ignored `.claude-work/` holds the job files) · **R**
`/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728` (older worktrees, the wiki clone) · ledger
`/Users/pmrj/.local/state/claude-agent-stack/8ad965da-ee69-47f6-8e8b-40a9d258455f/delegations.md`.

## 1. State

- **main**: the user ff-merges branch `limits-raise` right after this commit, then runs the reinstall. Tip of `limits-raise` before this
  commit: `52c1abcc` [v]; it includes a merge of main `ff8c3392` (post-merge: the moved-paths test fix and this integral rewrite). So
  main = this commit once merged; verify with `git -C M log --oneline -4 main`. Merged on main earlier (the user ran every ff
  merge): audit-fixes, eq-runtime-2 (A7: H5 removed; A8: E7 cell pass), docs-reorg, the jsonschema fix, hs-update-1007b,
  hs-next, and **dot-config** (A9 repository move: the Claude, Codex and Equilibrium trees live under `dot-config/`;
  `./install.sh --codex` is the single Codex installer; `extract_src` `parents[5]` re-pinned; the WALL lookup depth rule; the
  instructor patch is applied on main), post-merge (`b2ee53e8` + `ff8c3392`).
- **`limits-raise`, merged with this branch** (USER request 2026-10-08, "colliding with limits"; the soft limit of 80M had been hit):
  `soft.prompt.orchestrator` seed/floor/ceiling 80M/80M/100M -> **140M/140M/140M**; `hard.prompt` 100M/50M/250M -> **300M/300M/300M**.
  Exact pins, no headroom (USER choice). `soft.prompt` 33M and `hard.session` (1.92B seed / 2.5B ceiling) unchanged. F2 (USER: yes): for
  `hard.*` an env override can only LOWER the cap on every path without a usable snapshot (tampered or unwritable snapshot, event
  without session id, the guard's built-in constants when `stack_limits.py` is unusable); `turns.*` still ignore env there.
  Learned values are clamped into the new [floor, ceiling] on read, so no limits reset is needed. Running sessions keep
  119M/80M until a NEW session starts after the reinstall. Check: `stack_limits.py show '*prompt*'`. Two cosmetic points left
  unapplied: `Limits.where` wording when the seed is None; `bin/stack-budget` shows raw seeds on a fallback.
- **C10 on `b0ddf192`** (`H/.claude-work/c10/c10-main-b0ddf192.summary`) [r]: exactly 2 new failures (both `tests/test_moved_paths.py`;
  fixed by post-merge `b2ee53e8` + `ff8c3392`) and otherwise passed, apart from the 7 known environment failures (ids in
  `resume-770728/.claude-work/c10/c10-eqcli-321f037.failed_ids`: test_limits_guard T10, test_stack_tree x3, test_stack_usage x3;
  xcrun_db stderr) plus 2 `openpty` failures in install_smoke (280 passed / 2 failed). The `pool_sha` FAIL on `items/graders/`
  seen in the dot-config C10 was a script artefact (a glob). **The C10 on the final main (limits-raise merged, reinstalled) is still
  TO RUN by a coder.**
- **Installed stack is behind**: the manifest commit was `73eec41` (281 commits behind) on 2026-10-08. The installed orchestrator
  `tools:` line has no `Bash`; main's has. **USER STEP: `./install.sh`, then `./install.sh --codex`, from M right after the merge**
  (section 5); done when the manifest commit equals main. The reinstall also brings in 5 agents missing from the installed
  stack. After it, start a NEW session to get the new limits.
- Wiki: pushed to `pmrjge/blackcat.wiki` (`e0d2294` on `master`) [r]; the remote head is **unverified** (`ls-remote` blocked in
  the sandbox). A wiki `docs-reorg` branch awaits the user's merge.

Environment notes: the sandbox writes only in M and H; agents cannot merge into main; the shared uv cache
`/tmp/claude-501/uvcache` is corrupt (`uv run --no-cache`); harness runs need `EQ_AGENTS_DIR` and `EQ_CONTAINER_DIR`; BSD
`split` has no `-n l/4`; about 130 tests fail on paths when run under `.claude-work` (run from a `$TMPDIR` clone); the
verifier's read-only hook refuses harness, stack_progress and install runs (use a coder); BlackCat has a 24-tool-call cap per
prompt and the orchestrator a soft token limit (140M after `limits-raise` + reinstall, in a new session), so checkpoint the `plan.md` files.

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

Standing constraints: never push, no forge writes; agents never run `install.sh`; no paid runs without consent; no Haiku;
security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*, doctor.sh, agent definitions' tool lists)
get security-auditor + code-reviewer before merge; own worktree only; serialize agent_guard.py / settings.json / install.sh /
blackcat.md; uv for Python; C10 on main after every merge. Agent Bash sandboxes write only their own worktree, `$TMPDIR` and M;
no `claude` login inside them. `lib/eq-wall` and `tools/instructor` are protected: agents do not edit them.

## 3. Not merged / awaiting the user

| item | state |
|---|---|
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
| 1 | Reinstall (`limits-raise` merge first), then a C10 on main | USER step (section 5), done when the manifest commit equals main; then a coder runs the C10 (summary in `H/.claude-work/c10/`) |
| 3 | Programs (section 9), in the merge order | not started |
| 10 | `RESET_TO_MAIN.sh` `--archive`/`--apply`, worktree removals | the user (section 3) |
| 18 | A4 fold into COMPARE_eq A4 item 4 (`hand_off/A4_FOLD.md`) | after the user's paid probe (section 5); python-engineer |

Deferred: oracle residuals, 6.10 items, Stage 3 D1-D5.

## 5. User steps

1. **Reinstall** (quit every Claude Code session first; agents never run `install.sh`). Follow
   `H/.claude-work/dot-config/REINSTALL.md`: `./install.sh --dry-run`, `./install.sh --yes`, then `./install.sh --codex`. Correction
   to that note: it says 13 shipped files; **15 is correct**. The venv sync also clears the `jsonschema` mismatch. The
   `tools/instructor` deny rule makes sandboxed git writes to a `tools/instructor` path fail after the reinstall. Check:
   `grep -n '^tools:' ~/.claude/agents/orchestrator.md` has `Bash`; the manifest commit is main's. Undo:
   `./install.sh --restore` (backups in `~/.local/state/claude-agent-stack-backups`). The user runs it from M right after merging
   `limits-raise`; then start a new session for the new limits. After the reinstall, run `bash ~/.claude/bin/doctor.sh`.
2. Merge `limits-raise` (ff, before the reinstall); the wiki `docs-reorg` branch (the wiki push is yours).
3. Runtime Equilibrium live checks (nothing live-verified): README "Live checks" 9 (spec section 13) and
   `hand_off/R3_CONTAINER_CHECKLIST.md` C14-C23, D1-D9 (the default `core` set stops at exit 13 until the placeholder pins
   `BASH_SRC_SHA256`, `BASH_PATCHES_SHA256`, `BASH_BIN_SHA256`, `CONTAINER_PKG_SIGNER` are filled). Paid calibration:
   `hand_off/EQ_CALIBRATION_RUN_PLAN.md` (every step needs your approval and a ceiling). A class turns `validated` only when
   the committed `eq_params.json` carries it and you reinstall.
4. Stop the orphan `disc3.py` from the old mutation run: `pgrep -fl disc3.py`, then `pkill -f disc3.py` (agent sandboxes cannot).
5. Paid A4 probe (consent: one call, <= $0.25; run it from a logged-in terminal; then brief a python-engineer with the output
   path and COMPARE_eq A4). Not run yet. The command is in `hand_off/A4_FOLD.md`.
6. Paid program probes (section 9): SDK `sdk_smoke.py` <= $3.00, `sdk_probes.py` <= $10.50; Bayes pilots P1 <= $40, P2 <= $200.

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
- Not run by agents: `tests/install_smoke.sh` on a terminal (2 openpty failures are environmental), the c0 arm.

## 7. Open items

- Equilibrium broker TOCTOU: `load_wall_module` vs `Wall.start` in `eq_harness` (latent, MEDIUM, pre-existing).
- `STACK_CODEX_VIA_TOP=1` inner-installer bypass of agent_guard (LOW; `~/.codex` unguarded).
- A4 fold waits for the paid probe; `disc3.py` orphan; `RESET_TO_MAIN.sh` steps are the user's.
- Model display: setup is fine (every agent has `model: opus|sonnet`). In that other session check project-level `.claude/agents`
  shadowing; the reinstall brings in the 5 missing agents.
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
| Codex installer (codex-build `cfad7fa`) | now `dot-config/dot-codex_config`, installed by `./install.sh --codex` |
| eq-track `c0b2d8d` | the harness tracked as `dot-config/dot-equilibrium` (A5 path relativisation, A9 move) |
| audit-fixes `ad10c9ba` | no-push git gaps in both guards, web check, STACK_HOOK_RE, deferred profile |
| eq-runtime-2 `258d3a35` | harness p6/p7/CLI/E_rt, both product bugs fixed, A6-A8; 183 harness mutants killed |
| docs-reorg `f20c7a89`, jsonschema fix, hs-update-1007b, hs-next | layout, requirements, hand-off text |
| dot-config | A9 move, single installer, `parents[5]` re-pin, WALL lookup depth rule, instructor patch; C10 green bar the above |

## 9. Next programs (plans saved, not started)

Every plan file is under H (git-ignored `.claude-work/`). Merge order: Bayes 3a -> SDK-2 -> Bayes 3b -> Bayes 3c -> SDK-3 ->
Bayes 4 -> SDK-4; each through review and a C10 on main. Start only after the reinstall and a green C10 on main.

1. **SDK optimization**, `H/.claude-work/sdk/plan.md`. Decisions Q1-Q4: unattended runs stop at the plan with STATUS blocked;
   the installed `claude` via `cli_path`; Python only. User-run paid probes <= $13.50 in total (`sdk_smoke.py` <= $3.00,
   `sdk_probes.py` <= $10.50).
2. **Bayesian tuning**, `H/.claude-work/bayes/plan.md`. Decisions Q1-Q5: Q1 the empirical stage keeps deny-type values; Q2 advice
   only for width; Q3 consent to P1 <= $40 and P2 <= $200 (user-run pilots); Q4 amend the equilibrium before p data; Q5 default
   keep sched/fanout.
3. **Lost-work rescue**, `H/.claude-work/lost-features/rescue/` (`MANIFEST.md`, `campaign-restored/`, decision quotes in
   `bayesian-decision.md` and `sdk-request.md`). The user asked for steps; copy the folder out of the worktree first.
