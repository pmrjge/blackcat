import Mathlib

theorem pf_0079 : ∀ n : ℕ, 11 ≤ n → n ^ 5 < 3 ^ n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (11 + t + 1) ^ 5 ≤ 3 * (11 + t) ^ 5 := by
      calc (11 + t + 1) ^ 5 ≤ (11 + t + 1) ^ 5 + (234321 + 115935 * t + 22650 * t ^ 2 + 2190 * t ^ 3 + 105 * t ^ 4 + 2 * t ^ 5) := Nat.le_add_right _ _
        _ = 3 * (11 + t) ^ 5 := by ring
    calc (11 + t + 1) ^ 5 ≤ 3 * (11 + t) ^ 5 := step
      _ < 3 * 3 ^ (11 + t) := by omega
      _ = 3 ^ (11 + t + 1) := by ring
