import Mathlib

theorem pf_0040 : ∀ n : ℕ, Nat.gcd (16 * n + 3) (10 * n + 2) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (16 * n + 3) (10 * n + 2)
  have h2 := Nat.gcd_dvd_right (16 * n + 3) (10 * n + 2)
  have h3 : Nat.gcd (16 * n + 3) (10 * n + 2) ∣ 8 * (10 * n + 2) - 5 * (16 * n + 3) := Nat.dvd_sub (Dvd.dvd.mul_left h2 8) (Dvd.dvd.mul_left h1 5)
  have e : 8 * (10 * n + 2) - 5 * (16 * n + 3) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
