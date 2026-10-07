import Mathlib

theorem pf_0126 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 1) * ((i : ℚ) + 3)) = 1 / 2 * (1 / 1 + 1 / 2 - 1 / (n + 1) - 1 / (n + 2)) := by
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
