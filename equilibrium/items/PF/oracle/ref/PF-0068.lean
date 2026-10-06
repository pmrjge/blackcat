import Mathlib

theorem pf_0068 : ∀ n : ℤ, (30 : ℤ) ∣ n ^ 10 - n ^ 2 := by
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 10 - n ^ 2) 30).mp
  push_cast
  generalize (n : ZMod 30) = u
  revert u
  decide +kernel
