import Mathlib

theorem pf_0127 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 2) * ((i : ℚ) + 4)) = 1 / 2 * (1 / 2 + 1 / 3 - 1 / (n + 2) - 1 / (n + 3)) := by
  have eq_gap : ∀ i : ℚ, (1 : ℚ) / ((i + 2) * (i + 4)) = 1 / (i + 2) - 1 / (i + 4) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
