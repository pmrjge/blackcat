import Mathlib

theorem pf_0210 : ∀ a : ℕ → ℤ, a 0 = 1 → (∀ n, a (n + 1) = 3 * a n + 4) → ∀ n, a n = 3 * 3 ^ n - 2 := by
  have eq_gap : (3 : ℚ) * (4 / (3 - 1)) + 4 = 4 / (3 - 1) := by
    norm_num
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
