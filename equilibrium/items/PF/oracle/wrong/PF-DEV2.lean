import Mathlib

theorem pf_dev2 : ∀ n : ℕ, 7 ∣ 2 ^ n + 3 ^ (2 * n + 3) := by
  have eq_gap : (2 : ℤ) ^ 1 - 3 ^ 2 = -14 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (2 : ZMod 7) ^ 1 = (3 : ZMod 7) ^ 2 := by decide
  have hs : (2 : ZMod 7) ^ 0 + (3 : ZMod 7) ^ 3 = 0 := by decide
  generalize (2 : ZMod 7) = P at hpq hs ⊢
  generalize (3 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ n + Q ^ (2 * n + 3) = (P ^ 1) ^ n * P ^ 0 + (Q ^ 2) ^ n * Q ^ 3 := by ring
    _ = (Q ^ 2) ^ n * (P ^ 0 + Q ^ 3) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
