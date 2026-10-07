import Mathlib

theorem pf_0214 : ∀ a : ℕ → ℤ, a 0 = 0 → (∀ n, a (n + 1) = 3 * a n - 2) → ∀ n, a n = -3 ^ n + 1 := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
