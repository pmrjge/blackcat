import Mathlib

theorem pf_0190 : ∀ n : ℕ, 3 * ∑ i ∈ Finset.range (n + 1), i * (i + 1) = n * (n + 1) * (n + 2) := by
  have eq_gap : ∀ n : ℕ, (n + 1) * ((n + 1) + 1) * ((n + 1) + 2) = n * (n + 1) * (n + 2) + 3 * (n * (n + 1)) := by
    intro n; push_cast; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
