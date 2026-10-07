import Mathlib

theorem pf_0059 : ∀ n : ℤ, (6 : ℤ) ∣ n ^ 4 - n ^ 2 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 4 - n ^ 2) 6).mp
  push_cast
  generalize (n : ZMod 6) = u
  revert u
  decide +kernel
