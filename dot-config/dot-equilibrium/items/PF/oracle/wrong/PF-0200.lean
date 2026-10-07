import Mathlib

theorem pf_0200 : ∀ n : ℕ, 6 * ∑ i ∈ Finset.range (n + 1), 7 ^ i + 1 = 7 ^ (n + 1) := by
  have eq_gap : ∀ n : ℕ, 7 ^ (n + 2) = 7 ^ (n + 1) + 6 * 7 ^ n := by
    intro n; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, pow_succ 7 (k + 1)]
    omega
