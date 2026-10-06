import Mathlib

theorem pf_0120 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (3 : ℚ) / (((i : ℚ) + 2) * ((i : ℚ) + 3)) = 3 * n / (2 * (n + 2)) := by
  have eq_gap : ∀ i : ℚ, (3 : ℚ) / ((i + 2) * (i + 3)) = 3 / (i + 2) + 3 / (i + 3) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
