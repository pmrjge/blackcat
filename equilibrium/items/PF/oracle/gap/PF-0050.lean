import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 3 + v ^ 3 ≠ 3) := by
  decide
