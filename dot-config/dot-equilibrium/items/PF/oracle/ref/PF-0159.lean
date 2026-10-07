import Mathlib

theorem pf_0159 : ∀ n : ℕ, 7 ∣ 2 ^ (2 * n + 1) + 5 ^ (2 * n + 1) := by
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (2 : ZMod 7) ^ 2 = (5 : ZMod 7) ^ 2 := by decide
  have hs : (2 : ZMod 7) ^ 1 + (5 : ZMod 7) ^ 1 = 0 := by decide
  generalize (2 : ZMod 7) = P at hpq hs ⊢
  generalize (5 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (2 * n + 1) + Q ^ (2 * n + 1) = (P ^ 2) ^ n * P ^ 1 + (Q ^ 2) ^ n * Q ^ 1 := by ring
    _ = (Q ^ 2) ^ n * (P ^ 1 + Q ^ 1) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
