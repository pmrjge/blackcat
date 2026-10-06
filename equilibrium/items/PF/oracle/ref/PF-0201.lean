import Mathlib

theorem pf_0201 : ∀ n : ℕ, ∑ i ∈ Finset.range (n + 1), i * Nat.factorial i + 1 = Nat.factorial (n + 1) := by
  intro n
  induction n with
  | zero => simp
  | succ k ih =>
    rw [Finset.sum_range_succ, Nat.factorial_succ (k + 1)]
    nlinarith [ih]
