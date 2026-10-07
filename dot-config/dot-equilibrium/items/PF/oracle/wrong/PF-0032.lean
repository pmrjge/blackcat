import Mathlib

theorem pf_0032 : ∀ n : ℕ, Nat.gcd (10 * n + 2) (4 * n + 1) = 1 := by
  have eq_gap : ∀ n : ℤ, 4 * (10 * n + 2) - 10 * (4 * n + 1) = 1 := by
    intro n; ring
  intro n
  have h1 := Nat.gcd_dvd_left (10 * n + 2) (4 * n + 1)
  have h2 := Nat.gcd_dvd_right (10 * n + 2) (4 * n + 1)
  have h3 : Nat.gcd (10 * n + 2) (4 * n + 1) ∣ 5 * (4 * n + 1) - 2 * (10 * n + 2) := Nat.dvd_sub (Dvd.dvd.mul_left h2 5) (Dvd.dvd.mul_left h1 2)
  have e : 5 * (4 * n + 1) - 2 * (10 * n + 2) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
