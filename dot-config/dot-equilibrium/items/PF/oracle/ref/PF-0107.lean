import Mathlib

theorem pf_0107 : ∀ x : ℝ, 0 < x → 3 * x + 12 / x ≥ 12 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 3 * x + 12 / x - 12 = (3 * x - 6) ^ 2 / (3 * x) := by
    field_simp
    ring
  rw [e]
  positivity
