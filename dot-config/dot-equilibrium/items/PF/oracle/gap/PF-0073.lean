import Mathlib

theorem eq_gap_refutation : ¬ (∀ n : ℤ, (13 : ℤ) ∣ n ^ 12 - 1) := by
  intro h
  have := h 0
  norm_num at this
