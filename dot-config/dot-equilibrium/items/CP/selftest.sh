#!/bin/bash
# CP selftest: on every dev item the reference fix must score 1 and the seeded fixture 0.
# Prints one PASS/FAIL line per check; exits non-zero on any FAIL.
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE" || exit 1
T=$(mktemp -d "${TMPDIR:-/tmp}/cp_selftest.XXXXXX") || exit 1
trap 'rm -rf "$T"' EXIT
fail=0
NONCE=00112233445566778899aabbccddeeff  # the oracle reads it on stdin and prints `EQV1 <nonce> <json>`
score() { # item answer workdir -> score text
  printf '%s\n' "$NONCE" | uv run oracle.py --item "$1" --answer "$2" --workdir "$3" | sed -n "s/^EQV1 $NONCE //p" | uv run --no-project python -c 'import json,sys; print(json.load(sys.stdin)["score"])'
}
ids=$(uv run --no-project python -c 'import json; print(*sorted(k for k in json.load(open("oracle/items.json")) if "DEV" in k))')
for id in $ids; do
  uv run --no-project python -c '
import sys
sys.path.insert(0, "oracle")
import refs
i, ref, seed, ans = sys.argv[1:5]
refs.reference_workdir(i, ref); refs.seeded_workdir(i, seed); refs.answer_json(ans)
' "$id" "$T/ref_$id" "$T/seed_$id" "$T/ans_$id.json"
  r=$(score "$id" "$T/ans_$id.json" "$T/ref_$id")
  if [ "$r" = "1.0" ]; then echo "PASS $id reference fix scores 1.0"; else echo "FAIL $id reference fix scored $r"; fail=1; fi
  s=$(score "$id" "$T/ans_$id.json" "$T/seed_$id")
  if [ "$s" = "0.0" ]; then echo "PASS $id seeded fixture scores 0.0"; else echo "FAIL $id seeded fixture scored $s"; fail=1; fi
done
exit $fail
