import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 2 + 3 * v ^ 2 ≠ 15) := by
  decide
