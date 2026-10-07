import Mathlib

theorem eq_gap_refutation : ¬ ((4 : ℝ) * (9 / 4) + 9 / (9 / 4) = 12) := by
  norm_num
