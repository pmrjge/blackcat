import Mathlib

theorem pf_0012 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = -2 → (∀ n, f (n + 2) = 7 * f (n + 1) - 6 * f n) → ∀ n, f n = -6 ^ n + 4 * 1 ^ n := by
  have eq_gap : (-2 : ℤ) - 1 * 3 = 5 := by
    norm_num
  intro f h0 h1 hrec
  have key : ∀ n, f n = -6 ^ n + 4 * 1 ^ n ∧ f (n + 1) = -6 ^ (n + 1) + 4 * 1 ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
