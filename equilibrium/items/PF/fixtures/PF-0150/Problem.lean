import Mathlib

theorem pf_0150 : ∀ f : ℤ → ℤ, (∀ x y, f (x + y) = f x + f y - 2 * x * y) → f 1 = 2 → ∀ n, 2 * f n = -2 * n * (n - 1) + 4 * n := by
  sorry
