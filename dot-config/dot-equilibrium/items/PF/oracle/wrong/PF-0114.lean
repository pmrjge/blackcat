import Mathlib

theorem pf_0114 : ∀ x : ℝ, 0 < x → 3 * x ^ 2 + 48 / x ≥ 36 := by
  have eq_gap : ∀ x : ℝ, 0 < x → 2 * 3 * x - 48 / x ^ 2 = 0 → x ^ 3 = 48 / 3 := by
    intro x hx h; field_simp at h; nlinarith
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 3 * x ^ 2 + 48 / x - 36 = 3 * (x - 2) ^ 2 * (x + 4) / x := by
    field_simp
    ring
  rw [e]
  positivity
