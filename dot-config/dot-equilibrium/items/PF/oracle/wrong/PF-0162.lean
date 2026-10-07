import Mathlib

theorem pf_0162 : ∀ n : ℕ, 7 ∣ 3 ^ (3 * n + 1) + 5 ^ (3 * n + 2) := by
  have eq_gap : (3 : ℤ) ^ 3 - 5 ^ 3 = -91 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (3 : ZMod 7) ^ 3 = (5 : ZMod 7) ^ 3 := by decide
  have hs : (3 : ZMod 7) ^ 1 + (5 : ZMod 7) ^ 2 = 0 := by decide
  generalize (3 : ZMod 7) = P at hpq hs ⊢
  generalize (5 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (3 * n + 1) + Q ^ (3 * n + 2) = (P ^ 3) ^ n * P ^ 1 + (Q ^ 3) ^ n * Q ^ 2 := by ring
    _ = (Q ^ 3) ^ n * (P ^ 1 + Q ^ 2) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
