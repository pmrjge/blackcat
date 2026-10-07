import Mathlib

theorem pf_0071 : ∀ n : ℤ, (66 : ℤ) ∣ n ^ 12 - n ^ 2 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 12 - n ^ 2) 66).mp
  push_cast
  generalize (n : ZMod 66) = u
  revert u
  decide +kernel
