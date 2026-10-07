import Mathlib

theorem pf_0045 : ∀ x y : ℤ, 2 * x ^ 2 + 3 * y ^ 2 ≠ 6 := by
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 9)) h
  push_cast at h'
  generalize (x : ZMod 9) = u at h'
  generalize (y : ZMod 9) = v at h'
  revert u v
  decide
