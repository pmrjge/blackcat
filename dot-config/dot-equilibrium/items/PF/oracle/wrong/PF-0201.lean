import Mathlib

theorem pf_0201 : ∀ n : ℕ, ∑ i ∈ Finset.range (n + 1), i * Nat.factorial i + 1 = Nat.factorial (n + 1) := by
  have eq_gap : ∀ n : ℕ, Nat.factorial (n + 2) = Nat.factorial (n + 1) + n * Nat.factorial n := by
    intro n; ring
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, Nat.factorial_succ (k + 1)]
    nlinarith [ih]
