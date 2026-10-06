import Mathlib

theorem pf_0027 : ∀ a b : ℝ, a + b = 6 → a * b = 7 → a ^ 3 + b ^ 3 = 90 := by
  have eq_gap : ∀ a b : ℝ, a ^ 3 + b ^ 3 = (a + b) ^ 3 - 4 * (a + b) * (a * b) := by
    intro a b; ring
  intro a b h1 h2
  have e : a ^ 3 + b ^ 3 = (a + b) ^ 3 - 3 * (a + b) * (a * b) := by ring
  rw [e, h1, h2]
  norm_num
