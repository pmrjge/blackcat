import Mathlib

theorem pf_0115 : ∀ x : ℝ, 0 < x → x ^ 2 + 2 / x ≥ 3 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x ^ 2 + 2 / x - 3 = (x - 1) ^ 2 * (x + 2) / x := by
    field_simp
    ring
  rw [e]
  positivity
