import Mathlib

theorem pf_0072 : ∀ n : ℤ, (66 : ℤ) ∣ n ^ 13 - n ^ 3 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 13 - n ^ 3) 66).mp
  push_cast
  generalize (n : ZMod 66) = u
  revert u
  decide +kernel
