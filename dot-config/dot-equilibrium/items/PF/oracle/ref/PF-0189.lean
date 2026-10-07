import Mathlib

theorem pf_0189 : ∀ n : ℕ, 4 * ∑ i ∈ Finset.range (n + 1), i ^ 3 = n ^ 2 * (n + 1) ^ 2 := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
