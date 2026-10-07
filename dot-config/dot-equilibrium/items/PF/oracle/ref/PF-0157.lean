import Mathlib

theorem pf_0157 : ∀ f : ℤ → ℤ, (∀ x y, f (x + y) = f x + f y + 4 * x * y) → f 1 = 3 → ∀ n, 2 * f n = 4 * n * (n - 1) + 6 * n := by
  intro f hf h1
  have h0 : f 0 = 0 := by
    have := hf 0 0
    simp at this
    linarith
  intro n
  induction n using Int.induction_on with
  | zero => simp [h0]
  | succ k ih =>
    have := hf k 1
    linear_combination 2 * this + ih + 2 * h1
  | pred k ih =>
    have := hf (-(k : ℤ) - 1) 1
    simp only [sub_add_cancel] at this
    linear_combination -2 * this + ih - 2 * h1
