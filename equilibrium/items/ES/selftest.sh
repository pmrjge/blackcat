#!/usr/bin/env bash
# ES selftest: on every dev item the oracle must score a reference estimate (true x 1.05) as correct (e <= ln 1.1, the
# tie band) and seeded wrong estimates as wrong (true x 10 and true / 10: e >= ln 2; negative, zero, string and missing
# answers: e = inf), and must exit 2 on a malformed answer file. One PASS/FAIL line per check; exit 1 on any FAIL.
set -u
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/esself.XXXXXX") || exit 2
trap 'rm -rf "$tmp"' EXIT
fails=0

score_of() { uv run --quiet "$here/oracle.py" --item "$1" --answer "$2" 2>/dev/null | tail -n 1 | jq -r '.score'; }
verdict() { # label item score test(correct|wrong|inf)
  local ok=0
  case "$4" in
    correct) ok=$(jq -n --arg s "$3" '($s|tonumber? // 99) <= (1.1|log)') ;;
    wrong)   ok=$(jq -n --arg s "$3" '$s == "inf" or (($s|tonumber? // 0) >= (2|log))') ;;
    inf)     ok=$(jq -n --arg s "$3" '$s == "inf"') ;;
  esac
  if [ "$ok" = true ]; then echo "PASS $2 $1 (score $3)"; else echo "FAIL $2 $1 (expected $4, score $3)"; fails=$((fails + 1)); fi
}

for item in $(jq -r 'select(.dev) | .id' "$here/manifest.jsonl"); do
  t=$(jq -r --arg i "$item" 'select(.id == $i) | .true_value' "$here/oracle/truth.jsonl")
  d="$tmp/$item"; mkdir -p "$d"
  jq -n --argjson t "$t" '{answer: ($t * 1.05), evidence: [], confidence: 0.5}' > "$d/ref.json"
  verdict reference_x1.05 "$item" "$(score_of "$item" "$d/ref.json")" correct
  jq -n --argjson t "$t" '{answer: ($t * 10), evidence: [], confidence: 0.5}' > "$d/x10.json"
  verdict wrong_x10 "$item" "$(score_of "$item" "$d/x10.json")" wrong
  jq -n --argjson t "$t" '{answer: ($t / 10), evidence: [], confidence: 0.5}' > "$d/d10.json"
  verdict wrong_div10 "$item" "$(score_of "$item" "$d/d10.json")" wrong
  printf '{"answer": -5, "evidence": [], "confidence": 0.5}' > "$d/neg.json"
  verdict negative "$item" "$(score_of "$item" "$d/neg.json")" inf
  printf '{"answer": 0, "evidence": [], "confidence": 0.5}' > "$d/zero.json"
  verdict zero "$item" "$(score_of "$item" "$d/zero.json")" inf
  printf '{"answer": "about 1000", "evidence": [], "confidence": 0.5}' > "$d/str.json"
  verdict string_answer "$item" "$(score_of "$item" "$d/str.json")" inf
  printf '{"evidence": [], "confidence": 0.5}' > "$d/missing.json"
  verdict missing_answer "$item" "$(score_of "$item" "$d/missing.json")" inf
  printf 'not json' > "$d/bad.json"
  uv run --quiet "$here/oracle.py" --item "$item" --answer "$d/bad.json" > /dev/null 2>&1; rc=$?
  if [ "$rc" = 2 ]; then echo "PASS $item malformed_input (exit 2)"; else echo "FAIL $item malformed_input (exit $rc)"; fails=$((fails + 1)); fi
done
[ "$fails" -eq 0 ] || exit 1
exit 0
