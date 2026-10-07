import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, (11 : ℤ) ∣ n ^ 10 - 1) := by
  intro h
  have := h 0
  norm_num at this
