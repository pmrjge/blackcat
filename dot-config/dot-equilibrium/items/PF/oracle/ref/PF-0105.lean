import Mathlib

theorem pf_0105 : ∀ x : ℝ, 0 < x → 2 * x + 8 / x ≥ 8 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 2 * x + 8 / x - 8 = (2 * x - 4) ^ 2 / (2 * x) := by
    field_simp
    ring
  rw [e]
  positivity
