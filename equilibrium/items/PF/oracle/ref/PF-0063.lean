import Mathlib

theorem pf_0063 : ∀ n : ℤ, (30 : ℤ) ∣ n ^ 7 - n ^ 3 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 7 - n ^ 3) 30).mp
  push_cast
  generalize (n : ZMod 30) = u
  revert u
  decide +kernel
