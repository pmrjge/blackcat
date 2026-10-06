import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, ((n : ℤ) + 1) * (((n : ℤ) + 1) + 1) * (2 * ((n : ℤ) + 1) + 1) * (3 * ((n : ℤ) + 1) ^ 2 + 3 * ((n : ℤ) + 1) - 1) = (n : ℤ) * ((n : ℤ) + 1) * (2 * (n : ℤ) + 1) * (3 * (n : ℤ) ^ 2 + 3 * (n : ℤ) - 1) + 30 * ((n : ℤ) ^ 4)) := by
  intro h
  have := h 0
  norm_num at this
