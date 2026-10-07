#!/usr/bin/env bash
# Pairwise self-test (identical in DS and OE): on the 3 dev items, the reference answer must win against the seeded
# wrong answer under a deterministic stub grader that prefers the reference in both orders, lose when the pair is
# swapped, tie when the stub's orders disagree; invalid sides lose mechanically; blinding, malformed input,
# determinism and the pool audit are checked.
set -u
cd "$(dirname "$0")"
CLS="$(basename "$PWD")"
T="$(mktemp -d "${TMPDIR:-/tmp}/${CLS}-selftest.XXXXXX")"
trap 'rm -rf "$T"' EXIT
FAILS=0
O() { uv run --offline --quiet --script oracle.py "$@"; }
check() { if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (expected $2, got $3)"; FAILS=$((FAILS+1)); fi; }
pair() { jq -n --slurpfile a "$1" --slurpfile b "$2" '{first: $a[0], second: $b[0]}' > "$3"; }
# stub grader: prefer the response whose text equals the reference; "disagree" answers X twice; "equal" twice
stub() { # item pairfile mode -> score
  O --item "$1" --answer "$2" --grader-input "$T/g.json" >/dev/null
  jq --arg mode "$3" --slurpfile r "$4" '
    ($r[0].answer | gsub("\\s+$"; "")) as $ref |
    [ .[] | {rid, verdict: (if $mode == "prefer-ref" then (if .response_X == $ref then "X" else "Y" end)
                             elif $mode == "disagree" then "X" else "equal" end), note: "stub"} ]' "$T/g.json" > "$T/grades.json"
  O --item "$1" --answer "$2" --grade "$T/grades.json" | jq -r .score
}
for i in "$CLS-DEV1" "$CLS-DEV2" "$CLS-DEV3"; do
  R=selftest/$i.ref.json; W=selftest/$i.wrong.json
  pair $R $W "$T/rw.json"; pair $W $R "$T/wr.json"
  check "$i (reference, seeded wrong), stub prefers reference -> 1" 1 "$(stub $i "$T/rw.json" prefer-ref $R)"
  check "$i (seeded wrong, reference), stub prefers reference -> -1" -1 "$(stub $i "$T/wr.json" prefer-ref $R)"
  check "$i orders disagree (position-biased stub) -> 0" 0 "$(stub $i "$T/rw.json" disagree $R)"
  check "$i stub says equal -> 0" 0 "$(stub $i "$T/rw.json" equal $R)"
  echo '{"answer": "   "}' > "$T/empty.json"
  pair $R "$T/empty.json" "$T/re.json"
  check "$i (reference, empty answer) -> 1 without grading" 1 "$(O --item $i --answer "$T/re.json" | jq -r .score)"
  echo 'null' > "$T/null.json"
  pair "$T/null.json" $R "$T/nr.json"
  check "$i (missing, reference) -> -1 without grading" -1 "$(O --item $i --answer "$T/nr.json" | jq -r .score)"
  pair "$T/null.json" "$T/null.json" "$T/nn.json"
  check "$i (missing, missing) -> 0" 0 "$(O --item $i --answer "$T/nn.json" | jq -r .score)"
done
I="$CLS-DEV1"
pair selftest/$I.ref.json selftest/$I.wrong.json "$T/rw.json"
O --item $I --answer "$T/rw.json" >/dev/null; check "valid pair without grade -> exit 3 (needs grade)" 3 $?
check "grader input has 2 records, orders 1 and 2 swapped" "1 2 true" \
  "$(O --item $I --answer "$T/rw.json" --grader-input "$T/g.json" >/dev/null; jq -r '"\(.[0].order) \(.[1].order) \(.[0].response_X == .[1].response_Y and .[0].response_Y == .[1].response_X)"' "$T/g.json")"
jq '.answer = "'"$I"' p3 m2/5 As member 2 (arm q1, not S*), session 0f8fad5b-d9cb-469f-a165-70867728950e.\n\n" + .answer' selftest/$I.ref.json > "$T/leak.json"
pair "$T/leak.json" selftest/$I.wrong.json "$T/lw.json"
O --item $I --answer "$T/lw.json" --grader-input "$T/gl.json" >/dev/null
O --check-blind "$T/gl.json" >/dev/null; check "leaky answer -> grader input passes blind check" 0 $?
check "grader input has no first/second keys" 0 "$(jq "[.. | objects | keys[] | select(. == \"first\" or . == \"second\")] | length" "$T/gl.json")"
echo '[{"response_X": "selected by p3"}]' > "$T/raw.json"
O --check-blind "$T/raw.json" >/dev/null; check "blind check detects an arm token -> exit 2" 2 $?
echo 'not json' > "$T/bad.json"
O --item $I --answer "$T/bad.json" >/dev/null; check "malformed pair file -> exit 2" 2 $?
echo '{"first": null}' > "$T/half.json"
O --item $I --answer "$T/half.json" >/dev/null; check "pair file without 'second' -> exit 2" 2 $?
O --item "$CLS-9999" --answer "$T/rw.json" >/dev/null; check "unknown item -> exit 2" 2 $?
echo '[]' > "$T/nogr.json"
O --item $I --answer "$T/rw.json" --grade "$T/nogr.json" >/dev/null; check "grade file without these rids -> exit 2" 2 $?
O --item $I --answer "$T/rw.json" --grader-input "$T/d1.json" >/dev/null
O --item $I --answer "$T/rw.json" --grader-input "$T/d2.json" >/dev/null
cmp -s "$T/d1.json" "$T/d2.json"; check "grader input is deterministic" 0 $?
O --audit >/dev/null; check "pool audit (ids, criteria, segments, blinding of every item's grader input)" 0 $?
[ "$FAILS" -eq 0 ] && echo "ALL PASS" || echo "$FAILS FAIL"
exit "$FAILS"
