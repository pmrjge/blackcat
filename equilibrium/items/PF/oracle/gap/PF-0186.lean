import Mathlib

theorem eq_gap_refutation : ¬ (∀ x : ℝ, x ^ 4 + x ^ 2 + 6 * x + 6 ≥ 6) := by
  intro h
  have := h (-1)
  norm_num at this
