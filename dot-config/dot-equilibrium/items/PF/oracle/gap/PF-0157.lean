import Mathlib

theorem eq_gap_refutation : ¬ (∀ k : ℤ, 4 * k * (k - 1) + 6 * k + 6 + 8 * k = 4 * (k + 1) * (k + 2) + 6 * (k + 1)) := by
  intro h
  have := h 0
  norm_num at this
