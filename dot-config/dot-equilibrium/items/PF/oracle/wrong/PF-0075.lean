import Mathlib

theorem pf_0075 : ∀ n : ℕ, 10 ≤ n → n ^ 3 < 2 ^ n := by
  have eq_gap : 9 ^ 3 < 2 ^ 9 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (10 + t + 1) ^ 3 ≤ 2 * (10 + t) ^ 3 := by
      calc (10 + t + 1) ^ 3 ≤ (10 + t + 1) ^ 3 + (669 + 237 * t + 27 * t ^ 2 + t ^ 3) := Nat.le_add_right _ _
        _ = 2 * (10 + t) ^ 3 := by ring
    calc (10 + t + 1) ^ 3 ≤ 2 * (10 + t) ^ 3 := step
      _ < 2 * 2 ^ (10 + t) := by omega
      _ = 2 ^ (10 + t + 1) := by ring
