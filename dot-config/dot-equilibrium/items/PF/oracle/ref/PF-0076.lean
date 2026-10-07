import Mathlib

theorem pf_0076 : ∀ n : ℕ, 17 ≤ n → n ^ 4 < 2 ^ n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (17 + t + 1) ^ 4 ≤ 2 * (17 + t) ^ 4 := by
      calc (17 + t + 1) ^ 4 ≤ (17 + t + 1) ^ 4 + (62066 + 15976 * t + 1524 * t ^ 2 + 64 * t ^ 3 + t ^ 4) := Nat.le_add_right _ _
        _ = 2 * (17 + t) ^ 4 := by ring
    calc (17 + t + 1) ^ 4 ≤ 2 * (17 + t) ^ 4 := step
      _ < 2 * 2 ^ (17 + t) := by omega
      _ = 2 ^ (17 + t + 1) := by ring
