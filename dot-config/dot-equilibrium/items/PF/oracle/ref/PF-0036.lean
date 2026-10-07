import Mathlib

theorem pf_0036 : ∀ n : ℕ, Nat.gcd (11 * n + 8) (4 * n + 3) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (11 * n + 8) (4 * n + 3)
  have h2 := Nat.gcd_dvd_right (11 * n + 8) (4 * n + 3)
  have h3 : Nat.gcd (11 * n + 8) (4 * n + 3) ∣ 11 * (4 * n + 3) - 4 * (11 * n + 8) := Nat.dvd_sub (Dvd.dvd.mul_left h2 11) (Dvd.dvd.mul_left h1 4)
  have e : 11 * (4 * n + 3) - 4 * (11 * n + 8) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
