import Mathlib

theorem eq_gap_refutation : ¬ (6 ^ 13 < Nat.factorial 13) := by
  decide
