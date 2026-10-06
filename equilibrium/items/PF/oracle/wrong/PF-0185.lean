import Mathlib

theorem pf_0185 : ∀ x : ℝ, x ^ 4 - 5 * x ^ 2 - 2 * x + 11 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - 5 * x ^ 2 - 2 * x + 11 ≥ 11 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 3), sq_nonneg (x - 1)]
