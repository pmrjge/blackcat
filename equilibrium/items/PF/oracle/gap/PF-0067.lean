import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, (5 : ℤ) ∣ n ^ 4 - 1) := by
  intro h
  have := h 0
  norm_num at this
