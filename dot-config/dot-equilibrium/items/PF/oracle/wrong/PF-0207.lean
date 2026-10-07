import Mathlib

theorem pf_0207 : ∀ a : ℕ → ℚ, a 0 = 1 / 5 → (∀ n, a (n + 1) = a n / (1 + a n)) → ∀ n, a n = 1 / (n + 5) := by
  have eq_gap : ∀ x : ℚ, x / (1 + 1 * x) = x - 1 * x ^ 2 := by
    intro x; field_simp; ring
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : ((k : ℚ) + 5) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
