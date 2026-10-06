import Mathlib

theorem pf_0187 : ∀ x : ℝ, x ^ 4 - 8 * x + 9 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - 8 * x + 9 ≥ 9 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 2), sq_nonneg (x - 1)]
