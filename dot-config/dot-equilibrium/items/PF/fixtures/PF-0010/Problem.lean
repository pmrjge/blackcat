import Mathlib

theorem pf_0010 : ∀ f : ℕ → ℤ, f 0 = 2 → f 1 = 2 → (∀ n, f (n + 2) = 2 * f (n + 1) + 15 * f n) → ∀ n, f n = 5 ^ n + (-3) ^ n := by
  sorry
