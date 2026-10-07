import Mathlib

theorem pf_0114 : ∀ x : ℝ, 0 < x → 3 * x ^ 2 + 48 / x ≥ 36 := by
  intro x hx
  rw [ge_iff_le, ← sub_nonneg]
  have e : 3 * x ^ 2 + 48 / x - 36 = 3 * (x - 2) ^ 2 * (x + 4) / x := by
    field_simp
    ring
  rw [e]
  positivity
