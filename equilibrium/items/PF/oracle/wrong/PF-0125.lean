import Mathlib

theorem pf_0125 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (3 : ℚ) / (((i : ℚ) + 4) * ((i : ℚ) + 5)) = 3 * n / (4 * (n + 4)) := by
  have eq_gap : ∀ i : ℚ, (3 : ℚ) / ((i + 4) * (i + 5)) = 3 / (i + 4) + 3 / (i + 5) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
