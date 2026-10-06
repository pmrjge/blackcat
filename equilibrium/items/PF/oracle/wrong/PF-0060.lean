import Mathlib

theorem pf_0060 : ∀ n : ℤ, (6 : ℤ) ∣ n ^ 5 - n ^ 3 := by
  have eq_gap : ∀ n : ℤ, (3 : ℤ) ∣ n ^ 2 - 1 := by
    intro n; omega
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 5 - n ^ 3) 6).mp
  push_cast
  generalize (n : ZMod 6) = u
  revert u
  decide +kernel
