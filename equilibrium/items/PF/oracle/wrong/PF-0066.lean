import Mathlib

theorem pf_0066 : ∀ n : ℤ, (42 : ℤ) ∣ n ^ 9 - n ^ 3 := by
  have eq_gap : ∀ n : ℤ, (7 : ℤ) ∣ n ^ 6 - 1 := by
    intro n; omega
  intro n
  apply (ZMod.intCast_zmod_eq_zero_iff_dvd (n ^ 9 - n ^ 3) 42).mp
  push_cast
  generalize (n : ZMod 42) = u
  revert u
  decide +kernel
