# RUNBOOK c0: collect the baseline arm (the user runs every command; it is paid)

Re-derived 2026-10-05 after the loss of the original `RUNBOOK_c0.md` (worktree T was removed). Sources: the original
text recovered verbatim from the session transcripts, `COMPARE_c0.md` §5/§7, `freeze.sh`, `c0_check.sh` (all four read
in full), `HANDOFF_STATE.md` §5-§6. One command per block; paste them in order in one terminal. Not run by the author:
every step that installs, calls `claude`, or writes under `~/.claude`. Marks: **[v]** read in code or run read-only,
**[unverified]** not checkable from the agent sandbox.

c0 = the pre-registered baseline of the context-diet campaign: the installed stack at commit `a22c5b4`, 17 prompts in a
fixed order, one fresh session, then frozen. Cost: 17 real prompts through BlackCat and its children (large). The Docker
part of the old plan is dropped (Apple `container` replaced Docker, HANDOFF_STATE §6.1).

## 0. Read first

1. Order is fixed: **A** reinstall `a22c5b4` (a downgrade), **B** verify, **collect** (c0 itself), **C** back to main.
   Do not install main between A and C: `COMPARE_c0.md` §1 and §7 treat any install or `stack.env` edit during the arm as
   an arm stop.
2. **The inputs are gone from disk [v, 18:3x].** `/Users/pmrj/ZDone/claude-agent-stack/claude_next_steps/` does not
   exist now (git-ignored; commit `7e47dfb` "Trimmed folder"). `COMPARE_c0.md`, `c0_check.sh`, `freeze.sh` and
   `extract_child_finals.py` were recovered from the transcripts into `hand_off/c0_support/`; `COMPARE_c0.md`,
   `c0_check.sh` and `extract_child_finals.py` match the pinned sha256 byte for byte [v]; `freeze.sh` has no pin, so
   its exactness is [unverified] (last full read 2026-10-04 17:43, after the last edit). `prompts.csv` and
   `collect_b0v2.py` match their pins in `M/.claude-work/step6-data/stats_before_v1.1/` [v]. Section 1 rebuilds the tree.
   The old `data/` tables (FROZEN_AT, 17 files) are not needed by the arm; the pre-diet transcripts themselves survive in
   `M/.claude-work/context-diet/data/transcripts` [v].
3. **C2 risk (read before A).** At `a22c5b4` the installer renders the repo path into three installed files
   (`agents/claude-code-engineer.md`, `agents/mcp-broker.md`, `skills/mcp-server-craft/references/from-mcp-broker.md`:
   `__STACK_REPO__`) [v: `git grep` at `a22c5b4`], and the manifest `files` digest hashes the rendered files [v:
   `install.sh` at `a22c5b4`, `files_entry[rel] = rendered_hash`]. The pin `b6f957f3...` was taken from an install made at
   some path; the installer always re-executes from the checkout where `main` lives, so that path was very probably
   `/Users/pmrj/ZDone/claude-agent-stack` [unverified]. Installing from the throwaway clone of section A therefore makes
   C2 of `c0_check.sh` FAIL (C3 will pass), and C2 failing is an arm stop (`COMPARE_c0.md` §7). Section B tells you what to
   do; the way out is a dated §12 amendment that re-pins the digest, which is your decision, not a command here.
4. `a22c5b4` is an ancestor of `7d12c58` and of main [v]. The installed manifest is `7d12c58` [r: HANDOFF_STATE §1; check
   in step 1.1]. Between `a22c5b4` and `7d12c58` 28 files under `dot-claude/` change (blackcat.md, agent_guard.py,
   stack_hook.py, stack_limits.py, stack_sched.py, settings.json, the `mcp-server-craft` skill comes back, ...) [v: `git
   diff --name-status a22c5b4 7d12c58 -- dot-claude`]. The installer backs up everything it changes or removes into
   `~/.local/state/claude-agent-stack-backups/<timestamp>-*/`.
5. Use a session for c0 only; quit every other Claude Code session before A3 (shared rate limits and hook state).
6. The install flags you used last time are not recorded in the manifest [unverified]; add `--with-lsp` or others to the
   two `install.sh` lines of A and C only if you used them.

## 1. Preflight and rebuild the c0 input tree

Variables (the later blocks assume them in the same terminal):

```sh
export M=/Users/pmrj/ZDone/claude-agent-stack W=/Users/pmrj/ZDone/claude-agent-stack/claude_next_steps/work_carried
```

```sh
export CD=$W/context-diet A=$W/context-diet/arms/c0 SUP=$M/hand_off/c0_support X=$M/.claude-work/step6-data/stats_before_v1.1
```

1.1 What is installed now (expect `7d12c58...`):

```sh
jq -r .commit ~/.claude/.stack-manifest.json
```

1.2 The support files must be on main (they arrive with the `hand_off` merge); stop if this lists fewer than five files:

```sh
ls $SUP
```

1.3 Create the tree (only new folders under the git-ignored `claude_next_steps/`):

```sh
mkdir -p $CD $W/stats_before/inputs/baseline $W/stats_before/tools $W/compact-protocol/measurement
```

```sh
cp $SUP/COMPARE_c0.md $SUP/c0_check.sh $SUP/freeze.sh $CD/
```

```sh
cp $SUP/extract_child_finals.py $W/compact-protocol/measurement/
```

```sh
cp $X/inputs/baseline/prompts.csv $X/inputs/baseline/grades.csv $W/stats_before/inputs/baseline/
```

```sh
cp $X/tools/collect_b0v2.py $W/stats_before/tools/
```

1.4 Verify the five pinned files (all five lines must say OK; this check was run on a scratch copy and passed [v]):

```sh
cd $W && shasum -a 256 -c $SUP/PINS.sha256
```

1.5 Pre-registration sidecar (what `freeze.sh` default mode used to write; `c0_check.sh` C4 reads it) and read-only copies:

```sh
cd $CD && shasum -a 256 COMPARE_c0.md c0_check.sh freeze.sh > COMPARE_c0.sha256
```

```sh
cd $CD && chmod a-w COMPARE_c0.md c0_check.sh freeze.sh COMPARE_c0.sha256
```

1.6 The frozen pre-diet transcripts must exist (they are what the diet analysis reads later; the arm does not need them):

```sh
ls $M/.claude-work/context-diet/data/transcripts
```

## A. Reinstall a22c5b4 in a throwaway clone

Why a clone: at `a22c5b4` the installer installs only from a branch named `main`; started from a detached checkout it
fast-forwards nothing and re-runs itself from `$M`, i.e. it would install current main [v: `install.sh` at `a22c5b4`,
`main_branch_rule`]. A clone whose own `main` is set to `a22c5b4` touches neither `$M` nor any worktree. It never pushes.

A1 Clone and pin (reads `$M`, writes only `$D`; the `git` steps are [unverified] here, the agent sandbox refuses git on
another path):

```sh
export D=$HOME/c0-a22c5b4
```

```sh
git clone "$M" "$D"
```

```sh
git -C "$D" checkout -q -B main a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f
```

```sh
git -C "$D" rev-parse HEAD
```

The line above must print `a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f`; this must print nothing:

```sh
git -C "$D" status --porcelain
```

A2 Preview, writes nothing (needs the clone on `main`, which it is):

```sh
cd "$D" && ./install.sh --dry-run
```

Optional, read-only: what differs between the clone's `dot-claude/` and what is installed now:

```sh
cd "$D" && ./install.sh --diff
```

A3 Quit every Claude Code session, then install:

```sh
cd "$D" && ./install.sh --yes
```

Restart nothing yet; section B runs without a session. Undo at any time: `cd $M && ./install.sh --restore` (the backups
are in `~/.local/state/claude-agent-stack-backups`). Keep `$D` until section C.

## B. Verify before the first dispatch

```sh
jq -r .commit ~/.claude/.stack-manifest.json
```

Must print `a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f`.

```sh
jq -cS .files ~/.claude/.stack-manifest.json | shasum -a 256
```

Must start `b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886`. If the commit is right and this differs,
look at whether it is the path effect of §0.3 (this lists the installed files that carry the clone path; expect exactly
the three named there):

```sh
grep -rl "$D" ~/.claude/agents ~/.claude/skills
```

Three files and a differing digest: stop and tell the orchestrator (ASK USER: re-pin by a dated `COMPARE_c0.md` §12
amendment, then new sidecar hashes via `freeze.sh`'s documented procedure). Do not edit the pins yourself, and do not
dispatch.

Record the configuration (`c0_check.sh` refuses to pass without it; `stack.env` is hashed, never copied):

```sh
mkdir -p $A/inputs
```

```sh
{
  echo "label: c0"; echo "recorded_utc: $(date -u '+%FT%TZ')"
  echo "claude_version: $(claude --version | head -1)"
  echo "stack_commit: $(jq -r .commit ~/.claude/.stack-manifest.json)"
  echo "manifest_files_digest: $(jq -cS .files ~/.claude/.stack-manifest.json | shasum -a 256 | awk '{print $1}')"
  echo "main_head: $(git -C $M rev-parse HEAD)"
  echo "stack_env_sha256: $(shasum -a 256 ~/.claude/stack.env | awk '{print $1}')"
  grep -E '^(STACK_REPORT_FORMAT|STACK_SCHED_POLICY|STACK_LIMITS_SNAPSHOT|STACK_POLICY)=' ~/.claude/stack.env
  echo "settings: $(jq -c '{defaultMode: .permissions.defaultMode, agent, model, effortLevel, autoCompactWindow}' ~/.claude/settings.json)"
  echo "permission_mode_at_launch: acceptEdits"
  echo "lsp_on_path: $(for s in jdtls pyright-langserver typescript-language-server rust-analyzer kotlin-lsp; do command -v $s >/dev/null && printf '%s ' $s; done)"
  echo "agents (model effort maxTurns):"
  for f in ~/.claude/agents/*.md; do printf '  %s %s\n' "$(basename "$f" .md)" "$(grep -m3 -E '^(model|effort|maxTurns):' "$f" | tr '\n' ' ')"; done
} > $A/CONFIG.txt
```

Dry run of the gate with no session running (appends one PASS or FAIL line to `$A/DISPATCH_LOG.tsv`, and on PASS writes
`$A/messages/P90.txt` and copies it to the clipboard). C1-C4 must PASS, C5-C8 should; C9 may only WARN without a uuid:

```sh
bash $CD/c0_check.sh P90
```

## Collect c0

The 17 prompts, in this order (agent in brackets): P90 P91 P92 P93 P96 (orchestrator), P94 P99 (orchestrator; P99 needs
network, P94 may report Blender absent), P19 (scout, network), P04 (oracle), P21 (claude-code-guide, network), P07
(security-auditor), P10 (proof-checker), P41 (planner), P42 (plan-reviewer), P11 (build-fixer), P30 (python-engineer),
P44 (frontend-engineer) [v: `COMPARE_c0.md` §2].

Start the arm session in the main checkout (the flag overrides your default mode `plan`, in which builders cannot edit):

```sh
cd $M && claude --permission-mode acceptEdits
```

Note the session uuid after the first prompt (`/status`, or the newest `*.jsonl` in
`~/.claude/projects/-Users-pmrj-ZDone-claude-agent-stack/`). For EVERY prompt, in a SEPARATE terminal (never `!` inside
the arm session; the variables above must be exported there too), run the gate with the PID and, from prompt 2 on, the
session uuid (the second argument turns C9, another active session, from a warning into a failure):

```sh
bash $CD/c0_check.sh <PID> <session uuid>
```

PASS prints the exact message (also in `$A/messages/<PID>.txt` and on the clipboard). Send it unedited into the arm
session, wait for BlackCat's final relay, then gate the next PID. FAIL: do not dispatch (`COMPARE_c0.md` §7: C6 and C9
are fixable by waiting or sending the right PID; C1, C2, C3, C7, C8 stop the arm).

During the arm: an agent's `NEXT: ASK USER` gets exactly `Proceed with your recommended option.` and the PID goes into
`$A/NOTES.txt`; no `/compact` (note any auto-compaction with PID and time); no `/model`, effort or `stack.env` change; a
failed run is data and is not re-run (only a declared environment failure, label `c9`, `COMPARE_c0.md` §3/§7). After the
last relay, exit the session.

Collect then freeze, before any install (the collector reads the installed `~/.claude/agents`):

```sh
export SID=<c0 session uuid>
```

```sh
export OUT=$A/inputs/collected_${SID:0:8}
```

```sh
mkdir -p $OUT
```

```sh
cp $W/stats_before/inputs/baseline/prompts.csv $OUT/
```

```sh
head -1 $W/stats_before/inputs/baseline/grades.csv > $OUT/grades.csv
```

```sh
uv run --script $W/stats_before/tools/collect_b0v2.py --session $SID --campaign-since none --repo $M --out $OUT
```

```sh
uv run --script $W/compact-protocol/measurement/extract_child_finals.py --session $SID --collected $OUT --repo $M
```

Expect 17 prompt ids and 0 open segments; if a segment is open, wait and rerun the two commands above.

```sh
cp ~/.local/state/claude-agent-stack/usage/reports.jsonl ~/.local/state/claude-agent-stack/usage/runs3.csv $A/inputs/
```

```sh
cp $A/CONFIG.txt $A/DISPATCH_LOG.tsv $A/inputs/
```

```sh
[ -f $A/NOTES.txt ] && cp $A/NOTES.txt $A/inputs/
```

Freeze the arm's transcripts (copies to `$M/.claude-work/context-diet/data/arms/c0/`, writes `MANIFEST.sha256` and
`FROZEN_AT.txt` into `$A/transcripts/`; refuses to overwrite an earlier freeze; exit 3 = done but a session was missing):

```sh
bash $CD/freeze.sh --arm c0 $SID
```

```sh
cd $A/inputs && { echo "frozen_at_utc: $(date -u '+%FT%TZ')"; echo "label: c0"; echo "session: $SID"; } > FROZEN_AT.txt
```

```sh
cd $A/inputs && find . -type f ! -name MANIFEST.sha256 -print0 | sort -z | xargs -0 shasum -a 256 > MANIFEST.sha256
```

Never edit `$A/inputs/` afterwards. Then tell the orchestrator the session uuid and that `$A/inputs/FROZEN_AT.txt` exists.

## C. Back to main (the same reinstall as HANDOFF_STATE §5)

Only when `orch-bash` is merged into main and C10 passes on main (otherwise the install gives an orchestrator without
`Bash`); quit every Claude Code session first.

```sh
git -C $M log --oneline -3
```

```sh
cd $M && git status --short | head
```

```sh
cd $M && ./install.sh --dry-run
```

```sh
cd $M && ./install.sh --yes
```

```sh
jq -r .commit ~/.claude/.stack-manifest.json
```

Must equal `git -C $M rev-parse HEAD`:

```sh
git -C $M rev-parse HEAD
```

Remove the throwaway clone only now (your step; nothing in c0 needs it afterwards):

```sh
rm -rf "$D"
```

Fallback if something looks wrong: `cd $M && ./install.sh --restore` puts back the config as it was before the last install.

## Unverified

- `freeze.sh` byte-exactness (no pin); the clone and `checkout -B` steps (agent sandbox refused git on another path); the
  install flags of your last install; whether the pinned files digest came from an install at `$M` (§0.3); the state of
  other Claude Code sessions and of `~/.claude` (not readable from the agent sandbox); `./install.sh --diff` output.
