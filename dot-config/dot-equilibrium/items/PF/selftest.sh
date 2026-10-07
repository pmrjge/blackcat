#!/usr/bin/env bash
# PF selftest (ordinary, non-adversarial cases), 13 per dev item: the oracle must score 1 for the reference proof, for
# a legitimate variant (lemma + `open Nat in` + haveI + exported Fact instance + banned words in comments +
# `#print axioms`) and for a proof whose declared type is only definitionally equal to the statement (`theorem name :
# eq_S` with `def eq_S : Prop := stmt`, kernel-defeq branch); 0 for each wrong answer: gap-following proof, incomplete
# proof, sorry, wrong statement (True), changed statement (stmt ∨ True), declared axiom, explicit sorryAx, wrong theorem
# name, missing answer; malformed input exits 2. One PASS/FAIL line per check; exit 1 on any FAIL.
set -u
here=$(cd "$(dirname "$0")" && pwd)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/pfself.XXXXXX") || exit 2
trap 'rm -rf "$tmp"' EXIT
fails=0
NONCE=00112233445566778899aabbccddeeff  # the oracle reads it on stdin and prints `EQV1 <nonce> <json>`

wrap() { jq -Rs '{answer: ., evidence: [], confidence: 0.5}' < "$1" > "$2"; }

expect() { # label item answer.json expected-score
  local out score
  out=$(printf '%s\n' "$NONCE" | uv run --quiet "$here/oracle.py" --item "$2" --answer "$3" 2>/dev/null | sed -n "s/^EQV1 $NONCE //p")
  score=$(printf '%s' "$out" | jq -r '.score' 2>/dev/null)
  if [ "$score" = "$4" ]; then echo "PASS $2 $1 (score $score)"
  else echo "FAIL $2 $1 (expected $4, got: $out)"; fails=$((fails + 1)); fi
}

for item in $(jq -r 'select(.dev) | .id' "$here/manifest.jsonl"); do
  fx="$here/fixtures/$item"
  name=$(head -n 1 "$fx/statement.txt" | tr -d '[:space:]')
  stmt=$(tail -n +2 "$fx/statement.txt")
  d="$tmp/$item"; mkdir -p "$d"
  wrap "$here/oracle/ref/$item.lean" "$d/ref.json";            expect reference "$item" "$d/ref.json" 1
  wrap "$here/oracle/wrong/$item.lean" "$d/gap.json";          expect gap_following_wrong "$item" "$d/gap.json" 0
  wrap "$fx/Problem.lean" "$d/sorry.json";                     expect sorry "$item" "$d/sorry.json" 0
  printf 'import Mathlib\n\ntheorem %s : True := trivial\n' "$name" > "$d/stmt.lean"
  wrap "$d/stmt.lean" "$d/stmt.json";                          expect wrong_statement "$item" "$d/stmt.json" 0
  printf 'import Mathlib\n\naxiom eq_cheat : False\n\ntheorem %s : %s := eq_cheat.elim\n' "$name" "$stmt" > "$d/ax.lean"
  wrap "$d/ax.lean" "$d/ax.json";                              expect axiom_declared "$item" "$d/ax.json" 0
  printf 'import Mathlib\n\ntheorem %s : %s := sorryAx _ false\n' "$name" "$stmt" > "$d/sax.lean"
  wrap "$d/sax.lean" "$d/sax.json";                            expect explicit_sorryAx "$item" "$d/sax.json" 0
  printf 'import Mathlib\n\ntheorem %s : (%s) ∨ True := Or.inr trivial\n' "$name" "$stmt" > "$d/chg.lean"
  wrap "$d/chg.lean" "$d/chg.json";                            expect changed_statement "$item" "$d/chg.json" 0
  sed '$d' "$here/oracle/ref/$item.lean" > "$d/inc.lean"
  wrap "$d/inc.lean" "$d/inc.json";                            expect incomplete_proof "$item" "$d/inc.json" 0
  body=$(sed -n '/:= by$/,$p' "$here/oracle/ref/$item.lean" | tail -n +2)
  { printf 'import Mathlib\n\n-- comment words: sorry axiom native_decide instance notation macro\n/- block: admit #eval -/\n'
    printf 'instance : Fact (Nat.Prime 7) := ⟨by norm_num⟩\n\nopen Nat in\nlemma eq_aux : %s := by\n  haveI : Fact (Nat.Prime 2) := ⟨by norm_num⟩\n%s\n\n' "$stmt" "$body"
    printf 'theorem %s : %s := eq_aux\n\n#print axioms %s\n' "$name" "$stmt" "$name"; } > "$d/legit.lean"
  wrap "$d/legit.lean" "$d/legit.json";                        expect legit_variant "$item" "$d/legit.json" 1
  printf 'import Mathlib\n\ndef eq_S : Prop := %s\n\ntheorem %s : eq_S := by\n  show %s\n%s\n' "$stmt" "$name" "$stmt" "$body" > "$d/defeq.lean"
  wrap "$d/defeq.lean" "$d/defeq.json";                        expect defeq_statement "$item" "$d/defeq.json" 1
  sed "s/^theorem $name /theorem eq_other /" "$here/oracle/ref/$item.lean" > "$d/name.lean"
  wrap "$d/name.lean" "$d/name.json";                          expect wrong_name "$item" "$d/name.json" 0
  printf '{"evidence": [], "confidence": 0.5}' > "$d/missing.json"; expect missing_answer "$item" "$d/missing.json" 0
  printf 'not json' > "$d/bad.json"
  printf '%s\n' "$NONCE" | uv run --quiet "$here/oracle.py" --item "$item" --answer "$d/bad.json" > /dev/null 2>&1; rc=$?
  if [ "$rc" = 2 ]; then echo "PASS $item malformed_input (exit 2)"; else echo "FAIL $item malformed_input (exit $rc)"; fails=$((fails + 1)); fi
done
[ "$fails" -eq 0 ] || exit 1
exit 0
