import Mathlib

theorem pf_0205 : ∀ a : ℕ → ℚ, a 0 = 1 / 3 → (∀ n, a (n + 1) = a n / (1 + 2 * a n)) → ∀ n, a n = 1 / (2 * n + 3) := by
  have eq_gap : ∀ x : ℚ, x / (1 + 2 * x) = x - 2 * x ^ 2 := by
    intro x; field_simp; ring
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : (2 * (k : ℚ) + 3) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
