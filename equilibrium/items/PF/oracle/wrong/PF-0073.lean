import Mathlib

theorem pf_0073 : ∀ n : ℤ, (2730 : ℤ) ∣ n ^ 13 - n := by
  have eq_gap : ∀ n : ℤ, (13 : ℤ) ∣ n ^ 12 - 1 := by
    intro n; omega
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 13 - n) 2730).mp
  push_cast
  generalize (n : ZMod 2730) = u
  revert u
  decide +kernel
