import Mathlib

theorem eq_gap_refutation : ¬ (∀ i : ℚ, (3 : ℚ) / ((i + 4) * (i + 5)) = 3 / (i + 4) + 3 / (i + 5)) := by
  intro h
  have := h 0
  norm_num at this
