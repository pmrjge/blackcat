import Mathlib

theorem pf_0165 : ∀ n : ℕ, 7 ∣ 6 ^ (n + 1) + 3 ^ (3 * n) := by
  have eq_gap : (6 : ℤ) ^ 1 - 3 ^ 3 = -14 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (6 : ZMod 7) ^ 1 = (3 : ZMod 7) ^ 3 := by decide
  have hs : (6 : ZMod 7) ^ 1 + (3 : ZMod 7) ^ 0 = 0 := by decide
  generalize (6 : ZMod 7) = P at hpq hs ⊢
  generalize (3 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (n + 1) + Q ^ (3 * n) = (P ^ 1) ^ n * P ^ 1 + (Q ^ 3) ^ n * Q ^ 0 := by ring
    _ = (Q ^ 3) ^ n * (P ^ 1 + Q ^ 0) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
