import Mathlib

theorem pf_0009 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = -16 → (∀ n, f (n + 2) = f (n + 1) + 6 * f n) → ∀ n, f n = -2 * 3 ^ n + 5 * (-2) ^ n := by
  have eq_gap : (-16 : ℤ) - (-2) * 3 = 10 := by
    norm_num
  intro f h0 h1 hrec
  have key : ∀ n, f n = -2 * 3 ^ n + 5 * (-2) ^ n ∧ f (n + 1) = -2 * 3 ^ (n + 1) + 5 * (-2) ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
