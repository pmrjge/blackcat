import Mathlib

theorem pf_0178 : ∀ x : ℝ, x ^ 4 - x ^ 2 - 4 * x + 6 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 2)]
