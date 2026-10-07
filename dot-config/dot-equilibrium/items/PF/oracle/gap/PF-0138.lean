import Mathlib

theorem eq_gap_refutation : ¬ (132 ^ 2 = 15 * 63 ^ 2 + 1) := by
  norm_num
