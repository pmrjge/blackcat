#!/bin/bash
# CR selftest: on every dev item the reference finding set must score recall 1 / score 1.0 (provisional and graded
# path) and a seeded wrong answer (right file, wrong lines) must score <= 0. Exits non-zero on any FAIL.
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE" || exit 1
T=$(mktemp -d "${TMPDIR:-/tmp}/cr_selftest.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
fail=0
NONCE=00112233445566778899aabbccddeeff
# the oracle reads the nonce on stdin and prints `EQV1 <nonce> <json>`; keep only the authenticated JSON
oracle() { printf '%s\n' "$NONCE" | uv run oracle.py "$@" | sed -n "s/^EQV1 $NONCE //p"; }
field() { uv run --no-project python -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$1"; }
chk() { # label value expected-test(python expr on v)
  if uv run --no-project python -c 'import sys; v=float(sys.argv[1]); sys.exit(0 if eval(sys.argv[2]) else 1)' "$2" "$3"; then
    echo "PASS $1 (score $2)"
  else
    echo "FAIL $1 (score $2, wanted $3)"; fail=1
  fi
}
ids=$(uv run --no-project python -c 'import json; print(*sorted(k for k in json.load(open("oracle/items.json")) if "DEV" in k))')
for id in $ids; do
  uv run --no-project python -c '
import json, sys
sys.path.insert(0, "oracle")
import refs
i, d = sys.argv[1:3]
good = refs.reference_findings(i)
refs.write_answer(d + "/good.json", good)
refs.write_answer(d + "/wrong.json", [dict(f, line=f["line"] + 500) for f in good])
refs.write_answer(d + "/empty.json", [])
' "$id" "$T"
  s=$(oracle --item "$id" --answer "$T/good.json" | field score)
  chk "$id reference findings, provisional" "$s" "v == 1.0"
  oracle --item "$id" --answer "$T/good.json" --grader-input "$T/gin.json" >/dev/null
  uv run --no-project python -c '
import json, sys
g = json.load(open(sys.argv[1]))
json.dump([{"rid": f["rid"], "verdict": "true", "note": ""} for f in g], open(sys.argv[2], "w"))
' "$T/gin.json" "$T/grade_true.json"
  s=$(oracle --item "$id" --answer "$T/good.json" --grade "$T/grade_true.json" | field score)
  chk "$id reference findings, graded true" "$s" "v == 1.0"
  s=$(oracle --item "$id" --answer "$T/wrong.json" | field score)
  chk "$id wrong lines, provisional" "$s" "v < 0"
  uv run --no-project python -c '
import json, sys
a = json.load(open(sys.argv[1]))["answer"]
json.dump([{"rid": "f%d" % i, "verdict": "false", "note": ""} for i in range(len(a))], open(sys.argv[2], "w"))
' "$T/wrong.json" "$T/grade_false.json"
  s=$(oracle --item "$id" --answer "$T/wrong.json" --grade "$T/grade_false.json" | field score)
  chk "$id wrong lines, graded false" "$s" "v < 0"
  s=$(oracle --item "$id" --answer "$T/empty.json" | field score)
  chk "$id empty finding set" "$s" "v == 0.0"
done
exit $fail
