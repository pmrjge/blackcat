import Mathlib

theorem pf_0168 : ∀ n : ℕ, 5 ∣ 2 ^ (3 * n + 1) + 3 ^ (n + 1) := by
  have eq_gap : (2 : ℤ) ^ 3 - 3 ^ 1 = 10 := by
    norm_num
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 5).mp
  push_cast
  have hpq : (2 : ZMod 5) ^ 3 = (3 : ZMod 5) ^ 1 := by decide
  have hs : (2 : ZMod 5) ^ 1 + (3 : ZMod 5) ^ 1 = 0 := by decide
  generalize (2 : ZMod 5) = P at hpq hs ⊢
  generalize (3 : ZMod 5) = Q at hpq hs ⊢
  calc P ^ (3 * n + 1) + Q ^ (n + 1) = (P ^ 3) ^ n * P ^ 1 + (Q ^ 1) ^ n * Q ^ 1 := by ring
    _ = (Q ^ 1) ^ n * (P ^ 1 + Q ^ 1) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
