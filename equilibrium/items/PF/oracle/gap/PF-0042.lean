import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 2 + v ^ 2 ≠ 6) := by
  decide
