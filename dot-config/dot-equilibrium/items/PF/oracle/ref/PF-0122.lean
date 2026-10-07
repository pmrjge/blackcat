import Mathlib

theorem pf_0122 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (5 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 2)) = 5 * n / (n + 1) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
