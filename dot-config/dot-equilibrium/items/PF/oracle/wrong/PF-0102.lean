import Mathlib

theorem pf_0102 : ∀ x : ℝ, x ^ 3 - 4 * x ^ 2 - 3 * x + 18 = 0 → x = 3 ∨ x = -2 := by
  have eq_gap : ∀ x : ℝ, x ^ 3 - 4 * x ^ 2 - 3 * x + 18 = (x - 3) * (x ^ 2 + x - 6) := by
    intro x; ring
  intro x h
  have h' : (x - 3) * ((x - 3) * (x - (-2))) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = 3 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = 3 := by linarith
      rw [hx]; norm_num
    · have hx : x = -2 := by linarith
      rw [hx]; norm_num
