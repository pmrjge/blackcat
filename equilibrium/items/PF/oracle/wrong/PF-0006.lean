import Mathlib

theorem pf_0006 : ∀ f : ℕ → ℤ, f 0 = 4 → f 1 = -1 → (∀ n, f (n + 2) = 3 * f (n + 1) + 10 * f n) → ∀ n, f n = 3 * (-2) ^ n + 5 ^ n := by
  have eq_gap : (-1 : ℤ) - 5 * 4 = 21 := by
    norm_num
  intro f h0 h1 hrec
  have key : ∀ n, f n = 3 * (-2) ^ n + 5 ^ n ∧ f (n + 1) = 3 * (-2) ^ (n + 1) + 5 ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
