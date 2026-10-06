import Mathlib

theorem pf_0108 : ∀ x : ℝ, 0 < x → x + 9 / x ≥ 6 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x + 9 / x - 6 = (x - 3) ^ 2 / (x) := by
    field_simp
    ring
  rw [e]
  positivity
