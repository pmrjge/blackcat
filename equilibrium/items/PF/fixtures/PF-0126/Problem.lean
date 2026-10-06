import Mathlib

theorem pf_0126 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 3)) = 1 / 2 * (1 / 1 + 1 / 2 - 1 / (n + 1) - 1 / (n + 2)) := by
  sorry
