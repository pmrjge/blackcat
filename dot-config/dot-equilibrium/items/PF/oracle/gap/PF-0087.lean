import Mathlib

theorem eq_gap_refutation : ¬ (4 ^ 8 < Nat.factorial 8) := by
  decide
