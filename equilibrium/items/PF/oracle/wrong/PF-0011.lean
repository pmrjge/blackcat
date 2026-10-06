import Mathlib

theorem pf_0011 : ∀ f : ℕ → ℤ, f 0 = 2 → f 1 = 14 → (∀ n, f (n + 2) = 2 * f (n + 1) + 8 * f n) → ∀ n, f n = 3 * 4 ^ n - (-2) ^ n := by
  have eq_gap : (14 : ℤ) - (-2) * 2 = -18 := by
    norm_num
  intro f h0 h1 hrec
  have key : ∀ n, f n = 3 * 4 ^ n - (-2) ^ n ∧ f (n + 1) = 3 * 4 ^ (n + 1) - (-2) ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
