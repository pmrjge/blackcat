import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (2 : ℚ) / ((i + 3) * (i + 4)) = 2 / (i + 3) + 2 / (i + 4)) := by
  intro h
  have := h 0
  norm_num at this
