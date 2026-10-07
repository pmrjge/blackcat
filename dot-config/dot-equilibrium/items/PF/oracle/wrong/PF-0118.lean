import Mathlib

theorem pf_0118 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 2) * ((i : ℚ) + 3)) = n / (2 * (n + 2)) := by
  have eq_gap : ∀ i : ℚ, (1 : ℚ) / ((i + 2) * (i + 3)) = 1 / (i + 2) + 1 / (i + 3) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
