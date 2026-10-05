#!/usr/bin/env bash
#
# RESET_TO_MAIN.sh: reset the claude-agent-stack repository to "only main", safely.
# Design: hand_off/HANDOFF_STATE.md §4 item 10, §5 (worktree cleanup), §6 decisions 10 and 13.
# Runs on macOS /bin/bash 3.2 with the BSD tools (bsdtar, shasum, stat -f, find, awk) and /usr/bin/perl.
#
# Usage: RESET_TO_MAIN.sh [--archive [DIR] | --apply [DIR]] [options]
#
#   (no mode)        Dry run: inspect, classify and print every command stages 1 and 2 would run.
#                    Writes nothing anywhere (git runs with GIT_OPTIONAL_LOCKS=0; no temp files).
#   --archive [DIR]  Stage 1 only: archive everything unique into DIR, then verify it: a full bundle
#                    of main; a bundle per branch and per detached HEAD with commits not in main; a
#                    pack of the commits only reflogs reach; per worktree (M included) its status,
#                    HEAD + `git diff --binary HEAD`, the list and a tarball of its untracked and
#                    ignored files; named tarballs (EQ-T, its snapshot, c0 data, the transcripts,
#                    work_carried, every claude_info dir); MANIFEST.tsv and MANIFEST.tsv.sha256.
#                    Every file is mode 0600 in a 0700 DIR. Refuses a non-empty DIR unless --resume.
#   --apply [DIR]    Stage 2: needs DIR/MANIFEST.tsv whose sha256s, sizes and bundles verify (else
#                    exit 4 and nothing changes). Then, nested worktrees first and --last at the end,
#                    `git worktree remove` for each worktree whose state still matches the archive
#                    (`--force` only for a dirty one); never rm -rf, never a locked or live worktree.
#                    `git branch -d` for merged branches; `git branch -D` only for a branch whose
#                    verified bundle holds its current tip.
#
# Options
#   --dir DIR            archive directory (default: DEFAULT_DIR below); same as the DIR operand
#   --repo PATH          any checkout of the repository (default: the current directory)
#   --resume             with --archive: reuse a non-empty DIR; rows that still verify and match stay
#   --clean              with --apply: show `git clean -ndx` in M, then `git clean -fdx`, only when
#                        every file it deletes is in the verified archive and M is not live
#   --gc                 with --apply: `git reflog expire --expire=now --all` and `git gc --prune=now`,
#                        only with no live or locked worktree left, no stash, and every commit that
#                        would be dropped held by an archived pack or bundle
#   --session-wt PATH    worktree of a running session (repeatable): a blocker, never touched
#   --last PATH          worktree processed last (default: H, the hand-off worktree)
#   --live-minutes N     a worktree with a file modified in the last N minutes is live (default 60;
#                        0 turns the check off)
#   --main NAME          the branch that stays (default: main)
#   --item NAME=PATH     add a named tarball (repeatable); --secret-item NAME=PATH: same, flagged secret
#   --no-default-items   drop the built-in named tarballs
#   --skip-venvs         leave Python venvs (dirs holding pyvenv.cfg) out of the archive; --apply then
#                        deletes them unarchived (they are rebuildable)
#   --no-sizes           dry run: skip the per-worktree file counts and sizes
#   -h, --help           this text
#
# Blockers (listed, never touched): M itself; the worktree the caller runs from and the one holding
# this script; locked worktrees; --session-wt worktrees; a rebase, merge, cherry-pick, revert or
# bisect in progress; an index.lock; a file modified in the last N minutes; a worktree that contains
# any of these. Nested worktrees are found by path in `git worktree list --porcelain`.
# Never archived (rebuildable; deleted by --apply): __pycache__, .pytest_cache, .ruff_cache,
# .mypy_cache, .hypothesis, .DS_Store, empty directories.
#
# Exit codes
#   0  success: dry run printed / archive written and verified / apply left only main
#   1  unexpected internal error
#   2  usage error
#   3  precondition failed: not a git repository, bare repository, M not on the main branch, DIR not
#      empty without --resume, DIR inside a worktree, archive lock held
#   4  archive verification failed: no MANIFEST.tsv, manifest or file sha256/size mismatch, a bundle
#      fails `git bundle verify`, manifest of another repository; --apply then changes nothing
#   5  apply finished, but worktrees or branches other than M, main and the caller's worktree remain
#      (blockers, items missing from the archive or changed since)
#   6  an archive item or a git command of --apply failed (the log above the summary says which)
# End of usage

set -Eeuo pipefail
export LC_ALL=C GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0
# In a subshell ($(...), pipelines) pass the status up quietly: the caller handles or reports it.
trap 'rc=$?; if [ "${BASH_SUBSHELL:-0}" -gt 0 ]; then exit "$rc"; fi; printf "RESET_TO_MAIN: unexpected failure (rc=%s) at line %s: %s\n" "$rc" "$LINENO" "$BASH_COMMAND" >&2; exit 1' ERR

DEFAULT_DIR=/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/_archive_stack_1005
DEFAULT_LAST=/Users/pmrj/ZDone/Worktree_for_Claude/claude-agent-stack/claude-info-handoff-setup-05c3bb
CACHE_RE='(^|/)(__pycache__|\.pytest_cache|\.ruff_cache|\.mypy_cache|\.hypothesis)/|(^|/)\.DS_Store$'
SEP=$'\037'
TAB=$'\t'

# ---------------------------------------------------------------- helpers
die() { local rc=$1; shift; printf 'RESET_TO_MAIN: error: %s\n' "$*" >&2; exit "$rc"; }
say() { printf '%s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*"; }
usage() { sed -n '/^# Usage:/,/^# End of usage/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'; }
q() { # shell-quote the arguments for display: plain words as they are, others in single quotes
  local a out=""
  for a in "$@"; do
    case $a in
      '') out="$out ''" ;;
      *[!A-Za-z0-9_./:=@%^+,-]*) out="$out '$(printf '%s' "$a" | sed "s/'/'\\\\''/g")'" ;;
      *) out="$out $a" ;;
    esac
  done
  printf '%s' "${out# }"
}
cmdline() { printf '  $ %s\n' "$(q "$@")"; }
is_under() { # $1 is $2 or lies below it
  if [ "$1" = "$2" ]; then return 0; fi
  case $1 in "$2"/*) return 0 ;; esac
  return 1
}
canon() { # physical absolute path; a missing path is resolved through its parent
  local d b
  if [ -d "$1" ]; then (cd -- "$1" 2>/dev/null && pwd -P) || printf '%s' "$1"; return 0; fi
  d=$(dirname -- "$1"); b=$(basename -- "$1")
  if [ -d "$d" ]; then printf '%s/%s' "$( (cd -- "$d" && pwd -P) )" "$b"; else printf '%s' "$1"; fi
}
sha_of() { shasum -a 256 -- "$1" | cut -d' ' -f1; }
sha_stdin() { shasum -a 256 | cut -d' ' -f1; }
bytes_of() { stat -f %z -- "$1"; }
count_lines() { if [ -z "$1" ]; then echo 0; else printf '%s\n' "$1" | wc -l | tr -d ' '; fi; }
human() { awk -v b="$1" 'BEGIN { split("B KB MB GB TB", u, " "); i = 1
  while (b >= 1024 && i < 5) { b /= 1024; i++ }
  if (i == 1) printf "%d %s", b, u[i]; else printf "%.1f %s", b, u[i] }'; }
disp() { # short display form of a path: M/... for the main checkout, ~/... under $HOME
  case $1 in
    "$M") printf 'M' ;;
    "$M"/*) printf 'M/%s' "${1#"$M"/}" ;;
    "${HOME:-/nonexistent}"/*) printf '%s/%s' '~' "${1#"${HOME}"/}" ;;
    *) printf '%s' "$1" ;;
  esac
}
safe_name() { printf '%s' "$1" | tr -c 'A-Za-z0-9._-' '_'; }

# ---------------------------------------------------------------- arguments
MODE=dry DIR="" RESUME=0 CLEAN=0 GC=0 REPO=. LAST=$DEFAULT_LAST LIVE_MIN=60 MAIN=main
SKIP_VENVS=0 SIZES=1 DEFAULT_ITEMS=1
SESSIONS=() U_NAMES=() U_PATHS=() U_SECRET=()

need() { if [ $# -lt 2 ]; then die 2 "$1 needs a value"; fi; }
add_user_item() { # NAME=PATH secret-flag
  local name path
  case $1 in *=*) ;; *) die 2 "--item wants NAME=PATH, got: $1" ;; esac
  name=${1%%=*} path=${1#*=}
  case $name in '' | *[!A-Za-z0-9._-]*) die 2 "bad item name: '$name' (letters, digits, . _ -)" ;; esac
  if [ -z "$path" ]; then die 2 "empty item path in: $1"; fi
  U_NAMES+=("$name") U_PATHS+=("$path") U_SECRET+=("$2")
}
while [ $# -gt 0 ]; do
  case $1 in
    --archive | --apply)
      if [ "$MODE" != dry ]; then die 2 "use only one of --archive and --apply"; fi
      MODE=${1#--}
      if [ $# -ge 2 ] && [ -n "$2" ] && [ "${2#-}" = "$2" ]; then DIR=$2; shift; fi ;;
    --dir) need "$@"; DIR=$2; shift ;;
    --repo) need "$@"; REPO=$2; shift ;;
    --resume) RESUME=1 ;;
    --clean) CLEAN=1 ;;
    --gc) GC=1 ;;
    --session-wt) need "$@"; SESSIONS+=("$2"); shift ;;
    --last) need "$@"; LAST=$2; shift ;;
    --live-minutes)
      need "$@"
      case $2 in '' | *[!0-9]*) die 2 "--live-minutes wants a whole number of minutes" ;; esac
      LIVE_MIN=$2; shift ;;
    --main) need "$@"; MAIN=$2; shift ;;
    --item) need "$@"; add_user_item "$2" 0; shift ;;
    --secret-item) need "$@"; add_user_item "$2" 1; shift ;;
    --no-default-items) DEFAULT_ITEMS=0 ;;
    --skip-venvs) SKIP_VENVS=1 ;;
    --no-sizes) SIZES=0 ;;
    -h | --help) usage; exit 0 ;;
    *) die 2 "unknown argument: $1 (see --help)" ;;
  esac
  shift
done
if [ -z "$DIR" ]; then DIR=$DEFAULT_DIR; fi
if [ "$MODE" = archive ] && { [ "$CLEAN" = 1 ] || [ "$GC" = 1 ]; }; then die 2 "--clean and --gc go with --apply (or a dry run), not --archive"; fi
if [ "$RESUME" = 1 ] && [ "$MODE" != archive ]; then die 2 "--resume goes with --archive"; fi
command -v git >/dev/null 2>&1 || die 3 "git not found"
PERL=$(command -v perl) || die 3 "perl not found (macOS ships /usr/bin/perl; shasum needs it too)"

# ---------------------------------------------------------------- repository and worktrees
REPO_ABS=$(cd -- "$REPO" 2>/dev/null && pwd -P) || die 3 "no such directory: $REPO"
if ! git -C "$REPO_ABS" rev-parse --git-dir >/dev/null 2>&1; then die 3 "not a git repository: $REPO_ABS"; fi
COMMON=$(git -C "$REPO_ABS" rev-parse --path-format=absolute --git-common-dir) || die 3 "cannot find the git dir of $REPO_ABS"
COMMON=$(canon "$COMMON")

read_worktrees() { # one record per worktree: path SEP head SEP branch SEP locked SEP why SEP prunable SEP bare
  local f path="" head=- br=- lk=0 why=- pr=0 bare=0 have=0
  while IFS= read -r -d '' f; do
    case $f in
      'worktree '*) path=${f#worktree } head=- br=- lk=0 why=- pr=0 bare=0 have=1 ;;
      'HEAD '*) head=${f#HEAD } ;;
      'branch refs/heads/'*) br=${f#branch refs/heads/} ;;
      'branch '*) br=${f#branch } ;;
      bare) bare=1 ;;
      locked) lk=1 ;;
      'locked '*) lk=1 why=${f#locked } ;;
      prunable | 'prunable '*) pr=1 ;;
      '')
        if [ "$have" = 1 ]; then printf '%s\n' "$path$SEP$head$SEP$br$SEP$lk$SEP$why$SEP$pr$SEP$bare"; fi
        have=0 ;;
    esac
  done < <(git -C "$REPO_ABS" worktree list --porcelain -z)
  if [ "$have" = 1 ]; then printf '%s\n' "$path$SEP$head$SEP$br$SEP$lk$SEP$why$SEP$pr$SEP$bare"; fi
}

WT_PATH=() WT_CANON=() WT_HEAD=() WT_BRANCH=() WT_LOCKED=() WT_LOCKWHY=() WT_PRUNABLE=() WT_BARE=()
n=0
while IFS=$SEP read -r p_ h_ b_ l_ w_ r_ x_; do
  WT_PATH[n]=$p_ WT_HEAD[n]=$h_ WT_BRANCH[n]=$b_ WT_LOCKED[n]=$l_ WT_LOCKWHY[n]=$w_ WT_PRUNABLE[n]=$r_ WT_BARE[n]=$x_
  if [ "$r_" = 1 ]; then WT_CANON[n]=$p_; else WT_CANON[n]=$(canon "$p_"); fi
  n=$((n + 1))
done < <(read_worktrees)
NWT=$n
if [ "$NWT" -lt 1 ]; then die 3 "git worktree list returned nothing for $REPO_ABS"; fi
if [ "${WT_BARE[0]}" = 1 ]; then die 3 "bare repository: nothing to reset"; fi
M=${WT_CANON[0]}

MAIN_SHA=$(git -C "$M" rev-parse -q --verify "refs/heads/$MAIN^{commit}") || die 3 "no branch '$MAIN' in $M"
if [ "${WT_BRANCH[0]}" != "$MAIN" ]; then
  if [ "$MODE" = dry ]; then
    warn "M has '${WT_BRANCH[0]}' checked out, not '$MAIN': --archive and --apply will refuse"
  else
    die 3 "M ($M) must have '$MAIN' checked out (it has '${WT_BRANCH[0]}')"
  fi
fi

wt_containing() { # index of the innermost worktree holding path $1, or -1
  local i best=-1 len=0
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 0 ] && is_under "$1" "${WT_CANON[i]}" && [ "${#WT_CANON[i]}" -gt "$len" ]; then
      best=$i len=${#WT_CANON[i]}
    fi
  done
  printf '%s' "$best"
}
is_registered() { # $1 (canonical) is a registered, existing worktree other than M
  local i
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 0 ] && [ "${WT_CANON[i]}" = "$1" ]; then return 0; fi
  done
  return 1
}

CWD=$(pwd -P)
CALLER_IDX=$(wt_containing "$CWD")
SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" 2>/dev/null && pwd -P) || SCRIPT_DIR=$CWD
SCRIPT_IDX=$(wt_containing "$SCRIPT_DIR")
LAST_C=$(canon "$LAST")
SESS_C=()
for s_ in ${SESSIONS[@]+"${SESSIONS[@]}"}; do SESS_C+=("$(canon "$s_")"); done
is_session() {
  local s
  for s in ${SESS_C[@]+"${SESS_C[@]}"}; do
    if [ "$s" = "$1" ]; then return 0; fi
  done
  return 1
}
DIR_C=$(canon "$DIR")

# ---------------------------------------------------------------- inspection helpers
wt_gitdir() { # git dir of the worktree at $1 (read from its .git file)
  local line=""
  if [ -f "$1/.git" ]; then
    IFS= read -r line <"$1/.git" || true
    line=${line#gitdir: }
    case $line in /*) ;; '') ;; *) line=$1/$line ;; esac
    if [ -n "$line" ] && [ -d "$line" ]; then canon "$line"; fi
  elif [ -d "$1/.git" ]; then
    canon "$1/.git"
  fi
}
op_in_progress() { # operation in progress in git dir $1, if any
  local g=$1
  if [ -z "$g" ]; then return 0; fi
  if [ -d "$g/rebase-merge" ] || [ -d "$g/rebase-apply" ]; then echo rebase
  elif [ -f "$g/MERGE_HEAD" ]; then echo merge
  elif [ -f "$g/CHERRY_PICK_HEAD" ]; then echo cherry-pick
  elif [ -f "$g/REVERT_HEAD" ]; then echo revert
  elif [ -f "$g/BISECT_LOG" ]; then echo bisect
  elif [ -d "$g/sequencer" ]; then echo sequencer
  fi
}
recent_file() { # a file under root $1 (nested worktrees and .git left out) or the index in git dir $2
  # modified in the last LIVE_MIN minutes. Files only: a deletion (e.g. a removed nested worktree)
  # touches its directory, not a file, and is no sign of a running session.
  local root=$1 g=$2 k hit=""
  if [ "$LIVE_MIN" -le 0 ]; then return 0; fi
  local -a pr=(-path "$root/.git")
  for k in "${WT_CANON[@]}"; do
    if [ "$k" != "$root" ] && is_under "$k" "$root"; then pr+=(-o -path "$k"); fi
  done
  hit=$(find "$root" \( "${pr[@]}" \) -prune -o \( -type f -o -type l \) -mmin "-$LIVE_MIN" -print -quit 2>/dev/null) || true
  if [ -z "$hit" ] && [ -n "$g" ] && [ -f "$g/index" ]; then
    hit=$(find "$g/index" -mmin "-$LIVE_MIN" -print 2>/dev/null) || true
  fi
  printf '%s' "$hit"
}
filter_files() { # drop caches (and venvs with --skip-venvs) from a list of relative paths
  if [ "$SKIP_VENVS" = 1 ]; then
    { grep -v -E "$CACHE_RE" || true; } | awk '
      { line[NR] = $0
        if ($0 ~ /(^|\/)pyvenv\.cfg$/) { d = $0; sub(/\/?pyvenv\.cfg$/, "", d); if (d != "") venv[d] = 1 } }
      END { for (i = 1; i <= NR; i++) { p = line[i]; keep = 1; q = p
              while ((k = match(q, /\/[^\/]*$/)) > 0) { q = substr(q, 1, k - 1); if (q in venv) { keep = 0; break } }
              if (keep) print p } }'
  else
    grep -v -E "$CACHE_RE" || true
  fi
}
# File lists are line-based, one escaped name per line: "\" becomes "\\" and a newline "\n", so any
# legal file name survives; dec_nul turns such a list back into NUL-terminated names for tar and find.
# shellcheck disable=SC2016 # perl code: perl expands it
enc_lines() { "$PERL" -0 -ne 'chomp; s/\\/\\\\/g; s/\n/\\n/g; print "$_\n"'; }
# shellcheck disable=SC2016 # perl code: perl expands it
dec_nul() { "$PERL" -ne 'chomp; s/\\(\\|n)/$1 eq "n" ? "\n" : "\\"/ge; print "$_\0"'; }
root_files() { # untracked + ignored files of worktree $1: escaped names relative to it, sorted.
  # Registered nested worktrees are left out (handled on their own); a nested repository that is not
  # a worktree is listed file by file. Status 3: git failed; 5: find failed.
  local root=$1 others rel
  others=$(git -C "$root" ls-files --others -z | enc_lines) || return 3
  if [ -z "$others" ]; then return 0; fi
  {
    printf '%s\n' "$others" | { grep -v '/$' || true; }
    printf '%s\n' "$others" | { grep '/$' || true; } | while IFS= read -r rel; do
      rel=$(printf '%s\n' "${rel%/}" | dec_nul | tr -d '\0')
      if is_registered "$root/$rel"; then continue; fi
      (cd -- "$root" && find "./$rel" \( -type f -o -type l \) -print0 | enc_lines | sed 's|^\./||') || exit 5
    done
  } | filter_files | sort -u
}
list_why() { # text for a root_files/item_files status
  case $1 in
    3) printf 'git ls-files failed' ;;
    5) printf 'find failed (permissions?)' ;;
    *) printf 'status %s' "$1" ;;
  esac
}
# shellcheck disable=SC2016 # perl code: perl expands it
coverage_of_list() { # stdin: escaped names relative to $1; stdout: size TAB mtime TAB name, sorted
  # (lstat: a symlink is recorded as itself; a name that vanished meanwhile is left out)
  (cd -- "$1" && "$PERL" -ne 'chomp; my $e = $_; (my $n = $e) =~ s/\\(\\|n)/$1 eq "n" ? "\n" : "\\"/ge;
    my @s = lstat($n); print "$s[7]\t$s[9]\t$e\n" if @s;') | sort || true
}
tracked_stream() { # HEAD, porcelain status of tracked files and `git diff --binary HEAD` of worktree $1
  # ($2 = its git dir). git runs on a scratch copy of the index: `git diff` refreshes stat data and
  # rewrites the index even with GIT_OPTIONAL_LOCKS=0, which would also make the worktree look live.
  local h idx=$WORK/index
  rm -f -- "$idx"
  if [ -n "$2" ] && [ -f "$2/index" ]; then cp -p -- "$2/index" "$idx"; fi
  h=$(git -C "$1" rev-parse -q --verify HEAD) || h=unborn
  printf 'HEAD %s\n' "$h"
  GIT_INDEX_FILE=$idx git -C "$1" status --porcelain=v1 --untracked-files=no 2>/dev/null || printf 'STATUS FAILED\n'
  GIT_INDEX_FILE=$idx git -C "$1" diff --binary HEAD 2>/dev/null || true
}
reflog_only_commits() { # commits no ref reaches (only reflogs, or nothing): what --gc would drop
  local out
  out=$(git -C "$M" fsck --unreachable --no-reflogs --no-progress 2>/dev/null) || return 1
  printf '%s\n' "$out" | awk '$1 == "unreachable" && $2 == "commit" { print $3 }' | sort
}
root_id() { # $1 canonical path, $2 index
  if [ "$2" = 0 ]; then printf 'M'; return 0; fi
  printf '%s-%s' "$(safe_name "$(basename -- "$1")")" "$(printf '%s' "$1" | sha_stdin | cut -c1-8)"
}

# ---------------------------------------------------------------- classify worktrees
WT_GITDIR=() WT_CLASS=() WT_ACTION=() WT_REASON=() WT_DIRTY=() WT_UNIQ=() WT_ID=()
is_removable() { case $1 in CLEAN | DIRTY) return 0 ;; esac; return 1; }
set_wt() { WT_CLASS[$1]=$2 WT_ACTION[$1]=$3 WT_REASON[$1]=$4; }
head_info() {
  local i=$1 s
  if [ "${WT_BRANCH[i]}" != - ]; then s="branch ${WT_BRANCH[i]}"; else s="detached ${WT_HEAD[i]:0:7}"; fi
  if [ "${WT_UNIQ[i]}" != 0 ]; then s="$s, ${WT_UNIQ[i]} commit(s) not in $MAIN"; fi
  printf '%s' "$s"
}
classify_worktrees() {
  local i j g op st why changed
  for ((i = 0; i < NWT; i++)); do
    WT_GITDIR[i]="" WT_DIRTY[i]=0 WT_UNIQ[i]=0 WT_ID[i]=$(root_id "${WT_CANON[i]}" "$i")
    if [ "${WT_HEAD[i]}" != - ]; then
      WT_UNIQ[i]=$(git -C "$M" rev-list --count "${WT_HEAD[i]}" "^$MAIN_SHA" 2>/dev/null) || WT_UNIQ[i]="?"
    fi
    if [ "${WT_PRUNABLE[i]}" = 1 ]; then
      set_wt "$i" PRUNABLE prune "directory missing; git worktree prune drops the stale entry"
      continue
    fi
    if [ "$i" = 0 ]; then g=$COMMON; else g=$(wt_gitdir "${WT_CANON[i]}"); fi
    WT_GITDIR[i]=$g
    if st=$(git -C "${WT_CANON[i]}" status --porcelain=v1 --untracked-files=normal 2>/dev/null); then
      WT_DIRTY[i]=$(count_lines "$st")
    else
      WT_DIRTY[i]="?"
    fi
    if [ "$i" = 0 ]; then
      set_wt "$i" MAIN keep "main checkout; never removed"
    elif [ "$i" = "$CALLER_IDX" ] || [ "$i" = "$SCRIPT_IDX" ]; then
      set_wt "$i" CALLER keep "the caller runs from here or it holds this script; never removed"
    elif [ "${WT_LOCKED[i]}" = 1 ]; then
      if [ "${WT_LOCKWHY[i]}" = - ]; then set_wt "$i" LOCKED skip "locked (no reason given)"
      else set_wt "$i" LOCKED skip "locked: ${WT_LOCKWHY[i]}"; fi
    elif is_session "${WT_CANON[i]}"; then
      set_wt "$i" SESSION skip "running session (--session-wt)"
    elif [ -z "$g" ]; then
      set_wt "$i" ERROR skip "no git dir found for this worktree"
    elif op=$(op_in_progress "$g") && [ -n "$op" ]; then
      set_wt "$i" IN-PROGRESS skip "$op in progress: finish or abort it first"
    elif [ -e "$g/index.lock" ]; then
      set_wt "$i" LIVE skip "index.lock present: git is running there"
    elif [ "${WT_DIRTY[i]}" = "?" ]; then
      set_wt "$i" ERROR skip "git status failed"
    elif why=$(recent_file "${WT_CANON[i]}" "$g") && [ -n "$why" ]; then
      set_wt "$i" LIVE skip "modified in the last $LIVE_MIN min: $(disp "$why")"
    elif [ "${WT_DIRTY[i]}" -gt 0 ]; then
      set_wt "$i" DIRTY "remove --force" "${WT_DIRTY[i]} uncommitted entr(ies), archived first"
    else
      set_wt "$i" CLEAN remove "clean"
    fi
  done
  # a worktree holding a kept worktree would delete it on removal: keep it as well (to a fixpoint)
  changed=1
  while [ "$changed" = 1 ]; do
    changed=0
    for ((i = 1; i < NWT; i++)); do
      if ! is_removable "${WT_CLASS[i]}"; then continue; fi
      for ((j = 1; j < NWT; j++)); do
        if [ "$j" = "$i" ] || [ "${WT_PRUNABLE[j]}" = 1 ] || is_removable "${WT_CLASS[j]}"; then continue; fi
        if is_under "${WT_CANON[j]}" "${WT_CANON[i]}"; then
          set_wt "$i" NESTED skip "contains kept worktree $(disp "${WT_CANON[j]}") (${WT_CLASS[j]})"
          changed=1
          break
        fi
      done
    done
  done
}

# ---------------------------------------------------------------- classify branches
BR_NAME=() BR_TIP=() BR_UNIQ=() BR_WT=() BR_CLASS=() BR_ACTION=() BR_REASON=()
busy_branch() { # branch named in a rebase or bisect state of git dir $1 (porcelain shows such a worktree as detached)
  local g=$1 f line
  for f in "$g/rebase-merge/head-name" "$g/rebase-apply/head-name" "$g/BISECT_START"; do
    if [ -f "$f" ]; then
      IFS= read -r line <"$f" || true
      printf '%s' "${line#refs/heads/}"
      return 0
    fi
  done
}
wt_of_branch() { # worktree with branch $1 checked out, or being rebased/bisected there; -1 if none
  local i g
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_BRANCH[i]}" = "$1" ]; then printf '%s' "$i"; return 0; fi
  done
  for ((i = 0; i < NWT; i++)); do
    g=${WT_GITDIR[i]:-}
    if [ -n "$g" ] && [ "$(busy_branch "$g")" = "$1" ]; then printf '%s' "$i"; return 0; fi
  done
  printf '%s' -1
}
classify_branches() {
  local ref tip i=0 w
  while read -r ref tip; do
    BR_NAME[i]=${ref#refs/heads/} BR_TIP[i]=$tip
    BR_UNIQ[i]=$(git -C "$M" rev-list --count "$tip" "^$MAIN_SHA") || BR_UNIQ[i]="?"
    BR_WT[i]=$(wt_of_branch "${BR_NAME[i]}")
    w=${BR_WT[i]}
    if [ "${BR_NAME[i]}" = "$MAIN" ]; then
      BR_CLASS[i]=MAIN BR_ACTION[i]=keep BR_REASON[i]="the branch that stays"
    elif [ "$w" -ge 0 ] && ! is_removable "${WT_CLASS[w]}"; then
      BR_CLASS[i]=KEPT BR_ACTION[i]=skip BR_REASON[i]="checked out (or being rebased/bisected) in $(disp "${WT_CANON[w]}") (${WT_CLASS[w]})"
      if [ "${BR_UNIQ[i]}" != 0 ]; then BR_REASON[i]="${BR_REASON[i]}; ${BR_UNIQ[i]} commit(s) not in $MAIN, bundled in stage 1"; fi
    elif [ "${BR_UNIQ[i]}" = 0 ]; then
      BR_CLASS[i]=MERGED BR_ACTION[i]="branch -d" BR_REASON[i]="tip is in $MAIN"
    else
      BR_CLASS[i]=UNIQUE BR_ACTION[i]="branch -D" BR_REASON[i]="${BR_UNIQ[i]} commit(s) not in $MAIN; -D only once its bundle verifies"
    fi
    if [ "$w" -ge 0 ] && is_removable "${WT_CLASS[w]}"; then
      BR_REASON[i]="${BR_REASON[i]}; after its worktree is removed"
    fi
    i=$((i + 1))
  done < <(git -C "$M" for-each-ref --format='%(refname) %(objectname)' refs/heads)
  NBR=$i
}

# ---------------------------------------------------------------- named items
IT_NAME=() IT_PATH=() IT_SECRET=()
add_item() { # name path secret
  local p
  p=$(canon "$2")
  IT_NAME+=("$1") IT_PATH+=("$p") IT_SECRET+=("$3")
}
build_items() {
  local i
  if [ "$DEFAULT_ITEMS" = 1 ]; then
    add_item eq-t "$M/.claude-work/worktrees/eq-t-1005/.claude-work/equilibrium" 0
    add_item eq-t-snapshot "$DEFAULT_LAST/.claude-work/t1b/equilibrium-snapshot-1611" 0
    add_item c0-data "$M/.claude-work/context-diet" 0
    add_item transcripts "$M/.claude-work/context-diet/data/transcripts" 1
    add_item transcripts-top "$M/.claude-work/context-diet/transcripts" 1
    add_item work_carried "$M/claude_next_steps/work_carried" 0
    for ((i = 0; i < NWT; i++)); do
      if [ "${WT_PRUNABLE[i]}" = 0 ] && [ -d "${WT_CANON[i]}/claude_info" ]; then
        add_item "claude_info-${WT_ID[i]}" "${WT_CANON[i]}/claude_info" 0
      fi
    done
  fi
  for ((i = 0; i < ${#U_NAMES[@]}; i++)); do add_item "${U_NAMES[i]}" "${U_PATHS[i]}" "${U_SECRET[i]}"; done
}
item_files() { # files of item $1: escaped names relative to its parent dir; nested worktrees and
  # nested items left out. Status 5: find failed.
  local k=$1 p=${IT_PATH[$1]} parent base x j
  parent=$(dirname -- "$p") base=$(basename -- "$p")
  local -a pr=(-false)
  for x in "${WT_CANON[@]}"; do
    if [ "$x" != "$p" ] && is_under "$x" "$p"; then pr+=(-o -path "./$base${x#"$p"}"); fi
  done
  for ((j = 0; j < ${#IT_PATH[@]}; j++)); do
    x=${IT_PATH[j]}
    if [ "$j" != "$k" ] && [ "$x" != "$p" ] && is_under "$x" "$p"; then pr+=(-o -path "./$base${x#"$p"}"); fi
  done
  (cd -- "$parent" && find "./$base" \( "${pr[@]}" \) -prune -o \( -type f -o -type l \) -print0 |
    enc_lines | sed 's|^\./||') | sort
}
list_stats() { # stdin: coverage lines; prints "<files> files, <size>"
  awk -F '\t' '{ n++; s += $1 } END { printf "%d %d\n", n, s }' | {
    read -r nn ss
    printf '%s file(s), %s' "$nn" "$(human "$ss")"
  }
}

# ---------------------------------------------------------------- manifest
MF_KIND=() MF_SRC=() MF_FILE=() MF_SHA=() MF_BYTES=() MF_STATE=()
mf_find() { # row index of kind $1 and source $2, or -1
  local i
  for ((i = 0; i < ${#MF_KIND[@]}; i++)); do
    if [ "${MF_KIND[i]}" = "$1" ] && [ "${MF_SRC[i]}" = "$2" ]; then printf '%s' "$i"; return 0; fi
  done
  printf '%s' -1
}
mf_set() { # kind source absolute-file state: add or replace the row
  local i rel=${3#"$DIR_C"/}
  i=$(mf_find "$1" "$2")
  if [ "$i" -lt 0 ]; then i=${#MF_KIND[@]}; fi
  MF_KIND[i]=$1 MF_SRC[i]=$2 MF_FILE[i]=$rel MF_SHA[i]=$(sha_of "$3") MF_BYTES[i]=$(bytes_of "$3") MF_STATE[i]=$4
}
row_ok() { # file of row $1 exists with the recorded size and sha256
  local f=$DIR_C/${MF_FILE[$1]}
  [ -f "$f" ] || return 1
  [ "$(bytes_of "$f")" = "${MF_BYTES[$1]}" ] || return 1
  [ "$(sha_of "$f")" = "${MF_SHA[$1]}" ] || return 1
}
row_current() { # a row of kind $1 / source $2 with state $3 exists and verifies
  local i
  i=$(mf_find "$1" "$2")
  [ "$i" -ge 0 ] || return 1
  [ "${MF_STATE[i]}" = "$3" ] || return 1
  row_ok "$i"
}
load_manifest() { # 1 when absent; exits 4 on a malformed or foreign manifest
  local f=$DIR_C/MANIFEST.tsv line repo k s a h b st
  MF_KIND=() MF_SRC=() MF_FILE=() MF_SHA=() MF_BYTES=() MF_STATE=()
  [ -f "$f" ] || return 1
  IFS= read -r line <"$f" || die 4 "empty manifest: $f"
  case $line in '# RESET_TO_MAIN manifest v1'*) ;; *) die 4 "not a RESET_TO_MAIN manifest: $f" ;; esac
  repo=$(printf '%s\n' "$line" | tr '\t' '\n' | sed -n 's/^repo=//p')
  if [ "$repo" != "$M" ]; then die 4 "the manifest is for '$repo', not '$M'"; fi
  while IFS=$TAB read -r k s a h b st; do
    case $k in '#'* | '') continue ;; esac
    case $a in /* | ../* | */../* | *'/..' | '') die 4 "unsafe archive path in the manifest: $a" ;; esac
    case $h in *[!0-9a-f]* | '') die 4 "bad sha256 in the manifest row for $a" ;; esac
    case $b in *[!0-9]* | '') die 4 "bad size in the manifest row for $a" ;; esac
    MF_KIND+=("$k") MF_SRC+=("$s") MF_FILE+=("$a") MF_SHA+=("$h") MF_BYTES+=("$b") MF_STATE+=("${st:--}")
  done <"$f"
}
write_manifest() {
  local i f=$DIR_C/MANIFEST.tsv
  {
    printf '# RESET_TO_MAIN manifest v1\trepo=%s\tmain=%s\tcreated=%s\n' "$M" "$MAIN_SHA" "$(date '+%Y-%m-%d %H:%M:%S')"
    printf '#kind\tsource\tarchive_file\tsha256\tbytes\tstate\n'
    for ((i = 0; i < ${#MF_KIND[@]}; i++)); do
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "${MF_KIND[i]}" "${MF_SRC[i]}" "${MF_FILE[i]}" "${MF_SHA[i]}" "${MF_BYTES[i]}" "${MF_STATE[i]}"
    done
  } >"$f.part"
  mv -f -- "$f.part" "$f"
  (cd -- "$DIR_C" && shasum -a 256 MANIFEST.tsv) >"$f.sha256.part"
  mv -f -- "$f.sha256.part" "$f.sha256"
}
verify_archive() { # every row's size and sha256, the manifest's sha256, every bundle; 1 on any failure
  local i bad=0 exp act
  if [ ! -f "$DIR_C/MANIFEST.tsv.sha256" ]; then say "  ! MANIFEST.tsv.sha256 is missing"; return 1; fi
  exp=$(awk 'NR == 1 { print $1 }' "$DIR_C/MANIFEST.tsv.sha256")
  act=$(sha_of "$DIR_C/MANIFEST.tsv")
  if [ "$exp" != "$act" ]; then say "  ! MANIFEST.tsv does not match MANIFEST.tsv.sha256"; return 1; fi
  if [ "${#MF_KIND[@]}" -eq 0 ]; then say "  ! the manifest has no rows"; return 1; fi
  for ((i = 0; i < ${#MF_KIND[@]}; i++)); do
    if ! row_ok "$i"; then
      say "  ! ${MF_FILE[i]}: missing, or size/sha256 differ from the manifest"
      bad=1
      continue
    fi
    case ${MF_KIND[i]} in
      bundle*)
        if ! git -C "$M" bundle verify -q "$DIR_C/${MF_FILE[i]}" >/dev/null 2>&1; then
          say "  ! ${MF_FILE[i]}: git bundle verify failed"
          bad=1
        fi ;;
    esac
  done
  [ "$bad" = 0 ]
}

# ---------------------------------------------------------------- stage 1: archive
WORK="" LOCKED_DIR="" ITEM_FAILS=0 RUN=""
# shellcheck disable=SC2329 # invoked by the EXIT trap below
cleanup() {
  local f
  if [ -n "$WORK" ] && [ -d "$WORK" ]; then
    for f in list cov ilist icov extra tracked unreach covered err index; do
      if [ -e "$WORK/$f" ]; then rm -f -- "$WORK/$f"; fi
    done
    rmdir -- "$WORK" 2>/dev/null || true
  fi
  if [ -n "$LOCKED_DIR" ]; then rmdir -- "$LOCKED_DIR" 2>/dev/null || true; fi
}
trap cleanup EXIT
start_work() {
  WORK=$(mktemp -d "${TMPDIR:-/tmp}/reset_to_main.XXXXXX") || die 1 "mktemp failed"
  if ! mkdir -- "$DIR_C/.lock" 2>/dev/null; then
    die 3 "lock $DIR_C/.lock is held: another run is active (or crashed: rmdir it)"
  fi
  LOCKED_DIR=$DIR_C/.lock
}
item_fail() { ITEM_FAILS=$((ITEM_FAILS + 1)); printf '  ! FAILED: %s\n' "$*"; }
keep_msg() { printf '  keep  %s (unchanged, verified)\n' "$*"; }

archive_bundle() { # kind source where stem rev...: bundle, verify, record (state = bundled tip)
  local kind=$1 src=$2 where=$3 stem=$4 f err tip
  shift 4
  f=$DIR_C/bundles/$stem.$RUN.bundle
  cmdline git -C "$where" bundle create -q "$f" "$@"
  if ! err=$(git -C "$where" bundle create -q "$f.part" "$@" 2>&1); then item_fail "$kind $src: $err"; return 0; fi
  if ! err=$(git -C "$M" bundle verify -q "$f.part" 2>&1); then item_fail "$kind $src: git bundle verify: $err"; return 0; fi
  tip=$(git -C "$M" bundle list-heads "$f.part" | awk 'NR == 1 { print $1 }')
  mv -f -- "$f.part" "$f"
  mf_set "$kind" "$src" "$f" "$tip"
}
archive_reflog_pack() {
  local list lsha stem hash
  if ! list=$(reflog_only_commits); then item_fail "reflog-only commits: git fsck failed"; return 0; fi
  if [ -z "$list" ]; then say "  no commit is reachable only from reflogs"; return 0; fi
  lsha=$(printf '%s\n' "$list" | sha_stdin)
  if row_current pack reflog-only "$lsha" && row_current pack-list reflog-only "$lsha"; then keep_msg "reflog-only pack"; return 0; fi
  stem=$DIR_C/packs/reflog-only.$RUN
  say "  $(count_lines "$list") commit(s) reachable only from reflogs (or from nothing): packed"
  cmdline git -C "$M" pack-objects -q --revs "$stem"
  if ! hash=$({ printf '%s\n' "$list"; printf '^%s\n' "$MAIN_SHA"; } | git -C "$M" pack-objects -q --revs "$stem.part"); then
    item_fail "reflog-only pack: git pack-objects failed"
    return 0
  fi
  printf '%s\n' "$list" >"$stem.txt.part"
  mv -f -- "$stem.part-$hash.pack" "$stem-$hash.pack"
  mv -f -- "$stem.part-$hash.idx" "$stem-$hash.idx"
  mv -f -- "$stem.txt.part" "$stem.txt"
  mf_set pack reflog-only "$stem-$hash.pack" "$lsha"
  mf_set pack-idx reflog-only "$stem-$hash.idx" "$lsha"
  mf_set pack-list reflog-only "$stem.txt" "$lsha"
}
archive_root() { # status, tracked stream, file list and data tarball of worktree $1
  local i=$1 p=${WT_CANON[$1]} stem sig csha nfiles rc=0 err
  stem=$DIR_C/worktrees/${WT_ID[i]}.$RUN
  root_files "$p" >"$WORK/list" || rc=$?
  if [ "$rc" != 0 ]; then
    item_fail "$(disp "$p"): cannot list its untracked/ignored files: $(list_why "$rc")"
    return 0
  fi
  coverage_of_list "$p" <"$WORK/list" >"$WORK/cov"
  csha=$(sha_of "$WORK/cov")
  nfiles=$(wc -l <"$WORK/cov" | tr -d ' ')
  tracked_stream "$p" "${WT_GITDIR[i]}" >"$WORK/tracked"
  sig=$(sha_of "$WORK/tracked")
  if row_current wt-diff "$p" "$sig" && row_current wt-files "$p" "$csha" &&
    [ "$(mf_find wt-status "$p")" -ge 0 ] && row_ok "$(mf_find wt-status "$p")" &&
    [ "$(mf_find wt-data "$p")" -ge 0 ] && row_ok "$(mf_find wt-data "$p")"; then
    keep_msg "$(disp "$p")"
    return 0
  fi
  say "  $(disp "$p"): $nfiles untracked/ignored file(s); $(head_info "$i"); ${WT_DIRTY[i]} status entr(ies)"
  if ! git -C "$p" status --porcelain=v1 --untracked-files=normal >"$stem.status.part" 2>/dev/null; then
    item_fail "$(disp "$p"): git status failed"
    return 0
  fi
  cp -- "$WORK/tracked" "$stem.diff.part"
  cp -- "$WORK/cov" "$stem.files.part"
  if ! err=$(cut -f3- "$WORK/cov" | dec_nul | tar -czf "$stem.data.tar.gz.part" -C "$p" -n --null -T - 2>&1); then
    item_fail "$(disp "$p"): tar: $err"
    return 0
  fi
  mv -f -- "$stem.status.part" "$stem.status"
  mv -f -- "$stem.diff.part" "$stem.diff"
  mv -f -- "$stem.files.part" "$stem.files"
  mv -f -- "$stem.data.tar.gz.part" "$stem.data.tar.gz"
  mf_set wt-status "$p" "$stem.status" -
  mf_set wt-diff "$p" "$stem.diff" "$sig"
  mf_set wt-files "$p" "$stem.files" "$csha"
  mf_set wt-data "$p" "$stem.data.tar.gz" "$nfiles"
}
archive_item() { # named tarball of item $1
  local k=$1 p=${IT_PATH[$1]} name=${IT_NAME[$1]} kind=data parent csha f err rc
  if [ ! -e "$p" ]; then say "  absent: $name ($(disp "$p"))"; return 0; fi
  if [ "${IT_SECRET[k]}" = 1 ]; then kind=secret-data; fi
  parent=$(dirname -- "$p")
  rc=0
  item_files "$k" >"$WORK/ilist" || rc=$?
  if [ "$rc" != 0 ]; then item_fail "item $name: cannot list $(disp "$p"): $(list_why "$rc")"; return 0; fi
  coverage_of_list "$parent" <"$WORK/ilist" >"$WORK/icov"
  csha=$(sha_of "$WORK/icov")
  if row_current "$kind" "$p" "$csha"; then keep_msg "$kind $name"; return 0; fi
  f=$DIR_C/data/$name.$RUN.tar.gz
  say "  $name: $(list_stats <"$WORK/icov") from $(disp "$p")"
  if ! err=$(dec_nul <"$WORK/ilist" | tar -czf "$f.part" -C "$parent" -n --null -T - 2>&1); then
    item_fail "item $name: tar: $err"
    return 0
  fi
  chmod 600 "$f.part"
  mv -f -- "$f.part" "$f"
  mf_set "$kind" "$p" "$f" "$csha"
  if [ "$kind" = secret-data ]; then
    say "  NOTE: $(disp "$f") is mode 0600: it may hold secrets (session transcripts)"
  fi
}
write_restore() {
  local f=$DIR_C/RESTORE.$RUN.txt
  {
    say "RESET_TO_MAIN archive of $M (main $MAIN_SHA), run $RUN"
    say ""
    say "Check:     cd <this dir> && shasum -a 256 -c MANIFEST.tsv.sha256, then every row's sha256"
    say "           (column 4) against its file (column 3): RESET_TO_MAIN.sh --apply re-checks all."
    say "Repo:      git clone bundles/main.<run>.bundle repo"
    say "Branch:    git -C repo fetch <dir>/bundles/br-<name>.<run>.bundle 'refs/heads/*:refs/heads/*'"
    say "Detached:  git -C repo fetch <dir>/bundles/head-<id>.<run>.bundle HEAD && git -C repo branch rescued FETCH_HEAD"
    say "Reflog-only commits: git -C repo index-pack --stdin < packs/reflog-only.<run>-<hash>.pack"
    say "           (the commit ids are in packs/reflog-only.<run>.txt)"
    say "Worktree:  git -C repo worktree add <path> <branch or sha>;"
    say "           git -C <path> apply --binary worktrees/<id>.<run>.diff   (tracked changes; the"
    say "           HEAD/status lines at its top are ignored by git apply);"
    say "           tar -xzf worktrees/<id>.<run>.data.tar.gz -C <path>      (untracked + ignored files)"
    say "Item:      tar -xzf data/<name>.<run>.tar.gz -C <parent dir of the original path>"
    say "Every file here is mode 0600; secret-data rows (session transcripts) may hold secrets, and so"
    say "may the data tarball of the worktree that contains them."
  } >"$f.part"
  mv -f -- "$f.part" "$f"
  mf_set readme - "$f" -
}
archive_stage() {
  local i d
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 0 ] && is_under "$DIR_C" "${WT_CANON[i]}"; then
      die 3 "DIR $DIR_C lies inside worktree $(disp "${WT_CANON[i]}"): pick a DIR outside every worktree"
    fi
  done
  if [ -d "$DIR_C" ] && [ -n "$(ls -A -- "$DIR_C")" ] && [ "$RESUME" = 0 ]; then
    die 3 "DIR $DIR_C is not empty: use --resume to continue in it, or pick an empty DIR"
  fi
  umask 077
  if [ ! -d "$(dirname -- "$DIR_C")" ]; then die 3 "the parent of DIR does not exist: $(dirname -- "$DIR_C")"; fi
  for d in "$DIR_C" "$DIR_C/bundles" "$DIR_C/worktrees" "$DIR_C/data" "$DIR_C/packs"; do
    if [ ! -d "$d" ]; then mkdir -m 700 -- "$d"; fi
  done
  start_work
  if [ "$RESUME" = 1 ]; then
    if load_manifest; then say "resume: ${#MF_KIND[@]} row(s) in the existing manifest"; fi
  fi
  RUN=$(date '+%Y%m%dT%H%M%S')
  say ""
  say "== Stage 1: archive into $DIR_C (run $RUN; umask 077: files 0600, dirs 0700) =="
  say "-- bundles"
  if row_current bundle-main "refs/heads/$MAIN" "$MAIN_SHA"; then keep_msg "bundle of $MAIN"
  else archive_bundle bundle-main "refs/heads/$MAIN" "$M" main "refs/heads/$MAIN"; fi
  for ((i = 0; i < NBR; i++)); do
    if [ "${BR_NAME[i]}" = "$MAIN" ] || [ "${BR_UNIQ[i]}" = 0 ]; then continue; fi
    if row_current bundle "refs/heads/${BR_NAME[i]}" "${BR_TIP[i]}"; then keep_msg "bundle of ${BR_NAME[i]}"; continue; fi
    archive_bundle bundle "refs/heads/${BR_NAME[i]}" "$M" \
      "br-$(safe_name "${BR_NAME[i]}")-$(printf '%s' "${BR_NAME[i]}" | sha_stdin | cut -c1-6)" \
      "refs/heads/${BR_NAME[i]}" "^refs/heads/$MAIN"
  done
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ] || [ "${WT_BRANCH[i]}" != - ] || [ "${WT_UNIQ[i]}" = 0 ]; then continue; fi
    if row_current bundle-head "${WT_CANON[i]}" "${WT_HEAD[i]}"; then keep_msg "bundle of HEAD in $(disp "${WT_CANON[i]}")"; continue; fi
    archive_bundle bundle-head "${WT_CANON[i]}" "${WT_CANON[i]}" "head-${WT_ID[i]}" HEAD "^refs/heads/$MAIN"
  done
  say "-- commits reachable only from reflogs"
  archive_reflog_pack
  say "-- worktrees (status, HEAD + tracked diff, file list, untracked/ignored data)"
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ]; then continue; fi
    archive_root "$i"
  done
  say "-- named items"
  for ((i = 0; i < ${#IT_NAME[@]}; i++)); do archive_item "$i"; done
  write_restore
  write_manifest
  say "-- verification (sha256 of every file, git bundle verify of every bundle)"
  if ! verify_archive; then die 4 "the archive in $DIR_C does not verify"; fi
  say "  ok: ${#MF_KIND[@]} manifest row(s) verified; MANIFEST.tsv.sha256 matches"
  say "  NOTE: every archive file is mode 0600 in a 0700 dir; the transcripts (secret-data rows) may hold"
  say "        secrets, and so may the data tarball of the worktree that contains them (M)."
}

# ---------------------------------------------------------------- stage 2: apply
GATE_WHY=""
gate_rows() { # worktree $1 has all four rows
  local k
  for k in wt-status wt-diff wt-files wt-data; do
    if [ "$(mf_find "$k" "$1")" -lt 0 ]; then GATE_WHY="not in the archive (no $k row): run --archive --resume"; return 1; fi
  done
}
gate_coverage() { # every untracked/ignored file of worktree $1 is in its archived list, unchanged
  local p=$1 r rc=0 n
  root_files "$p" >"$WORK/list" || rc=$?
  if [ "$rc" != 0 ]; then GATE_WHY="cannot list its untracked/ignored files: $(list_why "$rc")"; return 1; fi
  coverage_of_list "$p" <"$WORK/list" >"$WORK/cov"
  r=$(mf_find wt-files "$p")
  comm -23 "$WORK/cov" "$DIR_C/${MF_FILE[r]}" >"$WORK/extra"
  if [ -s "$WORK/extra" ]; then
    n=$(wc -l <"$WORK/extra" | tr -d ' ')
    GATE_WHY="$n untracked/ignored file(s) new or changed since the archive, e.g. $(head -n 1 "$WORK/extra" | cut -f3-): run --archive --resume"
    return 1
  fi
}
gate_root() { # worktree index $1: rows, tracked state, files, detached HEAD bundle
  local i=$1 p=${WT_CANON[$1]} r
  gate_rows "$p" || return 1
  r=$(mf_find wt-diff "$p")
  if [ "$(tracked_stream "$p" "${WT_GITDIR[i]}" | sha_stdin)" != "${MF_STATE[r]}" ]; then
    GATE_WHY="HEAD or tracked changes differ from the archive: run --archive --resume"
    return 1
  fi
  gate_coverage "$p" || return 1
  if [ "${WT_BRANCH[i]}" = - ] && [ "${WT_UNIQ[i]}" != 0 ]; then
    r=$(mf_find bundle-head "$p")
    if [ "$r" -lt 0 ] || [ "${MF_STATE[r]}" != "${WT_HEAD[i]}" ]; then
      GATE_WHY="detached HEAD with commits not in $MAIN has no bundle at this HEAD"
      return 1
    fi
  fi
}
FRESH_WHY=""
fresh_ok() { # re-check worktree $1 right before its removal
  local i=$1 p=${WT_CANON[$1]} path h b lk w pr x pc found=0 op hit
  FRESH_WHY=""
  while IFS=$SEP read -r path h b lk w pr x; do
    if [ "$pr" = 1 ]; then continue; fi
    pc=$(canon "$path")
    if [ "$pc" = "$p" ]; then
      found=1
      if [ "$lk" = 1 ]; then FRESH_WHY="locked: $w"; return 1; fi
    elif is_under "$pc" "$p"; then
      FRESH_WHY="still contains registered worktree $(disp "$pc")"
      return 1
    fi
  done < <(read_worktrees)
  if [ "$found" = 0 ]; then FRESH_WHY="no longer a registered worktree"; return 1; fi
  op=$(op_in_progress "${WT_GITDIR[i]}")
  if [ -n "$op" ]; then FRESH_WHY="$op in progress"; return 1; fi
  if [ -e "${WT_GITDIR[i]}/index.lock" ]; then FRESH_WHY="index.lock present"; return 1; fi
  hit=$(recent_file "$p" "${WT_GITDIR[i]}")
  if [ -n "$hit" ]; then FRESH_WHY="modified in the last $LIVE_MIN min: $(disp "$hit")"; return 1; fi
}
run_git() { # print and run a git command; its output indented; 1 on failure
  local out
  cmdline git "$@"
  if out=$(git "$@" 2>&1); then
    if [ -n "$out" ]; then printf '%s\n' "$out" | sed 's/^/      /'; fi
    return 0
  fi
  printf '%s\n' "$out" | sed 's/^/      ! /'
  return 1
}
removal_order() { # removable worktree indices: deepest path first, --last at the very end
  local i d
  for ((i = 1; i < NWT; i++)); do
    if ! is_removable "${WT_CLASS[i]}" || [ "${WT_CANON[i]}" = "$LAST_C" ]; then continue; fi
    d=$(printf '%s' "${WT_CANON[i]}" | tr -cd '/' | wc -c | tr -d ' ')
    printf '%s %s\n' "$d" "$i"
  done | sort -k1,1nr -k2,2n | cut -d' ' -f2
  for ((i = 1; i < NWT; i++)); do
    if is_removable "${WT_CLASS[i]}" && [ "${WT_CANON[i]}" = "$LAST_C" ]; then printf '%s\n' "$i"; fi
  done
}
APPLY_FAILS=0 STEP_PRUNE="" STEP_CLEAN="" STEP_GC=""
apply_worktrees() {
  local i args
  say "-- worktrees (nested first, $(disp "$LAST_C") last)"
  for i in $(removal_order); do
    if ! fresh_ok "$i"; then
      set_wt "$i" "${WT_CLASS[i]}" skipped "$FRESH_WHY"
      say "  skip $(disp "${WT_CANON[i]}"): $FRESH_WHY"
      continue
    fi
    if ! gate_root "$i"; then
      set_wt "$i" "${WT_CLASS[i]}" skipped "$GATE_WHY"
      say "  skip $(disp "${WT_CANON[i]}"): $GATE_WHY"
      continue
    fi
    args=()
    if [ "${WT_CLASS[i]}" = DIRTY ]; then args=(--force); fi
    if run_git -C "$M" worktree remove ${args[@]+"${args[@]}"} "${WT_PATH[i]}"; then
      set_wt "$i" "${WT_CLASS[i]}" removed "archived and verified"
    else
      APPLY_FAILS=$((APPLY_FAILS + 1))
      set_wt "$i" "${WT_CLASS[i]}" FAILED "git worktree remove failed (output above)"
    fi
  done
}
apply_prune() {
  local i bad=""
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ] && [ "${WT_BRANCH[i]}" = - ] && [ "${WT_UNIQ[i]}" != 0 ]; then bad=$i; fi
  done
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ]; then break; fi
  done
  if [ "$i" -ge "$NWT" ]; then STEP_PRUNE="none prunable"; return 0; fi
  say "-- prune stale worktree entries"
  if [ -n "$bad" ]; then
    STEP_PRUNE="skipped: $(disp "${WT_CANON[bad]}") is missing with a detached HEAD holding commits not in $MAIN"
    say "  $STEP_PRUNE"
    return 0
  fi
  run_git -C "$M" worktree prune --dry-run -v || true
  if run_git -C "$M" worktree prune -v; then STEP_PRUNE="pruned"; else STEP_PRUNE="FAILED"; APPLY_FAILS=$((APPLY_FAILS + 1)); fi
}
checked_out_now() { # registered worktree that has branch $1 checked out, or rebases/bisects it, now
  local path h b lk w pr x g
  while IFS=$SEP read -r path h b lk w pr x; do
    if [ "$pr" = 1 ]; then continue; fi
    if [ "$b" = "$1" ]; then printf '%s' "$path"; return 0; fi
    g=$(wt_gitdir "$path")
    if [ -z "$g" ] && [ "$(canon "$path")" = "$M" ]; then g=$COMMON; fi
    if [ -n "$g" ] && [ "$(busy_branch "$g")" = "$1" ]; then printf '%s' "$path"; return 0; fi
  done < <(read_worktrees)
}
apply_branches() {
  local i b tip wt r
  say "-- branches"
  for ((i = 0; i < NBR; i++)); do
    b=${BR_NAME[i]}
    if [ "$b" = "$MAIN" ]; then continue; fi
    if ! tip=$(git -C "$M" rev-parse -q --verify "refs/heads/$b"); then
      BR_ACTION[i]=gone BR_REASON[i]="no longer exists"
      continue
    fi
    wt=$(checked_out_now "$b")
    if [ -n "$wt" ]; then
      BR_ACTION[i]=skipped BR_REASON[i]="checked out (or being rebased/bisected) in $(disp "$(canon "$wt")")"
      continue
    fi
    if git -C "$M" merge-base --is-ancestor "$tip" "$MAIN_SHA"; then
      if run_git -C "$M" branch -d "$b"; then BR_ACTION[i]="deleted (-d)" BR_REASON[i]="merged into $MAIN"
      else APPLY_FAILS=$((APPLY_FAILS + 1)); BR_ACTION[i]=FAILED BR_REASON[i]="git branch -d failed"; fi
      continue
    fi
    r=$(mf_find bundle "refs/heads/$b")
    if [ "$r" -ge 0 ] && [ "${MF_STATE[r]}" = "$tip" ]; then
      if run_git -C "$M" branch -D "$b"; then BR_ACTION[i]="deleted (-D)" BR_REASON[i]="tip ${tip:0:7} is in the verified bundle ${MF_FILE[r]}"
      else APPLY_FAILS=$((APPLY_FAILS + 1)); BR_ACTION[i]=FAILED BR_REASON[i]="git branch -D failed"; fi
    else
      BR_ACTION[i]=skipped BR_REASON[i]="not merged and no verified bundle holds tip ${tip:0:7}: run --archive --resume"
      say "  skip $b: ${BR_REASON[i]}"
    fi
  done
}
m_live_why() { # why M itself counts as live, if it does
  local op hit
  op=$(op_in_progress "$COMMON")
  if [ -n "$op" ]; then printf '%s in progress in M' "$op"; return 0; fi
  if [ -e "$COMMON/index.lock" ]; then printf 'index.lock present in M'; return 0; fi
  hit=$(recent_file "$M" "$COMMON")
  if [ -n "$hit" ]; then printf 'M modified in the last %s min: %s' "$LIVE_MIN" "$(disp "$hit")"; fi
}
apply_clean() {
  local why
  if [ "$CLEAN" = 0 ]; then STEP_CLEAN="not requested (--clean)"; return 0; fi
  say "-- clean M (git clean -fdx; nested worktrees are skipped by git)"
  why=$(m_live_why)
  if [ -n "$why" ]; then STEP_CLEAN="skipped: $why"; say "  skip: $why"; return 0; fi
  if ! gate_rows "$M" || ! gate_coverage "$M"; then STEP_CLEAN="skipped: M $GATE_WHY"; say "  skip: M $GATE_WHY"; return 0; fi
  run_git -C "$M" clean -ndx || true
  if run_git -C "$M" clean -fdx; then STEP_CLEAN="done: every deleted file was in the verified archive"
  else STEP_CLEAN="FAILED"; APPLY_FAILS=$((APPLY_FAILS + 1)); fi
}
gc_blockers() { # live or locked worktrees still registered (M and the caller excluded)
  local path h b lk w pr x pc i out=""
  while IFS=$SEP read -r path h b lk w pr x; do
    if [ "$pr" = 1 ]; then continue; fi
    pc=$(canon "$path")
    if [ "$pc" = "$M" ]; then continue; fi
    if [ "$CALLER_IDX" -ge 0 ] && [ "$pc" = "${WT_CANON[CALLER_IDX]}" ]; then continue; fi
    if [ "$lk" = 1 ]; then out="$out $(disp "$pc")(locked)"; continue; fi
    for ((i = 0; i < NWT; i++)); do
      if [ "${WT_CANON[i]}" = "$pc" ]; then
        case ${WT_CLASS[i]} in LIVE | SESSION | IN-PROGRESS | ERROR) out="$out $(disp "$pc")(${WT_CLASS[i]})" ;; esac
      fi
    done
  done < <(read_worktrees)
  printf '%s' "${out# }"
}
apply_gc() {
  local why tips="" i n
  if [ "$GC" = 0 ]; then STEP_GC="not requested (--gc)"; return 0; fi
  say "-- reflog expire + gc"
  why=$(gc_blockers)
  if [ -n "$why" ]; then STEP_GC="skipped: live or locked worktrees remain: $why"; say "  $STEP_GC"; return 0; fi
  if git -C "$M" rev-parse -q --verify refs/stash >/dev/null; then
    STEP_GC="skipped: refs/stash exists (reflog expire would drop the stash entries)"
    say "  $STEP_GC"
    return 0
  fi
  if ! reflog_only_commits >"$WORK/unreach"; then STEP_GC="skipped: git fsck failed"; say "  $STEP_GC"; return 0; fi
  for ((i = 0; i < ${#MF_KIND[@]}; i++)); do
    case ${MF_KIND[i]} in
      bundle | bundle-head)
        if git -C "$M" cat-file -e "${MF_STATE[i]}^{commit}" 2>/dev/null; then tips="$tips ${MF_STATE[i]}"; fi ;;
    esac
  done
  {
    i=$(mf_find pack-list reflog-only)
    if [ "$i" -ge 0 ]; then cat -- "$DIR_C/${MF_FILE[i]}"; fi
    # shellcheck disable=SC2086 # $tips is a list of commit ids
    if [ -n "$tips" ]; then git -C "$M" rev-list $tips "^$MAIN_SHA"; fi
  } | sort -u >"$WORK/covered"
  n=$(comm -23 "$WORK/unreach" "$WORK/covered" | wc -l | tr -d ' ')
  if [ "$n" != 0 ]; then
    STEP_GC="skipped: $n commit(s) gc would drop are in no archived pack or bundle: run --archive --resume"
    say "  $STEP_GC"
    return 0
  fi
  if run_git -C "$M" reflog expire --expire=now --all && run_git -C "$M" gc --prune=now; then
    STEP_GC="done"
  else
    STEP_GC="FAILED"
    APPLY_FAILS=$((APPLY_FAILS + 1))
  fi
}
apply_stage() {
  if [ ! -d "$DIR_C" ]; then die 4 "no archive dir $DIR_C: run --archive first (nothing changed)"; fi
  start_work
  if ! load_manifest; then die 4 "no MANIFEST.tsv in $DIR_C: run --archive first (nothing changed)"; fi
  say ""
  say "== Stage 2: apply, archive $DIR_C =="
  say "-- verifying the archive (manifest sha256, every file's size and sha256, every bundle)"
  if ! verify_archive; then die 4 "archive verification failed: nothing was changed"; fi
  say "  ok: ${#MF_KIND[@]} row(s) verified"
  apply_worktrees
  apply_prune
  apply_branches
  apply_clean
  apply_gc
}

# ---------------------------------------------------------------- dry run: the plan
print_plan() {
  local i r c d st msg why cnt list
  say ""
  say "== Stage 1 plan: --archive $(disp "$DIR_C") (<RUN> = run timestamp; umask 077) =="
  if [ -d "$DIR_C" ] && [ -n "$(ls -A -- "$DIR_C" 2>/dev/null)" ]; then
    say "  DIR exists and is not empty: --archive needs --resume (rows that still verify are kept)"
  elif [ -d "$DIR_C" ]; then say "  DIR exists and is empty"; else say "  DIR does not exist yet"; fi
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 0 ] && is_under "$DIR_C" "${WT_CANON[i]}"; then
      say "  ! DIR lies inside worktree $(disp "${WT_CANON[i]}"): --archive will refuse"
    fi
  done
  cmdline mkdir -p -m 700 "$DIR_C"
  cmdline git -C "$M" bundle create -q "$DIR_C/bundles/main.<RUN>.bundle" "refs/heads/$MAIN"
  for ((i = 0; i < NBR; i++)); do
    if [ "${BR_NAME[i]}" = "$MAIN" ] || [ "${BR_UNIQ[i]}" = 0 ]; then continue; fi
    printf '%s    # %s commit(s)\n' "$(cmdline git -C "$M" bundle create -q "$DIR_C/bundles/br-$(safe_name "${BR_NAME[i]}")-<h6>.<RUN>.bundle" "refs/heads/${BR_NAME[i]}" "^refs/heads/$MAIN")" "${BR_UNIQ[i]}"
  done
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ] || [ "${WT_BRANCH[i]}" != - ] || [ "${WT_UNIQ[i]}" = 0 ]; then continue; fi
    printf '%s    # detached, %s commit(s)\n' "$(cmdline git -C "${WT_CANON[i]}" bundle create -q "$DIR_C/bundles/head-${WT_ID[i]}.<RUN>.bundle" HEAD "^refs/heads/$MAIN")" "${WT_UNIQ[i]}"
  done
  if list=$(reflog_only_commits); then cnt=$(count_lines "$list"); else cnt="? (git fsck failed)"; fi
  printf '  $ git -C %s fsck --unreachable --no-reflogs | <commit ids> | git -C %s pack-objects -q --revs %s    # %s commit(s)\n' \
    "$(q "$M")" "$(q "$M")" "$(q "$DIR_C/packs/reflog-only.<RUN>")" "$cnt"
  for ((i = 0; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ]; then continue; fi
    c=${WT_CANON[i]} d="$DIR_C/worktrees/${WT_ID[i]}.<RUN>"
    msg=""
    if [ "$SIZES" = 1 ]; then
      r=0
      list=$(root_files "$c") || r=$?
      if [ "$r" != 0 ]; then msg="    # cannot list: $(list_why "$r"); --archive fails this item"
      elif [ -z "$list" ]; then msg="    # 0 file(s)"
      else msg="    # $(printf '%s\n' "$list" | coverage_of_list "$c" | list_stats)"; fi
    fi
    say "  # $(disp "$c") [${WT_CLASS[i]}]"
    printf '  $ git -C %s status --porcelain=v1 --untracked-files=normal > %s\n' "$(q "$c")" "$(q "$d.status")"
    printf '  $ { HEAD; git -C %s status --porcelain=v1 --untracked-files=no; git -C %s diff --binary HEAD; } > %s\n' "$(q "$c")" "$(q "$c")" "$(q "$d.diff")"
    printf '  $ <untracked+ignored files of %s, minus nested worktrees and caches> | tar -czf %s -C %s -n --null -T -%s\n' "$(disp "$c")" "$(q "$d.data.tar.gz")" "$(q "$c")" "$msg"
  done
  for ((i = 0; i < ${#IT_NAME[@]}; i++)); do
    if [ ! -e "${IT_PATH[i]}" ]; then say "  # item ${IT_NAME[i]}: absent ($(disp "${IT_PATH[i]}"))"; continue; fi
    msg=""
    if [ "${IT_SECRET[i]}" = 1 ]; then msg=" [secret: tarball mode 0600]"; fi
    if [ "$SIZES" = 1 ]; then
      if ! list=$(item_files "$i"); then msg="$msg cannot list it: --archive will report it"
      elif [ -z "$list" ]; then msg="$msg 0 file(s)"
      else msg="$msg $(printf '%s\n' "$list" | coverage_of_list "$(dirname -- "${IT_PATH[i]}")" | list_stats)"; fi
    fi
    printf '  $ <files of %s> | tar -czf %s -C %s -n --null -T -    #%s\n' "$(disp "${IT_PATH[i]}")" \
      "$(q "$DIR_C/data/${IT_NAME[i]}.<RUN>.tar.gz")" "$(q "$(dirname -- "${IT_PATH[i]}")")" "$msg"
  done
  printf '  $ (cd %s && shasum -a 256 MANIFEST.tsv > MANIFEST.tsv.sha256)\n' "$(q "$DIR_C")"
  say "  then: verify every row's sha256 and size, git bundle verify every bundle"

  say ""
  say "== Stage 2 plan: --apply $(disp "$DIR_C") (each removal first re-checks liveness and the archive) =="
  for i in $(removal_order); do
    if [ "${WT_CLASS[i]}" = DIRTY ]; then
      printf '%s    # DIRTY: %s\n' "$(cmdline git -C "$M" worktree remove --force "${WT_PATH[i]}")" "${WT_REASON[i]}"
    else
      printf '%s    # CLEAN\n' "$(cmdline git -C "$M" worktree remove "${WT_PATH[i]}")"
    fi
  done
  for ((i = 1; i < NWT; i++)); do
    if [ "${WT_PRUNABLE[i]}" = 1 ]; then cmdline git -C "$M" worktree prune -v; break; fi
  done
  for ((i = 0; i < NBR; i++)); do
    case ${BR_CLASS[i]} in
      MERGED) cmdline git -C "$M" branch -d "${BR_NAME[i]}" ;;
      UNIQUE) printf '%s    # only once its bundle verifies\n' "$(cmdline git -C "$M" branch -D "${BR_NAME[i]}")" ;;
    esac
  done
  if [ "$CLEAN" = 1 ]; then
    if st=$(git -C "$M" clean -ndx 2>&1); then
      cnt=$(count_lines "$st")
      say "  git clean -ndx in M now lists $cnt line(s) (the first 15; it is shown in full before -fdx):"
      printf '%s\n' "$st" | sed -n '1,15s/^/      /p'
    fi
    cmdline git -C "$M" clean -ndx
    cmdline git -C "$M" clean -fdx
    why=$(m_live_why)
    if [ -n "$why" ]; then say "  (would be skipped now: $why)"; fi
    STEP_CLEAN="planned (--clean)"
  else
    say "  git clean -fdx in M: not planned (needs --clean)"
    STEP_CLEAN="not requested (--clean)"
  fi
  if [ "$GC" = 1 ]; then
    cmdline git -C "$M" reflog expire --expire=now --all
    cmdline git -C "$M" gc --prune=now
    why=""
    for ((i = 1; i < NWT; i++)); do
      case ${WT_CLASS[i]} in LOCKED | LIVE | SESSION | IN-PROGRESS | ERROR) why="$why $(disp "${WT_CANON[i]}")(${WT_CLASS[i]})" ;; esac
    done
    if [ -n "$why" ]; then say "  (gc would be refused now: live or locked worktrees:$why)"; fi
    if git -C "$M" rev-parse -q --verify refs/stash >/dev/null; then say "  (gc would be refused now: refs/stash exists)"; fi
    STEP_GC="planned (--gc)"
  else
    say "  reflog expire + gc: not planned (needs --gc)"
    STEP_GC="not requested (--gc)"
  fi
  STEP_PRUNE="planned if any entry is prunable"
}

# ---------------------------------------------------------------- summary
print_summary() {
  local i w1=4 w2=5 w3=6 name
  for ((i = 0; i < NWT; i++)); do
    name=$(disp "${WT_CANON[i]}")
    if [ "${#name}" -gt "$w1" ]; then w1=${#name}; fi
    if [ "${#WT_CLASS[i]}" -gt "$w2" ]; then w2=${#WT_CLASS[i]}; fi
    if [ "${#WT_ACTION[i]}" -gt "$w3" ]; then w3=${#WT_ACTION[i]}; fi
  done
  for ((i = 0; i < NBR; i++)); do
    if [ "${#BR_NAME[i]}" -gt "$w1" ]; then w1=${#BR_NAME[i]}; fi
    if [ "${#BR_ACTION[i]}" -gt "$w3" ]; then w3=${#BR_ACTION[i]}; fi
  done
  say ""
  case $MODE in
    dry) say "== Summary (dry run: ACTION is the plan) ==" ;;
    archive) say "== Summary (archive: ACTION is what --apply would do) ==" ;;
    apply) say "== Summary (apply: ACTION is what was done) ==" ;;
  esac
  printf '%-8s  %-*s  %-*s  %-*s  %s\n' KIND "$w1" NAME "$w2" CLASS "$w3" ACTION REASON
  for ((i = 0; i < NWT; i++)); do
    printf '%-8s  %-*s  %-*s  %-*s  %s\n' worktree "$w1" "$(disp "${WT_CANON[i]}")" "$w2" "${WT_CLASS[i]}" "$w3" "${WT_ACTION[i]}" "${WT_REASON[i]}; $(head_info "$i")"
  done
  for ((i = 0; i < NBR; i++)); do
    printf '%-8s  %-*s  %-*s  %-*s  %s\n' branch "$w1" "${BR_NAME[i]}" "$w2" "${BR_CLASS[i]}" "$w3" "${BR_ACTION[i]}" "${BR_REASON[i]}"
  done
  printf '%-8s  %-*s  %-*s  %-*s  %s\n' step "$w1" prune "$w2" - "$w3" - "$STEP_PRUNE"
  printf '%-8s  %-*s  %-*s  %-*s  %s\n' step "$w1" clean "$w2" - "$w3" - "$STEP_CLEAN"
  printf '%-8s  %-*s  %-*s  %-*s  %s\n' step "$w1" gc "$w2" - "$w3" - "$STEP_GC"
}
remaining_count() { # worktrees (not M, not the caller's) and branches (not main) still present after --apply
  local i n=0
  for ((i = 1; i < NWT; i++)); do
    case ${WT_ACTION[i]} in removed | prune) ;; *) if [ "${WT_CLASS[i]}" != CALLER ]; then n=$((n + 1)); fi ;; esac
  done
  for ((i = 0; i < NBR; i++)); do
    case ${BR_ACTION[i]} in keep | 'deleted (-d)' | 'deleted (-D)' | gone) ;; *) n=$((n + 1)) ;; esac
  done
  printf '%s' "$n"
}

# ---------------------------------------------------------------- main
classify_worktrees
classify_branches
build_items

say "RESET_TO_MAIN ($MODE) $(date '+%Y-%m-%d %H:%M:%S')"
say "  repository M:   $M (git dir $COMMON)"
say "  keep branch:    $MAIN @ ${MAIN_SHA:0:12}"
if [ "$CALLER_IDX" -ge 0 ]; then say "  caller in:      $(disp "${WT_CANON[CALLER_IDX]}")"; else say "  caller in:      $CWD (outside every worktree)"; fi
say "  processed last: $(disp "$LAST_C")"
say "  archive DIR:    $DIR_C"
say "  live window:    $LIVE_MIN min; sessions: ${#SESS_C[@]}"
say "  worktrees:      $NWT (M included); branches: $NBR"
others=$(git -C "$M" for-each-ref --format='%(refname)' | { grep -v '^refs/heads/' || true; } | tr '\n' ' ')
say "  other refs:     ${others:-none} (never touched)"
if git -C "$M" rev-parse -q --verify refs/stash >/dev/null; then
  say "  stash:          $(git -C "$M" log -g --format=%H refs/stash | wc -l | tr -d ' ') entr(ies): --gc refuses while it exists"
else
  say "  stash:          none"
fi
if [ -n "$(git -C "$M" ls-tree --name-only "$MAIN_SHA" -- claude_info)" ]; then
  warn "claude_info/ is still tracked on $MAIN: HANDOFF §4 item 10 says git rm -r claude_info/ (a user step; not done here)"
else
  say "  claude_info/:   not tracked on $MAIN (ok; the §4 'git rm -r claude_info/' step is obsolete)"
fi

rc=0
case $MODE in
  dry)
    print_plan ;;
  archive)
    archive_stage
    STEP_PRUNE="stage 2" STEP_CLEAN="stage 2" STEP_GC="stage 2"
    if [ "$ITEM_FAILS" -gt 0 ]; then rc=6; fi ;;
  apply)
    apply_stage
    if [ "$APPLY_FAILS" -gt 0 ]; then rc=6
    elif [ "$(remaining_count)" -gt 0 ]; then rc=5; fi ;;
esac
print_summary
case $MODE in
  dry) say ""; say "Dry run: nothing was written. Next: --archive [DIR], then --apply [DIR]." ;;
  archive)
    say ""
    if [ "$rc" = 0 ]; then say "Archive complete and verified: $DIR_C. Next: --apply $DIR_C"
    else say "Archive written with $ITEM_FAILS failed item(s) (above); the manifest covers the rest. Re-run with --resume."; fi ;;
  apply)
    say ""
    say "Apply finished: $APPLY_FAILS failure(s); $(remaining_count) worktree(s)/branch(es) other than M, $MAIN and the caller's remain." ;;
esac
exit "$rc"
