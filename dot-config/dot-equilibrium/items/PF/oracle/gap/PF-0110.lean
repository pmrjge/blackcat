import Mathlib

theorem eq_gap_refutation : ¬ ((5 : ℝ) * (20 / 5) + 20 / (20 / 5) = 20) := by
  norm_num
