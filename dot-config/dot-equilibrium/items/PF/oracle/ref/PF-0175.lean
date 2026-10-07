import Mathlib

theorem pf_0175 : ∀ x : ℝ, x ^ 4 + x ^ 2 - 6 * x + 5 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 1)]
