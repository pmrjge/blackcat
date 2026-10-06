import Mathlib

theorem pf_0167 : ∀ n : ℕ, 5 ∣ 2 ^ (n + 1) + 3 ^ (3 * n + 1) := by
  have eq_gap : (2 : ℤ) ^ 1 - 3 ^ 3 = -20 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 5).mp
  push_cast
  have hpq : (2 : ZMod 5) ^ 1 = (3 : ZMod 5) ^ 3 := by decide
  have hs : (2 : ZMod 5) ^ 1 + (3 : ZMod 5) ^ 1 = 0 := by decide
  generalize (2 : ZMod 5) = P at hpq hs ⊢
  generalize (3 : ZMod 5) = Q at hpq hs ⊢
  calc P ^ (n + 1) + Q ^ (3 * n + 1) = (P ^ 1) ^ n * P ^ 1 + (Q ^ 3) ^ n * Q ^ 1 := by ring
    _ = (Q ^ 3) ^ n * (P ^ 1 + Q ^ 1) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
