import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℕ, Nat.factorial (n + 2) = Nat.factorial (n + 1) + n * Nat.factorial n) := by
  intro h
  have := h 0
  norm_num at this
