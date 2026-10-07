import Mathlib

theorem pf_0094 : ∀ x : ℝ, x ^ 3 + 2 * x ^ 2 - 11 * x - 12 = 0 → x = 3 ∨ x = -1 ∨ x = -4 := by
  intro x h
  have h' : (x - 3) * ((x - (-1)) * (x - (-4))) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = 3 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = -1 := by linarith
      rw [hx]; norm_num
    · have hx : x = -4 := by linarith
      rw [hx]; norm_num
