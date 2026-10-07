import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (2 : ℚ) / ((i + 1) * (i + 2)) = 2 / (i + 1) + 2 / (i + 2)) := by
  intro h
  have := h 0
  norm_num at this
