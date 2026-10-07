import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, (3 : ℤ) ∣ n ^ 2 - 1) := by
  intro h
  have := h 0
  norm_num at this
