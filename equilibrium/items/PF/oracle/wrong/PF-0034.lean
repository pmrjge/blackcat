import Mathlib

theorem pf_0034 : ∀ n : ℕ, Nat.gcd (8 * n + 3) (5 * n + 2) = 1 := by
  have eq_gap : ∀ n : ℤ, 5 * (8 * n + 3) - 8 * (5 * n + 2) = 1 := by
    intro n; ring
  intro n
  have h1 := Nat.gcd_dvd_left (8 * n + 3) (5 * n + 2)
  have h2 := Nat.gcd_dvd_right (8 * n + 3) (5 * n + 2)
  have h3 : Nat.gcd (8 * n + 3) (5 * n + 2) ∣ 8 * (5 * n + 2) - 5 * (8 * n + 3) := Nat.dvd_sub (Dvd.dvd.mul_left h2 8) (Dvd.dvd.mul_left h1 5)
  have e : 8 * (5 * n + 2) - 5 * (8 * n + 3) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
