import Mathlib

theorem pf_0012 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = -2 → (∀ n, f (n + 2) = 7 * f (n + 1) - 6 * f n) → ∀ n, f n = -6 ^ n + 4 * 1 ^ n := by
  sorry
