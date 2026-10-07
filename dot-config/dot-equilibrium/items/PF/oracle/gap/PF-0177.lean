import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 4 - 4 * x ^ 2 - 4 * x + 12 ≥ 12) := by
  intro h
  have := h 1
  norm_num at this
