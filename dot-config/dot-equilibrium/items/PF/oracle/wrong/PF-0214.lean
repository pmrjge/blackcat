import Mathlib

theorem pf_0214 : ∀ a : ℕ → ℤ, a 0 = 0 → (∀ n, a (n + 1) = 3 * a n - 2) → ∀ n, a n = -3 ^ n + 1 := by
  have eq_gap : (3 : ℚ) * (-2 / (3 - 1)) + -2 = -2 / (3 - 1) := by
    norm_num
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
