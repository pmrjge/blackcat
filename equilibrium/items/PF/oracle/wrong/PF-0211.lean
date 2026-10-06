import Mathlib

theorem pf_0211 : ∀ a : ℕ → ℤ, a 0 = 1 → (∀ n, a (n + 1) = 2 * a n + 3) → ∀ n, a n = 4 * 2 ^ n - 3 := by
  have eq_gap : (2 : ℚ) * (3 / (2 - 1)) + 3 = 3 / (2 - 1) := by
    norm_num
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
