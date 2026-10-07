import Mathlib

theorem pf_0173 : ∀ x : ℝ, x ^ 4 - x ^ 2 - 2 * x + 3 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 1)]
