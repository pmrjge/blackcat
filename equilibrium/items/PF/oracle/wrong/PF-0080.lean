import Mathlib

theorem pf_0080 : ∀ n : ℕ, 23 ≤ n → n ^ 5 < 2 ^ n := by
  have eq_gap : 22 ^ 5 < 2 ^ 22 := by
    norm_num
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (23 + t + 1) ^ 5 ≤ 2 * (23 + t) ^ 5 := by
      calc (23 + t + 1) ^ 5 ≤ (23 + t + 1) ^ 5 + (4910062 + 1139530 * t + 105100 * t ^ 2 + 4820 * t ^ 3 + 110 * t ^ 4 + t ^ 5) := Nat.le_add_right _ _
        _ = 2 * (23 + t) ^ 5 := by ring
    calc (23 + t + 1) ^ 5 ≤ 2 * (23 + t) ^ 5 := step
      _ < 2 * 2 ^ (23 + t) := by omega
      _ = 2 ^ (23 + t + 1) := by ring
