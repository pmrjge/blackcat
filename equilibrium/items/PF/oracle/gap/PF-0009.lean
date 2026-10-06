import Mathlib

theorem eq_gap_refutation : ¬ ((-16 : ℤ) - (-2) * 3 = 10) := by
  norm_num
