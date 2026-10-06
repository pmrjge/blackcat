# PF pool: planted-gap proofs checked by Lean 4 (2026-10-04, built by mathematician)

**Counts:** 215 pool + 3 dev items (PF-DEV1..3: gcdlin, divind, amgm), 15 parametrised families (14-16 each): 2nd- and
1st-order recurrences, power sums from a+b and ab, gcd of linear forms, Diophantine non-solvability mod m, m | n^k - n^j,
exponential/factorial bounds, cubic roots, AM-GM bounds, telescoping and closed-form sums, Pell witnesses, additive
functional equations, p^(un+v) + q^(wn+z) divisibility, quartic positivity. **Item:** prompt = the Lean statement (closed Prop, theorem `pf_<id>`) + instructions; segments = sketch steps "Step i of
K", shuffled once (`default_rng(3725927731)`, id order). One step is a planted gap, a concrete false claim (wrong
residue/modulus, sign or index slip, wrong witness, Fermat misused at p | n, false base case, ...); `decisive_segment` =
its index (`oracle/items_meta.jsonl` has it as a Lean Prop). Answer = the complete Lean file.

**Oracle:** `check_lean.sh ANSWER.lean [statement.txt]` (Lean 4.34.1, Mathlib v4.34.1 at `$EQ_LEAN_PROJECT`, default
`/Users/pmrj/lean/stack_mathlib`), Lean tooling only, no text screening: (1) `EqStmt.lean` = `import Mathlib` +
`def eq_pristine_stmt : Prop := <statement>` from statement.txt alone, compiled concurrently with (2) the answer as
module EqAnswer; (4) trusted `EqVerify.lean` (`lean --run`) replays the answer's constants through the kernel on its
imports plus EqStmt (`Kernel.Environment.replay`, leanchecker's code), requires `<name>` declared by the answer with
type = pristine statement (alpha-equivalence, else kernel defeq), and walks the replayed constants for axioms (only
propext, Classical.choice, Quot.sound). (3) core `leanchecker EqAnswer` is off by default (`EQ_LEANCHECKER=1` turns it
on): LeanChecker.lean:12-34 and EqVerify read the same olean parts and call the same replay on the same constants, in a
subset vs superset import env, and EqVerify fails closed on any constant it could not replay; it cost ~8 s of ~11 s.
Limits: min(`EQ_LEAN_TIMEOUT` 300 s, time left of `EQ_LEAN_TOTAL` 540 s, below the harness kill at 600 s) per Lean
run; timeout, crash or signal = FAIL. Measured (finalcheck, 12 checks in parallel): reference median 65 s, max 86 s;
wrong answers median 41 s, max 55 s; one check alone on an idle machine ~11 s. `uv run oracle.py --item ID --answer
out.json` -> 1/0 (exit 2 malformed, 3 Lean environment broken). Fixture = public check (Problem.lean, statement.txt,
check_lean.sh, EqVerify.lean; harness writes `answer` to Answer.lean). `allowed_tools`: Read, Write, Edit, Bash.

**Proven per item:** `gen_pf.py verify` (218/218, `oracle/build/verify_results.jsonl`, earlier text-screening checker):
gap refuted in Lean (`oracle/gap/`); no single tactic of simp, simp_all, decide, omega, norm_num, linarith, nlinarith,
positivity, aesop, tauto, ring_nf, field_simp, exact? (alone or after `intros`) closes the statement (the battery does
solve trivial controls). Current checker (`finalcheck`, `oracle/build/final_check.tsv` with seconds): reference
(`oracle/ref/`) 1 and gap-following wrong answer (`oracle/wrong/`) 0 on every item. `selftest.sh` (13 per dev item,
39/39 PASS, `oracle/build/selftest.out`): reference, legitimate variant (lemma, `open Nat in`, haveI, exported Fact
instance, banned words in comments, `#print axioms`) and a type only defeq to the statement score 1; gap-following,
incomplete, sorry, True, stmt ∨ True, declared axiom, sorryAx, wrong theorem name, missing answer 0; malformed exit 2.

**Known weaknesses:** templated families (effective diversity ~15); difficulty not calibrated on any model; the gap
can be ignored. The checker trusts the imported Mathlib oleans and the kernel; unsafe/partial constants are not
replayed (false FAIL, unlikely). Compile-time code in an answer (#eval, run_cmd, initialize, elaborators or macros it
defines) runs with the caller's privileges during step 2, in the member's own check, in the harness public check and
in oracle.py. No sandbox is provided: the harness runs both unsandboxed (harness/README.md, isolation paragraph;
sandbox-exec wrapping not built). Owner: harness, open item. No adversarial probing (user decision).

**Verdict channel (security finding F1):** `oracle.py` reads the harness nonce from the first stdin line before anything
else (missing, empty or multi-word: exit 4, nothing on stdout), sets PR_SET_DUMPABLE=0 on Linux only (macOS host / off mode
work without prctl), runs `check_lean.sh` with stdin=DEVNULL in its own session (group killed afterwards), and prints
`EQV1 <nonce> <json>` as its very last act; the harness must accept exactly one such line carrying its nonce. Exit codes
are unchanged (0 scored, 2 malformed, 3 checker error, plus 4 no nonce). `check_lean.sh` and `EqVerify.lean` are
untouched (hash-frozen). Proofs: `items/test_f1_verdict_channel.py` (stub judge in a scratch copy). **Residual:** the
answer's compile-time code (`#eval`, elaborators, macros) runs inside the same `check_lean.sh` process tree as the
trusted `EqVerify` step and can tamper with what the checker reads (the compiled `.olean`, the files `check_lean.sh`
writes) or with the final `PASS` line it prints; the nonce does not help because the oracle trusts the checker's last
line. Stronger fix (needs the frozen judge split, not done): two containers, compile in the first, run `EqVerify` in a
fresh one with the `.olean` mounted read-only.
