import Mathlib

theorem pf_0069 : ∀ n : ℤ, (30 : ℤ) ∣ n ^ 11 - n ^ 3 := by
  have eq_gap : ∀ n : ℤ, (5 : ℤ) ∣ n ^ 4 - 1 := by
    intro n; omega
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 11 - n ^ 3) 30).mp
  push_cast
  generalize (n : ZMod 30) = u
  revert u
  decide +kernel
