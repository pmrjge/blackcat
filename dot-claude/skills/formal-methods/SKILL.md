---
name: formal-methods
description: Use when code or a protocol needs machine-checked assurance — choosing SMT, TLA+, Kani/Miri, property tests, fuzzing.
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

## Modules
| Module | Load when |
|---|---|
| `fm-smt-z3` | arithmetic, bit-vector or loop-invariant facts for all inputs of a fixed width (z3) |
| `fm-tla` | concurrent or distributed protocols: TLA+/PlusCal with TLC or Apalache |
| `fm-rust-kani-miri` | Rust panics, overflow, UB and memory-model bugs: Kani, Miri, loom, sanitizers |

Property-based/stateful tests and fuzzing are modules of `test-strategy`: `test-property-based`, `test-fuzzing`. Their results are evidence, not proof (§7).

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
