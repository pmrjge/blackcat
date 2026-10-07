import Mathlib

theorem pf_0204 : ∀ a : ℕ → ℚ, a 0 = 1 → (∀ n, a (n + 1) = a n / (1 + 2 * a n)) → ∀ n, a n = 1 / (2 * n + 1) := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : (2 * (k : ℚ) + 1) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
