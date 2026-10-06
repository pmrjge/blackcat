import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (4 : ℚ) / ((i + 1) * (i + 2)) = 4 / (i + 1) + 4 / (i + 2)) := by
  intro h
  have := h 0
  norm_num at this
