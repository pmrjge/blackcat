import Mathlib

theorem pf_0024 : ∀ a b : ℝ, a + b = 3 → a * b = 1 → a ^ 7 + b ^ 7 = 843 := by
  intro a b h1 h2
  have e : a ^ 7 + b ^ 7 = (a + b) ^ 7 - 7 * (a + b) ^ 5 * (a * b) + 14 * (a + b) ^ 3 * (a * b) ^ 2 - 7 * (a + b) * (a * b) ^ 3 := by ring
  rw [e, h1, h2]
  norm_num
