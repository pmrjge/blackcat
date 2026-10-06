import Mathlib

theorem pf_0077 : ∀ n : ℕ, 4 ≤ n → n ^ 3 < 3 ^ n := by
  intro n hn
  induction n, hn using Nat.le_induction with
  | base => norm_num
  | succ m hm ih =>
    obtain ⟨t, rfl⟩ := Nat.exists_eq_add_of_le hm
    have step : (4 + t + 1) ^ 3 ≤ 3 * (4 + t) ^ 3 := by
      calc (4 + t + 1) ^ 3 ≤ (4 + t + 1) ^ 3 + (67 + 69 * t + 21 * t ^ 2 + 2 * t ^ 3) := Nat.le_add_right _ _
        _ = 3 * (4 + t) ^ 3 := by ring
    calc (4 + t + 1) ^ 3 ≤ 3 * (4 + t) ^ 3 := step
      _ < 3 * 3 ^ (4 + t) := by omega
      _ = 3 ^ (4 + t + 1) := by ring
