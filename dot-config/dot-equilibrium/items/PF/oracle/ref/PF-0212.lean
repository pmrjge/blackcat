import Mathlib

theorem pf_0212 : ∀ a : ℕ → ℤ, a 0 = -1 → (∀ n, a (n + 1) = 4 * a n + 6) → ∀ n, a n = 4 ^ n - 2 := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
