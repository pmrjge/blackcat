import Mathlib

theorem eq_gap_refutation : ¬ ((1 : ℝ) * (9 / 1) + 9 / (9 / 1) = 6) := by
  norm_num
