import Mathlib

theorem pf_0098 : ∀ x : ℝ, x ^ 3 - 3 * x ^ 2 + 4 = 0 → x = 2 ∨ x = -1 := by
  intro x h
  have h' : (x - 2) * ((x - 2) * (x - (-1))) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = 2 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = 2 := by linarith
      rw [hx]; norm_num
    · have hx : x = -1 := by linarith
      rw [hx]; norm_num
