import Mathlib

theorem pf_0206 : ∀ a : ℕ → ℚ, a 0 = 1 → (∀ n, a (n + 1) = a n / (1 + 3 * a n)) → ∀ n, a n = 1 / (3 * n + 1) := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : (3 * (k : ℚ) + 1) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
