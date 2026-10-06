import Mathlib

theorem pf_0111 : ∀ x : ℝ, 0 < x → x ^ 2 + 16 / x ≥ 12 := by
  have eq_gap : ∀ x : ℝ, 0 < x → 2 * 1 * x - 16 / x ^ 2 = 0 → x ^ 3 = 16 / 1 := by
    intro x hx h; field_simp at h; nlinarith
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x ^ 2 + 16 / x - 12 = (x - 2) ^ 2 * (x + 4) / x := by
    field_simp
    ring
  rw [e]
  positivity
