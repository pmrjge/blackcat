import Mathlib

theorem eq_gap_refutation : ¬ (5 ^ 11 < Nat.factorial 11) := by
  decide
