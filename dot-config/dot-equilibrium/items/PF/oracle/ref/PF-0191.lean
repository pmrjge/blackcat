import Mathlib

theorem pf_0191 : ∀ n : ℕ, 4 * ∑ i ∈ Finset.range (n + 1), i * (i + 1) * (i + 2) = n * (n + 1) * (n + 2) * (n + 3) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
