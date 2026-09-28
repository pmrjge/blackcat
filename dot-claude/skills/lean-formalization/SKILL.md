---
name: lean-formalization
description: Load before writing, repairing or checking Lean 4 and Mathlib code — lake projects, Mathlib cache, the Lean LSP MCP goal loop, lemma search, tactic playbook, soundness checks.
---
# Lean 4 formalization with Mathlib

## Scope and version notes
- Covers: setting up and updating Lean/Mathlib projects; formalizing statements and proofs; repairing
  broken Lean; soundness checks; CI and blueprints.
- Informal proof search and strategy: `proof-craft`. Categorical mathematics: `category-theory`.
- Checked in Sept 2026 against Lean v4.34.1 (stable), Mathlib `v4.34.1` (master was on v4.35.0-rc3),
  elan 4.2.4, Lake 5.0 and lean-lsp-mcp 0.30.0.
- Mathlib renames and deprecates constantly, so trust the compiler over memory. A deprecation warning
  names the replacement.
- Recent changes that break remembered code:
  - `push_neg` is deprecated; use `push Not`.
  - `polyrith` is gone (its Sage backend shut down); use `linear_combination` or `grobner`.
  - Bundled order classes such as `LinearOrderedField` are gone; write
    `[Field α] [LinearOrder α] [IsStrictOrderedRing α]`.
  - Concrete categories are `GrpCat`, `AddCommGrpCat`, `CommRingCat`, ….

## 1. Toolchain and projects
1. Install elan, the toolchain manager: `brew install elan-init` on macOS, or
   `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y --default-toolchain none`.
   Each project's `lean-toolchain` then selects its own Lean.
2. New project depending on Mathlib: `lake +stable new my_project math`, then `cd my_project`.
   - The `math` template writes `lean-toolchain` (e.g. `leanprover/lean4:v4.34.1`) and a
     `lakefile.toml` that requires Mathlib's tag for that toolchain:
     ```toml
     [[require]]
     name = "mathlib"
     scope = "leanprover-community"
     rev = "v4.34.1"
     ```
   - It then clones Mathlib; Mathlib's post-update hook downloads the prebuilt cache.
   - Expect about 8 GB on disk.
3. After cloning an existing project, or after any manifest change: `lake exe cache get`. It is
   idempotent; `lake exe cache get!` re-downloads every linked file.
   - If Lake starts compiling thousands of `Mathlib.*` files, stop: the toolchain does not match
     Mathlib's, or the cache is missing.
4. Commit `lean-toolchain`, `lakefile.toml` and `lake-manifest.json` together; the manifest pins exact
   commits.
5. Add `autoImplicit = false` under `[leanOptions]`, as Mathlib itself does. With the default (true), a
   typo in a signature silently becomes a universally quantified variable.
6. Check one file: `lake env lean MyProject/Foo.lean` (or `lake lean MyProject/Foo.lean`). Build the
   default targets: `lake build`.
   - In scratch files import specific modules (`import Mathlib.Analysis.SpecialFunctions.Exp`): a bare
     `import Mathlib` costs memory and load time.
   - `object file … does not exist` means the module path is wrong (or renamed), or the cache is
     incomplete.
7. Update Mathlib safely:
   1. Start from a clean git tree and note the current `lean-toolchain` and Mathlib `rev`.
   2. Set `rev` to the target tag, e.g. `"v4.35.0"`. To track master, drop `rev` and fetch the
      toolchain:
      `curl -L https://raw.githubusercontent.com/leanprover-community/mathlib4/master/lean-toolchain -o lean-toolchain`.
   3. `lake update mathlib`. Lake rewrites the manifest and bumps `lean-toolchain` to Mathlib's if that
      is newer, restarting itself through elan; Mathlib's hook then fetches the new cache.
   4. `lake build`, then fix fallout: follow the deprecation warnings, and search renamed lemmas (§3).
      Projects with an all-imports root file: `lake exe mk_all && lake build`.
   5. Commit the three files together, or `git checkout` them back if the fallout is too large.
   - Projects using leanblueprint or doc-gen update with `lake -R -Kenv=dev update`.

## 2. The working loop
**With the Lean MCP server.**
- The stack's MCP catalog has a `lean` server (lean-lsp-mcp 0.30.0) that can be mounted on demand.
  It needs elan and a built project (`lake build` first); set `LEAN_PROJECT_PATH`.
- Tools, as the server names them (a proxy may add a prefix; read the tool list after mounting):
  - Proof state and feedback: `lean_goal` (goals at line/column), `lean_term_goal`,
    `lean_diagnostic_messages`, `lean_hover_info`, `lean_code_actions` (returns "Try this" edits;
    it does not apply them).
  - Trying things: `lean_multi_attempt` (several tactics at one position), `lean_run_code` (standalone
    snippet).
  - Navigation: `lean_file_outline`, `lean_declaration_file`, `lean_references`, `lean_completions`.
  - Search:
    - `lean_local_search` (ripgrep over the project and its dependencies; confirms a name exists);
    - remote search, rate-limited per tool (per 30 s: `lean_loogle` 3, `lean_state_search` and
      `lean_hammer_premise` 6, `lean_leanfinder` 10, `lean_leansearch` 90).
  - Project-level: `lean_verify` (axioms plus a scan for `unsafe` or `debug.*` options),
    `lean_minimal_hypotheses` (which hypotheses are load-bearing), `lean_profile_proof`, `lean_build`.

**Without it.** Edit the file, run `lake env lean F.lean 2>&1 | head -60`, fix the first error only,
and repeat. `extract_goal` prints the current goal as a standalone theorem.

**Rhythm.**
1. State the theorem with `:= by sorry` and compile. It must elaborate: this checks the types.
2. Write the skeleton: `have h₁ : … := by sorry`, `suffices h : … by …`, `calc` steps.
3. Fill one leaf at a time, recompiling after each.
4. Finish with no `sorry` anywhere.

## 3. Finding lemmas
- Naming convention: the name describes the statement, conclusion first.
  - `mul_comm`, `add_le_add`, `Finset.sum_range_succ`; `_iff` for ↔.
  - `lt_of_le_of_lt` for a ≤ b → b < c → a < c.
  - Suffixes: `_left/_right`, `_pos/_nonneg`, `_mono`, `_injective`, `_self`, `_zero/_one`.
- Case and dot notation:
  - Theorems in snake_case, types and structures in UpperCamelCase, defs in lowerCamelCase.
  - Dot notation on hypotheses: `h.le`, `h.trans h'`, `hf.comp hg`, `h.symm`.
- In-editor search:
  - Goal-directed: `exact?`, `apply?`, `rw?`, `hint` (runs a battery of tactics).
  - `simp?` prints a `simp only [...]`; paste it, since it is faster and robust to library changes.
  - Lookup: `#check @name`, `#print name`, `#help tactic gcongr`, `#synth Field ℝ`.
  - Remote (LeanSearchClient, bundled with Mathlib): `#loogle …`, `#leansearch "…"`, and the tactic
    `#statesearch` inside a proof.
- Web search engines:
  - Loogle (loogle.lean-lang.org): patterns such as `Real.sin`, `_ * (_ ^ _)`,
    `|- tsum _ = _ * tsum _`.
  - LeanSearch (leansearch.net): natural language.
  - Lean Finder: informal statements and proof states.
  - Mathlib docs: leanprover-community.github.io/mathlib4_docs.
  - Moogle is no longer wired into Mathlib's search client.
- Search indexes can lag the project's Mathlib: confirm every name with `#check` in the project.

## 4. Tactic playbook by goal shape
| Goal | First try | Notes |
|---|---|---|
| ring identity | `ring`; `ring_nf` to normalize | treats x⁻¹ as an atom: if cancellation needs x ≠ 0, `field_simp` first |
| consequence of equations | `linear_combination (a+b) * h₁ - 2 * h₂`; `grobner` | `grobner` finds the combination itself |
| field identity with `/` | `field_simp` then `ring` | needs `x ≠ 0` facts in context |
| linear (in)equality | `linarith`, `linarith [sq_nonneg (a-b)]` | ordered fields, ℤ; hypotheses must be linear |
| nonlinear inequality | `nlinarith [sq_nonneg (a-b), mul_pos ha hb]` | supply the products it needs |
| `0 < e`, `0 ≤ e`, `e ≠ 0` | `positivity` | syntactic; fails on differences |
| monotone bound | `gcongr` (`f a ≤ f b` from `a ≤ b`), `bound` | side goals go to `positivity` |
| order facts | `order` | uses only order hypotheses |
| ℕ/ℤ arithmetic incl. `-`, `/`, `%` by constants | `omega` | linear only; no casts to ℝ |
| numerals, `Nat.Prime 97` | `norm_num`, `norm_num [f]` | `decide` for small decidable props |
| heavy decidable computation | `decide +kernel` | `native_decide` adds an axiom (§10) |
| casts ℕ→ℤ→ℚ→ℝ | `push_cast`, `norm_cast`, `exact_mod_cast h` | `zify [h]`, `qify`, `rify`, `lift x to ℕ using hx` |
| groups, modules | `abel`, `group`, `module`, `noncomm_ring` | |
| propositional / first-order glue | `tauto`, `aesop`, `simp_all`, `grind` | `grind`: congruence closure plus arithmetic, in core |
| continuity, measurability, differentiability | `fun_prop`; `continuity`, `measurability` | try `fun_prop` first; the other two are aesop-based and slower |
| rewriting | `rw [h, ← h']`, `nth_rw 2 [h]`, `rwa`, `conv_lhs => rw [h]`, `simp only [h] at h' ⊢`, `simpa using h` | non-terminal bare `simp` is fragile |
| ∧, ∃, ↔, extensionality | `constructor`, `refine ⟨?_, ?_⟩`, `use x`, `ext x`, `funext x`, `congr 1`, `congr!` | `convert h using 2` leaves the differences as goals |
| unpack hypotheses | `obtain ⟨x, hx, rfl⟩ := h`, `rintro ⟨-, hq⟩`, `choose f hf using h` | `set y := e with hy`, `generalize`, `subst`, `apply_fun f at h` |
| negation, contradiction | `by_contra h`, `by_contra! h`, `push Not at h ⊢`, `contrapose! h`, `exfalso` | |
| case analysis | `rcases` (below), `interval_cases x`, `fin_cases x`, `split_ifs with h`, `wlog h : x ≤ y generalizing x y` | |
| induction | structured `induction … with` (below) | |
| filters, eventually | `filter_upwards [h₁, h₂] with x hx₁ hx₂` | |
| sanity-test a statement | `plausible` | random testing; proves nothing and leaves a `sorry` |

Syntax for the rows marked "below" (all checked against Mathlib v4.34.1):
```lean
rcases h with h₁ | h₂                                         -- disjunction
induction n with
  | zero => simp
  | succ k ih => rw [Finset.sum_range_succ, mul_add, ih]; ring
induction n using Nat.strong_induction_on with
  | _ n ih => exact step n ih                                 -- ih : ∀ m < n, P m
induction n, hn using Nat.le_induction with                   -- hn : m ≤ n
  | base => norm_num
  | succ k hk ih => nlinarith
```

## 5. Proof structure
- Build a sorry-first skeleton: `have`, `suffices … by`, `show` (restate the goal up to defeq), `calc`.
  Extract a lemma when a `have` exceeds about 10 lines or is reused.
- State lemmas at the right generality, e.g. an ordered field instead of `ℝ` when nothing
  real-specific is used:
  `variable {α : Type*} [Field α] [LinearOrder α] [IsStrictOrderedRing α]`.
  Do not over-generalize into hard typeclass problems.
- Keep proofs robust:
  - Use `simp only [...]` rather than a non-terminal `simp`.
  - Name hypotheses (`intro x hx`, `rename_i`), and never rely on auto-names like `h✝`.
  - Prefer `obtain` patterns over index juggling.
- `theorem`/`lemma` for propositions, `def` for data, `example` for tests; `private` for local helpers.

## 6. Definitions and statement faithfulness
- Kinds of declaration:
  - `def` is computable by default; mark it `noncomputable` when it uses choice or real-number limits
    (Lean says so).
  - `abbrev` is reducible.
  - `structure` gets projections; add `@[ext]` for extensionality.
  - `class` and `instance` hook into the typeclass hierarchy. Extend existing Mathlib classes rather than
    creating parallel ones: parallel classes cause instance diamonds.
- Search Mathlib before defining anything. A new definition needs a small API: basic `@[simp]` lemmas,
  ext lemmas, and `example`s showing it behaves as intended on small inputs (`#eval`, `decide`).
- Junk values make formal statements true for silly reasons:
  - `x / 0 = 0`, `Real.sqrt x = 0` for x ≤ 0, `Real.log 0 = 0`;
  - ℕ subtraction truncates (`2 - 5 = 0`) and ℕ division floors;
  - ℤ division rounds toward −∞ for a positive divisor (`(-7 : ℤ) / 2 = -4`).

  Carry the informal side conditions (`x ≠ 0`, `0 ≤ x`, `b ≤ a`) into the formal statement.
- Faithfulness check, the main risk in formalization:
  - Compare the Lean statement with the informal one, quantifier by quantifier.
  - Show the hypotheses are satisfiable by building an instance.
  - Check that a deliberately false variant fails.
  - Unused-variable warnings on hypotheses are a red flag.

## 7. Common errors and fixes
| Message | Usual cause | Fix |
|---|---|---|
| `failed to synthesize <Class>` | missing import or instance; wrong type (ℕ vs ℝ); needs `[Fact p.Prime]` | `#synth`; `set_option trace.Meta.synthInstance true in`; add the import or assumption |
| type mismatch with `↑` | cast in the wrong place: `((a - b : ℕ) : ℝ)` ≠ `(a : ℝ) - b` | annotate `(2 : ℝ)`, `(n : ℝ)`; `push_cast [h]` |
| numeral elaborated in ℕ | a numeral with no expected type defaults to ℕ | type ascription on the first occurrence: `(2 : ℝ)` |
| `motive is not type correct` (`rw`) | the rewritten term appears in a dependent type, e.g. `x : Fin n` when rewriting `n` | `subst h` / `cases h` (variable = term), `simp only [h]`, `conv`, `nth_rw` |
| `(deterministic) timeout … maxHeartbeats` | default 200000 exceeded: large `simp` sets, `decide`, typeclass loops | first make the proof cheaper (`simp only`, split lemmas); then `set_option maxHeartbeats 400000 in` before the declaration |
| `maximum recursion depth` | huge terms or numerals under `decide`/`rfl` | `norm_num`, restructure, `set_option maxRecDepth N in` |
| universe errors | `Type u` vs `Type*` mismatch; category `Category.{v, u}` | make universes explicit; `ULift`; match `HasLimitsOfSize.{w, w}` |
| `unknown identifier` / `unknown constant` | renamed lemma or missing import | `lean_local_search`, `#check`, deprecation messages |
| `Ambiguous term` | e.g. `Monad` under `open CategoryTheory` | qualify: `CategoryTheory.Monad` |
| `linarith failed`, `simp made no progress` | goal not in normal form; missing fact | `push_cast`, `ring_nf at *`, supply the product or lemma explicitly |

## 8. Category theory in Mathlib
- Location and names:
  - `open CategoryTheory`; sources under `Mathlib/CategoryTheory/`.
  - Concrete categories: `GrpCat`, `AddCommGrpCat`, `CommGrpCat`, `MonCat`, `RingCat`, `CommRingCat`,
    `ModuleCat R` (in `Mathlib/Algebra/Category/`); `TopCat`; `Cat`.
  - `Type u` is a category whose morphisms are functions.
- Scoped notation:
  - Morphisms: `X ⟶ Y`; composition `f ≫ g` in diagrammatic order (first `f`); `𝟙 X`.
  - Functors: `C ⥤ D`; composition `F ⋙ G` (first `F`); identity `𝟭 C`; opposite `Cᵒᵖ`.
  - Natural transformations: `α : F ⟶ G`, with `α.app X` and `α.naturality f`.
  - Isomorphisms: `X ≅ Y`, with `e.hom`, `e.inv`, `e.hom_inv_id`.
  - Adjunctions: `F ⊣ G`, with `adj.unit`, `adj.counit`, `adj.homEquiv X Y`,
    `adj.left_triangle_components`.
- Yoneda: `yoneda : C ⥤ Cᵒᵖ ⥤ Type v`, `yonedaEquiv`, `Yoneda.fullyFaithful`.
- Limits (`open CategoryTheory.Limits`):
  - `limit F`, `HasLimit F`, `IsLimit c`, `pullback f g`.
  - `Adjunction.rightAdjoint_preservesLimits`, `Adjunction.leftAdjoint_preservesColimits`.
  - Adjoint functor theorems in `Adjunction/AdjointFunctorTheorems.lean`.
- Monads: `CategoryTheory.Monad`, `Monad.Algebra`, `Kleisli`, `Adjunction.toMonad`
  (`Monad/Adjunction.lean`).
- Monoidal (`open MonoidalCategory`): `X ⊗ Y`, `f ⊗ₘ g`, whiskering `X ◁ f` and `f ▷ Y`, `𝟙_ C`,
  `α_ X Y Z`, `λ_ X`, `ρ_ X`.
- Automation: `simp` with `@[reassoc]` lemmas, `ext`, `aesop_cat`. `cat_disch` discharges category
  auto-params. `erw` is occasionally needed across defeq-but-not-syntactic forms.
- Universes: `Category.{v, u} C` has objects in `Type u` and homs in `Type v`; `SmallCategory` and
  `LargeCategory` are the two standard cases.

## 9. Larger projects
- Blueprint:
  - Install with `uv tool install leanblueprint`; needs graphviz and libgraphviz-dev for pygraphviz.
  - Commands: `leanblueprint new`, then `pdf` | `web` | `checkdecls` | `all` | `serve`.
  - In the LaTeX, tag each node with `\lean{Decl.name}`, `\leanok`, `\uses{label}`, `\notready`,
    `\mathlibok`. The dependency graph tracks progress.
- CI: the `math` template already writes `.github/workflows/lean_action_ci.yml` (`actions/checkout`,
  then `leanprover/lean-action@v1`). It auto-detects Mathlib and its cache; inputs include `build`,
  `test`, `lint`, `mk_all-check`, `leanchecker`.
- Hygiene: `lake shake` reports unused imports (`--fix` applies the changes), `#min_imports` gives the
  minimal imports for a file, and one concept per file.

## 10. Verify (soundness)
- [ ] Clean build: `rm -rf .lake/build && lake build` succeeds with no errors. Warnings are reviewed.
- [ ] No `sorry` or `admit`: `grep -rnE '\bsorry\b|\badmit\b' --include='*.lean' --exclude-dir=.lake .`,
      and no "declaration uses `sorry`" in the build output.
- [ ] `#print axioms MainTheorem` lists only `propext`, `Classical.choice`, `Quot.sound`.
  - `sorryAx` means an unfinished proof.
  - An extra `…native_decide.ax…` axiom means `native_decide` was used.
  - Any project `axiom` needs explicit justification.
- [ ] No `set_option debug.skipKernelTC`, `unsafe` or `@[implemented_by]` in proof-relevant code
      (`lean_verify` scans for these).
- [ ] Kernel replay: `lake env leanchecker` (current project) or `lake env leanchecker MyProject.Foo`
      (module prefix). It is silent on success. It detects environment hacking; it is not an
      independent checker.
- [ ] Statement faithfulness reviewed (§6). `lean_minimal_hypotheses` confirms each hypothesis is
      load-bearing, or the redundancy is explained.

## Deliverables
- The building project: `.lean` files, `lean-toolchain`, `lakefile.toml`, `lake-manifest.json`.
- A table mapping each informal statement to its Lean declaration name and file.
- `#print axioms` output for the main results, plus the Lean and Mathlib versions.
- Any remaining `sorry` or deviation from the informal statement, listed with its reason.
