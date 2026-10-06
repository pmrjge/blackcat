import Mathlib

theorem pf_0065 : ∀ n : ℤ, (42 : ℤ) ∣ n ^ 8 - n ^ 2 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 8 - n ^ 2) 42).mp
  push_cast
  generalize (n : ZMod 42) = u
  revert u
  decide +kernel
