import Mathlib

theorem pf_0208 : ∀ a : ℕ → ℚ, a 0 = 1 / 2 → (∀ n, a (n + 1) = a n / (1 + 3 * a n)) → ∀ n, a n = 1 / (3 * n + 2) := by
  have eq_gap : ∀ x : ℚ, x / (1 + 3 * x) = x - 3 * x ^ 2 := by
    intro x; field_simp; ring
  intro a h0 hrec n
  induction n with
  | zero => rw [h0]; norm_num
  | succ k ih =>
    rw [hrec, ih]
    have hk : (3 * (k : ℚ) + 2) ≠ 0 := by positivity
    push_cast
    field_simp
    try ring
