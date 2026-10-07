import Mathlib

theorem pf_0095 : ∀ x : ℝ, x ^ 3 - 19 * x - 30 = 0 → x = -2 ∨ x = -3 ∨ x = 5 := by
  have eq_gap : ∀ x : ℝ, x ^ 3 - 19 * x - 30 = (x - (-2)) * (x ^ 2 + 2 * x - 15) := by
    intro x; ring
  intro x h
  have h' : (x - (-2)) * ((x - (-3)) * (x - 5)) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = -2 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = -3 := by linarith
      rw [hx]; norm_num
    · have hx : x = 5 := by linarith
      rw [hx]; norm_num
