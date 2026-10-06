import Mathlib

theorem pf_0078 : ∀ n : ℕ, 8 ≤ n → n ^ 4 < 3 ^ n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (8 + t + 1) ^ 4 ≤ 3 * (8 + t) ^ 4 := by
      calc (8 + t + 1) ^ 4 ≤ (8 + t + 1) ^ 4 + (5727 + 3228 * t + 666 * t ^ 2 + 60 * t ^ 3 + 2 * t ^ 4) := Nat.le_add_right _ _
        _ = 3 * (8 + t) ^ 4 := by ring
    calc (8 + t + 1) ^ 4 ≤ 3 * (8 + t) ^ 4 := step
      _ < 3 * 3 ^ (8 + t) := by omega
      _ = 3 ^ (8 + t + 1) := by ring
