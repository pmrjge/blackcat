import Mathlib

theorem pf_0171 : ∀ n : ℕ, 5 ∣ 4 ^ (n + 1) + 2 ^ (2 * n) := by
  have eq_gap : (4 : ℤ) ^ 1 - 2 ^ 2 = 5 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 5).mp
  push_cast
  have hpq : (4 : ZMod 5) ^ 1 = (2 : ZMod 5) ^ 2 := by decide
  have hs : (4 : ZMod 5) ^ 1 + (2 : ZMod 5) ^ 0 = 0 := by decide
  generalize (4 : ZMod 5) = P at hpq hs ⊢
  generalize (2 : ZMod 5) = Q at hpq hs ⊢
  calc P ^ (n + 1) + Q ^ (2 * n) = (P ^ 1) ^ n * P ^ 1 + (Q ^ 2) ^ n * Q ^ 0 := by ring
    _ = (Q ^ 2) ^ n * (P ^ 1 + Q ^ 0) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
