import Mathlib

theorem pf_0037 : ∀ n : ℕ, Nat.gcd (13 * n + 5) (5 * n + 2) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (13 * n + 5) (5 * n + 2)
  have h2 := Nat.gcd_dvd_right (13 * n + 5) (5 * n + 2)
  have h3 : Nat.gcd (13 * n + 5) (5 * n + 2) ∣ 13 * (5 * n + 2) - 5 * (13 * n + 5) := Nat.dvd_sub (Dvd.dvd.mul_left h2 13) (Dvd.dvd.mul_left h1 5)
  have e : 13 * (5 * n + 2) - 5 * (13 * n + 5) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
