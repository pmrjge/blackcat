import Mathlib

theorem pf_0089 : ∀ n : ℕ, 14 ≤ n → 6 ^ n < Nat.factorial n := by
  have eq_gap : 6 ^ 13 < Nat.factorial 13 := by
    decide
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => decide
  | succ m hm ih =>
    rw [Nat.factorial_succ, pow_succ]
    have hc : 6 ≤ m + 1 := by omega
    have hf : 0 < Nat.factorial m := Nat.factorial_pos m
    nlinarith
