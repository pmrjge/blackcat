import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, 3 ^ (n + 2) = 3 ^ (n + 1) + 2 * 3 ^ n) := by
  intro h
  have := h 0
  norm_num at this
