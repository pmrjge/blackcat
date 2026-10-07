import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 2 + 5 * v ^ 2 ≠ 8) := by
  decide
