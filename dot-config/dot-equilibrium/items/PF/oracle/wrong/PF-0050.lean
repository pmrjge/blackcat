import Mathlib

theorem pf_0050 : ∀ x y : ℤ, x ^ 3 + y ^ 3 ≠ 3 := by
  have eq_gap : ∀ u v : ZMod 4, u ^ 3 + v ^ 3 ≠ 3 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 7)) h
  push_cast at h'
  generalize (x : ZMod 7) = u at h'
  generalize (y : ZMod 7) = v at h'
  revert u v
  decide
