import Mathlib

theorem pf_0011 : ∀ f : ℕ → ℤ, f 0 = 2 → f 1 = 14 → (∀ n, f (n + 2) = 2 * f (n + 1) + 8 * f n) → ∀ n, f n = 3 * 4 ^ n - (-2) ^ n := by
  sorry
