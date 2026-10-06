import Mathlib

theorem pf_0215 : ∀ a : ℕ → ℤ, a 0 = 2 → (∀ n, a (n + 1) = 6 * a n + 10) → ∀ n, a n = 4 * 6 ^ n - 2 := by
  have eq_gap : (6 : ℚ) * (10 / (6 - 1)) + 10 = 10 / (6 - 1) := by
    norm_num
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
