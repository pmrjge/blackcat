import Mathlib

theorem pf_0209 : ∀ a : ℕ → ℤ, a 0 = 0 → (∀ n, a (n + 1) = 2 * a n + 1) → ∀ n, a n = 2 ^ n - 1 := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
