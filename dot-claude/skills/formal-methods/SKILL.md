---
name: formal-methods
description: Use when code or a protocol needs machine-checked assurance — z3/SMT, TLA+ (TLC, Apalache), Kani and Miri, property-based and stateful tests, fuzzing; what each result guarantees.
---
# Formal methods and machine-checked assurance

## Scope
- Covers: selecting and applying SMT solving, model checking, bounded model checking for Rust, UB detection, property-based/stateful testing and fuzzing; stating what the evidence proves.
- Not here: interactive theorem proving — Lean, Coq/Rocq, Isabelle are pointers only (the `lean-formalization` skill covers Lean; a Lean 4 prover MCP server can be mounted on demand). Algorithm design: `algorithm-design`. Threat modeling and secure patterns: `secure-coding`.

## 1. Pick the tool by the question
| Question | Tool | Result means | Effort |
|---|---|---|---|
| Does an arithmetic/bit-level fact, bound or loop invariant hold for all inputs of a fixed width? | SMT: z3 (Python) | proof for the encoded formula (bit-precise with bit-vectors) | minutes–hours |
| Does a concurrent or distributed protocol keep safety and liveness under all interleavings, crashes, message loss? | TLA+/PlusCal + TLC (explicit, finite model); Apalache (symbolic, bounded) | exhaustive for the chosen constants / up to the depth bound | days to model well |
| Can this Rust function panic, overflow or violate an assertion for any input? | Kani | all inputs allowed by the harness, loops within the unwind bound | minutes–hours |
| Does (unsafe) Rust hit UB on the paths the tests execute? | Miri | per executed path and seed | tests run 10–100× slower |
| Is a concurrent Rust structure correct under the C11 memory model? | loom (exhaustive for tiny tests), shuttle (randomized) | bounded interleavings | hours |
| Does the implementation agree with a model over random operation sequences? | stateful PBT: hypothesis, proptest(-state-machine), fast-check (`test-property-based`) | evidence, not proof | cheap |
| Does a parser/decoder crash, hang or hit UB on hostile bytes? | fuzzing (cargo-fuzz, atheris, AFL++) + sanitizers (`test-fuzzing`) | coverage-guided evidence | CPU-hours |
| Full functional correctness of a small critical core | deductive verification: Dafny, Verus or Creusot (Rust), Frama-C WP / Why3 (C), SPARK (Ada); proof assistants | proof relative to the spec and trusted base | weeks |

Order of attack: PBT and fuzzing on existing code first (cheap, and they find the shallow bugs fast); model-check a protocol before implementing it; SMT for localized arithmetic facts; deductive proofs only for small cores where the cost is justified. Verify the current status and install method of any tool not covered below before recommending it.

## 2. SMT with z3 (Python)
z3-solver is in the sci venv: `__CLAUDE_DIR__/venvs/sci/bin/python`. To prove P, assert ¬P: `unsat` = proved for the encoding, `sat` = counterexample in `s.model()`, `unknown` (timeout, quantifiers, nonlinear integers) = nothing proved.
```python
from z3 import *

# Midpoint of unsigned 32-bit indices: naive form overflows, safe form stays in range.
lo, hi = BitVecs("lo hi", 32)
s = Solver(); s.add(ULE(lo, hi), Not(BVAddNoOverflow(lo, hi, False)))
print(s.check(), s.model())                 # sat: e.g. lo=1, hi=2^32-1 -> (lo+hi)/2 overflows
s = Solver(); mid = lo + LShR(hi - lo, 1)
s.add(ULE(lo, hi), Not(And(ULE(lo, mid), ULE(mid, hi))))
print(s.check())                            # unsat: holds for every pair with lo <= hi

# Inductive invariant for: i = 0; t = 0; while i < n: t += i; i += 1   (claim: 2t = i(i-1))
i, t, n, i1, t1 = Ints("i t n i1 t1")
inv = lambda i, t: And(2 * t == i * (i - 1), 0 <= i, i <= n)
def valid(f):
    v = Solver(); v.add(Not(f)); return v.check() == unsat
print(valid(Implies(And(i == 0, t == 0, n >= 0), inv(i, t))),                       # initiation
      valid(Implies(And(inv(i, t), i < n, i1 == i + 1, t1 == t + i), inv(i1, t1))),  # consecution
      valid(Implies(And(inv(i, t), Not(i < n)), 2 * t == n * (n - 1))))             # exit => post
```
Encoding rules:
- `Int`/`Real` are mathematical: no overflow, so they cannot find overflow bugs. Model machine integers with `BitVec(width)`. On bit-vectors `<`, `/`, `%`, `>>` are signed; use `ULT/ULE/UDiv/URem/LShR` for unsigned. Overflow predicates: `BVAddNoOverflow(a, b, signed)`, `BVMulNoOverflow`, `BVSubNoUnderflow`, `BVSDivNoOverflow`.
- IEEE floats: `FP("x", Float32())` sorts are bit-precise but slow; modeling floats as `Real` ignores rounding, NaN and infinities.
- Straight-line code → SSA (a fresh variable per assignment); loops → an inductive invariant (three checks above) or bounded unrolling (only a bounded claim).
- Vacuity: check the assumptions alone are satisfiable — contradictory preconditions make every property "proved".
- Quantifiers: E-matching/MBQI may give `unknown` or run forever. Prefer quantifier-free encodings; add `patterns=[...]` to `ForAll`; set `s.set("timeout", ms)`. Nonlinear integer arithmetic is undecidable — bound the range and use bit-vectors.
- Debugging unsat: `s.set(unsat_core=True)`, `s.assert_and_track(expr, "label")`, `s.unsat_core()` (add `s.set("core.minimize", True)` for a smaller core). Incremental queries: `push()`/`pop()`.
- Optimization: `Optimize()` with `minimize`/`maximize` (then `h.value()`), `add_soft(expr, weight)` for MaxSAT. For large combinatorial optimization prefer a MIP/CP solver (`algorithm-design`).

## 3. TLA+ and PlusCal (TLC, Apalache)
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

## 4. Rust: Kani, Miri, loom
Kani (bounded model checking, CBMC backend). Install: `cargo install --locked kani-verifier && cargo kani setup` (Linux x86-64, macOS Intel and Apple Silicon).
```rust
pub fn midpoint(lo: u32, hi: u32) -> u32 { lo + (hi - lo) / 2 }

#[cfg(kani)]
mod proofs {
    use super::*;
    #[kani::proof]
    fn midpoint_in_range() {
        let (lo, hi): (u32, u32) = (kani::any(), kani::any());
        kani::assume(lo <= hi);
        let m = midpoint(lo, hi);
        assert!(lo <= m && m <= hi);
    }
}
```
- Run `cargo kani` (all harnesses) or `cargo kani --harness midpoint_in_range`; loops need `#[kani::unwind(N)]` or `--default-unwind N` — unwinding assertions fail loudly when N is too small; `-Z concrete-playback --concrete-playback=print` turns a counterexample into a unit test; defaults go in `[package.metadata.kani.flags]`.
- Checked automatically: panics (assert, unwrap, expect, indexing), arithmetic overflow, division by zero, oversized shifts, invalid pointer dereferences. Limits: bounded inputs and loops, heavy heap/large arrays get slow, no concurrency; contracts, stubbing and loop invariants are experimental (see `cargo kani --help` for the unstable flags).
- Plain `cargo build` warns `unexpected cfg condition name: kani` (likewise `loom`); declare them: `[lints.rust] unexpected_cfgs = { level = "warn", check-cfg = ['cfg(kani)', 'cfg(loom)'] }`.

Miri (interpreter that detects UB): `rustup +nightly component add miri`, then `cargo +nightly miri test`. Detects out-of-bounds and use-after-free, uninitialized reads, invalid values, misalignment, data races, Stacked/Tree Borrows aliasing violations, leaks. Flags via `MIRIFLAGS`: `-Zmiri-tree-borrows`, `-Zmiri-many-seeds` (explore schedules and nondeterminism), `-Zmiri-strict-provenance`, `-Zmiri-disable-isolation` (host env/files). Cross-check endianness with `cargo +nightly miri test --target s390x-unknown-linux-gnu`. No FFI; only the executed paths.

loom: write the test against `loom::sync`/`loom::thread` inside `loom::model(|| { ... })`, gate with `#[cfg(loom)]`, run `RUSTFLAGS="--cfg loom" cargo test --release`; keep tests to 2–3 threads and a few operations. shuttle randomizes schedules for larger tests. Sanitizers (nightly): `RUSTFLAGS="-Zsanitizer=address" cargo +nightly test -Zbuild-std --target x86_64-unknown-linux-gnu` (thread sanitizer likewise; `-Zbuild-std` needs the `rust-src` component and an instrumented std avoids TSan false positives).

## 5–6. Property-based, stateful testing and fuzzing
Moved to modules of `test-strategy`: `test-property-based` (hypothesis state machines, proptest, fast-check) and `test-fuzzing` (cargo-fuzz, atheris, AFL++, Go fuzzing, sanitizers, corpus hygiene). Their results are evidence, not proof (§7).

## 7. What a result does and does not guarantee
- Everything is relative to a specification and a trusted base (compiler, solver, model checker, harness, stubs). A wrong or vacuous spec proves nothing — always demonstrate that the check can fail.
- SMT `unsat`: the property holds for the formula as encoded (widths, semantics, assumptions). Not for code paths you did not encode, not across `Int`-vs-machine-integer gaps. `unknown` is not a proof.
- TLC "no error": holds for the finite model with those constants, constraints and fairness assumptions, at the spec level — not for the implementation (refinement gap) or larger instances. Apalache without an inductive invariant: holds up to `--length` steps.
- Kani "VERIFICATION SUCCESSFUL": every input the harness admits, loops within bounds, no concurrency, stubs trusted. `kani::assume` narrows what was verified — list every assumption.
- Miri, PBT, fuzzing: evidence on executed inputs and paths only; report coverage and budget, not "safe".

## Verify
- [ ] Each property is written in words and in the tool's language; assumptions and bounds listed.
- [ ] Non-vacuity shown: a seeded bug or reachability probe is caught by every tool used.
- [ ] Tool versions recorded; commands reproduce the result from a clean checkout.
- [ ] Counterexamples turned into regression tests; fixes re-checked with the same tool.

## Deliverables
- Files: `.tla` + `.cfg` (or Apalache configs), z3 scripts, Kani harnesses, property/stateful tests, fuzz targets with corpus and dictionary, regression tests from counterexamples.
- Report table: `| Property | Tool + version | Model/bounds/assumptions | Result (proved / verified to bound / counterexample / evidence) | Coverage (states, depth, execs, unwind) |`, plus residual risks and what remains unverified.
