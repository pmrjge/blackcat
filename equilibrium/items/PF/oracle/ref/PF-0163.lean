import Mathlib

theorem pf_0163 : ∀ n : ℕ, 7 ∣ 3 ^ (3 * n) + 6 ^ (n + 1) := by
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (3 : ZMod 7) ^ 3 = (6 : ZMod 7) ^ 1 := by decide
  have hs : (3 : ZMod 7) ^ 0 + (6 : ZMod 7) ^ 1 = 0 := by decide
  generalize (3 : ZMod 7) = P at hpq hs ⊢
  generalize (6 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (3 * n) + Q ^ (n + 1) = (P ^ 3) ^ n * P ^ 0 + (Q ^ 1) ^ n * Q ^ 1 := by ring
    _ = (Q ^ 1) ^ n * (P ^ 0 + Q ^ 1) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
