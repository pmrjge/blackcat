import Mathlib

theorem pf_0022 : ∀ a b : ℝ, a + b = 1 → a * b = -3 → a ^ 6 + b ^ 6 = 154 := by
  have eq_gap : ∀ a b : ℝ, a ^ 6 + b ^ 6 = (a + b) ^ 6 - 6 * (a + b) ^ 4 * (a * b) + 9 * (a + b) ^ 2 * (a * b) ^ 2 - 3 * (a * b) ^ 3 := by
    intro a b; ring
  intro a b h1 h2
  have e : a ^ 6 + b ^ 6 = (a + b) ^ 6 - 6 * (a + b) ^ 4 * (a * b) + 9 * (a + b) ^ 2 * (a * b) ^ 2 - 2 * (a * b) ^ 3 := by ring
  rw [e, h1, h2]
  norm_num
