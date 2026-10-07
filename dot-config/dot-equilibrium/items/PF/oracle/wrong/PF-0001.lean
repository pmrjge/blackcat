import Mathlib

theorem pf_0001 : ∀ f : ℕ → ℤ, f 0 = 2 → f 1 = 5 → (∀ n, f (n + 2) = 5 * f (n + 1) - 6 * f n) → ∀ n, f n = 2 ^ n + 3 ^ n := by
  have eq_gap : (5 : ℤ) - 3 * 2 = 1 := by
    norm_num
  intro f h0 h1 hrec
  have key : ∀ n, f n = 2 ^ n + 3 ^ n ∧ f (n + 1) = 2 ^ (n + 1) + 3 ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
