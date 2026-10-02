---
name: fm-tla
description: Use for model-checking concurrent or distributed protocols — TLA+, PlusCal, safety and liveness, TLC, Apalache.
---
# TLA+ and PlusCal (TLC, Apalache)
Hub: `formal-methods` (tool choice, what each result guarantees — §7, report table). Tool versions and commands were checked earlier without recorded URLs: unverified as of 2026-10-02 unless a Sources line says otherwise.

Tools: `tla2tools.jar` (SANY parser, PlusCal translator, TLC) on a recent JDK — releases at github.com/tlaplus/tlaplus, or the TLA+ VS Code extension. Commands (checked on a current build):
- Translate PlusCal: `java -cp tla2tools.jar pcal.trans -nocfg Spec.tla` (without `-nocfg` the translator writes and rewrites `Spec.cfg`).
- Check: `java -XX:+UseParallelGC -cp tla2tools.jar tlc2.TLC -workers auto -config Spec.cfg Spec.tla`.
- Useful flags: `-deadlock` (turns deadlock checking OFF), `-dumpTrace json trace.json`, `-simulate -depth 200` (random deep traces for huge spaces), `-coverage 1`, `-continue`, `-difftrace`.

```tla
---- MODULE Peterson ----
EXTENDS Naturals
(* --algorithm Peterson
variables flag = [p \in {0, 1} |-> FALSE], turn = 0;
fair process proc \in {0, 1}
begin
  ncs: while TRUE do
  a1:    flag[self] := TRUE;
  a2:    turn := 1 - self;
  a3:    await ~flag[1 - self] \/ turn = self;
  cs:    skip;
  a4:    flag[self] := FALSE;
       end while;
end process;
end algorithm; *)
\* BEGIN TRANSLATION
\* END TRANSLATION
MutualExclusion == ~(pc[0] = "cs" /\ pc[1] = "cs")
StarvationFree  == \A p \in {0, 1} : (pc[p] = "a1") ~> (pc[p] = "cs")
====
```
`Peterson.cfg`: `SPECIFICATION Spec` / `INVARIANT MutualExclusion` / `PROPERTY StarvationFree`. TLC: no error, 42 distinct states; swapping `a1` and `a2` (write `turn` before raising `flag`) yields a mutual-exclusion counterexample trace.
- Safety: invariants (`TypeOK`, mutual exclusion, no lost update) and action properties `[][A]_vars`. Liveness: `P ~> Q`, `<>[]P`, `[]<>P` — only meaningful with fairness (`fair process` = weak fairness, `fair+ process` = strong, or `WF_vars(Next)` in the spec); without it every liveness property fails by stuttering.
- Model the environment explicitly: message loss, duplication and reordering, crash/restart with persisted vs volatile state, timeouts, clock skew. The bugs live there.
- State-space control: small constants (3 nodes, 2 values) find most bugs; `CONSTRAINT` bounds counters and queues; symmetry sets (`Permutations(Nodes)`) shrink the space but can hide liveness violations — drop symmetry when checking liveness; `VIEW` abstracts irrelevant variables; watch distinct states and depth in the output.
- Guard against vacuity: add a "reachability" invariant that should fail (e.g. `~(pc[0] = "cs")`) and confirm TLC produces a trace; mutate the spec (remove a guard) and confirm TLC catches it.
- Apalache (symbolic, SMT-based, bounded): needs type annotations (`\* @type: ...;`); `apalache-mc typecheck Spec.tla`, `apalache-mc check --inv=Inv --length=10 Spec.tla` (also `--init`, `--next`, `--cinit`, `--temporal`). Proves unbounded safety via an inductive invariant: `--init=Init --inv=IndInv --length=0`, then `--init=IndInv --inv=IndInv --length=1`, then `--init=IndInv --inv=Safety --length=0`. Check the current version and install at apalache-mc.org.

Protocol design patterns (consensus, idempotency, retries, outbox) and their failure modes: `dist-systems`.

## Verify
- [ ] Safety invariants and liveness properties written in words and in TLA+; fairness stated for every liveness property.
- [ ] Non-vacuity: a reachability invariant fails with a trace; a mutated spec (guard removed) is caught.
- [ ] Constants, constraints, symmetry and the distinct-state count and depth reported; liveness checked without symmetry.
- [ ] tla2tools / Apalache versions recorded.
