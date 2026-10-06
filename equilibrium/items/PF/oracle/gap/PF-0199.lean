import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, 5 ^ (n + 2) = 5 ^ (n + 1) + 4 * 5 ^ n) := by
  intro h
  have := h 0
  norm_num at this
