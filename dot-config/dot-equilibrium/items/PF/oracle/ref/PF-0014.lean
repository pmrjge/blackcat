import Mathlib

theorem pf_0014 : ∀ f : ℕ → ℤ, f 0 = 3 → f 1 = 5 → (∀ n, f (n + 2) = f (n + 1) + 12 * f n) → ∀ n, f n = (-3) ^ n + 2 * 4 ^ n := by
  intro f h0 h1 hrec
  have key : ∀ n, f n = (-3) ^ n + 2 * 4 ^ n ∧ f (n + 1) = (-3) ^ (n + 1) + 2 * 4 ^ (n + 1) := by
    intro n
    induction n with
    | zero => exact ⟨by rw [h0]; norm_num, by rw [h1]; norm_num⟩
    | succ k ih =>
      refine ⟨ih.2, ?_⟩
      rw [hrec, ih.2, ih.1]
      ring
  exact fun n => (key n).1
