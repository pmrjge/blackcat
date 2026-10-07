import Mathlib

theorem pf_0083 : ∀ n : ℕ, 8 ≤ n → n ^ 6 < 5 ^ n := by
  have eq_gap : 7 ^ 6 < 5 ^ 7 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (8 + t + 1) ^ 6 ≤ 5 * (8 + t) ^ 6 := by
      calc (8 + t + 1) ^ 6 ≤ (8 + t + 1) ^ 6 + (779279 + 628746 * t + 208785 * t ^ 2 + 36620 * t ^ 3 + 3585 * t ^ 4 + 186 * t ^ 5 + 4 * t ^ 6) := Nat.le_add_right _ _
        _ = 5 * (8 + t) ^ 6 := by ring
    calc (8 + t + 1) ^ 6 ≤ 5 * (8 + t) ^ 6 := step
      _ < 5 * 5 ^ (8 + t) := by omega
      _ = 5 ^ (8 + t + 1) := by ring
