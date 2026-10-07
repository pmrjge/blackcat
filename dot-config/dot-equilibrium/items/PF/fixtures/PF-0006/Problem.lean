import Mathlib

theorem pf_0006 : ∀ f : ℕ → ℤ, f 0 = 4 → f 1 = -1 → (∀ n, f (n + 2) = 3 * f (n + 1) + 10 * f n) → ∀ n, f n = 3 * (-2) ^ n + 5 ^ n := by
  sorry
