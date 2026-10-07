import Mathlib

theorem eq_gap_refutation : ¬ ((-6 : ℤ) - 4 * (-1) = 2) := by
  norm_num
