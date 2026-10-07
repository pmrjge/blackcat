import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (1 : ℚ) / ((i + 5) * (i + 7)) = 1 / (i + 5) - 1 / (i + 7)) := by
  intro h
  have := h 0
  norm_num at this
