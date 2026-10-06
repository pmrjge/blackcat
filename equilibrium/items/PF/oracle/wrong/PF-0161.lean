import Mathlib

theorem pf_0161 : ∀ n : ℕ, 7 ∣ 3 ^ (2 * n + 1) + 2 ^ (n + 2) := by
  have eq_gap : (3 : ℤ) ^ 2 - 2 ^ 1 = 14 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (3 : ZMod 7) ^ 2 = (2 : ZMod 7) ^ 1 := by decide
  have hs : (3 : ZMod 7) ^ 1 + (2 : ZMod 7) ^ 2 = 0 := by decide
  generalize (3 : ZMod 7) = P at hpq hs ⊢
  generalize (2 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (2 * n + 1) + Q ^ (n + 2) = (P ^ 2) ^ n * P ^ 1 + (Q ^ 1) ^ n * Q ^ 2 := by ring
    _ = (Q ^ 1) ^ n * (P ^ 1 + Q ^ 2) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
