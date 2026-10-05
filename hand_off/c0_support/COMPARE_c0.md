# COMPARE_c0: pre-registration of the c0 baseline arm (installed stack a22c5b4 = 9b39839 behaviour)

**Drafted 2026-10-04 15:55 +0100 by data-scientist (plan `follow-claude-next-steps-sharded-lamport.md`, step 4).**
**Frozen when the user runs `freeze.sh`.** That script copies this file, `c0_check.sh` and itself into
`claude_next_steps/work_carried/context-diet/` and writes their sha256 and the freeze time to `COMPARE_c0.sha256`
beside them. A file cannot hold its own hash, and git cannot record the order either: `claude_next_steps/` is ignored by the
stack repo (`.gitignore:45`, `git check-ignore -v`). The proof of order is therefore: the sidecar's `frozen_at_utc` is
earlier than the first `PASS` line in `arms/c0/DISPATCH_LOG.tsv` and earlier than the first c0 root `start` in the
collector's `runs.csv`; and `shasum -a 256 -c COMPARE_c0.sha256` still prints OK when any later arm is analysed. Any
change after the freeze is an amendment: append it to §12 with its date and reason, never edit §0-§11, and add a
dated `amended` line to the sidecar.

Paths: `M=/Users/pmrj/ZDone/claude-agent-stack` (main checkout), `W=$M/claude_next_steps/work_carried`,
`CD=$W/context-diet`, `A=$CD/arms/c0`.

## 0. What this supersedes, and what it keeps

- User decision, 2026-10-04 14:14 (`DECISIONS.md`, "Answers 2026-10-04 14:14"): "re-pre-register c0 on the `9b39839`
  install", replacing the compact-protocol c0 ("A arm after the Phase-1 install").
- **Superseded:** `COMPARE_compact.md` §1 (the c0 row only), §2 (the choice of optional blocks: all of them are now
  required, §2 below) and §8 (the configuration snapshot); `RUNBOOK_A_ARM.md` §0-§1 (Phase-1 preconditions and install)
  and §3-§4 (replaced by §5 here, which adds the per-dispatch check).
- **Kept by reference, unchanged:** `COMPARE_compact.md` §3-§7 and §9-§10 (data sources, metrics M1-M8, schema 1.2.0,
  decision rules, BEFORE contrasts, confounds, analysis procedure) and `stats_before/COMPARE.md` (P1-P4, §4
  denominators, §6 reading). Both stay byte-identical; their hashes are pinned in §4. `COMPARE_compact.md` gets no
  amendment from this file (that would change its sidecar).
- **Feeds:** the compact-protocol contrast c1 vs c0, and the context-diet program (plan.md "ORDER AND ARMS": c0 is the
  clean baseline before P2/c1 and the diet arm). `COMPARE_diet.md` (plan B0) pre-registers its own arm against c1.

## 1. The arm: c0 = the installed stack at manifest commit `a22c5b4`

| item | value | how it was checked (2026-10-04 15:4x) |
|---|---|---|
| installed manifest commit | `a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f` | `jq -r .commit ~/.claude/.stack-manifest.json` (manifest mtime 2026-10-04 15:21) |
| same agent behaviour as `9b39839` | yes | `git diff --quiet 9b39839 a22c5b4 -- dot-claude` exits 0; the two commits (`845296b`, `a22c5b4`) touch only `install.sh`, `lib/devtools.sh`, two tests, `tests/install_smoke.sh`, `CONFIG.md`, `README.md` (7 files, +372/-49) |
| installed files = manifest | 485/485, 0 drift | two routes: a Python sha256 pass over `files`, and `jq … \| shasum -a 256 -c` |
| manifest files digest | `b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886` | `jq -cS .files ~/.claude/.stack-manifest.json \| shasum -a 256` |
| manifest vs git | of 485 manifest entries, 483 exist under `dot-claude/` at both revisions: 394 byte-identical, the same 89 differ for `9b39839` and for `a22c5b4` (cause not checked; presumably install-time rewriting, e.g. agent files); 2 exist only in the install | sha256 of each `git show <rev>:dot-claude/<path>` blob vs the manifest |
| Phase 1 (observe mode) | included | `94b8f1b`, `ba7304f`, `b302cc6`, `acbbefa` are ancestors of `9b39839`; `STACK_REPORT_FORMAT` default `observe` (`CONFIG.md:148` at `a22c5b4`) |
| `READ_GATE_CLAUDE_WORK_BYTES` | does not exist at `a22c5b4` | `git grep` at `a22c5b4`: no hit. Not set in c0 |

- **Known difference from a `9b39839` install:** only the toolchain the installer may have added (`--with-lsp`: jdtls and
  other LSP servers). That is environment, not stack files. §5 step 2 records which LSP servers are on PATH.
- **Not in c0:** the delegate-only work (plan step 2) and anything else merged to `main` after `a22c5b4`. `main` may move
  during the arm. That is allowed, because the arm pins the *installed* stack, and `M` tracks no project-level Claude
  configuration (`git ls-files` has no `CLAUDE.md`, `.mcp.json` or `.claude/` settings). The gitStatus block in each
  prompt does change with `main`: `main_head` is logged per dispatch.
- **Rule:** no `./install.sh` (in any mode that writes), no `stack.env` edit and no `/model` or effort change from the
  configuration record (§5 step 2) until the c0 collection (§5 step 7) is done. User decision Q1: hold install until c0
  is collected.

## 2. Prompt set (all 17 required, fixed order)

Prompt text and rubric: `$W/stats_before/inputs/baseline/prompts.csv` (sha256 in §4), unchanged. Hash per prompt =
sha256(`prompt` + U+001F + `check`)[:12], recomputed 2026-10-04: 17/17 equal to `COMPARE_compact.md` §2.

| order | id | block | agent | class | size | hash | network |
|---|---|---|---|---|---|---|---|
| 1 | P90 | O | orchestrator | orchestrated | L | `f38854616453` | no |
| 2 | P91 | O | orchestrator | orchestrated | L | `ffcd774409b8` | no |
| 3 | P92 | O | orchestrator | orchestrated | L | `6338ae553461` | no |
| 4 | P93 | O | orchestrator | orchestrated | L | `1f4458391d5e` | no |
| 5 | P96 | O | orchestrator | orchestrated | L | `42968e3e7427` | no |
| 6 | P94 | O+ | orchestrator | orchestrated | L | `6db200b4fa7b` | no (Blender may be absent; the rubric accepts an honest missing-tool report) |
| 7 | P99 | O+ | orchestrator | orchestrated | L | `95d916d31cb7` | yes |
| 8 | P19 | S | scout | lookup | S | `4cc018698443` | yes |
| 9 | P04 | S | oracle | lookup | S | `3aa33e1335b5` | no |
| 10 | P21 | S | claude-code-guide | lookup | S | `f8b304883639` | yes |
| 11 | P07 | S | security-auditor | review | S | `5c8af133ea92` | no |
| 12 | P10 | S | proof-checker | review | S | `3c2bcfb50d29` | no |
| 13 | P41 | S | planner | plan | M | `bbfe7b0dd138` | no |
| 14 | P42 | S | plan-reviewer | review | M | `a33118b6a202` | no |
| 15 | P11 | S | build-fixer | builder | S | `77ae17a53be4` | no |
| 16 | P30 | S | python-engineer | builder | M | `1c0d16790ee6` | no |
| 17 | P44 | S | frontend-engineer | builder | M | `8d10d6aabc3e` | no |

- Why all 17: block O+ raises the orchestrated n from 5 to 7 (with 5 prompts no sign test can reach p < 0.05; §8), and
  block S gives single-agent spawns of 10 types for the diet metrics (per-type spawn prefix, tool use, turns) and the
  hand-back classes block O rarely produces. All 11 agent types exist in the installed roster (`~/.claude/agents/`).
- Excluded, as before: P95 (needs P78's output, which never ran) and P97 (held: `git init` under `.claude-work` is a
  user decision).
- Every later arm that is compared with c0 runs the same ids in the same order, with the same message template (§5
  step 4) and only the label changed.

## 3. Labels

- Agent description `<PID> c0 run <agent>` (e.g. `P90 c0 run orchestrator`), as `COMPARE.md` §2 and
  `COMPARE_compact.md` §1. `a1` is never used (reserved for the Bayesian AFTER).
- A re-run is allowed only for an environment failure (§7), at most once per prompt, declared in §12 before it is
  dispatched, with the label `c9` (`P90 c9 run orchestrator`). The analysis uses the `c9` run in place of the failed
  `c0` run and lists it. Its check: `C0_ORDER_OVERRIDE=1 bash …/c0_check.sh <PID> <uuid>`; in the printed message every
  `c0` becomes `c9` (the only edit ever made to a message).
- **Label clash to resolve outside this file:** `COMPARE_compact.md` §1 uses `c2` for the optional read-gate arm, and the
  context-diet plan (B0) uses `c2` for the diet arm. c0 uses neither; `COMPARE_diet.md` must pick distinct labels.

## 4. Pinned inputs (sha256, computed 2026-10-04)

| file (under `$W`) | sha256 |
|---|---|
| `stats_before/inputs/baseline/prompts.csv` | `2d8bb00aa4e67d4654d18c0aea8f88c319e947c375385495698b9ac038ee364e` |
| `stats_before/tools/collect_b0v2.py` (the frozen collector) | `71710cf73f40c30e4e880cc30824db7820b0a95eb67444bbb197e17f22946689` |
| `compact-protocol/measurement/extract_child_finals.py` | `847b8bfff5a7d70f0241436126f1b83e5204511ce130360465508efb903b38c4` |
| `stats_before/tools/manifest.py` | `7a47f4fa871c9ddc9524fb3f137b83dad61ad3c567766b0a684e985173f74e0b` |
| `stats_before/COMPARE.md` | `a894da025a6640b74d7013aa29ef596bc231e40d9905b447336cca8a2f122dca` |
| `compact-protocol/measurement/COMPARE_compact.md` | `6b540f5221fb538e8923e8877a02aedd8c5607d0cd68d87dfcc2f1e9f098421a` (matches its sidecar) |
| `context-diet/plan.md` | `872849aa495d723b424bbbbba05d188102c310f2c1a9ae3c74342dac2a4446f7` |

`c0_check.sh` re-verifies the first three before every dispatch (C5). The pre-diet transcripts (sessions 4e2da3ce,
fae82d02, e4fe4e24, a59eca09, 68541e7b) are frozen by the same `freeze.sh` run, with `MANIFEST.sha256` and
`FROZEN_AT.txt` in `$CD/data/`.

## 5. Procedure (the user runs it; one fresh session, one prompt at a time)

1. **Preconditions** (stop if one fails): `freeze.sh` has run (`$CD/data/FROZEN_AT.txt` and `$CD/COMPARE_c0.sha256`
   exist); no other Claude Code session is running agents; nothing has been installed since `a22c5b4`.
2. **Record the configuration** before the first dispatch (`c0_check.sh` refuses to pass without this file):

   ```sh
   A=/Users/pmrj/ZDone/claude-agent-stack/claude_next_steps/work_carried/context-diet/arms/c0
   mkdir -p $A/inputs
   {
     echo "label: c0"; echo "recorded_utc: $(date -u '+%FT%TZ')"
     echo "claude_version: $(claude --version | head -1)"
     echo "stack_commit: $(jq -r .commit ~/.claude/.stack-manifest.json)"
     echo "manifest_files_digest: $(jq -cS .files ~/.claude/.stack-manifest.json | shasum -a 256 | awk '{print $1}')"
     echo "main_head: $(git -C /Users/pmrj/ZDone/claude-agent-stack rev-parse HEAD)"
     echo "stack_env_sha256: $(shasum -a 256 ~/.claude/stack.env | awk '{print $1}')"
     grep -E '^(STACK_REPORT_FORMAT|STACK_SCHED_POLICY|STACK_LIMITS_SNAPSHOT|STACK_POLICY)=' ~/.claude/stack.env
     echo "settings: $(jq -c '{defaultMode: .permissions.defaultMode, agent, model, effortLevel, autoCompactWindow}' ~/.claude/settings.json)"
     echo "permission_mode_at_launch: acceptEdits"
     echo "lsp_on_path: $(for s in jdtls pyright-langserver typescript-language-server rust-analyzer kotlin-lsp; do command -v $s >/dev/null && printf '%s ' $s; done)"
     echo "agents (model effort maxTurns):"
     for f in ~/.claude/agents/*.md; do printf '  %s %s\n' "$(basename "$f" .md)" "$(grep -m3 -E '^(model|effort|maxTurns):' "$f" | tr '\n' ' ')"; done
   } > $A/CONFIG.txt
   ```

   The file holds the sha256 of `stack.env`, not its contents (it may hold keys), plus the four knob lines above.
3. **Start the session:** `cd /Users/pmrj/ZDone/claude-agent-stack && claude --permission-mode acceptEdits`. The flag
   overrides the user default `plan` (in Plan mode builders cannot edit); every later arm uses the same flag. Note the
   session id after the first prompt (`/status`, or the newest `*.jsonl` in
   `~/.claude/projects/-Users-pmrj-ZDone-claude-agent-stack/`).
4. **Before every dispatch**, in a separate terminal (never `!` inside the arm session):
   `bash /Users/pmrj/ZDone/claude-agent-stack/claude_next_steps/work_carried/context-diet/c0_check.sh <PID> [<session uuid>]`
   (the uuid from prompt 2 on; it turns the concurrent-session check C9
   from a warning into a failure). It checks C1 the installed manifest commit, C2 the manifest files digest, C3 the
   installed files against the manifest, C4 this file's sidecar, C5 the pinned inputs, C6 that the PID is the next one
   in §2 order (or a re-check of the last PASS), C7 the Claude Code version and C8 the `stack.env` hash against `CONFIG.txt`, C9 no other session active
   in the last 15 minutes. It appends a PASS/FAIL line to `$A/DISPATCH_LOG.tsv`. On PASS it prints the message (also in
   `$A/messages/<PID>.txt` and the clipboard); send it unedited, wait for BlackCat's final relay, then check the next
   PID. The template (identical to `RUNBOOK_A_ARM.md` §4; only the label differs between arms):

   ```
   Measurement arm c0, prompt <PID>. Dispatch exactly one <agent> subagent with the Agent description "<PID> c0 run <agent>". Forward the task below verbatim. Work directory: /Users/pmrj/ZDone/claude-agent-stack/.claude-work/compact-ab/c0/<PID>/ (create it). Do none of the work yourself, add no requirements, and relay its result when it finishes.
   TASK: <prompt cell of prompts.csv, verbatim>
   ```
5. **During the arm:** an agent's `NEXT: ASK USER` gets exactly `Proceed with your recommended option.` (note the PID in
   `$A/NOTES.txt`). No `/compact`; note any auto-compaction (PID, time). No `/model`, effort or `stack.env` change. A
   failed run is data and is not re-run, except under §7.
6. **After the last relay**, exit the session.
7. **Collect, then freeze** (before any install; the collector reads the installed `~/.claude/agents` for `max_turns`
   and skills):

   ```sh
   M=/Users/pmrj/ZDone/claude-agent-stack; W=$M/claude_next_steps/work_carried; A=$W/context-diet/arms/c0
   SID=<c0 session uuid>; OUT=$A/inputs/collected_${SID:0:8}
   mkdir -p $OUT
   cp $W/stats_before/inputs/baseline/prompts.csv $OUT/
   head -1 $W/stats_before/inputs/baseline/grades.csv > $OUT/grades.csv
   uv run --script $W/stats_before/tools/collect_b0v2.py --session $SID --campaign-since none --repo $M --out $OUT
   uv run --script $W/compact-protocol/measurement/extract_child_finals.py --session $SID --collected $OUT --repo $M
   cp ~/.local/state/claude-agent-stack/usage/reports.jsonl ~/.local/state/claude-agent-stack/usage/runs3.csv $A/inputs/
   cp $A/CONFIG.txt $A/DISPATCH_LOG.tsv $A/inputs/; [ -f $A/NOTES.txt ] && cp $A/NOTES.txt $A/inputs/
   bash $W/context-diet/freeze.sh --arm c0 $SID   # the arm's transcripts -> $M/.claude-work/context-diet/data/arms/c0/,
                                                  # MANIFEST.sha256 + FROZEN_AT.txt -> $A/transcripts/
   cd $A/inputs && { echo "frozen_at_utc: $(date -u '+%FT%TZ')"; echo "label: c0"; echo "session: $SID"; } > FROZEN_AT.txt \
     && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256
   ```

   `--campaign-since none` is right because the session is fresh. The collector prints the prompt-id count and the open
   segments: expect 17 ids (or the number dispatched) and 0 open segments; if one is open, wait and rerun the two
   collector commands. Never edit `$A/inputs/` afterwards.

## 6. Metrics (computed on c0 now, contrasted later)

Run = (session, prompt_id, label) with all segments carrying that prompt tag (`COMPARE.md` §4); segment and turn as the
collector defines them. Pairing unit for contrasts = prompt id. log2 ratios are arm/c0.

**From `COMPARE_compact.md` §4, unchanged:** M1 report_chars per hand-back (primary for c1 vs c0), M1a-M1c, M2 tokens
per run split into input / cache_read / cache_write / output (primary), M3 pass rate, M4 parent-carried tokens
(estimate), M5 tokens per orchestrated job (blocks O and O+), M6 format compliance and would-restate rate (observe mode),
M7 E-flag precision, M8 (zero in c0 by construction).

**Context-diet metrics (new; descriptive at c0, secondary in contrasts):**

| # | metric | route 1 | route 2 (must agree) | estimator |
|---|---|---|---|---|
| D1 | first-call context per spawn, by agent type: `first_cc`, `first_cr`, `first_ctx` | `runs3.csv` rows of the arm session (last row per segment) | the first API call's usage in each `subagents/agent-*.jsonl` (frozen copy) | median, p10, p90 per type; n shown |
| D2 | API calls per segment and per run; `turn_limited`, `hit_turn` rates | collector `turns`, `hit_max_turns` | `runs3.csv` `api_calls`, `turn_limited`, `hit_turn` | median per run; Wilson for rates |
| D3 | tool calls per run by tool; tools allowlisted but unused per type | collector `tools` | `runs3.csv` `n_*` columns | counts; unused = tools line at `a22c5b4` (`git show a22c5b4:dot-claude/agents/<type>.md`) minus tools used, n runs stated |
| D4 | cache share per segment = cache_read / (input + cache_creation + cache_read) | collector token columns | `runs3.csv` | median per type |
| D5 | resume share (segments with `resume=1`; `cold`) | `runs3.csv` | collector `nsegs` > 1 | k/n, Wilson |
| D6 | brief_chars per dispatch | ledger (`reports.jsonl` / registry, Phase 1) | the Agent tool_use `prompt` length in the parent transcript | median per type |
| D7 | cap hits: `hit_soft`, `hit_turn`, `compacted` | `runs3.csv` | collector `soft_limit_hits`, `hit_max_turns`, `compactions` | k/n, Wilson (= `COMPARE.md` P3) |
| D8 | wall time per run | collector `wall_s` (root) | `runs3.csv` `wall_s` | median (= `COMPARE.md` P4) |

**Pin verification (route 2 of the arm definition), before any number is reported:** every `runs3.csv` row with
`session == SID` has `stack_commit == a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f`; for every dispatched PID,
`DISPATCH_LOG.tsv` has a `PASS` line for it that is earlier than its root `start` in `runs.csv`, with no `FAIL` of C1, C2, C3,
C7 or C8 between that `PASS` and the `start`, and the first `PASS` of the arm is later than the sidecar's `frozen_at_utc`. A prompt that fails any of these is excluded from every c0 statistic and listed.

**Grading (M3, M7).** Grader: agent type `verifier`; rubric = the `check` column; vocabulary pass|partial|fail|tool-absent;
CSV `id,check_result,why`; the brief saved word for word as `$A/grader_brief.md`. Preferred: c0 is graded together with
the first comparison arm in one blinded batch (run dirs relabelled, order randomised with seed 20261004). If c0 is graded
on its own first (plan step 6), the same brief is reused word for word later, and the later batch re-grades a random half
of the c0 runs (seed 20261004) blinded among the new ones; grader agreement (Cohen's kappa, n) is reported and, if
kappa < 0.6, all c0 grades from the later batch replace the earlier ones.

## 7. Stop rules

- **Per dispatch:** any `c0_check.sh` FAIL means do not dispatch. C6, C9: fix (wait for the other session to end, send
  the right PID) and run the check again.
- **Arm stop (the remaining prompts are not run and are reported as missing):** C1, C2 or C3 fails (an install or an
  edit changed the stack: irrecoverable for c0); C7 fails (the session restarted on another Claude Code version: stop,
  and continue only after a §12 amendment that splits the arm by version); C8 fails (stack.env changed: stop; continue
  only after restoring the file to the recorded hash, with a §12 note); the session hits its hard token cap.
- **Environment failure** (API outage, harness crash, a run killed by something outside the stack): note it in
  `NOTES.txt`; one declared re-run labelled `c9` (§3). Model errors, refusals, wrong answers, tool absence, hook
  denials and cap hits are not environment failures: they are data.
- **No early stop for results.** c0 is a baseline with no treatment, so nothing is tested during the arm and no result
  stops it. A partial arm is analysed on the prompts completed, with the intersection rule of `COMPARE.md` §4.

## 8. Contrasts against c0 and how to read them

- **c1 vs c0 (compact protocol):** exactly `COMPARE_compact.md` §4, §6 and §10, with c0 as defined here. Seeds as there
  (`20261003 ^ sha256("compact|<metric>")[:8]`).
- **Any later arm X vs c0** (the diet arm, or the installed stack after the delegate-only and simplification work):
  primary `COMPARE.md` P1 (tokens_total, paired log2, median over prompts, percentile bootstrap over prompts,
  B = 10000, seed = `20261004 ^ int(sha256("c0|X|P1")[:8], 16)`), P2 pass rate (Wilson; exact McNemar on discordant
  pairs), P3 cap-hit rate, P4 wall time; D1-D8 secondary, per type, descriptive.
- **Reading** (`COMPARE.md` §6): measured only when the 95 % interval excludes 0 or McNemar p < 0.05, with n stated;
  otherwise "no measured difference at this n". Sign-test reach (exact, two-sided, all at p < 0.05): 7 orchestrated
  prompts need 7/7 in one direction (p = 0.0156); the 10 single-agent prompts need 9/10 (p = 0.021); all 17 need 13/17
  (p = 0.049); 5 prompts can never reach it. Expect M2, M5, D1-D8 to stay descriptive unless the effect is large and
  uniform.
- **Attribution.** Everything that lands between c0 and X is part of the contrast. Every X-vs-c0 table states
  `git diff --stat a22c5b4 <X's manifest commit> -- dot-claude`, the Claude Code versions and models of both arms, and is
  labelled with the whole change set. One arm cannot attribute an effect to one change. The BlackCat delegate-only
  change affects BlackCat's main thread, which the collector does not count (no main-thread row), so its effect on
  subagent metrics is expected to be small but is not assumed to be zero.
- **BEFORE** (`stats_before/`, sessions 4e2da3ce and fae82d02) vs c0 is cross-install only, labelled confounded
  (`COMPARE_compact.md` §7).
- **Censoring:** runs with `hit_max_turns = 1` or `soft_limit_hits > 0` stay in; listed per arm; P1/M2 are repeated
  without them.
- **Cost:** only with the dated price table of `COMPARE_compact.md` §4 (fetched 2026-10-03); re-fetch and record the date
  if any compared arm runs after 2026-10-31.

## 9. Confounds inside c0 (recorded, not controlled)

- One session for 17 prompts: BlackCat's context grows from prompt to prompt and may auto-compact (window 629,000).
  Subagent prefixes do not carry BlackCat's history, but the order is fixed, so position and prompt are confounded; later
  arms keep the same order.
- One run per prompt: within-prompt variance is unknown (as in `COMPARE_compact.md` §9).
- The gitStatus block in each spawn varies with `main` (logged per dispatch as `main_head`).
- Learned limits may move during the arm (stack behaviour, not an intervention): the `snap` and `regime` values per
  segment are reported. At drafting, the newest `runs3.csv` row had snap `6e386b5db4a2089a`, regime `26f4f120e1cc7b6a`.
- Network prompts (P99, P19, P21) depend on the web at run time.

## 10. Configuration snapshot at drafting (not the arm configuration; §5 step 2 records that)

Claude Code 2.1.287. Installed manifest `a22c5b4` (written 2026-10-04 15:21). User settings: `permissions.defaultMode`
`plan`, `agent` `blackcat`, `autoCompactWindow` 629000, `autoCompactEnabled` true; `cleanupPeriodDays` unset (default 30
days). Manifest `settings_env`: `BLACKCAT_MAX_DISPATCH` 8, `BLACKCAT_MAX_STEPS` 24, `BLACKCAT_DISPATCH_WINDOW_S` 120,
`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS` 128, `CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH` 8, `ANTHROPIC_DEFAULT_OPUS_MODEL`
claude-opus-5-5, `ANTHROPIC_DEFAULT_SONNET_MODEL` and `ANTHROPIC_DEFAULT_HAIKU_MODEL` claude-sonnet-5-5. Frontmatter
(model / effort / maxTurns): blackcat sonnet/medium; orchestrator opus/high/200; scout sonnet/low/11; oracle opus/low/12;
claude-code-guide sonnet/low/30; security-auditor opus/xhigh/100; proof-checker opus/xhigh/80; planner opus/xhigh/60;
plan-reviewer opus/high/60; build-fixer sonnet/low/60; python-engineer opus/high/170; frontend-engineer
opus/medium/170; coder sonnet/medium/170; writer opus/medium/80; verifier sonnet/high/140.

## 11. Analysis outputs

`$A/inputs/` (frozen as §5 step 7), then `$CD/arms/c0/stats/`: the compute script (schema 1.2.0 of `COMPARE_compact.md`
§5, extended with D1-D8 columns; `SEED`, `B`, `MIN_N_CI`, `Z`, the quantile method and every regex byte-identical to
`stats_before/compute_stats.py` except the 1.2.0 changes) and an independent second-route script (`runs3.csv` +
`reports.jsonl` + transcripts). Both must pass before any number is reported. The c0 report gives n per cell and keeps
every caveat above.

## 12. Amendments (dated; append only)

- (none)
