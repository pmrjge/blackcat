import Mathlib

theorem eq_gap_refutation : ¬ ((-2 : ℤ) - 1 * 3 = 5) := by
  norm_num
