import Mathlib

theorem pf_dev1 : ∀ n : ℕ, Nat.gcd (21 * n + 2) (14 * n + 1) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (21 * n + 2) (14 * n + 1)
  have h2 := Nat.gcd_dvd_right (21 * n + 2) (14 * n + 1)
  have h3 : Nat.gcd (21 * n + 2) (14 * n + 1) ∣ 2 * (21 * n + 2) - 3 * (14 * n + 1) := Nat.dvd_sub (Dvd.dvd.mul_left h1 2) (Dvd.dvd.mul_left h2 3)
  have e : 2 * (21 * n + 2) - 3 * (14 * n + 1) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
