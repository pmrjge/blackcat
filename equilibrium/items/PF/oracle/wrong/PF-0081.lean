import Mathlib

theorem pf_0081 : ∀ n : ℕ, 8 ≤ n → n ^ 5 < 4 ^ n := by
  have eq_gap : 7 ^ 5 < 4 ^ 7 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (8 + t + 1) ^ 5 ≤ 4 * (8 + t) ^ 5 := by
      calc (8 + t + 1) ^ 5 ≤ (8 + t + 1) ^ 5 + (72023 + 49115 * t + 13190 * t ^ 2 + 1750 * t ^ 3 + 115 * t ^ 4 + 3 * t ^ 5) := Nat.le_add_right _ _
        _ = 4 * (8 + t) ^ 5 := by ring
    calc (8 + t + 1) ^ 5 ≤ 4 * (8 + t) ^ 5 := step
      _ < 4 * 4 ^ (8 + t) := by omega
      _ = 4 ^ (8 + t + 1) := by ring
