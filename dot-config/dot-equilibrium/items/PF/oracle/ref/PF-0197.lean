import Mathlib

theorem pf_0197 : ∀ n : ℕ, 2 * ∑ i ∈ Finset.range (n + 1), i * (i + 1) * (2 * i + 1) = n * (n + 1) ^ 2 * (n + 2) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
