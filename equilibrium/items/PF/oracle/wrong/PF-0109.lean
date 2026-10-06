import Mathlib

theorem pf_0109 : ∀ x : ℝ, 0 < x → 4 * x + 25 / x ≥ 20 := by
  have eq_gap : (4 : ℝ) * (25 / 4) + 25 / (25 / 4) = 20 := by
    norm_num
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 4 * x + 25 / x - 20 = (4 * x - 10) ^ 2 / (4 * x) := by
    field_simp
    ring
  rw [e]
  positivity
