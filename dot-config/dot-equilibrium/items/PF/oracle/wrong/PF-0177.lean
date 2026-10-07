import Mathlib

theorem pf_0177 : ∀ x : ℝ, x ^ 4 - 4 * x ^ 2 - 4 * x + 12 > 0 := by
  have eq_gap : ∀ x : ℝ, x ^ 4 - 4 * x ^ 2 - 4 * x + 12 ≥ 12 := by
    intro x; nlinarith
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 3), sq_nonneg (x - 1)]
