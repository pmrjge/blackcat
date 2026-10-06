import Mathlib

theorem pf_0039 : ∀ n : ℕ, Nat.gcd (20 * n + 3) (15 * n + 2) = 1 := by
  have eq_gap : ∀ n : ℤ, 15 * (20 * n + 3) - 20 * (15 * n + 2) = 1 := by
    intro n; ring
  intro n
  have h1 := Nat.gcd_dvd_left (20 * n + 3) (15 * n + 2)
  have h2 := Nat.gcd_dvd_right (20 * n + 3) (15 * n + 2)
  have h3 : Nat.gcd (20 * n + 3) (15 * n + 2) ∣ 3 * (20 * n + 3) - 4 * (15 * n + 2) := Nat.dvd_sub (Dvd.dvd.mul_left h1 3) (Dvd.dvd.mul_left h2 4)
  have e : 3 * (20 * n + 3) - 4 * (15 * n + 2) = 1 := by omega
  rw [e] at h3
  exact Nat.dvd_one.mp h3
