import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, 3 * u ^ 2 - 5 * v ^ 2 ≠ 4) := by
  decide
