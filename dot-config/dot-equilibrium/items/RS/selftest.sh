#!/usr/bin/env bash
# RS self-test: oracle on the 3 dev items (reference must score 1, seeded wrong answers 0), stub grades written
# deterministically from the rid of each grader input, blinding and malformed-input checks, pool audit.
set -u
cd "$(dirname "$0")"
T="$(mktemp -d "${TMPDIR:-/tmp}/rs-selftest.XXXXXX")"
trap 'rm -rf "$T"' EXIT
FAILS=0
O() { uv run --offline --quiet --script oracle.py "$@"; }
check() { # name expected actual
  if [ "$2" = "$3" ]; then echo "PASS $1"; else echo "FAIL $1 (expected $2, got $3)"; FAILS=$((FAILS+1)); fi
}
grade() { # item answer verdict -> prints score
  O --item "$1" --answer "$2" --grader-input "$T/g.json" >/dev/null
  jq -n --arg rid "$(jq -r .rid "$T/g.json")" --arg v "$3" '[{rid:$rid, verdict:$v, note:"stub"}]' > "$T/grades.json"
  O --item "$1" --answer "$2" --grade "$T/grades.json" | jq -r .score
}
for i in RS-DEV1 RS-DEV2 RS-DEV3; do
  check "$i reference + stub pass -> 1" 1 "$(grade $i selftest/$i.ref.json pass)"
  check "$i reference + stub fail -> 0" 0 "$(grade $i selftest/$i.ref.json fail)"
  check "$i seeded wrong label + stub pass -> 0" 0 "$(grade $i selftest/$i.wrong.json pass)"
  check "$i seeded wrong label, mechanical -> 0" 0 "$(O --item $i --answer selftest/$i.wrong.json | jq -r .score)"
  if [ -f selftest/$i.wrongvalue.json ]; then
    check "$i right label, wrong correction value + stub pass -> 0" 0 "$(grade $i selftest/$i.wrongvalue.json pass)"
  fi
done
O --item RS-DEV1 --answer selftest/RS-DEV1.ref.json >/dev/null; check "reference without grade -> exit 3 (needs grade)" 3 $?
echo '{"answer": null}' > "$T/null.json"
check "missing answer -> 0" 0 "$(O --item RS-DEV1 --answer "$T/null.json" | jq -r .score)"
echo '{"answer": {"label": "MAYBE", "value": "", "rationale": ""}}' > "$T/inv.json"
check "schema-invalid answer -> 0" 0 "$(O --item RS-DEV1 --answer "$T/inv.json" | jq -r .score)"
echo 'not json' > "$T/bad.json"
O --item RS-DEV1 --answer "$T/bad.json" >/dev/null; check "malformed answer file -> exit 2" 2 $?
O --item RS-9999 --answer selftest/RS-DEV1.ref.json >/dev/null; check "unknown item -> exit 2" 2 $?
# blinding: arm, member and head tokens in the answer are redacted from the grader input
jq '.answer.rationale = "RS-DEV1 p3 m2/5 As member 3 of q1 (and S*) I checked session 0f8fad5b-d9cb-469f-a165-70867728950e. " + .answer.rationale' \
  selftest/RS-DEV1.ref.json > "$T/leak.json"
O --item RS-DEV1 --answer "$T/leak.json" --grader-input "$T/gl.json" >/dev/null
O --check-blind "$T/gl.json" >/dev/null; check "leaky answer -> grader input passes blind check" 0 $?
check "leaky answer -> redactions counted" yes "$(O --item RS-DEV1 --answer "$T/leak.json" --grader-input "$T/gl.json" | jq -r 'if .detail.redactions >= 5 then "yes" else "no" end')"
echo '{"answer": {"rationale": "chosen by p3"}}' > "$T/raw.json"
O --check-blind "$T/raw.json" >/dev/null; check "blind check detects an arm token -> exit 2" 2 $?
# determinism of the grader input
O --item RS-DEV2 --answer selftest/RS-DEV2.ref.json --grader-input "$T/d1.json" >/dev/null
O --item RS-DEV2 --answer selftest/RS-DEV2.ref.json --grader-input "$T/d2.json" >/dev/null
cmp -s "$T/d1.json" "$T/d2.json"; check "grader input is deterministic" 0 $?
O --audit >/dev/null; check "pool audit (ids, segments, decisive index, keys discriminate, blinding of all items)" 0 $?
[ "$FAILS" -eq 0 ] && echo "ALL PASS" || echo "$FAILS FAIL"
exit "$FAILS"
