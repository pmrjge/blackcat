import Mathlib

theorem pf_0112 : ∀ x : ℝ, 0 < x → x ^ 2 + 54 / x ≥ 27 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x ^ 2 + 54 / x - 27 = (x - 3) ^ 2 * (x + 6) / x := by
    field_simp
    ring
  rw [e]
  positivity
