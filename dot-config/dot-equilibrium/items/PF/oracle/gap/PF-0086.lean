import Mathlib

theorem eq_gap_refutation : ¬ (3 ^ 6 < Nat.factorial 6) := by
  decide
