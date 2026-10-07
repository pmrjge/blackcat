import Mathlib

theorem pf_0193 : ∀ n : ℕ, ∑ i ∈ Finset.range (n + 1), (2 * i + 1) ^ 3 = (n + 1) ^ 2 * (2 * n ^ 2 + 4 * n + 1) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, ih]
    push_cast
    ring
