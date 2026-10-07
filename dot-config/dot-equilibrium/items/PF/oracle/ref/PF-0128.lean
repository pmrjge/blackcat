import Mathlib

theorem pf_0128 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 3) * ((i : ℚ) + 5)) = 1 / 2 * (1 / 3 + 1 / 4 - 1 / (n + 3) - 1 / (n + 4)) := by
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
