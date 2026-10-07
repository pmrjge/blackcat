import Mathlib

theorem eq_gap_refutation : ¬ ((9 : ℝ) * (1 / 9) + 1 / (1 / 9) = 6) := by
  norm_num
