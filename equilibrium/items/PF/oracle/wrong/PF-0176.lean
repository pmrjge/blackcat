import Mathlib

theorem pf_0176 : ∀ x : ℝ, x ^ 4 - 2 * x ^ 2 - 4 * x + 7 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - 2 * x ^ 2 - 4 * x + 7 ≥ 7 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 2), sq_nonneg (x - 1)]
