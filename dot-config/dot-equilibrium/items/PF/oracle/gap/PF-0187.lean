import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 4 - 8 * x + 9 ≥ 9) := by
  intro h
  have := h 1
  norm_num at this
