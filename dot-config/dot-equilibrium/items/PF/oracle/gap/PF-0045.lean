import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, 2 * u ^ 2 + 3 * v ^ 2 ≠ 6) := by
  decide
