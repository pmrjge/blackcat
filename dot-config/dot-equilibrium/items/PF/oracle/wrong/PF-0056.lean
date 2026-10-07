import Mathlib

theorem pf_0056 : ∀ x y : ℤ, x ^ 2 - 2 * y ^ 2 ≠ 3 := by
  have eq_gap : ∀ u v : ZMod 4, u ^ 2 - 2 * v ^ 2 ≠ 3 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 8)) h
  push_cast at h'
  generalize (x : ZMod 8) = u at h'
  generalize (y : ZMod 8) = v at h'
  revert u v
  decide
