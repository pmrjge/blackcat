import Mathlib

theorem pf_0175 : ∀ x : ℝ, x ^ 4 + x ^ 2 - 6 * x + 5 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 + x ^ 2 - 6 * x + 5 ≥ 5 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 1)]
