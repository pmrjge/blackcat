import Mathlib

theorem pf_0153 : ∀ f : ℤ → ℤ, (∀ x y, f (x + y) = f x + f y - 3 * x * y) → f 1 = 1 → ∀ n, 2 * f n = -3 * n * (n - 1) + 2 * n := by
  sorry
