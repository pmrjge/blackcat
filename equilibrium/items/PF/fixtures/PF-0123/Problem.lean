import Mathlib

theorem pf_0123 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (2 : ℚ) / (((i : ℚ) + 3) * ((i : ℚ) + 4)) = 2 * n / (3 * (n + 3)) := by
  sorry
