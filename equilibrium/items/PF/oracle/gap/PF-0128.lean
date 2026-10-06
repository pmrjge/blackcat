import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (1 : ℚ) / ((i + 3) * (i + 5)) = 1 / (i + 3) - 1 / (i + 5)) := by
  intro h
  have := h 0
  norm_num at this
