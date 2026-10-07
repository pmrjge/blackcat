import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (1 : ℚ) / ((i + 2) * (i + 4)) = 1 / (i + 2) - 1 / (i + 4)) := by
  intro h
  have := h 0
  norm_num at this
