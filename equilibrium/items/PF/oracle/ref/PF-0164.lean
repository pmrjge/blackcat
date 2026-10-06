import Mathlib

theorem pf_0164 : ∀ n : ℕ, 7 ∣ 6 ^ (2 * n + 1) + 2 ^ (3 * n) := by
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 7).mp
  push_cast
  have hpq : (6 : ZMod 7) ^ 2 = (2 : ZMod 7) ^ 3 := by decide
  have hs : (6 : ZMod 7) ^ 1 + (2 : ZMod 7) ^ 0 = 0 := by decide
  generalize (6 : ZMod 7) = P at hpq hs ⊢
  generalize (2 : ZMod 7) = Q at hpq hs ⊢
  calc P ^ (2 * n + 1) + Q ^ (3 * n) = (P ^ 2) ^ n * P ^ 1 + (Q ^ 3) ^ n * Q ^ 0 := by ring
    _ = (Q ^ 3) ^ n * (P ^ 1 + Q ^ 0) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
