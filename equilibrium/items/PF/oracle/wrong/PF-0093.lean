import Mathlib

theorem pf_0093 : ∀ x : ℝ, x ^ 3 + 2 * x ^ 2 - 13 * x + 10 = 0 → x = 2 ∨ x = -5 ∨ x = 1 := by
  have eq_gap : ∀ x : ℝ, x ^ 3 + 2 * x ^ 2 - 13 * x + 10 = (x - 2) * (x ^ 2 - 4 * x - 5) := by
    intro x; ring
  intro x h
  have h' : (x - 2) * ((x - (-5)) * (x - 1)) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = 2 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = -5 := by linarith
      rw [hx]; norm_num
    · have hx : x = 1 := by linarith
      rw [hx]; norm_num
