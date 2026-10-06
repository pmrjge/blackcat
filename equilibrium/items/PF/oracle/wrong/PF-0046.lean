import Mathlib

theorem pf_0046 : ∀ x y : ℤ, x ^ 2 - 3 * y ^ 2 ≠ 10 := by
  have eq_gap : ∀ u v : ZMod 4, u ^ 2 - 3 * v ^ 2 ≠ 10 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 8)) h
  push_cast at h'
  generalize (x : ZMod 8) = u at h'
  generalize (y : ZMod 8) = v at h'
  revert u v
  decide
