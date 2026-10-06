#!/bin/bash
# freeze.sh: freeze the pre-diet transcripts and the c0 pre-registration (context-diet S-DATA step 0; COMPARE_c0.md).
# For the USER to run in a normal terminal (agents cannot write into the main checkout). Read-only on the sources.
#
#   bash freeze.sh                      # once: the 5 pre-diet sessions + install and hash the c0 pre-registration
#   bash freeze.sh --arm <label> <uuid> # after an arm (e.g. c0): freeze that arm session's transcripts
#
# Default mode:
#   copies   ~/.claude/projects/<slug>/<uuid>.jsonl and ~/.claude/projects/<slug>/<uuid>/ (subagents/, tool-results/,
#            workflows/, custom-title.json) for sessions 4e2da3ce fae82d02 e4fe4e24 a59eca09 68541e7b, every project
#            folder that holds them; plus the stack's per-session state (~/.local/state/claude-agent-stack/<uuid>/ and
#            usage/sessions/<uuid>/, no *.lock/*.mutex) and a snapshot of usage/{runs3.csv,runs.csv,reports.jsonl}
#   to       $M/.claude-work/context-diet/data/transcripts/{projects,state}/   (git-ignored; mode 0700/0600: may hold secrets)
#   writes   $P/work_carried/context-diet/data/{MANIFEST.sha256,FROZEN_AT.txt,SOURCE_RECHECK.txt}
#   installs COMPARE_c0.md, c0_check.sh and this script into $P/work_carried/context-diet/ (read-only) and writes
#            COMPARE_c0.sha256 there (sha256 + freeze time: the package is git-ignored, so this replaces a commit)
# Refuses to overwrite an earlier freeze. Exit 0 = done; 3 = done but a session was missing; 1 = failed.
set -euo pipefail

M=/Users/pmrj/ZDone/claude-agent-stack
P=$M/claude_next_steps
CD=$P/work_carried/context-diet
STAGE=/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/next-steps-7c1c7f/.claude-work/context-diet
DEST_ROOT=$M/.claude-work/context-diet/data
PROJ=$HOME/.claude/projects
STATE=$HOME/.local/state/claude-agent-stack
SIDS="4e2da3ce-e2f4-4971-aac5-a67f2dcf252e fae82d02-7bf7-4439-9024-17b07cace5cc e4fe4e24-7ca9-4c48-9e12-813abd17269b a59eca09-6dbc-468a-b41f-d777f972ff55 68541e7b-6973-4b5a-ba22-07b78df35d08"
# sha256 of the staged files, fixed when this script was written (2026-10-04); a mismatch means they were edited since
EXPECT_COMPARE=57b6411aec7f83265d7e85123fa9f40f648cb53595936c71f239998b15e3792c
EXPECT_CHECK=2e70d6ba31df796926ae89964e7ce2b9e4c3747d0f66a891669f91a6bb4c20b8
CLEANUP_DAYS_DEFAULT=30

die()  { echo "freeze.sh: $*" >&2; exit 1; }
note() { echo "freeze.sh: $*"; }
sha()  { shasum -a 256 "$1" | awk '{print $1}'; }
for t in shasum rsync jq git find awk sed du df stat; do command -v "$t" >/dev/null 2>&1 || die "missing command: $t"; done

MODE=default; LABEL=""
if [ "${1:-}" = "--arm" ]; then
  [ $# -eq 3 ] || die "usage: bash freeze.sh --arm <label> <session uuid>"
  MODE=arm; LABEL="$2"; SIDS="$3"
  case "$LABEL" in c[0-9]|c[0-9][0-9]) ;; *) die "label must look like c0, c1, c9 ..." ;; esac
  case "$SIDS" in *[!0-9a-f-]*|"") die "bad session uuid: $SIDS" ;; esac
  DEST=$DEST_ROOT/arms/$LABEL
  META=$CD/arms/$LABEL/transcripts
elif [ $# -ne 0 ]; then
  die "usage: bash freeze.sh | bash freeze.sh --arm <label> <session uuid>"
else
  DEST=$DEST_ROOT/transcripts
  META=$CD/data
fi

# ---- preflight (nothing is written before every check passes) ----
[ -d "$M/.git" ] || die "$M is not the main checkout"
[ -d "$CD" ] || die "missing $CD"
git -C "$M" check-ignore -q ".claude-work/context-diet/data/x" || die "$M/.claude-work is not git-ignored: refusing to copy transcripts there"
[ ! -e "$META/FROZEN_AT.txt" ] && [ ! -e "$META/MANIFEST.sha256" ] || die "already frozen: $META/FROZEN_AT.txt or MANIFEST.sha256 exists (never overwritten)"
if [ -d "$DEST" ] && [ -n "$(ls -A "$DEST" 2>/dev/null)" ]; then die "$DEST is not empty (an earlier or partial freeze?): inspect it, then move it aside yourself"; fi
if [ "$MODE" = default ]; then
  [ "$(sha "$STAGE/COMPARE_c0.md")" = "$EXPECT_COMPARE" ] || die "staged COMPARE_c0.md changed since this script was written"
  [ "$(sha "$STAGE/c0_check.sh")" = "$EXPECT_CHECK" ] || die "staged c0_check.sh changed since this script was written"
  [ ! -e "$CD/COMPARE_c0.sha256" ] || die "$CD/COMPARE_c0.sha256 exists: the pre-registration was already frozen"
  for f in COMPARE_c0.md c0_check.sh freeze.sh; do
    if [ -e "$CD/$f" ] && ! cmp -s "$CD/$f" "$STAGE/$f"; then die "$CD/$f exists and differs from the staged copy"; fi
  done
fi

found=""; missing=""; need_k=0
for sid in $SIDS; do
  hit=0
  for j in "$PROJ"/*/"$sid".jsonl; do
    [ -f "$j" ] || continue
    hit=1
    d="${j%.jsonl}"
    k=$(du -sk "$j" | awk '{print $1}'); need_k=$((need_k + k))
    if [ -d "$d" ]; then k=$(du -sk "$d" | awk '{print $1}'); need_k=$((need_k + k)); fi
  done
  for d in "$PROJ"/*/"$sid"; do            # a folder without its .jsonl (session moved between projects)
    if [ -d "$d" ] && [ ! -f "$d.jsonl" ]; then hit=1; k=$(du -sk "$d" | awk '{print $1}'); need_k=$((need_k + k)); fi
  done
  if [ "$hit" = 1 ]; then found="$found $sid"; else missing="$missing $sid"; fi
done
[ -n "$found" ] || die "none of the sessions was found under $PROJ (expired?):$missing"
avail_k=$(df -k "$M" | awk 'NR==2{print $4}')
[ "$avail_k" -gt $((need_k * 2 + 1048576)) ] || die "not enough free space: need ~$((need_k/1024)) MB x2 + 1 GB, have $((avail_k/1024)) MB"
note "mode=$MODE; sessions found:$found; missing:${missing:- none}; ~$((need_k/1024)) MB to copy"

# ---- copy ----
umask 077
NOW_EPOCH=$(date +%s)
FROZEN_LOCAL=$(date '+%F %T %z'); FROZEN_UTC=$(date -u '+%FT%TZ')
mkdir -p "$DEST/projects" "$DEST/state/usage/sessions"
sess_info=""
for sid in $found; do
  slugs=""; nfiles=0; bytes=0; newest=0
  for d in "$PROJ"/*/"$sid".jsonl "$PROJ"/*/"$sid"; do
    [ -e "$d" ] || continue
    slug=$(basename "$(dirname "$d")")
    case " $slugs " in *" $slug "*) ;; *) slugs="$slugs $slug" ;; esac
    mkdir -p "$DEST/projects/$slug"
    if [ -f "$d" ]; then cp -p "$d" "$DEST/projects/$slug/"
    else rsync -a --exclude .DS_Store "$d/" "$DEST/projects/$slug/$sid/"; fi
  done
  for s in "$STATE/$sid" "$STATE/usage/sessions/$sid"; do
    [ -d "$s" ] || continue
    rel="${s#"$STATE"/}"
    mkdir -p "$DEST/state/$rel"
    rsync -a --exclude '*.lock' --exclude '*.mutex' --exclude .DS_Store "$s/" "$DEST/state/$rel/"
  done
  # per-session facts for FROZEN_AT.txt (sources, not copies)
  for slug in $slugs; do
    while IFS= read -r f; do
      nfiles=$((nfiles + 1)); b=$(stat -f %z "$f"); bytes=$((bytes + b))
      m=$(stat -f %m "$f"); if [ "$m" -gt "$newest" ]; then newest=$m; fi
    done < <(find "$PROJ/$slug/$sid.jsonl" "$PROJ/$slug/$sid" -type f 2>/dev/null)
  done
  j1=""; for j in "$PROJ"/*/"$sid".jsonl; do if [ -f "$j" ]; then j1="$j"; break; fi; done
  first_ts=""; last_ts=""
  if [ -n "$j1" ]; then
    first_ts=$(head -n 200 "$j1" | grep -o '"timestamp":"[^"]*"' | head -1 | sed 's/.*:"\(.*\)"/\1/' || true)
    last_ts=$(tail -n 200 "$j1" | grep -o '"timestamp":"[^"]*"' | tail -1 | sed 's/.*:"\(.*\)"/\1/' || true)
  fi
  active=no; if [ $((NOW_EPOCH - newest)) -lt 600 ]; then active="yes (written in the last 10 min: the copy is a snapshot)"; fi
  sess_info="$sess_info
  - session: $sid
    project_dirs:$slugs
    files: $nfiles   bytes: $bytes
    first_ts: ${first_ts:-?}   last_ts: ${last_ts:-?}
    newest_source_mtime: $(date -r "$newest" '+%F %T %z')
    active_at_freeze: $active"
done
if [ "$MODE" = default ]; then
  for f in runs3.csv runs.csv reports.jsonl; do if [ -f "$STATE/usage/$f" ]; then cp -p "$STATE/usage/$f" "$DEST/state/usage/"; fi; done
fi
chmod -R go-rwx "$DEST_ROOT"

# ---- manifest + verification ----
mkdir -p "$META"
tmp=$(mktemp "${TMPDIR:-/tmp}/freeze-manifest.XXXXXX")
(cd "$DEST" && find . -type f ! -name .DS_Store -print0 | LC_ALL=C sort -z | xargs -0 shasum -a 256) > "$tmp"
(cd "$DEST" && shasum -a 256 -c --quiet "$tmp") || die "the copy does not verify against its own manifest ($tmp)"
n_copied=$(wc -l < "$tmp" | tr -d ' ')
# route 2: the same hashes recomputed on the SOURCE files (live usage tables and an active session may differ)
recheck=$(mktemp "${TMPDIR:-/tmp}/freeze-recheck.XXXXXX")
sed -e "s#  \./projects/#  $PROJ/#" -e "s#  \./state/#  $STATE/#" "$tmp" | shasum -a 256 -c 2>&1 | grep -v ': OK$' > "$recheck" || true
n_diff=$(grep -c . "$recheck" || true)
mv "$tmp" "$META/MANIFEST.sha256"
{ echo "# source files whose bytes changed between copy and recheck ($FROZEN_UTC); expected only for live files"
  echo "# (usage/*.csv, reports.jsonl, an active session). Paths are the sources; the copy is what MANIFEST.sha256 pins."
  cat "$recheck"; } > "$META/SOURCE_RECHECK.txt"
rm -f "$recheck"

# ---- c0 pre-registration (default mode only) ----
prereg=""
if [ "$MODE" = default ]; then
  for f in COMPARE_c0.md c0_check.sh freeze.sh; do
    [ -e "$CD/$f" ] || cp -p "$STAGE/$f" "$CD/$f"
    chmod a-w "$CD/$f"
  done
  { echo "# frozen_at_local: $FROZEN_LOCAL"
    echo "# frozen_at_utc: $FROZEN_UTC"
    echo "# pre-registration of c0 before any c0 dispatch; written by freeze.sh. claude_next_steps/ is git-ignored"
    echo "# (.gitignore:45), so this sidecar replaces a commit. Amendments: append to COMPARE_c0.md §12, then add a line"
    echo "# '# amended <date>: <reason>' here and replace the COMPARE_c0.md hash line."
    (cd "$CD" && shasum -a 256 COMPARE_c0.md c0_check.sh freeze.sh); } > "$CD/COMPARE_c0.sha256"
  (cd "$CD" && shasum -a 256 -c --quiet COMPARE_c0.sha256) || die "COMPARE_c0.sha256 does not verify"
  prereg="prereg:
  COMPARE_c0.md  $(sha "$CD/COMPARE_c0.md")
  c0_check.sh    $(sha "$CD/c0_check.sh")
  freeze.sh      $(sha "$CD/freeze.sh")
  sidecar        $CD/COMPARE_c0.sha256"
fi

# ---- FROZEN_AT.txt ----
cleanup=$(jq -r '.cleanupPeriodDays // empty' "$HOME/.claude/settings.json" 2>/dev/null || true)
cdays=${cleanup:-$CLEANUP_DAYS_DEFAULT}
{
  echo "frozen_at_local: $FROZEN_LOCAL"
  echo "frozen_at_utc: $FROZEN_UTC"
  echo "frozen_by: freeze.sh (sha256 $(sha "$0")), mode $MODE${LABEL:+ label $LABEL}, user $(id -un)"
  echo "claude_version: $(claude --version 2>/dev/null | head -1 || echo unknown)"
  echo "installed_stack_commit: $(jq -r .commit "$HOME/.claude/.stack-manifest.json" 2>/dev/null || echo unknown)"
  echo "main_head: $(git -C "$M" rev-parse HEAD)"
  echo "cleanupPeriodDays: ${cleanup:-unset (default $CLEANUP_DAYS_DEFAULT)}; sources expire about newest_source_mtime + $cdays days"
  echo "copy_root: $DEST (git-ignored, mode 0700; never commit: transcripts can hold secrets)"
  echo "manifest: $META/MANIFEST.sha256 ($n_copied files; paths relative to copy_root; verify: cd copy_root && shasum -a 256 -c <manifest>)"
  echo "source_recheck: $n_diff file(s) differed on the source after the copy ($META/SOURCE_RECHECK.txt)"
  echo "missing_sessions:${missing:- none}"
  echo "sessions:$sess_info"
  echo "layout:"
  echo "  projects/<slug>/<uuid>.jsonl and projects/<slug>/<uuid>/   mirror ~/.claude/projects (collector: --projects <copy_root>/projects)"
  echo "  state/<uuid>/, state/usage/sessions/<uuid>/                mirror ~/.local/state/claude-agent-stack (collector: --state-dir <copy_root>/state)"
  if [ "$MODE" = default ]; then echo "  state/usage/{runs3.csv,runs.csv,reports.jsonl}             snapshot of the live usage tables at frozen_at"; fi
  if [ -n "$prereg" ]; then echo "$prereg"; fi
} > "$META/FROZEN_AT.txt"

note "copied $n_copied files to $DEST"
note "wrote $META/MANIFEST.sha256, FROZEN_AT.txt, SOURCE_RECHECK.txt ($n_diff source file(s) changed after the copy)"
if [ -n "$prereg" ]; then note "pre-registration frozen: $CD/COMPARE_c0.sha256"; fi
if [ -n "$missing" ]; then note "MISSING sessions (expired or never here):$missing"; exit 3; fi
exit 0
