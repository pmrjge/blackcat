import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, ((n + 1) + 1) ^ 2 * (2 * (n + 1) ^ 2 + 4 * (n + 1) + 1) = (n + 1) ^ 2 * (2 * n ^ 2 + 4 * n + 1) + 1 * ((2 * n + 1) ^ 3)) := by
  intro h
  have := h 0
  norm_num at this
