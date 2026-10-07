import Mathlib

theorem pf_0183 : ∀ x : ℝ, x ^ 4 - 8 * x + 10 > 0 := by
  intro x
  nlinarith [sq_nonneg (x ^ 2 - 1), sq_nonneg (x - 2)]
