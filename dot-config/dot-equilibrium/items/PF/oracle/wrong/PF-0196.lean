import Mathlib

theorem pf_0196 : ∀ n : ℕ, 12 * ∑ i ∈ Finset.range (n + 1), (i : ℤ) ^ 5 = (n : ℤ) ^ 2 * (n + 1) ^ 2 * (2 * n ^ 2 + 2 * n - 1) := by
  have eq_gap : ∀ n : ℕ, ((n : ℤ) + 1) ^ 2 * (((n : ℤ) + 1) + 1) ^ 2 * (2 * ((n : ℤ) + 1) ^ 2 + 2 * ((n : ℤ) + 1) - 1) = (n : ℤ) ^ 2 * ((n : ℤ) + 1) ^ 2 * (2 * (n : ℤ) ^ 2 + 2 * (n : ℤ) - 1) + 12 * ((n : ℤ) ^ 5) := by
    intro n; push_cast; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
