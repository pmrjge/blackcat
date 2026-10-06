import Mathlib

theorem pf_0195 : ∀ n : ℕ, 30 * ∑ i ∈ Finset.range (n + 1), (i : ℤ) ^ 4 = (n : ℤ) * (n + 1) * (2 * n + 1) * (3 * n ^ 2 + 3 * n - 1) := by
  have eq_gap : ∀ n : ℕ, ((n : ℤ) + 1) * (((n : ℤ) + 1) + 1) * (2 * ((n : ℤ) + 1) + 1) * (3 * ((n : ℤ) + 1) ^ 2 + 3 * ((n : ℤ) + 1) - 1) = (n : ℤ) * ((n : ℤ) + 1) * (2 * (n : ℤ) + 1) * (3 * (n : ℤ) ^ 2 + 3 * (n : ℤ) - 1) + 30 * ((n : ℤ) ^ 4) := by
    intro n; push_cast; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, mul_add, ih]
    push_cast
    ring
