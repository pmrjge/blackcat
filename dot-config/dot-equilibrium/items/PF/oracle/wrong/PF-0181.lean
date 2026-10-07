import Mathlib

theorem pf_0181 : ∀ x : ℝ, x ^ 4 - 3 * x ^ 2 + 2 * x + 6 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - 3 * x ^ 2 + 2 * x + 6 ≥ 6 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 2), sq_nonneg (x + 1)]
