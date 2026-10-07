import Mathlib

theorem pf_0091 : ∀ x : ℝ, x ^ 3 - 5 * x ^ 2 + 2 * x + 8 = 0 → x = -1 ∨ x = 2 ∨ x = 4 := by
  intro x h
  have h' : (x - (-1)) * ((x - 2) * (x - 4)) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = -1 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = 2 := by linarith
      rw [hx]; norm_num
    · have hx : x = 4 := by linarith
      rw [hx]; norm_num
