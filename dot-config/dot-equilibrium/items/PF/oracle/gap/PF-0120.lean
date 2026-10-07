import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (3 : ℚ) / ((i + 2) * (i + 3)) = 3 / (i + 2) + 3 / (i + 3)) := by
  intro h
  have := h 0
  norm_num at this
