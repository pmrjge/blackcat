#!/bin/bash
# eq_check.sh: pre-item checks of the agent-equilibrium experiment (COMPARE_eq.md §5 step 3, E1-E11).
# Run by `eq_harness.py run` before every item (or by hand):
#     bash eq_check.sh <ITEM> [<stage: p|q|d>]          (stage defaults to p)
# Exit 0 = the item may start. Exit 1 = do not start it. Exit 2 = usage.
# Every call appends one line to $EQ/runs/<stage>/DISPATCH_LOG.tsv (PASS or FAIL): the audit trail.
# Read-only except that log. Never calls the API (`claude --version` only).
# Env overrides (tests and the dry run only): EQ_M (main checkout), EQ_ROOT (the frozen package), EQ_HOME (home whose
# .claude/ and .local/state/ are read). `claude` and `pgrep` are taken from PATH.
set -u

M=${EQ_M:-$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null || { cd "$(dirname "$0")/../.." && pwd; })}
W=$M/claude_next_steps/work_carried
EQ=${EQ_ROOT:-$W/equilibrium}
H=${EQ_HOME:-$HOME}
MAN="$H/.claude/.stack-manifest.json"
STATE="$H/.local/state/claude-agent-stack"
ACTIVE_S=900

ITEM="${1:-}"; STAGE="${2:-p}"
if [ -z "$ITEM" ]; then echo "usage: bash eq_check.sh <ITEM> [<stage>]" >&2; exit 2; fi
case "$ITEM" in [A-Z][A-Z]-[A-Z0-9]*) ;; *) echo "bad item id: $ITEM" >&2; exit 2 ;; esac
case "$ITEM" in *[!A-Z0-9-]*) echo "bad item id: $ITEM" >&2; exit 2 ;; esac
case "$STAGE" in p|q|d) ;; *) echo "bad stage: $STAGE" >&2; exit 2 ;; esac
for t in jq shasum awk; do
  command -v "$t" >/dev/null 2>&1 || { echo "FAIL missing command: $t" >&2; exit 1; }
done
RUNS="$EQ/runs/$STAGE"
mkdir -p "$RUNS" || exit 1
LOG="$RUNS/DISPATCH_LOG.tsv"
LEDGER="$RUNS/ledger.jsonl"
CONFIG="$RUNS/CONFIG.txt"
SCHED="$EQ/schedule.tsv"
[ -f "$LOG" ] || printf 'utc\titem\tverdict\tstack_commit\tclaude_version\tfailed_checks\n' > "$LOG"

fails=""
ok()  { printf 'PASS %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1"; fails="$fails $2"; }
sha() { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }
cfg() { [ -f "$CONFIG" ] && sed -n "s/^$1: //p" "$CONFIG" | head -1; }

have_cfg=0; [ -f "$CONFIG" ] && have_cfg=1
[ "$have_cfg" = 1 ] || bad "E0 $CONFIG missing: record the configuration first (COMPARE_eq §5 step 2)" E0

# E1-E3 installed stack = the pin recorded in CONFIG.txt (drift check)
commit="$(jq -r .commit "$MAN" 2>/dev/null)"
pin="$(cfg stack_commit)"
if [ -n "$pin" ] && [ "$commit" = "$pin" ]; then ok "E1 manifest commit $commit"
else bad "E1 manifest commit '${commit}' != CONFIG.txt '${pin}'" E1; fi
dig="$(jq -cS .files "$MAN" 2>/dev/null | shasum -a 256 | awk '{print $1}')"
pdig="$(cfg manifest_files_digest)"
if [ -n "$pdig" ] && [ "$dig" = "$pdig" ]; then ok "E2 manifest files digest"
else bad "E2 manifest files digest $dig != CONFIG.txt '${pdig}'" E2; fi
if [ -f "$MAN" ]; then
  n_bad="$(jq -r '.files|to_entries[]|"\(.value)  \(.key)"' "$MAN" | (cd "$H/.claude" && shasum -a 256 -c 2>/dev/null) | grep -vc ': OK$')"
else n_bad="manifest missing"; fi
if [ "$n_bad" = 0 ]; then ok "E3 installed files match the manifest"; else bad "E3 installed files differ from the manifest ($n_bad)" E3; fi

# E4 the frozen package verifies
if [ -f "$EQ/COMPARE_eq.sha256" ] && (cd "$EQ" && grep -v '^#' COMPARE_eq.sha256 | shasum -a 256 -c --quiet >/dev/null 2>&1); then
  ok "E4 COMPARE_eq.sha256 verifies"
else bad "E4 sidecar missing or mismatched ($EQ/COMPARE_eq.sha256)" E4; fi

# E5 c0 collected
C0="$W/context-diet/arms/c0/inputs"
if [ -f "$C0/FROZEN_AT.txt" ] && [ -f "$C0/MANIFEST.sha256" ]; then ok "E5 c0 collected"
else bad "E5 c0 not collected ($C0/FROZEN_AT.txt or MANIFEST.sha256 missing)" E5; fi

# E6 no open measurement arm: every arms/*/DISPATCH_LOG.tsv with a PASS line has inputs/FROZEN_AT.txt beside it
open_arms=""
for lg in "$W"/*/arms/*/DISPATCH_LOG.tsv; do
  [ -f "$lg" ] || continue
  if awk -F'\t' '$3=="PASS"{f=1} END{exit !f}' "$lg" && [ ! -f "$(dirname "$lg")/inputs/FROZEN_AT.txt" ]; then
    open_arms="$open_arms ${lg#"$W"/}"
  fi
done
if [ -z "$open_arms" ]; then ok "E6 no open measurement arm"; else bad "E6 open arm(s):$open_arms" E6; fi

# E7 the item is the next one in schedule.tsv, or a re-check of the last PASS whose calls have not started
if [ ! -f "$SCHED" ]; then bad "E7 $SCHED missing" E7
else
  items="$(awk -F'\t' 'NR>1 && !seen[$3]++ {print $3}' "$SCHED")"
  expected=""
  for it in $items; do
    if ! awk -F'\t' -v p="$it" '$2==p && $3=="PASS"{f=1} END{exit !f}' "$LOG"; then expected="$it"; break; fi
  done
  last_pass="$(awk -F'\t' '$3=="PASS"{p=$2} END{print p}' "$LOG")"
  started=0
  if [ -f "$LEDGER" ] && jq -e --arg i "$ITEM" 'select(.record=="call" and .item==$i)' "$LEDGER" >/dev/null 2>&1; then started=1; fi
  if ! printf '%s\n' "$items" | grep -qx "$ITEM"; then bad "E7 $ITEM is not in $SCHED" E7
  elif [ "$ITEM" = "$expected" ]; then ok "E7 $ITEM is next in schedule.tsv"
  elif [ "$ITEM" = "$last_pass" ] && [ "$started" = 0 ]; then ok "E7 re-check of $ITEM (last PASS, no call started)"
  else bad "E7 expected ${expected:-none (all done)}, got $ITEM" E7; fi
fi

# E8 Claude Code version, E9 stack.env, both against CONFIG.txt
ver="$(claude --version 2>/dev/null | head -1)"
cver="$(cfg claude_version)"
if [ -n "$cver" ] && [ "$ver" = "$cver" ]; then ok "E8 claude version $ver"
else bad "E8 claude version '$ver' != CONFIG.txt '$cver'" E8; fi
henv="$(sha "$H/.claude/stack.env")"; cenv="$(cfg stack_env_sha256)"
if [ -n "$henv" ] && [ "$henv" = "$cenv" ]; then ok "E9 stack.env unchanged"
else bad "E9 stack.env hash '${henv}' != CONFIG.txt '${cenv}'" E9; fi

# E10 no other session active in the last 900 s (runs3.csv, c0 C9 rule; this stage's ledger sessions excepted),
# and no running `claude` process (the harness has no child running between items)
mine=""
[ -f "$LEDGER" ] && mine="$(jq -r 'select(.record=="call") | .session_id // empty' "$LEDGER" 2>/dev/null | sort -u | tr '\n' ' ')"
now="$(date +%s)"
others="$(awk -F, -v now="$now" -v win="$ACTIVE_S" -v mine=" $mine " \
  'NR>1 && $19+0 > now-win && index(mine, " " $2 " ") == 0 {print substr($2,1,8)}' "$STATE/usage/runs3.csv" 2>/dev/null | sort -u | tr '\n' ' ')"
nproc="$(pgrep -x claude 2>/dev/null | grep -c . || true)"
if [ -z "$others" ] && [ "${nproc:-0}" = 0 ]; then ok "E10 no concurrent session or claude process"
else bad "E10 concurrent: sessions [${others}] claude processes [${nproc}]" E10; fi

# E11 spend: ledger Σ total_cost_usd + 4B <= the consented ceiling
cls="${ITEM%%-*}"
b="$(cfg "B_usd_$cls")"; ceil="$(cfg spend_ceiling_usd)"
spent=0
[ -f "$LEDGER" ] && spent="$(jq -s '[.[] | select(.record=="call") | (.total_cost_usd // 0)] | add // 0' "$LEDGER" 2>/dev/null || echo NaN)"
if [ -n "$b" ] && [ -n "$ceil" ] && awk -v s="$spent" -v b="$b" -v c="$ceil" 'BEGIN{exit !(s ~ /^[0-9.eE+-]+$/ && s + 4*b <= c)}'; then
  ok "E11 spend $spent + 4 x $b <= $ceil"
else bad "E11 spend $spent + 4 x '${b}' > ceiling '${ceil}' (or a value missing)" E11; fi

# E12 ledger integrity (when the stage ledger exists): every line is one JSON object whose seq is its line number, and
# the file ends with a newline. A torn last line or a deleted/reordered middle line fails here, not only through a later
# jq error; a clean truncation at a line boundary (whole last lines removed) is NOT caught (seq stays 1..n).
if [ ! -s "$LEDGER" ]; then ok "E12 no ledger yet"
else
  lerr=""
  [ "$(tail -c 1 "$LEDGER" | od -An -tx1 | tr -d ' \n')" = 0a ] || lerr="no final newline (torn or truncated last line)"
  if [ -z "$lerr" ]; then
    lerr="$(jq -nRr '[inputs] | to_entries | map(. as $e | ($e.value | try fromjson catch null) as $o
      | select(($o | type) != "object" or $o.seq != $e.key + 1))
      | if length == 0 then "" else "line \(.[0].key + 1): not one JSON object with seq = its line number (\(length) such line(s))" end' \
      "$LEDGER" 2>&1)" || lerr="jq failed: ${lerr:-?}"
  fi
  if [ -z "$lerr" ]; then ok "E12 ledger intact ($(awk 'END{print NR}' "$LEDGER") lines, seq 1..n)"
  else bad "E12 ledger $LEDGER: $lerr" E12; fi
fi

verdict=PASS; [ -n "$fails" ] && verdict=FAIL
printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u '+%FT%TZ')" "$ITEM" "$verdict" "${commit:0:7}" "$ver" "${fails# }" >> "$LOG"
if [ "$verdict" = FAIL ]; then echo "VERDICT: FAIL ($fails ). Do not start $ITEM (COMPARE_eq §10)."; exit 1; fi
echo "VERDICT: PASS $ITEM"
exit 0
