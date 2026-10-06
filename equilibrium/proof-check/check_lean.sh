#!/usr/bin/env bash
# check_lean.sh ANSWER.lean [STATEMENT.txt]
# PF checker (public check and oracle core). Prints PASS or FAIL: <reason>; exit 0 on PASS, 1 on FAIL, 2 on usage error.
# STATEMENT.txt: line 1 = theorem name, lines 2.. = the closed statement (a Lean Prop). Default: statement.txt next to
# this script (each fixture ships its own copy).
# Accepts iff (1) the lexical screen passes (comments/strings stripped; no sorry/admit/axiom/native_decide/#eval/#exit,
# no notation/macro/syntax/elab, no exported instance other than Fact, no unsafe/extern/opaque, imports only from
# Mathlib/Batteries/Aesop, no set_option debug.*/bootstrap.*/compiler.*/interpreter.*); (2) the answer compiles as module EqAnswer;
# (3) a separate module importing EqAnswer elaborates `theorem eq_statement_check : <statement> := <name>`;
# (4) `#print axioms eq_statement_check` lists only propext, Classical.choice, Quot.sound.
# Lean project with Mathlib: $EQ_LEAN_PROJECT (default /Users/pmrj/lean/stack_mathlib, Lean 4.34.1, Mathlib v4.34.1).
# Time limit per Lean run: $EQ_LEAN_TIMEOUT seconds (default 300).
set -u
ans=${1:-}
here=$(cd "$(dirname "$0")" && pwd)
stmt_file=${2:-$here/statement.txt}
proj=${EQ_LEAN_PROJECT:-/Users/pmrj/lean/stack_mathlib}
tlimit=${EQ_LEAN_TIMEOUT:-300}
if [ -z "$ans" ] || [ ! -f "$ans" ] || [ ! -f "$stmt_file" ] || [ ! -d "$proj" ]; then
  echo "usage: check_lean.sh ANSWER.lean [STATEMENT.txt]  (answer, statement or Lean project missing)" >&2
  exit 2
fi
name=$(head -n 1 "$stmt_file" | tr -d '[:space:]')
stmt=$(tail -n +2 "$stmt_file")
if [ -z "$name" ] || [ -z "$stmt" ]; then echo "usage: empty statement file" >&2; exit 2; fi

work=$(mktemp -d "${TMPDIR:-/tmp}/eqlean.XXXXXX") || exit 2
trap 'rm -rf "$work"' EXIT
cp "$ans" "$work/EqAnswer.lean"

# 1. lexical screen on the answer with comments and string literals removed
reason=$(perl -e '
  local $/; my $s = <STDIN>;
  # strip nested block comments /- ... -/
  my $out = ""; my $depth = 0; my $i = 0; my $n = length $s;
  while ($i < $n) {
    my $two = substr($s, $i, 2);
    if ($two eq "/-") { $depth++; $i += 2; next; }
    if ($depth > 0 && $two eq "-/") { $depth--; $i += 2; next; }
    if ($depth == 0) { $out .= substr($s, $i, 1); }
    $i++;
  }
  $out =~ s/--[^\n]*//g;            # line comments
  $out =~ s/"(?:[^"\\]|\\.)*"/""/g; # string literals
  $out =~ s{\b(local|scoped)\s+instance\b}{}g;            # non-exported instances are fine
  $out =~ s{\binstance\b[^:\n]*:\s*Fact\b}{}g;           # Fact instances (e.g. primality) are fine
  my @bad = qw(sorry admit axiom native_decide ofReduceBool implemented_by extern unsafe
               macro macro_rules syntax elab elab_rules notation infix infixl infixr prefix postfix instance
               run_cmd run_tac run_elab run_meta initialize builtin_initialize opaque trustCompiler);
  for my $w (@bad) { if ($out =~ /(?<![\w.])\Q$w\E(?![\w])/) { print "banned token: $w"; exit 0; } }
  for my $w ("#exit", "#eval", "#exec") { if (index($out, $w) >= 0) { print "banned token: $w"; exit 0; } }
  while ($out =~ /^\s*import\s+(\S+)/mg) {
    my $m = $1;
    unless ($m =~ /^(Mathlib|Batteries|Aesop)(\.[A-Za-z0-9_.]+)?$/) { print "import not allowed: $m"; exit 0; }
  }
  while ($out =~ /set_option\s+(\S+)/g) {
    my $o = $1;
    if ($o =~ /^(debug|bootstrap|compiler|interpreter)\./) { print "set_option not allowed: $o"; exit 0; }
  }
' < "$work/EqAnswer.lean")
if [ -n "$reason" ]; then echo "FAIL: $reason"; exit 1; fi

run_lean() { # run with a wall-clock limit (no coreutils timeout on macOS)
  perl -e 'my $t = shift; my $pid = fork(); if ($pid == 0) { exec @ARGV or exit 127 }
           local $SIG{ALRM} = sub { kill "KILL", $pid; print STDERR "eqlean: timeout\n"; exit 124 };
           alarm $t; waitpid($pid, 0); exit($? >> 8)' "$tlimit" "$@"
}

LP=$(cd "$proj" && lake env printenv LEAN_PATH 2>/dev/null) || { echo "FAIL: lake env failed in $proj"; exit 1; }

# 2. compile the answer as module EqAnswer
if ! (cd "$proj" && export LEAN_PATH="$LP" && run_lean lean --root="$work" -o "$work/EqAnswer.olean" "$work/EqAnswer.lean") > "$work/answer.log" 2>&1; then
  echo "FAIL: answer does not compile: $(grep -m 3 -E 'error|timeout' "$work/answer.log" | tr '\n' ' ' | cut -c1-600)"
  exit 1
fi

# 3. statement check in a separate module
{
  printf 'import Mathlib\nimport EqAnswer\n\ntheorem eq_statement_check :\n'
  printf '%s\n' "$stmt"
  printf '  := %s\n\n#print axioms eq_statement_check\n' "$name"
} > "$work/EqCheck.lean"
if ! (cd "$proj" && export LEAN_PATH="$work:$LP" && run_lean lean "$work/EqCheck.lean") > "$work/check.log" 2>&1; then
  echo "FAIL: statement mismatch or theorem '$name' missing: $(grep -m 3 -E 'error|timeout' "$work/check.log" | tr '\n' ' ' | cut -c1-600)"
  exit 1
fi

# 4. axioms
ax=$(tr '\n' ' ' < "$work/check.log" | sed -n "s/.*'eq_statement_check' depends on axioms: \[\([^]]*\)\].*/\1/p")
if [ -z "$ax" ] && ! grep -q "'eq_statement_check' does not depend on any axioms" "$work/check.log"; then
  echo "FAIL: could not read axioms output"; exit 1
fi
for a in $(printf '%s' "$ax" | tr ',' ' '); do
  case "$a" in
    propext|Classical.choice|Quot.sound) ;;
    *) echo "FAIL: non-standard axiom $a"; exit 1 ;;
  esac
done
echo "PASS"
exit 0
