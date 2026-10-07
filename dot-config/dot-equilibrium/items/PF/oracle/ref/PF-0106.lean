import Mathlib

theorem pf_0106 : ∀ x : ℝ, 0 < x → 9 * x + 1 / x ≥ 6 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 9 * x + 1 / x - 6 = (9 * x - 3) ^ 2 / (9 * x) := by
    field_simp
    ring
  rw [e]
  positivity
