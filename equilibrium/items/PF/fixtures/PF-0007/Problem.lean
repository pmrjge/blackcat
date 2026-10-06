import Mathlib

theorem pf_0007 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = -2 → (∀ n, f (n + 2) = -3 * f (n + 1) + 4 * f n) → ∀ n, f n = 2 * 1 ^ n + (-4) ^ n := by
  sorry
