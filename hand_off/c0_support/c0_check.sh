#!/bin/bash
# c0_check.sh: the pre-dispatch check of the c0 arm (COMPARE_c0.md §5). Read-only except the arm log.
# Run it in a SEPARATE terminal (never with `!` inside the arm session: its output would enter BlackCat's
# context) before every c0 dispatch:
#     bash c0_check.sh <PID> [<arm session uuid>]
# Exit 0 = dispatch allowed (prints the exact message to send). Exit 1 = do not dispatch.
# Every call appends one line to arms/c0/DISPATCH_LOG.tsv (PASS or FAIL), which is the audit trail.
# Env: C0_ORDER_OVERRIDE=1 skips the order check (only after an amendment in COMPARE_c0.md §12; logged).
set -u

M=/Users/pmrj/ZDone/claude-agent-stack
W=$M/claude_next_steps/work_carried
CD=$W/context-diet
A=$CD/arms/c0
MAN="$HOME/.claude/.stack-manifest.json"
STATE="$HOME/.local/state/claude-agent-stack"

PIN_COMMIT=a22c5b4e5aa67d5d3c6bea977eda2de1800bfd5f
PIN_FILES_DIGEST=b6f957f39fee1b5579eac3b77308e6d04695c86372425efb77981038d4bfc886   # sha256 of `jq -cS .files` (485 files)
PIN_PROMPTS=2d8bb00aa4e67d4654d18c0aea8f88c319e947c375385495698b9ac038ee364e        # stats_before/inputs/baseline/prompts.csv
PIN_COLLECTOR=71710cf73f40c30e4e880cc30824db7820b0a95eb67444bbb197e17f22946689      # stats_before/tools/collect_b0v2.py
PIN_EXTRACT=847b8bfff5a7d70f0241436126f1b83e5204511ce130360465508efb903b38c4        # compact-protocol/measurement/extract_child_finals.py
ORDER="P90 P91 P92 P93 P96 P94 P99 P19 P04 P21 P07 P10 P41 P42 P11 P30 P44"
ACTIVE_S=900   # another session with a segment active in the last 15 min = a concurrent session

PID="${1:-}"; ARM_SID="${2:-}"
if [ -z "$PID" ]; then echo "usage: bash c0_check.sh <PID> [<arm session uuid>]" >&2; exit 2; fi
for t in jq shasum git awk claude uv; do
  command -v "$t" >/dev/null 2>&1 || { echo "FAIL missing command: $t" >&2; exit 1; }
done
mkdir -p "$A/messages" || exit 1
LOG="$A/DISPATCH_LOG.tsv"
[ -f "$LOG" ] || printf 'utc\tpid\tverdict\tmanifest_commit\tmain_head\tclaude_version\tfailed_checks\n' > "$LOG"

fails=""
ok()   { printf 'PASS %s\n' "$1"; }
bad()  { printf 'FAIL %s\n' "$1"; fails="$fails ${2:-$1}"; }
warn() { printf 'WARN %s\n' "$1"; }
sha()  { shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'; }

# C1 installed manifest commit
commit="$(jq -r .commit "$MAN" 2>/dev/null)"
if [ "$commit" = "$PIN_COMMIT" ]; then ok "C1 manifest commit $commit"; else bad "C1 manifest commit '$commit' != $PIN_COMMIT" C1; fi
# C2 manifest file set and hashes unchanged since pre-registration
dig="$(jq -cS .files "$MAN" 2>/dev/null | shasum -a 256 | awk '{print $1}')"
if [ "$dig" = "$PIN_FILES_DIGEST" ]; then ok "C2 manifest files digest"; else bad "C2 manifest files digest $dig" C2; fi
# C3 installed files still match the manifest (no hand edit, no partial install)
n_bad="$(jq -r '.files|to_entries[]|"\(.value)  \(.key)"' "$MAN" | (cd "$HOME/.claude" && shasum -a 256 -c 2>/dev/null) | grep -vc ': OK$')"
if [ "$n_bad" = 0 ]; then ok "C3 installed files match the manifest"; else bad "C3 $n_bad installed file(s) differ from the manifest" C3; fi
# C4 the pre-registration and this script are unchanged
if [ -f "$CD/COMPARE_c0.sha256" ] && (cd "$CD" && shasum -a 256 -c --quiet COMPARE_c0.sha256 >/dev/null 2>&1); then
  ok "C4 COMPARE_c0.md and c0_check.sh match COMPARE_c0.sha256"
else bad "C4 pre-registration sidecar missing or mismatched ($CD/COMPARE_c0.sha256)" C4; fi
# C5 frozen measurement inputs
[ "$(sha "$W/stats_before/inputs/baseline/prompts.csv")" = "$PIN_PROMPTS" ] && ok "C5a prompts.csv" || bad "C5a prompts.csv hash" C5a
[ "$(sha "$W/stats_before/tools/collect_b0v2.py")" = "$PIN_COLLECTOR" ] && ok "C5b collector" || bad "C5b collector hash" C5b
[ "$(sha "$W/compact-protocol/measurement/extract_child_finals.py")" = "$PIN_EXTRACT" ] && ok "C5c extract_child_finals" || bad "C5c extract_child_finals hash" C5c
# C6 the PID is pre-registered and is the next one in the fixed order
expected=""
for p in $ORDER; do
  if ! awk -F'\t' -v p="$p" '$2==p && $3=="PASS"{f=1} END{exit !f}' "$LOG"; then expected="$p"; break; fi
done
last_pass="$(awk -F'\t' '$3=="PASS"{p=$2} END{print p}' "$LOG")"
case " $ORDER " in *" $PID "*) inlist=1 ;; *) inlist=0 ;; esac
if [ "$inlist" = 0 ]; then bad "C6 $PID is not in the pre-registered set" C6
elif [ "$PID" = "$expected" ]; then ok "C6 $PID is next in order"
elif [ "$PID" = "$last_pass" ]; then ok "C6 re-check of $PID (the last PASS; dispatch it only if not yet sent)"
elif [ "${C0_ORDER_OVERRIDE:-0}" = 1 ]; then warn "C6 order override: expected ${expected:-none}, got $PID (needs an amendment in §12)"
else bad "C6 expected ${expected:-none (all done)}, got $PID" C6; fi
# C7/C8 Claude Code version and stack.env unchanged since the configuration was recorded (§5 step 2)
ver="$(claude --version 2>/dev/null | head -1)"
if [ -f "$A/CONFIG.txt" ]; then
  cver="$(sed -n 's/^claude_version: //p' "$A/CONFIG.txt")"
  [ "$ver" = "$cver" ] && ok "C7 claude version $ver" || bad "C7 claude version '$ver' != CONFIG.txt '$cver'" C7
  cenv="$(sed -n 's/^stack_env_sha256: //p' "$A/CONFIG.txt")"
  henv="$(sha "$HOME/.claude/stack.env")"
  if [ -z "$cenv" ] || [ -z "$henv" ]; then bad "C8 stack.env hash missing (CONFIG.txt '$cenv', now '$henv'; unreadable file?)" C8
  elif [ "$henv" = "$cenv" ]; then ok "C8 stack.env unchanged"
  else bad "C8 stack.env changed since CONFIG.txt" C8; fi
else bad "C7/C8 $A/CONFIG.txt missing: record the configuration first (COMPARE_c0.md §5 step 2)" C7; fi
# C9 no other session running agents (shared rate limits and hook state)
now="$(date +%s)"
others="$(awk -F, -v now="$now" -v win="$ACTIVE_S" -v me="$ARM_SID" \
  'NR>1 && $19+0 > now-win && $2 != me {print substr($2,1,8)}' "$STATE/usage/runs3.csv" 2>/dev/null | sort -u | tr '\n' ' ')"
if [ -z "$others" ]; then ok "C9 no other active session in the last ${ACTIVE_S}s"
elif [ -n "$ARM_SID" ]; then bad "C9 other active session(s): $others" C9
else warn "C9 sessions active in the last ${ACTIVE_S}s: $others (pass the arm session uuid to make this a hard check)"; fi

head="$(git -C "$M" rev-parse --short HEAD 2>/dev/null)"
verdict=PASS; [ -n "$fails" ] && verdict=FAIL
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$(date -u '+%FT%TZ')" "$PID" "$verdict" "${commit:0:7}" "$head" "$ver" "${fails# }" >> "$LOG"
if [ "$verdict" = FAIL ]; then echo "VERDICT: FAIL ($fails ). Do not dispatch $PID. See COMPARE_c0.md §7."; exit 1; fi

# The message to send, built from the frozen prompts.csv (prompt cell verbatim)
msg="$A/messages/$PID.txt"
uv run --no-project --quiet python - "$W/stats_before/inputs/baseline/prompts.csv" "$PID" > "$msg" <<'PY' || { echo "FAIL building the message"; exit 1; }
import csv, sys
path, pid = sys.argv[1], sys.argv[2]
row = next(r for r in csv.DictReader(open(path, newline="", encoding="utf-8")) if r["id"] == pid)
agent = row["target_agent"]
print(f'Measurement arm c0, prompt {pid}. Dispatch exactly one {agent} subagent with the Agent description '
      f'"{pid} c0 run {agent}". Forward the task below verbatim. Work directory: '
      f'/Users/pmrj/ZDone/claude-agent-stack/.claude-work/compact-ab/c0/{pid}/ (create it). Do none of the work '
      f'yourself, add no requirements, and relay its result when it finishes.')
print(f'TASK: {row["prompt"]}')
PY
echo "VERDICT: PASS. Send this message (also in $msg):"
echo "----"; cat "$msg"; echo "----"
command -v pbcopy >/dev/null 2>&1 && pbcopy < "$msg" && echo "(copied to the clipboard)"
exit 0
