import Mathlib

theorem pf_0192 : ∀ n : ℕ, 3 * ∑ i ∈ Finset.range (n + 1), (2 * i + 1) ^ 2 = (n + 1) * (2 * n + 1) * (2 * n + 3) := by
  have eq_gap : ∀ n : ℕ, ((n + 1) + 1) * (2 * (n + 1) + 1) * (2 * (n + 1) + 3) = (n + 1) * (2 * n + 1) * (2 * n + 3) + 3 * ((2 * n + 1) ^ 2) := by
    intro n; push_cast; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
