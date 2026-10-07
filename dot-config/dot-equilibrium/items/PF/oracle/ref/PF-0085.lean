import Mathlib

theorem pf_0085 : ∀ n : ℕ, 4 ≤ n → 2 ^ n < Nat.factorial n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => decide
  | succ m hm ih =>
    rw [Nat.factorial_succ, pow_succ]
    have hc : 2 ≤ m + 1 := by omega
    have hf : 0 < Nat.factorial m := Nat.factorial_pos m
    nlinarith
