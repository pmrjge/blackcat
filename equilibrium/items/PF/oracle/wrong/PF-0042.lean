import Mathlib

theorem pf_0042 : ∀ x y : ℤ, x ^ 2 + y ^ 2 ≠ 6 := by
  have eq_gap : ∀ u v : ZMod 4, u ^ 2 + v ^ 2 ≠ 6 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 8)) h
  push_cast at h'
  generalize (x : ZMod 8) = u at h'
  generalize (y : ZMod 8) = v at h'
  revert u v
  decide
