import Mathlib

theorem pf_0019 : ∀ a b : ℝ, a + b = 6 → a * b = 4 → a ^ 5 + b ^ 5 = 3936 := by
  intro a b h1 h2
  have e : a ^ 5 + b ^ 5 = (a + b) ^ 5 - 5 * (a + b) ^ 3 * (a * b) + 5 * (a + b) * (a * b) ^ 2 := by ring
  rw [e, h1, h2]
  norm_num
