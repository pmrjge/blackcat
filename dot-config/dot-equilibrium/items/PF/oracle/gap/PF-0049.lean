import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 2 - 7 * v ^ 2 ≠ 5) := by
  decide
