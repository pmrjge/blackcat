import Mathlib

theorem pf_0015 : ∀ a b : ℝ, a + b = 5 → a * b = 3 → a ^ 4 + b ^ 4 = 343 := by
  intro a b h1 h2
  have e : a ^ 4 + b ^ 4 = (a + b) ^ 4 - 4 * (a + b) ^ 2 * (a * b) + 2 * (a * b) ^ 2 := by ring
  rw [e, h1, h2]
  norm_num
