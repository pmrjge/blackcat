import Mathlib

theorem pf_0048 : ∀ x y : ℤ, x ^ 2 + 5 * y ^ 2 ≠ 8 := by
  have eq_gap : ∀ u v : ZMod 4, u ^ 2 + 5 * v ^ 2 ≠ 8 := by
    decide
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 5)) h
  push_cast at h'
  generalize (x : ZMod 5) = u at h'
  generalize (y : ZMod 5) = v at h'
  revert u v
  decide
