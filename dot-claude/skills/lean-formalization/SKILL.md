---
name: lean-formalization
description: Load for Lean 4 and Mathlib — lake projects, Mathlib cache, the Lean LSP goal loop, lemma search, tactics, statement faithfulness.
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
Read `references/toolchain-projects.md` when installing elan, creating or updating a lake project, or fetching the Mathlib cache.


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
Read `references/tactic-playbook.md` when choosing a tactic for a goal (table by goal shape, first try, notes).

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
Read `references/common-errors.md` when Lean reports an error you don't immediately understand (message → cause → fix table).

## 8. Category theory in Mathlib
Read `references/category-theory-mathlib.md` when formalizing category theory (Mathlib locations, names, notation, automation).

## 9. Larger projects
Read `references/larger-projects.md` when a formalization spans many files (blueprints, file layout, imports).

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
