import Mathlib

theorem pf_0055 : ∀ x y : ℤ, 2 * x ^ 4 + 5 * y ^ 4 ≠ 8 := by
  have eq_gap : ∀ u v : ZMod 4, 2 * u ^ 4 + 5 * v ^ 4 ≠ 8 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 5)) h
  push_cast at h'
  generalize (x : ZMod 5) = u at h'
  generalize (y : ZMod 5) = v at h'
  revert u v
  decide
