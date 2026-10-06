import Mathlib

theorem pf_0180 : ∀ x : ℝ, x ^ 4 + 2 * x ^ 2 - 8 * x + 6 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 1)]
