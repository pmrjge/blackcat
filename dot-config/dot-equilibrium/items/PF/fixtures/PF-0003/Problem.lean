import Mathlib

theorem pf_0003 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = -4 → (∀ n, f (n + 2) = -f (n + 1) + 6 * f n) → ∀ n, f n = 2 ^ n + 2 * (-3) ^ n := by
  sorry
