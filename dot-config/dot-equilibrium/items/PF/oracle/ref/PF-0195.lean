import Mathlib

theorem pf_0195 : ∀ n : ℕ, 30 * ∑ i ∈ Finset.range (n + 1), (i : ℤ) ^ 4 = (n : ℤ) * (n + 1) * (2 * n + 1) * (3 * n ^ 2 + 3 * n - 1) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
