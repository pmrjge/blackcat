import Mathlib

theorem pf_0041 : ∀ n : ℕ, Nat.gcd (25 * n + 2) (15 * n + 1) = 1 := by
  have eq_gap : ∀ n : ℤ, 15 * (25 * n + 2) - 25 * (15 * n + 1) = 1 := by
    intro n; ring
  intro n
  have h1 := Nat.gcd_dvd_left (25 * n + 2) (15 * n + 1)
  have h2 := Nat.gcd_dvd_right (25 * n + 2) (15 * n + 1)
  have h3 : Nat.gcd (25 * n + 2) (15 * n + 1) ∣ 3 * (25 * n + 2) - 5 * (15 * n + 1) := Nat.dvd_sub (Dvd.dvd.mul_left h1 3) (Dvd.dvd.mul_left h2 5)
  have e : 3 * (25 * n + 2) - 5 * (15 * n + 1) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
