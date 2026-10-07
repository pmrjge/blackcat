import Mathlib

theorem pf_0111 : ∀ x : ℝ, 0 < x → x ^ 2 + 16 / x ≥ 12 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : x ^ 2 + 16 / x - 12 = (x - 2) ^ 2 * (x + 4) / x := by
    field_simp
    ring
  rw [e]
  positivity
