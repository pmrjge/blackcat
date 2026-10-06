import Mathlib

theorem pf_0104 : ∀ x : ℝ, 0 < x → x + 4 / x ≥ 4 := by
  have eq_gap : (1 : ℝ) * (4 / 1) + 4 / (4 / 1) = 4 := by
    norm_num
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x + 4 / x - 4 = (x - 2) ^ 2 / (x) := by
    field_simp
    ring
  rw [e]
  positivity
