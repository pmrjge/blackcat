import Mathlib

theorem eq_gap_refutation : ¬ ((-1 : ℤ) - 5 * 4 = 21) := by
  norm_num
