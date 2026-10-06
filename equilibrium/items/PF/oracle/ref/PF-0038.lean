import Mathlib

theorem pf_0038 : ∀ n : ℕ, Nat.gcd (18 * n + 2) (12 * n + 1) = 1 := by
  intro n
  have h1 := Nat.gcd_dvd_left (18 * n + 2) (12 * n + 1)
  have h2 := Nat.gcd_dvd_right (18 * n + 2) (12 * n + 1)
  have h3 : Nat.gcd (18 * n + 2) (12 * n + 1) ∣ 2 * (18 * n + 2) - 3 * (12 * n + 1) := Nat.dvd_sub (Dvd.dvd.mul_left h1 2) (Dvd.dvd.mul_left h2 3)
  have e : 2 * (18 * n + 2) - 3 * (12 * n + 1) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
