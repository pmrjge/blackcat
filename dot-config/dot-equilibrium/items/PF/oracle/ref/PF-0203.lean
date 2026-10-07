import Mathlib

theorem pf_0203 : ∀ a : ℕ → ℚ, a 0 = 1 / 2 → (∀ n, a (n + 1) = a n / (1 + a n)) → ∀ n, a n = 1 / (n + 2) := by
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : ((k : ℚ) + 2) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
