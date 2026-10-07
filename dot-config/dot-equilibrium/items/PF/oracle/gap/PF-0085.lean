import Mathlib

theorem eq_gap_refutation : ¬ (2 ^ 3 < Nat.factorial 3) := by
  decide
