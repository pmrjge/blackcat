import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, 2 * u ^ 3 - 5 * v ^ 3 ≠ 4) := by
  decide
