import Mathlib

theorem pf_0067 : ∀ n : ℤ, (30 : ℤ) ∣ n ^ 9 - n := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 9 - n) 30).mp
  push_cast
  generalize (n : ZMod 30) = u
  revert u
  decide +kernel
