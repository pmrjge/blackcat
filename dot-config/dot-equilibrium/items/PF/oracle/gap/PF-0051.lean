import Mathlib

theorem eq_gap_refutation : ¬ (∀ u v : ZMod 4, u ^ 3 + 2 * v ^ 3 ≠ 4) := by
  decide
