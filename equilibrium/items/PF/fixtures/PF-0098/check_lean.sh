#!/usr/bin/env bash
# check_lean.sh ANSWER.lean [STATEMENT.txt]
# PF checker (public check and oracle core). Prints PASS or FAIL: <reason>; exit 0 on PASS, 1 on FAIL, 2 on usage or
# environment error (missing files, Lean project missing, fixture statement does not elaborate).
# STATEMENT.txt: line 1 = theorem name, lines 2.. = the closed statement (a Lean Prop). Default: statement.txt next to
# this script (each fixture ships its own copy, with EqVerify.lean).
# Steps, all with Lean's own tooling (no text screening of the answer):
#  1. EqStmt.lean = `import Mathlib` + `def eq_pristine_stmt : Prop := <statement>` is built from STATEMENT.txt alone,
#     so the answer cannot affect how the statement elaborates.        (steps 1 and 2 run concurrently)
#  2. The answer is compiled as module EqAnswer (lean -o).
#  3. Optional (EQ_LEANCHECKER=1): core `leanchecker EqAnswer`. Off by default: it runs the same
#     Kernel.Environment.replay on the same constants as step 4 (see README).
#  4. The trusted EqVerify.lean (lean --run) replays the answer's constants through the kernel on top of the answer's
#     imports plus EqStmt (the replay code of core leanchecker), then checks that the answer's constant <name> has
#     exactly the pristine statement as its type (alpha-equivalence, else kernel defeq) and that its transitive axioms
#     are among propext, Classical.choice, Quot.sound.
# Lean project with Mathlib: $EQ_LEAN_PROJECT (default /Users/pmrj/lean/stack_mathlib, Lean 4.34.1, Mathlib v4.34.1).
# Time limits: each Lean run gets min($EQ_LEAN_TIMEOUT (default 300), time left before the total deadline
# $EQ_LEAN_TOTAL seconds (default 540, below the harness kill at 600 s)). Timeout, crash or signal = FAIL.
# EQ_LEAN_VERBOSE=1 copies the verifier's INFO lines (how the statement matched) to stderr.
# Compile-time code in an answer (#eval, run_cmd, initialize, elaborators or macros it defines) runs with the caller's
# privileges during step 2. No sandbox is provided here; the harness runs this unsandboxed (open item, owner: harness).
set -u
ans=${1:-}
here=$(cd "$(dirname "$0")" && pwd)
stmt_file=${2:-$here/statement.txt}
verifier=$here/EqVerify.lean
proj=${EQ_LEAN_PROJECT:-/Users/pmrj/lean/stack_mathlib}
tlimit=${EQ_LEAN_TIMEOUT:-300}
deadline=$(( $(date +%s) + ${EQ_LEAN_TOTAL:-540} ))
if [ -z "$ans" ] || [ ! -f "$ans" ] || [ ! -f "$stmt_file" ] || [ ! -f "$verifier" ] || [ ! -d "$proj" ]; then
  echo "usage: check_lean.sh ANSWER.lean [STATEMENT.txt]  (answer, statement, EqVerify.lean or Lean project missing)" >&2
  exit 2
fi
name=$(head -n 1 "$stmt_file" | tr -d '[:space:]')
stmt=$(tail -n +2 "$stmt_file")
if [ -z "$name" ] || [ -z "$stmt" ]; then echo "usage: empty statement file" >&2; exit 2; fi

work=$(mktemp -d "${TMPDIR:-/tmp}/eqlean.XXXXXX") || exit 2
trap 'rm -rf "$work"' EXIT
cp "$ans" "$work/EqAnswer.lean"
{ printf 'import Mathlib\n\ndef eq_pristine_stmt : Prop :=\n'; printf '%s\n' "$stmt"; } > "$work/EqStmt.lean"

run_lean() { # wall-clock limit (no coreutils timeout on macOS); 124 timeout, 125 fork failure, 128+N killed by signal N
  local left=$(( deadline - $(date +%s) ))
  [ "$left" -lt 1 ] && left=1
  local t=$(( left < tlimit ? left : tlimit ))
  perl -e 'my $t = shift; my $pid = fork(); defined $pid or exit 125; if ($pid == 0) { exec @ARGV or exit 127 }
           local $SIG{ALRM} = sub { kill "KILL", $pid; print STDERR "eqlean: timeout\n"; exit 124 };
           alarm $t; waitpid($pid, 0); alarm 0;
           if ($? & 127) { print STDERR "eqlean: killed by signal ", ($? & 127), "\n"; exit(128 + ($? & 127)) }
           exit($? >> 8)' "$t" "$@"
}
first_errors() { grep -m 3 -E 'error|timeout|signal' "$1" | tr '\n' ' ' | cut -c1-600; }

LP=$(cd "$proj" && lake env printenv LEAN_PATH 2>/dev/null) || { echo "lake env failed in $proj" >&2; exit 2; }

# 1. pristine statement (trusted input only), concurrently with 2. the answer compiled as module EqAnswer
(cd "$proj" && export LEAN_PATH="$LP" && run_lean lean --root="$work" -o "$work/EqStmt.olean" "$work/EqStmt.lean") > "$work/stmt.log" 2>&1 &
spid=$!
(cd "$proj" && export LEAN_PATH="$LP" && run_lean lean --root="$work" -o "$work/EqAnswer.olean" "$work/EqAnswer.lean") > "$work/answer.log" 2>&1
arc=$?
wait "$spid"
src=$?
if [ "$src" -ne 0 ]; then
  echo "fixture statement does not elaborate (rc $src): $(first_errors "$work/stmt.log")" >&2
  exit 2
fi
if [ "$arc" -ne 0 ]; then
  echo "FAIL: answer does not compile (rc $arc): $(first_errors "$work/answer.log")"
  exit 1
fi

# 3. optional: core leanchecker replay of the answer's constants on top of its imports
if [ "${EQ_LEANCHECKER:-0}" = 1 ]; then
  if ! (cd "$proj" && export LEAN_PATH="$work:$LP" && run_lean leanchecker EqAnswer) > "$work/leanchecker.log" 2>&1; then
    echo "FAIL: leanchecker rejected the answer: $(tr '\n' ' ' < "$work/leanchecker.log" | cut -c1-600)"
    exit 1
  fi
fi

# 4. trusted verifier: replay on top of imports + EqStmt, statement identity, axioms
(cd "$proj" && export LEAN_PATH="$work:$LP" && run_lean lean --run "$verifier" EqAnswer EqStmt "$name") > "$work/verify.log" 2>&1
rc=$?
verdict=$(grep -E '^(PASS|FAIL)' "$work/verify.log" | tail -n 1)
if [ "$rc" = 0 ] && [ "$verdict" = PASS ]; then
  [ "${EQ_LEAN_VERBOSE:-0}" = 1 ] && grep '^INFO' "$work/verify.log" >&2
  echo "PASS"; exit 0
fi
if [ "$rc" = 1 ] && [ -n "$verdict" ]; then echo "$verdict" | cut -c1-800; exit 1; fi
if [ "$rc" = 1 ]; then echo "FAIL: verifier aborted on the answer: $(tr '\n' ' ' < "$work/verify.log" | cut -c1-600)"; exit 1; fi
if [ "$rc" = 124 ]; then echo "FAIL: verifier timeout"; exit 1; fi
# steps 1-2 already imported Mathlib cleanly, so a crash here comes from the answer
if [ "$rc" -ge 128 ]; then echo "FAIL: verifier crashed on the answer: $(tail -c 300 "$work/verify.log" | tr '\n' ' ')"; exit 1; fi
echo "verifier error rc=$rc: $(tr '\n' ' ' < "$work/verify.log" | cut -c1-600)" >&2
exit 2
