import Mathlib

theorem pf_0087 : ∀ n : ℕ, 9 ≤ n → 4 ^ n < Nat.factorial n := by
  have eq_gap : 4 ^ 8 < Nat.factorial 8 := by
    decide
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => decide
  | succ m hm ih =>
    rw [Nat.factorial_succ, pow_succ]
    have hc : 4 ≤ m + 1 := by omega
    have hf : 0 < Nat.factorial m := Nat.factorial_pos m
    nlinarith
