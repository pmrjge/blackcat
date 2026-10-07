import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 4 + 3 * v ^ 4 ≠ 7) := by
  decide
