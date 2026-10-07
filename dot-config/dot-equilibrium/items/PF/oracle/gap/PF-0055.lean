import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, 2 * u ^ 4 + 5 * v ^ 4 ≠ 8) := by
  decide
