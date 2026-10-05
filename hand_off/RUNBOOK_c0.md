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
   do; the way out is a dated §12 amendment that re-pins the digest: decided 2026-10-05 (keep the clone flow), commands
   in section 12 below.
4. `a22c5b4` is an ancestor of `7d12c58` and of main [v]. The installed manifest is `73eec41`, whose `dot-claude/`
   equals `7d12c58`'s [v 2026-10-05; check in step 1.1]. Between `a22c5b4` and `7d12c58` 28 files under `dot-claude/`
   change (blackcat.md, agent_guard.py, stack_hook.py, stack_limits.py, stack_sched.py, settings.json, the
   `mcp-server-craft` skill comes back, ...) [v: `git diff --name-status a22c5b4 7d12c58 -- dot-claude`]. The
   installer backs up everything it changes or removes into `~/.local/state/claude-agent-stack-backups/<timestamp>-*/`.
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

1.1 What is installed now (expect `73eec41abab299278735f6ecbe9261d1f89bfb98` [v 2026-10-05, manifest at
`~/.claude/.stack-manifest.json`], or any commit whose `dot-claude/` equals `7d12c58`'s: for that commit,
`git -C $M diff --quiet 7d12c58 <commit> -- dot-claude` exits 0 [v for `73eec41`]):

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

1.5 Pre-registration sidecar and read-only copies. It follows the format `freeze.sh` default mode writes
(`freeze.sh:160-165`): the `# frozen_at_local:` and `# frozen_at_utc:` header lines come first, because the proof of
order reads `frozen_at_utc` from this file (`COMPARE_c0.md:7-9`, `:209`); `c0_check.sh` C4 checks the hash lines:

```sh
cd $CD && { echo "# frozen_at_local: $(date '+%F %T %z')"; echo "# frozen_at_utc: $(date -u '+%FT%TZ')"; echo "# written by RUNBOOK_c0 step 1.5 (inputs recovered from transcripts; freeze.sh default mode not run). Amendments: append to COMPARE_c0.md §12, then add a '# amended <date>: <reason>' line here and replace the hash lines."; shasum -a 256 COMPARE_c0.md c0_check.sh freeze.sh; } > COMPARE_c0.sha256
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

Expected from the clone install: it differs from `b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886`,
for the path reason of §0.3 (settled: section 12 below re-pins it; do not stop). This lists the installed files that
carry the clone path; expect exactly the three named in §0.3:

```sh
grep -rl "$D" ~/.claude/agents ~/.claude/skills
```

Three files and a differing digest: do section 12 now (re-pin, 2026-10-05), before the `CONFIG.txt` block below and
before any dispatch. A different number of files, or a digest that fails the section 12 proof (step 12.2): stop, do not
dispatch, tell the orchestrator.

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

## 12. Re-pin of the manifest files digest (2026-10-05)

Decision (user, 2026-10-05): keep the throwaway-clone install of section A and re-pin C2's expected digest afterwards.

Why the expected hash differs [v: `git show a22c5b4:install.sh`, `git grep __STACK_REPO__ a22c5b4 -- dot-claude`]. The
installer renders `__STACK_REPO__` as the directory it runs from (`HERE`, passed to the renderer as `REPO`), and the
manifest stores the sha256 of each rendered file (`files_entry[rel] = rendered_hash`). Exactly three shipped files
contain the placeholder:

- `agents/claude-code-engineer.md`
- `agents/mcp-broker.md`
- `skills/mcp-server-craft/references/from-mcp-broker.md`

Installed from `$D` (`$HOME/c0-a22c5b4`) they contain `$D` where the pinned install (very probably `$M`, [unverified])
had `/Users/pmrj/ZDone/claude-agent-stack`, so their three manifest hashes, and with them the `jq -cS .files` digest
`b6f957f3...`, change. The other files do not depend on the repo path. C3 (installed files match the manifest) still
passes. Where C2 reads the expected value: the line `PIN_FILES_DIGEST=` near the top of `$CD/c0_check.sh`. The copy in
`hand_off/c0_support/c0_check.sh` keeps the old value on purpose: it is pinned byte for byte (`PINS.sha256`, step 1.4);
only the `$CD` copy is amended, and `COMPARE_c0.sha256` (C4) is regenerated for it.

Run after A3 and the §B commit check, before the `CONFIG.txt` block. Same terminal as section A (`$D`, `$M`, `$CD`, `$A`
set).

12.1 Record the new digest:

```sh
export NEWDIG=$(jq -cS .files ~/.claude/.stack-manifest.json | shasum -a 256 | awk '{print $1}'); echo $NEWDIG
```

12.2 Proof that only the path changed: re-hash the three files with `$D` replaced by `$M`, substitute those hashes into
the manifest and digest it. The last command must print `b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886`
(if it prints anything else, stop: something other than the path changed, or the pinned install was not at `$M`):

```sh
cd ~/.claude && for f in agents/claude-code-engineer.md agents/mcp-broker.md skills/mcp-server-craft/references/from-mcp-broker.md; do printf '%s\t%s\n' "$f" "$(sed "s#$D#$M#g" "$f" | shasum -a 256 | awk '{print $1}')"; done > $TMPDIR/repin_m.tsv
```

```sh
jq -cS --rawfile t $TMPDIR/repin_m.tsv '.files + ($t | split("\n") | map(select(length > 0) | split("\t") | {key: .[0], value: .[1]}) | from_entries)' ~/.claude/.stack-manifest.json | shasum -a 256 | awk '{print $1}'
```

12.3 Amend the `$CD` copies (they are read-only; this makes them writable, edits, restores). The first command must
print `GO` (it checks that 12.1 ran in this terminal); the second shows the old pin (12.4 shows the new one):

```sh
[ ${#NEWDIG} -eq 64 ] && [ -d "$D" ] && [ -n "$M" ] && echo GO || echo "STOP: run 12.1 in the section A terminal"
```

```sh
grep -n '^PIN_FILES_DIGEST=' $CD/c0_check.sh
```

```sh
chmod u+w $CD/c0_check.sh $CD/COMPARE_c0.md $CD/COMPARE_c0.sha256
```

```sh
sed -i '' "s/^PIN_FILES_DIGEST=[0-9a-f]\{64\}/PIN_FILES_DIGEST=$NEWDIG/" $CD/c0_check.sh
```

```sh
cat >> $CD/COMPARE_c0.md <<EOF
- 2026-10-05 re-pin of the manifest files digest (§1 table, C2). Reason: c0 is installed from a throwaway clone at
  \`$D\`, and the installer renders its own path into three files (\`agents/claude-code-engineer.md\`,
  \`agents/mcp-broker.md\`, \`skills/mcp-server-craft/references/from-mcp-broker.md\`; \`__STACK_REPO__\`), so the
  \`jq -cS .files\` digest differs from \`b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886\`. Proof: with
  the clone path replaced by \`$M\` in those three files the digest is again the old one. New expected digest:
  \`$NEWDIG\` (\`PIN_FILES_DIGEST\` in \`c0_check.sh\`). Commit pin, C3 and every other pin are unchanged.
EOF
```

Rewrite the sidecar: its `#` header lines (with `frozen_at_utc`) are kept, one `amended` line is added, the three hash
lines are replaced:

```sh
{ grep '^#' $CD/COMPARE_c0.sha256; echo "# amended 2026-10-05: C2 files digest re-pinned (RUNBOOK_c0 section 12); COMPARE_c0.md and c0_check.sh hashes replaced"; (cd $CD && shasum -a 256 COMPARE_c0.md c0_check.sh freeze.sh); } > $TMPDIR/COMPARE_c0.sha256.new && mv $TMPDIR/COMPARE_c0.sha256.new $CD/COMPARE_c0.sha256
```

```sh
chmod a-w $CD/c0_check.sh $CD/COMPARE_c0.md $CD/COMPARE_c0.sha256
```

12.4 Verify and keep a record (C4 sidecar must say OK on all three; the header must still hold exactly one
`frozen_at_utc` line; the pin line must show `$NEWDIG`):

```sh
cd $CD && shasum -a 256 -c COMPARE_c0.sha256
```

This must print `1`:

```sh
grep -c '^# frozen_at_utc' $CD/COMPARE_c0.sha256
```

```sh
grep -n '^PIN_FILES_DIGEST=' $CD/c0_check.sh
```

```sh
mkdir -p $A && printf 'repinned_utc: %s\nold: b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886\nnew: %s\nclone: %s\n' "$(date -u '+%FT%TZ')" "$NEWDIG" "$D" > $A/REPIN.txt
```

The `P90` dry run of the gate in section B must then show `PASS C2`. If you later redo A3 from a clone at another path,
repeat section 12 with that path.

## Unverified

- `freeze.sh` byte-exactness (no pin); the clone and `checkout -B` steps (agent sandbox refused git on another path); the
  install flags of your last install; whether the pinned files digest came from an install at `$M` (§0.3); the state of
  other Claude Code sessions and of `~/.claude` (not readable from the agent sandbox); `./install.sh --diff` output.
- Section 12: the commands were not run (the install cannot be run by agents); the three placeholder files are verified
  from `a22c5b4`'s tree, the 12.2 proof assumes the pinned install was at `$M` and that `sed` reproduces the rendered
  bytes (the clone path appears in those files only through `__STACK_REPO__`). `shasum -a 256 -c [--quiet]` accepts `#`
  lines [v: steps 1.5, 12.3 and 12.4 run on scratch copies under bash and zsh, 2026-10-05: headers kept, rc 0,
  `grep -c '^# frozen_at_utc'` printed 1].
