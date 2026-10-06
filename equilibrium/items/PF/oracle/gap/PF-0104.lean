import Mathlib

theorem eq_gap_refutation : ¬ ((1 : ℝ) * (4 / 1) + 4 / (4 / 1) = 4) := by
  norm_num
