import Mathlib

theorem pf_0086 : ∀ n : ℕ, 7 ≤ n → 3 ^ n < Nat.factorial n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => decide
  | succ m hm ih =>
    rw [Nat.factorial_succ, pow_succ]
    have hc : 3 ≤ m + 1 := by omega
    have hf : 0 < Nat.factorial m := Nat.factorial_pos m
    nlinarith
