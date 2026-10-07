import Mathlib

theorem pf_0119 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (2 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 2)) = 2 * n / (n + 1) := by
  have eq_gap : ∀ i : ℚ, (2 : ℚ) / ((i + 1) * (i + 2)) = 2 / (i + 1) + 2 / (i + 2) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
