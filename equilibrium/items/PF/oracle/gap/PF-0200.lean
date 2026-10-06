import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, 7 ^ (n + 2) = 7 ^ (n + 1) + 6 * 7 ^ n) := by
  intro h
  have := h 0
  norm_num at this
