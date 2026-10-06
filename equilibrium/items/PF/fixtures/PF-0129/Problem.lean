import Mathlib

theorem pf_0129 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 4) * ((i : ℚ) + 6)) = 1 / 2 * (1 / 4 + 1 / 5 - 1 / (n + 4) - 1 / (n + 5)) := by
  sorry
