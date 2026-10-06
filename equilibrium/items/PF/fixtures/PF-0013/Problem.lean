import Mathlib

theorem pf_0013 : ∀ f : ℕ → ℤ, f 0 = -1 → f 1 = -6 → (∀ n, f (n + 2) = 7 * f (n + 1) - 12 * f n) → ∀ n, f n = 2 * 3 ^ n - 3 * 4 ^ n := by
  sorry
