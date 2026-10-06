import Mathlib

theorem pf_0054 : ∀ x y : ℤ, x ^ 4 + 3 * y ^ 4 ≠ 7 := by
  intro x y h
  have h' := congrArg (fun z : ℤ => (z : ZMod 5)) h
  push_cast at h'
  generalize (x : ZMod 5) = u at h'
  generalize (y : ZMod 5) = v at h'
  revert u v
  decide
