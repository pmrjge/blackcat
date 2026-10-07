import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 4 + v ^ 4 ≠ 4) := by
  decide
