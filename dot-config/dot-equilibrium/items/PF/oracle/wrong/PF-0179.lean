import Mathlib

theorem pf_0179 : ∀ x : ℝ, x ^ 4 - x ^ 2 - 6 * x + 8 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - x ^ 2 - 6 * x + 8 ≥ 8 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 2), sq_nonneg (x - 1)]
