import Mathlib

theorem pf_0122 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (5 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 2)) = 5 * n / (n + 1) := by
  have eq_gap : ∀ i : ℚ, (5 : ℚ) / ((i + 1) * (i + 2)) = 5 / (i + 1) + 5 / (i + 2) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
