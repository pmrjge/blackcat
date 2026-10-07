import Mathlib

theorem pf_0123 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (2 : ℚ) / (((i : ℚ) + 3) * ((i : ℚ) + 4)) = 2 * n / (3 * (n + 3)) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
