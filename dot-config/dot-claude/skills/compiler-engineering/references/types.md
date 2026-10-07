# Name resolution and type systems

Baseline: `compiler-engineering`. Formal proofs of soundness: `lean-formalization`, `proof-craft`; property-based tests: `test-property-based`.

## Name resolution
- Separate pass producing a resolved tree: each use points to a definition ID; scopes as a stack or tree; shadowing rules written down.
- Modules and imports: build the module graph first, detect cycles explicitly, resolve globs after explicit imports; report unused and ambiguous imports.
- Hygiene for macros: identifiers carry syntax contexts so macro-introduced bindings don't capture user names.

## Choosing the type-checking style
| language | approach |
|---|---|
| ML/Haskell-style, few annotations | Hindley–Milner (Algorithm W/J) with let-polymorphism and value restriction |
| richer features (higher-rank, subtyping, GADTs) | bidirectional type checking: check against known types, infer where possible, annotations at boundaries |
| traits/typeclasses | constraint generation + solving (dictionary passing or monomorphization), coherence/orphan rules |
| gradual or optional typing | consistency relation, runtime checks at boundaries |
| dependent types | normalization by evaluation, conversion checking, elaboration with metavariables |

## Implementation rules
- Unification with union–find over type variables; occurs check (or deliberately infinite types); levels or ranks for efficient generalization.
- Constraint-based checking separates generation from solving: better errors (you can choose which constraint to blame) and easier extension.
- Elaborate to an explicitly typed core IR (System F-like or monomorphic) — later phases never re-infer.
- Generics: decide monomorphization (fast code, code size) vs dictionary passing/boxing (compile speed, separate compilation); document the choice.
- Subtyping and variance declared per type constructor; check variance of user definitions.
- Exhaustiveness and redundancy checking for pattern matches (Maranget's usefulness algorithm).
- Integer and float types: overflow semantics and implicit conversions (or their absence) specified.

## Error messages
- Report the expected vs found type with where each expectation came from (secondary spans); avoid leaking internal type variables (`'a12`) — name them or show placeholders.
- Stop cascades: an `Error` type that unifies with everything silently.

## Soundness testing
- Property tests: well-typed generated programs run without stuck states in the reference interpreter (progress + preservation, empirically); generators for well-typed terms (QuickCheck/hypothesis/proptest).
- Regression corpus of known-unsound programs from similar languages (variance holes, mutable references with polymorphism, recursive types).
- Formalize the core calculus (Lean/Coq/PLT Redex) when soundness matters enough to prove.

## Pitfalls
Generalizing over variables that escape into the environment; missing value restriction with mutable references; unification without occurs check looping; type errors reported at the wrong location; inference order dependence; trait resolution that is non-terminating without limits.

## Verify
Golden tests for accepted and rejected programs (with diagnostics) · property-based soundness tests run with the reference interpreter · exhaustiveness checker tests including nested patterns · performance check on large generated inputs (no exponential blowups beyond known HM worst cases).
