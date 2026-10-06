import Mathlib

theorem pf_0121 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 3) * ((i : ℚ) + 4)) = n / (3 * (n + 3)) := by
  have eq_gap : ∀ i : ℚ, (1 : ℚ) / ((i + 3) * (i + 4)) = 1 / (i + 3) + 1 / (i + 4) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
