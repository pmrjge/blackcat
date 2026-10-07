import Mathlib

theorem pf_0064 : ∀ n : ℤ, (42 : ℤ) ∣ n ^ 7 - n := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 7 - n) 42).mp
  push_cast
  generalize (n : ZMod 42) = u
  revert u
  decide +kernel
