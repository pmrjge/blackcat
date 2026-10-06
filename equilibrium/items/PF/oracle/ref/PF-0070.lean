import Mathlib

theorem pf_0070 : ∀ n : ℤ, (66 : ℤ) ∣ n ^ 11 - n := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 11 - n) 66).mp
  push_cast
  generalize (n : ZMod 66) = u
  revert u
  decide +kernel
