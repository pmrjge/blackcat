import Mathlib

theorem pf_0116 : ∀ x : ℝ, 0 < x → 2 * x ^ 2 + 108 / x ≥ 54 := by
  have eq_gap : ∀ x : ℝ, 0 < x → 2 * 2 * x - 108 / x ^ 2 = 0 → x ^ 3 = 108 / 2 := by
    intro x hx h; field_simp at h; nlinarith
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 2 * x ^ 2 + 108 / x - 54 = 2 * (x - 3) ^ 2 * (x + 6) / x := by
    field_simp
    ring
  rw [e]
  positivity
