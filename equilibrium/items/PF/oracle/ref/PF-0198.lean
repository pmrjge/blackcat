import Mathlib

theorem pf_0198 : ∀ n : ℕ, 2 * ∑ i ∈ Finset.range (n + 1), 3 ^ i + 1 = 3 ^ (n + 1) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, pow_succ 3 (k + 1)]
    omega
