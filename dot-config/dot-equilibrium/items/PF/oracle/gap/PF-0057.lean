import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, 5 * u ^ 2 + 7 * v ^ 2 ≠ 15) := by
  decide
