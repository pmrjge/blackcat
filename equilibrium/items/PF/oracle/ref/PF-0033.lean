import Mathlib

theorem pf_0033 : ∀ n : ℕ, Nat.gcd (14 * n + 2) (6 * n + 1) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (14 * n + 2) (6 * n + 1)
  have h2 := Nat.gcd_dvd_right (14 * n + 2) (6 * n + 1)
  have h3 : Nat.gcd (14 * n + 2) (6 * n + 1) ∣ 7 * (6 * n + 1) - 3 * (14 * n + 2) := Nat.dvd_sub (Dvd.dvd.mul_left h2 7) (Dvd.dvd.mul_left h1 3)
  have e : 7 * (6 * n + 1) - 3 * (14 * n + 2) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
