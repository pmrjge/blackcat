import Mathlib

theorem pf_0110 : ∀ x : ℝ, 0 < x → 5 * x + 20 / x ≥ 20 := by
  have eq_gap : (5 : ℝ) * (20 / 5) + 20 / (20 / 5) = 20 := by
    norm_num
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 5 * x + 20 / x - 20 = (5 * x - 10) ^ 2 / (5 * x) := by
    field_simp
    ring
  rw [e]
  positivity
