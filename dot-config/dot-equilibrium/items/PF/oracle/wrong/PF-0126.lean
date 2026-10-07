import Mathlib

theorem pf_0126 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 3)) = 1 / 2 * (1 / 1 + 1 / 2 - 1 / (n + 1) - 1 / (n + 2)) := by
  have eq_gap : ∀ i : ℚ, (1 : ℚ) / ((i + 1) * (i + 3)) = 1 / (i + 1) - 1 / (i + 3) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
