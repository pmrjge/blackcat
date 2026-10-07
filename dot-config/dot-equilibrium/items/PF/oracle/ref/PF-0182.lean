import Mathlib

theorem pf_0182 : ∀ x : ℝ, x ^ 4 - 2 * x ^ 2 - 8 * x + 14 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 3), sq_nonneg (x - 1)]
