import Mathlib

theorem pf_dev3 : ∀ x : ℝ, 0 < x → 4 * x + 9 / x ≥ 12 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 4 * x + 9 / x - 12 = (4 * x - 6) ^ 2 / (4 * x) := by
    field_simp
    ring
  rw [e]
  positivity
