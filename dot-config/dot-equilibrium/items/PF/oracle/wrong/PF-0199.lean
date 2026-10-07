import Mathlib

theorem pf_0199 : ∀ n : ℕ, 4 * ∑ i ∈ Finset.range (n + 1), 5 ^ i + 1 = 5 ^ (n + 1) := by
  have eq_gap : ∀ n : ℕ, 5 ^ (n + 2) = 5 ^ (n + 1) + 4 * 5 ^ n := by
    intro n; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, pow_succ 5 (k + 1)]
    omega
