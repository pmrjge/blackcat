import Mathlib

theorem pf_0071 : ∀ n : ℤ, (66 : ℤ) ∣ n ^ 12 - n ^ 2 := by
  have eq_gap : ∀ n : ℤ, (11 : ℤ) ∣ n ^ 10 - 1 := by
    intro n; omega
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 12 - n ^ 2) 66).mp
  push_cast
  generalize (n : ZMod 66) = u
  revert u
  decide +kernel
