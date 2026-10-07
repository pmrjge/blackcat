import Mathlib

theorem pf_0113 : ∀ x : ℝ, 0 < x → 2 * x ^ 2 + 4 / x ≥ 6 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 2 * x ^ 2 + 4 / x - 6 = 2 * (x - 1) ^ 2 * (x + 2) / x := by
    field_simp
    ring
  rw [e]
  positivity
