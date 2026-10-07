import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, (n + 1) * ((n + 1) + 1) * (2 * (n + 1) + 1) = n * (n + 1) * (2 * n + 1) + 6 * (n ^ 2)) := by
  intro h
  have := h 0
  norm_num at this
