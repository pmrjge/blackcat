import Mathlib

theorem pf_0082 : ∀ n : ℕ, 15 ≤ n → n ^ 6 < 3 ^ n := by
  have eq_gap : 14 ^ 6 < 3 ^ 14 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (15 + t + 1) ^ 6 ≤ 3 * (15 + t) ^ 6 := by
      calc (15 + t + 1) ^ 6 ≤ (15 + t + 1) ^ 6 + (17394659 + 7377294 * t + 1295085 * t ^ 2 + 120580 * t ^ 3 + 6285 * t ^ 4 + 174 * t ^ 5 + 2 * t ^ 6) := Nat.le_add_right _ _
        _ = 3 * (15 + t) ^ 6 := by ring
    calc (15 + t + 1) ^ 6 ≤ 3 * (15 + t) ^ 6 := step
      _ < 3 * 3 ^ (15 + t) := by omega
      _ = 3 ^ (15 + t + 1) := by ring
