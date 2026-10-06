import Mathlib

theorem pf_0023 : ∀ a b : ℝ, a + b = 4 → a * b = 2 → a ^ 6 + b ^ 6 = 1584 := by
  intro a b h1 h2
  have e : a ^ 6 + b ^ 6 = (a + b) ^ 6 - 6 * (a + b) ^ 4 * (a * b) + 9 * (a + b) ^ 2 * (a * b) ^ 2 - 2 * (a * b) ^ 3 := by ring
  rw [e, h1, h2]
  norm_num
