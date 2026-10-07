import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, ((n : ℤ) + 1) ^ 2 * (((n : ℤ) + 1) + 1) ^ 2 * (2 * ((n : ℤ) + 1) ^ 2 + 2 * ((n : ℤ) + 1) - 1) = (n : ℤ) ^ 2 * ((n : ℤ) + 1) ^ 2 * (2 * (n : ℤ) ^ 2 + 2 * (n : ℤ) - 1) + 12 * ((n : ℤ) ^ 5)) := by
  intro h
  have := h 0
  norm_num at this
