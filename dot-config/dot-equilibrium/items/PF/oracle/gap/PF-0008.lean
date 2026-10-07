import Mathlib

theorem eq_gap_refutation : ¬ ((-13 : ℤ) - 5 * (-2) = 3) := by
  norm_num
