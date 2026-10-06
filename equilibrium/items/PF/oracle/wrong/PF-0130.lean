import Mathlib

theorem pf_0130 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 5) * ((i : ℚ) + 7)) = 1 / 2 * (1 / 5 + 1 / 6 - 1 / (n + 5) - 1 / (n + 6)) := by
  have eq_gap : ∀ i : ℚ, (1 : ℚ) / ((i + 5) * (i + 7)) = 1 / (i + 5) - 1 / (i + 7) := by
    intro i; field_simp; ring
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
