import Mathlib

theorem pf_0058 : ∀ n : ℤ, (6 : ℤ) ∣ n ^ 3 - n := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 3 - n) 6).mp
  push_cast
  generalize (n : ZMod 6) = u
  revert u
  decide +kernel
