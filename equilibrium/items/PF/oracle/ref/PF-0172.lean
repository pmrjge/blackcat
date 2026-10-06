import Mathlib

theorem pf_0172 : ∀ x : ℝ, x ^ 4 - 4 * x + 4 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 1)]
