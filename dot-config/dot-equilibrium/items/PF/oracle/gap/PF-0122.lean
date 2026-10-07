import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (5 : ℚ) / ((i + 1) * (i + 2)) = 5 / (i + 1) + 5 / (i + 2)) := by
  intro h
  have := h 0
  norm_num at this
