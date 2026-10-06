import Mathlib

theorem pf_0052 : ∀ x y : ℤ, 2 * x ^ 3 - 5 * y ^ 3 ≠ 4 := by
  have eq_gap : ∀ u v : ZMod 4, 2 * u ^ 3 - 5 * v ^ 3 ≠ 4 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 8)) h
  push_cast at h'
  generalize (x : ZMod 8) = u at h'
  generalize (y : ZMod 8) = v at h'
  revert u v
  decide
