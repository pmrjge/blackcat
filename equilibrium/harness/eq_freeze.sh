#!/bin/bash
# eq_freeze.sh: freeze the agent-equilibrium pre-registration, and later collect a stage (COMPARE_eq.md header, §5.5).
# For the USER to run in a normal terminal (agents cannot write into the main checkout). Read-only on the sources.
#
#   bash eq_freeze.sh                  # once, after c0 is collected and before any eq call: install the package
#                                      # into $EQ and write $EQ/COMPARE_eq.sha256 (sha256 + frozen_at_utc)
#   bash eq_freeze.sh --collect <p|q>  # after a stage: copy its transcripts (by the ledger's session ids), raw JSON,
#                                      # usage tables, CONFIG.txt, DISPATCH_LOG.tsv, NOTES.txt and the ledger into
#                                      # $EQ/runs/<stage>/inputs/ (transcripts into $R/<stage>/transcripts/), then
#                                      # write FROZEN_AT.txt and MANIFEST.sha256 there. Never overwrites.
# Refuses to run if c0 is not collected ($W/context-diet/arms/c0/inputs/FROZEN_AT.txt missing).
# Env overrides (tests only): EQ_M (main checkout), EQ_ROOT ($EQ), EQ_STAGE_DIR (the staged package), EQ_RAW ($R),
# EQ_HOME (home whose ~/.claude/projects and ~/.local/state are read).
# Exit 0 = done; 1 = refused or failed.
set -euo pipefail

M=${EQ_M:-/Users/pmrj/ZDone/claude-agent-stack}
W=$M/claude_next_steps/work_carried
EQ=${EQ_ROOT:-$W/equilibrium}
STAGE=${EQ_STAGE_DIR:-/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/equilibrium}
R=${EQ_RAW:-$M/.claude-work/equilibrium/runs}
H=${EQ_HOME:-$HOME}
C0=$W/context-diet/arms/c0/inputs
CLASSES="PF CP CR RS ES DS OE"

die()  { echo "eq_freeze.sh: $*" >&2; exit 1; }
note() { echo "eq_freeze.sh: $*"; }
for t in shasum jq find awk sort xargs cp; do command -v "$t" >/dev/null 2>&1 || die "missing command: $t"; done

[ -f "$C0/FROZEN_AT.txt" ] || die "c0 is not collected ($C0/FROZEN_AT.txt missing): no eq step may run before it (COMPARE_eq §0)"
[ -d "$W" ] || die "missing $W"

MODE=freeze; ST=""
if [ "${1:-}" = "--collect" ]; then
  [ $# -eq 2 ] || die "usage: bash eq_freeze.sh --collect <p|q>"
  MODE=collect; ST="$2"
  case "$ST" in p|q) ;; *) die "stage must be p or q" ;; esac
elif [ $# -ne 0 ]; then
  die "usage: bash eq_freeze.sh | bash eq_freeze.sh --collect <p|q>"
fi
umask 077
FROZEN_UTC=$(date -u '+%FT%TZ')

if [ "$MODE" = freeze ]; then
  [ ! -e "$EQ/COMPARE_eq.sha256" ] || die "$EQ/COMPARE_eq.sha256 exists: the pre-registration was already frozen"
  # ---- preflight: every input present (nothing is written before this passes) ----
  H_=$STAGE/harness
  need="$STAGE/COMPARE_eq.md $STAGE/PROPOSAL.md $STAGE/MEDIATOR.md $H_/eq_harness.py $H_/eq_mediator.py $H_/eq_check.sh"
  need="$need $H_/eq_freeze.sh $H_/flags.json"
  need="$need $H_/schedule.tsv $H_/LEDGER_SCHEMA.md $STAGE/items/lenses.json"
  for c in $CLASSES; do need="$need $STAGE/items/$c/manifest.jsonl $STAGE/items/$c/schema.json $STAGE/items/$c/pool.sha256"; done
  for f in $need; do [ -f "$f" ] || die "missing input: $f"; done
  [ -d "$STAGE/items/graders" ] || die "missing grader briefs: $STAGE/items/graders/"
  for c in $CLASSES; do
    (cd "$STAGE/items/$c" && shasum -a 256 -c --quiet pool.sha256 >/dev/null) || die "pool $c does not verify against its pool.sha256"
  done
  if [ -d "$EQ" ] && [ -n "$(ls -A "$EQ" 2>/dev/null)" ]; then die "$EQ is not empty: inspect it, then move it aside yourself"; fi
  # ---- install ----
  mkdir -p "$EQ"
  cp -p "$STAGE/COMPARE_eq.md" "$STAGE/PROPOSAL.md" "$STAGE/MEDIATOR.md" "$EQ/"
  for f in CONTRACT.md seeds.out derive_numbers.py derive_numbers.out mediator_numbers.py mediator_numbers.out \
           shift_check.py shift_check.out; do
    if [ -f "$STAGE/$f" ]; then cp -p "$STAGE/$f" "$EQ/"; fi
  done
  for f in eq_harness.py eq_mediator.py eq_check.sh eq_freeze.sh flags.json schedule.tsv LEDGER_SCHEMA.md README.md \
           stub_claude; do
    if [ -f "$H_/$f" ]; then cp -p "$H_/$f" "$EQ/"; fi
  done
  mkdir -p "$EQ/items"
  cp -pR "$STAGE/items/." "$EQ/items/"
  find "$EQ" -type f -exec chmod a-w {} +
  tmp=$(mktemp "${TMPDIR:-/tmp}/eq-sidecar.XXXXXX")
  (cd "$EQ" && find . -type f ! -name COMPARE_eq.sha256 ! -name .DS_Store -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$tmp"
  { echo "# frozen_at_utc: $FROZEN_UTC"
    echo "# frozen_at_local: $(date '+%F %T %z')"
    echo "# pre-registration of eq (COMPARE_eq.md) before any eq call; written by eq_freeze.sh. claude_next_steps/ is"
    echo "# git-ignored, so this sidecar replaces a commit. Amendments: append to COMPARE_eq.md §12, then add a line"
    echo "# '# amended <date>: <reason>' here and replace the changed hash lines."
    echo "# c0_frozen_at: $(sed -n 's/^frozen_at_utc: //p' "$C0/FROZEN_AT.txt" | head -1)"
    cat "$tmp"; } > "$EQ/COMPARE_eq.sha256"
  rm -f "$tmp"
  chmod a-w "$EQ/COMPARE_eq.sha256"
  (cd "$EQ" && grep -v '^#' COMPARE_eq.sha256 | shasum -a 256 -c --quiet) || die "COMPARE_eq.sha256 does not verify"
  note "installed $(grep -vc '^#' "$EQ/COMPARE_eq.sha256") files into $EQ; sidecar $EQ/COMPARE_eq.sha256 (frozen_at_utc $FROZEN_UTC)"
  exit 0
fi

# ---- collect a stage ----
RUNS=$EQ/runs/$ST
IN=$RUNS/inputs
LEDGER=$RUNS/ledger.jsonl
PROJ=$H/.claude/projects
STATE=$H/.local/state/claude-agent-stack
[ -f "$EQ/COMPARE_eq.sha256" ] || die "the package is not frozen ($EQ/COMPARE_eq.sha256 missing)"
[ -f "$LEDGER" ] || die "missing $LEDGER"
[ ! -e "$IN/FROZEN_AT.txt" ] && [ ! -e "$IN/MANIFEST.sha256" ] || die "already collected: $IN/FROZEN_AT.txt or MANIFEST.sha256 exists"
if [ -d "$M/.git" ]; then
  git -C "$M" check-ignore -q ".claude-work/equilibrium/runs/x" || die "$M/.claude-work is not git-ignored: refusing to copy transcripts there"
else die "$M is not a git checkout"; fi
T=$R/$ST/transcripts
if [ -d "$T" ] && [ -n "$(ls -A "$T" 2>/dev/null)" ]; then die "$T is not empty: inspect it, then move it aside yourself"; fi
mkdir -p "$IN/raw" "$T"
sids=$(jq -r 'select(.record=="call") | .session_id // empty' "$LEDGER" | sort -u)
missing=""; n_s=0
for sid in $sids; do
  case "$sid" in *[!0-9a-f-]*) die "bad session id in ledger: $sid" ;; esac
  hit=0
  for j in "$PROJ"/*/"$sid".jsonl "$PROJ"/*/"$sid"; do
    [ -e "$j" ] || continue
    hit=1; slug=$(basename "$(dirname "$j")"); mkdir -p "$T/$slug"
    if [ -d "$j" ]; then cp -pR "$j" "$T/$slug/"; else cp -p "$j" "$T/$slug/"; fi
  done
  if [ "$hit" = 1 ]; then n_s=$((n_s + 1)); else missing="$missing $sid"; fi
done
# raw JSON outputs and prompts named in the ledger
paths=$(jq -r 'select(.record=="call") | .raw_path, .prompt_path' "$LEDGER") || die "cannot read $LEDGER"
while IFS= read -r p; do
  [ -n "$p" ] && [ -f "$p" ] || continue
  case "$p" in "$R"/*) ;; *) die "raw path outside $R in the ledger: $p" ;; esac
  rel=${p#"$R"/}
  if ! { mkdir -p "$IN/raw/$(dirname "$rel")" && cp -p "$p" "$IN/raw/$rel"; }; then
    die "copy failed: $p (partial collection in $IN and $T: move both aside before a rerun)"
  fi
done <<< "$paths"
for f in runs3.csv reports.jsonl; do if [ -f "$STATE/usage/$f" ]; then cp -p "$STATE/usage/$f" "$IN/"; fi; done
for f in CONFIG.txt DISPATCH_LOG.tsv NOTES.txt ledger.jsonl; do if [ -f "$RUNS/$f" ]; then cp -p "$RUNS/$f" "$IN/"; fi; done
# mediator ledgers ($R/<stage>/<item>/<label>/mediator.jsonl)
if [ -d "$R/$ST" ]; then
  while IFS= read -r mf; do
    rel=${mf#"$R/$ST"/}
    if ! { mkdir -p "$IN/mediator/$(dirname "$rel")" && cp -p "$mf" "$IN/mediator/$rel"; }; then
      die "copy failed: $mf (partial collection in $IN and $T: move both aside before a rerun)"
    fi
  done < <(find "$R/$ST" -mindepth 3 -maxdepth 3 -name mediator.jsonl -type f)
fi
{ echo "frozen_at_utc: $FROZEN_UTC"; echo "stage: $ST"; echo "sessions_copied: $n_s"
  echo "sessions_missing:${missing:- none}"; echo "transcripts: $T (git-ignored, mode 0700)"
  echo "sidecar_sha256: $(shasum -a 256 "$EQ/COMPARE_eq.sha256" | awk '{print $1}')"; } > "$IN/FROZEN_AT.txt"
(cd "$T" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$IN/TRANSCRIPTS.sha256"
(cd "$IN" && find . -type f ! -name MANIFEST.sha256 -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$IN/MANIFEST.sha256"
(cd "$IN" && shasum -a 256 -c --quiet MANIFEST.sha256) || die "the collection does not verify against its manifest"
note "collected stage $ST: $n_s session(s) to $T; inputs $IN (missing:${missing:- none})"
exit 0
