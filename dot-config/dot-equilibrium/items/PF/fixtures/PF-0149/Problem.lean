import Mathlib

theorem pf_0149 : ∀ f : ℤ → ℤ, (∀ x y, f (x + y) = f x + f y + 5 * x * y) → f 1 = 1 → ∀ n, 2 * f n = 5 * n * (n - 1) + 2 * n := by
  sorry
