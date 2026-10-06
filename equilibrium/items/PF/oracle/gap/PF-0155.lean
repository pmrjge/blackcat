import Mathlib

theorem eq_gap_refutation : ¬ (∀ k : ℤ, 6 * k * (k - 1) + 2 * k + 2 + 12 * k = 6 * (k + 1) * (k + 2) + 2 * (k + 1)) := by
  intro h
  have := h 0
  norm_num at this
