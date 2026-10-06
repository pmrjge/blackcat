import Mathlib

theorem eq_gap_refutation : ¬ (199 ^ 2 = 11 * 30 ^ 2 + 1) := by
  norm_num
