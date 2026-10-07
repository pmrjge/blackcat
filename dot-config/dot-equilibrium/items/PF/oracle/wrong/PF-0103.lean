import Mathlib

theorem pf_0103 : ∀ x : ℝ, x ^ 3 + 3 * x ^ 2 - 16 * x + 12 = 0 → x = 1 ∨ x = -6 ∨ x = 2 := by
  have eq_gap : ∀ x : ℝ, x ^ 3 + 3 * x ^ 2 - 16 * x + 12 = (x - 1) * (x ^ 2 - 4 * x - 12) := by
    intro x; ring
  intro x h
  have h' : (x - 1) * ((x - (-6)) * (x - 2)) = 0 := by linear_combination h
  rcases mul_eq_zero.mp h' with h1 | h23
  · have hx : x = 1 := by linarith
    rw [hx]; norm_num
  · rcases mul_eq_zero.mp h23 with h2 | h3
    · have hx : x = -6 := by linarith
      rw [hx]; norm_num
    · have hx : x = 2 := by linarith
      rw [hx]; norm_num
