import Mathlib

theorem pf_0026 : ∀ a b : ℝ, a + b = 2 → a * b = -1 → a ^ 7 + b ^ 7 = 478 := by
  have eq_gap : ∀ a b : ℝ, a ^ 7 + b ^ 7 = (a + b) ^ 7 - 7 * (a + b) ^ 5 * (a * b) + 14 * (a + b) ^ 3 * (a * b) ^ 2 - 8 * (a + b) * (a * b) ^ 3 := by
    intro a b; ring
  intro a b h1 h2
  have e : a ^ 7 + b ^ 7 = (a + b) ^ 7 - 7 * (a + b) ^ 5 * (a * b) + 14 * (a + b) ^ 3 * (a * b) ^ 2 - 7 * (a + b) * (a * b) ^ 3 := by ring
  rw [e, h1, h2]
  norm_num
