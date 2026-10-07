import Mathlib

theorem pf_0129 : ∀ n : ℕ, ∑ i ∈ Finset.range n, (1 : ℚ) / (((i : ℚ) + 4) * ((i : ℚ) + 6)) = 1 / 2 * (1 / 4 + 1 / 5 - 1 / (n + 4) - 1 / (n + 5)) := by
  intro n
  induction n with
  | zero => norm_num
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    field_simp
    ring
