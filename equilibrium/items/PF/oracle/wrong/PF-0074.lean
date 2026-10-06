import Mathlib

theorem pf_0074 : ∀ n : ℕ, 5 ≤ n → n ^ 2 < 2 ^ n := by
  have eq_gap : 4 ^ 2 < 2 ^ 4 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (5 + t + 1) ^ 2 ≤ 2 * (5 + t) ^ 2 := by
      calc (5 + t + 1) ^ 2 ≤ (5 + t + 1) ^ 2 + (14 + 8 * t + t ^ 2) := Nat.le_add_right _ _
        _ = 2 * (5 + t) ^ 2 := by ring
    calc (5 + t + 1) ^ 2 ≤ 2 * (5 + t) ^ 2 := step
      _ < 2 * 2 ^ (5 + t) := by omega
      _ = 2 ^ (5 + t + 1) := by ring
