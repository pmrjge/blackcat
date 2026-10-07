import Mathlib

theorem pf_0020 : ∀ a b : ℝ, a + b = 2 → a * b = -5 → a ^ 3 + b ^ 3 = 38 := by
  have eq_gap : ∀ a b : ℝ, a ^ 3 + b ^ 3 = (a + b) ^ 3 - 4 * (a + b) * (a * b) := by
    intro a b; ring
  intro a b h1 h2
  have e : a ^ 3 + b ^ 3 = (a + b) ^ 3 - 3 * (a + b) * (a * b) := by ring
  rw [e, h1, h2]
  norm_num
