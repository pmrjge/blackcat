import Mathlib

theorem pf_0060 : ∀ n : ℤ, (6 : ℤ) ∣ n ^ 5 - n ^ 3 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 5 - n ^ 3) 6).mp
  push_cast
  generalize (n : ZMod 6) = u
  revert u
  decide +kernel
