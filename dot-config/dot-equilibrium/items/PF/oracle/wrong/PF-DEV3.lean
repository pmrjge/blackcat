import Mathlib

theorem pf_dev3 : ∀ x : ℝ, 0 < x → 4 * x + 9 / x ≥ 12 := by
  have eq_gap : (4 : ℝ) * (9 / 4) + 9 / (9 / 4) = 12 := by
    norm_num
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 4 * x + 9 / x - 12 = (4 * x - 6) ^ 2 / (4 * x) := by
    field_simp
    ring
  rw [e]
  positivity
