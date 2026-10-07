import Mathlib

theorem pf_0016 : ∀ a b : ℝ, a + b = 5 → a * b = 3 → a ^ 3 + b ^ 3 = 80 := by
  intro a b h1 h2
  have e : a ^ 3 + b ^ 3 = (a + b) ^ 3 - 3 * (a + b) * (a * b) := by ring
  rw [e, h1, h2]
  norm_num
