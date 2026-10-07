import Mathlib

theorem pf_0115 : ∀ x : ℝ, 0 < x → x ^ 2 + 2 / x ≥ 3 := by
  have eq_gap : ∀ x : ℝ, 0 < x → 2 * 1 * x - 2 / x ^ 2 = 0 → x ^ 3 = 2 / 1 := by
    intro x hx h; field_simp at h; nlinarith
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x ^ 2 + 2 / x - 3 = (x - 1) ^ 2 * (x + 2) / x := by
    field_simp
    ring
  rw [e]
  positivity
