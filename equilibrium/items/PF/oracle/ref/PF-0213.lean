import Mathlib

theorem pf_0213 : ∀ a : ℕ → ℤ, a 0 = 3 → (∀ n, a (n + 1) = 5 * a n - 8) → ∀ n, a n = 5 ^ n + 2 := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    ring
