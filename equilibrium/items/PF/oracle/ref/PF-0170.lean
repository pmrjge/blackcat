import Mathlib

theorem pf_0170 : ∀ n : ℕ, 5 ∣ 2 ^ (2 * n) + 4 ^ (3 * n + 1) := by
  intro n
  apply (ZMod.natCast_eq_zero_iff _ 5).mp
  push_cast
  have hpq : (2 : ZMod 5) ^ 2 = (4 : ZMod 5) ^ 3 := by decide
  have hs : (2 : ZMod 5) ^ 0 + (4 : ZMod 5) ^ 1 = 0 := by decide
  generalize (2 : ZMod 5) = P at hpq hs ⊢
  generalize (4 : ZMod 5) = Q at hpq hs ⊢
  calc P ^ (2 * n) + Q ^ (3 * n + 1) = (P ^ 2) ^ n * P ^ 0 + (Q ^ 3) ^ n * Q ^ 1 := by ring
    _ = (Q ^ 3) ^ n * (P ^ 0 + Q ^ 1) := by rw [hpq]; ring
    _ = 0 := by rw [hs, mul_zero]
