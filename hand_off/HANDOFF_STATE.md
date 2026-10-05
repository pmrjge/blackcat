# HANDOFF_STATE: claude-agent-stack, session 8ad965da (2026-10-05, written ~16:30, updated ~16:45 after the stop)

**STOPPED STATE.** At ~16:37 the user ordered every running task stopped except the commit of `hand_off/` to main.
Stopped: the orchestrator (aeb982e2417df4dd0), R3 (main-coder a5a3114a94bceb867), the L1 INTEG (main-coder
a7fae00afc61465ac, mid-C10), `orch-bash` (claude-code-engineer a7ed898c01c4f5a2d) and the reset-script writer (main-coder
acddf3f1fa0c498d5). None should still run (the C10 log stopped growing at 16:37:22; the process list was not readable
from the agent sandbox, so [unverified]). Their branches and worktrees hold unmerged WIP and stay as they are (§2); only the
user removes worktrees. The L1 fixes did reach main, but **C10 on main was interrupted and is not confirmed** (§1).

Supersedes `claude_info/HANDOFF_FULL.md` §0, §6 and §7 where they differ. HANDOFF_FULL remains the reference for R1/R2,
the Stage-4 lever table (§2 R4), the L1 review findings (§4) and older decisions (§5).

Paths: **M** `/Users/pmrj/ZDone/claude-agent-stack` (main checkout, repo of record; `hand_off/` is committed on main,
so `M/hand_off/` is the copy to read) · **H** the handoff worktree
`/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb` (branch
`golden/claude-info-handoff-setup-05c3bb`; its git-ignored `.claude-work/` holds the job files) · **WT** `M/.claude/worktrees` · **EQ-T** (new)
`WT/eq-t-1005/.claude-work/equilibrium` · job plan `H/.claude-work/resume-1005/plan.md` · ledger
`/Users/pmrj/.local/state/claude-agent-stack/8ad965da-ee69-47f6-8e8b-40a9d258455f/delegations.md`.
**T** (`next-steps-7c1c7f`) and **S** (`agent-stack-resume-9caddf`) no longer exist.

Key: **[v]** read in a file or git this session · **[r]** from an agent's report or the job plan, not re-run ·
**[unverified]** nobody checked it.

## 1. DONE / merged

| item | state |
|---|---|
| `main` | the commit that adds `hand_off/`; below it `7ea9590` ("Main", 16:42, committed in M after the stop: adds `.claude-work` to `.gitignore`), `2aff512` (claude_info: L1 follow-ups noted), `69067f6` (L1 review follow-ups), `743a7e2` (claude_info R3b correction), `ff48d70` (session-stop handoff), `d955bef` (L1) [v: `git log`, 16:47] |
| L1 review follow-ups (T2) | **Merged** by fast-forward: branch `worktree-agent-afb29c2edb383d1dc` @ `2aff512` is an ancestor of main; its worktree `WT/agent-afb29c2edb383d1dc` is clean and locked [v]. Files: `tests/cache_monitor.py`, `tests/cache_stability_lint.py`, `tests/test_cache_monitor.py`, `tests/test_cache_stability.py`, `claude_info/HANDOFF_FULL.md` [v: `git diff --stat 743a7e2 2aff512`]. **C10 on main @ `2aff512`: NOT confirmed.** The INTEG run (runner `H/.claude-work/resume-1005/c10-main-2aff512.sh`) started 16:31:27 and stopped in pytest at ~8 % when the user stopped the agents; the log stopped growing at 16:37:22 and no step result was written (`c10-main-2aff512.summary` holds only the start line) [v] |
| Installed manifest | `7d12c58` [r]. Install HELD; it ends when the user reinstalls main (§5) |
| T0 isolation backend | Decided: Apple `container` 1.5.0 replaces Docker. Spike passed: `--network none`, `--read-only`, 0.62 s cold start [r]. Seatbelt/`sandbox-exec` and App Sandbox rejected (researcher aa86e636efb18156d: no per-path denies, Keychain IPC reachable, no fork/memory caps; scout a30dd79402430c2dc: `sandbox-exec` deprecated, no removal notice found) [r] |
| T1g docs check (claude-code-guide ac12a2c909bccbe01) | `--agent` tools apply to the main thread (`-p` unverified); `--settings` arrays merge, precedence managed > `--settings` > local > project > user; `--tools` restricts built-ins, `--allowedTools` only auto-approves; only `Read()`/`Edit()` path rules are consulted, `Write()` rules never [r] |
| T1b skill amendment A4 (python-engineer a8f4c248dfa20814e) | `--tools` (built-ins + `Skill` + `StructuredOutput`) plus `--allowedTools` kept; `common_tools = ["Skill"]` in flags.json, fails closed without it; test `harness/tests/test_skill_tools_argv.py`; COMPARE_eq A4 written [v: COMPARE_eq.md:424-467]. 416 harness tests pass [r] |
| T1x EQ-T restore | EQ-T restored as worktree `WT/eq-t-1005` from branch `golden/next-steps-7c1c7f`, snapshot copied in, `diff -r` vs snapshot clean, 416 passed [r; both re-checked at 16:41, §2: v]. **EQ-T is not in git.** Sole other copy: `H/.claude-work/t1b/equilibrium-snapshot-1611/` (read-only; pre-edit harness `t1b/eq_harness.py.pre-t1b`, diffs `t1b/eq_harness.t1b.diff`, `t1b/t1b-all.diff`) [v: files exist] |
| Worktree audit | `H/.claude-work/resume-1005/worktree-cleanup.md` (verifier a752e2c18d6e1139d, 16:02): commands by class, nothing removed [v] |
| Loss assessment | `H/.claude-work/resume-1005/t-loss.md` (verifier a402ed933d056b18e, 16:19) [v] |
| User-run command list | explore aff29c92b53acef18 [r; output not in a file found] |

## 2. STOPPED by the user's order (~16:37; were running; all agent ids die with the session)

State read at ~16:40 with git and the files named [v], unless marked. Nobody resumes these agents; the next session
briefs fresh builders from the files.

| agent | id | work | state at stop |
|---|---|---|---|
| orchestrator | aeb982e2417df4dd0 | coordinated resume-1005 (job plan `H/.claude-work/resume-1005/plan.md`, last checkpoint 16:34) | stopped; no own branch |
| main-coder (R3) | a5a3114a94bceb867 | Port R3 to `container` in worktree `WT/agent-a5a3114a94bceb867`, branch `worktree-agent-a5a3114a94bceb867`, base `743a7e2` | stopped. Branch @ `60dd3ad`, 2 WIP commits ahead of main: `5bb86bf` (lib/eq-container + lib/eq-wall copy) and `60dd3ad` (driver `eq-container.sh`, `probe.sh`, `verify-tools.sh`, `eqc_json.py`, WALL policy path + REVIEW re-hash). **Uncommitted:** `lib/eq-container/lib.sh` (+6/-3) and untracked `tests/fake-container/container` (16:35). Not wired into the installer, no tests run, not reviewed. Harness work was in its own copy `WT/agent-a5a3114a94bceb867/.claude-work/r3/eqt/equilibrium/harness/eq_harness.py` (baseline `.claude-work/r3/eqt-base/`), mid-port; EQ-T itself was not touched (see EQ-T below) |
| main-coder (L1 INTEG) | a7fae00afc61465ac | Fast-forward the L1 fixes into main, C10 on main | stopped during C10: the merge is on main (§1), C10 not confirmed |
| python-engineer (L1 fixes, T2) | afb29c2edb383d1dc | L1 review follow-ups (HANDOFF_FULL §4) | done and merged (§1); branch and worktree kept (locked, clean) |
| claude-code-engineer | a7ed898c01c4f5a2d | Add `Bash` to the orchestrator, worktree `M/.claude-work/worktrees/orch-bash`, branch `orch-bash` | stopped. Branch @ `743a7e2`, **no commits**; uncommitted edits to `CONFIG.md` (+3), `README.md` (1 line), `dot-claude/agents/orchestrator.md` (tools line becomes `Agent, SendMessage, TaskStop, Read, Write, Edit, Bash, Skill, mcp__neural-memory`: adds Bash, drops Glob and Grep; body step 8 "integrate: fast-forward main with Bash, no worktree removal, never push"). Not reviewed. Main's `dot-claude/agents/orchestrator.md:7` still has no Bash. `H/.claude-work/resume-1005/orch-bash.md` does not exist |
| main-coder (R3s reset script) | acddf3f1fa0c498d5 | `RESET_TO_MAIN.sh` (archive, then dry-run reset to main only) with throwaway-repo tests in `M/.claude-work/resume-1005/reset/` | stopped. **No files found:** `M/.claude-work/resume-1005/reset/` does not exist; nothing reset-related under `M/.claude-work`, `H/.claude-work` or `hand_off/`; the archive dir `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/_archive_stack_1005/` does not exist; nothing committed. Treat as not started (§4) |

EQ-T (`WT/eq-t-1005`, branch `golden/next-steps-7c1c7f` @ `a22c5b4`, already in main): `diff -rq` against the snapshot
`H/.claude-work/t1b/equilibrium-snapshot-1611/` is clean at 16:40, so it holds the T1b A4 edits and none of R3's harness
work. Harness suite on a scratch copy of EQ-T (16:41, `uv run --no-project --with pytest --with duckdb
--with-requirements harness/eq_harness.py pytest -q -p no:cacheprovider harness/tests`): **416 passed** in 97 s [v].
EQ-T is consistent; no half-applied edit in it.

Not started, unchanged by the stop: Stage 4 items after L1 (L2 branch `s4-l2-output` @ `b6e05d6` and L5 branch
`s4-l5-budget` @ `2ebc26f`, both unmerged [v]; CLAUDE.md block, instructor, L7 B1/B3 + L10), Stage 3, the c0 runbook,
ONE_TREE/RESET (§4 items 4-11).

R3 remaining (from `WT/agent-a5a3114a94bceb867/.claude-work/r3/STATE.md` at 16:32; its "Progress" line says all
lib/eq-container scripts and the lib/eq-wall policy path are ported in the WIP commits, so items 1-2 need only a check,
the exec bits and README; the harness copy is part-ported; next were flags.json, README, harness tests, then the installer):
1. lib/eq-container: check the ported scripts against STATE.md "Remaining" item 1; exec bits (100755 for `*.sh`,
   `minimal/lake-shim`, `tests/fake-container/container`); README; commit the uncommitted `lib.sh` edit and the fake CLI.
2. lib/eq-wall: docs docker -> container (`WALL_DESIGN.md`/`INSTALLER_WALL.md` were touched in `60dd3ad`; check).
3. Installer wiring: `--with-eq-container`, `--eq-container-profiles`, `--no-eq-broker`/`--with-eq-broker`; steps 10b/10c;
   `__EQ_TUNNEL__` render; manifest keys `eq_container`/`eq_wall`; stack.env, `stack_diff.py`, agent_guard keep-list +
   `eq_tunnel_root()`, doctor.sh; settings.json deny rules as **Read+Edit** on `~/.cache/claude-agent-stack/eq-tunnel/**`,
   `/__EQ_TUNNEL__/**`, `/__STACK_STATE__/eq-wall/**` plus sandbox denyWrite (Write rules are never consulted).
4. Tests: `tests/fake-container/container`, conftest, `test_eq_container.py`, install tests, smoke cases.
5. Harness backend `container`: finish the port in R3's copy `.claude-work/r3/eqt/` (diff against `eqt-base/`), then
   apply it to EQ-T (outside the A4 argv block); flags.json, README, harness tests with fake_container, run from a /tmp copy.
6. Docs; C10 (the runner `S/.claude-work/wrapup/c10.sh` is lost: recreate as `.claude-work/r3/c10.sh` in its worktree);
   squash the WIP; security-auditor + code-reviewer; fixes; INTEG (merges main into its branch first; one INTEG at a time).

## 3. MISSING / LOST

Worktrees T and S were removed at ~16:12 on 2026-10-05, including their git-ignored `.claude-work/`. Cause unknown; no
copy in the Trash was checkable (sandbox) and none found on disk. **User decision: re-derive, no recovery.** Details per
item: `H/.claude-work/resume-1005/t-loss.md`.

| lost | re-derive from |
|---|---|
| one-tree `AUDIT.tsv` (112 rows) + `ONE_TREE.sh` draft | live git; `worktree-cleanup.md`, `wtlist.txt`, `rows1.txt` in `H/.claude-work/resume-1005/` |
| `context-diet/RUNBOOK_c0.md` | HANDOFF_FULL §8 outline (A reinstall a22c5b4 in a throwaway clone, B verify, collect c0 17 prompts with `freeze.sh --arm c0`, C back to main); `M/claude_next_steps/work_carried/context-diet/` (COMPARE_c0, freeze.sh, c0_check.sh); template `work_carried/compact-protocol/measurement/RUNBOOK_A_ARM.md` |
| next-steps `plan.md` ledger, `STAGE4.md` (L1-L10 specs), `R5_MAP.md`, `staged/` (NEXT_STEPS, DECISIONS, CHANGES) | HANDOFF_FULL; commits d955bef b6e05d6 2ebc26f deea4d5; `claude_info/s4_outputs/`; R5 maps by re-running explore |
| `s4-l5/` DESIGN.md + `agent_guard.patch` + `install.patch` | branch `s4-l5-budget` @ `2ebc26f` (code survives); patches re-written by the L5 builder |
| `s4-l7-l10/MECHANISMS.md` | HANDOFF_FULL lines 80 and 126 (B1/B2/B3 outline); if insufficient, ASK USER before building |
| S `r3/` patches + STATE.md, `wrapup/c10.sh` | R3 builder's own STATE.md/plan.md; C10 command line in HANDOFF_FULL §1 item 10 |

Survivors: EQ-T (snapshot + restored `WT/eq-t-1005`), `claude_info/s4_outputs/` (s4-instructor, s4-l2, s4-l7-l10 without
MECHANISMS, s4-l9), `M/claude_next_steps/work_carried/context-diet/`, git commits `2ebc26f`, `deea4d5`, `b6e05d6`, `d955bef`.

`skill-removals.md` is at `M/.claude-work/resume-1005/skill-removals.md` (15:18), not under H [v]. Not found:
`H/.claude-work/resume-1005/orch-bash.md`; the reset-script files (§2). New since the first write:
`H/.claude-work/resume-1005/unused-folders.md` (verifier a1838258f061311ce, read-only inventory of clutter folders in M).

## 4. LEFT TO DO (in order; serialized merges, C10 on main after each; one INTEG at a time)

| # | task | owner agent type |
|---|---|---|
| 0 | Verify state (first actions of the next-session prompt), then **C10 on main** at its current HEAD: the run on `2aff512` was interrupted (§1); runner to adapt: `H/.claude-work/resume-1005/c10-main-2aff512.sh` (full C10 ~21 min) | verifier |
| 1 | `orch-bash`: commit the uncommitted edits in its worktree (§2), security-auditor review, fixes, INTEG; then the user reinstalls (§5) | claude-code-engineer, security-auditor |
| 2 | L1 follow-ups: **merged** (`69067f6`, `2aff512`); only the C10 of item 0 is left | (none) |
| 3 | R3 `container` port: commit the uncommitted WIP, finish the §2 list; security-auditor + code-reviewer; fixes; INTEG | main-coder, security-auditor, code-reviewer |
| 4 | L2 `s4-l2-output` `b6e05d6` + 3 patches from `claude_info/s4_outputs/s4-l2/` in an own worktree; reviews; merge after R3 (settings.json serialized) | main-coder, security-auditor, code-reviewer |
| 5 | Installer-managed `~/.claude/CLAUDE.md` block (spec lost with STAGE4.md: re-derive from HANDOFF_FULL + brief) | main-coder |
| 6 | Instructor: re-commit `deea4d5`'s tree from its own worktree (plumbing commit breaks the own-worktree rule), apply its 3 patches; one allow rule per recipe; `just` 1.58.0 installed [r]; reviews; merge | main-coder, security-auditor, code-reviewer |
| 7 | L5 `2ebc26f` observe-only: re-derive the 2 lost patches; reviews; merge | main-coder, security-auditor |
| 8 | L7 mechanisms B1 + B3 (agent_guard.py, serialized) + L10 trims as a side commit (user said yes; -26 tokens/spawn [r]); MECHANISMS re-derived, ASK USER if the outline is insufficient | main-coder, security-auditor |
| 9 | Stage 3 quality pass: re-map with explore, ≤ 2 coders in disjoint worktrees, behaviour-neutral; behaviour changes listed for approval | explore, coder |
| 10 | ONE_TREE / RESET (user order: reset the repo to "only main" after the live work lands; the orchestrator folded ONE_TREE into it). Not started (§2). Write `RESET_TO_MAIN.sh` with throwaway-repo tests: stage 1 archives everything unique to `/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/_archive_stack_1005/` (a bundle per branch; tarballs for untracked/ignored data: EQ-T + snapshot, c0 data, dirty worktrees, `claude_next_steps/work_carried`, `M/.claude-work/context-diet/transcripts` (may hold secrets), `claude_info`; manifest + sha256); then dry-run by default, `--apply` explicit; never `rm -rf` a worktree; `worktree remove --force` only after the archive is verified; `branch -D` only for a branch in a verified bundle; `git clean -ndx` shown before `-fdx`; reflog expire/gc behind a separate flag; live or locked worktrees are blockers. Re-take the audit after all merges; code-reviewer, then a verifier dry run; the archive dir is outside the agents' sandbox and `--apply` is the user's. After the user's archive is verified: `git rm -r claude_info/` on main (`hand_off/` replaces it). H is removed last | main-coder, code-reviewer, verifier |
| 11 | c0 runbook re-derived with exact commands, handed to the user (c0 collection is user-run and paid) | main-coder or verifier |
| 12 | After the user's paid probe: fold the result into COMPARE_eq A4 item 4 | python-engineer |

Deferred: oracle residuals (HANDOFF_FULL §6.1), §6.10 items.

## 5. USER STEPS

Reinstall (gives the orchestrator `Bash`, ends the install hold). Only after `orch-bash` is merged into main and C10
passes on main: installing main before that installs an orchestrator without Bash. Quit every Claude Code session first.

```bash
git -C /Users/pmrj/ZDone/claude-agent-stack log --oneline -3
```

```bash
grep -n '^tools:' /Users/pmrj/ZDone/claude-agent-stack/dot-claude/agents/orchestrator.md
```

```bash
cd /Users/pmrj/ZDone/claude-agent-stack
```

```bash
./install.sh --dry-run
```

```bash
./install.sh --yes
```

```bash
grep -n '^tools:' ~/.claude/agents/orchestrator.md
```

Undo (backups in `~/.local/state/claude-agent-stack-backups`):

```bash
./install.sh --restore
```

Paid probe for A4 (consent given: one call, hard cap $0.25). Run it yourself from a normal logged-in terminal (agent
sandboxes have no `claude` login). Not run yet. The T1b python-engineer (a8f4c248dfa20814e) is gone with the session:
afterwards brief a fresh python-engineer with the output file path and COMPARE_eq A4; it strips credentials and folds
the result into A4 item 4 (§4 item 12). If you move EQ-T first (below), change `P=` to the new path.

```bash
P=/Users/pmrj/ZDone/claude-agent-stack/.claude/worktrees/eq-t-1005/.claude-work/equilibrium/probes; mkdir -p "$P"; TS=$(date -u +%Y%m%dT%H%M%SZ); cd "$(mktemp -d)" && printf 'List the exact names of every tool you can call, then return them.\n' | claude -p --agent writer --model sonnet --max-budget-usd 0.25 --json-schema '{"type":"object","properties":{"tools":{"type":"array","items":{"type":"string"}}},"required":["tools"],"additionalProperties":false}' --output-format stream-json --verbose --permission-mode acceptEdits --disallowedTools Agent WebSearch WebFetch --strict-mcp-config --tools Read,Skill,StructuredOutput --allowedTools Read Skill > "$P/a4-probe-$TS.json" 2> "$P/a4-probe-$TS.err"; echo "exit=$?" >> "$P/a4-probe-$TS.err"
```

`container` flags: done. You ran `container run --help` and `container image inspect alpine:latest | jq '.[0] | keys'`,
and the output was relayed to R3 (a5a3114a94bceb867).

Move EQ-T to the agreed worktree location. R3 and T1b are stopped, so it can run before the next session; then give
the builders the new path (R3's STATE.md still names the old one):

```bash
git -C /Users/pmrj/ZDone/claude-agent-stack worktree move /Users/pmrj/ZDone/claude-agent-stack/.claude/worktrees/eq-t-1005 /Users/pmrj/ZDone/claude-agent-stack/.claude-work/worktrees/eq-t-1005
```

Worktree cleanup: commands in `H/.claude-work/resume-1005/worktree-cleanup.md`. Class 1a and 1c are safe now; 1b only
after the sessions using them are closed and the builds are done; class 2 (`--force`) only after its backup commands;
class 4 (`branch -D`) optional. Its rows for T and S are obsolete (both gone), and its 1b "copy S to T" step can no
longer run. Keep `agent-a5a3114…` (R3 WIP, partly uncommitted), `M/.claude-work/worktrees/orch-bash` (all of its work
is uncommitted), `eq-t-1005` (EQ-T, not in git), `agent-ac1227df…` (R3b reference) and H until their work is merged or
archived (§4 item 10); `agent-afb29c2…` is merged and clean (locked). Nobody but you removes worktrees.

`protocol-p1` worktree (in W, rebase stopped on a CONFIG.md conflict): continue, abort or archive: your call (HANDOFF_FULL §2 R5).

## 6. DECISIONS made this session (USER; do not re-ask)

1. Isolation backend: Apple `container` 1.5.0; Docker dropped. c0 and the Docker runbook: the user runs c0 (stated
   this session; whether it was run: unverified, `RUNBOOK_c0.md` is lost, item 11); the Docker part is dropped.
2. Image choices: Debian packages for bash/perl/jq/busybox; Scala 3 release tarball; MongoDB out (PostgreSQL profile also
   dropped by R3: its only runner was compose); `cc` linker in the Rust/Haskell images.
3. Oracle residuals (§6.1) deferred; §6.10 deferred.
4. `mcp-server-craft` stays retired (`e045482`); do not restore.
5. Plugin autoUpdate for claude-plugins-official: keep on.
6. Stage 4 build threshold confirmed: 3% pooled, 2% per class, 4 of 5 sessions.
7. SendMessage-resume rule: restrict. Subagent cache TTL: keep the default. `omitClaudeMd`: measure offline first.
8. R3 merges after its reviews with the install still held; the user reinstalls next session.
9. L10 side commit: yes.
10. ONE_TREE default: archive unique-commit rows as git bundles; dry-run only; never `--apply` by an agent.
11. A4 paid probe approved (one call, ≤ $0.25); logged-in or paid `claude` steps are user steps.
12. T/S loss: re-derive, no recovery.
13. Nobody but the user removes worktrees (INTEG step "remove worktree" becomes "list for the user").
14. Hand-made worktrees go under `M/.claude-work/worktrees/<name>`; harness `isolation: "worktree"` worktrees stay in `M/.claude/worktrees`.
15. Orchestrator gets `Bash` (branch `orch-bash`), effective after review, merge and the user's reinstall.

Standing constraints (unchanged, HANDOFF_FULL §1): never push, no forge writes; agents never run `install.sh`; no paid
runs without consent; no Haiku; security surfaces (agent_guard.py, settings.json, install.sh, hooks, WALL, lib/eq-*,
doctor.sh, agent definitions' tool lists) get security-auditor + code-reviewer before merge; own worktree only; serialize
agent_guard.py / settings.json / install.sh / blackcat.md; uv for Python; C10 on main after every merge. Agent Bash
sandboxes write only their own worktree, `$TMPDIR` and M; no `claude` login inside them.

## 7. OPEN questions / unverified

- `container` flags: VERIFIED by the user's `container run --help` output (relayed to R3). Present: `--rm --read-only
  --cap-drop --init --user --uid --gid -m -c --ulimit --tmpfs <path> --mount ...,readonly -w --name --network`. Absent:
  `--pids-limit`, `--security-opt` (`--ulimit nproc=512` is the substitute). `--network none` is not in the help but works
  per the user's spike.
- Still unverified: `--tmpfs` `size=`/`mode=` sub-options; the digest field path (`image inspect` top-level keys are
  `configuration`, `id`, `variants`, with no `digest` key); whether R3's fake-container tests match the real CLI.
- Paid probe: not yet run (command in §5).
- Answered at the stop (§1, §2): the L1 fixes are merged; `orch-bash` has no commit and no review; R3 committed two WIP
  commits and left `lib.sh` + the fake CLI uncommitted; no reset-script files exist.
- C10 on main: the run on `2aff512` was interrupted at ~8 % of pytest, so the L1 follow-up code (`69067f6`, test
  tooling only) has no confirmed C10 on main.
- EQ-T snapshot completeness: no original T listing to diff against; any `runs/` dirs in T are not in the snapshot.
- A4 item 4: `--json-schema` answer under `--tools`; `--agent` frontmatter tools ∩ `--tools` under `-p`; `--settings`
  cannot widen the list; `Skill` loads under `--strict-mcp-config`. All need the paid probe.
- Cause of the T/S removal (some other session or a cleanup run): unknown.
- The `explore` user-command list (aff29c92b53acef18) was not found in a file.

## 8. Progress, session resume-770728

Live plan: /Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/resume-770728/.claude-work/resume-1005/plan.md

| item | result | branch@sha | C10 |
|---|---|---|---|
| 1 orch-bash | orchestrator holds Bash with the T1 web check (bash -c/eval/find -exec unwrapped, stdin-fed shells refused, linear -c regex); 1571 targeted tests pass | orch-bash@d534cd4 | C10 on main: see plan.md |
| 11+12 handoff-docs | RUNBOOK_c0 (+§12 re-pin for clone install), A4_FOLD.md, a4_fold.py (8 tests pass), c0_support/ merged; reviewer not run (no spawn tool) | handoff-docs-2@dd8ceb6 | C10 on main: see plan.md |
| 4 L2 output | output_shrink PostToolUse `Bash\|Read` hook in shadow mode (logs only; `STACK_OUTPUT_SHRINK=on` cuts), 3 patches unchanged + install/doctor wiring, docs, read_family, review fixes (persisted Bash skipped, Read note line numbers only, ranged-Read paging); 114 tests, 63/63 mutants; security-auditor + code-reviewer applied | l2-final@0b87cbd | C10 on main: see plan.md |
