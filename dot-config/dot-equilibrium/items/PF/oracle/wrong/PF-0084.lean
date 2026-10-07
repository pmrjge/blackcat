import Mathlib

theorem pf_0084 : ∀ n : ℕ, 10 ≤ n → n ^ 6 < 4 ^ n := by
  have eq_gap : 9 ^ 6 < 4 ^ 9 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (10 + t + 1) ^ 6 ≤ 4 * (10 + t) ^ 6 := by
      calc (10 + t + 1) ^ 6 ≤ (10 + t + 1) ^ 6 + (2228439 + 1433694 * t + 380385 * t ^ 2 + 53380 * t ^ 3 + 4185 * t ^ 4 + 174 * t ^ 5 + 3 * t ^ 6) := Nat.le_add_right _ _
        _ = 4 * (10 + t) ^ 6 := by ring
    calc (10 + t + 1) ^ 6 ≤ 4 * (10 + t) ^ 6 := step
      _ < 4 * 4 ^ (10 + t) := by omega
      _ = 4 ^ (10 + t + 1) := by ring
